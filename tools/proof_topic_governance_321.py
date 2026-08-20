"""#321 — Topic governance hardening proof: authority (R4), lock/eligibility (R3), exact decision
validity (R5), bounded recovery ownership (R6), provenance truth (R8) and rework lifecycle audit (N1).

Drives the PRODUCTION engine/worker/API paths against the isolated api_selftest DB/runtime. Stub
writer only; one worker; zero retries; asserts the INTENDED typed error, not merely "an error".
Mechanically invoked by gates.api_selftest (importing it runs it; SystemExit(1) fails the gate).
"""
import os
import threading
import time

import psycopg2.extras

import gates.api_selftest as S
import gates.engine as E
import run_writers as RW

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


def _err(body):
    d = body.get("detail") if isinstance(body, dict) else None
    return d if isinstance(d, dict) else (body if isinstance(body, dict) else {})


conn = S.db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cfg = E.load_config()
os.environ["TANAGHOM_WRITER_STUB"] = "1"

# --- seed a completed automatic topic round (canonical Stage 2A path) ---
elig = [e["name"] for e in S.GET("/baseline-eligibility")["eligible"]]
mix = {n: 0 for n in elig}
mix[elig[0]] = 2
_, rb = S.POST("/rounds", {"days": 1, "posts_per_day": 2, "label": "#321 gov proof", "format_mix": mix})
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

# Principals: khal is the configured topic_review reviewer (assigned). p321.stranger is a valid signed
# principal with NO assignment. p321.admin holds workflow.admin but NO topic_review assignment (proving
# ordinary mutation does not inherit the #319 terminalization permission). None mutate seeded principals.
cur.execute("""INSERT INTO principal (principal_id, kind, role, permissions, active)
               VALUES ('p321.stranger','user','viewer','[]'::jsonb,true),
                      ('p321.admin','user','workflow_admin',%s,true)
               ON CONFLICT (principal_id) DO UPDATE
                  SET permissions=EXCLUDED.permissions, role=EXCLUDED.role, active=true""",
            (psycopg2.extras.Json(["workflow.admin"]),))
conn.commit()

print("\n#321 R4 — canonical stage-assignment authority on edit/restore/rework (no workflow.admin)")
# assigned reviewer succeeds
r = E.edit_revision(conn, slot_id, "topic", "text_ar", "زاوية معدّلة ١", actor="khal", cfg=cfg)
check("R4 assigned reviewer (khal) may edit", r["new_revision"], 2)
# unassigned principal is fail-closed, typed
raises("R4 unassigned principal edit -> GovernedDenial(not_authorized)",
       lambda: E.edit_revision(conn, slot_id, "topic", "text_ar", "x", actor="p321.stranger", cfg=cfg),
       E.GovernedDenial, reason="not_authorized")
raises("R4 unassigned principal restore -> GovernedDenial(not_authorized)",
       lambda: E.restore_revision(conn, slot_id, "topic", 1, actor="p321.stranger", cfg=cfg),
       E.GovernedDenial, reason="not_authorized")
raises("R4 unassigned principal rework -> GovernedDenial(not_authorized)",
       lambda: E.begin_rework_operation(conn, slot_id, 1, "c", "p321.stranger", "R4-K1", cfg=cfg),
       E.GovernedDenial, reason="not_authorized")
# workflow.admin does NOT confer ordinary mutation authority (it is #319-terminalization-exclusive)
raises("R4 workflow.admin holder is NOT authorized to edit (no inheritance)",
       lambda: E.edit_revision(conn, slot_id, "topic", "text_ar", "x", actor="p321.admin", cfg=cfg),
       E.GovernedDenial, reason="not_authorized")
check("R4 no revision minted by any denied mutation", [r["revision"] for r in E.list_revisions(conn, slot_id)],
      [1, 2])
# HTTP path: signed-but-unassigned principal -> 409 governed_denial(not_authorized); assigned -> 200
_sig_stranger = S._signed("p321.stranger")
st_h, b_h = S._req("POST", f"/slots/{slot_id}/edit",
                   {"artifact": "topic", "field": "text_ar", "value": "x"}, headers=_sig_stranger)
