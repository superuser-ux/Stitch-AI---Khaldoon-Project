"""Seed/reset an isolated final-review round for Playwright browser validation."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402

RID = "RFIN"
SLOTS = [
    ("RFIN-1", "P1_SELF", "1.1", "Hero Reel", "الزاوية النهائية الأولى", "هوك نهائي أول", "نص نهائي أول\n\n— سطر أخير"),
    ("RFIN-2", "P2_RELATIONSHIPS", "2.1", "Carousel", "الزاوية النهائية الثانية", "هوك نهائي ثان", "نص نهائي ثان\n\n— سطر أخير"),
]


def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RFIN-%%'")
    cur.execute("DELETE FROM slot WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()


def seed(conn):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
               pillar_distribution,format_distribution,status,tenant_id)
           VALUES (%s,'final-e2e',1,2,'["09:00","20:00"]','{}','{}','planning','e2e')""",
        (RID,),
    )
    for index, (sid, pillar, hcs, fmt, angle, hook, script_ar) in enumerate(SLOTS, start=1):
        time_uae = "09:00" if index == 1 else "20:00"
        cur.execute(
            """INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,format,
                   hook_type,status,cycle_no,topic_angle,hook_text,tenant_id)
               VALUES (%s,%s,1,%s,%s,%s,'L1',%s,'Painful Truth','APPROVED_ASSIGNED',1,%s,%s,%s)""",
            (sid, RID, time_uae, pillar, hcs, fmt, angle, hook, "e2e"),
        )
        cur.execute(
            """INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,
                   rationale_ar,rationale_en,hook_text,hook_type,revision,tenant_id)
               VALUES (%s,%s,'L1',%s,1,%s,'سبب','because it matters',%s,'Painful Truth',1,%s)""",
            (sid, hcs, RID, angle, hook, "e2e"),
        )
        cur.execute(
            """INSERT INTO script (slot_id,hcs_id,lens,script_ar,structure,final_line,delivery_notes,
                   delivery_check,used_islamic_anchor,needs_scholar_review,needs_native_review,flags,
                   model,revision,feedback,tenant_id)
               VALUES (%s,%s,'L1',%s,'[]','سطر أخير','[]','{}',false,false,false,'[]',
                   'e2e-final',1,NULL,%s)""",
            (sid, hcs, script_ar, "e2e"),
        )
    conn.commit()


def main():
    conn = engine.db_connect()
    teardown(conn)
    seed(conn)
    gid = engine.open_gate(conn, "final_review", round_id=RID, actor="e2e")
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM slot WHERE round_id=%s GROUP BY status", (RID,))
    print(f"seeded {RID}: {dict(cur.fetchall())}  final gate {str(gid)[:8]} open")
    conn.close()


if __name__ == "__main__":
    main()
