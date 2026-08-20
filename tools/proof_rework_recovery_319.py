"""#319 P0 — stale rework transaction rollback + permanent-fence recovery proof.

Drives the REAL worker (`run_writers.run_rework_operation`) through a deterministic forced
interleaving — lease expiry, competing reclaim, stale generation completion, rejection — and proves
that a rejected completion commits NOTHING.

Why this exists: `complete_rework_operation()` rejects a stale claim_token with a plain Python raise,
which does NOT abort the SQL transaction. Before #319 the worker's handler then called
`fail_rework_operation()` on that SAME connection, whose unconditional `conn.commit()` durably
persisted the whole rejected generation. This proof snapshots every generation-touched table
immediately before the stale completion and asserts none of them moved.

Runs in-process against the isolated api_selftest DB/runtime. Stub writer only; no provider call.
"""
import os
import time
import threading

import psycopg2.extras

import gates.api_selftest as S
import gates.engine as E
import run_writers as RW

FAILS = []

# The worker resolves the engine through its own lazy import, which is a DIFFERENT module object from
# `gates.engine`. Fault injection must target the object the worker actually calls.
WENG = RW._load_engine()

# Every table the generation transaction touches between BEGIN and the commit it never reaches.
# `gate_decision` is included deliberately: the rework path DELETEs open-gate decisions inside the
# generation transaction, so a stale commit silently destroys reviewer decisions.
GEN_TABLES = ("topic", "slot", "gate_decision", "audit_log", "directive", "topic_provenance",
              "rework_operation")


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc, **attrs):
    try:
        fn()
    except exc as e:
        ok = all(getattr(e, k, None) == v for k, v in attrs.items())
        detail = " ".join(f"{k}={getattr(e, k, None)!r}" for k in attrs)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {type(e).__name__} {detail}")
        if not ok:
            FAILS.append(label)
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] {label}: wrong exception {type(e).__name__}: {e}")
        FAILS.append(label)
    else:
        print(f"  [FAIL] {label}: no exception raised")
        FAILS.append(label)


conn = S.db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def snapshot(slot_id):
    """A full-fidelity snapshot of every generation-touched table for one slot. Compared by VALUE, not
    by row count: a count-only check would pass while content silently changed underneath it."""
    snap = {}
    cur.execute("SELECT * FROM topic WHERE slot_id=%s ORDER BY revision", (slot_id,))
    snap["topic"] = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT slot_id, topic_angle, hook_text, hook_type, status, updated_at "
                "FROM slot WHERE slot_id=%s", (slot_id,))
    snap["slot"] = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM gate_decision WHERE slot_id=%s ORDER BY gate_id", (slot_id,))
    snap["gate_decision"] = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT id, action, actor, detail FROM audit_log "
                "WHERE entity='slot' AND entity_id=%s ORDER BY id", (slot_id,))
    snap["audit_log"] = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM directive WHERE slot_id=%s ORDER BY directive_id", (slot_id,))
    snap["directive"] = [dict(r) for r in cur.fetchall()]
    # topic_provenance keys on topic_id, not slot_id — join so the snapshot follows the slot's rows.
    cur.execute("""SELECT p.* FROM topic_provenance p JOIN topic t USING (topic_id)
                    WHERE t.slot_id=%s ORDER BY p.provenance_id""", (slot_id,))
    snap["topic_provenance"] = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM rework_operation WHERE slot_id=%s ORDER BY op_id", (slot_id,))
    snap["rework_operation"] = [dict(r) for r in cur.fetchall()]
    conn.commit()                       # end the read txn so the next snapshot sees fresh commits
    return snap


def diff_tables(before, after):
    """The tables whose committed content differs. Empty == nothing was persisted."""
    return [t for t in GEN_TABLES if before[t] != after[t]]


# --------------------------------------------------------------------------- #
# Seed a completed automatic Stage 2A topic round over HTTP (the canonical path)
# --------------------------------------------------------------------------- #
elig = [e["name"] for e in S.GET("/baseline-eligibility")["eligible"]]
mix = {n: 0 for n in elig}
mix[elig[0]] = 2
_, rb = S.POST("/rounds", {"days": 1, "posts_per_day": 2, "label": "#319 rollback proof",
                           "format_mix": mix})
rid = rb["round_id"]
_, g = S.POST("/gates", {"stage": "schedule_review", "round_id": rid}, headers=S.AUTH_KHAL)
S.POST(f"/gates/{g['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"},
       headers=S.AUTH_KHAL)
S.POST(f"/gates/{g['gate_id']}/resolve", {}, headers=S.AUTH_KHAL)
for _ in range(120):
    m = S.GET(f"/rounds/{rid}/generation")
    if m["phase"] in ("completed", "failed", "partial"):
        break
    time.sleep(0.5)

cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED' ORDER BY slot_id",
            (rid,))
_slots = [r["slot_id"] for r in cur.fetchall()]
conn.commit()
slot_id, slot2 = _slots[0], _slots[1]
cfg = E.load_config()

os.environ["TANAGHOM_WRITER_STUB"] = "1"

