"""#292 — deterministic proof of the governed schedule mapping's concurrency invariants.

WHY A SEPARATE MODULE: these are the only checks in the repo that need TWO real connections racing
each other, so they need their own fixture round and their own thread plumbing.

DETERMINISM WITHOUT SLEEPS — the rule this module exists to honour:
    The DB LOCK IS THE BARRIER. Where an interleaving must be forced, one thread takes the round
    lock and signals a threading.Event; the other then attempts the same lock and BLOCKS in
    postgres. That block is a real event, not a timer: no sleep, no poll, no retry, no wall-clock
    assumption. Ordering is enforced by the database, exactly as it is in production.

Run:  docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.schedule_concurrency_selftest
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))   # repo root, for integrations/
import engine          # noqa: E402
import run_writers as W  # noqa: E402

RID = "RSEQ292"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} want={want}")
    if not ok:
        FAILS.append(label)


class FakeChat:
    """Deterministic stand-in for the writer's model client — mirrors gates/selftest.py's FakeChat.
    It is what lets these proofs exercise the REAL process_topic path with no network."""

    def __init__(self):
        self.model, self.n = "fake:test", 0

    def complete(self, system, user):
        self.n += 1
        return json.dumps({
            "maps_to_hcs": True,
            "topic_angle": f"زاوية تجريبية رقم {self.n}",
            "hook_text": "الخوف بياكل قرارك اليوم",
            "hook_type": "Painful Truth",
            "rationale_ar": "سبب مختصر",
            "rationale_en": "why this topic now (test)"}, ensure_ascii=False)


class FakeEmbed:
    def embed(self, text):
        out = []
        i = 0
        while len(out) < 1024:
            out.extend((b / 127.5 - 1.0) for b in hashlib.sha256(f"{text}|{i}".encode()).digest())
            i += 1
        return out[:1024]


SLOTS = [("RSEQ292-1", "P1_SELF", "P1", 1, "1.1"),
         ("RSEQ292-2", "P2_RELATIONSHIPS", "P2", 1, "2.1"),
         ("RSEQ292-3", "P3_PARENTING", "P3", 1, "3.1")]


def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE %s", (RID + "%",))
    cur.execute("DELETE FROM slot  WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit(); cur.close()


def seed(conn):
    """Isolated, synthetic, non-client fixture. Never touches another round."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id)
                   VALUES (%s,'292-concurrency',1,3,'["09:00"]','{}','{}','planning','e2e')""", (RID,))
    # pillar_short_code / seq_in_pillar are NOT slot columns — they come from pillar.code_short and
    # hcs.seq_in_pillar via the same join the read model uses. The fixture therefore reuses the
    # real catalogue rows rather than inventing a parallel one.
    for sid, pillar, _short, _seq, hcs in SLOTS:
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,
                       hcs_id,lens,hook_type,status,cycle_no,topic_angle,hook_text,
                       format,tenant_id)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','SCHEDULE_APPROVED',1,
                               'زاوية','خليك أقوى','Hero Reel','e2e')""",
                    (sid, RID, pillar, hcs))
    conn.commit(); cur.close()


def _order(conn):
    m = engine.schedule_mapping(conn, RID)
    return [p["slot_id"] for p in m["positions"]], m["schedule_token"]