check("R4 HTTP unassigned edit -> 409 governed_denial(not_authorized)",
      (st_h, _err(b_h).get("error"), _err(b_h).get("reason")), (409, "governed_denial", "not_authorized"))
st_ok, _ = S._req("POST", f"/slots/{slot_id}/edit",
                  {"artifact": "topic", "field": "text_ar", "value": "زاوية عبر HTTP"},
                  headers=S.AUTH_KHAL)
check("R4 HTTP assigned edit -> 200", st_ok, 200)

print("\n#321 P1.1 — authority re-read under the lock: unauthorized known-key replay + authority change")
# authorized keyed edit, then an UNAUTHORIZED replay of the SAME idempotency key is DENIED — not
# returned. Authority precedes the idempotency replay, under the lock.
kr = E.edit_revision(conn, slot_id, "topic", "text_ar", "keyed once", actor="khal",
                     idempotency_key="P11-K", cfg=cfg)
raises("P1.1 unauthorized principal cannot REPLAY a known idempotency key (denied, not returned)",
       lambda: E.edit_revision(conn, slot_id, "topic", "text_ar", "keyed once", actor="p321.stranger",
                               idempotency_key="P11-K", cfg=cfg),
       E.GovernedDenial, reason="not_authorized")
kr2 = E.edit_revision(conn, slot_id, "topic", "text_ar", "keyed once", actor="khal",
                      idempotency_key="P11-K", cfg=cfg)
check("P1.1 authorized same-actor replay still returns the original revision (idempotent)",
      (kr2["new_revision"], kr2.get("idempotent_replay")), (kr["new_revision"], True))
# authority is RE-READ per command: a governed reassignment flips the outcome on the NEXT command.
E.edit_revision(conn, slot_id, "topic", "text_ar", "before reassignment", actor="khal", cfg=cfg)
cur.execute("INSERT INTO approval_policy (stage, rule_key) VALUES ('topic_review','any') "
            "RETURNING policy_id")
_pid = cur.fetchone()["policy_id"]
cur.execute("INSERT INTO approval_policy_assignment (policy_id, assignment_kind, assignment_key) "
            "VALUES (%s,'user','huda')", (_pid,))
conn.commit()
raises("P1.1 authority CHANGE (reassigned to huda) denies khal on the NEXT command (re-read, not cached)",
       lambda: E.edit_revision(conn, slot_id, "topic", "text_ar", "after reassignment", actor="khal",
                               cfg=cfg),
       E.GovernedDenial, reason="not_authorized")
r_huda = E.edit_revision(conn, slot_id, "topic", "text_ar", "huda now authorized", actor="huda", cfg=cfg)
check("P1.1 the newly-assigned principal (huda) is authorized on the next command",
      r_huda["new_revision"] > 0, True)
cur.execute("DELETE FROM approval_policy WHERE policy_id=%s", (_pid,))   # restore config authority (khal)
conn.commit()

print("\n#321 R3 — mutable eligibility re-read UNDER the canonical slot lock (fail closed)")
# eligibility is enforced under the lock: an approved item's edit/restore is denied; a rework-active
# item's edit is denied. (The lock-ordering itself is structural; these prove the guard is enforced.)
_h = E._head_revision(cur, slot_id, "topic")
E._record_approval(cur, slot_id, "topic", _h, "khal")
conn.commit()
raises("R3 approved item edit denied (eligibility under lock)",
       lambda: E.edit_revision(conn, slot_id, "topic", "text_ar", "x", actor="khal", cfg=cfg),
       E.GovernedDenial, reason="approved")
cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot_id,))
conn.commit()
began_ra = E.begin_rework_operation(conn, slot_id, 1, "rework-active fence", "khal", "R3-RA", cfg=cfg)
raises("R3 rework-active item edit denied (eligibility under lock)",
       lambda: E.edit_revision(conn, slot_id, "topic", "text_ar", "x", actor="khal", cfg=cfg),
       E.GovernedDenial, reason="rework_active")
# drive the rework to completion so the fence clears for later sections (stub, one worker)
RW.run_rework_operation(cfg, began_ra["op_id"])
conn.commit()

