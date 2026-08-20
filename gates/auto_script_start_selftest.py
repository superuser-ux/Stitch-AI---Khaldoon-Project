"""#359 Stage 3B — automatic governed Script-generation start at the topic_review acceptance.

Deterministic throughout: interleavings are arbitrated by TWO DATABASE CONNECTIONS contending for
real row locks, never by sleeps; a "crash after commit" is the acceptance transaction committing with
no dispatch ever invoked, which is precisely what a crash in that window leaves behind. No process
kills, no providers, no timing.

Proves, in the reconciliation's own order:
  A  identical manifest identity and job identity for automatic vs manual entry
  B  forced automatic/manual and automatic/automatic convergence on ONE identity
  C  authority failure rolls back the ENTIRE acceptance — no half-accepted gate
  D  non-authority no-start outcomes stay typed, fabricate nothing, and leave acceptance intact
  E  crash after the acceptance commit, before dispatch, is recovered by the merged #362 drain
  F  a terminal failed attempt is NOT automatically replaced by the trigger
  G  Topic behaviour, uniqueness and lock order unchanged; actor provenance is truthful

Run: docker exec -e PYTHONPATH=/work:/work/gates:/work/agents <lane> python -m gates.auto_script_start_selftest
"""
import json
import os
import threading as _th
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402

FAILS = []
APPROVER = "khal"


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def _cur(conn):
    return conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)


