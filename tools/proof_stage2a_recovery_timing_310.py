"""#310 recovery — TIMING-CONTROLLED tests (real short lease via env).

Run with: TANAGHOM_TOPICGEN_LEASE_SECONDS=2 TANAGHOM_TOPICGEN_HEARTBEAT_SECONDS=0.4

Proves (non-skipping, real timing):
  1. immediate restart while the abandoned lease is STILL FRESH -> the periodic drainer's pass does
     NOT reclaim it -> after the lease actually expires, the next pass reclaims and completes it, with
     no gate action.
  2. a real long-running attempt beyond one lease interval, with the independent heartbeat keeper
     active, is NEVER drainable/stolen.
  3. heartbeat stops on completion and the terminal lease is cleared (lease_expires_at IS NULL, stays).

Stub-only; no model/provider call. Isolated :8014 / tanaghom_pr310.
"""
import os, sys, time, threading
sys.path.insert(0, "/work"); sys.path.insert(0, "/work/gates"); sys.path.insert(0, "/work/agents")
import psycopg2, psycopg2.extras
import engine as eng
import run_writers

PASS = True
def check(label, got, want):
    global PASS; ok = got == want; PASS = PASS and ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")

CFG = eng.load_config()
LEASE = eng.TOPIC_GENERATION_LEASE_SECONDS
print(f"lease={LEASE}s heartbeat_env={os.environ.get('TANAGHOM_TOPICGEN_HEARTBEAT_SECONDS')}")