print("\n#319 §1 — DEFECT: a stale worker's rejected completion must commit NOTHING")
print("  forced interleaving: claim -> lease expiry -> competing reclaim -> stale completion\n")

# LEASE shorter than the generation DELAY: worker A's lease provably expires mid-generation.
# The heartbeat interval is pushed BEYOND the generation, so the beat never renews — modelling the
# real hazard #313 P1-1 leaves open: a worker whose heartbeat is stalled or partitioned while its
# generation keeps running. Without this the beat correctly renews the lease and no reclaim can win —
# the fence works; the defect is what happens AFTER a reclaim legitimately wins.
os.environ["TANAGHOM_REWORK_LEASE_SECONDS"] = "2"
os.environ["TANAGHOM_REWORK_HEARTBEAT_SECONDS"] = "999"
os.environ["TANAGHOM_REWORK_TEST_DELAY_SECONDS"] = "8"

began = E.begin_rework_operation(conn, slot_id, 1, "#319 stale-worker rework", "khal",
                                 "IDEM-319-STALE", artifact="topic", cfg=cfg)
op_id = began["op_id"]
restored = began["restored_revision"]
check("§1 setup: operation created with a restored source revision", began["action"], "start")

# Seed a REAL open-gate decision on the stale-worker slot. The rework path DELETEs open topic_review
# decisions inside the generation transaction (run_writers `_clear_open_gate_decisions_after_rework`,
# fired because a rework carries feedback). This is the exact destructive consequence #318 leaves out:
# a stale commit silently erases a reviewer's recorded decision. An empty-before/empty-after fixture
# could never detect it — so we make it NON-EMPTY. Post-fix the rollback must preserve this row;
# pre-fix the stale commit must delete it. It does NOT block the rework: the mutation guard keys on
# slot_approval + downstream script, not on a topic_review gate_decision.
_gate_stage, _ = RW._gate_for_rework(cfg, "topic")
cur.execute("""INSERT INTO gate (gate_id, scope, stage, policy, rule_key, quorum, status)
               VALUES (gen_random_uuid(),'item',%s,'fixed','any','1','open') RETURNING gate_id""",
            (_gate_stage,))
_seeded_gate_id = cur.fetchone()["gate_id"]
cur.execute("""INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision, notes, decided_at)
               VALUES (%s,%s,'khal','request_change','#319 reviewer decision that must survive',
                       now())""", (_seeded_gate_id, slot_id))
conn.commit()
cur.execute("""SELECT count(*) AS n FROM gate_decision gd JOIN gate g USING (gate_id)
                WHERE gd.slot_id=%s AND g.stage=%s AND g.status='open'""", (slot_id, _gate_stage))
check("§1 setup: a REAL open-gate reviewer decision exists on the stale-worker slot",
      cur.fetchone()["n"], 1)
conn.commit()

worker_a = {}


def _drive_a():
    try:
        worker_a["result"] = RW.run_rework_operation(cfg, op_id)
    except Exception as e:                       # noqa: BLE001 — the stale rejection is EXPECTED
        worker_a["error"] = e


ta = threading.Thread(target=_drive_a, daemon=True)
ta.start()

# Wait until worker A has claimed and is inside its (over-long) generation.
for _ in range(100):
    cur.execute("SELECT state, claim_token FROM rework_operation WHERE op_id=%s", (op_id,))
    _r = cur.fetchone()
    conn.commit()
    if _r["state"] == "running" and _r["claim_token"]:
        break
    time.sleep(0.1)
token_a = _r["claim_token"]
check("§1 worker A claimed the operation (token minted)", _r["state"], "running")

# Let A's 2s lease expire while it is still generating, then a COMPETING worker reclaims it —
# the real engine claim, minting a new token and stripping A's ownership.
time.sleep(3.5)
reclaimed = E.claim_rework_operation(conn, op_id)
check("§1 competing reclaim succeeded after lease expiry", reclaimed is not None, True)
token_b = reclaimed["claim_token"]
check("§1 reclaim minted a NEW claim_token (A's ownership is gone)", token_b != token_a, True)

# CHECKPOINT BASELINE — captured after the reclaim and before A's completion attempt. A's generation
# writes are uncommitted and therefore invisible here, so this is exactly the committed state
# immediately before the stale completion.
before = snapshot(slot_id)
check("§1 baseline: head is still the restored source (no generation committed yet)",
      [r["revision"] for r in before["topic"]][-1], restored)

ta.join(timeout=60)
check("§1 stale worker A raised instead of completing", "error" in worker_a, True)
check("§1 the raise is the ownership fence rejecting it",
      "ownership lost" in str(worker_a.get("error", "")), True)

# ---- CHECKPOINT A: immediately after stale rejection + rollback ----
after_a = snapshot(slot_id)
drift_a = diff_tables(before, after_a)
print("\n  -- CHECKPOINT A (post-rejection/rollback): every generation-touched table --")
for t in GEN_TABLES:
    print(f"     {'UNCHANGED' if before[t] == after_a[t] else 'CHANGED  '}  {t}")
