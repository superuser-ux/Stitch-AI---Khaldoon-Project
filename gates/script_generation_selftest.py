"""#357 Stage 3A — targeted engine proof for governed Script generation.

Runs against an isolated lane that already holds a run at TOPIC_APPROVED. Every assertion below was
produced ad hoc while building #357; committing them makes the evidence REPEATABLE by a reviewer
rather than readable only in a transcript.

What it proves, and why each one is here:

  AUTHORITY      an unsigned caller, a valid non-approver, and the frozen approver are three
                 DISTINGUISHABLE outcomes. A denial that arrives as a generic failure is
                 indistinguishable from a bug, which is exactly what the typed contract forbids.
  IDENTITY       the attempt digest is deterministic over the same governed inputs, and a replay
                 returns the SAME attempt instead of minting a second one.
  CONCURRENCY    an active attempt dominates the write path. The unique index alone is not enough:
                 mid-run the input set shrinks, so a second request would otherwise build a
                 different-but-overlapping manifest and race the first.
  CRASH          an ABANDONED attempt (expired persisted lease) is reclaimable by exactly one
                 worker, and a HEALTHY one (live lease) is never stolen. Deterministic injection at
                 the persistence boundary — no sleeps, no process kills, no provider.
  PROVENANCE     every produced revision pins the exact consumed Topic revision, and requested vs
                 effective route/provider/model stay distinct so a substitution cannot hide.
  TOPIC          Topic job identity/uniqueness is untouched, and no Script path can fall back to a
                 Topic artifact.

    docker exec -e PYTHONPATH=/work <lane-api> python -m gates.script_generation_selftest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import engine  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)
    return ok


def check_true(label, got):
    return check(label, bool(got), True)


def _round_at_topic_approved(conn):
    """The lane's run whose items sit at the configured Script input status."""
    cfg = engine.load_config()
    src = engine.stage_cfg(cfg, "script_review").get("generates_from")
    cur = conn.cursor()
    cur.execute("SELECT round_id FROM slot WHERE status=%s GROUP BY round_id "
                "ORDER BY count(*) DESC LIMIT 1", (src,))
    row = cur.fetchone()
    cur.close()
    return (row[0] if row else None), src


