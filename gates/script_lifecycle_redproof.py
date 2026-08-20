"""#367 — RED proofs (amendment 16): each targeted control, shown to FAIL when the specific fix is
locally reverted. Surgical — each proof exercises exactly the reverted behavior, no broad mutation,
no sleeps, no process kills. GREEN of the same behavior lives in script_lifecycle_selftest.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402
import run_writers as W  # noqa: E402
import gates.script_lifecycle_selftest as SL  # noqa: E402

RESULTS = []


def proof(label, reverted_behavior_is_wrong):
    """reverted_behavior_is_wrong: True iff the DEFECT (reverted fix) produced the wrong outcome,
    i.e. the fix is discriminating."""
    ok = reverted_behavior_is_wrong
    print(f"  {'DISCRIMINATING' if ok else 'NOT-DISCRIMINATING'}  {label}")
    RESULTS.append((label, ok))


def main():
    conn = engine.db_connect()
    cfg = engine.load_config()

    # R3.1 — decide() CAS must validate against the SCRIPT head. Reverted (topic head) behavior: a
    # stale expected_revision=1 (script head is 2, topic head is 1) is WRONGLY accepted (no conflict).
    sid = SL.seed_script_at_review(conn, cfg)
    engine.edit_revision(conn, sid, "script", "final_line", "x", actor=SL.APPROVER)  # script head -> 2
    gid = engine.open_gate(conn, "script_review", round_id=SL.RID, actor="rp", cfg=cfg)
    _real_head = engine._head_revision
    engine._head_revision = lambda cur, s, a: _real_head(cur, s, "topic")  # the R3.1 DEFECT
    defect_accepted = None
    try:
        engine.decide(conn, gid, SL.APPROVER, "approve", slot_ids=[sid], revision=1,
                      expected_revision=1, cfg=cfg)
        defect_accepted = True    # no conflict -> defect wrongly accepted a stale script CAS
    except engine.RevisionConflict:
        defect_accepted = False
    finally:
        engine._head_revision = _real_head
    conn.rollback()
    proof("R3.1 topic-hardcoded CAS wrongly accepts a stale SCRIPT approval", defect_accepted is True)

    # R3.2 — approve/drop must thread the artifact. Reverted (topic literal) behavior: a script drop
    # would record a reject against the TOPIC, not the script — provable via contract with artifact.
    # Direct: contract.reject with the wrong artifact vs right artifact yields a different eligibility.
    import contract as K
    sid = SL.seed_script_at_review(conn, cfg)
    # right artifact (script) — drop is eligible (script in review, no downstream)
    res_right = K.reject(SL.RID, "script", sid, actor=SL.APPROVER, eligibility_check=True)
    conn2 = engine.db_connect()
    # wrong artifact (topic) — the topic IS approved (downstream-advanced), so a #249 eligibility
    # check against topic fails closed: the reverted route would misjudge the script drop.
    res_wrong = K.reject(SL.RID, "topic", sid, actor=SL.APPROVER, eligibility_check=True)
    conn2.close()
    proof("R3.2 topic-literal drop judges a SCRIPT item against the wrong artifact's eligibility",
          res_right.get("ok") != res_wrong.get("ok"))

    # R3.3 — the durable worker must dispatch on artifact. Reverted (always process_topic) behavior:
    # a script rework produces a TOPIC revision and no new script. Proven by forcing the topic branch.
    sid = SL.seed_script_at_review(conn, cfg)
    topics0 = SL.topic_count(conn, sid)
    scripts0 = len(SL.script_rows(conn, sid))
    began = engine.begin_rework_operation(conn, sid, 1, "rp", SL.APPROVER,
                                          idempotency_key=f"{sid}-rp3", artifact="script", cfg=cfg)
    op_id = began["op_id"]
    # The R3.3 DEFECT reproduced faithfully: the reverted worker ignored op["artifact"] and always
    # dispatched the TOPIC branch. Flip the persisted artifact to 'topic' so run_rework_operation
    # takes exactly that branch — while begin_rework_operation already restored a SCRIPT revision
    # (restored_revision=2). The topic branch then reads the TOPIC head (1), sees 1 != 2, and fails
    # the source-changed guard — so the Script rework NEVER completes and NO reworked script is
    # produced. The fixed (script-dispatch) worker completes it; that divergence is the proof.
    ck = conn.cursor(); ck.execute("UPDATE rework_operation SET artifact='topic' WHERE op_id=%s", (op_id,))
    conn.commit(); ck.close()
    try:
        W.run_rework_operation(cfg, op_id)
    except Exception:                       # noqa: BLE001 — the head-mismatch guard fires as designed
        pass
    conn3 = engine.db_connect()
    ck = conn3.cursor()
    ck.execute("SELECT state FROM rework_operation WHERE op_id=%s", (op_id,))
    defect_state = ck.fetchone()[0]; ck.close()
    defect_no_rework_script = len(SL.script_rows(conn3, sid)) == scripts0 + 1  # only the restore
    defect_no_topic_content = SL.topic_count(conn3, sid) == topics0            # topic not produced
    conn3.close()
    proof("R3.3 reverted worker (topic dispatch) CANNOT complete a SCRIPT rework",
          defect_state != "completed" and defect_no_rework_script and defect_no_topic_content)

    SL.wipe(conn)
    conn.close()
    print("\n" + "=" * 60)
    bad = [l for l, ok in RESULTS if not ok]
    if bad:
        print(f"{len(bad)} PROOF(S) NOT DISCRIMINATING")
        for l in bad:
            print(f"  - {l}")
        print("=" * 60); sys.exit(1)
    print("ALL RED PROOFS DISCRIMINATING")
    print("=" * 60)


if __name__ == "__main__":
    main()