check("§1 CHECKPOINT A: ALL generation-touched tables unchanged after stale rejection", drift_a, [])
check("§1 CHECKPOINT A: no topic revision persisted by the stale worker",
      [r["revision"] for r in after_a["topic"]], [r["revision"] for r in before["topic"]])
check("§1 CHECKPOINT A: no provenance persisted by the stale worker",
      len(after_a["topic_provenance"]), len(before["topic_provenance"]))
check("§1 CHECKPOINT A: operation NOT marked completed by the stale worker",
      [r["state"] for r in after_a["rework_operation"]], ["running"])
check("§1 CHECKPOINT A: generated_revision still NULL",
      [r["generated_revision"] for r in after_a["rework_operation"]], [None])
# The destructive path #318 omits: the reviewer's open-gate decision must SURVIVE the stale rejection.
check("§1 CHECKPOINT A: the seeded reviewer gate_decision SURVIVES (not silently deleted)",
      [(r["gate_id"], r["decision"]) for r in after_a["gate_decision"]],
      [(r["gate_id"], r["decision"]) for r in before["gate_decision"]])
check("§1 CHECKPOINT A: the seeded topic_review decision is among the survivors",
      str(_seeded_gate_id) in [str(r["gate_id"]) for r in after_a["gate_decision"]], True)

# ---- CHECKPOINT B: after the worker's clean failure recording ----
# A stale worker's fenced failure write matches ZERO rows. Recording NOTHING is the TRUTHFUL outcome:
# A no longer owns the operation, and a loser must not overwrite the real owner's state. The allowed
# delta for the stale path is therefore empty — and, critically, still no generation effect.
after_b = snapshot(slot_id)
drift_b = diff_tables(before, after_b)
check("§1 CHECKPOINT B: stale failure recording truthfully no-ops (fenced, zero rows)", drift_b, [])
check("§1 CHECKPOINT B: still no generation effect committed",
      [t for t in drift_b if t != "rework_operation"], [])
check("§1 CHECKPOINT B: the reviewer gate_decision still survives after clean failure recording",
      str(_seeded_gate_id) in [str(r["gate_id"]) for r in after_b["gate_decision"]], True)

print("\n#319 §2 — ACCEPTANCE 4/5: competing ownership -> exactly ONE revision, fence released")
os.environ["TANAGHOM_REWORK_TEST_DELAY_SECONDS"] = "0"
time.sleep(2.5)                                  # let the reclaimer's lease lapse so a worker may claim
w = RW.run_rework_operation(cfg, op_id)
check("§2 the reclaimed winner completed", bool(w), True)
cur.execute("SELECT revision FROM topic WHERE slot_id=%s ORDER BY revision", (slot_id,))
revs = [r["revision"] for r in cur.fetchall()]
cur.execute("""SELECT count(*) AS n FROM topic_provenance p JOIN topic t USING (topic_id)
                WHERE t.slot_id=%s AND t.revision > %s""", (slot_id, restored))
nprov = cur.fetchone()["n"]
cur.execute("SELECT state, generated_revision FROM rework_operation WHERE op_id=%s", (op_id,))
opw = cur.fetchone()
conn.commit()
check("§2 exactly ONE generated revision above the restored source (no duplicate from the loser)",
      [r for r in revs if r > restored], [restored + 1])
check("§2 exactly ONE truthful provenance record for this rework", nprov, 1)
check("§2 operation completed with its generated revision", opw["state"], "completed")
check("§2 generated_revision matches the durable head", opw["generated_revision"], restored + 1)
# ACCEPTANCE 5 — a NORMAL reclaimed-winner completion clears the fence with NO terminalization.
E._topic_item_mutation_eligibility(cur, slot_id, "topic")   # raises GovernedDenial if still fenced
conn.commit()
print("  [PASS] §2 fence released by normal completion — terminalization NOT needed")

print("\n#319 §3 — ACCEPTANCE 2: a clean failure records state but commits NO generation effect")
# Fault-inject INSIDE the generation transaction, AFTER the topic rows are written, with the worker's
# token still VALID. This is the owner-failure path: it must roll back the generation and still record
# the failure — proving failure-state recording cannot smuggle generation effects through.
began3 = E.begin_rework_operation(conn, slot2, 1, "#319 owner-failure rework", "khal",
                                  "IDEM-319-OWNERFAIL", artifact="topic", cfg=cfg)
op3 = began3["op_id"]
before3 = snapshot(slot2)
_real_prov = WENG.record_rework_provenance


def _boom(*a, **k):
    raise RuntimeError("#319 injected fault after the topic rows were written")


WENG.record_rework_provenance = _boom
try:
    raises("§3 owner's generation failed as injected",
           lambda: RW.run_rework_operation(cfg, op3), RuntimeError)
finally:
    WENG.record_rework_provenance = _real_prov

after3 = snapshot(slot2)
drift3 = diff_tables(before3, after3)
check("§3 ONLY rework_operation changed — every generation effect rolled back",
      drift3, ["rework_operation"])
check("§3 no topic revision committed by the failed generation",
      after3["topic"] == before3["topic"], True)
