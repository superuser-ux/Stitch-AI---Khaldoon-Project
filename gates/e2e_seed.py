"""Seed/reset the isolated E2E round (RE2E) for the Playwright UI suite, and open its topic gate.
Idempotent — always resets to a clean 3-topic TOPIC_PROPOSED start. The UI now has an explicit
schedule-first flow for normal runs, but this fixture still seeds a direct topic-review round for
focused regression coverage. Run in a container on the
tanaghom network (DB=db). The dashboard then shows RE2E and Playwright drives the real UI.

  docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
    -v "$PWD":/work -w /work python:3.12-slim \
    bash -lc "pip install -q -r gates/requirements.txt && python gates/e2e_seed.py"
"""
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402

RID = "RE2E"
# Each slot carries a real content_format name so the topic card resolves the managed framework
# (name + component steps) the same way a planner-assigned round would — distinct formats prove the
# card's framework join is per-slot, not a single hardcoded lookup.
SLOTS = [("RE2E-1", "P1_SELF", "1.1", "الزاوية الأصلية للذات", "Hero Reel"),
         ("RE2E-2", "P2_RELATIONSHIPS", "2.1", "الزاوية الأصلية للعلاقات", "Carousel"),
         ("RE2E-3", "P3_PARENTING", "3.1", "الزاوية الأصلية للأبوة", "Pic + Caption")]


def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RE2E-%%'")
    cur.execute("DELETE FROM slot  WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()


def seed(conn):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id)
                   VALUES (%s,'e2e',1,3,'["09:00"]','{}','{}','planning','e2e')""", (RID,))
    for sid, pillar, hcs, angle, fmt in SLOTS:
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,topic_angle,hook_text,format,tenant_id)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','TOPIC_PROPOSED',1,%s,'خليك أقوى من خوفك',%s,%s)""",
                    (sid, RID, pillar, hcs, angle, fmt, "e2e"))
        cur.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,
                       rationale_ar,rationale_en,hook_text,hook_type,revision,tenant_id)
                       VALUES (%s,%s,'L1',%s,1,%s,'سبب','because it matters','خليك أقوى من خوفك','Painful Truth',1,%s)""",
                    (sid, hcs, RID, angle, "e2e"))
    conn.commit()


def main():
    conn = engine.db_connect()
    teardown(conn)
    seed(conn)
    gid = engine.open_gate(conn, "topic_review", round_id=RID, actor="e2e")
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM slot WHERE round_id=%s GROUP BY status", (RID,))
    print(f"seeded {RID}: {dict(cur.fetchall())}  topic gate {str(gid)[:8]} open")
    conn.close()


if __name__ == "__main__":
    main()
