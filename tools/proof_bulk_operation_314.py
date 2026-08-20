"""#314 — Bulk Topic disposition (per-item-commit ledger) + Topic-workbench presentation-order proof.

Drives the PRODUCTION engine against the isolated api_selftest DB/runtime. Stub writer; asserts the
INTENDED typed outcome, not merely "an error". Mechanically invoked by gates.api_selftest (importing
it runs it; SystemExit(1) fails the gate). Covers:
  - bulk_approve happy path -> truthful per-item 'succeeded'; ledger 'completed'; ascending-slot_id seq
  - idempotent replay on (round_id, idempotency_key) -> same batch, no double effect
  - per-item CAS: a stale expected_revision -> 'stale' for THAT item only (truthful partial outcome)
  - bulk_drop eligibility: an already-approved item -> 'denied' (GovernedDenial); a proposable one -> ok
  - authority: an unassigned actor's items -> 'denied' (reuses decide's gate authority; no new authority)
  - not_attempted: fail_bulk_operation records still-pending items truthfully
  - presentation order: reorder -> token+1, complete permutation enforced, stale token -> ScheduleConflict
  - PRESENTATION-ONLY invariance: schedule_token, slot placement, and disposition are all UNCHANGED
  - append-only audit: bulk_started/bulk_completed/bulk_item_settled + topic_presentation_reordered
"""
import os
import time

import psycopg2.extras

import gates.api_selftest as S
import gates.engine as E

FAILS = []


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
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {type(e).__name__} "
              + " ".join(f"{k}={getattr(e, k, None)!r}" for k in attrs))
        if not ok:
            FAILS.append(label)
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] {label}: wrong exception {type(e).__name__}: {e}")
        FAILS.append(label)
    else:
        print(f"  [FAIL] {label}: no exception raised")
        FAILS.append(label)


os.environ["TANAGHOM_WRITER_STUB"] = "1"
conn = S.db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cfg = E.load_config()

# --- seed a completed automatic topic round; open a topic_review gate over its TOPIC_PROPOSED slots ---
elig = [e["name"] for e in S.GET("/baseline-eligibility")["eligible"]]
mix = {n: 0 for n in elig}
mix[elig[0]] = 4
_, rb = S.POST("/rounds", {"days": 2, "posts_per_day": 2, "label": "#314 bulk proof", "format_mix": mix})
rid = rb["round_id"]
_, sg = S.POST("/gates", {"stage": "schedule_review", "round_id": rid}, headers=S.AUTH_KHAL)
S.POST(f"/gates/{sg['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"}, headers=S.AUTH_KHAL)
S.POST(f"/gates/{sg['gate_id']}/resolve", {}, headers=S.AUTH_KHAL)
for _ in range(120):
    m = S.GET(f"/rounds/{rid}/generation")
    if m["phase"] in ("completed", "failed", "partial"):
        break
    time.sleep(0.5)
_, tg = S.POST("/gates", {"stage": "topic_review", "round_id": rid}, headers=S.AUTH_KHAL)
gate_id = tg["gate_id"]
cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED' ORDER BY slot_id", (rid,))
slots = [r["slot_id"] for r in cur.fetchall()]
conn.commit()
assert len(slots) >= 4, f"need >=4 TOPIC_PROPOSED slots, got {len(slots)}"


def heads(sids):
    return {s: E._head_revision(cur, s, "topic") for s in sids}


def hv(s):
    """Current topic head for a slot — every bulk item MUST pin a positive expected_revision (#314)."""
    conn.commit()
    return E._head_revision(cur, s, "topic")


print("\n#314 A — bulk_approve happy path: truthful per-item outcomes + completed ledger + ascending seq")
h = heads(slots[:2])
begun = E.begin_bulk_operation(conn, rid, gate_id, "bulk_approve",
                               [{"slot_id": slots[1], "expected_revision": h[slots[1]]},
                                {"slot_id": slots[0], "expected_revision": h[slots[0]]}],
                               actor="khal", idempotency_key="A-approve-1", cfg=cfg)