check("§3 no provenance committed by the failed generation",
      after3["topic_provenance"] == before3["topic_provenance"], True)
check("§3 slot NOT advanced by the failed generation", after3["slot"] == before3["slot"], True)
check("§3 gate_decision rows NOT destroyed by the failed generation",
      after3["gate_decision"] == before3["gate_decision"], True)
cur.execute("SELECT state, error_detail, generated_revision FROM rework_operation WHERE op_id=%s",
            (op3,))
f3 = cur.fetchone()
conn.commit()
# The ENUMERATED allowed delta, split by cause. The baseline predates the worker's claim, so the
# operation row legitimately carries this tenure's claim fields as well as the failure record.
# Nothing outside these two sets may move — and no generation effect appears in either.
_allowed_failure = {"state", "error_detail", "updated_at"}            # the clean failure record
_allowed_claim = {"claim_token", "lease_expires_at", "heartbeat_at"}  # the legitimate claim's tenure
_changed = {k for k in before3["rework_operation"][0]
            if before3["rework_operation"][0][k] != after3["rework_operation"][0][k]}
check("§3 delta touches NOTHING beyond the enumerated claim-tenure + failure fields",
      sorted(_changed - (_allowed_failure | _allowed_claim)), [])
check("§3 the failure record wrote exactly the enumerated failure fields",
      sorted(_changed & _allowed_failure), ["error_detail", "state", "updated_at"])
check("§3 operation is failed (resumable)", f3["state"], "failed")
check("§3 failure claims no revision it did not produce", f3["generated_revision"], None)
check("§3 failure detail is truthful (the injected cause)",
      "#319 injected fault" in (f3["error_detail"] or ""), True)

print("\n#319 §4 — the PERMANENT FENCE and its governed escape (terminalization)")
# Construct the stranded state the defect produces in the field: a failed operation whose restored
# source is NO LONGER head, so the worker's fail-closed source check rejects every recovery attempt
# forever. (At 78e7ea3 this arises from the stale commit itself; here it is set up directly, since
# post-fix no stale commit can create it.)
cur.execute("""INSERT INTO topic (slot_id, hcs_id, lens, round_id, cycle_no, text_ar, hook_text,
                                  hook_type, revision)
               SELECT slot_id, hcs_id, lens, round_id, cycle_no, text_ar, hook_text, hook_type,
                      (SELECT max(revision)+1 FROM topic WHERE slot_id=%s)
                 FROM topic WHERE slot_id=%s ORDER BY revision DESC LIMIT 1""", (slot2, slot2))
cur.execute("UPDATE rework_operation SET state='failed', lease_expires_at=now() - interval '1 hour' "
            "WHERE op_id=%s", (op3,))
conn.commit()

st = E.stranded_rework_operation(conn, op3)
check("§4 the stranded operation is terminalization-eligible", st["terminalization_eligible"], True)
check("§4 stranded because restored source is no longer head",
      st["head_revision"] != st["restored_revision"], True)
raises("§4 the item is PERMANENTLY fenced — no governed escape without terminalization",
       lambda: E._topic_item_mutation_eligibility(cur, slot2, "topic"), E.GovernedDenial,
       reason="rework_active")
conn.rollback()

tok = st["expected_op_token"]

# --- authorization: explicit workflow.admin ONLY ---
# DEDICATED principals. The seeded `khal`/`huda` are deliberately NOT mutated: overwriting a shared
# principal's permissions leaks out of this proof and silently breaks every later authorization check
# in the gate — a contaminated fixture that would make unrelated suites lie.
# `p319.noauth` deliberately holds the NEAR MISSES (workflow.assign, config.write, policy.admin) and
# the admin-sounding role names, proving authority comes from the explicit workflow.admin permission
# alone — never from a role name or a neighbouring permission.
cur.execute("""INSERT INTO principal (principal_id, kind, role, permissions, active)
               VALUES ('p319.admin','user','workflow_admin',%s,true),
                      ('p319.noauth','user','admin',%s,true)
               ON CONFLICT (principal_id) DO UPDATE
                  SET permissions=EXCLUDED.permissions, role=EXCLUDED.role, active=true""",
            (psycopg2.extras.Json(["workflow.admin"]),
             psycopg2.extras.Json(["workflow.assign", "config.write", "policy.admin"])))
conn.commit()
raises("§4 AUTHORIZATION: workflow.assign/config.write/policy.admin + an 'admin' role name do NOT "
       "confer terminalization (no broadening)",
       lambda: E.terminalize_rework_operation(conn, op3, "p319.noauth", tok, "T1",
                                              "unsafely stranded"),
       E.GovernedDenial, reason="unauthorized")
raises("§4 AUTHORIZATION: an unknown principal is denied (fail-closed)",
       lambda: E.terminalize_rework_operation(conn, op3, "p319.ghost", tok, "T1b",
                                              "unsafely stranded"),
       E.GovernedDenial, reason="unauthorized")
check("§4 the denied attempt did NOT release the fence",
      E.stranded_rework_operation(conn, op3)["state"], "failed")
cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='rework_operation' AND entity_id=%s "
            "AND action='rework_terminalization_denied'", (op3,))