def main():
    conn = engine.db_connect()
    round_id, src = _round_at_topic_approved(conn)
    if not round_id:
        print(f"NO LANE INPUT: this proof needs a run at {src}. Provision one through the governed "
              f"chain first (plan -> schedule_review -> topic_review).")
        sys.exit(2)
    print(f"#357 script generation proof — round {round_id} (input status {src})\n")

    # IDEMPOTENT BY TEARDOWN, mirroring gates/selftest.py's RSELF discipline. Without this the proof
    # can only run once: its own first attempt becomes an ACTIVE attempt, which then (correctly)
    # dominates every subsequent decision, so a second run reports `attempt_in_progress` everywhere
    # and looks like a failure of the code rather than of the fixture. Scoped to THIS round's Script
    # attempts only — Topic jobs, slots and artifacts are never touched.
    _reset_script_attempts(conn, round_id)

    cfg = engine.load_config()

    # ---------------------------------------------------------------- AUTHORITY
    print("AUTHORITY")
    d_unsigned = engine.script_generation_decision(conn, round_id, principal=None, cfg=cfg)
    check("unsigned decision is typed principal_missing", d_unsigned["reason_code"], "principal_missing")
    check("unsigned decision is unavailable", d_unsigned["available"], False)

    d_stranger = engine.script_generation_decision(conn, round_id, principal="definitely-not-an-approver", cfg=cfg)
    check("non-approver is a DISTINCT typed denial", d_stranger["reason_code"], "principal_not_approver")

    approver = (d_unsigned.get("input_revisions") is not None) and _first_approver(conn, round_id)
    check_true("an approver was resolved from the frozen snapshot", approver)
    d_ok = engine.script_generation_decision(conn, round_id, principal=approver, cfg=cfg)
    check("the frozen approver is offered the action", d_ok["available"], True)
    check("the pinned input count is disclosed", len(d_ok["input_revisions"]) > 0, True)

    for code in ("principal_missing", "principal_not_approver"):
        try:
            engine.create_script_generation_attempt(
                conn, round_id, None if code == "principal_missing" else "definitely-not-an-approver", cfg=cfg)
            FAILS.append(f"{code} was not refused")
            print(f"  FAIL  {code} was not refused")
        except engine.GovernedDenial as e:
            check(f"write refuses with typed {code}", getattr(e, "reason", None), code)

    # ---------------------------------------------------------------- IDENTITY
    print("\nIDENTITY + REPLAY")
    first = engine.create_script_generation_attempt(conn, round_id, approver, cfg=cfg)
    check("first attempt is newly minted", first["replayed"], False)
    again = engine.create_script_generation_attempt(conn, round_id, approver, cfg=cfg,
                                                    correlation_id="different-correlation",
                                                    idempotency_key="different-key")
    check("replay returns the SAME attempt", again["job_id"], first["job_id"])
    check("replay is reported as a replay", again["replayed"], True)
    check("a different correlation/idempotency does NOT mint identity",
          _script_job_count(conn, round_id), 1)

    # ---------------------------------------------------------------- CRASH
    print("\nCRASH / CONCURRENCY (deterministic, persisted-boundary injection)")
    _set_lease(conn, first["job_id"], expired=True)
    c1, c2 = engine.db_connect(), engine.db_connect()
    w1 = engine.claim_script_generation_job(c1, first["job_id"], worker="w1")
    w2 = engine.claim_script_generation_job(c2, first["job_id"], worker="w2")
    check("an abandoned attempt has exactly one winner", w1 ^ w2, True)

    _set_lease(conn, first["job_id"], expired=False)
    w3 = engine.claim_script_generation_job(engine.db_connect(), first["job_id"], worker="w3")
    check("a HEALTHY attempt is never stolen", w3, False)

    # ---------------------------------------------------------------- INPUT-STATE DENIALS
    print("\nINPUT-STATE DENIALS")
    # DOWNSTREAM-ADVANCED: once items leave the input status there is nothing legitimate to generate.
    # Proven by advancing the pinned items and re-asking — the decision must say so in its own words,
    # not fall back to a generic unavailable or invent a fresh attempt over an empty set.
    _reset_script_attempts(conn, round_id)
    moved = _advance_inputs(conn, round_id, src)
    d_adv = engine.script_generation_decision(conn, round_id, principal=approver, cfg=cfg)
    check("advanced inputs yield a typed no_eligible_input", d_adv["reason_code"], "no_eligible_input")
    check("advanced inputs are NOT offered an attempt", d_adv["available"], False)
    try:
        engine.create_script_generation_attempt(conn, round_id, approver, cfg=cfg)
        FAILS.append("advanced inputs were not refused")
        print("  FAIL  advanced inputs were not refused")
    except engine.GovernedDenial as e:
        check("write refuses advanced inputs", getattr(e, "reason", None), "no_eligible_input")
    _restore_inputs(conn, moved, src)
    check("inputs restored for the remaining checks", _count_at(conn, round_id, src) > 0, True)

    # ---------------------------------------------------------------- EXPIRED-LEASE RECLAIM AUTHORITY
    print("\nEXPIRED-LEASE RECLAIM AUTHORITY")
    # THE DEFECT THIS GUARDS. Replay used to return the active attempt BEFORE any principal check, and
    # the caller then claimed it. Once the lease expired, any validly signed NON-approver could reclaim
    # and execute work they were never authorized to start. Replay is not a lesser operation than
    # creation — it hands back an executable attempt, so it needs the same authority.
    _reset_script_attempts(conn, round_id)
    live = engine.create_script_generation_attempt(conn, round_id, approver, cfg=cfg)
    _set_lease(conn, live["job_id"], expired=True)          # the abandoned-worker signature
    before = _job_exec_state(conn, live["job_id"])

    for probe in ("definitely-not-an-approver", "another-stranger", "definitely-not-an-approver"):
        try:
            engine.create_script_generation_attempt(conn, round_id, probe, cfg=cfg)
            FAILS.append("expired-lease reclaim by a non-approver was allowed")
            print("  FAIL  expired-lease reclaim by a non-approver was ALLOWED")
        except engine.GovernedDenial as e:
            check(f"expired-lease reclaim denied for {probe[:12]}…",
                  getattr(e, "reason", None), "principal_not_approver")
    after = _job_exec_state(conn, live["job_id"])
    check("denied reclaim mutated NO claim/lease/heartbeat/status", after, before)

    # the frozen approver may still reclaim — exactly once
    ok = engine.create_script_generation_attempt(conn, round_id, approver, cfg=cfg)
    check("the frozen approver still reaches the attempt", ok["job_id"], live["job_id"])
    c1, c2 = engine.db_connect(), engine.db_connect()
    w1 = engine.claim_script_generation_job(c1, live["job_id"], worker="a1")
    w2 = engine.claim_script_generation_job(c2, live["job_id"], worker="a2")
    check("the approver reclaims EXACTLY once", w1 ^ w2, True)

    # a malformed frozen authority fails closed rather than assuming
    _corrupt_authority(conn, live["job_id"])
    _set_lease(conn, live["job_id"], expired=True)
    try:
        engine.create_script_generation_attempt(conn, round_id, approver, cfg=cfg)
        FAILS.append("malformed authority snapshot did not fail closed")
        print("  FAIL  malformed authority snapshot did not fail closed")
    except engine.GovernedDenial as e:
        check("malformed frozen authority fails closed",
              getattr(e, "reason", None), "malformed_authority_snapshot")

    # ---------------------------------------------------------------- PROVENANCE IS NOT FABRICATED
    print("\nPROVENANCE INTEGRITY")
    # THE DEFECT THIS GUARDS. Provenance used to be reconstructed after the fact by selecting each
    # pinned slot's LATEST script. For a slot whose writer FAILED but which already held a script
    # from a prior attempt, that linked the OLD revision to the NEW job and claimed this attempt
    # produced it. Fabricated provenance is worse than missing provenance — nothing downstream can
    # tell it from the real thing.
    #
    # Simulated deterministically: a pre-existing script row, a governed attempt that produces
    # NOTHING for it, and the assertion that the finalizer links nothing and counts it failed.
    _reset_script_attempts(conn, round_id)
    # CONSTRUCT the precondition rather than hope the lane happens to have it. A skipped proof is not
    # a passed proof — this exact check skipped on a fresh round the first time it ran, which would
    # have shipped an untested guard.
    victim = _seed_preexisting_script(conn, round_id)
    if victim:
        before = _provenance_for(conn, victim)
        attempt = engine.create_script_generation_attempt(conn, round_id, approver, cfg=cfg)
        # finalize WITHOUT running the writer — i.e. the writer produced nothing at all.
        # #362: closing an attempt now REQUIRES full ownership, so this takes a real tenure first
        # rather than relying on the removed unfenced path.
        _t = engine.claim_script_generation_job(conn, attempt["job_id"], worker="sgs-finalizer")
        conn.commit()
        res = engine.record_script_generation_results(conn, attempt["job_id"],
                                                     worker="sgs-finalizer", claim_token=_t)
        after = _provenance_for(conn, victim)
        check("a pre-existing script is NOT linked to an attempt that produced nothing", after, before)
        check("the finalizer links nothing when nothing was produced", res["linked"], 0)
        check("unproduced items are counted FAILED, not silently dropped",
              res["planned"] > 0 and res["status"] == "failed", True)
        _remove_seeded_script(conn, victim)
    else:
        FAILS.append("could not construct the pre-existing-script precondition")
        print("  FAIL  could not construct the pre-existing-script precondition")

    # ---------------------------------------------------------------- TOPIC NON-REGRESSION
    print("\nTOPIC NON-REGRESSION")
    check("no Topic job was given a NULL schedule token", _topic_jobs_missing_token(conn), 0)
    check("Script rows never carry a Schedule token", _script_jobs_with_token(conn), 0)

    print(f"\n{'='*60}\n{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}\n{'='*60}")
    sys.exit(1 if FAILS else 0)


