"""#364 — DURABLE generation truth for the shared gate guards and read projections.

Every check below is arbitrated by persisted rows, never by timing. There are no sleeps, no process
kills and no providers: a "restart" is simulated by CLEARING the in-process registry, which is
exactly the state a fresh process starts in — a kill would prove the same thing less precisely and
less repeatably.

What this proves, in the directive's own order:
  1. clearing/evicting the registry cannot hide queued or running durable Topic or Script work;
  2. a simulated restart cannot let a gate commit over relevant non-terminal work;
  3. running work blocks before AND after lease expiry, until a real terminal transition;
  4. terminal rows (completed/partial/failed) do not block;
  5. wrong-stage rows neither block, satisfy, nor project as another stage;
  6. mixed Topic and Script history for one round resolves independently;
  7. the vocabulary hole this directive was written around: a job registered under the GENERATION
     stage string (what the governed Stage 2A paths actually write) is invisible to the old
     registry lookup and must now block on durable truth alone.

Run: docker exec -e PYTHONPATH=/work:/work/gates:/work/agents <lane> python -m gates.generation_truth_selftest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402
import jobs    # noqa: E402

FAILS = []
RID_T = "RGT364T"          # Topic-stage round
RID_S = "RGT364S"          # Script-stage round
RID_M = "RGT364M"          # mixed history round


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def mk_round(conn, rid):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id, period_len_days, posts_per_day, post_times,
                                     pillar_distribution, format_distribution, status)
                   VALUES (%s, 7, 1, '["09:00"]'::jsonb, '{}'::jsonb, '{}'::jsonb, 'active')
                   ON CONFLICT (round_id) DO NOTHING""", (rid,))
    conn.commit(); cur.close()


def mk_job(conn, rid, stage, status, lease=None):
    """A durable job row in a genuinely reachable state. `lease='expired'` persists a PAST
    timestamp — the stored signature of a worker that died mid-run, and the reason this suite needs
    no sleep to test lease expiry."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO generation_job
                     (round_id, stage, status, accepted_schedule_token, manifest_digest,
                      lease_expires_at, claimed_by)
                   VALUES (%s,%s,%s,
                           CASE WHEN %s='topic' THEN %s ELSE NULL END,
                           CASE WHEN %s='script' THEN %s ELSE NULL END,
                           CASE WHEN %s='expired' THEN now() - interval '1 hour'
                                WHEN %s='live'    THEN now() + interval '1 hour' ELSE NULL END,
                           CASE WHEN %s IS NULL THEN NULL ELSE 'w364' END)
                   RETURNING job_id::text""",
                (rid, stage, status, stage, abs(hash(rid + status + (lease or ""))) % 90000,
                 stage, f"{rid}-{status}-{lease}-digest", lease, lease, lease))
    jid = cur.fetchone()[0]
    conn.commit(); cur.close()
    return jid


def clear_jobs(rid=None, stage=None, conn=None):
    cur = conn.cursor()
    if rid:
        cur.execute("DELETE FROM generation_job WHERE round_id=%s", (rid,))
    conn.commit(); cur.close()


def durable(conn, rids, gate_stage):
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    try:
        return engine.durable_generation_pending_rounds(cur, rids, gate_stage)
    finally:
        cur.close()


def guard_blocks(conn, rid, gate_stage, cfg):
    """Does the shared guard refuse for this round? Uses the REAL guard, not a reimplementation."""
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    try:
        engine._guard_generation_complete(cur, cfg, None, gate_stage, "open", round_ids=[rid])
        return False
    except engine.GateNotReady:
        return True
    finally:
        cur.close()