check("§4 the denial is durably audited", cur.fetchone()["n"] >= 1, True)
conn.commit()

# --- stale expected-token rejection ---
raises("§4 STALE TOKEN: a request formed against a stale operation view is rejected",
       lambda: E.terminalize_rework_operation(conn, op3, "p319.admin", "deadbeef" * 4, "T2",
                                              "unsafely stranded"),
       E.GovernedDenial, reason="stale_token")

# --- active/recoverable denial ---
cur.execute("UPDATE rework_operation SET state='running', "
            "lease_expires_at=now() + interval '1 hour' WHERE op_id=%s", (op3,))
conn.commit()
_live = E.stranded_rework_operation(conn, op3)
check("§4 a live-lease operation is NOT eligible", _live["terminalization_eligible"], False)
raises("§4 ACTIVE OWNER: a running operation under a live lease is denied",
       lambda: E.terminalize_rework_operation(conn, op3, "p319.admin", _live["expected_op_token"], "T3",
                                              "unsafely stranded"),
       E.GovernedDenial, reason="active_owner")
cur.execute("UPDATE rework_operation SET state='queued', lease_expires_at=NULL WHERE op_id=%s",
            (op3,))
conn.commit()
_q = E.stranded_rework_operation(conn, op3)
raises("§4 RECOVERABLE: a queued operation recovery can re-drive is denied",
       lambda: E.terminalize_rework_operation(conn, op3, "p319.admin", _q["expected_op_token"], "T4",
                                              "unsafely stranded"),
       E.GovernedDenial, reason="recoverable")
cur.execute("UPDATE rework_operation SET state='failed', "
            "lease_expires_at=now() - interval '1 hour' WHERE op_id=%s", (op3,))
conn.commit()

# --- the bounded terminal transition ---
before4 = snapshot(slot2)
st2 = E.stranded_rework_operation(conn, op3)
res = E.terminalize_rework_operation(conn, op3, "p319.admin", st2["expected_op_token"], "T-OK",
                                     "worker stranded: restored source is no longer head")
check("§4 TERMINALIZED to the one allowed terminal state", res["state"], "terminated")
check("§4 terminalization reports no idempotent replay", res["idempotent_replay"], False)
after4 = snapshot(slot2)
# The snapshot's audit scope is the SLOT's audit trail — the generation footprint. Terminalization's
# own audit row is entity='rework_operation' and is asserted separately below, so within the
# generation footprint the ONLY table terminalization may move is the operation row itself.
check("§4 EFFECTS BOUNDED: within the generation footprint, ONLY rework_operation changed",
      sorted(diff_tables(before4, after4)), ["rework_operation"])
check("§4 terminalization appended NO slot-scoped audit (it claims no generation effect)",
      after4["audit_log"] == before4["audit_log"], True)
check("§4 terminalization created NO topic revision", after4["topic"] == before4["topic"], True)
check("§4 terminalization altered NO provenance",
      after4["topic_provenance"] == before4["topic_provenance"], True)
check("§4 terminalization did NOT mutate the slot", after4["slot"] == before4["slot"], True)
check("§4 terminalization did NOT touch approval/downstream state (gate_decision)",
      after4["gate_decision"] == before4["gate_decision"], True)
cur.execute("SELECT generated_revision FROM rework_operation WHERE op_id=%s", (op3,))
check("§4 terminalization SELECTED no revision (generated_revision still NULL)",
      cur.fetchone()["generated_revision"], None)
conn.commit()

# --- the fence is released, bounded to this operation ---
E._topic_item_mutation_eligibility(cur, slot2, "topic")      # raises if still fenced
conn.commit()
print("  [PASS] §4 FENCE RELEASED — the permanently-fenced item is governable again")

# --- immutable, truthful audit evidence ---
cur.execute("""SELECT actor, detail FROM audit_log WHERE entity='rework_operation' AND entity_id=%s
                 AND action='rework_operation_terminated' ORDER BY id""", (op3,))
arows = cur.fetchall()
conn.commit()
check("§4 exactly ONE terminalization audit row", len(arows), 1)
_d = arows[0]["detail"]
check("§4 audit records the actor", arows[0]["actor"], "p319.admin")
check("§4 audit records the authority it acted under", _d["authority"], "workflow.admin")
check("§4 audit records the reason", "restored source is no longer head" in _d["reason"], True)
check("§4 audit records the released fence", _d["fence_released"], "rework_active")
check("§4 audit truthfully claims NO revision", _d["generated_revision"], None)
check("§4 audit records that it confers NO #249 reconsideration", _d["confers_reconsideration"],
      False)

# --- idempotent replay + different-key denial ---
rep = E.terminalize_rework_operation(conn, op3, "p319.admin", st2["expected_op_token"], "T-OK",
                                     "worker stranded: restored source is no longer head")
check("§4 IDEMPOTENT REPLAY: same key returns the original terminal result", rep["state"],
      "terminated")
check("§4 replay is flagged as a replay", rep["idempotent_replay"], True)
cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='rework_operation' AND entity_id=%s "
            "AND action='rework_operation_terminated'", (op3,))