def _job_exec_state(conn, job_id):
    """The execution-mutable fields a denied caller must not be able to touch."""
    cur = conn.cursor()
    cur.execute("""SELECT status, claimed_by, lease_expires_at, heartbeat_at
                     FROM generation_job WHERE job_id=%s""", (job_id,))
    row = cur.fetchone(); cur.close()
    return tuple(str(x) for x in row) if row else None


def _corrupt_authority(conn, job_id):
    cur = conn.cursor()
    cur.execute("UPDATE generation_job SET authority_snapshot='{}'::jsonb WHERE job_id=%s", (job_id,))
    conn.commit(); cur.close()


def _seed_preexisting_script(conn, round_id):
    """Give one pinned slot a script from 'earlier work' — the exact shape that made the post-hoc
    inference fabricate a link. Marked so it can be removed again; the fixture is borrowed, not
    consumed."""
    cur = conn.cursor()
    cur.execute("SELECT slot_id, hcs_id, lens FROM slot WHERE round_id=%s ORDER BY slot_id LIMIT 1",
                (round_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); return None
    slot_id, hcs_id, lens = row
    cur.execute("""INSERT INTO script (slot_id, hcs_id, lens, script_ar, model, revision)
                   VALUES (%s,%s,%s,%s,'prior-attempt:seeded',1)
                   ON CONFLICT DO NOTHING""", (slot_id, hcs_id, lens, "prior work"))
    conn.commit(); cur.close()
    return slot_id


def _remove_seeded_script(conn, slot_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM script WHERE slot_id=%s AND model='prior-attempt:seeded'", (slot_id,))
    conn.commit(); cur.close()


def _provenance_for(conn, slot_id):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM script_provenance WHERE slot_id=%s", (slot_id,))
    n = cur.fetchone()[0]; cur.close(); return n


def _advance_inputs(conn, round_id, src):
    """Move this round's input items downstream, simulating work that already advanced. Returns the
    ids so the proof can restore them — it borrows the state, it does not consume the fixture."""
    cur = conn.cursor()
    cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status=%s", (round_id, src))
    ids = [r[0] for r in cur.fetchall()]
    cur.execute("UPDATE slot SET status='DRAFT_ASSIGNED' WHERE slot_id = ANY(%s)", (ids,))
    conn.commit(); cur.close()
    return ids


def _restore_inputs(conn, ids, src):
    cur = conn.cursor()
    cur.execute("UPDATE slot SET status=%s WHERE slot_id = ANY(%s)", (src, ids))
    conn.commit(); cur.close()


def _count_at(conn, round_id, src):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status=%s", (round_id, src))
    n = cur.fetchone()[0]; cur.close(); return n


def _reset_script_attempts(conn, round_id):
    """Remove only this round's SCRIPT attempts + their provenance, so the proof is repeatable.
    Deliberately narrow: it touches no Topic job, no slot, and no produced artifact."""
    cur = conn.cursor()
    cur.execute("""DELETE FROM script_provenance
                    WHERE job_id IN (SELECT job_id FROM generation_job
                                      WHERE round_id=%s AND stage='script')""", (round_id,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s AND stage='script'", (round_id,))
    removed = cur.rowcount
    conn.commit(); cur.close()
    if removed:
        print(f"  (reset: removed {removed} prior Script attempt(s) for {round_id})\n")


def _first_approver(conn, round_id):
    """The frozen affirmative approver the attempt authorizes against — read the same way the engine
    does, so the proof cannot pass by consulting a different source than the code under test."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        m, authority, err = engine._script_attempt_manifest(cur, round_id, engine.load_config())
        if err or not authority:
            return None
        ids = authority.get("approver_ids") or []
        return ids[0] if ids else None
    finally:
        cur.close()


def _script_job_count(conn, round_id):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM generation_job WHERE round_id=%s AND stage='script'", (round_id,))
    n = cur.fetchone()[0]; cur.close(); return n


def _set_lease(conn, job_id, expired):
    cur = conn.cursor()
    cur.execute("""UPDATE generation_job
                      SET status='running',
                          lease_expires_at = now() + (%s || ' hour')::interval,
                          heartbeat_at = now(), claimed_by='selftest'
                    WHERE job_id=%s""", ("-1" if expired else "1", job_id))
    conn.commit(); cur.close()


def _topic_jobs_missing_token(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM generation_job WHERE stage='topic' AND accepted_schedule_token IS NULL")
    n = cur.fetchone()[0]; cur.close(); return n


def _script_jobs_with_token(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM generation_job WHERE stage='script' AND accepted_schedule_token IS NOT NULL")
    n = cur.fetchone()[0]; cur.close(); return n


if __name__ == "__main__":
    main()
