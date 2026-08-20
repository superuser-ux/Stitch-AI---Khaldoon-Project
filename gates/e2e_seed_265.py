"""Seed/reset the isolated #265 E2E fixture round (R265E) for the gate-reconcile Playwright spec.
Idempotent; never touches RE2E or any real round. Modes:

  partial — 2 slots generated (TOPIC_PROPOSED) + 4 still awaiting generation (SCHEDULE_APPROVED),
            PLUS the seeded-legacy 2-target open gate: models the live regression mid-generation
            (the UI must show generate + the held-gate warning, never start_review).
  legacy  — all 6 generated + the seeded-legacy 2-target open gate: models the post-generation
            inconsistent state that bounded reconciliation must heal to 6 targets on read.
  clean   — teardown only.

  docker exec -w /work tanaghom-gateapi python gates/e2e_seed_265.py <mode>
"""
import os
import sys

import psycopg2  # noqa: F401  (engine brings the driver; kept for parity with e2e_seed.py)

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402

RID = "R265E"
# valid pillar/HCS taxonomy pairs (same catalogue rows the RE2E fixture relies on) + real content
# formats so the topic cards resolve their framework exactly like a planner-assigned round
SLOTS = [("R265E-1", "P1_SELF", "1.1", "Hero Reel"),
         ("R265E-2", "P2_RELATIONSHIPS", "2.1", "Carousel"),
         ("R265E-3", "P3_PARENTING", "3.1", "Pic + Caption"),
         ("R265E-4", "P1_SELF", "1.2", "Hero Reel"),
         ("R265E-5", "P2_RELATIONSHIPS", "2.2", "Carousel"),
         ("R265E-6", "P1_SELF", "1.3", "Pic + Caption")]


def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'R265E-%%'")
    cur.execute("DELETE FROM slot  WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()


def seed(conn, generated):
    """Insert the round + 6 slots; the first `generated` are TOPIC_PROPOSED (with topic rows), the
    rest sit at SCHEDULE_APPROVED = the topic writer's input status (still awaiting generation)."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id)
                   VALUES (%s,'e2e-265',2,3,'["09:00"]','{}','{}','planning','e2e')""", (RID,))
    for i, (sid, pillar, hcs, fmt) in enumerate(SLOTS, 1):
        status = "TOPIC_PROPOSED" if i <= generated else "SCHEDULE_APPROVED"
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,topic_angle,hook_text,format,tenant_id)
                       VALUES (%s,%s,%s,'09:00',%s,%s,'L1','Painful Truth',%s,1,
                               'زاوية اختبار','خليك أقوى من خوفك',%s,'e2e')""",
                    (sid, RID, (i + 2) // 3, pillar, hcs, status, fmt))
        if i <= generated:
            cur.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,
                           rationale_ar,rationale_en,hook_text,hook_type,revision,tenant_id)
                           VALUES (%s,%s,'L1',%s,1,'زاوية اختبار','سبب','because it matters',
                                   'خليك أقوى من خوفك','Painful Truth',1,'e2e')""", (sid, hcs, RID))
    conn.commit()


def legacy_gate(conn):
    """The seeded-legacy inconsistency (regression fixture, NOT newly-permitted behaviour): an open
    round/stage gate targeting only the first 2 of the round's eligible slots."""
    cfg = engine.load_config()
    pol = engine.stage_approval_contract(cfg, "topic_review", conn=conn)
    cur = conn.cursor()
    cur.execute("INSERT INTO gate (scope,stage,policy,rule_key,quorum,status) "
                "VALUES ('batch','topic_review','fixed',%s,%s,'open') RETURNING gate_id",
                (pol["rule_key"], str(pol["quorum"])))
    gid = cur.fetchone()[0]
    cur.execute("INSERT INTO gate_target (gate_id,slot_id) VALUES (%s,'R265E-1'),(%s,'R265E-2')",
                (gid, gid))
    conn.commit()
    return gid


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "legacy").strip()
    if mode not in ("partial", "legacy", "clean"):
        raise SystemExit(f"unknown mode {mode!r} (expected partial | legacy | clean)")
    conn = engine.db_connect()
    teardown(conn)
    if mode != "clean":
        seed(conn, generated=2 if mode == "partial" else 6)
        gid = legacy_gate(conn)
        print(f"seeded {RID} [{mode}]: legacy 2-target gate {str(gid)[:8]} open")
    else:
        print(f"cleaned {RID}")
    conn.close()


if __name__ == "__main__":
    main()