check("§4 replay appended NO second audit row (history immutable)", cur.fetchone()["n"], 1)
conn.commit()
after5 = snapshot(slot2)
check("§4 replay mutated NOTHING", diff_tables(after4, after5), [])
raises("§4 a DIFFERENT key against a terminal operation is a typed denial, not a silent replay",
       lambda: E.terminalize_rework_operation(conn, op3, "p319.admin", st2["expected_op_token"], "T-OTHER",
                                              "second actor"),
       E.GovernedDenial)

# --- terminal is terminal: recovery and stragglers cannot resurrect it ---
check("§4 a terminalized operation is NOT recoverable (never re-driven)",
      op3 in E.recoverable_rework_operations(conn), False)
check("§4 a terminalized operation cannot be claimed", E.claim_rework_operation(conn, op3), None)
check("§4 a straggler worker cannot flip it back to failed (which would re-raise the fence)",
      E.fail_rework_operation(conn, op3, str(st2.get("claim_token") or op3), "straggler"), False)
cur.execute("SELECT state FROM rework_operation WHERE op_id=%s", (op3,))
check("§4 the operation is still terminal after the straggler", cur.fetchone()["state"],
      "terminated")
conn.commit()

print("\n#319 §5 — CONCURRENCY: audit-backed idempotency under a same-key race")
# Ruling 2's condition: eligibility, token validation, idempotency lookup, transition, and audit are
# serialized under ONE lock. Racing the SAME key from N threads must yield exactly ONE transition and
# exactly ONE audit row — the losers must observe the receipt, not append a second one.
began5 = E.begin_rework_operation(conn, slot_id, 1, "#319 concurrency", "khal", "IDEM-319-CONC",
                                  artifact="topic", cfg=cfg)
op5 = began5["op_id"]
cur.execute("""INSERT INTO topic (slot_id, hcs_id, lens, round_id, cycle_no, text_ar, hook_text,
                                  hook_type, revision)
               SELECT slot_id, hcs_id, lens, round_id, cycle_no, text_ar, hook_text, hook_type,
                      (SELECT max(revision)+1 FROM topic WHERE slot_id=%s)
                 FROM topic WHERE slot_id=%s ORDER BY revision DESC LIMIT 1""", (slot_id, slot_id))
cur.execute("UPDATE rework_operation SET state='failed', "
            "lease_expires_at=now() - interval '1 hour' WHERE op_id=%s", (op5,))
conn.commit()
st5 = E.stranded_rework_operation(conn, op5)
check("§5 the concurrency subject is stranded/eligible", st5["terminalization_eligible"], True)

_barrier = threading.Barrier(6)
_out = []


def _race():
    c = S.db()
    try:
        _barrier.wait()
        _out.append(("ok", E.terminalize_rework_operation(
            c, op5, "p319.admin", st5["expected_op_token"], "T-RACE", "concurrent terminalization")))
    except Exception as e:                       # noqa: BLE001
        _out.append(("err", type(e).__name__, getattr(e, "reason", None)))
    finally:
        c.close()


threads = [threading.Thread(target=_race) for _ in range(6)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=30)

_oks = [o for o in _out if o[0] == "ok"]
_firsts = [o for o in _oks if o[1].get("idempotent_replay") is False]
_replays = [o for o in _oks if o[1].get("idempotent_replay") is True]
check("§5 every racing same-key request succeeded (none errored)", len(_oks), 6)
check("§5 EXACTLY ONE performed the transition", len(_firsts), 1)
check("§5 the other five observed the receipt as replays", len(_replays), 5)
cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='rework_operation' AND entity_id=%s "
            "AND action='rework_operation_terminated'", (op5,))
check("§5 EXACTLY ONE audit row despite the 6-way race (append-only receipt is the idempotency "
      "record)", cur.fetchone()["n"], 1)
cur.execute("SELECT state FROM rework_operation WHERE op_id=%s", (op5,))
check("§5 exactly one terminal state", cur.fetchone()["state"], "terminated")
conn.commit()

print("\n#319 §6 — terminalization confers NO #249 reconsideration authority")
# Releasing the fence returns the item to the SAME governed state it would have had if the rework had
# never started. An approved item must still be denied by its own #249 guard.
cur.execute("SELECT max(revision) AS h FROM topic WHERE slot_id=%s", (slot2,))
_h = cur.fetchone()["h"]
E._record_approval(cur, slot2, "topic", _h, "khal")
conn.commit()
raises("§6 an approved item stays #249-denied after terminalization (no reconsideration granted)",
       lambda: E.edit_revision(conn, slot2, "topic", "text_ar", "x", actor="khal"),
       E.GovernedDenial, reason="approved")
cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot2,))
conn.commit()

print("\n#319 §7 — LIVE HTTP CONTRACT: signed-principal boundary, typed mapping, token round trip")
# Everything above exercises the engine directly. This section drives the ACTUAL FastAPI routes over
# HTTP so signed-principal resolution, authority enforcement, HTTP status/typed-reason mapping, body
# validation, actor mismatch, and the real read->write TOKEN ROUND TRIP are all proven end to end.
AUTH_ADMIN = S._signed("p319.admin")      # holds workflow.admin
AUTH_NOAUTH = S._signed("p319.noauth")    # holds workflow.assign+config.write+policy.admin + 'admin' role


