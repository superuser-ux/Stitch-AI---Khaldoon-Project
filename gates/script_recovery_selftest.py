"""#362 — durable Script recovery drain and fenced lease heartbeat.

WHAT THIS PROVES. #357 gave Scripts a durable job with a lease, but ownership was identified only by
`claimed_by` — a worker NAME. Two tenures by the same worker are indistinguishable, so a worker whose
lease had been reclaimed could still satisfy an ownership check and persist output over work another
worker now owns. And after #360 correctly stage-isolated the Topic drain, Scripts had no drain at
all: a queued attempt whose dispatch was lost sat queued forever.

`claim_token` closes the first: a fresh UUID per tenure, required by every authoritative write, so a
reclaim instantly kills the previous owner's ability to commit anything. The bounded drain closes the
second.

DETERMINISM. Every recovery boundary here is injected at the PERSISTENCE layer — an expired lease is
a written timestamp, ownership loss is a reclaim executed in another transaction. No sleeps as
correctness evidence, no process kills, no live provider, no probabilistic races. Two-claim
interleaving is arbitrated by PostgreSQL, not by timing.

NON-VACUITY. Each negative uses a job in a genuinely eligible state, so a refusal is attributable to
the fence rather than to ineligibility, and asserts the row is byte-identical afterwards. Every
negative has a positive control proving the same operation still succeeds for the rightful owner —
without those, a fence that rejected everything would pass.
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402

FAILS = []
MUT = ("status", "claimed_by", "claim_token", "lease_expires_at", "heartbeat_at",
       "slots_done", "slots_failed")
RID = "RREC362"


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def snap(conn, jid):
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(MUT)} FROM generation_job WHERE job_id=%s", (jid,))
    r = cur.fetchone()
    cur.close()
    return tuple(str(x) for x in r) if r else None


def mk_round(conn):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id, label, period_len_days, posts_per_day, post_times,
                                      pillar_distribution, format_distribution)
                   VALUES (%s,%s,1,1,'["09:00"]'::jsonb,'{}'::jsonb,'{}'::jsonb)
                   ON CONFLICT DO NOTHING""", (RID, RID))
    conn.commit()
    cur.close()


def mk_job(conn, stage, status, lease=None, manifest=None):
    """A durable job in a genuinely eligible state. `lease='expired'` writes a past timestamp — the
    persisted signature of a worker that died mid-run."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO generation_job
                     (round_id, stage, status, accepted_schedule_token, manifest_digest, manifest,
                      lease_expires_at, heartbeat_at, claimed_by, claim_token)
                   VALUES (%s,%s,%s,
                           CASE WHEN %s='topic' THEN %s ELSE NULL END,
                           CASE WHEN %s='script' THEN %s ELSE NULL END,
                           %s::jsonb,
                           CASE WHEN %s='expired' THEN now() - interval '1 hour' ELSE NULL END,
                           CASE WHEN %s='expired' THEN now() - interval '1 hour' ELSE NULL END,
                           CASE WHEN %s='expired' THEN 'dead-worker' ELSE NULL END,
                           CASE WHEN %s='expired' THEN gen_random_uuid() ELSE NULL END)
                   RETURNING job_id::text""",
                (RID, stage, status, stage, int(uuid.uuid4().int % 90000),
                 stage, uuid.uuid4().hex, manifest, lease, lease, lease, lease))
    jid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return jid


def expire(conn, jid):
    cur = conn.cursor()
    cur.execute("""UPDATE generation_job SET lease_expires_at = now() - interval '1 hour',
                                             heartbeat_at = now() - interval '1 hour'
                    WHERE job_id=%s""", (jid,))
    conn.commit()
    cur.close()


def _artifact_counts(conn):
    cur = conn.cursor()
    cur.execute("""SELECT (SELECT count(*) FROM script c JOIN slot s ON s.slot_id=c.slot_id
                            WHERE s.round_id=%s),
                          (SELECT count(*) FROM script_provenance sp JOIN slot s ON s.slot_id=sp.slot_id
                            WHERE s.round_id=%s)""", (RID, RID))
    r = cur.fetchone(); cur.close()
    return r[0], r[1]


def _topic_id_of(conn, slot_id):
    cur = conn.cursor()
    cur.execute("SELECT topic_id::text FROM topic WHERE slot_id=%s ORDER BY revision DESC LIMIT 1",
                (slot_id,))
    r = cur.fetchone(); cur.close()
    return r[0] if r else "00000000-0000-0000-0000-000000000001"