check("A begin returns start", begun["action"], "start")
st = E.run_bulk_operation(begun["batch_id"], actor="khal", cfg=cfg)
check("A batch completed", st["state"], "completed")
check("A both items succeeded", [i["outcome"] for i in st["items"]], ["succeeded", "succeeded"])
check("A items driven in ASCENDING slot_id order (seq 1,2 = sorted slots)",
      [i["slot_id"] for i in st["items"]], sorted(slots[:2]))
cur.execute("SELECT decision FROM gate_decision WHERE gate_id=%s AND slot_id=ANY(%s) ORDER BY slot_id",
            (gate_id, slots[:2]))
check("A canonical decide effect persisted (approve x2)", [r["decision"] for r in cur.fetchall()],
      ["approve", "approve"]); conn.commit()

print("\n#314 B — request-bound idempotency: same request re-resolves to the same batch; a DIFFERENT "
      "request under the same key is a typed conflict (never a silent wrong-op dedupe)")
same_items = [{"slot_id": slots[1], "expected_revision": h[slots[1]]},
              {"slot_id": slots[0], "expected_revision": h[slots[0]]}]
begun2 = E.begin_bulk_operation(conn, rid, gate_id, "bulk_approve", same_items,
                                actor="khal", idempotency_key="A-approve-1", cfg=cfg)
check("B same-request replay -> dedupe (already completed)", begun2["action"], "dedupe")
check("B same-request replay -> SAME batch_id", begun2["batch_id"], begun["batch_id"])
st2 = E.run_bulk_operation(begun2["batch_id"], actor="khal", cfg=cfg)
check("B same-request replay drives nothing new (completed, 2 items)",
      (st2["state"], len(st2["items"])), ("completed", 2))
raises("B DIFFERENT request under the same key -> GovernedDenial(idempotency_key_mismatch)",
       lambda: E.begin_bulk_operation(conn, rid, gate_id, "bulk_approve",
                                      [{"slot_id": slots[0], "expected_revision": h[slots[0]]}],
                                      actor="khal", idempotency_key="A-approve-1", cfg=cfg),
       E.GovernedDenial, reason="idempotency_key_mismatch")

print("\n#314 C — per-item CAS: a stale expected_revision -> 'stale' for THAT item only")
h2 = heads(slots[2:4])
stc = E.run_bulk_operation(
    E.begin_bulk_operation(conn, rid, gate_id, "bulk_approve",
                           [{"slot_id": slots[2], "expected_revision": 999},          # stale
                            {"slot_id": slots[3], "expected_revision": h2[slots[3]]}],  # current
                           actor="khal", idempotency_key="C-cas-1", cfg=cfg)["batch_id"],
    actor="khal", cfg=cfg)
out_by_slot = {i["slot_id"]: i["outcome"] for i in stc["items"]}
check("C stale item -> 'stale' (truthful partial)", out_by_slot[slots[2]], "stale")
check("C current item -> 'succeeded' (partial success, not all-or-nothing)", out_by_slot[slots[3]], "succeeded")

print("\n#314 D — bulk_drop eligibility: an already-approved item is denied; a proposable one succeeds")
# Resolve slots[0]'s approve (partial) so a slot_approval PIN exists -> a drop is then #249-fence-denied.
# (an approve DECISION alone does not park the item; only a resolved approval / downstream script does.)
S.POST(f"/gates/{gate_id}/resolve", {"slot_ids": [slots[0]]}, headers=S.AUTH_KHAL)
std = E.run_bulk_operation(
    E.begin_bulk_operation(conn, rid, gate_id, "bulk_drop",
                           [{"slot_id": slots[0], "expected_revision": hv(slots[0])}, {"slot_id": slots[2], "expected_revision": hv(slots[2])}],
                           actor="khal", idempotency_key="D-drop-1", cfg=cfg)["batch_id"],
    actor="khal", cfg=cfg)
drop_out = {i["slot_id"]: i["outcome"] for i in std["items"]}
check("D dropping an APPROVED (resolved) item -> denied (eligibility fail-closed, #249 unconsumed)",
      drop_out[slots[0]], "denied")
check("D dropping a proposable item -> succeeded", drop_out[slots[2]], "succeeded")

