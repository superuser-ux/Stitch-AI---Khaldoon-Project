"""Seed/reset an isolated schedule-stage round (RSCH) with an OPEN schedule_review gate (#175).
The gate's assignment snapshot is the configured khal-only schedule policy, so the round is the
Playwright fixture for the not-assigned reviewer UX: Nour must see view-only guidance, Khal must
keep deciding. Idempotent — always resets to a clean 3-slot RESERVED start. Run like e2e_seed.py:

  docker exec -w /work tanaghom-gateapi python gates/e2e_schedule_seed.py
"""
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402

RID = "RSCH"
SLOTS = [("RSCH-1", "P1_SELF", "1.1", "Hero Reel"),
         ("RSCH-2", "P2_RELATIONSHIPS", "2.1", "Carousel"),
         ("RSCH-3", "P3_PARENTING", "3.1", "Pic + Caption")]


def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RSCH-%%'")
    cur.execute("DELETE FROM slot  WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()


def seed(conn):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id)
                   VALUES (%s,'e2e schedule',1,3,'["09:00"]','{}','{}','planning','e2e')""", (RID,))
    for sid, pillar, hcs, fmt in SLOTS:
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,format,tenant_id)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','RESERVED',1,%s,'e2e')""",
                    (sid, RID, pillar, hcs, fmt))
    conn.commit()


def main():
    conn = engine.db_connect()
    teardown(conn)
    seed(conn)
    gid = engine.open_gate(conn, "schedule_review", round_id=RID, actor="e2e")
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM slot WHERE round_id=%s GROUP BY status", (RID,))
    print(f"seeded {RID}: {dict(cur.fetchall())}  schedule gate {str(gid)[:8]} open")
    conn.close()


if __name__ == "__main__":
    main()