print("\n#321 R5 — exact decision validity: decide(N) -> head advance -> resolve fails typed-stale")
# Use slot2 (clean). Open a topic_review gate, approve the EXACT head, advance the head with an edit,
# then resolve: the slot must NOT advance, the decision is preserved, the later head is never approved.
cur.execute("SELECT max(revision) AS h FROM topic WHERE slot_id=%s", (slot2,))
head_n = cur.fetchone()["h"]
conn.commit()
_, g2 = S.POST("/gates", {"stage": "topic_review", "round_id": rid}, headers=S.AUTH_KHAL)
gid2 = g2["gate_id"]
S.POST(f"/gates/{gid2}/decide",
       {"approver_id": "khal", "decision": "approve", "slot_ids": [slot2], "revision": head_n,
        "expected_revision": head_n}, headers=S.AUTH_KHAL)
# advance the head past the reviewed revision (edit by the assigned reviewer)
adv = E.edit_revision(conn, slot2, "topic", "text_ar", "أحدث رأس غير مُراجَع", actor="khal", cfg=cfg)
check("R5 head advanced past the reviewed revision", adv["new_revision"], head_n + 1)
out = E.resolve(conn, gid2, actor="khal", slot_ids=[slot2])
check("R5 resolve returns typed stale_revision (not approved)", out.get(slot2), "stale_revision")
cur.execute("SELECT status FROM slot WHERE slot_id=%s", (slot2,))
check("R5 slot did NOT advance to approved", cur.fetchone()["status"], "TOPIC_PROPOSED")
cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot2,))
check("R5 no approval pin created for the later head", cur.fetchone(), None)
cur.execute("""SELECT decision, revision FROM gate_decision WHERE gate_id=%s AND slot_id=%s""",
            (gid2, slot2))
_d = cur.fetchone()
check("R5 the recorded decision is PRESERVED (never deleted), still pinned to N",
      (_d["decision"], _d["revision"]), ("approve", head_n))
cur.execute("""SELECT count(*) AS n FROM audit_log WHERE entity='slot' AND entity_id=%s
                AND action='resolve_stale_revision'""", (slot2,))
check("R5 immutable resolve_stale_revision audit recorded", cur.fetchone()["n"], 1)
conn.commit()
# re-approve the CURRENT head -> resolves approved (the governed way forward)
new_head = adv["new_revision"]
S.POST(f"/gates/{gid2}/decide",
       {"approver_id": "khal", "decision": "approve", "slot_ids": [slot2], "revision": new_head,
        "expected_revision": new_head}, headers=S.AUTH_KHAL)
out2 = E.resolve(conn, gid2, actor="khal", slot_ids=[slot2])
check("R5 re-approving the current head resolves approved", out2.get(slot2), "approved")
cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot2,))
check("R5 approval now pinned to the reviewed current head", cur.fetchone()["revision"], new_head)
conn.commit()

print("\n#321 P1.2 — quorum>1 (ALL) mixed-revision: N/N+1 approvals cannot combine; re-approve head advances")
# Reopen slot2 into review, install an 'all' 2-approver contract [khal, huda], open an AUTHORITATIVE
# topic_review gate (freezes {khal,huda} 'all'), then run the mixed-revision scenario.
E.reopen(conn, slot2, actor="khal")
conn.commit()
cur.execute("INSERT INTO approval_policy (stage, rule_key) VALUES ('topic_review','all') RETURNING policy_id")
_pp = cur.fetchone()["policy_id"]
for _u in ("khal", "huda"):
    cur.execute("INSERT INTO approval_policy_assignment (policy_id, assignment_kind, assignment_key) "
                "VALUES (%s,'user',%s)", (_pp, _u))
conn.commit()
_, gq = S.POST("/gates", {"stage": "topic_review", "round_id": rid, "slot_ids": [slot2]},
               headers=S.AUTH_KHAL)
gqid = gq["gate_id"]
n = E._head_revision(cur, slot2, "topic")
conn.commit()
# approver A (khal) approves revision N
S.POST(f"/gates/{gqid}/decide", {"approver_id": "khal", "decision": "approve", "slot_ids": [slot2],
       "revision": n, "expected_revision": n}, headers=S.AUTH_KHAL)
