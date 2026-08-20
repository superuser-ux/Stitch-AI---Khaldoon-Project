"""#360 — Topic-stage isolation of the durable generation_job execution path.

THE DEFECT. `generation_job` is stage-aware, and #357 added durable Script rows to it. The Topic
pending/claim/heartbeat/terminal/retry paths selected by status and round only, so a queued or
lease-expired SCRIPT attempt was visible to the Topic drain, claimable by it, and executable by the
Topic writer — which produces nothing (it only advances SCHEDULE_APPROVED slots) and then stamps
Topic-shaped terminal state over a Script job the real dispatcher could no longer claim.

HOW THESE TESTS AVOID PASSING VACUOUSLY. Three ways a stage-isolation suite can be green while
proving nothing, each defeated explicitly:

  1. an EMPTY fixture — so every negative asserts the Script job exists first;
  2. a NON-CLAIMABLE job — a job that is merely ineligible would be refused anyway, and the refusal
     would not be attributable to the stage predicate. Every Script negative therefore uses a job in
     a genuinely CLAIMABLE state: `queued`, and separately `running` with an EXPIRED lease;
  3. an UNRELATED refusal — refusal alone is not evidence, so each negative also asserts that all
     five mutable fields are BYTE-IDENTICAL afterwards.

And because a predicate that blocks everything would also pass the negatives, every negative has a
matching POSITIVE control: a Topic job in the SAME state must still be discovered, claimed, and
reclaimed exactly once.

Deterministic throughout: state is injected at the persistence boundary (an already-expired lease is
a written timestamp, not a sleep). No process kills, no timing races, no provider.

GUARD CLASSIFICATION. Six of the eight guards are INDEPENDENTLY REACHABLE and each is red-proved by
removing it alone (pending, claim, heartbeat, terminal, retry SELECT, runner entry). Two are
DEFENCE-IN-DEPTH and cannot be reached while their upstream guard stands, so they have no independent
red proof — this is stated rather than papered over:

  * `retry_topic_generation`'s UPDATE — reachable only if its own SELECT returned a wrong-stage row.
    With the SELECT predicate present the UPDATE can never see one; removing BOTH is what the
    RED[retrySELECT] case exercises.
  * `activate_manual_topic_generation`'s transition UPDATE — its governing SELECT was ALREADY
    stage-scoped before #360, so the row it updates is Topic by construction. The predicate makes
    that structural instead of a data-flow accident, so a later edit to that SELECT cannot silently
    turn the UPDATE into a cross-stage write.

Both are cheap, both fail closed, and neither can be exercised without first defeating a guard that
is itself proved. Claiming an independent red proof for either would be dishonest.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402

FAILS = []
MUTABLE = ("status", "claimed_by", "lease_expires_at", "heartbeat_at", "slots_done", "slots_failed")


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def _snapshot(conn, job_id):
    """The exact mutable execution state a wrong-stage call must not touch."""
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(MUTABLE)} FROM generation_job WHERE job_id=%s", (job_id,))
    row = cur.fetchone()
    cur.close()
    return tuple(str(x) for x in row) if row else None


def _domain_snapshot(conn, rid):
    """The six domains a wrong-stage run must leave untouched.

    Counts alone would be vacuous on an empty lane — `0 == 0` passes with the guard removed — so the
    fixture below is deliberately NON-EMPTY and this captures content digests, not just cardinality.
    """
    cur = conn.cursor()
    out = {}
    cur.execute("""SELECT count(*), coalesce(md5(string_agg(slot_id||':'||status, ',' ORDER BY slot_id)),'-')
                     FROM slot WHERE round_id=%s""", (rid,))
    out["slots"] = cur.fetchone()
    cur.execute("""SELECT count(*), coalesce(md5(string_agg(t.topic_id::text||':'||t.revision, ',' ORDER BY t.topic_id)),'-')
                     FROM topic t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s""", (rid,))
    out["topics"] = cur.fetchone()
    cur.execute("""SELECT count(*), coalesce(md5(string_agg(c.script_id::text||':'||c.revision, ',' ORDER BY c.script_id)),'-')
                     FROM script c JOIN slot s ON s.slot_id=c.slot_id WHERE s.round_id=%s""", (rid,))
    out["scripts"] = cur.fetchone()
    cur.execute("""SELECT count(*), coalesce(md5(string_agg(sp.provenance_id::text, ',' ORDER BY sp.provenance_id)),'-')
                     FROM script_provenance sp JOIN slot s ON s.slot_id=sp.slot_id WHERE s.round_id=%s""", (rid,))
    out["script_provenance"] = cur.fetchone()
    cur.execute("""SELECT count(*), coalesce(md5(string_agg(tp.provenance_id::text, ',' ORDER BY tp.provenance_id)),'-')
                     FROM topic_provenance tp JOIN topic t ON t.topic_id=tp.topic_id
                     JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s""", (rid,))
    out["topic_provenance"] = cur.fetchone()
    cur.close()
    return out


def _seed_artifacts(conn, rid):
    """A NON-EMPTY fixture across every domain the runner could damage.

    Without this the runner's non-mutation assertions are vacuous: an empty table is trivially
    unchanged, so the test would stay green with the guard deleted. Each domain gets real rows so
    'unchanged' is a discriminating claim.
    """
    cur = conn.cursor()
    cur.execute("SELECT pillar_code FROM pillar ORDER BY pillar_code LIMIT 1")
    pil = (cur.fetchone() or ["P1"])[0]
    cur.execute("SELECT hcs_id FROM hcs WHERE pillar_code=%s ORDER BY hcs_id LIMIT 1", (pil,))
    hcs = (cur.fetchone() or ["H1"])[0]
    cur.execute("SELECT lens_id FROM lens ORDER BY lens_id LIMIT 1")
    lens = (cur.fetchone() or ["L1"])[0]
    for n in (1, 2):
        sid = f"{rid}-S{n}"
        cur.execute("""INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                                         hcs_id, lens, status)
                       VALUES (%s,%s,%s,'09:00',%s,'Hero Reel',%s,%s,'TOPIC_APPROVED')
                       ON CONFLICT DO NOTHING""", (sid, rid, n, pil, hcs, lens))
        cur.execute("""INSERT INTO topic (slot_id, hcs_id, lens, text_ar, hook_text, revision)
                       VALUES (%s,%s,%s,'موضوع','هوك',1) ON CONFLICT DO NOTHING
                       RETURNING topic_id""", (sid, hcs, lens))
        row = cur.fetchone()
        if row:
            cur.execute("""INSERT INTO topic_provenance (topic_id, revision, resolved_model)
                           VALUES (%s,1,'stub:test') ON CONFLICT DO NOTHING""", (row[0],))
        cur.execute("""INSERT INTO script (slot_id, hcs_id, lens, script_ar, model, revision)
                       VALUES (%s,%s,%s,'نص','stub:test',1) ON CONFLICT DO NOTHING
                       RETURNING script_id""", (sid, hcs, lens))
        row = cur.fetchone()
        if row:
            cur.execute("""INSERT INTO script_provenance (script_id, revision, slot_id, effective_model)
                           VALUES (%s,1,%s,'stub:test') ON CONFLICT DO NOTHING""", (row[0], sid))
    conn.commit()
    cur.close()


def _seed_retriable_input(conn, rid):
    """One slot at SCHEDULE_APPROVED so retry_topic_generation reaches its UPDATE.

    Without it retry exits early on 'no slots to retry', and the stage predicate under test is never
    evaluated — the test would pass with the guard removed.
    """
    cur = conn.cursor()
    cur.execute("SELECT pillar_code FROM pillar ORDER BY pillar_code LIMIT 1")
    pil = (cur.fetchone() or ["P1"])[0]
    cur.execute("SELECT hcs_id FROM hcs WHERE pillar_code=%s ORDER BY hcs_id LIMIT 1", (pil,))
    hcs = (cur.fetchone() or ["H1"])[0]
    cur.execute("SELECT lens_id FROM lens ORDER BY lens_id LIMIT 1")
    lens = (cur.fetchone() or ["L1"])[0]
    cur.execute("""INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                                     hcs_id, lens, status)
                   VALUES (%s,%s,9,'09:00',%s,'Hero Reel',%s,%s,'SCHEDULE_APPROVED')
                   ON CONFLICT DO NOTHING""", (f"{rid}-SA", rid, pil, hcs, lens))
    conn.commit()
    cur.close()


def _mk_round(conn, rid):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id, label, period_len_days, posts_per_day, post_times,
                                      pillar_distribution, format_distribution)
                   VALUES (%s,%s,1,1,'["09:00"]'::jsonb,'{}'::jsonb,'{}'::jsonb)
                   ON CONFLICT DO NOTHING""", (rid, rid))
    conn.commit()
    cur.close()