print("\n#314 E — CREATION AUTHORITY: an unassigned principal creates ZERO rows (denied before any write)")
cur.execute("""INSERT INTO principal (principal_id, kind, role, permissions, active)
               VALUES ('p314.stranger','user','viewer','[]'::jsonb,true)
               ON CONFLICT (principal_id) DO UPDATE SET active=true""")
conn.commit()
cur.execute("SELECT count(*) AS n FROM bulk_operation"); _bo0 = cur.fetchone()["n"]
cur.execute("SELECT count(*) AS n FROM bulk_operation_item"); _bi0 = cur.fetchone()["n"]
cur.execute("SELECT count(*) AS n FROM audit_log WHERE action='bulk_started'"); _au0 = cur.fetchone()["n"]
conn.commit()
raises("E unassigned principal bulk create -> GovernedDenial(not_authorized) BEFORE any write",
       lambda: E.begin_bulk_operation(conn, rid, gate_id, "bulk_approve",
                                      [{"slot_id": slots[3], "expected_revision": hv(slots[3])}],
                                      actor="p314.stranger", idempotency_key="E-auth-1", cfg=cfg),
       E.GovernedDenial, reason="not_authorized")
conn.rollback()
cur.execute("SELECT count(*) AS n FROM bulk_operation"); check("E zero bulk_operation rows created", cur.fetchone()["n"], _bo0)
cur.execute("SELECT count(*) AS n FROM bulk_operation_item"); check("E zero bulk_operation_item rows created", cur.fetchone()["n"], _bi0)
cur.execute("SELECT count(*) AS n FROM audit_log WHERE action='bulk_started'"); check("E zero bulk_started audit rows", cur.fetchone()["n"], _au0)
conn.commit()

print("\n#314 F — not_attempted: fail_bulk_operation truthfully records still-pending items")
begf = E.begin_bulk_operation(conn, rid, gate_id, "bulk_approve",
                              [{"slot_id": slots[3], "expected_revision": hv(slots[3])}], actor="khal",
                              idempotency_key="F-na-1", cfg=cfg)
stf = E.fail_bulk_operation(begf["batch_id"], error="proof-stop", actor="khal")  # stop before driving
check("F failed batch state", stf["state"], "failed")
check("F pending item recorded not_attempted", stf["items"][0]["outcome"], "not_attempted")

print("\n#314 G — presentation order: reorder -> token+1; complete permutation; stale token -> conflict")
before_sched = E.schedule_token(cur, rid)
before_status = {s: r for s, r in ((s, E._head_revision(cur, s, "topic")) for s in slots)}
cur.execute("SELECT day, time_uae FROM slot WHERE slot_id=%s", (slots[0],))
placement_before = dict(cur.fetchone()); conn.commit()
allslots = E._topic_round_slot_ids(cur, rid); conn.commit()
r1 = E.reorder_topic_presentation(conn, rid, list(reversed(allslots)), 0, actor="khal", cfg=cfg)
check("G first reorder mints token 1", r1["topic_presentation_token"], 1)
check("G positions are the reversed permutation", [p["slot_id"] for p in r1["positions"]], list(reversed(allslots)))
raises("G stale token -> typed ScheduleConflict",
       lambda: E.reorder_topic_presentation(conn, rid, allslots, 0, actor="khal", cfg=cfg),
       E.ScheduleConflict)
raises("G incomplete permutation -> GateError",
       lambda: E.reorder_topic_presentation(conn, rid, allslots[:-1], 1, actor="khal", cfg=cfg),
       E.GateError)
r2 = E.reorder_topic_presentation(conn, rid, allslots, 1, actor="khal", cfg=cfg)
check("G second reorder advances token to 2", r2["topic_presentation_token"], 2)

print("\n#314 H — PRESENTATION-ONLY invariance: schedule token, slot placement, disposition UNCHANGED")
check("H #292 schedule_token UNCHANGED by topic reorder", E.schedule_token(cur, rid), before_sched)
cur.execute("SELECT day, time_uae FROM slot WHERE slot_id=%s", (slots[0],))
check("H slot physical placement UNCHANGED", dict(cur.fetchone()), placement_before)
check("H topic heads (revision identity) UNCHANGED",
      {s: E._head_revision(cur, s, "topic") for s in slots}, before_status)