def _err(body):
    """Unwrap a FastAPI typed-error body ({"detail": {...}}) to the inner {error, reason, ...}."""
    d = body.get("detail") if isinstance(body, dict) else None
    return d if isinstance(d, dict) else (body if isinstance(body, dict) else {})


def _term_url(op):
    return f"/rework_operations/{op}/terminalize"


# A fresh, unsafely-stranded op on slot_id (op5 there is terminated; the fence is released).
began7 = E.begin_rework_operation(conn, slot_id, 1, "#319 http contract", "khal", "IDEM-319-HTTP",
                                  artifact="topic", cfg=cfg)
op7 = began7["op_id"]
cur.execute("""INSERT INTO topic (slot_id, hcs_id, lens, round_id, cycle_no, text_ar, hook_text,
                                  hook_type, revision)
               SELECT slot_id, hcs_id, lens, round_id, cycle_no, text_ar, hook_text, hook_type,
                      (SELECT max(revision)+1 FROM topic WHERE slot_id=%s)
                 FROM topic WHERE slot_id=%s ORDER BY revision DESC LIMIT 1""", (slot_id, slot_id))
cur.execute("UPDATE rework_operation SET state='failed', "
            "lease_expires_at=now() - interval '1 hour' WHERE op_id=%s", (op7,))
conn.commit()

# --- READ boundary: fail-closed, workflow.admin only ---
st_r_unsigned, _ = S._req("GET", f"/rework_operations/{op7}")
check("§7 READ unsigned -> 401 (fail-closed, matches sibling governance reads)", st_r_unsigned, 401)
st_r_noauth, b_r_noauth = S._req("GET", f"/rework_operations/{op7}", headers=AUTH_NOAUTH)
check("§7 READ signed WITHOUT workflow.admin -> 403 (no role/near-permission fallback)",
      (st_r_noauth, _err(b_r_noauth).get("reason")), (403, "unauthorized"))
st_r_ok, b_r_ok = S._req("GET", f"/rework_operations/{op7}", headers=AUTH_ADMIN)
check("§7 READ authorized -> 200", st_r_ok, 200)
check("§7 READ exposes strandedness + the canonical token",
      (b_r_ok["terminalization_eligible"], bool(b_r_ok["expected_op_token"])), (True, True))
http_token = b_r_ok["expected_op_token"]     # the token as the GOVERNED READ minted it

# --- WRITE boundary ---
st_w_unsigned, _ = S._req("POST", _term_url(op7),
                          {"expected_op_token": http_token, "idempotency_key": "H1",
                           "reason": "unsafely stranded"})
check("§7 WRITE unsigned -> 401", st_w_unsigned, 401)
st_w_noauth, b_w_noauth = S._req("POST", _term_url(op7),
                                 {"expected_op_token": http_token, "idempotency_key": "H1",
                                  "reason": "x"}, headers=AUTH_NOAUTH)
check("§7 WRITE signed WITHOUT workflow.admin -> 409 governed_denial unauthorized (audited in-engine)",
      (st_w_noauth, _err(b_w_noauth).get("reason")), (409, "unauthorized"))
st_w_missing, _ = S._req("POST", _term_url(op7),
                         {"expected_op_token": http_token, "idempotency_key": "H1"},
                         headers=AUTH_ADMIN)
check("§7 WRITE body validation: missing reason -> 4xx", st_w_missing in (400, 422), True)
st_w_mismatch, _ = S._req("POST", _term_url(op7),
                          {"expected_op_token": http_token, "idempotency_key": "H1",
                           "reason": "x", "actor": "someone_else"}, headers=AUTH_ADMIN)
check("§7 WRITE actor mismatch (body actor != signed principal) -> 400", st_w_mismatch, 400)
st_w_stale, b_w_stale = S._req("POST", _term_url(op7),
                               {"expected_op_token": "deadbeef" * 4, "idempotency_key": "H1",
                                "reason": "x"}, headers=AUTH_ADMIN)
check("§7 WRITE stale token -> 409 stale_token",
      (st_w_stale, _err(b_w_stale).get("reason")), (409, "stale_token"))
# The real round trip: terminalize with the token the READ route minted.
st_w_ok, b_w_ok = S._req("POST", _term_url(op7),
                         {"expected_op_token": http_token, "idempotency_key": "H1",
                          "reason": "unsafely stranded — terminalized over HTTP"}, headers=AUTH_ADMIN)
check("§7 WRITE authorized, token read->write ROUND TRIP -> 200 terminated",
      (st_w_ok, b_w_ok.get("state"), b_w_ok.get("idempotent_replay")), (200, "terminated", False))
st_w_rep, b_w_rep = S._req("POST", _term_url(op7),
                           {"expected_op_token": http_token, "idempotency_key": "H1",
                            "reason": "unsafely stranded — terminalized over HTTP"},
                           headers=AUTH_ADMIN)
