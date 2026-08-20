"""#310 CP18 — manual trigger routes into the SAME canonical Stage 2A runner (only timing differs).

Proves the two CP17-BLOCK P1 corrections:
  1. MANUAL trigger: the authorized Generate action ACTIVATES the awaiting_trigger job into the SAME
     run_stage2a_topic_job path — pinned policy, proactive novelty, provenance, entry_mode — identical
     to automatic except WHEN it fires. Double-click / replay is idempotent (one job, one run).
  2. HISTORY: read-model entry_mode comes from the IMMUTABLE job snapshot; a later policy-generation
     change never reinterprets an existing automatic or manual run.
Plus automatic/manual PARITY (identical pins/provenance shape) and HTTP double-click idempotency.

Stub-only; no model/provider call. Isolated :8014 / tanaghom_pr310.
"""
import os, sys, time, json, urllib.request
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

def teardown(conn, rid):
    cur = conn.cursor()
    cur.execute("DELETE FROM topic_provenance WHERE topic_id IN (SELECT topic_id FROM topic WHERE round_id=%s)", (rid,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (rid,))
    cur.execute("""SELECT DISTINCT gate_id FROM gate_target WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)
                   UNION SELECT DISTINCT gate_id FROM gate_decision WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)""", (rid, rid))
    gids = [r[0] for r in cur.fetchall()]
    for tbl in ("directive", "topic", "gate_decision", "gate_target"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
    for gid in gids:
        cur.execute("DELETE FROM gate WHERE gate_id=%s", (gid,))
    cur.execute("DELETE FROM schedule_display_generation WHERE round_id=%s", (rid,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE %s", (rid + "%",))
    cur.execute("DELETE FROM slot WHERE round_id=%s", (rid,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (rid,))
    conn.commit(); cur.close()

def cleanup_scope(conn, tenant):
    cur = conn.cursor(); cur.execute("DELETE FROM topic_generation_policy WHERE tenant_id=%s", (tenant,)); conn.commit(); cur.close()

def set_mode(conn, tenant, mode):
    cur = conn.cursor()
    cur.execute("DELETE FROM topic_generation_policy WHERE tenant_id=%s", (tenant,))
    cur.execute("""INSERT INTO topic_generation_policy (generation_no,status,actor,reason,tenant_id,module,entry_mode)
                   VALUES (1,'active','operator','test',%s,'content',%s)""", (tenant, mode))
    conn.commit(); cur.close()

def seed_accept(conn, rid, tenant):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id,module)
                   VALUES (%s,'mt',1,3,'["09:00"]','{}','{}','planning',%s,'content')""", (rid, tenant))
    cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,
                   status,cycle_no,topic_angle,hook_text,format,tenant_id)
                   VALUES (%s,%s,1,'09:00','P1_SELF','1.1','L1','Painful Truth','RESERVED',1,'ز','خ','Hero Reel',%s)""",
                (rid + "-A", rid, tenant))
    conn.commit(); cur.close()
    eng.initialize_schedule_mapping(conn, rid, actor="system", cfg=CFG)
    gid = eng.open_gate(conn, "schedule_review", round_id=rid, actor="khal", cfg=CFG)
    eng.decide(conn, gid, "khal", "approve", cfg=CFG)
    return eng.resolve(conn, gid, actor="khal", cfg=CFG)

def rc(conn, sql, args=()):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor); cur.execute(sql, args); r = cur.fetchone(); cur.close(); return r
def prov(conn, rid):
    return rc(conn, """SELECT tp.* FROM topic_provenance tp JOIN topic t ON t.topic_id=tp.topic_id WHERE t.round_id=%s LIMIT 1""", (rid,))
def http_generate(rid):
    req = urllib.request.Request(f"http://localhost:8000/rounds/{rid}/stages/topic_review/generate", method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

conn = db()

print("1) MANUAL TRIGGER via the authorized Generate action -> SAME canonical runner + provenance")
T, RID = "mtman", "R-MTMAN"; cleanup_scope(conn, T); teardown(conn, RID)
set_mode(conn, T, "manual"); seed_accept(conn, RID, T)
job = rc(conn, "SELECT job_id, status, entry_mode FROM generation_job WHERE round_id=%s", (RID,))
check("acceptance persisted an awaiting_trigger manual job", (job["status"], job["entry_mode"]), ("awaiting_trigger", "manual"))
# activate (what the Generate endpoint does) + run the SAME canonical runner
activated = eng.activate_awaiting_topic_generation(conn, RID)
check("activation returns the SAME job (awaiting_trigger -> queued)", activated, str(job["job_id"]))
run_writers.run_stage2a_topic_job(CFG, activated)
p = prov(conn, RID)
check("manual trigger generated via the canonical path (topics + provenance)",
      (rc(conn, "SELECT count(*) n FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED'", (RID,))["n"], p is not None), (1, True))
check("provenance carries the SAME pins as automatic (policy, writer, novelty) + entry_mode=manual",
      (p["topic_generation_policy_id"] is not None, p["writer_agent"], p["novelty_brief_version"] is not None, p["entry_mode"]),
      (True, "writers", True, "manual"))
teardown(conn, RID); cleanup_scope(conn, T)

print("2) DOUBLE-CLICK / replay idempotency — one job, one run (engine + HTTP)")
T, RID = "mtidem", "R-MTIDEM"; cleanup_scope(conn, T); teardown(conn, RID)
set_mode(conn, T, "manual"); seed_accept(conn, RID, T)
a1 = eng.activate_awaiting_topic_generation(conn, RID)
a2 = eng.activate_awaiting_topic_generation(conn, RID)
check("engine: first activate wins, second is a no-op (no double activation)", (a1 is not None, a2), (True, None))
teardown(conn, RID); cleanup_scope(conn, T)
# HTTP double-POST against the live API
set_mode(conn, T, "manual"); seed_accept(conn, RID, T)
r1 = http_generate(RID); r2 = http_generate(RID)
check("HTTP: first Generate ACTIVATES the Stage 2A job", (r1.get("stage2a"), r1.get("activated")), (True, True))
check("HTTP: second Generate is idempotent (already), not a second job/run",
      (r2.get("stage2a"), r2.get("activated"), r2.get("already")), (True, None, True))
for _ in range(20):
    if rc(conn, "SELECT status FROM generation_job WHERE round_id=%s", (RID,))["status"] == "completed": break
    time.sleep(0.5)
check("exactly ONE job for the round (no duplicate from double-click)",
      rc(conn, "SELECT count(*) n FROM generation_job WHERE round_id=%s", (RID,))["n"], 1)
check("exactly ONE topic per slot (no double generation)",
      rc(conn, "SELECT count(*) n FROM topic WHERE round_id=%s", (RID,))["n"], 1)
teardown(conn, RID); cleanup_scope(conn, T)

print("3) AUTOMATIC / MANUAL PARITY — identical pinned snapshot shape; differ only in mode + timing")
TA, RA = "mtpauto", "R-MTPA"; TM, RM = "mtpman", "R-MTPM"
for t, r in ((TA, RA), (TM, RM)): cleanup_scope(conn, t); teardown(conn, r)
set_mode(conn, TA, "automatic"); seed_accept(conn, RA, TA)            # automatic
run_writers.dispatch_pending_topic_generation(CFG, round_id=RA)
set_mode(conn, TM, "manual"); seed_accept(conn, RM, TM)              # manual
run_writers.run_stage2a_topic_job(CFG, eng.activate_awaiting_topic_generation(conn, RM))
pa, pm = prov(conn, RA), prov(conn, RM)
def shape(p): return (p["topic_generation_policy_id"] is not None, p["repetition_policy_snapshot"] is not None,
                      p["writer_agent"], p["writer_contract_version"], p["novelty_brief_version"] is not None,
                      p["authority_snapshot"] is not None)
check("automatic & manual pin the IDENTICAL provenance snapshot shape", shape(pa) == shape(pm), True)
check("they differ ONLY in the recorded entry_mode", (pa["entry_mode"], pm["entry_mode"]), ("automatic", "manual"))
for t, r in ((TA, RA), (TM, RM)): teardown(conn, r); cleanup_scope(conn, t)

print("4) HISTORY STABILITY — a later policy-generation change never reinterprets an existing run")
# automatic run, then flip the scope's policy to manual -> the completed run stays 'automatic'.
T, RID = "mthist", "R-MTHIST"; cleanup_scope(conn, T); teardown(conn, RID)
set_mode(conn, T, "automatic"); seed_accept(conn, RID, T)
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
check("run recorded under automatic", eng.topic_generation_read_model(conn, RID)["entry_mode"], "automatic")
# supersede: the scope's active policy becomes MANUAL (a new governed generation)
cur = conn.cursor()
cur.execute("UPDATE topic_generation_policy SET status='superseded' WHERE tenant_id=%s AND status='active'", (T,))
cur.execute("""INSERT INTO topic_generation_policy (generation_no,supersedes,status,actor,reason,tenant_id,module,entry_mode)
               VALUES (2,(SELECT policy_id FROM topic_generation_policy WHERE tenant_id=%s AND status='superseded' LIMIT 1),
                       'active','operator','changed to manual',%s,'content','manual')""", (T, T))
conn.commit(); cur.close()
check("read-model STILL reports the run as automatic (from the job snapshot, not live policy)",
      eng.topic_generation_read_model(conn, RID)["entry_mode"], "automatic")
check("provenance mode is likewise frozen automatic", prov(conn, RID)["entry_mode"], "automatic")
teardown(conn, RID); cleanup_scope(conn, T)

conn.close()
print("\n" + "="*62)
print("ALL MANUAL-TRIGGER / IDEMPOTENCY / PARITY / HISTORY CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*62)
sys.exit(0 if PASS else 1)