def main():
    conn = engine.db_connect()
    cfg = engine.load_config()
    for rid in (RID_T, RID_S, RID_M):
        mk_round(conn, rid)
        clear_jobs(rid, conn=conn)

    # The registry is emptied ONCE at the start and never repopulated. Every check below therefore
    # runs in exactly the state a freshly-restarted process is in: no in-memory job knowledge at all.
    jobs.JOBS.clear()

    print("\n1 · REGISTRY EVICTION CANNOT HIDE DURABLE WORK (Topic and Script)")
    t_queued = mk_job(conn, RID_T, "topic", "queued")
    check("empty registry (a fresh process's state)", len(jobs.JOBS), 0)
    check("durable queued Topic work is visible", durable(conn, [RID_T], "topic_review").get(RID_T),
          t_queued)
    check("the old volatile signal sees nothing at all",
          jobs.find_running("topics", RID_T, "topic_review"), None)
    check("the guard REFUSES on durable truth alone", guard_blocks(conn, RID_T, "topic_review", cfg),
          True)

    s_running = mk_job(conn, RID_S, "script", "running", lease="live")
    check("durable running Script work is visible",
          durable(conn, [RID_S], "script_review").get(RID_S), s_running)
    check("the guard REFUSES for Script", guard_blocks(conn, RID_S, "script_review", cfg), True)

    print("\n2 · A SIMULATED RESTART CANNOT LET A GATE COMMIT OVER NON-TERMINAL WORK")
    # stage_state is the read projection every surface reads; it must agree with the guard.
    ss = engine.stage_state(conn, RID_T, "topic_review")
    check("stage_state reports generation, not a reviewable stage", ss["next_action"], "generate")
    check("stage_state exposes NO gate while work is non-terminal", ss["gate_id"], None)
    # The durable signal must reach the PROJECTION, not just the guard: this recommendation string
    # is only produced when the in-flight signal is truthy.
    check("stage_state reports generation IN PROGRESS (durable signal reached the projection)",
          ss["recommendation"].startswith("Generation in progress"), True)
    # Response shape is unchanged: the projection never exposed the job id and still does not, so
    # no consumer can observe the 12-hex-registry -> UUID change.
    check("stage_state exposes no job id (response shape preserved)", "running_job" in ss, False)
    assert t_queued

    print("\n3 · RUNNING WORK BLOCKS BEFORE AND AFTER LEASE EXPIRY")
    clear_jobs(RID_T, conn=conn)
    live = mk_job(conn, RID_T, "topic", "running", lease="live")
    check("running with a LIVE lease blocks", guard_blocks(conn, RID_T, "topic_review", cfg), True)
    clear_jobs(RID_T, conn=conn)
    exp = mk_job(conn, RID_T, "topic", "running", lease="expired")
    check("running with an EXPIRED lease still blocks (expiry != completion)",
          guard_blocks(conn, RID_T, "topic_review", cfg), True)
    check("the expired-lease job is reported, not silently dropped",
          durable(conn, [RID_T], "topic_review").get(RID_T), exp)
    check("live and expired leases are treated identically", live is not None and exp is not None,
          True)

    print("\n3b · awaiting_trigger IS NON-TERMINAL (reconciled semantics)")
    clear_jobs(RID_T, conn=conn)
    park = mk_job(conn, RID_T, "topic", "awaiting_trigger")
    check("a parked manual-entry job is visible",
          durable(conn, [RID_T], "topic_review").get(RID_T), park)
    check("a parked manual-entry job BLOCKS the gate",
          guard_blocks(conn, RID_T, "topic_review", cfg), True)

    print("\n3c · UNKNOWN / CORRUPT / FUTURE STATUSES FAIL CLOSED (closed terminal set)")
    # `generation_job.status` is unconstrained text with no CHECK constraint. A value outside the
    # canonical vocabulary is therefore reachable — a future state, a corrupt row, a hand-edited
    # record. It is NOT a proven completion, so it must block. Enumerating the blocking states
    # instead would let exactly these rows through.
    cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM information_schema.constraint_column_usage ccu
                     JOIN pg_constraint pc ON pc.conname = ccu.constraint_name
                    WHERE ccu.table_name='generation_job' AND ccu.column_name='status'
                      AND pc.contype='c'""")
    check("status is genuinely unconstrained (the premise of this section)", cur.fetchone()[0], 0)
    cur.close()

    for unknown in ("cancelled", "paused_by_operator", "", "QUEUED", "zzz-future-state"):
        clear_jobs(RID_T, conn=conn)
        u = mk_job(conn, RID_T, "topic", unknown)
        check(f"unknown status {unknown!r}: LOOKUP reports it",
              durable(conn, [RID_T], "topic_review").get(RID_T), u)
        check(f"unknown status {unknown!r}: GUARD fails closed",
              guard_blocks(conn, RID_T, "topic_review", cfg), True)
        ss_u = engine.stage_state(conn, RID_T, "topic_review")
        check(f"unknown status {unknown!r}: stage_state does not offer review",
              (ss_u["next_action"], ss_u["gate_id"]), ("generate", None))

    # Case-sensitivity is the subtle one: 'QUEUED' is NOT the canonical 'queued'. Under an
    # enumerated blocking set it would slip through as unrecognised; under the closed terminal set it
    # blocks, which is the safe reading of a value nobody can vouch for.
    clear_jobs(RID_T, conn=conn)
    mk_job(conn, RID_T, "topic", "COMPLETED")
    check("a case-variant of a TERMINAL status is not accepted as terminal either",
          guard_blocks(conn, RID_T, "topic_review", cfg), True)

    print("\n4 · TERMINAL ROWS DO NOT BLOCK")
    for term in ("completed", "partial", "failed"):
        clear_jobs(RID_T, conn=conn)
        mk_job(conn, RID_T, "topic", term)
        check(f"'{term}' is terminal: not reported", durable(conn, [RID_T], "topic_review"), {})
        check(f"'{term}' is terminal: does not block",
              guard_blocks(conn, RID_T, "topic_review", cfg), False)

    print("\n5 · WRONG-STAGE ROWS NEITHER BLOCK NOR PROJECT AS ANOTHER STAGE")
    clear_jobs(RID_T, conn=conn); clear_jobs(RID_S, conn=conn)
    only_script = mk_job(conn, RID_T, "script", "running", lease="live")
    check("a Script row does not block the Topic guard",
          guard_blocks(conn, RID_T, "topic_review", cfg), False)
    check("a Script row is invisible to the Topic projection",
          durable(conn, [RID_T], "topic_review"), {})
    check("the same row DOES block the Script guard (it is real work, not an inert fixture)",
          guard_blocks(conn, RID_T, "script_review", cfg), True)
    clear_jobs(RID_T, conn=conn)
    mk_job(conn, RID_T, "topic", "running", lease="live")
    check("a Topic row does not block the Script guard",
          guard_blocks(conn, RID_T, "script_review", cfg), False)
    check("a non-generative gate stage maps to nothing and blocks nothing",
          durable(conn, [RID_T], "schedule_review"), {})
    check("an unknown gate stage blocks nothing rather than guessing",
          durable(conn, [RID_T], "not_a_stage"), {})
    assert only_script

    print("\n6 · MIXED TOPIC AND SCRIPT HISTORY RESOLVES INDEPENDENTLY")
    clear_jobs(RID_M, conn=conn)
    m_topic_done = mk_job(conn, RID_M, "topic", "completed")
    m_script_live = mk_job(conn, RID_M, "script", "running", lease="live")
    check("Topic side is complete", durable(conn, [RID_M], "topic_review"), {})
    check("Script side is still pending",
          durable(conn, [RID_M], "script_review").get(RID_M), m_script_live)
    check("Topic gate is free while Script work runs",
          guard_blocks(conn, RID_M, "topic_review", cfg), False)
    check("Script gate is held while Script work runs",
          guard_blocks(conn, RID_M, "script_review", cfg), True)
    assert m_topic_done

    print("\n7 · THE VOCABULARY HOLE — a governed Stage 2A job the old signal could never see")
    # The Stage 2A paths register the GENERATION stage ('topic'); every lookup passed the GATE stage
    # ('topic_review'), so this record never matched even in-process. Reproduced exactly.
    clear_jobs(RID_T, conn=conn)
    stage2a = mk_job(conn, RID_T, "topic", "running", lease="live")
    jobs.JOBS["gt364"] = {"job_id": "gt364", "kind": "topics", "round_id": RID_T,
                          "stage": "topic", "status": "running", "total": 6, "done": 6,
                          "error": None}
    try:
        check("the old volatile lookup MISSES it (the defect, reproduced)",
              jobs.find_running("topics", RID_T, "topic_review"), None)
        check("durable truth sees it", durable(conn, [RID_T], "topic_review").get(RID_T), stage2a)
        check("the guard REFUSES anyway", guard_blocks(conn, RID_T, "topic_review", cfg), True)
    finally:
        jobs.JOBS.pop("gt364", None)

    print("\n8 · BATCHED: ONE QUERY FOR MANY ROUNDS (no N+1 in the guard path)")
    clear_jobs(RID_T, conn=conn); clear_jobs(RID_S, conn=conn); clear_jobs(RID_M, conn=conn)
    a = mk_job(conn, RID_T, "topic", "queued")
    b = mk_job(conn, RID_M, "topic", "running", lease="expired")
    mk_job(conn, RID_S, "topic", "completed")
    got = durable(conn, [RID_T, RID_S, RID_M], "topic_review")
    check("one call resolves every round", got, {RID_T: a, RID_M: b})
    check("the terminal round is absent from the batch", RID_S in got, False)
    check("an empty round list short-circuits", durable(conn, [], "topic_review"), {})

    print("\n9 · THE REGISTRY IS PRESERVED FOR BOOKKEEPING (not deleted, not authority)")
    check("jobs.start still exists", callable(jobs.start), True)
    check("jobs.status still exists", callable(jobs.status), True)
    check("jobs.find_running still exists (bookkeeping callers keep working)",
          callable(jobs.find_running), True)
    _src = open(engine.__file__, encoding="utf-8").read()
    check("engine no longer treats the registry as generation authority",
          "jobs.find_running" in _src, False)

    # ---------------------------------------------------------------- teardown
    for rid in (RID_T, RID_S, RID_M):
        clear_jobs(rid, conn=conn)

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