check("§7 WRITE idempotent replay (same key) -> 200, flagged replay",
      (st_w_rep, b_w_rep.get("idempotent_replay")), (200, True))
st_w_diff, b_w_diff = S._req("POST", _term_url(op7),
                             {"expected_op_token": http_token, "idempotency_key": "H2",
                              "reason": "second actor"}, headers=AUTH_ADMIN)
check("§7 WRITE different key on a terminal op -> 409 governed_denial (not a silent replay)",
      (st_w_diff, _err(b_w_diff).get("reason")), (409, "already_terminalized"))
# HTTP active/recoverable denial (the eligibility gate, over the wire).
began7b = E.begin_rework_operation(conn, slot2, 1, "#319 http recoverable", "khal",
                                   "IDEM-319-HTTP-REC", artifact="topic", cfg=cfg)
op7b = began7b["op_id"]        # queued + recoverable: NOT stranded
conn.commit()
b_r_rec = S.GET(f"/rework_operations/{op7b}", headers=AUTH_ADMIN)
check("§7 READ reports a recoverable op as NOT eligible", b_r_rec["terminalization_eligible"], False)
st_w_rec, b_w_rec = S._req("POST", _term_url(op7b),
                           {"expected_op_token": b_r_rec["expected_op_token"],
                            "idempotency_key": "H3", "reason": "should be denied"},
                           headers=AUTH_ADMIN)
check("§7 WRITE terminalize of a recoverable op -> 409 governed_denial recoverable",
      (st_w_rec, _err(b_w_rec).get("reason")), (409, "recoverable"))

# --- LIVE HTTP ACTIVE-OWNER (Codex re-review required case) ---
# Drive op7b into state='running' under a genuinely LIVE lease: claim it with an explicit long lease
# (the §1 env pinned a 2s lease, which would expire before the POST and re-read as recoverable). A
# live owner still holds the work, so terminalization must be refused over the wire, and the denial
# must leave the operation, its audit trail, and its fence exactly as they were.
_op7b_claim = E.claim_rework_operation(conn, op7b, lease_seconds=3600)
check("§7 active-owner setup: op7b is now running under a live lease",
      _op7b_claim["state"] if _op7b_claim else None, "running")
conn.commit()
_ao_before = snapshot(slot2)
cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='rework_operation' AND entity_id=%s",
            (op7b,))
_ao_audit_before = cur.fetchone()["n"]
conn.commit()
b_r_active = S.GET(f"/rework_operations/{op7b}", headers=AUTH_ADMIN)
check("§7 READ authenticated: a running/live-lease op still returns a token",
      bool(b_r_active["expected_op_token"]), True)
check("§7 READ: active op reports terminalization_eligible=false", b_r_active["terminalization_eligible"],
      False)
check("§7 READ: active op reports lease_valid=true (owner is live)", b_r_active["lease_valid"], True)
st_w_active, b_w_active = S._req("POST", _term_url(op7b),
                                 {"expected_op_token": b_r_active["expected_op_token"],
                                  "idempotency_key": "H4",
                                  "reason": "should be denied — a live owner still holds it"},
                                 headers=AUTH_ADMIN)
check("§7 WRITE terminalize of an ACTIVE-owner op -> 409 governed_denial active_owner",
      (st_w_active, _err(b_w_active).get("reason")), (409, "active_owner"))
_ao_after = snapshot(slot2)
check("§7 active-owner denial had NO effect on any generation-touched table",
      diff_tables(_ao_before, _ao_after), [])
_ao_row_before = [(r["state"], r["claim_token"], r["lease_expires_at"], r["generated_revision"])
                  for r in _ao_before["rework_operation"] if str(r["op_id"]) == str(op7b)]
_ao_row_after = [(r["state"], r["claim_token"], r["lease_expires_at"], r["generated_revision"])
                 for r in _ao_after["rework_operation"] if str(r["op_id"]) == str(op7b)]
check("§7 active-owner op unchanged: same state/token/lease, generated_revision still NULL",
      _ao_row_after, _ao_row_before)
cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='rework_operation' AND entity_id=%s",
            (op7b,))
check("§7 active-owner denial wrote NO audit row", cur.fetchone()["n"], _ao_audit_before)
conn.commit()
raises("§7 active-owner denial did NOT release the fence (item still rework_active)",
       lambda: E._topic_item_mutation_eligibility(cur, slot2, "topic"), E.GovernedDenial,
       reason="rework_active")
conn.rollback()

# The seeded principals must be untouched at exit (no shared-state contamination).
cur.execute("SELECT permissions FROM principal WHERE principal_id='khal'")
check("§7 seeded 'khal' principal left untouched (no contamination)",
      cur.fetchone()["permissions"], [])
conn.commit()

print("\n" + "=" * 78)
if FAILS:
    print(f"#319 PROOF FAILED — {len(FAILS)} check(s):")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1)
print("#319 PROOF PASSED — a rejected completion commits nothing; a permanently fenced item has "
      "exactly one governed, audited, bounded escape.")
print("=" * 78)