def _gen_count(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM schedule_display_generation WHERE round_id=%s", (RID,))
    n = cur.fetchone()[0]; cur.close()
    return n


def _topic_count(conn, slot_id):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM topic WHERE slot_id=%s", (slot_id,))
    n = cur.fetchone()[0]; cur.close()
    return n


def _audits(conn, action):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM audit_log WHERE entity_id=%s AND action=%s", (RID, action))
    n = cur.fetchone()[0]; cur.close()
    return n


def main():
    cfg = engine.load_config()
    conn = engine.db_connect()
    teardown(conn); seed(conn)
    actor = "khal"

    print(f"\n#292 schedule concurrency — fixture {RID} (synthetic, isolated)")

    # ---- 1. initialization: a new round is governed from birth -------------------------------
    print("\n1) initial generation (deterministic, position-derived codes)")
    gen = engine.initialize_schedule_mapping(conn, RID, actor="system")
    check("initial generation is 1", gen, 1)
    order, token = _order(conn)
    check("token after init", token, 1)
    check("initial order is planning order", order, ["RSEQ292-1", "RSEQ292-2", "RSEQ292-3"])
    m = engine.schedule_mapping(conn, RID)
    codes = [p["display_code"] for p in m["positions"]]
    # posts_per_day=3 -> positions 1..3 all land on day 01, posts .01/.02/.03
    check("position-derived codes", codes, ["P01-HS01-01.01", "P02-HS01-01.02", "P03-HS01-01.03"])
    check("initialize is idempotent (no second generation)",
          engine.initialize_schedule_mapping(conn, RID, actor="system"), None)

    # ---- 2. stage-aware predicate: Schedule's OWN decision is not downstream ------------------
    print("\n2) downstream predicate is EXACT and stage-aware")
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    check("SCHEDULE_APPROVED slots are not downstream",
          engine._downstream_advanced(cur, [s[0] for s in SLOTS]), [])
    # A decision on the round's OWN schedule_review gate must not make its slots look advanced.
    cur.execute("INSERT INTO gate (scope, stage, status, tenant_id) "
                "VALUES ('item','schedule_review','open','e2e') RETURNING gate_id")
    sched_gate = cur.fetchone()["gate_id"]
    cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s)", (sched_gate, "RSEQ292-1"))
    cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                "VALUES (%s,%s,%s,'approve')", (sched_gate, "RSEQ292-1", actor))
    conn.commit()
    check("a schedule_review decision is NOT downstream evidence",
          engine._downstream_advanced(cur, ["RSEQ292-1"]), [])
    # ...but a decision on a LATER stage is.
    cur.execute("INSERT INTO gate (scope, stage, status, tenant_id) "
                "VALUES ('item','topic_review','open','e2e') RETURNING gate_id")
    topic_gate = cur.fetchone()["gate_id"]
    cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s)", (topic_gate, "RSEQ292-1"))
    cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                "VALUES (%s,%s,%s,'approve')", (topic_gate, "RSEQ292-1", actor))
    conn.commit()
    check("a topic_review decision IS downstream evidence",
          engine._downstream_advanced(cur, ["RSEQ292-1"]), ["RSEQ292-1"])
    cur.execute("DELETE FROM gate WHERE gate_id IN (%s,%s)", (sched_gate, topic_gate))
    conn.commit()
    check("predicate clean again after removing the later-stage gate",
          engine._downstream_advanced(cur, ["RSEQ292-1"]), [])
    cur.close()

    # ---- 3. a governed reorder -----------------------------------------------------------------
    print("\n3) governed reorder renumbers presentation; canonical ids never move")
    res = engine.reorder_schedule(conn, RID, ["RSEQ292-3", "RSEQ292-1", "RSEQ292-2"], 1, actor=actor)
    check("token advanced", res["schedule_token"], 2)
    order, token = _order(conn)
    check("accepted order", order, ["RSEQ292-3", "RSEQ292-1", "RSEQ292-2"])
    check("codes follow POSITION, not the slot",
          [p["display_code"] for p in engine.schedule_mapping(conn, RID)["positions"]],
          ["P03-HS01-01.01", "P01-HS01-01.02", "P02-HS01-01.03"])
    c2 = conn.cursor()
    c2.execute("SELECT count(*) FROM slot WHERE round_id=%s AND day=1 AND time_uae='09:00'", (RID,))
    check("physical day/time untouched by reorder", c2.fetchone()[0], 3)
    c2.execute("SELECT array_agg(slot_id ORDER BY slot_id) FROM slot WHERE round_id=%s", (RID,))
    check("canonical slot_ids unchanged", c2.fetchone()[0], ["RSEQ292-1", "RSEQ292-2", "RSEQ292-3"])
    c2.close()
    check("prior generation still readable (append-only history)", _gen_count(conn), 2)
    check("winning audit written once", _audits(conn, "schedule_reordered"), 1)

    # ---- 4. stale token -> typed 409, no mutation ----------------------------------------------
    print("\n4) stale token is rejected without mutating anything")
    gens_before = _gen_count(conn)
    try:
        engine.reorder_schedule(conn, RID, ["RSEQ292-1", "RSEQ292-2", "RSEQ292-3"], 1, actor=actor)
        check("stale token raises", False, True)
    except engine.ScheduleConflict as e:
        check("stale token -> ScheduleConflict", True, True)
        check("conflict carries current token", e.current.get("current_token"), 2)
    check("rejection created NO generation", _gen_count(conn), gens_before)
    check("rejection audited as a rejection (not a mutation)",
          _audits(conn, "schedule_reorder_rejected") >= 1, True)
    check("order unchanged after rejection", _order(conn)[0], ["RSEQ292-3", "RSEQ292-1", "RSEQ292-2"])
    check("incomplete permutation rejected",
          isinstance(_expect_error(lambda: engine.reorder_schedule(
              conn, RID, ["RSEQ292-1"], 2, actor=actor)), engine.GateError), True)
    check("still no extra generation", _gen_count(conn), gens_before)

    # ---- 5. EXACTLY-ONE-WINNER under true concurrency ------------------------------------------
    # Both threads submit a reorder at the SAME token, released together by a Barrier. They
    # serialize on the round row; exactly one may win.
    print("\n5) two concurrent reorders at the same token -> exactly one winner")
    _, base = _order(conn)
    barrier = threading.Barrier(2)
    results = {}

    def racer(name, order_):
        c = engine.db_connect()
        try:
            barrier.wait()                       # release both at once — no sleep
            engine.reorder_schedule(c, RID, order_, base, actor=actor)
            results[name] = "won"
        except engine.ScheduleConflict:
            results[name] = "conflict"
        except engine.GateError as e:
            results[name] = f"error:{e}"
        finally:
            c.close()

    t1 = threading.Thread(target=racer, args=("A", ["RSEQ292-1", "RSEQ292-2", "RSEQ292-3"]))
    t2 = threading.Thread(target=racer, args=("B", ["RSEQ292-2", "RSEQ292-1", "RSEQ292-3"]))
    t1.start(); t2.start(); t1.join(); t2.join()
    check("exactly one winner", sorted(results.values()), ["conflict", "won"])
    check("exactly one new generation", _gen_count(conn), gens_before + 1)
    check("exactly one winning audit", _audits(conn, "schedule_reordered"), 2)

    # ---- 6. SYMMETRIC RACE, direction A: downstream persist wins first -------------------------
    print("\n6A) downstream persist wins -> reorder fails closed, leaves no generation/positions")
    _, tok = _order(conn)
    W.process_topic(conn, FakeChat(), None, FakeEmbed(), cfg,
                    _slot_row(conn, "RSEQ292-1"), dry_run=False)
    check("topic persisted", _topic_count(conn, "RSEQ292-1"), 1)
    gens_now = _gen_count(conn)
    err = _expect_error(lambda: engine.reorder_schedule(
        conn, RID, ["RSEQ292-1", "RSEQ292-2", "RSEQ292-3"], tok, actor=actor))
    check("reorder fails closed on downstream advancement", isinstance(err, engine.GateError), True)
    check("...naming the advanced slot", "RSEQ292-1" in str(err), True)
    check("no generation created by the failed reorder", _gen_count(conn), gens_now)

    # ---- 7. SYMMETRIC RACE, direction B: reorder wins first ------------------------------------
    # THE RACE WINDOW IS THE MODEL CALL. process_topic captures the token at entry, generates, then
    # revalidates before its first insert — so the only way to drive direction B honestly is to let a
    # governed reorder commit WHILE generation is in flight. FakeChat.complete() is exactly that
    # moment, so the reorder is issued from inside it on a SEPARATE connection. Deterministic, no
    # sleep: the model call is the barrier, and it models production exactly.
    print("\n7B) reorder wins DURING generation -> stale writer aborts with NO artifact/status/audit")
    teardown(conn); seed(conn); engine.initialize_schedule_mapping(conn, RID, actor="system")
    slot = _slot_row(conn, "RSEQ292-2")
    _, tok = _order(conn)
    fired = {"done": False}

    class RacingChat(FakeChat):
        """Commits a governed reorder the first time the writer calls the model."""

        def complete(self, system, user):
            if not fired["done"]:
                fired["done"] = True
                c2 = engine.db_connect()
                try:
                    engine.reorder_schedule(c2, RID, ["RSEQ292-3", "RSEQ292-2", "RSEQ292-1"],
                                            tok, actor=actor)
                finally:
                    c2.close()
            return super().complete(system, user)

    outcome = {}
    try:
        W.process_topic(conn, RacingChat(), None, FakeEmbed(), cfg, slot, dry_run=False)
        outcome["result"] = "persisted"
    except engine.ScheduleConflict:
        outcome["result"] = "aborted"
    finally:
        conn.rollback()

    check("a reorder did land during generation", fired["done"], True)
    check("token advanced while generating", _order(conn)[1], tok + 1)
    check("stale writer ABORTED (did not persist)", outcome.get("result"), "aborted")
    check("no topic row", _topic_count(conn, "RSEQ292-2"), 0)
    c3 = conn.cursor()
    c3.execute("SELECT status FROM slot WHERE slot_id='RSEQ292-2'")
    check("no status change", c3.fetchone()[0], "SCHEDULE_APPROVED")
    c3.close()
    check("no mutation audit for the aborted writer",
          _audits(conn, "topic_proposed") + _audits(conn, "status_change"), 0)
    check("no partial mapping (only init + the reorder)", _gen_count(conn), 2)

    # ---- 8. BLOCKING LOCK: the lock itself is the barrier --------------------------------------
    print("\n8) a competing writer BLOCKS on the round lock (no sleep, no poll)")
    held = threading.Event()
    released = threading.Event()
    blocked = {}

    def holder():
        c = engine.db_connect()
        try:
            cc = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
            engine._lock_round(cc, RID)        # hold the round row
            held.set()
            released.wait()                    # keep holding until the main thread says so
            c.rollback()
            cc.close()
        finally:
            c.close()

    def contender():
        c = engine.db_connect()
        try:
            cc = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
            blocked["entered"] = True
            engine._lock_round(cc, RID)        # BLOCKS in postgres until the holder releases
            blocked["acquired_after_release"] = released.is_set()
            c.rollback(); cc.close()
        finally:
            c.close()

    h = threading.Thread(target=holder); h.start(); held.wait()
    cth = threading.Thread(target=contender); cth.start()
    # The contender is now blocked in the DB. Release and let it through — ordering is enforced by
    # postgres, never by wall-clock.
    released.set()
    h.join(); cth.join(timeout=30)
    check("contender entered", blocked.get("entered"), True)
    check("contender acquired the lock only AFTER the holder released",
          blocked.get("acquired_after_release"), True)

    # ---- 9. REVISION vs FIRST-TOPIC WRITER: mutable slot state is read UNDER the round lock ------
    # The defect this proves absent: revise_schedule_slot used to SELECT the slot's status BEFORE
    # taking the round lock, then validate that stale snapshot after acquiring it. A writer that
    # commits inside the window (process_topic persisting the first topic, SCHEDULE_APPROVED ->
    # TOPIC_PROPOSED) left the revision believing the slot was still at schedule stage, so it pushed
    # a slot that now carries a topic back to RESERVED — silently reopening downstream content. The
    # combined token cannot catch it: topic persistence changes no schedule mapping, so the token is
    # unchanged and the revision sails through its conflict check.
    #
    # The interleaving is forced by the DB, not by wall-clock: the writer holds the round lock, the
    # reviser BLOCKS on that same lock, and we wait on pg_blocking_pids() — an observed database wait
    # state, not a timer — before letting the writer commit. That guarantees the reviser is parked
    # INSIDE the window under test.
    print("\n9) a revision that races first-topic persistence re-reads status under the lock")
    teardown(conn); seed(conn)
    engine.initialize_schedule_mapping(conn, RID, actor="system", cfg=cfg)
    _, tok9 = _order(conn)
    target = SLOTS[0][0]
    writer_locked = threading.Event()
    writer_committed = threading.Event()
    reviser_parked = threading.Event()
    race = {}

    def racing_writer():
        c = engine.db_connect()
        try:
            cc = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
            engine._lock_round(cc, RID)          # hold the round: the reviser must queue behind this
            writer_locked.set()
            reviser_parked.wait()                # only proceed once the reviser is provably blocked
            cc.execute("SELECT * FROM slot WHERE slot_id=%s", (target,))
            slot_row = cc.fetchone()
            W.process_topic(c, FakeChat(), None, FakeEmbed(), cfg, slot_row, dry_run=False)
            c.commit()                           # first topic is now durable; slot is TOPIC_PROPOSED
            writer_committed.set()
            cc.close()
        finally:
            c.close()                            # releases the round lock -> reviser wakes up

    def reviser():
        c = engine.db_connect()
        try:
            # Bound the lock wait in the DATABASE. The reviser is meant to block here briefly and
            # then proceed; a statement_timeout means a genuine hang surfaces as a reported failure
            # instead of an indefinitely stuck run. It never orders the interleaving — the lock does.
            b = c.cursor(); b.execute("SET statement_timeout = '60s'"); b.close()
            # A GOVERNED schedule field (see _SCHEDULE_REVISION_FIELDS). Using anything else is
            # rejected during argument validation before any DB work, so the reviser would never
            # reach the lock and the "race" would prove nothing while still reporting "refused".
            engine.revise_schedule_slot(c, target, {"topic_guidance": "وجّه الزاوية بعد السباق"},
                                        actor="khal", cfg=cfg, expected_token=tok9)
            c.commit()
            race["outcome"] = "applied"
        except engine.GateError as e:
            race["outcome"] = "refused"
            race["error"] = str(e)
        except Exception as e:                   # noqa: BLE001 — any other failure is a real failure
            race["outcome"] = f"unexpected:{type(e).__name__}"
            race["error"] = str(e)
        finally:
            c.close()

    wt = threading.Thread(target=racing_writer); wt.start(); writer_locked.wait()
    rt = threading.Thread(target=reviser); rt.start()
    parked = _wait_until_blocked_on()            # observed DB wait state — no sleep, no wall-clock
    # Release the writer UNCONDITIONALLY: if the detector never saw the park, the proof is invalid and
    # must be reported as a failed check — it must never strand the writer holding the round lock and
    # deadlock the run against its own barrier.
    reviser_parked.set()
    wt.join(timeout=60); rt.join(timeout=60)

    print(f"    [info] reviser outcome={race.get('outcome')} error={race.get('error')!r}")
    check("the reviser was observed parked on the round lock (window is real)", parked, True)
    check("the racing writer committed the first topic", writer_committed.is_set(), True)
    # The reviser resumed AFTER the writer committed. Under the lock the slot is TOPIC_PROPOSED, so
    # the bounded precondition must refuse it. Before the fix this returned "applied".
    check("the revision REFUSED the now-TOPIC_PROPOSED slot", race.get("outcome"), "refused")
    check("the refusal names the reopen requirement",
          "reopen" in (race.get("error") or "").lower(), True)
    # …and nothing downstream was silently reopened or remapped.
    check("slot status was NOT reopened to RESERVED", _slot_row(conn, target)["status"], "TOPIC_PROPOSED")
    check("the persisted topic survives the race", _topic_count(conn, target), 1)
    check("no schedule_revision audit was written", _audits(conn, "schedule_revision"), 0)
    check("the mapping generation is untouched", _gen_count(conn), 1)

    # ---- 10. NEW ROUND ATOMICITY: mapping failure rolls the WHOLE round back --------------------
    # The defect this proves absent: the API used to plan+commit the round, then open a SECOND
    # connection to create mapping generation 1. Anything that failed after that first commit left a
    # durable round with no governed mapping — indistinguishable from a genuine pre-#292 round
    # (legacy by absence) even though the endpoint reported failure. Generation 1 now lives in the
    # planner's own transaction, so a mapping error takes the round and its slots down with it.
    print("\n10) a NEW round is atomic: a mapping failure rolls back the whole run")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "planner"))
    import plan_round as P                                   # noqa: E402
    PROBE = "292-atomicity-probe"
    rounds_before = _round_count_by_label(conn, PROBE)
    real_init = engine.initialize_schedule_mapping
    # #276 — format_mix is REQUIRED and is validated against the CURRENT baseline policy, so it is
    # resolved from that policy here rather than hard-coded. Passing None (or a stale framework) is
    # rejected during argument validation, which would make this probe "raise" without the planner
    # ever creating anything — a proof that proves nothing.
    _elig = P.baseline_eligibility_api(cfg)["eligible"]
    probe_mix = {_elig[0]["name"]: 1}                # days=1 × posts_per_day=1 -> exactly 1 slot
    FORCED = "forced mapping failure (atomicity probe)"

    def exploding_init(*a, **kw):
        raise RuntimeError("forced mapping failure (atomicity probe)")

    # plan_round holds `import engine as _engine` — the SAME module object — so patching here is what
    # the planner will call. Restored in finally: a probe must never leave the engine altered.
    engine.initialize_schedule_mapping = exploding_init
    try:
        P.plan_round_api(cfg, 1, 1, label=PROBE, format_mix=probe_mix)
        atomic = "committed"
    except Exception as e:                                   # noqa: BLE001 — expect the forced one
        atomic = "raised" if FORCED in str(e) else f"other:{e}"
    finally:
        engine.initialize_schedule_mapping = real_init

    # Assert the FORCED failure specifically: a bare "an exception happened" would also pass on an
    # argument-validation error, in which case the planner never created anything and the rollback
    # check below would be vacuously true.
    check("the failing creation surfaced the INJECTED mapping error", atomic, "raised")
    check("NO round survives the failed creation (whole run rolled back)",
          _round_count_by_label(conn, PROBE), rounds_before)
    check("the engine was restored after the probe",
          engine.initialize_schedule_mapping is real_init, True)
    # …and the happy path still yields a round governed from birth, in ONE transaction.
    ok = P.plan_round_api(cfg, 1, 1, label=PROBE, format_mix=probe_mix)
    check("a successful creation IS governed from birth (generation 1 exists)",
          _gen_count_for(conn, ok["round_id"]), 1)
    _drop_round(conn, ok["round_id"])

    # The CLI `plan()` is a SEPARATE creation path with its own transaction — patching it without
    # proving it would leave the duplicate-path concern only half closed, so it gets the same
    # failure-injection proof rather than an argument that it is "probably fine".
    CLI_PROBE = "292-atomicity-probe-cli"
    cli_args = argparse.Namespace(
        config=os.environ.get("TANAGHOM_CONFIG", str(P.DEFAULT_CONFIG)),
        template=None, round_id=None, label=CLI_PROBE)
    cli_before = _round_count_by_label(conn, CLI_PROBE)
    engine.initialize_schedule_mapping = exploding_init
    try:
        P.plan(cli_args)
        cli_atomic = "committed"
    except Exception as e:                                   # noqa: BLE001 — expect the forced one
        cli_atomic = "raised" if FORCED in str(e) else f"other:{e}"
    finally:
        engine.initialize_schedule_mapping = real_init

    check("CLI: the failing creation surfaced the INJECTED mapping error", cli_atomic, "raised")
    check("CLI: NO round survives the failed creation (whole run rolled back)",
          _round_count_by_label(conn, CLI_PROBE), cli_before)
    # …and the CLI happy path is governed from birth too.
    P.plan(cli_args)
    cli_rid = _round_id_by_label(conn, CLI_PROBE)
    check("CLI: a successful creation IS governed from birth (generation 1 exists)",
          _gen_count_for(conn, cli_rid), 1)
    _drop_round(conn, cli_rid)
    check("CLI probe cleaned up", _round_count_by_label(conn, CLI_PROBE), cli_before)

    # ---- 11. RUN PLACEMENT (#304): governed, concurrency-protected, frozen after execution -------
    # A run's absolute placement is the ONLY new authority in #304, so it must prove it reuses the
    # existing contracts rather than inventing parallel ones: schedule_review authority, the COMBINED
    # schedule token, and the exact `_downstream_advanced` freeze predicate over persisted facts.
    print("\n11) run placement is governed, token-checked, audited, and frozen after execution")
    teardown(conn); seed(conn)
    engine.initialize_schedule_mapping(conn, RID, actor="system", cfg=cfg)
    _, ptok = _order(conn)
    D1 = datetime.date(2026, 9, 1)

    # legacy/unplaced is TRUTHFUL, never back-filled from created_at
    check("a run with no governed placement reads as unplaced (never created_at)",
          _round_starts_on(conn, RID), None)

    # authority: an intruder cannot place a run (fails closed, denial audited)
    err = _expect_error(lambda: engine.place_run(conn, RID, D1, actor="intruder", cfg=cfg,
                                                 expected_token=ptok))
    check("an unauthorized actor cannot place a run", isinstance(err, engine.GateError), True)
    check("the denied placement did not land", _round_starts_on(conn, RID), None)

    # concurrency: a stale/absent token is a typed 409-bearing conflict, never a silent overwrite
    stale = _expect_error(lambda: engine.place_run(conn, RID, D1, actor=actor, cfg=cfg,
                                                   expected_token=ptok - 1))
    check("a stale token is a ScheduleConflict, not an overwrite",
          isinstance(stale, engine.ScheduleConflict), True)
    absent = _expect_error(lambda: engine.place_run(conn, RID, D1, actor=actor, cfg=cfg,
                                                    expected_token=None))
    check("an ABSENT token is refused (no legacy bypass)",
          isinstance(absent, engine.ScheduleConflict), True)
    check("neither conflict placed the run", _round_starts_on(conn, RID), None)

    # the governed happy path
    res = engine.place_run(conn, RID, D1, actor=actor, cfg=cfg, expected_token=ptok)
    check("a governed placement lands", _round_starts_on(conn, RID), D1)
    check("the accepted placement echoes the token it was accepted against",
          res["schedule_token"], ptok)
    check("placement is audited append-only with old/new", _audits(conn, "run_placed"), 1)
    # a run move re-projects the SAME canonical cells: identity, day/time and mapping never move
    check("canonical slot ids unchanged by the move", _order(conn)[0],
          ["RSEQ292-1", "RSEQ292-2", "RSEQ292-3"])
    check("slot day/time untouched by the move", _slot_row(conn, SLOTS[0][0])["day"], 1)
    check("the mapping generation is untouched by a run move", _gen_count(conn), 1)

    # a correction while still planned is permitted and audited again
    D2 = datetime.date(2026, 9, 8)
    engine.place_run(conn, RID, D2, actor=actor, cfg=cfg, expected_token=ptok)
    check("a planned run's placement can be corrected", _round_starts_on(conn, RID), D2)
    check("each accepted correction appends its own audit", _audits(conn, "run_placed"), 2)

    # FREEZE: once material execution begins the placement is frozen — proven from persisted state via
    # the same predicate #292 gates reorder with, not from a UI guess or round.status.
    cur11 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    cur11.execute("SELECT * FROM slot WHERE slot_id=%s", (SLOTS[0][0],))
    W.process_topic(conn, FakeChat(), None, FakeEmbed(), cfg, cur11.fetchone(), dry_run=False)
    conn.commit(); cur11.close()
    frozen = _expect_error(lambda: engine.place_run(conn, RID, D1, actor=actor, cfg=cfg,
                                                    expected_token=ptok))
    check("placement FREEZES once a slot is downstream-advanced",
          isinstance(frozen, engine.GateError) and not isinstance(frozen, engine.ScheduleConflict), True)
    check("the freeze refusal names material execution",
          "frozen" in str(frozen).lower() and "execution" in str(frozen).lower(), True)
    check("the frozen run keeps its last governed placement", _round_starts_on(conn, RID), D2)
    check("a frozen attempt writes no acceptance audit", _audits(conn, "run_placed"), 2)

    teardown(conn)

    # ---- 12. TRIAL EQUIVALENCE (#304 A16): same governed rules, only retention may differ --------
    # #304: "Trial mode affects generated-data retention only. It must not alter policy, eligibility,
    # methodology, workflow, authority, lifecycle predicates, Schedule population, generated
    # configuration, or accepted run behavior."
    #
    # This is a REGRESSION BARRIER, not a demonstration. Today no governed path branches on a trial
    # signal — so the honest way to prove the rule is to assert that flipping every trial signal we
    # have changes NOTHING about the governed answers. If someone later writes `if trial: relax the
    # gate` (or seeds a trial-only policy), these checks fail. Passing today is the point: a second
    # trial product model must never appear, and "we never built one" is only durable if it is
    # enforced.
    print("\n12) trial and non-trial resolve IDENTICAL governed Stage 1 rules")
    teardown(conn); seed(conn)
    engine.initialize_schedule_mapping(conn, RID, actor="system", cfg=cfg)
    TRIAL_SIGNALS = ("CLIENT_TRIAL_MODE", "TANAGHOM_TRIAL_MODE", "TANAGHOM_TRIAL")

    def _governed_answers():
        """Every governed Stage 1 answer this slice depends on, resolved from live authority."""
        c2 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        cfg2 = engine.load_config()
        contract = engine.stage_approval_contract(cfg2, "schedule_review", conn=conn)
        elig = engine.resolve_run_eligibility(c2)
        tok = engine.schedule_token(c2, RID)
        adv = engine._downstream_advanced(c2, [s[0] for s in SLOTS])
        m = engine.schedule_mapping(conn, RID)
        c2.close()
        return json.dumps({
            "approval_rule": contract.get("rule"),
            "approval_quorum": contract.get("quorum"),
            "assignments": [a.get("assignment_key") for a in contract.get("assignments", [])],
            "eligible": sorted(e["name"] for e in elig["eligible"]),
            "baseline_generation": elig["policy"]["generation"],
            "schedule_token": tok,
            "downstream_advanced": sorted(adv),
            "display_codes": [p["display_code"] for p in m["positions"]],
            "positions": [p["slot_id"] for p in m["positions"]],
        }, sort_keys=True, ensure_ascii=False)

    saved = {k: os.environ.get(k) for k in TRIAL_SIGNALS}
    try:
        for k in TRIAL_SIGNALS:
            os.environ.pop(k, None)
        non_trial = _governed_answers()
        for k in TRIAL_SIGNALS:
            os.environ[k] = "true"
        trial = _governed_answers()
    finally:
        for k, v in saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    check("trial and non-trial resolve identical governed Stage 1 answers "
          "(policy, eligibility, authority, token, freeze predicate, display codes)",
          trial == non_trial, True)

    # The placement CONTRACT itself must not soften under trial either: the same stale token is
    # refused, and the same governed placement is accepted, with the trial signal on.
    os.environ["CLIENT_TRIAL_MODE"] = "true"
    try:
        cur12 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        tok12 = engine.schedule_token(cur12, RID); cur12.close()
        stale12 = _expect_error(lambda: engine.place_run(conn, RID, datetime.date(2026, 10, 1),
                                                         actor=actor, cfg=cfg, expected_token=tok12 - 1))
        check("under trial, a stale token is STILL refused",
              isinstance(stale12, engine.ScheduleConflict), True)
        intruder12 = _expect_error(lambda: engine.place_run(conn, RID, datetime.date(2026, 10, 1),
                                                            actor="intruder", cfg=cfg,
                                                            expected_token=tok12))
        check("under trial, authority is STILL enforced",
              isinstance(intruder12, engine.GateError), True)
        engine.place_run(conn, RID, datetime.date(2026, 10, 1), actor=actor, cfg=cfg,
                         expected_token=tok12)
        check("under trial, a governed placement is accepted the same way",
              _round_starts_on(conn, RID), datetime.date(2026, 10, 1))
    finally:
        os.environ.pop("CLIENT_TRIAL_MODE", None)

    teardown(conn)

    # ---- 13. #306 Stage 1B: governed Pillar/HCS override is RUN-LOCAL and CURSOR-NEUTRAL ---------
    # The whole contract rests on one claim: an operator override changes ONE slot's classification
    # and leaves cross-run planner state byte-identical. If that is false, every future run is
    # silently reinterpreted by a past run's edit. So it is proven, not asserted.
    print("\n13) #306 governed Pillar/HCS override: run-local, cursor-neutral, pin-resolved")
    teardown(conn); seed(conn)
    # The taxonomy WRITE requires a PINNED methodology generation, so §13 plans a real run (which
    # pins one) rather than the legacy seed fixture. sys.path already has planner/ from §10.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "planner"))
    import plan_round as _P13  # noqa: E402
    _elig13 = _P13.baseline_eligibility_api(cfg)["eligible"]
    _mix13 = {_elig13[0]["name"]: 2, _elig13[1]["name"]: 2} if len(_elig13) > 1 else {_elig13[0]["name"]: 4}
    RID13 = _P13.plan_round_api(cfg, 2, 2, label="306-selftest", format_mix=_mix13)["round_id"]
    engine.initialize_schedule_mapping(conn, RID13, actor="system", cfg=cfg)
    _, tok13 = _order13(conn, RID13)
    target13 = _first_slot(conn, RID13)
    _hcs_before13 = _slot_row(conn, target13)["hcs_id"]

    # A REAL alternative HCS from RID13's PINNED generation, under a DIFFERENT pillar than the slot
    # currently holds, so the atomic-pair + tuple resolution is genuinely exercised.
    c13 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    c13.execute("""SELECT mh.hcs_id, mh.pillar_code
                     FROM methodology_hcs mh
                     JOIN round_policy_snapshot rp ON rp.methodology_version = mh.version_id::text
                    WHERE rp.round_id=%s AND mh.pillar_code <> %s
                    ORDER BY mh.pillar_code, mh.seq_in_pillar LIMIT 1""",
                (RID13, _slot_row(conn, target13)["pillar_code"]))
    alt = c13.fetchone(); c13.close()

    cursor_before = _snapshot(conn, "SELECT pillar_code, last_hcs_id, cycle_no FROM hcs_cursor ORDER BY pillar_code")
    lens_before   = _snapshot(conn, "SELECT hcs_id, cycle_no, lens FROM lens_history ORDER BY hcs_id, cycle_no")
    cycle_before  = _slot_row(conn, target13)["cycle_no"]

    # fail closed: HCS that is not in the pinned generation
    e1 = _expect_error(lambda: engine.revise_schedule_slot(
        conn, target13, {"pillar_code": "P1_SELF", "hcs_id": "NOT-A-REAL-HCS"},
        actor=actor, cfg=cfg, expected_token=tok13))
    check("an HCS outside the run's pinned generation fails closed", isinstance(e1, engine.GateError), True)

    # fail closed: HCS that does not belong to the named pillar (dependent combination)
    e2 = _expect_error(lambda: engine.revise_schedule_slot(
        conn, target13, {"pillar_code": "P1_SELF", "hcs_id": alt["hcs_id"]},
        actor=actor, cfg=cfg, expected_token=tok13))
    check("a dependent Pillar/HCS mismatch fails closed", isinstance(e2, engine.GateError), True)

    # fail closed: the pair is atomic — one without the other is refused
    e3 = _expect_error(lambda: engine.revise_schedule_slot(
        conn, target13, {"hcs_id": alt["hcs_id"]}, actor=actor, cfg=cfg, expected_token=tok13))
    check("hcs_id without pillar_code is refused (atomic pair)", isinstance(e3, engine.GateError), True)

    # fail closed: authority and token, on the taxonomy path specifically
    e4 = _expect_error(lambda: engine.revise_schedule_slot(
        conn, target13, {"pillar_code": alt["pillar_code"], "hcs_id": alt["hcs_id"]},
        actor="intruder", cfg=cfg, expected_token=tok13))
    check("an unauthorized taxonomy override is refused", isinstance(e4, engine.GateError), True)
    e5 = _expect_error(lambda: engine.revise_schedule_slot(
        conn, target13, {"pillar_code": alt["pillar_code"], "hcs_id": alt["hcs_id"]},
        actor=actor, cfg=cfg, expected_token=tok13 - 1))
    check("a stale-token taxonomy override is a ScheduleConflict", isinstance(e5, engine.ScheduleConflict), True)
    check("no refusal changed the slot", _slot_row(conn, target13)["hcs_id"], _hcs_before13)

    # the governed happy path
    before_codes = [p["display_code"] for p in engine.schedule_mapping(conn, RID13)["positions"]]
    res13 = engine.revise_schedule_slot(conn, target13, {"pillar_code": alt["pillar_code"],
                                                         "hcs_id": alt["hcs_id"]},
                                        actor=actor, cfg=cfg, expected_token=tok13)
    row13 = _slot_row(conn, target13)
    check("the override lands the pinned pair", (row13["pillar_code"], row13["hcs_id"]),
          (alt["pillar_code"], alt["hcs_id"]))
    check("a lens valid for the NEW hcs was resolved", bool(row13["lens"]), True)
    # #306 P1.2 — the FULL tuple (pillar, hcs, lens, hook_type) must be coherent within ONE pinned
    # version: the new hcs recommends the lens, and the lens's default hook is what the slot now holds.
    check("hook_type was re-resolved together with lens", bool(row13["hook_type"]), True)
    tuple_ok = _tuple_coherent(conn, RID13, row13["hcs_id"], row13["lens"], row13["hook_type"])
    check("pillar/hcs/lens/hook_type all resolve from ONE pinned generation", tuple_ok, True)

    # THE CORE CROSS-RUN PROOF: planner state is byte-identical.
    check("hcs_cursor is byte-identical after the override (future runs unaffected)",
          _snapshot(conn, "SELECT pillar_code, last_hcs_id, cycle_no FROM hcs_cursor ORDER BY pillar_code"),
          cursor_before)
    check("lens_history is byte-identical after the override (no walk emission was recorded)",
          _snapshot(conn, "SELECT hcs_id, cycle_no, lens FROM lens_history ORDER BY hcs_id, cycle_no"),
          lens_before)
    check("cycle_no is unchanged (it is the RUN's walk position)", row13["cycle_no"], cycle_before)

    # atomic mapping generation + regenerated display code, canonical identity stable
    m13 = engine.schedule_mapping(conn, RID13)
    check("the accepted override minted exactly ONE new generation", m13["schedule_token"], tok13 + 1)
    check("the token the caller gets back is that generation", res13["schedule_token"], tok13 + 1)
    check("the display code was regenerated for the revised slot",
          [p["display_code"] for p in m13["positions"]] != before_codes, True)
    check("canonical slot_id never changed", sorted(p["slot_id"] for p in m13["positions"]),
          sorted(_slot_ids(conn, RID13)))
    # The revision audits entity='slot' (entity_id = the slot), not the round — _audits() is
    # round-scoped, so it correctly reports 0 here. Count the slot's own append-only trail.
    check("the override is audited append-only against the SLOT",
          _slot_audits(conn, target13, "schedule_revised") >= 1, True)

    # REUSABLE LINEAGE (Codex correction): two slots may share the same pinned Pillar/HCS. There is
    # deliberately no duplicate rejection — Pillar/HCS is classification lineage, not content
    # identity, and meaning-based Topic dedup is Stage 2.
    _, tok13b = _order13(conn, RID13)
    second13 = [x for x in _slot_ids(conn, RID13) if x != target13][0]
    engine.revise_schedule_slot(conn, second13, {"pillar_code": alt["pillar_code"],
                                                 "hcs_id": alt["hcs_id"]},
                                actor=actor, cfg=cfg, expected_token=tok13b)
    check("a SECOND slot may share the same pinned Pillar/HCS (reusable lineage, not identity)",
          _slot_row(conn, second13)["hcs_id"], alt["hcs_id"])

    # #306 P1.1 — a LEGACY run (no pinned methodology generation) FAILS CLOSED on a taxonomy write,
    # and the refusal touches nothing: slot, token, generation count and audit are all unchanged.
    # The fixture seed() round has no round_policy_snapshot, so it is exactly the legacy case.
    teardown(conn); seed(conn)   # legacy: seeded slots, NO snapshot, token 0
    leg_slot = SLOTS[0][0]
    leg_hcs_before   = _slot_row(conn, leg_slot)["hcs_id"]
    leg_token_before = _order(conn)[1]
    leg_gens_before  = _gen_count(conn)
    leg_audit_before = _slot_audits(conn, leg_slot, "schedule_revised")
    legacy = _expect_error(lambda: engine.revise_schedule_slot(
        conn, leg_slot, {"pillar_code": alt["pillar_code"], "hcs_id": alt["hcs_id"]},
        actor=actor, cfg=cfg, expected_token=leg_token_before))
    check("a legacy (no-snapshot) taxonomy write FAILS CLOSED", isinstance(legacy, engine.GateError), True)
    check("legacy refusal left the slot hcs unchanged", _slot_row(conn, leg_slot)["hcs_id"], leg_hcs_before)
    check("legacy refusal left the token unchanged", _order(conn)[1], leg_token_before)
    check("legacy refusal minted no generation", _gen_count(conn), leg_gens_before)
    check("legacy refusal wrote no acceptance audit", _slot_audits(conn, leg_slot, "schedule_revised"), leg_audit_before)

    teardown(conn)

    teardown(conn)
    conn.close()
    print(f"\n{'='*60}\n{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}\n{'='*60}")
    sys.exit(1 if FAILS else 0)