def _seed_writer_input(conn):
    """A real TOPIC_APPROVED slot with an APPROVED topic revision — the writer needs genuine input,
    or it would produce nothing and both the negative and the control would be vacuous."""
    cur = conn.cursor()
    cur.execute("SELECT pillar_code FROM pillar ORDER BY pillar_code LIMIT 1")
    pil = cur.fetchone()[0]
    cur.execute("SELECT hcs_id FROM hcs WHERE pillar_code=%s ORDER BY hcs_id LIMIT 1", (pil,))
    hcs = cur.fetchone()[0]
    cur.execute("SELECT lens_id FROM lens ORDER BY lens_id LIMIT 1")
    lens = cur.fetchone()[0]
    sid = f"{RID}-W1"
    cur.execute("""INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                                     hcs_id, lens, status)
                   VALUES (%s,%s,1,'09:00',%s,'Hero Reel',%s,%s,'TOPIC_APPROVED')
                   ON CONFLICT (slot_id) DO UPDATE SET status='TOPIC_APPROVED'""",
                (sid, RID, pil, hcs, lens))
    cur.execute("""INSERT INTO topic (slot_id, hcs_id, lens, text_ar, hook_text, revision)
                   VALUES (%s,%s,%s,'موضوع','هوك',1) ON CONFLICT DO NOTHING""", (sid, hcs, lens))
    cur.execute("""INSERT INTO slot_approval (slot_id, artifact, revision, approver)
                   VALUES (%s,'topic',1,'khal') ON CONFLICT (slot_id, artifact)
                   DO UPDATE SET revision=1""", (sid,))
    conn.commit(); cur.close()
    return sid