# head advances to N+1 (edit by an assigned reviewer)
advq = E.edit_revision(conn, slot2, "topic", "text_ar", "رأس جديد للنصاب", actor="khal", cfg=cfg)
np1 = advq["new_revision"]
check("P1.2 head advanced N -> N+1 between the two approvals", np1, n + 1)
# approver B (huda) approves N+1 — signed AS huda (a distinct principal's decision)
S.POST(f"/gates/{gqid}/decide", {"approver_id": "huda", "decision": "approve", "slot_ids": [slot2],
       "revision": np1, "expected_revision": np1}, headers=S._signed("huda"))
# --- P1.4 — the READ MODELS / persisted coverage / audit must agree with resolve (one truth) ---
# BEFORE resolve, after the split-revision decisions: persisted coverage counts only the current head.
cur.execute("SELECT count(*) AS n FROM gate_token_coverage WHERE gate_id=%s AND slot_id=%s",
            (gqid, slot2))
check("P1.4 persisted token coverage EXCLUDES the superseded approval (1 of 2 tokens)",
      cur.fetchone()["n"], 1)
conn.commit()
_gv = E.get_gate(conn, gqid)
_t2 = next(t for t in _gv["targets"] if t["slot_id"] == slot2)
check("P1.4 read model: approval_count reflects ONLY current-head approvals (1)", _t2["approval_count"], 1)
check("P1.4 read model: outcome is pending, NEVER approved, on split-revision quorum",
      _t2["current_outcome"], "pending")
cur.execute("""SELECT detail->>'outcome' AS outcome FROM audit_log WHERE entity='slot' AND entity_id=%s
                AND action='coverage_recomputed' ORDER BY id DESC LIMIT 1""", (slot2,))
check("P1.4 decision-time coverage_recomputed audit never claims approved",
      cur.fetchone()["outcome"] in ("pending", "changes_requested", "rejected"), True)
conn.commit()
# P1.4 (reviewer queue) — khal approved the SUPERSEDED revision N; the head is now N+1. khal MUST
# re-review, so the mixed gate must still surface in khal's pending queue (a superseded approval is
# not "mine/decided"). Before the fix khal's N approval hid the gate.
_pend_khal = [str(g["gate_id"]) for g in E.list_pending_approvals(conn, "khal")]
check("P1.4 the superseded approver (khal) still sees the mixed N/N+1 gate as pending",
      str(gqid) in _pend_khal, True)
conn.commit()
# P1.4 (legacy remaining-assignments) — the SAME effective decisions must drive remaining-assignments,
# so a superseded approval never shows its assignment satisfied while the outcome is pending.
_assign = [{"assignment_kind": "user", "assignment_key": "khal"},
           {"assignment_kind": "user", "assignment_key": "huda"}]
_mix = [{"approver_id": "khal", "decision": "approve", "revision": 5},
        {"approver_id": "huda", "decision": "approve", "revision": 6}]
_eff6 = E._effective_decisions_for_head(_mix, 6)     # head=6: khal@5 superseded
_rem = E._remaining_assignment_snapshots(cur, "all", _assign, _eff6)
check("P1.4 legacy remaining-assignments: the superseded approver's assignment stays OUTSTANDING",
      any(a["assignment_key"] == "khal" for a in _rem), True)
check("P1.4 legacy remaining-assignments: the current-head approver is satisfied",
      any(a["assignment_key"] == "huda" for a in _rem), False)
conn.commit()
# resolve: khal reviewed N, huda reviewed N+1 -> quorum NOT met on the current head N+1 -> stale
_, rq = S.POST(f"/gates/{gqid}/resolve", {"actor": "khal"}, headers=S.AUTH_KHAL)
check("P1.2 mixed-revision quorum does NOT combine -> typed stale (not approved)",
      (rq or {}).get("outcomes", {}).get(slot2), "stale_revision")
# AFTER stale resolve: read model + coverage unchanged and still not approved.
_gv2 = E.get_gate(conn, gqid)
_t2b = next(t for t in _gv2["targets"] if t["slot_id"] == slot2)
check("P1.4 after stale resolve the read model is still not approved", _t2b["current_outcome"] != "approved", True)
check("P1.4 after stale resolve approval_count still counts only the current head (1)",
      _t2b["approval_count"], 1)