def _order13(conn, round_id):
    m = engine.schedule_mapping(conn, round_id)
    return [p["slot_id"] for p in m["positions"]], m["schedule_token"]


def _slot_ids(conn, round_id):
    cur = conn.cursor()
    cur.execute("SELECT slot_id FROM slot WHERE round_id=%s ORDER BY day, time_uae, slot_id", (round_id,))
    ids = [r[0] for r in cur.fetchall()]; cur.close()
    return ids


def _first_slot(conn, round_id):
    return _slot_ids(conn, round_id)[0]


def _tuple_coherent(conn, round_id, hcs_id, lens, hook_type):
    """True iff (hcs -> recommends lens) AND (lens -> default_hook_type == hook_type) both hold in
    the run's ONE pinned methodology version. Proves the dependent tuple is not mixed lineage."""
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    cur.execute("SELECT methodology_version FROM round_policy_snapshot WHERE round_id=%s", (round_id,))
    r = cur.fetchone()
    ver = (r or {}).get("methodology_version")
    if not ver:
        cur.close(); return False
    cur.execute("SELECT recommended_lenses FROM methodology_hcs WHERE version_id=%s AND hcs_id=%s", (ver, hcs_id))
    rec = (cur.fetchone() or {}).get("recommended_lenses") or []
    if isinstance(rec, str):
        rec = [x.strip() for x in rec.split(",") if x.strip()]
    cur.execute("SELECT default_hook_type FROM methodology_lens WHERE version_id=%s AND lens_id=%s", (ver, lens))
    dh = (cur.fetchone() or {}).get("default_hook_type")
    cur.close()
    return (lens in rec) and (dh == hook_type)