def db():
    return psycopg2.connect(host=os.environ["DB_HOST"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                            port=os.environ.get("DB_PORT", "5432"))

RID = "R-STG2ARC310"
SLOTS = [("R-STG2ARC310-A", "P1_SELF", "1.1"), ("R-STG2ARC310-B", "P2_RELATIONSHIPS", "2.1")]

def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM topic_provenance WHERE topic_id IN (SELECT topic_id FROM topic WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
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
    cur.execute("DELETE FROM slot WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit(); cur.close()

def seed_accept(conn):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id)
                   VALUES (%s,'rc',1,3,'["09:00"]','{}','{}','planning','default')""", (RID,))
    for sid, pillar, hcs in SLOTS:
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,topic_angle,hook_text,format,tenant_id)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','RESERVED',1,
                               'زاوية','خليك أقوى','Hero Reel','default')""", (sid, RID, pillar, hcs))
    conn.commit(); cur.close()
    eng.initialize_schedule_mapping(conn, RID, actor="system", cfg=CFG)
    gid = eng.open_gate(conn, "schedule_review", round_id=RID, actor="khal", cfg=CFG)
    eng.decide(conn, gid, "khal", "approve", cfg=CFG)
    eng.resolve(conn, gid, actor="khal", cfg=CFG)

conn = db()

print("1) immediate restart, lease STILL FRESH -> not reclaimed until real expiry, then completes")
teardown(conn); seed_accept(conn)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT job_id FROM generation_job WHERE round_id=%s", (RID,))
jid = str(cur.fetchone()["job_id"])
# Simulate a worker that CLAIMED (queued->running) then died with the lease still valid.
cur.execute("""UPDATE generation_job SET status='running', claimed_by='dead',
               lease_expires_at=now() + (%s || ' seconds')::interval, heartbeat_at=now()
               WHERE job_id=%s""", (str(LEASE), jid)); conn.commit()
run_writers.dispatch_pending_topic_generation(CFG)         # a recovery pass NOW (lease fresh)
cur.execute("SELECT status, slots_done FROM generation_job WHERE job_id=%s", (jid,))
r = cur.fetchone()
check("fresh-lease running job is NOT reclaimed by an early pass", (r["status"], r["slots_done"]), ("running", 0))
time.sleep(LEASE + 0.8)                                     # let the lease actually EXPIRE (real)
run_writers.dispatch_pending_topic_generation(CFG)         # the next recovery pass — no gate action
cur.execute("SELECT status, slots_done FROM generation_job WHERE job_id=%s", (jid,))
r = cur.fetchone()
check("after real expiry, the recovery pass reclaims + completes it", (r["status"], r["slots_done"]),
      ("completed", len(SLOTS)))
cur.execute("SELECT lease_expires_at FROM generation_job WHERE job_id=%s", (jid,))
check("terminal lease cleared (lease_expires_at IS NULL)", cur.fetchone()["lease_expires_at"], None)

print("2) long attempt beyond one lease interval, keeper active -> never drainable/stolen")
teardown(conn); seed_accept(conn)
cur.execute("SELECT job_id FROM generation_job WHERE round_id=%s", (RID,))
jid2 = str(cur.fetchone()["job_id"])
_real_pt = run_writers.process_topic
def _slow_pt(*a, **k):
    time.sleep(LEASE * 1.6)          # ONE attempt longer than a full lease interval
    return _real_pt(*a, **k)
run_writers.process_topic = _slow_pt
done_flag = {"v": None}
def _run():
    done_flag["v"] = run_writers.run_stage2a_topic_job(CFG, jid2)
th = threading.Thread(target=_run, daemon=True); th.start()
time.sleep(LEASE + 0.6)              # we are now PAST one lease interval, mid-attempt; keeper must hold
probe = db()
try:
    drainable = any(j["job_id"] == jid2 for j in eng.pending_topic_generation_jobs(probe, round_id=RID))
    stolen = eng.claim_topic_generation_job(probe, jid2)   # a rival recovery pass tries to steal
finally:
    probe.close()
check("mid long attempt: NOT drainable (keeper holds the lease)", drainable, False)
check("mid long attempt: a rival claim CANNOT steal it", stolen, False)
run_writers.process_topic = _real_pt
th.join(timeout=LEASE * 3)
check("the long attempt completed normally", (done_flag["v"] or {}).get("status"), "completed")

print("3) heartbeat stops on completion; terminal lease stays cleared")
cur.execute("SELECT lease_expires_at FROM generation_job WHERE job_id=%s", (jid2,))
check("completed => lease cleared", cur.fetchone()["lease_expires_at"], None)
time.sleep(1.0)                      # > heartbeat interval: a still-running keeper would re-set a lease
cur.execute("SELECT lease_expires_at, status FROM generation_job WHERE job_id=%s", (jid2,))
r = cur.fetchone()
check("keeper stopped: lease stays NULL after completion", (r["lease_expires_at"], r["status"]), (None, "completed"))

print("4) transient heartbeat DB failure mid-attempt -> heartbeats RESUME, live lease not reclaimable")
teardown(conn); seed_accept(conn)
cur.execute("SELECT job_id FROM generation_job WHERE round_id=%s", (RID,))
jid4 = str(cur.fetchone()["job_id"])
# Inject the REAL hazard: the FIRST heartbeat aborts its connection's transaction (a bad statement)
# then raises; every LATER beat delegates to the real heartbeat and must succeed on the recovered/
# replaced connection. If the keeper did not recover the connection, all later beats would fail and
# the lease would expire -> the job would become drainable/reclaimable mid-run.
_real_hb = eng.heartbeat_topic_generation_job
hb_state = {"failed": 0}
def _flaky_hb(conn_, job_id_):
    if hb_state["failed"] == 0:
        hb_state["failed"] = 1
        c = conn_.cursor()
        try:
            c.execute("SELECT nonexistent_col_zzz")   # aborts conn_'s transaction, like a real DB error
        finally:
            c.close()
        return
    return _real_hb(conn_, job_id_)
eng.heartbeat_topic_generation_job = _flaky_hb
_real_pt4 = run_writers.process_topic
def _slow_pt4(*a, **k):
    time.sleep(LEASE * 1.8)                            # one attempt spanning MANY heartbeat intervals
    return _real_pt4(*a, **k)
run_writers.process_topic = _slow_pt4
done4 = {"v": None}
th4 = threading.Thread(target=lambda: done4.__setitem__("v", run_writers.run_stage2a_topic_job(CFG, jid4)), daemon=True)
th4.start()
time.sleep(LEASE + 0.8)                                # past one lease interval; later beats must have resumed
probe = db()
try:
    drainable4 = any(j["job_id"] == jid4 for j in eng.pending_topic_generation_jobs(probe, round_id=RID))
    stolen4 = eng.claim_topic_generation_job(probe, jid4)
finally:
    probe.close()
eng.heartbeat_topic_generation_job = _real_hb
run_writers.process_topic = _real_pt4
check("the transient heartbeat failure was actually injected", hb_state["failed"], 1)
check("after a transient DB failure, heartbeats RESUME -> job NOT drainable", drainable4, False)
check("after a transient DB failure, a rival claim CANNOT steal the live job", stolen4, False)
th4.join(timeout=LEASE * 3)
check("the attempt completed despite the transient heartbeat failure", (done4["v"] or {}).get("status"), "completed")

teardown(conn); cur.close(); conn.close()
print("\n" + "="*60)
print("ALL RECOVERY-TIMING CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*60)
sys.exit(0 if PASS else 1)