conn.commit()
cur.execute("SELECT status FROM slot WHERE slot_id=%s", (slot2,))
check("P1.2 slot did NOT advance on split-revision quorum", cur.fetchone()["status"], "TOPIC_PROPOSED")
cur.execute("SELECT count(*) AS n FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot2,))
check("P1.2 no approval pin on the split-quorum head", cur.fetchone()["n"], 0)
cur.execute("SELECT count(*) AS n FROM gate_decision WHERE gate_id=%s AND decision='approve'", (gqid,))
check("P1.2 BOTH approval decisions are preserved (nothing deleted)", cur.fetchone()["n"], 2)
conn.commit()
# the required current-revision principal (khal) re-approves N+1 -> quorum met on the head -> approved
S.POST(f"/gates/{gqid}/decide", {"approver_id": "khal", "decision": "approve", "slot_ids": [slot2],
       "revision": np1, "expected_revision": np1}, headers=S.AUTH_KHAL)
# P1.4 — re-approval on the current head UPDATES the persisted coverage to full (both tokens)
cur.execute("SELECT count(*) AS n FROM gate_token_coverage WHERE gate_id=%s AND slot_id=%s",
            (gqid, slot2))
check("P1.4 re-approval on the current head updates coverage to full (2 of 2)", cur.fetchone()["n"], 2)
conn.commit()
_, rq2 = S.POST(f"/gates/{gqid}/resolve", {"actor": "khal"}, headers=S.AUTH_KHAL)
check("P1.2 re-approval by BOTH on the current head advances (quorum met on N+1)",
      (rq2 or {}).get("outcomes", {}).get(slot2), "approved")
cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot2,))
check("P1.2 approval pinned to the reviewed current head N+1", cur.fetchone()["revision"], np1)
cur.execute("DELETE FROM approval_policy WHERE policy_id=%s", (_pp,))   # restore config authority
conn.commit()

# P1.4 — the LEGACY/count projection is exact-head aware too (the shared head-filter helper), and
# reject/request_change stay revision-independent.
_mixed = [{"approver_id": "khal", "decision": "approve", "revision": 5},
          {"approver_id": "huda", "decision": "approve", "revision": 6}]
check("P1.4 legacy/count rollup counts only the current-head approval (superseded rev5 excluded @6)",
      E._decision_rollup(E._effective_decisions_for_head(_mixed, 6), 2)["approval_count"], 1)
check("P1.4 legacy/count rollup: with quorum 2 and one superseded approval, outcome is pending",
      E._decision_rollup(E._effective_decisions_for_head(_mixed, 6), 2)["current_outcome"], "pending")
_rej = [{"approver_id": "a", "decision": "reject", "revision": 5}]
check("P1.4 reject stays revision-independent (kept regardless of head)",
      E._effective_decisions_for_head(_rej, 6), _rej)
_rc = [{"approver_id": "a", "decision": "request_change", "revision": 5}]
check("P1.4 request_change stays revision-independent (kept regardless of head)",
      E._effective_decisions_for_head(_rc, 6), _rc)
_both_head = [{"approver_id": "khal", "decision": "approve", "revision": 6},
              {"approver_id": "huda", "decision": "approve", "revision": 6}]
check("P1.4 both current-head approvals combine to meet quorum 2 (approved)",
      E._decision_rollup(E._effective_decisions_for_head(_both_head, 6), 2)["current_outcome"], "approved")

print("\n#321 R6/P1.3 — ACTUAL bounded periodic drain: invocation, batch, exclusions, overlap, "
      "retry, no-terminalization, config validation")
import inspect  # noqa: E402
import gates.api as _api  # noqa: E402

# A controlled strand set on fresh synthetic ops (direct rows): 5 recoverable (failed+expired), plus
# one each active(live-lease) / completed / terminated that MUST be excluded from any drain.
cur.execute("SELECT slot_id FROM slot WHERE round_id=%s ORDER BY slot_id", (rid,))
_all = [r["slot_id"] for r in cur.fetchall()]
conn.commit()


def _mk_op(key, state, lease_sql, gen="NULL"):
    cur.execute(f"""INSERT INTO rework_operation (slot_id, idempotency_key, artifact, base_revision,
                        restored_revision, comment, actor, state, lease_expires_at, generated_revision)
                    VALUES (%s,%s,'topic',1,1,'r6','khal',%s,{lease_sql},{gen})
                    RETURNING op_id""", (_all[0], key, state))
    return str(cur.fetchone()["op_id"])