def _slot_audits(conn, slot_id, action):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM audit_log WHERE entity='slot' AND entity_id=%s AND action=%s",
                (slot_id, action))
    n = cur.fetchone()[0]; cur.close()
    return n


def _snapshot(conn, sql):
    """Byte-comparable snapshot of a table's governed state — used to prove NON-mutation."""
    cur = conn.cursor()
    cur.execute(sql)
    rows = json.dumps(cur.fetchall(), sort_keys=True, default=str)
    cur.close()
    return rows


def _round_id_by_label(conn, label):
    cur = conn.cursor()
    cur.execute("SELECT round_id FROM round WHERE label=%s ORDER BY round_id DESC LIMIT 1", (label,))
    r = cur.fetchone(); cur.close()
    return r[0] if r else None


def _round_count_by_label(conn, label):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM round WHERE label=%s", (label,))
    n = cur.fetchone()[0]; cur.close()
    return n


def _gen_count_for(conn, round_id):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM schedule_display_generation WHERE round_id=%s", (round_id,))
    n = cur.fetchone()[0]; cur.close()
    return n


def _drop_round(conn, round_id):
    """Remove ONLY the synthetic probe round this module created."""
    cur = conn.cursor()
    cur.execute("DELETE FROM schedule_display_position WHERE generation_id IN "
                "(SELECT generation_id FROM schedule_display_generation WHERE round_id=%s)", (round_id,))
    cur.execute("DELETE FROM schedule_display_generation WHERE round_id=%s", (round_id,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE %s", (round_id + "%",))
    cur.execute("DELETE FROM slot  WHERE round_id=%s", (round_id,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (round_id,))
    conn.commit(); cur.close()


def _round_starts_on(conn, round_id):
    cur = conn.cursor()
    cur.execute("SELECT starts_on FROM round WHERE round_id=%s", (round_id,))
    v = cur.fetchone()[0]; cur.close()
    return v


def _slot_row(conn, slot_id):
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM slot WHERE slot_id=%s", (slot_id,))
    row = cur.fetchone(); cur.close()
    return row


def _wait_until_blocked_on(tries=20000):
    """Return True once some backend in THIS database is genuinely WAITING on a row lock.

    Same discipline as the rest of the module — the DB is the barrier — applied to an interleaving
    the lock alone cannot express: we must know the reviser has reached the lock and parked there
    BEFORE the writer commits. pg_blocking_pids() reports postgres's own wait graph, so this observes
    a real database state rather than elapsed time; nothing here sleeps or assumes who got there
    first. Without it the test would only *probably* be in the window, and a probabilistic proof of a
    race is no proof.
    Two properties this must have, both learned the hard way:
      - it probes on its OWN autocommit connection. Probing from the caller's open transaction is
        what made an earlier version spin forever;
      - it is BOUNDED and returns False rather than looping. A detector that can hang turns a failed
        proof into a hung suite, and the caller must stay free to release the writer either way.
    """
    c = engine.db_connect()
    c.autocommit = True
    cur = c.cursor()
    try:
        for _ in range(tries):
            cur.execute("""SELECT count(*) FROM pg_stat_activity
                           WHERE datname = current_database()
                             AND pid <> pg_backend_pid()
                             AND cardinality(pg_blocking_pids(pid)) > 0""")
            if cur.fetchone()[0] > 0:
                return True
        return False
    finally:
        cur.close(); c.close()


def _expect_error(fn):
    try:
        fn()
        return None
    except Exception as e:                        # noqa: BLE001
        return e


if __name__ == "__main__":
    main()
