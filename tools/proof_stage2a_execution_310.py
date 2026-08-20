"""#310 review-patch regressions — the automatic acceptance->execution path + correctness fixes.

Proves the five Codex BLOCK findings are closed, with NON-happy-path coverage:
  P0-1  Schedule acceptance -> one job -> writer EXECUTION -> populated Topics/provenance in V2;
        replay -> no duplicate job and no second writer launch (atomic claim).
  P0-2  fresh init -> exactly one active baseline; idempotent; explicit disable respected (fallback).
  P1-3  provenance-write failure -> atomic rollback (no TOPIC_PROPOSED slot without exact provenance).
  P1-4  partial + retry -> CUMULATIVE counts (N+M), recomputed from canonical truth.
  P1-5  one provenance row per (topic_id, revision) — idempotent recovery.

Stub-only; no model/provider call. Isolated :8014 / tanaghom_pr310.
"""
import os, sys
sys.path.insert(0, "/work"); sys.path.insert(0, "/work/gates"); sys.path.insert(0, "/work/agents")
import psycopg2, psycopg2.extras
import engine as eng
import run_writers

PASS = True
def check(label, got, want):
    global PASS; ok = got == want; PASS = PASS and ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")

CFG = eng.load_config()
def db():
    return psycopg2.connect(host=os.environ["DB_HOST"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                            port=os.environ.get("DB_PORT", "5432"))

RID = "R-STG2A310"
SLOTS = [("R-STG2A310-A", "P1_SELF", "1.1"), ("R-STG2A310-B", "P1_SELF", "1.1"),
         ("R-STG2A310-C", "P2_RELATIONSHIPS", "2.1")]

def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM topic_provenance WHERE topic_id IN (SELECT topic_id FROM topic WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
    # gate has no round_id — reach it through the round's slots via gate_target/gate_decision.
    cur.execute("""SELECT DISTINCT gate_id FROM gate_target WHERE slot_id IN
                     (SELECT slot_id FROM slot WHERE round_id=%s)
                   UNION SELECT DISTINCT gate_id FROM gate_decision WHERE slot_id IN
                     (SELECT slot_id FROM slot WHERE round_id=%s)""", (RID, RID))
    gate_ids = [r[0] for r in cur.fetchall()]
    for tbl in ("directive", "topic", "gate_decision", "gate_target"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    for gid in gate_ids:
        cur.execute("DELETE FROM gate WHERE gate_id=%s", (gid,))
    cur.execute("DELETE FROM schedule_display_generation WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE %s", (RID + "%",))
    cur.execute("DELETE FROM slot  WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit(); cur.close()

def seed_reserved(conn):
    """A round whose slots are at RESERVED — pre-acceptance, so resolve() drives the real trigger."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id)
                   VALUES (%s,'stage2a-exec',1,3,'["09:00"]','{}','{}','planning','default')""", (RID,))
    for sid, pillar, hcs in SLOTS:
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,topic_angle,hook_text,format,tenant_id)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','RESERVED',1,
                               'زاوية','خليك أقوى','Hero Reel','default')""", (sid, RID, pillar, hcs))
    conn.commit(); cur.close()

def accept_schedule(conn):
    """Drive the REAL acceptance through the governed API: open the schedule_review gate over the
    round's RESERVED slots, record khal's approval, and resolve() — the exact production trigger."""
    eng.initialize_schedule_mapping(conn, RID, actor="system", cfg=CFG)
    gid = eng.open_gate(conn, "schedule_review", round_id=RID, actor="khal", cfg=CFG)
    eng.decide(conn, gid, "khal", "approve", cfg=CFG)
    return eng.resolve(conn, gid, actor="khal", cfg=CFG)

# ----------------------------------------------------------------------------------------------
conn = db()
teardown(conn); seed_reserved(conn)

print("P0-1) Schedule acceptance -> exactly one queued job (the real resolve() trigger)")
outcomes = accept_schedule(conn)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT status FROM slot WHERE round_id=%s ORDER BY slot_id", (RID,))
check("all slots advanced to SCHEDULE_APPROVED", [r["status"] for r in cur.fetchall()],
      ["SCHEDULE_APPROVED"] * len(SLOTS))
cur.execute("SELECT job_id, status, slots_total FROM generation_job WHERE round_id=%s", (RID,))
jobs_rows = cur.fetchall()
check("acceptance enqueued exactly ONE job", len(jobs_rows), 1)
check("job is queued, total = accepted population", (jobs_rows[0]["status"], jobs_rows[0]["slots_total"]),
      ("queued", len(SLOTS)))

print("P0-1) DISPATCH -> writer execution -> populated canonical Topics + provenance in V2")
res = run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
check("dispatch ran exactly one job to completion", [(r["status"], r["done"], r["failed"]) for r in res],
      [("completed", len(SLOTS), 0)])
cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED'", (RID,))
check("every accepted slot is now a generated Topic", cur.fetchone()["n"], len(SLOTS))
cur.execute("""SELECT count(*) AS n FROM topic_provenance tp
                 JOIN topic t ON t.topic_id=tp.topic_id WHERE t.round_id=%s""", (RID,))
check("each generated Topic has exact provenance", cur.fetchone()["n"], len(SLOTS))
rm = eng.topic_generation_read_model(conn, RID)
check("V2 read model: phase completed, generated == accepted",
      (rm["phase"], rm["counts"]["generated"], rm["counts"]["accepted"]),
      ("completed", len(SLOTS), len(SLOTS)))

print("P0-1) REPLAY -> no duplicate job, no second writer launch")
cur.execute("SELECT accepted_schedule_token FROM generation_job WHERE round_id=%s", (RID,))
_tok = cur.fetchone()["accepted_schedule_token"]
eng.enqueue_topic_generation(conn, RID, _tok, actor="khal")     # replayed acceptance trigger
cur.execute("SELECT count(*) AS n FROM generation_job WHERE round_id=%s", (RID,))
check("replayed enqueue minted NO second job", cur.fetchone()["n"], 1)
res2 = run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
check("re-dispatch launched nothing (no queued job; completed is not re-run)", res2, [])
cur.execute("""SELECT count(*) AS n FROM topic_provenance tp
                 JOIN topic t ON t.topic_id=tp.topic_id WHERE t.round_id=%s""", (RID,))
check("re-dispatch produced no extra Topics/provenance", cur.fetchone()["n"], len(SLOTS))

# ----------------------------------------------------------------------------------------------
print("P1-3 + P1-4) provenance failure -> ATOMIC rollback; retry -> CUMULATIVE counts")
teardown(conn); seed_reserved(conn)
accept_schedule(conn)
cur.execute("SELECT job_id FROM generation_job WHERE round_id=%s", (RID,))
job_id = str(cur.fetchone()["job_id"])
cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status='SCHEDULE_APPROVED' ORDER BY day,time_uae,slot_id", (RID,))
first_slot = cur.fetchone()["slot_id"]     # the slot processed first — we make ITS provenance fail

_real = eng.record_topic_provenance
_state = {"failed_once": False}
def _flaky(cur_, topic_id, revision, job_row, *a, **k):
    if not _state["failed_once"]:
        _state["failed_once"] = True
        raise RuntimeError("injected provenance write failure")
    return _real(cur_, topic_id, revision, job_row, *a, **k)
eng.record_topic_provenance = _flaky
try:
    run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
finally:
    eng.record_topic_provenance = _real

cur.execute("SELECT status FROM slot WHERE slot_id=%s", (first_slot,))
check("the failed slot rolled back to SCHEDULE_APPROVED (atomic)", cur.fetchone()["status"], "SCHEDULE_APPROVED")
cur.execute("SELECT count(*) AS n FROM topic WHERE slot_id=%s", (first_slot,))
check("the failed slot has NO Topic (atomic — no orphan)", cur.fetchone()["n"], 0)
cur.execute("SELECT slots_done, slots_failed, status FROM generation_job WHERE job_id=%s", (job_id,))
jr = cur.fetchone()
check("job is partial with N-1 done (canonical), 1 remaining",
      (jr["slots_done"], jr["slots_failed"], jr["status"]), (len(SLOTS) - 1, 1, "partial"))

# retry: reset failed/partial -> queued, then dispatch again -> the one remaining slot generates.
eng.retry_topic_generation(conn, RID, "khal")
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
cur.execute("SELECT slots_done, slots_failed, status FROM generation_job WHERE job_id=%s", (job_id,))
jr = cur.fetchone()
check("retry -> CUMULATIVE done = N (not just the 1 retried), completed",
      (jr["slots_done"], jr["slots_failed"], jr["status"]), (len(SLOTS), 0, "completed"))
cur.execute("SELECT status FROM slot WHERE slot_id=%s", (first_slot,))
check("the previously-failed slot is now generated", cur.fetchone()["status"], "TOPIC_PROPOSED")
# P1 — a completed job must NOT carry the stale partial error_detail.
cur.execute("SELECT error_detail FROM generation_job WHERE job_id=%s", (job_id,))
check("completed => error_detail IS NULL (stale partial error cleared)", cur.fetchone()["error_detail"], None)

print("P1-5) one provenance row per (topic_id, revision) — idempotent recovery")
cur.execute("SELECT topic_id, revision FROM topic WHERE slot_id=%s ORDER BY revision DESC LIMIT 1", (first_slot,))
t = cur.fetchone()
cur.execute("SELECT job_id FROM generation_job WHERE round_id=%s", (RID,))
jrow = {"job_id": cur.fetchone()["job_id"], "round_id": RID, "accepted_schedule_token": 1}
pcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
eng.record_topic_provenance(pcur, t["topic_id"], t["revision"], jrow, None, "stub", "stub:test", actor="khal")
conn.commit(); pcur.close()
cur.execute("SELECT count(*) AS n FROM topic_provenance WHERE topic_id=%s AND revision=%s", (t["topic_id"], t["revision"]))
check("re-recording the same attempt is a no-op (unique + ON CONFLICT)", cur.fetchone()["n"], 1)

teardown(conn)

# ----------------------------------------------------------------------------------------------
print("P0-DUR-a) a committed QUEUED job survives a simulated restart and is drained (no gate action)")
teardown(conn); seed_reserved(conn)
accept_schedule(conn)                                # commits an acceptance -> a QUEUED job
# SIMULATE RESTART: the process died after the acceptance commit but before the post-commit handoff
# started the thread. Nothing dispatched it. We do NOT touch any gate again — we only run the drain
# that startup performs.
cur.execute("SELECT job_id, status FROM generation_job WHERE round_id=%s", (RID,))
jr = cur.fetchone()
check("pre-drain: the job is stranded QUEUED (never started)", jr["status"], "queued")
run_writers.dispatch_pending_topic_generation(CFG)  # == the startup drain (all rounds), NO gate action
cur.execute("SELECT status, slots_done FROM generation_job WHERE job_id=%s", (jr["job_id"],))
d = cur.fetchone()
check("startup drain completed the orphaned queued job", (d["status"], d["slots_done"]),
      ("completed", len(SLOTS)))
cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED'", (RID,))
check("every accepted slot is populated after recovery", cur.fetchone()["n"], len(SLOTS))
teardown(conn)

print("P0-DUR-b) an ABANDONED running claim (expired lease) is safely reclaimed and completed")
teardown(conn); seed_reserved(conn)
accept_schedule(conn)
cur.execute("SELECT job_id FROM generation_job WHERE round_id=%s", (RID,))
jid = str(cur.fetchone()["job_id"])
# SIMULATE a worker that claimed (queued->running) then DIED before generating: force running with an
# already-EXPIRED lease. pending must treat it as drainable; a live-lease running job must not be.
cur.execute("""UPDATE generation_job SET status='running', lease_expires_at=now() - interval '1 hour',
               heartbeat_at=now() - interval '1 hour', claimed_by='dead-worker' WHERE job_id=%s""", (jid,))
conn.commit()
check("an expired-lease running job IS drainable",
      any(j["job_id"] == jid for j in eng.pending_topic_generation_jobs(conn, round_id=RID)), True)
# a FRESH-lease running job must NOT be reclaimable (never steal an active run)
cur.execute("UPDATE generation_job SET lease_expires_at=now() + interval '5 minutes' WHERE job_id=%s", (jid,))
conn.commit()
check("a live-lease running job is NOT drainable (not stolen)",
      any(j["job_id"] == jid for j in eng.pending_topic_generation_jobs(conn, round_id=RID)), False)
check("claim refuses a live-lease running job", eng.claim_topic_generation_job(conn, jid), False)
# back to abandoned -> the drain reclaims and completes it
cur.execute("UPDATE generation_job SET lease_expires_at=now() - interval '1 hour' WHERE job_id=%s", (jid,))
conn.commit()
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
cur.execute("SELECT status, slots_done FROM generation_job WHERE job_id=%s", (jid,))
d = cur.fetchone()
check("abandoned running job reclaimed and completed", (d["status"], d["slots_done"]),
      ("completed", len(SLOTS)))
teardown(conn)

# ----------------------------------------------------------------------------------------------
print("P0-2) fresh init -> exactly one active baseline; idempotent; explicit disable respected")
c2 = db(); c2.autocommit = False
x = c2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
# Work inside ONE transaction we ROLL BACK, so the real operator policy is never mutated.
x.execute("DELETE FROM topic_provenance")   # FK order: provenance -> job/policy
x.execute("DELETE FROM generation_job")
x.execute("DELETE FROM topic_generation_policy")
x.execute("SELECT count(*) AS n FROM topic_generation_policy WHERE status='active'")
check("clean slate: zero active baseline", x.fetchone()["n"], 0)
eng._bootstrap_topic_generation_policy_tx(x, actor="system")
x.execute("SELECT count(*) AS n FROM topic_generation_policy WHERE status='active'")
check("fresh init -> exactly one active baseline", x.fetchone()["n"], 1)
eng._bootstrap_topic_generation_policy_tx(x, actor="system")   # idempotent
x.execute("SELECT count(*) AS n FROM topic_generation_policy")
check("re-init is a create-only no-op (still exactly one generation)", x.fetchone()["n"], 1)
x.execute("UPDATE topic_generation_policy SET status='disabled'")   # operator's explicit disable
eng._bootstrap_topic_generation_policy_tx(x, actor="system")       # must NOT resurrect it
x.execute("SELECT count(*) AS n FROM topic_generation_policy WHERE status='active'")
check("explicit disable is respected (no active baseline -> Stage 1 fallback)", x.fetchone()["n"], 0)
c2.rollback(); x.close(); c2.close()      # restore the real operator policy untouched

conn.close()
print("\n" + "="*64)
print("ALL STAGE-2A EXECUTION/CORRECTNESS CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*64)
sys.exit(0 if PASS else 1)
