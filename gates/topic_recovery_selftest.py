"""#373 — recovery-action representability (reopen) + exact authoritative gate projection (undecide).

Proves the reconciled backend corrections over the CANONICAL per-item read model, with a discriminating
red proof on each load-bearing control:
  A  `reopen` action typed availability tracks engine.reopen eligibility EXACTLY (a dropped item with a
     committed decision is reopen-able; an in-review item is not) — and is DISTINCT from `restore`.
  B  `authoritative_gate_id` + `undecide` are projected ONLY when exactly one open gate applies:
       B1  exactly one open gate holding an uncommitted decision -> gate_id set, undecide allowed;
       B2  zero open gates -> gate_id null, undecide unavailable(no_open_gate)  [not a fabricated id];
       B3  MULTIPLE open gates -> gate_id null, undecide unavailable(ambiguous_gate)  [RED: no latest-pick];
       B4  one open gate but NO decision -> gate_id set, undecide unavailable(no_decision).
  C  the projected gate id is the EXACT gate holding the decision (correlates to gate_decision.gate_id).

Deterministic: fixtures are direct governed-shape SQL (no writer/sleep). Run:
  docker exec -e PYTHONPATH=/work:/work/gates:/work/agents <lane> python -m gates.topic_recovery_selftest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402

FAILS = []
RID = "R373REC"
STAGE = "topic_review"
APPROVER = "khal"
OTHER = "rula"        # a DIFFERENT trusted principal, for the A-vs-B multi-approver proofs (Codex P1)


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def _cur(conn):
    return conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)


def wipe(conn):
    c = conn.cursor()
    for stmt in (
        "DELETE FROM audit_log WHERE entity_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM gate_token_coverage WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM gate_decision WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM gate_target WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM gate WHERE gate_id NOT IN (SELECT gate_id FROM gate_target)",
        "DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM topic WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM slot WHERE round_id=%s",
        "DELETE FROM round WHERE round_id=%s",
    ):
        c.execute(stmt, (RID,))
    conn.commit()
    c.close()


PILLAR = None
HCS = None


def _mk_slot(c, slot_id, status):
    c.execute("INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, status) "
              "VALUES (%s,%s,1,'09:00',%s,%s)", (slot_id, RID, PILLAR, status))
    c.execute("INSERT INTO topic (slot_id, revision, hcs_id, hook_text, text_ar) "
              "VALUES (%s,1,%s,%s,%s)", (slot_id, HCS, "h", "نص"))


def _open_gate(c, slot_id):
    c.execute("INSERT INTO gate (scope, stage, status) VALUES ('batch', %s, 'open') RETURNING gate_id", (STAGE,))
    gid = c.fetchone()["gate_id"]
    c.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s)", (gid, slot_id))
    return gid


def _decide(c, gid, slot_id, decision="request_change"):
    c.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) VALUES (%s,%s,%s,%s)",
              (gid, slot_id, APPROVER, decision))


def main():
    global PILLAR, HCS
    conn = engine.db_connect()
    cfg = engine.load_config()
    wipe(conn)
    c = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    c.execute("SELECT pillar_code FROM pillar LIMIT 1"); PILLAR = c.fetchone()["pillar_code"]
    c.execute("SELECT hcs_id FROM hcs LIMIT 1"); HCS = c.fetchone()["hcs_id"]
    c.execute("INSERT INTO round (round_id, label, period_len_days, posts_per_day, post_times, "
              "pillar_distribution, format_distribution) VALUES (%s,%s,1,1,%s::jsonb,%s::jsonb,%s::jsonb)",
              (RID, "373-recovery", '["09:00"]', "{}", "{}"))

    # ---- reject/review statuses from config (governed, never hard-coded) ----
    reject = sorted(s for s in engine.reject_statuses(cfg) if s)
    review = engine.stage_cfg(cfg, STAGE).get("reviews_status", "DRAFT_ASSIGNED")
    review = (review[0] if isinstance(review, list) else review) or "DRAFT_ASSIGNED"
    dropped_status = reject[0] if reject else "DROPPED"

    # === A. reopen availability tracks engine.reopen eligibility, distinct from restore ===
    _mk_slot(c, "S-DROP", dropped_status)          # a dropped item...
    g1 = _open_gate(c, "S-DROP")
    _decide(c, g1, "S-DROP", "reject")             # ...with a committed decision to reverse
    _mk_slot(c, "S-REVIEW", review)                # an in-review item (nothing to reverse)
    g2 = _open_gate(c, "S-REVIEW")
    conn.commit()

    a_drop = engine.topic_item_read_model(conn, "S-DROP", "topic")["actions"]
    a_rev = engine.topic_item_read_model(conn, "S-REVIEW", "topic")["actions"]
    check("A reopen allowed for dropped+decision", a_drop["reopen"]["allowed"], True)
    check("A reopen denied for in-review (nothing_to_reverse)",
          (a_rev["reopen"]["allowed"], a_rev["reopen"].get("reason")), (False, "nothing_to_reverse"))
    check("A reopen is a DISTINCT key from restore", "restore" in a_drop and "reopen" in a_drop, True)

    # === B/C. authoritative gate projection + PRINCIPAL-BOUND undecide (Codex P1) ===
    # B1 + C: exactly one open gate holding THIS actor's decision -> gate_id set, undecide allowed
    rm_drop = engine.topic_item_read_model(conn, "S-DROP", "topic", APPROVER)
    check("B1 authoritative_gate_id set (exactly one gate)", rm_drop["authoritative_gate_id"], str(g1))
    check("B1 undecide allowed for the DECIDING principal", rm_drop["actions"]["undecide"]["allowed"], True)
    # P1 (A-vs-B): a DIFFERENT principal has NO decision here, so undecide is unavailable for them even
    # though approver A does have one — the projection binds to the caller, never any approver.
    p1_b = engine.topic_item_read_model(conn, "S-DROP", "topic", OTHER)["actions"]["undecide"]
    check("P1 undecide unavailable(no_decision) for a NON-deciding principal (A-vs-B)",
          (p1_b["allowed"], p1_b.get("reason")), (False, "no_decision"))
    # P1: an UNSIGNED read cannot confirm the caller -> principal_missing (never leaks A's undo-ability)
    p1_u = engine.topic_item_read_model(conn, "S-DROP", "topic", None)["actions"]["undecide"]
    check("P1 undecide principal_missing for an unsigned read",
          (p1_u["allowed"], p1_u.get("reason")), (False, "principal_missing"))

    # B4: one open gate, the actor has NO decision -> undecide unavailable(no_decision)
    b4 = engine.topic_item_read_model(conn, "S-REVIEW", "topic", APPROVER)["actions"]["undecide"]
    check("B4 undecide unavailable no_decision (in-review, no decision)", (b4["allowed"], b4.get("reason")), (False, "no_decision"))

    # B2: zero open gates -> gate_id null, undecide unavailable(no_open_gate)
    _mk_slot(c, "S-NOGATE", review)
    conn.commit()
    rm_nogate = engine.topic_item_read_model(conn, "S-NOGATE", "topic")
    check("B2 authoritative_gate_id null (zero gates)", rm_nogate["authoritative_gate_id"], None)
    check("B2 undecide unavailable no_open_gate",
          (rm_nogate["actions"]["undecide"]["allowed"], rm_nogate["actions"]["undecide"].get("reason")),
          (False, "no_open_gate"))

    # B3 (RED): MULTIPLE open gates for the same slot+stage -> gate_id null, ambiguous — NEVER a latest-pick
    _mk_slot(c, "S-DUP", review)
    _open_gate(c, "S-DUP")
    _open_gate(c, "S-DUP")                          # a second open gate for the same slot+stage
    conn.commit()
    rm_dup = engine.topic_item_read_model(conn, "S-DUP", "topic")
    check("B3 authoritative_gate_id null when >1 gate (no latest-pick)", rm_dup["authoritative_gate_id"], None)
    check("B3 undecide unavailable ambiguous_gate",
          (rm_dup["actions"]["undecide"]["allowed"], rm_dup["actions"]["undecide"].get("reason")),
          (False, "ambiguous_gate"))

    # === P1. clear_decision is OWNER-BOUND, TRUTHFUL and FAIL-CLOSED on a zero-delete ===
    # A non-owner clear would delete zero rows -> it must RAISE, never report a phantom success.
    try:
        engine.clear_decision(conn, g1, OTHER, slot_ids=["S-DROP"], actor=OTHER)
        check("P1 non-owner clear fails closed (zero-delete raises)", "no_raise", "raise")
    except engine.GateError:
        check("P1 non-owner clear fails closed (zero-delete raises)", "raise", "raise")
    ck = _cur(conn)
    ck.execute("SELECT 1 FROM gate_decision WHERE gate_id=%s AND slot_id='S-DROP' AND approver_id=%s", (g1, APPROVER))
    check("P1 owner decision INTACT after the refused non-owner clear", ck.fetchone() is not None, True)
    # The OWNER clears their own decision -> succeeds and removes exactly it.
    res = engine.clear_decision(conn, g1, APPROVER, slot_ids=["S-DROP"], actor=APPROVER)
    check("P1 owner clear succeeds (reports the real deletion)", "S-DROP" in res.get("cleared", []), True)
    ck.execute("SELECT 1 FROM gate_decision WHERE gate_id=%s AND slot_id='S-DROP' AND approver_id=%s", (g1, APPROVER))
    check("P1 owner decision REMOVED after the owner clear", ck.fetchone() is None, True)
    ck.close()

    wipe(conn)
    c.close()
    conn.close()
    print(f"\n{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