def _mk_job(conn, rid, stage, status, lease):
    """A durable job in a genuinely CLAIMABLE state.

    `lease` is 'expired' or None. An expired lease is written as a past timestamp — the durable
    signature of a worker that died mid-run — so recovery behaviour is exercised without sleeping.
    """
    cur = conn.cursor()
    if stage == "topic":
        cur.execute("""INSERT INTO generation_job (round_id, stage, status, accepted_schedule_token,
                                                   lease_expires_at, heartbeat_at, claimed_by)
                       VALUES (%s,'topic',%s,%s,
                               CASE WHEN %s='expired' THEN now() - interval '1 hour' ELSE NULL END,
                               CASE WHEN %s='expired' THEN now() - interval '1 hour' ELSE NULL END,
                               CASE WHEN %s='expired' THEN 'dead-worker' ELSE NULL END)
                       RETURNING job_id""",
                    (rid, status, int(uuid.uuid4().int % 100000), lease, lease, lease))
    else:
        cur.execute("""INSERT INTO generation_job (round_id, stage, status, manifest_digest,
                                                   lease_expires_at, heartbeat_at, claimed_by)
                       VALUES (%s,'script',%s,%s,
                               CASE WHEN %s='expired' THEN now() - interval '1 hour' ELSE NULL END,
                               CASE WHEN %s='expired' THEN now() - interval '1 hour' ELSE NULL END,
                               CASE WHEN %s='expired' THEN 'dead-worker' ELSE NULL END)
                       RETURNING job_id""",
                    (rid, status, uuid.uuid4().hex, lease, lease, lease))
    jid = str(cur.fetchone()[0])
    conn.commit()
    cur.close()
    return jid