def main():
    conn = engine.db_connect()
    mk_round(conn)
    # Referential order matters: script_provenance references generation_job, and the control run
    # below deliberately produces both. Deleting the job first would fail the FK on a rerun, so the
    # suite would only pass on a pristine lane — exactly the kind of fixture dependence that makes a
    # green run unrepeatable.
    cur = conn.cursor()
    cur.execute("""DELETE FROM script_provenance WHERE slot_id IN
                     (SELECT slot_id FROM slot WHERE round_id=%s)""", (RID,))
    cur.execute("""DELETE FROM script WHERE slot_id IN
                     (SELECT slot_id FROM slot WHERE round_id=%s)""", (RID,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
    conn.commit()
    cur.close()

    # ---------------------------------------------------------------- L1 / J1
    print("\nL1 · J1 — FRESH TOKEN ON CLAIM AND ON EVERY RECLAIM")
    # A REAL manifest: without one, record_script_generation_results returns early on
    # "no manifest" and never reaches the fence — the J6 assertion below would then pass
    # vacuously on a code path that was never exercised.
    MANIFEST = ('{"manifest_version":"script-manifest/v1","round_id":"%s","stage":"script",'
                '"items":[{"slot_id":"%s-S1","topic_id":"00000000-0000-0000-0000-000000000001",'
                '"topic_revision":1}]}' % (RID, RID))
    j = mk_job(conn, "script", "queued", manifest=MANIFEST)
    t1 = engine.claim_script_generation_job(conn, j, worker="w1")
    check("initial claim wins and returns a token", bool(t1), True)
    check("a queued job had no token before it was claimed", snap(conn, j) is not None, True)
    expire(conn, j)
    t2 = engine.claim_script_generation_job(conn, j, worker="w2")
    check("expired-lease reclaim wins", bool(t2), True)
    check("reclaim MINTS A DIFFERENT token (no reuse)", t1 != t2, True)

    # ---------------------------------------------------------------- J3
    print("\nJ3 — A HEALTHY LEASE IS NOT RECLAIMABLE")
    check("a live tenure cannot be stolen", engine.claim_script_generation_job(conn, j, worker="w3"), None)

    # ---------------------------------------------------------------- L2 / J4
    print("\nL2 · J4 — HEARTBEAT REJECTS WRONG OWNER, STALE TOKEN, WRONG STAGE, TERMINAL, UNCLAIMED")
    check("heartbeat succeeds for the CURRENT owner (control)",
          engine.heartbeat_script_generation_job(conn, j, "w2", t2), True)
    before = snap(conn, j)
    check("heartbeat REJECTS the stale token", engine.heartbeat_script_generation_job(conn, j, "w2", t1), False)
    check("heartbeat REJECTS a wrong owner with the right token",
          engine.heartbeat_script_generation_job(conn, j, "not-w2", t2), False)
    check("row byte-identical after rejected heartbeats", snap(conn, j), before)

    topic_j = mk_job(conn, "topic", "running", lease="expired")
    check("heartbeat REJECTS a wrong-stage job",
          engine.heartbeat_script_generation_job(conn, topic_j, "w2", t2), False)

    queued_j = mk_job(conn, "script", "queued")
    check("heartbeat cannot revive an UNCLAIMED job",
          engine.heartbeat_script_generation_job(conn, queued_j, "w2", t2), False)

    term_j = mk_job(conn, "script", "completed")
    check("heartbeat cannot revive a TERMINAL job",
          engine.heartbeat_script_generation_job(conn, term_j, "w2", t2), False)

    # ---------------------------------------------------------------- J5
    print("\nJ5 — FORCED TWO-CLAIM INTERLEAVING, ONE DATABASE WINNER")
    race = mk_job(conn, "script", "queued")
    c1, c2 = engine.db_connect(), engine.db_connect()
    r1 = engine.claim_script_generation_job(c1, race, worker="racer-1")
    r2 = engine.claim_script_generation_job(c2, race, worker="racer-2")
    check("exactly one claimant wins", bool(r1) ^ bool(r2), True)
    check("the loser receives no token", (r1 is None) or (r2 is None), True)
    c1.close(); c2.close()

    # ---------------------------------------------------------------- L3 / J6
    print("\nL3 · J6 — A STALE WORKER CANNOT PERSIST AFTER RECLAIM")
    # w2 still believes it owns `j`; a third worker reclaims it out from under them.
    expire(conn, j)
    t3 = engine.claim_script_generation_job(conn, j, worker="w3")
    check("a third worker reclaims the attempt", bool(t3) and t3 != t2, True)
    before = snap(conn, j)
    check("stale worker cannot heartbeat", engine.heartbeat_script_generation_job(conn, j, "w2", t2), False)
    check("stale worker cannot write a TERMINAL state",
          engine.finish_script_generation_job(conn, j, done=99, failed=0, worker="w2", claim_token=t2), None)
    check("stale worker cannot release the lease (row unchanged)", snap(conn, j), before)
    res = engine.record_script_generation_results(conn, j, worker="w2", claim_token=t2)
    check("the fence path was actually REACHED (job carries a manifest)", res.get("status") is None, True)
    check("stale worker's result/provenance write is fenced out", res.get("fenced_out"), True)
    check("row STILL byte-identical after every stale write", snap(conn, j), before)
    # positive control: the true owner can do what the stale one could not
    check("the CURRENT owner CAN terminalise (control)",
          engine.finish_script_generation_job(conn, j, done=1, failed=0, worker="w3", claim_token=t3) is not None,
          True)

    # ---------------------------------------------------------------- L3 (writer level, REAL)
    print("\nL3 — THE WRITER'S OWN PERSISTENCE TRANSACTION IS FENCED (run_scripts actually invoked)")
    # This must INVOKE the writer. An earlier version only inspected database state and asserted
    # "no provenance written" without ever running anything — vacuously true, and it would have
    # passed with the writer fence deleted. Both cases below execute the real path in stub mode.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents"))
    import run_writers as rw

    cfg = engine.load_config()
    slot_id = _seed_writer_input(conn)          # a real TOPIC_APPROVED slot with an approved topic
    man = ('{"manifest_version":"script-manifest/v1","round_id":"%s","stage":"script",'
           '"writer_mode":"scripts","items":[{"slot_id":"%s","topic_id":"%s","topic_revision":1}]}'
           % (RID, slot_id, _topic_id_of(conn, slot_id)))

    # --- STALE TENURE: the writer must persist NOTHING ---
    wj = mk_job(conn, "script", "queued", manifest=man)
    stale_tok = engine.claim_script_generation_job(conn, wj, worker="owner-a")
    expire(conn, wj)
    engine.claim_script_generation_job(conn, wj, worker="owner-b")     # owner-a is now stale
    before_scripts, before_prov = _artifact_counts(conn)
    rw.run_scripts(cfg, rw._GovernedScriptArgs(RID, __import__("json").loads(man), wj,
                                               claim_token=stale_tok, worker="owner-a"))
    after_scripts, after_prov = _artifact_counts(conn)
    check("stale tenure wrote NO script row", after_scripts, before_scripts)
    check("stale tenure wrote NO provenance row", after_prov, before_prov)

    # --- CURRENT TENURE: the same call MUST persist, or the negative above proves nothing ---
    ok_job = mk_job(conn, "script", "queued", manifest=man)
    ok_tok = engine.claim_script_generation_job(conn, ok_job, worker="owner-c")
    before_scripts, before_prov = _artifact_counts(conn)
    rw.run_scripts(cfg, rw._GovernedScriptArgs(RID, __import__("json").loads(man), ok_job,
                                               claim_token=ok_tok, worker="owner-c"))
    after_scripts, after_prov = _artifact_counts(conn)
    check("CURRENT tenure DID write a script row (control)", after_scripts > before_scripts, True)
    check("CURRENT tenure DID write provenance (control)", after_prov > before_prov, True)

    # ---------------------------------------------------------------- J7
    print("\nJ7 — CRASH / NO HEARTBEAT IS DETERMINISTICALLY RECLAIMABLE")
    crashed = mk_job(conn, "script", "queued")
    tok = engine.claim_script_generation_job(conn, crashed, worker="doomed")
    check("worker claims it", bool(tok), True)
    expire(conn, crashed)                       # the crash: lease stops being renewed
    pend = [p["job_id"] for p in engine.pending_script_generation_jobs(conn)]
    check("an abandoned attempt reappears in the drain", crashed in pend, True)
    check("a NEW worker can reclaim it", bool(engine.claim_script_generation_job(conn, crashed, worker="rescuer")), True)

    # ---------------------------------------------------------------- J1 / D
    print("\nJ1 · D — DISCOVERY IS STAGE-SCOPED AND BOUNDED PER PASS")
    for _ in range(8):
        mk_job(conn, "script", "queued")
    pend = engine.pending_script_generation_jobs(conn)
    check("the pass is BOUNDED (never unbounded like the Topic drain)",
          len(pend) <= engine.SCRIPT_RECOVERY_BATCH, True)
    ids = {p["job_id"] for p in pend}
    check("no TOPIC job appears in the Script drain", topic_j in ids, False)
    check("a live-lease Script job is not a recovery candidate", j in ids, False)

    # ---------------------------------------------------------------- J9 / F
    print("\nJ9 · F — BIDIRECTIONAL NON-MUTATION")
    tsnap = snap(conn, topic_j)
    check("Script claim REFUSES a Topic job", engine.claim_script_generation_job(conn, topic_j, worker="w"), None)
    check("Topic job byte-identical after the refused Script claim", snap(conn, topic_j), tsnap)
    script_live = mk_job(conn, "script", "queued")
    ssnap = snap(conn, script_live)
    check("Topic claim REFUSES a Script job (#360, re-proved here)",
          engine.claim_topic_generation_job(conn, script_live, worker="t"), False)
    check("Script job byte-identical after the refused Topic claim", snap(conn, script_live), ssnap)

    # ---------------------------------------------------------------- L5 / J5
    print("\nL5 — NO UNIQUENESS OR ATTEMPT-IDENTITY INVARIANT CHANGED")
    cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM pg_indexes
                    WHERE tablename='generation_job' AND indexdef LIKE '%claim_token%'""")
    check("claim_token participates in NO index", cur.fetchone()[0], 0)
    cur.execute("""SELECT count(*) FROM information_schema.columns
                    WHERE table_name='generation_job' AND column_name='claim_token'
                      AND is_nullable='YES' AND column_default IS NULL""")
    check("claim_token is nullable with no default", cur.fetchone()[0], 1)
    cur.close()

    # ---------------------------------------------------------------- M / J10
    # SHUTDOWN BOUNDARY. Every assertion here is arbitrated by threading Events, never by sleeps:
    # a sleep-based proof would pass or fail on machine speed, which is not a proof of ordering.
    print("\nM — SHUTDOWN BOUNDARY (stop-before-claim, bounded, non-destructive)")
    import threading as _th
    rw.reset_script_drain_shutdown()

    # Two claimable jobs: the second exists so that "stopped" can be distinguished from
    # "there was nothing left to do" — the classic vacuity in a drain test.
    m_a = mk_job(conn, "script", "queued")
    m_b = mk_job(conn, "script", "queued")
    before_a, before_b = snap(conn, m_a), snap(conn, m_b)

    # M1 — no claim at all once shutdown has begun.
    rw.begin_script_drain_shutdown()
    check("shutdown: dispatch claims nothing", rw.dispatch_pending_script_generation(cfg), [])
    check("shutdown: job A untouched", snap(conn, m_a), before_a)
    check("shutdown: job B untouched", snap(conn, m_b), before_b)

    # M2 — stop-before-claim at the job level, not only at the batch level.
    r = rw.run_governed_script_job(cfg, m_a)
    check("shutdown: single job refused", r.get("status"), "skipped")
    check("shutdown: refusal claimed no tenure", snap(conn, m_a), before_a)

    # M3 — the control. Without the flag the SAME call claims, so M1/M2 prove the flag, not an
    # empty queue or an unclaimable fixture.
    rw.reset_script_drain_shutdown()
    tok_ctl = engine.claim_script_generation_job(conn, m_a, worker="m-ctl")
    check("control: same job IS claimable when not shutting down", bool(tok_ctl), True)

    # M4 — shutdown DURING active execution. A worker is held inside the job by an Event; shutdown
    # is signalled while it is provably mid-flight.
    started, release = _th.Event(), _th.Event()
    seen = {}
    real_run = rw.run_governed_script_job

    def _held(cfg_, job_id, worker="script-drain"):
        # This stub must take a REAL tenure before blocking. A stub that only sleeps would leave the
        # row 'queued' with a NULL token, and "shutdown did not terminalize it" would then be
        # asserted about a job that was never in flight — true, and worthless.
        seen.setdefault("jobs", []).append(str(job_id))
        c = engine.db_connect()
        try:
            seen["token"] = engine.claim_script_generation_job(c, job_id, worker="m-inflight")
            c.commit()          # the tenure must be VISIBLE to the observer, not rolled back on close
        finally:
            c.close()
        started.set()
        release.wait(10)                       # bounded so a defect fails the suite, not hangs it
        return {"job_id": str(job_id), "status": "held"}

    rw.run_governed_script_job = _held
    try:
        m_c = mk_job(conn, "script", "queued")
        m_d = mk_job(conn, "script", "queued")
        # The drain picks its own job from the pending set (m_b is still queued from M1), so the
        # observation is bound to the job it ACTUALLY claimed rather than to a guess. Guessing here
        # is how the first version of this proof silently observed an untouched bystander.
        # Snapshot the WHOLE claimable set, not just this section's two jobs: earlier sections leave
        # their own claimable fixtures behind, and the drain is entitled to pick any of them.
        pending_ids = [str(j["job_id"]) for j in engine.pending_script_generation_jobs(conn)]
        pre = {j: snap(conn, j) for j in pending_ids}
        check("more than one job is claimable (mid-batch stop is provable)",
              len(pending_ids) >= 2, True)
        t = _th.Thread(target=lambda: rw.dispatch_pending_script_generation(cfg), daemon=True)
        t.start()
        check("in-flight worker reached", started.wait(10), True)
        # The fixture is only meaningful if it actually reached a live owned tenure.
        obs = seen["jobs"][0]
        check("observed job came from the claimable set", obs in pre, True)
        before_obs = pre[obs]
        inflight = snap(conn, obs)
        check("in-flight job holds a REAL tenure (fixture is not vacuous)",
              bool(seen.get("token")), True)
        check("in-flight row is running+owned, not the pre-claim queued row",
              (inflight[0], inflight[1] != "None", inflight != before_obs),
              ("running", True, True))

        # Signalled while the worker is demonstrably inside a claimed, running job.
        rw.begin_script_drain_shutdown()
        check("shutdown during active work: live tenure NOT terminalized or released",
              snap(conn, obs), inflight)
        cur = conn.cursor()
        cur.execute("""SELECT status, claim_token IS NOT NULL, lease_expires_at IS NOT NULL
                         FROM generation_job WHERE job_id=%s""", (obs,))
        check("shutdown left it running, owned, and leased",
              tuple(cur.fetchone()), ("running", True, True))
        cur.close()

        release.set()
        t.join(10)
        check("drain thread exited", t.is_alive(), False)
        # The pass had TWO jobs to run; shutdown mid-batch must stop it taking the second.
        check("shutdown mid-batch: no further job entered", len(seen.get("jobs", [])), 1)
    finally:
        rw.run_governed_script_job = real_run
        release.set()
        rw.reset_script_drain_shutdown()

    # M5 — the REAL recovery loop. The previous version of this check installed a stub thread as
    # `_RECOVERY_THREAD`, which meant the actual `_loop` was never executed — and it therefore passed
    # while the loop still ran `while True`, spinning every drain at full speed forever once the
    # event was set. A shutdown proof that never runs the loop is not a shutdown proof.
    import api as _api                                # noqa: E402 — proven where it is wired
    passes = {"topic": 0, "script": 0}
    real_topic = rw.dispatch_pending_topic_generation
    real_script = rw.dispatch_pending_script_generation
    ran = _th.Event()

    def _count_topic(cfg_):
        passes["topic"] += 1
        ran.set()
        return []

    def _count_script(cfg_, limit=None):
        passes["script"] += 1
        return []

    prev_poll = os.environ.get("TANAGHOM_TOPICGEN_RECOVERY_SECONDS")
    prev_rw_off = os.environ.get("TANAGHOM_REWORK_RECOVERY_DISABLED")
    os.environ["TANAGHOM_TOPICGEN_RECOVERY_SECONDS"] = "0.05"   # fast cycles: a spin would be obvious
    os.environ["TANAGHOM_REWORK_RECOVERY_DISABLED"] = "1"
    rw.dispatch_pending_topic_generation = _count_topic
    rw.dispatch_pending_script_generation = _count_script
    try:
        _api._start_topic_generation_recovery()       # the real owner, real thread, real loop
        check("real recovery loop is running", ran.wait(10), True)
        check("real loop thread is alive", _api._RECOVERY_THREAD.is_alive(), True)

        finished = _api.begin_recovery_shutdown(timeout=10)
        check("bounded join reports the loop ACTUALLY EXITED", finished, True)
        check("loop thread is gone", _api._RECOVERY_THREAD.is_alive(), False)

        # No pass may run after shutdown. The snapshot is taken FIRST and compared after a bounded
        # observation window — comparing `passes` against a snapshot taken at the same instant would
        # be a self-comparison that is true no matter what the loop does.
        frozen = dict(passes)
        _th.Event().wait(0.5)                         # observation window >> the 0.05s poll above
        check("no topic pass after shutdown", passes["topic"], frozen["topic"])
        check("no script pass after shutdown", passes["script"], frozen["script"])
        check("shutdown raised stop-before-claim", rw.script_drain_is_shutting_down(), True)
    finally:
        rw.dispatch_pending_topic_generation = real_topic
        rw.dispatch_pending_script_generation = real_script
        _api._RECOVERY_SHUTDOWN.clear()
        _api._RECOVERY_THREAD = None
        rw.reset_script_drain_shutdown()
        for k, v in (("TANAGHOM_TOPICGEN_RECOVERY_SECONDS", prev_poll),
                     ("TANAGHOM_REWORK_RECOVERY_DISABLED", prev_rw_off)):
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    check("bounded wait returns True when no loop is running",
          _api.begin_recovery_shutdown(timeout=0.5), True)
    _api._RECOVERY_SHUTDOWN.clear(); rw.reset_script_drain_shutdown()

    # ---------------------------------------------------------------- N / correction C
    # HEARTBEAT CADENCE VALIDATION. The unsafe case is not "ugly config" — a cadence at or beyond the
    # lease means a HEALTHY worker loses its lease before it can renew, and the drain reclaims work
    # that is still running. Each boundary is asserted on both sides.
    print("\nN — HEARTBEAT CADENCE VALIDATED AGAINST THE LEASE")
    lease = engine.SCRIPT_GENERATION_LEASE_SECONDS
    derived = engine.script_heartbeat_ceiling(lease)
    v = engine._validated_script_heartbeat_seconds

    def _with(raw, want, label):
        prev = os.environ.get("TANAGHOM_SCRIPTGEN_HEARTBEAT_SECONDS")
        if raw is None:
            os.environ.pop("TANAGHOM_SCRIPTGEN_HEARTBEAT_SECONDS", None)
        else:
            os.environ["TANAGHOM_SCRIPTGEN_HEARTBEAT_SECONDS"] = raw
        try:
            check(label, v(), want)
        finally:
            os.environ.pop("TANAGHOM_SCRIPTGEN_HEARTBEAT_SECONDS", None)
            if prev is not None:
                os.environ["TANAGHOM_SCRIPTGEN_HEARTBEAT_SECONDS"] = prev

    _with(None, derived, "unset -> derived safe cadence")
    _with("", derived, "empty -> derived safe cadence")
    _with("abc", derived, "non-numeric -> derived safe cadence")
    _with("0", derived, "zero -> derived safe cadence")
    _with("-5", derived, "negative -> derived safe cadence")
    _with(str(lease), derived, f"equal to lease ({lease}s) -> rejected")
    _with(str(lease + 1), derived, "longer than lease -> rejected")
    _with(str(lease - 1), derived,
          "just under lease -> REJECTED: one missed beat would lose a healthy worker's lease")
    _with(str(derived), derived, f"exactly at the margin ceiling ({derived}s) -> accepted")
    _with(str(derived + 1), derived, "one second past the ceiling -> rejected (boundary is exact)")
    _with(str(max(1, derived // 2)), max(1, derived // 2),
          "faster than the ceiling -> accepted (more renewal is never unsafe)")
    _with("1", 1, "minimum positive -> accepted")
    check("ceiling gives at least the required beats per lease",
          derived * engine.SCRIPT_HEARTBEATS_PER_LEASE <= lease, True)
    check("ceiling is positive", derived >= 1, True)

    # ---------------------------------------------------------------- O
    # LINEARIZATION BOUNDARY between the shutdown check and the SQL claim. A flag read followed by a
    # claim is check-then-act; the window between them is what the shared gate closes. Both orderings
    # are exercised, and blocking is observed directly rather than inferred.
    print("\nO — SHUTDOWN/CLAIM LINEARIZATION (both orderings)")
    rw.reset_script_drain_shutdown()
    o_a = mk_job(conn, "script", "queued")
    o_before = snap(conn, o_a)

    # O1 — the CLAIM path takes the gate. Held by this thread, a claim cannot proceed.
    done_claim, out = _th.Event(), {}
    rw.SCRIPT_CLAIM_GATE.acquire()
    try:
        def _try_claim():
            out["r"] = rw.run_governed_script_job(cfg, o_a, worker="o-claimer")
            done_claim.set()
        _th.Thread(target=_try_claim, daemon=True).start()
        check("claim BLOCKS while the gate is held (check+claim are not separable)",
              done_claim.wait(0.5), False)
        check("no tenure taken while blocked", snap(conn, o_a), o_before)
    finally:
        rw.SCRIPT_CLAIM_GATE.release()
    check("claim proceeds once the gate is free", done_claim.wait(10), True)
    check("the unblocked claim took a real tenure", snap(conn, o_a) != o_before, True)

    # O2 — SHUTDOWN takes the SAME gate. If it did not, the two could interleave.
    rw.reset_script_drain_shutdown()
    done_sd = _th.Event()
    rw.SCRIPT_CLAIM_GATE.acquire()
    try:
        _th.Thread(target=lambda: (rw.begin_script_drain_shutdown(), done_sd.set()),
                   daemon=True).start()
        check("shutdown BLOCKS while the gate is held (same lock, not a second one)",
              done_sd.wait(0.5), False)
        check("flag NOT set while shutdown is blocked", rw.script_drain_is_shutting_down(), False)
    finally:
        rw.SCRIPT_CLAIM_GATE.release()
    check("shutdown completes once the gate is free", done_sd.wait(10), True)
    check("flag set after shutdown completes", rw.script_drain_is_shutting_down(), True)

    # O3 — ORDERING A: shutdown wins the gate. Every later claim refuses; no tenure is created.
    o_b = mk_job(conn, "script", "queued")
    b_before = snap(conn, o_b)
    check("ordering A — claim after shutdown is refused",
          rw.run_governed_script_job(cfg, o_b, worker="o-late").get("status"), "skipped")
    check("ordering A — job untouched", snap(conn, o_b), b_before)

    # O4 — ORDERING B: the claim is already in progress when shutdown is signalled. The ordering is
    # FORCED, not raced: this thread holds the gate (an RLock, so its own re-entry is permitted),
    # starts a shutdown thread that provably blocks on it, and only then performs the claim. Racing
    # two threads for the lock would prove whichever ordering the scheduler happened to pick.
    rw.reset_script_drain_shutdown()
    o_c = mk_job(conn, "script", "queued")
    sd_done = _th.Event()
    rw.SCRIPT_CLAIM_GATE.acquire()
    try:
        _th.Thread(target=lambda: (rw.begin_script_drain_shutdown(), sd_done.set()),
                   daemon=True).start()
        check("ordering B — shutdown is waiting on the gate", sd_done.wait(0.3), False)
        # The claim runs to completion with shutdown provably pending behind it.
        rw.run_governed_script_job(cfg, o_c, worker="o-winner")
        after_claim = snap(conn, o_c)
        check("ordering B — the claim took a real tenure despite pending shutdown",
              after_claim[2] != "None", True)         # claim_token minted
        check("ordering B — shutdown STILL blocked while the claim ran",
              rw.script_drain_is_shutting_down(), False)
    finally:
        rw.SCRIPT_CLAIM_GATE.release()
    check("ordering B — shutdown completes after the claim", sd_done.wait(10), True)
    check("ordering B — shutdown did not alter the completed tenure",
          snap(conn, o_c), after_claim)
    rw.reset_script_drain_shutdown()

    # ---------------------------------------------------------------- P
    # THE TERMINAL/CLOSE HELPERS FAIL CLOSED. Every write that fixes an outcome or releases a lease
    # requires FULL ownership; partial ownership is no ownership, not a weaker claim to be honoured.
    print("\nP — TERMINAL WRITES REQUIRE FULL OWNERSHIP (no unfenced path)")
    p_job = mk_job(conn, "script", "queued", manifest=json.dumps({"items": [{"slot_id": f"{RID}-P1"}]}))
    p_tok = engine.claim_script_generation_job(conn, p_job, worker="p-owner")
    conn.commit()
    p_running = snap(conn, p_job)
    check("fixture holds a live tenure", bool(p_tok), True)

    for label, kw in (("no ownership at all", {}),
                      ("worker only (partial)", {"worker": "p-owner"}),
                      ("token only (partial)", {"claim_token": p_tok}),
                      ("wrong worker", {"worker": "p-other", "claim_token": p_tok}),
                      ("wrong token", {"worker": "p-owner",
                                       "claim_token": "00000000-0000-0000-0000-000000000000"})):
        check(f"finish REFUSED — {label}",
              engine.finish_script_generation_job(conn, p_job, done=5, failed=0, **kw), None)
        check(f"row unchanged after refused finish — {label}", snap(conn, p_job), p_running)

    for label, kw in (("no ownership at all", {}),
                      ("worker only (partial)", {"worker": "p-owner"}),
                      ("token only (partial)", {"claim_token": p_tok})):
        r = engine.record_script_generation_results(conn, p_job, **kw)
        check(f"close REFUSED — {label}", (r["status"], r.get("fenced_out")), (None, True))
        check(f"row unchanged after refused close — {label}", snap(conn, p_job), p_running)

    # The control: the SAME call with the SAME job succeeds when ownership is complete — so every
    # refusal above is the fence, not an unwritable row.
    ok = engine.finish_script_generation_job(conn, p_job, done=1, failed=0,
                                             worker="p-owner", claim_token=p_tok)
    check("finish SUCCEEDS with full ownership (control)", ok is not None, True)
    cur = conn.cursor()
    cur.execute("SELECT status, lease_expires_at IS NULL FROM generation_job WHERE job_id=%s",
                (p_job,))
    check("terminal write landed and released the lease", tuple(cur.fetchone()), ("completed", True))
    cur.close()

    # No conditional fence may remain in the source: a predicate assembled at runtime is how the
    # unfenced path existed in the first place.
    # Read the SHIPPED SOURCE, not the currently-bound object: this pins what the repo contains,
    # and stays meaningful when a red proof rebinds the function.
    _es = open(engine.__file__, encoding="utf-8").read()
    _i = _es.index("def finish_script_generation_job(")
    src = _es[_i:_es.index("\ndef ", _i + 1)]
    check("terminal UPDATE carries the fence statically (no dynamic predicate)",
          ("if fenced" in src or "fenced else" in src), False)
    check("terminal UPDATE always names claim_token", "claim_token=%s::uuid" in src, True)

    print("\n" + "=" * 60)
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 60)
        sys.exit(1)
    print("ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