recoverable = [_mk_op(f"P13-rec-{i}", "failed", "now() - interval '1 hour'") for i in range(5)]
active_op = _mk_op("P13-active", "running", "now() + interval '1 hour'")
completed_op = _mk_op("P13-done", "completed", "NULL", gen="99")
terminated_op = _mk_op("P13-term", "terminated", "NULL")
conn.commit()

# Instrument the ACTUAL drain: capture what it dispatches WITHOUT spawning real workers, and record any
# terminalization call (which the drain must NEVER make). This replaces the prior vacuous `or True`.
_dispatched, _term_calls = [], []
_orig_drive, _orig_term = _api._drive_rework_operation, E.terminalize_rework_operation
_api._drive_rework_operation = lambda _cfg, _op: _dispatched.append(str(_op))
E.terminalize_rework_operation = lambda *a, **k: _term_calls.append(a)
try:
    os.environ["TANAGHOM_REWORK_RECOVERY_BATCH"] = "3"
    driven = _api._periodic_rework_recovery(cfg)          # the REAL bounded periodic drain
    check("P1.3 drain dispatched AT MOST the batch cap (3)", len(driven) <= 3, True)
    check("P1.3 drain actually invoked _drive for each dispatched op",
          sorted(driven) == sorted(_dispatched), True)
    check("P1.3 every dispatched op is a recoverable (failed/expired) op",
          all(op in set(recoverable) for op in driven), True)
    check("P1.3 recoverable-FAILURE retry: a failed op is among those dispatched",
          len(driven) >= 1 and driven[0] in recoverable, True)
    check("P1.3 active-owner (live lease) NOT dispatched", active_op in _dispatched, False)
    check("P1.3 completed NOT dispatched", completed_op in _dispatched, False)
    check("P1.3 terminated NOT dispatched", terminated_op in _dispatched, False)
    check("P1.3 the drain made ZERO terminalization calls", _term_calls, [])
    # startup-loop seam: the #310 startup daemon's loop invokes the periodic rework drain (no race — we
    # assert the wiring by source, and invoke the same function directly above).
    _src = inspect.getsource(_api._start_topic_generation_recovery)
    check("P1.3 the startup recovery loop invokes _periodic_rework_recovery",
          "_periodic_rework_recovery" in _src, True)
    # (the zero-terminalization guarantee is proven at RUNTIME above via _term_calls == [], not by
    # source substrings — the drain's comments legitimately mention that it never terminalizes.)
    # config validation: invalid / non-positive -> fail safe to a positive default; valid -> honored
    for _bad in ("0", "-1", "abc", ""):
        os.environ["TANAGHOM_REWORK_RECOVERY_BATCH"] = _bad
        check(f"P1.3 invalid batch {_bad!r} fails safe to a positive default",
              _api._rework_recovery_batch() >= 1, True)
    os.environ["TANAGHOM_REWORK_RECOVERY_BATCH"] = "7"
    check("P1.3 a valid positive batch is honored", _api._rework_recovery_batch(), 7)
finally:
    _api._drive_rework_operation = _orig_drive
    E.terminalize_rework_operation = _orig_term

# overlap idempotency at the CLAIM level: concurrent claims of one op -> exactly one wins (atomic)
cur.execute("UPDATE rework_operation SET state='failed', lease_expires_at=now()-interval '1 hour', "
            "generated_revision=NULL WHERE op_id=%s", (recoverable[0],))
conn.commit()
_wins = []
_barrier = threading.Barrier(4)


def _race_claim():
    c = S.db()
    try:
        _barrier.wait()
        _wins.append(E.claim_rework_operation(c, recoverable[0]) is not None)
    finally:
        c.close()


ts = [threading.Thread(target=_race_claim) for _ in range(4)]
for t in ts:
    t.start()
for t in ts:
    t.join(timeout=20)
check("P1.3 overlapping claims of one op: EXACTLY ONE wins (atomic, overlap-safe)",
      sum(1 for w in _wins if w), 1)