cur.execute("SELECT count(*) AS n FROM gate_decision WHERE gate_id=%s AND slot_id=%s", (gate_id, slots[0]))
check("H prior disposition still present (approve on slots[0])", cur.fetchone()["n"], 1)
conn.commit()

print("\n#314 I — append-only lifecycle audit present")
cur.execute("""SELECT action, count(*) AS n FROM audit_log
                WHERE action IN ('bulk_started','bulk_completed','bulk_item_settled',
                                 'topic_presentation_reordered','bulk_failed')
                GROUP BY action ORDER BY action""")
audit = {r["action"]: r["n"] for r in cur.fetchall()}; conn.commit()
check("I bulk_started audited", audit.get("bulk_started", 0) >= 4, True)
check("I bulk_completed audited", audit.get("bulk_completed", 0) >= 2, True)
check("I bulk_item_settled audited", audit.get("bulk_item_settled", 0) >= 4, True)
check("I bulk_failed audited (not_attempted path)", audit.get("bulk_failed", 0) >= 1, True)
check("I topic_presentation_reordered audited", audit.get("topic_presentation_reordered", 0) >= 2, True)

print("\n#314 J — membership fail-closed at creation + governed read authorization")
raises("J foreign slot at creation -> GateError (membership fail-closed, not a gate target)",
       lambda: E.begin_bulk_operation(conn, rid, gate_id, "bulk_approve",
                                      [{"slot_id": "NOPE-SLOT", "expected_revision": 1}], actor="khal",
                                      idempotency_key="J-mem-1", cfg=cfg),
       E.GateError)
raises("J unassigned principal cannot READ a bulk operation -> GovernedDenial(not_authorized)",
       lambda: E._authorize_bulk_read(conn, begun["batch_id"], "p314.stranger", cfg),
       E.GovernedDenial, reason="not_authorized")
_read_ok = True
try:
    E._authorize_bulk_read(conn, begun["batch_id"], "khal", cfg)   # assigned approver -> no raise
except Exception as _e:  # noqa: BLE001
    _read_ok = False
check("J assigned approver (khal) may READ the bulk operation", _read_ok, True)

print("\n#314 K — REAL forced-interleaving concurrency (threads + Barrier; the DB arbitrates)")
import threading
_, kb = S.POST("/rounds", {"days": 2, "posts_per_day": 2, "label": "#314 conc", "format_mix": mix})
krid = kb["round_id"]
_, ksg = S.POST("/gates", {"stage": "schedule_review", "round_id": krid}, headers=S.AUTH_KHAL)
S.POST(f"/gates/{ksg['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"}, headers=S.AUTH_KHAL)
S.POST(f"/gates/{ksg['gate_id']}/resolve", {}, headers=S.AUTH_KHAL)
for _ in range(120):
    if S.GET(f"/rounds/{krid}/generation")["phase"] in ("completed", "failed", "partial"):
        break
    time.sleep(0.5)
_, ktg = S.POST("/gates", {"stage": "topic_review", "round_id": krid}, headers=S.AUTH_KHAL)
kgate = ktg["gate_id"]
cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED' ORDER BY slot_id", (krid,))
kslots = [r["slot_id"] for r in cur.fetchall()]; conn.commit()
kall = sorted(kslots)


def _run2(fa, fb):
    """Release two real workers SIMULTANEOUSLY through a Barrier, each on its own connection; capture
    each result or the exception it raised. The database (locks / UNIQUE / CAS) arbitrates, exactly as
    in production — no sleeps, no sequential setup masquerading as concurrency."""
    bar = threading.Barrier(2); out = {}
    def wrap(name, fn):
        def go():
            c = E.db_connect()
            try:
                bar.wait(); out[name] = fn(c)
            except Exception as ex:  # noqa: BLE001
                out[name] = ex
            finally:
                c.close()
        return go
    ta = threading.Thread(target=wrap("A", fa)); tb = threading.Thread(target=wrap("B", fb))
    ta.start(); tb.start(); ta.join(timeout=30); tb.join(timeout=30)
    return out