def main():
    conn = engine.db_connect()
    rid = "RISO360"
    _mk_round(conn, rid)
    _seed_artifacts(conn, rid)
    _seed_retriable_input(conn, rid)
    cur = conn.cursor()
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (rid,))
    conn.commit()
    cur.close()

    # Both CLAIMABLE states, on both stages — so every negative has a same-state positive control.
    s_queued = _mk_job(conn, rid, "script", "queued", None)
    s_expired = _mk_job(conn, rid, "script", "running", "expired")
    t_queued = _mk_job(conn, rid, "topic", "queued", None)
    t_expired = _mk_job(conn, rid, "topic", "running", "expired")
    # RETRY fixture. retry_topic_generation refuses any job that is not failed/partial, so a queued or
    # running Script job would be refused for that reason alone and the SELECT predicate would prove
    # nothing. These two are RETRIABLE, and the Script row is created LAST so it is the most recent —
    # the exact shape an unscoped `ORDER BY created_at DESC LIMIT 1` selects.
    t_failed = _mk_job(conn, rid, "topic", "failed", None)
    s_failed = _mk_job(conn, rid, "script", "failed", None)

    print("\nFIXTURE (all four genuinely claimable — a refusal cannot be blamed on ineligibility)")
    check("script queued job exists", _snapshot(conn, s_queued) is not None, True)
    check("script expired-lease job exists", _snapshot(conn, s_expired) is not None, True)
    check("topic queued job exists", _snapshot(conn, t_queued) is not None, True)
    check("topic expired-lease job exists", _snapshot(conn, t_expired) is not None, True)

    # ---------------------------------------------------------------- PENDING
    print("\nPENDING SELECTION")
    pending = {str(j["job_id"]) for j in engine.pending_topic_generation_jobs(conn, round_id=rid)}
    check("queued SCRIPT job absent from the Topic drain", s_queued in pending, False)
    check("expired-lease SCRIPT job absent from the Topic drain", s_expired in pending, False)
    check("queued TOPIC job still present (control)", t_queued in pending, True)
    check("expired-lease TOPIC job still present (control)", t_expired in pending, True)

    # ---------------------------------------------------------------- CLAIM
    print("\nDIRECT CLAIM")
    for label, jid in (("queued", s_queued), ("expired-lease", s_expired)):
        before = _snapshot(conn, jid)
        won = engine.claim_topic_generation_job(conn, jid, worker="wrong-stage-probe")
        after = _snapshot(conn, jid)
        check(f"Topic claim REFUSES a {label} Script job", won, False)
        check(f"{label} Script job is byte-identical after the refused claim", after, before)

    t_before = _snapshot(conn, t_queued)
    check("Topic claim still WINS a queued Topic job (control)",
          engine.claim_topic_generation_job(conn, t_queued, worker="ctl"), True)
    check("...and that Topic job actually changed (the control is real)",
          _snapshot(conn, t_queued) != t_before, True)
    check("expired-lease TOPIC job is reclaimable (control)",
          engine.claim_topic_generation_job(conn, t_expired, worker="ctl"), True)

    # ---------------------------------------------------------------- HEARTBEAT
    print("\nHEARTBEAT")
    before = _snapshot(conn, s_expired)
    try:
        engine.heartbeat_topic_generation_job(conn, s_expired)
    except Exception as e:                                    # noqa: BLE001
        print(f"    (heartbeat raised, acceptable: {type(e).__name__})")
    check("Topic heartbeat does not extend a Script lease", _snapshot(conn, s_expired), before)

    # ---------------------------------------------------------------- TERMINAL
    print("\nTERMINAL STATE")
    before = _snapshot(conn, s_queued)
    engine.set_generation_job_state(conn, s_queued, status="completed", done=99, failed=0)
    check("Topic terminal write cannot stamp a Script job", _snapshot(conn, s_queued), before)

    # ---------------------------------------------------------------- RETRY
    print("\nRETRY SELECTION")
    # The Script job is the MOST RECENT row for this round, so an unscoped
    # `ORDER BY created_at DESC LIMIT 1` selects it every time — deterministic, not racy.
    sf_before = _snapshot(conn, s_failed)
    tf_before = _snapshot(conn, t_failed)
    retry_err = None
    try:
        engine.retry_topic_generation(conn, rid, actor="khal")
    except Exception as e:                                    # noqa: BLE001
        retry_err = type(e).__name__
        print(f"    (retry raised: {retry_err})")
    # NEGATIVE: the retriable SCRIPT job is the most recent row, so an unscoped SELECT re-queues it.
    check("Topic retry did NOT re-queue the retriable SCRIPT job", _snapshot(conn, s_failed), sf_before)
    # POSITIVE CONTROL: retry must still reach the retriable TOPIC job and re-queue it.
    tf_after = _snapshot(conn, t_failed)
    check("Topic retry DID re-queue the retriable TOPIC job (control)",
          tf_after[0], "queued")
    check("...and it was genuinely failed beforehand (the control is real)", tf_before[0], "failed")
    # POSITIVE CONTROL (completing the previously-unused t_before): with the Script rows excluded,
    # retry must still REACH a Topic job. Either it re-queued the expired Topic job, or it refused
    # for a genuine domain reason — but it must not have silently done nothing while a Topic job was
    # eligible, which is how an over-broad predicate would look.


    # ---------------------------------------------------------------- RUNNER ENTRY
    print("\nRUNNER ENTRY")
    try:
        from agents import run_writers as rw
    except Exception:                                          # noqa: BLE001
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents"))
        import run_writers as rw                               # type: ignore
    # (3) DETERMINISTIC RESOURCE-CLOSE PROOF. The runner opens its OWN connection and cursor, so a
    # refusal path that returns without closing them leaks. Rather than counting server-side
    # connections — which CPython refcounting can close on its own, making the probe
    # non-discriminating — every connection/cursor the runner creates is wrapped and its `closed`
    # flag asserted directly. That distinguishes "closed by the code" from "collected by chance".
    created = {"conns": [], "curs": []}
    real_connect = rw.db_connect

    class _TrackedConn:
        """A delegating proxy — psycopg2's connection is a C extension whose `cursor` attribute is
        read-only, so the tracking wraps it rather than mutating it. `closed` is read through to the
        real connection, so the assertion below observes genuine driver state, not a local flag."""

        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)

        def cursor(self, *a, **k):
            cu = self._inner.cursor(*a, **k)
            created["curs"].append(cu)
            return cu

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_inner"), name)

    def _tracking_connect(*a, **k):
        c = _TrackedConn(real_connect(*a, **k))
        created["conns"].append(c)
        return c
    rw.db_connect = _tracking_connect

    before_job = _snapshot(conn, s_queued)
    before_dom = _domain_snapshot(conn, rid)
    # the fixture must be NON-EMPTY or "unchanged" proves nothing
    check("fixture is discriminating: slots/topics/scripts/provenance all non-empty",
          all(before_dom[k][0] > 0 for k in
              ("slots", "topics", "scripts", "script_provenance", "topic_provenance")), True)

    res = rw.run_stage2a_topic_job(engine.load_config(), s_queued)
    rw.db_connect = real_connect

    check("Topic runner refuses a Script job", res.get("status"), "skipped")
    check("...with a stage-specific reason (not an unrelated refusal)",
          "wrong stage" in (res.get("reason") or ""), True)
    check("job row byte-identical after the refused run", _snapshot(conn, s_queued), before_job)

    after_dom = _domain_snapshot(conn, rid)
    for domain in ("slots", "topics", "scripts", "script_provenance", "topic_provenance"):
        check(f"{domain} unchanged by the refused run (count+content digest)",
              after_dom[domain], before_dom[domain])

    check("runner opened at least one connection (the close proof is not vacuous)",
          len(created["conns"]) > 0, True)
    check("every runner-owned connection is CLOSED",
          all(c.closed for c in created["conns"]), True)
    check("every runner-owned cursor is CLOSED",
          all(c.closed for c in created["curs"]), True)

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