# a terminal op is untouched by recovery (neither created nor cleared)
cur.execute("SELECT state FROM rework_operation WHERE op_id=%s", (terminated_op,))
check("P1.3 a terminalized op stays terminal after a drain pass", cur.fetchone()["state"], "terminated")
# clean up the synthetic strands so their un-generated fence does not block the R8/N1 reworks below
cur.execute("DELETE FROM rework_operation WHERE idempotency_key LIKE 'P13-%%'")
conn.commit()

print("\n#321 R8 — rework provenance records the ACTUAL runner identity (stub), never dict/unknown")
# slot_id is in review (R3's rework completed); drive a real stub rework and read its provenance.
began8 = E.begin_rework_operation(conn, slot_id, E._head_revision(cur, slot_id, "topic"),
                                  "provenance truth", "khal", "R8-1", cfg=cfg)
conn.commit()
RW.run_rework_operation(cfg, began8["op_id"])
conn.commit()
cur.execute("""SELECT p.resolved_provider, p.resolved_model, p.execution_route
                 FROM topic_provenance p JOIN topic t USING (topic_id)
                WHERE t.slot_id=%s ORDER BY t.revision DESC LIMIT 1""", (slot_id,))
prov = cur.fetchone()
conn.commit()
check("R8 resolved_provider is the ACTUAL served provider (stub), not a config dict",
      prov["resolved_provider"], "stub")
check("R8 resolved_model is the ACTUAL served model (from the runner label), not 'unknown'",
      prov["resolved_model"], "test")
check("R8 execution_route is the truthful rework context", prov["execution_route"], "manual_rework")

print("\n#321 N1 — immutable rework lifecycle audit across begin/claim/fail/terminalize/completion")
# begin -> rework_started; the completed op above -> rework_claimed + rework_completed
cur.execute("""SELECT action FROM audit_log WHERE entity='rework_operation' AND entity_id=%s
                ORDER BY id""", (began8["op_id"],))
acts8 = [r["action"] for r in cur.fetchall()]
conn.commit()
check("N1 rework_started recorded at begin", "rework_started" in acts8, True)
check("N1 rework_claimed recorded at ownership acquisition", "rework_claimed" in acts8, True)
check("N1 rework_completed recorded at atomic completion", "rework_completed" in acts8, True)
# a failed op -> rework_failed (clean, owned failure)
began_f = E.begin_rework_operation(conn, slot_id, E._head_revision(cur, slot_id, "topic"),
                                   "will fail", "khal", "N1-FAIL", cfg=cfg)
claimed_f = E.claim_rework_operation(conn, began_f["op_id"])
ok_f = E.fail_rework_operation(conn, began_f["op_id"], claimed_f["claim_token"], "injected N1 failure")
check("N1 owned failure is recorded", ok_f, True)
cur.execute("""SELECT count(*) AS n FROM audit_log WHERE entity='rework_operation' AND entity_id=%s
                AND action='rework_failed'""", (began_f["op_id"],))
check("N1 rework_failed recorded at clean failure persistence", cur.fetchone()["n"], 1)
# reclaim an expired op -> rework_reclaimed
cur.execute("UPDATE rework_operation SET state='running', lease_expires_at=now()-interval '1 hour' "
            "WHERE op_id=%s", (began_f["op_id"],))
conn.commit()
E.claim_rework_operation(conn, began_f["op_id"], controller="recovery")
cur.execute("""SELECT count(*) AS n FROM audit_log WHERE entity='rework_operation' AND entity_id=%s
                AND action='rework_reclaimed'""", (began_f["op_id"],))
check("N1 rework_reclaimed recorded on expired-lease reclaim", cur.fetchone()["n"], 1)
# stale/fenced failure records NOTHING (N1 + #319-consistent): a loser writes no event
noown = E.fail_rework_operation(conn, began_f["op_id"], "00000000-0000-0000-0000-000000000000",
                                "stale loser")
check("N1 a stale/fenced failure records no event (truthful no-op)", noown, False)
conn.commit()

print("\n" + "=" * 78)
if FAILS:
    print(f"#321 PROOF FAILED — {len(FAILS)} check(s):")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1)
print("#321 PROOF PASSED — canonical authority, lock-safe eligibility, exact decision validity, "
      "bounded no-terminalize recovery, truthful provenance, and immutable rework audit.")
print("=" * 78)