def _errs(res):
    return [type(v).__name__ for v in res.values() if isinstance(v, Exception)]


# K1 reorder x reorder @ the SAME token -> exactly one winner (UNIQUE(round,generation_no) arbitrates).
r1 = _run2(lambda c: "won" if E.reorder_topic_presentation(c, krid, kall, 0, "khal", cfg) else "won",
           lambda c: "won" if E.reorder_topic_presentation(c, krid, list(reversed(kall)), 0, "khal", cfg) else "won")
check("K1 reorder×reorder(same token): exactly one won, one ScheduleConflict",
      sorted("conflict" if isinstance(v, E.ScheduleConflict) else str(v) for v in r1.values()),
      ["conflict", "won"])
check("K1 exactly one accepted generation (token=1)",
      E.topic_presentation(conn, krid)["topic_presentation_token"], 1); conn.commit()

# K2 duplicate partial replay -> two concurrent run_bulk_operation on ONE batch: claim fence, exactly-once.
items = [{"slot_id": s, "expected_revision": hv(s)} for s in kslots]
bk = E.begin_bulk_operation(conn, krid, kgate, "bulk_approve", items, actor="khal",
                            idempotency_key="K2-dup", cfg=cfg)["batch_id"]
r2 = _run2(lambda c: E.run_bulk_operation(bk, actor="khal", cfg=cfg)["state"],
           lambda c: E.run_bulk_operation(bk, actor="khal", cfg=cfg)["state"])
check("K2 duplicate concurrent run -> completed exactly once", E.bulk_operation_status(bk)["state"], "completed")
cur.execute("SELECT slot_id FROM gate_decision WHERE gate_id=%s GROUP BY slot_id HAVING count(*)>1", (kgate,))
check("K2 no duplicate gate_decision (exactly-once under the claim fence)", cur.fetchall(), [])
cur.execute("SELECT count(*) n FROM audit_log WHERE action='bulk_claimed' AND entity_id=%s", (str(bk),))
check("K2 exactly ONE driver claimed the batch (audit)", cur.fetchone()["n"], 1); conn.commit()

# K3 bulk x individual @ the SAME slot -> slot FOR UPDATE serializes them; consistent single-effect
# outcome (edit-first => item 'stale' CAS; bulk-first => 'succeeded'); never both / never a lost update.
s0 = kslots[0]; h0 = hv(s0)
b3 = E.begin_bulk_operation(conn, krid, kgate, "bulk_approve",
                            [{"slot_id": s0, "expected_revision": h0}], actor="khal",
                            idempotency_key="K3-bi", cfg=cfg)["batch_id"]
r3 = _run2(lambda c: E.run_bulk_operation(b3, actor="khal", cfg=cfg)["items"][0]["outcome"],
           lambda c: E.edit_revision(c, s0, "topic", "text_ar", "تعديل متزامن K3", actor="khal", cfg=cfg)["new_revision"])
check("K3 bulk×individual(same slot): item settled CONSISTENTLY (succeeded XOR stale)",
      E.bulk_operation_status(b3)["items"][0]["outcome"] in ("succeeded", "stale"), True)
cur.execute("SELECT count(*) n FROM gate_decision WHERE gate_id=%s AND slot_id=%s", (kgate, s0))
check("K3 at most one approve decision (no lost/duplicate update)", cur.fetchone()["n"] <= 1, True)
check("K3 no deadlock", _errs(r3), []); conn.commit()

# K4 reorder x drop CONCURRENT -> deterministic lock order (round->slots asc) serializes them
# cleanly: both commit, no deadlock, presentation-only preserved.
tok = E.topic_presentation(conn, krid)["topic_presentation_token"]; conn.commit()
s2 = kslots[2]
d4 = E.begin_bulk_operation(conn, krid, kgate, "bulk_drop",
                            [{"slot_id": s2, "expected_revision": hv(s2)}], actor="khal",
                            idempotency_key="K4-drop", cfg=cfg)["batch_id"]