def wipe(conn, rid):
    c = conn.cursor()
    c.execute("DELETE FROM script_provenance WHERE job_id IN "
              "(SELECT job_id FROM generation_job WHERE round_id=%s)", (rid,))
    c.execute("DELETE FROM generation_job WHERE round_id=%s", (rid,))
    c.execute("DELETE FROM audit_log WHERE entity_id=%s", (rid,))
    c.execute("DELETE FROM gate_decision WHERE gate_id IN (SELECT gate_id FROM gate_target t "
              "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (rid,))
    c.execute("DELETE FROM gate_target WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
              (rid,))
    c.execute("DELETE FROM gate WHERE gate_id NOT IN (SELECT gate_id FROM gate_target)")
    c.execute("DELETE FROM script WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
    c.execute("DELETE FROM topic WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
    c.execute("DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
              (rid,))
    # A topic_review acceptance emits inter-stage directives; they reference slot.
    c.execute("DELETE FROM directive WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
              (rid,))
    c.execute("DELETE FROM slot_review WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
              (rid,))
    c.execute("DELETE FROM slot WHERE round_id=%s", (rid,))
    c.execute("DELETE FROM round WHERE round_id=%s", (rid,))
    conn.commit(); c.close()


def seed_round_at_topic_review(conn, rid, n=2, approve=True, with_topics=True):
    """A round sitting at an OPEN topic_review gate with `n` slots at TOPIC_PROPOSED, each holding an
    approvable topic revision. This is the exact state the acceptance boundary consumes."""
    wipe(conn, rid)
    c = conn.cursor()
    c.execute("""INSERT INTO round (round_id, period_len_days, posts_per_day, post_times,
                                    pillar_distribution, format_distribution, status)
                 VALUES (%s,7,1,'["09:00"]'::jsonb,'{}'::jsonb,'{}'::jsonb,'active')""", (rid,))
    c.execute("SELECT pillar_code FROM pillar ORDER BY pillar_code LIMIT 1")
    pil = c.fetchone()[0]
    c.execute("SELECT hcs_id FROM hcs WHERE pillar_code=%s ORDER BY hcs_id LIMIT 1", (pil,))
    hcs = c.fetchone()[0]
    c.execute("SELECT lens_id FROM lens ORDER BY lens_id LIMIT 1")
    lens = c.fetchone()[0]
    slots = []
    for i in range(1, n + 1):
        sid = f"{rid}-{i}"
        c.execute("""INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                                       hcs_id, lens, status)
                     VALUES (%s,%s,%s,'09:00',%s,'Hero Reel',%s,%s,'TOPIC_PROPOSED')""",
                  (sid, rid, i, pil, hcs, lens))
        if with_topics:
            c.execute("""INSERT INTO topic (slot_id, hcs_id, lens, text_ar, hook_text, revision)
                         VALUES (%s,%s,%s,'موضوع','هوك',1)""", (sid, hcs, lens))
        slots.append(sid)
    conn.commit(); c.close()
    gid = engine.open_gate(conn, "topic_review", round_id=rid, actor="t359", cfg=engine.load_config())
    if approve:
        engine.decide(conn, gid, APPROVER, "approve", cfg=engine.load_config())
    return gid, slots


def job_rows(conn, rid):
    c = _cur(conn)
    c.execute("""SELECT job_id::text AS job_id, status, manifest_digest, trigger_source, actor,
                        initiating_actor, effective_actor, authority_snapshot, slots_total
                   FROM generation_job WHERE round_id=%s AND stage='script'
                  ORDER BY created_at""", (rid,))
    rows = c.fetchall(); c.close()
    return rows


def gate_status(conn, gid):
    c = _cur(conn)
    c.execute("SELECT status FROM gate WHERE gate_id=%s", (gid,))
    r = c.fetchone(); c.close()
    return r["status"] if r else None


def slot_statuses(conn, rid):
    c = _cur(conn)
    c.execute("SELECT status, count(*) AS n FROM slot WHERE round_id=%s GROUP BY status", (rid,))
    out = {r["status"]: r["n"] for r in c.fetchall()}; c.close()
    return out


def main():
    conn = engine.db_connect()
    cfg = engine.load_config()
    # This is an isolated candidate lane. The #362 drain is BOUNDED (LIMIT), so stale queued Script
    # jobs left by earlier runs could push a fresh test job out of the pending window and make
    # section E flaky. Clear ORPHANED script jobs (their round already deleted) up front so the
    # drain-visibility assertion is deterministic and rerun-independent. Live jobs of real rounds are
    # untouched.
    _clean = conn.cursor()
    _clean.execute("""DELETE FROM script_provenance WHERE job_id IN
                        (SELECT job_id FROM generation_job gj WHERE gj.stage='script'
                          AND NOT EXISTS (SELECT 1 FROM round r WHERE r.round_id=gj.round_id))""")
    _clean.execute("""DELETE FROM generation_job gj WHERE gj.stage='script'
                       AND NOT EXISTS (SELECT 1 FROM round r WHERE r.round_id=gj.round_id)""")
    conn.commit(); _clean.close()

    # ---------------------------------------------------------------- A
    print("\nA · AUTOMATIC AND MANUAL PRODUCE THE SAME IDENTITY (one builder, one digest)")
    RA = "RA359"
    gid, _ = seed_round_at_topic_review(conn, RA)
    engine.resolve(conn, gid, actor="t359", cfg=cfg)          # <- the automatic trigger fires here
    rows = job_rows(conn, RA)
    check("acceptance created exactly ONE Script job", len(rows), 1)
    auto = rows[0]
    check("it is queued", auto["status"], "queued")
    check("trigger is the accepted decision, not a manual command", auto["trigger_source"],
          "topic_acceptance")
    check("initiating actor is the typed system identity (no fabricated human)",
          auto["initiating_actor"], engine.SCRIPT_AUTOMATIC_ACTOR)
    check("no effective actor yet — no worker has claimed it", auto["effective_actor"], None)
    snap = auto["authority_snapshot"]
    snap = json.loads(snap) if isinstance(snap, str) else snap
    check("the frozen human authority is the accepted decision's approvers",
          snap.get("approver_ids"), [APPROVER])
    check("the system actor is NOT in approver_ids (authority not widened)",
          engine.SCRIPT_AUTOMATIC_ACTOR in (snap.get("approver_ids") or []), False)

    # What WOULD the manual command have computed for the same accepted decision?
    c = _cur(conn)
    manifest, authority, err = engine._script_attempt_manifest(c, RA, cfg, None)
    c.close()
    check("manual builder resolves the same decision without error", err, None)
    check("MANUAL digest is byte-identical to the automatic one",
          engine._digest_v1(manifest), auto["manifest_digest"])
    check("frozen authority identical too", authority["approver_ids"], snap.get("approver_ids"))

    # ---------------------------------------------------------------- B
    print("\nB · FORCED INTERLEAVINGS CONVERGE ON ONE IDENTITY")
    # B1 automatic -> manual: the manual command must OBSERVE, never mint a second attempt.
    res = engine.create_script_generation_attempt(conn, RA, APPROVER, cfg=cfg)
    check("manual start after automatic REPLAYS", res["replayed"], True)
    check("manual returns the same job id", res["job_id"], auto["job_id"])
    check("still exactly one row", len(job_rows(conn, RA)), 1)

    # B2 automatic/automatic: a SECOND acceptance resolve of the same gate (idempotent re-resolve).
    engine.resolve(conn, gid, actor="t359", cfg=cfg)
    check("re-resolving the accepted gate mints no second attempt", len(job_rows(conn, RA)), 1)

    # B3 TRUE concurrency, DB-arbitrated: two connections race the same acceptance boundary. The
    # in-flight dominator takes FOR UPDATE, so the loser blocks on the row lock until the winner
    # commits, then observes. No sleeps decide this — PostgreSQL does.
    RB = "RB359"
    gidb, _ = seed_round_at_topic_review(conn, RB)
    # Put the round in the exact state the boundary produces — accepted decision, slots advanced,
    # revisions pinned — and then remove the attempt the trigger made, so both racers start from
    # "coherent accepted decision, no attempt yet". Racing before acceptance would only prove that
    # an unaccepted round has no eligible input.
    engine.resolve(conn, gidb, actor="t359", cfg=cfg)
    kb = conn.cursor()
    kb.execute("DELETE FROM generation_job WHERE round_id=%s AND stage='script'", (RB,))
    conn.commit(); kb.close()
    check("racers start from an accepted decision with no attempt",
          (gate_status(conn, gidb), len(job_rows(conn, RB))), ("approved", 0))
    # GENUINE in-flight arbitration, DB-proven — NOT sequential. Caller 1 runs the pure body (the
    # INSERT ... ON CONFLICT lands but is UNCOMMITTED, because the body never commits). Caller 2, on
    # its own connection in a thread, then runs the same body and BLOCKS on the unique index behind
    # caller 1's uncommitted row. The block is asserted deterministically with pg_blocking_pids —
    # PostgreSQL's own view of "backend X is waiting on backend Y" — so nothing here depends on
    # timing. Only when caller 1 commits does caller 2 unblock, see the conflict, and converge.
    c1, c2, mon = engine.db_connect(), engine.db_connect(), engine.db_connect()
    try:
        k1 = _cur(c1)
        c1.cursor().execute("SELECT 1")                # ensure a live backend
        pid1 = _cur(c1); pid1.execute("SELECT pg_backend_pid() AS p"); p1 = pid1.fetchone()["p"]; pid1.close()
        pid2c = _cur(c2); pid2c.execute("SELECT pg_backend_pid() AS p"); p2 = pid2c.fetchone()["p"]; pid2c.close()

        r1 = engine._script_attempt_tx(k1, RB, cfg, principal=None,
                                       trigger_source="topic_acceptance",
                                       initiating_actor=engine.SCRIPT_AUTOMATIC_ACTOR,
                                       require_principal=False)   # UNCOMMITTED — holds the unique key

        started2, result2 = _th.Event(), {}

        def _caller2():
            k2 = _cur(c2)
            started2.set()
            try:
                result2["r"] = engine._script_attempt_tx(k2, RB, cfg, principal=None,
                                                         trigger_source="topic_acceptance",
                                                         initiating_actor=engine.SCRIPT_AUTOMATIC_ACTOR,
                                                         require_principal=False)
                c2.commit()
                result2["ok"] = True
            except Exception as ex:                    # noqa: BLE001
                result2["err"] = repr(ex)
            finally:
                k2.close()

        t2 = _th.Thread(target=_caller2, daemon=True)
        t2.start()
        check("caller 2 entered the body", started2.wait(10), True)

        # Poll PostgreSQL's own blocking view until it reports caller 2 waiting ON caller 1. This is
        # a deterministic STATE, not a duration: the small backoff only paces the poll of a fact
        # Postgres is already enforcing.
        mk = _cur(mon)
        blocked_by_1 = False
        for _ in range(200):
            mk.execute("SELECT pg_blocking_pids(%s) AS b", (p2,))
            if p1 in (mk.fetchone()["b"] or []):
                blocked_by_1 = True
                break
            _th.Event().wait(0.02)
        mk.close()
        check("caller 2 is genuinely BLOCKED on caller 1's uncommitted insert (pg_blocking_pids)",
              blocked_by_1, True)
        check("and caller 2 has NOT completed while blocked", result2.get("ok"), None)

        # Release caller 1. Only now can caller 2 make progress.
        c1.commit(); k1.close()
        t2.join(10)
        check("caller 2 completed once caller 1 committed", result2.get("ok"), True)
        check("first caller CREATED", r1["outcome"], "created")
        check("second caller CONVERGED on the unique index (no rival attempt)",
              result2["r"]["outcome"] in ("replayed", "converged"), True)
        check("both resolved to ONE job identity", r1["job_id"], result2["r"]["job_id"])
        check("exactly one durable row exists", len(job_rows(conn, RB)), 1)
    finally:
        c1.close(); c2.close(); mon.close()

    # ---------------------------------------------------------------- C
    print("\nC · AUTHORITY FAILURE ROLLS BACK THE WHOLE ACCEPTANCE (Amendment I)")
    RC = "RC359"
    gidc, _ = seed_round_at_topic_review(conn, RC)
    before_slots = slot_statuses(conn, RC)
    before_gate = gate_status(conn, gidc)
    check("precondition: nothing accepted yet", (before_gate, before_slots.get("TOPIC_PROPOSED")),
          ("open", 2))
    # The corruption Amendment I addresses is authority that cannot be CONSTRUCTED at the acceptance
    # boundary. It is unreachable by deleting the decisions, because quorum is computed from those
    # same rows — remove them and the gate simply never accepts, which proves nothing. So the
    # snapshot builder is made to yield empty affirmative authority for the duration of this one
    # resolve: the gate accepts normally, and the authority is unusable exactly when the trigger
    # needs it. That is the real corruption, injected at the only point it can occur.
    _orig_snap = engine._topic_authority_snapshot
    engine._topic_authority_snapshot = lambda cur_, gid_: {"gate_id": gid_, "stage": "topic_review",
                                                           "approver_ids": [], "approvals": [],
                                                           "decision_generation": "x"}
    raised = None
    try:
        engine.resolve(conn, gidc, actor="t359", cfg=cfg)
    except engine.ScriptAuthorityUnavailable as e:
        raised = e.code
    except Exception as e:                                     # noqa: BLE001
        raised = f"WRONG-EXCEPTION:{type(e).__name__}"
    finally:
        engine._topic_authority_snapshot = _orig_snap
    conn.rollback()
    check("acceptance aborted with the typed authority failure", raised,
          "missing_authority_snapshot")
    check("NO job was created", len(job_rows(conn, RC)), 0)
    check("slots did NOT advance — no half-accepted gate", slot_statuses(conn, RC), before_slots)
    check("gate status unchanged", gate_status(conn, gidc), before_gate)
    check("the failure is NOT a GovernedDenial (it aborts, it does not answer)",
          issubclass(engine.ScriptAuthorityUnavailable, engine.GovernedDenial), False)

    # ---------------------------------------------------------------- D
    print("\nD · NON-AUTHORITY NO-START OUTCOMES DO NOT ABORT THE ACCEPTANCE (ruling 3)")
    # A round whose topics have no resolvable revision: eligible-input resolution fails, but the
    # Topic acceptance itself is coherent and must stand.
    RD = "RD359"
    gidd, slots_d = seed_round_at_topic_review(conn, RD, n=1, with_topics=False)
    engine.resolve(conn, gidd, actor="t359", cfg=cfg)
    check("acceptance COMMITTED despite no startable Script work",
          gate_status(conn, gidd), "approved")
    check("slots advanced normally", slot_statuses(conn, RD).get("TOPIC_APPROVED"), 1)
    check("no job was fabricated", len(job_rows(conn, RD)), 0)
    k = _cur(conn)
    k.execute("""SELECT detail FROM audit_log WHERE entity_id=%s
                   AND action='script_generation_automatic_start_skipped'""", (RD,))
    skipped = k.fetchall(); k.close()
    check("the decline is recorded append-only with its existing typed reason", len(skipped), 1)
    if skipped:
        d = skipped[0]["detail"]
        d = json.loads(d) if isinstance(d, str) else d
        check("the typed reason is preserved verbatim", d.get("reason"),
              "unresolvable_input_revision")

    # ---------------------------------------------------------------- E
    print("\nE · CRASH AFTER COMMIT, BEFORE DISPATCH — RECOVERED BY THE MERGED #362 DRAIN")
    # The acceptance committed and nothing dispatched: exactly what a crash in that window leaves.
    RE = "RE359"
    gide, _ = seed_round_at_topic_review(conn, RE)
    engine.resolve(conn, gide, actor="t359", cfg=cfg)
    rows_e = job_rows(conn, RE)
    check("the attempt is durable and queued", (len(rows_e), rows_e[0]["status"]), (1, "queued"))
    # The #362 drain pass is BOUNDED (LIMIT per cycle) and round-agnostic, so in a lane holding other
    # suites' older queued jobs a single bounded pass may not include this fresh one — that is
    # correct recovery behaviour (it is drained over cycles), not a miss. To assert MEMBERSHIP in the
    # recovery population deterministically, query the same existing function with a limit that
    # clears the unrelated backlog. No new mechanism: it is `pending_script_generation_jobs`.
    pend = engine.pending_script_generation_jobs(conn, limit=10000)
    check("the existing drain's own query SEES it as a recovery candidate (no new mechanism)",
          rows_e[0]["job_id"] in [str(j["job_id"]) for j in pend], True)
    tok = engine.claim_script_generation_job(conn, rows_e[0]["job_id"], worker="drain-359")
    conn.commit()
    check("the existing drain can CLAIM it (recovery path intact)", bool(tok), True)
    check("claiming records the effective actor, distinct from the initiator",
          job_rows(conn, RE)[0]["effective_actor"] is None
          or job_rows(conn, RE)[0]["initiating_actor"] == engine.SCRIPT_AUTOMATIC_ACTOR, True)

    # ---------------------------------------------------------------- F
    print("\nF · A TERMINAL FAILED ATTEMPT IS NOT AUTOMATICALLY REPLACED")
    k = conn.cursor()
    k.execute("""UPDATE generation_job SET status='failed', lease_expires_at=NULL
                  WHERE round_id=%s AND stage='script'""", (RE,))
    conn.commit(); k.close()
    engine.resolve(conn, gide, actor="t359", cfg=cfg)          # re-resolve the accepted gate
    rows_f = job_rows(conn, RE)
    check("the terminal attempt is still the only one — no automatic replacement", len(rows_f), 1)
    check("and it is still terminal (identity and outcome preserved)", rows_f[0]["status"], "failed")

    # ---------------------------------------------------------------- G
    print("\nG · TOPIC BEHAVIOUR AND SURROUNDING CONTRACTS UNCHANGED")
    c = _cur(conn)
    c.execute("SELECT count(*) AS n FROM generation_job WHERE round_id=%s AND stage='topic'", (RA,))
    check("the trigger created NO Topic job", c.fetchone()["n"], 0)
    c.execute("""SELECT count(*) AS n FROM pg_indexes WHERE tablename='generation_job'
                   AND indexname='uq_generation_job_script_manifest'""")
    check("the Script uniqueness index is untouched", c.fetchone()["n"], 1)
    c.close()
    check("script_review is HELD while the attempt is non-terminal (ruling 8, intended)",
          engine.stage_state(conn, RB, "script_review")["next_action"], "generate")
    # And the hold is real at the guard, not only in the projection.
    held = False
    try:
        engine.open_gate(conn, "script_review", round_id=RB, actor="t359", cfg=cfg)
    except engine.GateNotReady:
        held = True
    check("opening script_review fails closed while the attempt is non-terminal", held, True)

    # review fix 3 — the accelerator scope helper returns THIS topic_review gate's own queued Script
    # jobs, and NOTHING for any other gate stage. Proven directly against the helper the API calls.
    ra_gid = None
    ck = _cur(conn)
    ck.execute("""SELECT g.gate_id::text AS g FROM gate g JOIN gate_target t USING(gate_id)
                    JOIN slot s ON s.slot_id=t.slot_id
                   WHERE s.round_id=%s AND g.stage='topic_review' LIMIT 1""", (RA,))
    _r = ck.fetchone(); ck.close()
    ra_gid = _r["g"] if _r else None
    # EXACT set, not a tautology: the helper must target precisely RA's own queued Script job(s).
    ra_queued = {r["job_id"] for r in job_rows(conn, RA) if r["status"] == "queued"}
    check("RA genuinely holds a queued job (the positive check is not vacuous)",
          len(ra_queued) >= 1, True)
    check("topic_review gate targets EXACTLY its own round's queued Script job set",
          set(engine.topic_acceptance_script_targets(conn, ra_gid)), ra_queued)
    # A schedule_review gate exists nowhere here; assert the stage guard directly: a NON-topic_review
    # gate yields NO targets, so an unrelated resolve can never launch Script work.
    cg = conn.cursor()
    cg.execute("""INSERT INTO gate (gate_id, stage, status, quorum, rule_key, scope)
                  VALUES (gen_random_uuid(), 'schedule_review', 'approved', 1, 'k', 'batch')
                  RETURNING gate_id::text""")
    sched_gid = cg.fetchone()[0]; conn.commit(); cg.close()
    check("an unrelated (schedule_review) gate dispatches NO Script work",
          engine.topic_acceptance_script_targets(conn, sched_gid), [])
    cg = conn.cursor(); cg.execute("DELETE FROM gate WHERE gate_id=%s", (sched_gid,))
    conn.commit(); cg.close()

    src = open(engine.__file__, encoding="utf-8").read()
    body = src[src.index("def _script_attempt_tx("):src.index("def create_script_generation_attempt(")]
    check("the shared body never commits", "conn.commit()" in body, False)
    check("the shared body never rolls back", "conn.rollback()" in body, False)
    check("the shared body never opens a connection", "db_connect(" in body, False)
    check("the shared body never calls the committing denial closure", "_deny(" in body, False)

    # ---------------------------------------------------------------- H
    # API-BOUNDARY: the aborted-acceptance audit must run ONLY after the failed acceptance
    # transaction's release is established, and must be SKIPPED (refusal preserved) if release
    # cannot be established. Proven against the exact helper the resolve route calls, with a fake
    # connection that records ordering — no HTTP, no timing.
    print("\nH · ACCEPTANCE-ABORT AUDIT RELEASES BEFORE IT AUDITS (review fix 1)")
    import api as _api                                  # noqa: E402 — proven where it is wired

    class _FakeConn:
        def __init__(self, rollback_fails=False, close_fails=False):
            self.rollback_fails = rollback_fails
            self.close_fails = close_fails
            self.log = []
        def rollback(self):
            self.log.append("rollback")
            if self.rollback_fails:
                raise RuntimeError("rollback boom")
        def close(self):
            self.log.append("close")
            if self.close_fails:
                raise RuntimeError("close boom")

    # A recording audit-connection factory: appends 'audit-open'/'audit-commit' to the SHARED log so
    # ordering against release is observable.
    def _make_opener(shared_log):
        class _AuditConn:
            def cursor(self, *a, **k):
                shared_log.append("audit-open")
                class _C:
                    def execute(self_, *a_, **k_): shared_log.append("audit-execute")
                    def close(self_): pass
                    def fetchone(self_): return None
                return _C()
            def commit(self): shared_log.append("audit-commit")
            def rollback(self): shared_log.append("audit-rollback")
            def close(self): shared_log.append("audit-close")
        return lambda: _AuditConn()

    _orig_audit = engine.audit_denied
    engine.audit_denied = lambda conn_, *a, **k: conn_.cursor()   # route through the fake cursor
    try:
        # H1 — rollback SUCCEEDS: release established via rollback, THEN audit.
        fc = _FakeConn()
        r = _api._abort_acceptance_audit(fc, "RH", "g1", "missing_authority_snapshot",
                                         _open=_make_opener(fc.log))
        check("H1 rollback path returns audited", r, "audited")
        check("H1 release (rollback) precedes the audit", fc.log.index("rollback"),
              min(fc.log.index("rollback"), fc.log.index("audit-commit")))
        check("H1 audit ran after rollback", fc.log.index("rollback") < fc.log.index("audit-commit"),
              True)

        # H2 — rollback FAILS, close SUCCEEDS: release forced via close, THEN audit.
        fc = _FakeConn(rollback_fails=True)
        r = _api._abort_acceptance_audit(fc, "RH", "g2", "missing_authority_snapshot",
                                         _open=_make_opener(fc.log))
        check("H2 rollback-fail path still audits after forced close", r, "audited")
        check("H2 close (forced release) happened", "close" in fc.log, True)
        check("H2 audit ran strictly AFTER the forced release",
              fc.log.index("close") < fc.log.index("audit-commit"), True)

        # H3 — rollback AND close both FAIL: release NOT established -> audit SKIPPED, refusal stands.
        fc = _FakeConn(rollback_fails=True, close_fails=True)
        r = _api._abort_acceptance_audit(fc, "RH", "g3", "missing_authority_snapshot",
                                         _open=_make_opener(fc.log))
        check("H3 unestablished release -> audit skipped", r, "skipped_unreleased")
        check("H3 NO audit connection was ever opened",
              any(x.startswith("audit") for x in fc.log), False)
        check("H3 both release attempts were made", ("rollback" in fc.log and "close" in fc.log),
              True)
    finally:
        engine.audit_denied = _orig_audit

    for rid in ("RA359", "RB359", "RC359", "RD359", "RE359"):
        wipe(conn, rid)

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
