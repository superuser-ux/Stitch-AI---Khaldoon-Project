"""Seed/reset isolated operational-stage rounds for Playwright browser validation.

Rounds:
  - RPROD: production_review open on READY_FOR_PRODUCTION slots
  - REDIT: edit_review open on PRODUCED slots
  - RDIST: distribution_review open on EDITED slots
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import directives  # noqa: E402
import engine  # noqa: E402
import dam  # noqa: E402

CFG = engine.load_config()
ROUNDS = {
    "RPROD": {"label": "ops-production-e2e", "status": "READY_FOR_PRODUCTION", "gate": "production_review", "emit_stage": "script"},
    "REDIT": {"label": "ops-edit-e2e", "status": "PRODUCED", "gate": "edit_review", "emit_stage": "production"},
    "RDIST": {"label": "ops-distribution-e2e", "status": "EDITED", "gate": "distribution_review", "emit_stage": "media_edit"},
}
SLOTS = [
    ("P1_SELF", "1.1", "Hero Reel", "النسخة التشغيلية الأولى", "هوك تشغيلي أول", "نص تشغيلي أول\n\n— سطر أخير"),
    ("P2_RELATIONSHIPS", "2.1", "Carousel", "النسخة التشغيلية الثانية", "هوك تشغيلي ثان", "نص تشغيلي ثان\n\n— سطر أخير"),
]


def teardown(conn):
    cur = conn.cursor()
    for rid in ROUNDS:
        # #250 — sdam rows are append-only/immutable by design and FK the assets below (NO ACTION);
        # bypass the guards transiently for THIS isolated fixture round's teardown only.
        cur.execute("SET session_replication_role = replica")
        cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id LIKE %s)", (f"{rid}-%",))
        cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id LIKE %s", (f"{rid}-%",))
        cur.execute("SET session_replication_role = DEFAULT")
        cur.execute(
            "DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)",
            (rid,),
        )
        for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
            cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
        cur.execute("DELETE FROM audit_log WHERE entity_id LIKE %s", (f"{rid}-%",))
        cur.execute("DELETE FROM slot WHERE round_id=%s", (rid,))
        cur.execute("DELETE FROM round WHERE round_id=%s", (rid,))
    conn.commit()


def insert_round(cur, rid, label):
    cur.execute(
        """INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
               pillar_distribution,format_distribution,status,tenant_id)
           VALUES (%s,%s,1,2,'["09:00","20:00"]','{}','{}','planning','e2e')""",
        (rid, label),
    )


def insert_slot_bundle(cur, rid, sid, time_uae, pillar, hcs, fmt, angle, hook, script_ar, status):
    cur.execute(
        """INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,format,
               hook_type,status,cycle_no,topic_angle,hook_text,tenant_id)
           VALUES (%s,%s,1,%s,%s,%s,'L1',%s,'Painful Truth',%s,1,%s,%s,%s)""",
        (sid, rid, time_uae, pillar, hcs, fmt, status, angle, hook, "e2e"),
    )
    cur.execute(
        """INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,
               rationale_ar,rationale_en,hook_text,hook_type,revision,tenant_id)
           VALUES (%s,%s,'L1',%s,1,%s,'سبب','because it matters',%s,'Painful Truth',1,%s)""",
        (sid, hcs, rid, angle, hook, "e2e"),
    )
    cur.execute(
        """INSERT INTO script (slot_id,hcs_id,lens,script_ar,structure,final_line,delivery_notes,
               delivery_check,used_islamic_anchor,needs_scholar_review,needs_native_review,flags,
               model,revision,feedback,tenant_id)
           VALUES (%s,%s,'L1',%s,'[]','سطر أخير','[]','{}',false,false,false,'[]',
               'e2e-ops',1,NULL,%s)""",
        (sid, hcs, script_ar, "e2e"),
    )


def seed_round(conn, rid, meta):
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    insert_round(cur, rid, meta["label"])
    for index, (pillar, hcs, fmt, angle, hook, script_ar) in enumerate(SLOTS, start=1):
        sid = f"{rid}-{index}"
        time_uae = "09:00" if index == 1 else "20:00"
        insert_slot_bundle(cur, rid, sid, time_uae, pillar, hcs, fmt, angle, hook, script_ar, meta["status"])
        if meta["emit_stage"] in ("production", "media_edit"):
            dam.add_asset(conn, sid, "production", "raw_cut", uri=f"placeholder://raw/{sid}", actor="e2e")
        if meta["emit_stage"] == "media_edit":
            dam.add_asset(conn, sid, "media_edit", "edit", uri=f"placeholder://edit/{sid}", actor="e2e")
        directives.emit_output(cur, sid, meta["emit_stage"], CFG, actor="e2e")
    conn.commit()
    engine.open_gate(conn, meta["gate"], round_id=rid, actor="e2e")


def main():
    conn = engine.db_connect()
    teardown(conn)
    for rid, meta in ROUNDS.items():
        seed_round(conn, rid, meta)
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    for rid, meta in ROUNDS.items():
        cur.execute("SELECT status, count(*) FROM slot WHERE round_id=%s GROUP BY status", (rid,))
        counts = {row["status"]: row["count"] for row in cur.fetchall()}
        print(f"seeded {rid}: {counts}  {meta['gate']} open")
    conn.close()


if __name__ == "__main__":
    main()