r4 = _run2(lambda c: E.reorder_topic_presentation(c, krid, list(reversed(kall)), tok, "khal", cfg)["topic_presentation_token"],
           lambda c: E.run_bulk_operation(d4, actor="khal", cfg=cfg)["items"][0]["outcome"])
check("K4 reorder×drop(concurrent): reorder committed (token+1)",
      E.topic_presentation(conn, krid)["topic_presentation_token"], tok + 1)
check("K4 reorder×drop(concurrent): drop committed, no deadlock", E.bulk_operation_status(d4)["items"][0]["outcome"], "succeeded")
check("K4 no deadlock/incorrect state", _errs(r4), []); conn.commit()

# K5 reorder x head advancement CONCURRENT -> deterministic lock order minimizes contention; a residual
# slot-FK serialization deadlock is atomically rolled back and surfaced as a RETRYABLE ScheduleConflict
# (no incorrect/lost state), and a retry succeeds. Head advances independently (revision-independent).
tok5 = E.topic_presentation(conn, krid)["topic_presentation_token"]; conn.commit()
s3 = kslots[3]
def _reorder5(c):
    try:
        return E.reorder_topic_presentation(c, krid, kall, tok5, "khal", cfg)["topic_presentation_token"]
    except E.ScheduleConflict:
        return "retryable_conflict"
def _edit5(c):
    for _ in range(4):
        try:
            return E.edit_revision(c, s3, "topic", "text_ar", "تعديل رأس متزامن K5", actor="khal", cfg=cfg)["new_revision"]
        except E.psycopg2.errors.DeadlockDetected:
            c.rollback()
    return "edit_retry_exhausted"
r5 = _run2(_reorder5, _edit5)
check("K5 no UNHANDLED deadlock (only success or a typed retryable conflict)", _errs(r5), [])
if E.topic_presentation(conn, krid)["topic_presentation_token"] == tok5:   # reorder rolled back -> retry
    E.reorder_topic_presentation(conn, krid, kall, tok5, "khal", cfg); conn.commit()
if hv(s3) < 2:                                                             # edit rolled back -> retry
    E.edit_revision(conn, s3, "topic", "text_ar", "K5 head retry", actor="khal", cfg=cfg); conn.commit()
check("K5 reorder committed (retry after any serialization conflict succeeds)",
      E.topic_presentation(conn, krid)["topic_presentation_token"], tok5 + 1)
check("K5 head advanced independently (revision-independent order)", hv(s3) >= 2, True); conn.commit()

# K6 bulk x Stage-2A/recovery OWNERSHIP race -> two concurrent claims on ONE queued rework op: exactly
# one owner (fresh claim_token), the other gets None; a concurrent bulk_drop of the owned slot is fenced.
s1 = kslots[1]
op = E.begin_rework_operation(conn, s1, hv(s1), "rework directive", "khal", "K6-rw", cfg=cfg)
opid = op["op_id"]
r6 = _run2(lambda c: E.claim_rework_operation(c, opid, controller="w1") is not None,
           lambda c: E.claim_rework_operation(c, opid, controller="w2") is not None)
check("K6 rework OWNERSHIP race: exactly ONE worker claimed (fenced)",
      sorted(bool(v) for v in r6.values() if not isinstance(v, Exception)), [False, True])
d6 = E.begin_bulk_operation(conn, krid, kgate, "bulk_drop",
                            [{"slot_id": s1, "expected_revision": hv(s1)}], actor="khal",
                            idempotency_key="K6-drop", cfg=cfg)["batch_id"]
E.run_bulk_operation(d6, actor="khal", cfg=cfg)
check("K6 bulk_drop of a rework-OWNED item -> denied (Stage-2A/recovery ownership fence)",
      E.bulk_operation_status(d6)["items"][0]["outcome"], "denied"); conn.commit()


cur.close()
conn.close()
if FAILS:
    print(f"\n#314 PROOF FAILED: {len(FAILS)} check(s): {FAILS}")
    raise SystemExit(1)
print("\n#314 bulk-operation + topic-presentation proof: ALL PASSED")
