"""#310 entry_mode — governed Schedule-to-Topic entry as a versioned product-policy choice.

Proves (operator invariant): entry mode is on the topic_generation_policy generation (immutable,
versioned), NOT a surface branch or an overload of policy absence/active status.
  1. AUTOMATIC (baseline default): Schedule acceptance enqueues + dispatch generates topics; job +
     provenance pin entry_mode='automatic'; read-model reports it.
  2. MANUAL (authorized generation): a V2-governed authorized trigger-timing choice over the SAME
     durable job — Schedule acceptance enqueues that job in 'awaiting_trigger' (non-drainable), slots
     stay SCHEDULE_APPROVED until an authorized V2 Generate trigger activates it into the same canonical
     runner; the resolved mode is pinned in an append-only audit; read-model reports entry_mode='manual',
     stage2a_enabled=true.
  3. INIT create-only / non-destructive: baseline seeds 'automatic'; re-seed is a no-op; a pre-existing
     MANUAL generation is never overwritten back to automatic.
  4. NO silent fallback: absent active policy => Stage 2A NOT provisioned (no job AND no manual audit —
     an explicit third state); an unrecognized entry_mode fails closed (GateError), and the DB CHECK
     rejects invalid values.

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

def seed_accept(conn, rid, tenant):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id,module)
                   VALUES (%s,'em',1,3,'["09:00"]','{}','{}','planning',%s,'content')""", (rid, tenant))
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

conn = db()

print("1) AUTOMATIC (baseline default) — acceptance enqueues + dispatch generates; mode pinned")
T, RID = "emauto", "R-EMAUTO"; cleanup_scope(conn, T); teardown(conn, RID)
seed_accept(conn, RID, T)
job = rc(conn, "SELECT * FROM generation_job WHERE round_id=%s", (RID,))
check("baseline auto-provisioned entry_mode=automatic",
      rc(conn, "SELECT entry_mode FROM topic_generation_policy WHERE tenant_id=%s AND status='active'", (T,))["entry_mode"], "automatic")
check("acceptance enqueued a job with entry_mode pinned=automatic", (job is not None, job["entry_mode"]), (True, "automatic"))
rm = eng.topic_generation_read_model(conn, RID)
check("read-model reports entry_mode=automatic, stage2a_enabled", (rm["entry_mode"], rm["stage2a_enabled"]), ("automatic", True))
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
check("slots generated (TOPIC_PROPOSED)", rc(conn, "SELECT count(*) n FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED'", (RID,))["n"], 1)
check("provenance pins entry_mode=automatic",
      rc(conn, "SELECT tp.entry_mode FROM topic_provenance tp JOIN topic t ON t.topic_id=tp.topic_id WHERE t.round_id=%s", (RID,))["entry_mode"], "automatic")
teardown(conn, RID); cleanup_scope(conn, T)

print("2) MANUAL — durable non-drainable awaiting-trigger job (same snapshot); V2-governed trigger-timing")
T, RID = "emmanual", "R-EMMANUAL"; cleanup_scope(conn, T); teardown(conn, RID)
cur = conn.cursor()
cur.execute("""INSERT INTO topic_generation_policy (generation_no, status, actor, reason, tenant_id, module, entry_mode)
               VALUES (1,'active','operator','authorized manual generation',%s,'content','manual')""", (T,))
conn.commit(); cur.close()
seed_accept(conn, RID, T)
job = rc(conn, "SELECT * FROM generation_job WHERE round_id=%s", (RID,))
check("MANUAL: a durable AWAITING_TRIGGER job is persisted (not dispatched)",
      (job is not None, job["status"], job["entry_mode"]), (True, "awaiting_trigger", "manual"))
check("MANUAL: the SAME immutable snapshot is pinned (policy + writer + authority)",
      (job["topic_generation_policy_id"] is not None, job["writer_agent"], job["authority_snapshot"] is not None),
      (True, "writers", True))
check("MANUAL: slots stay SCHEDULE_APPROVED until the authorized V2 Generate trigger activates the job",
      rc(conn, "SELECT count(*) n FROM slot WHERE round_id=%s AND status='SCHEDULE_APPROVED'", (RID,))["n"], 1)
check("MANUAL: awaiting_trigger is NON-DRAINABLE (recovery drain / auto-dispatch ignore it)",
      run_writers.dispatch_pending_topic_generation(CFG, round_id=RID), [])
rm = eng.topic_generation_read_model(conn, RID)
check("read-model: entry_mode=manual (from job snapshot), stage2a_enabled, phase=awaiting_trigger",
      (rm["entry_mode"], rm["stage2a_enabled"], rm["phase"]), ("manual", True, "awaiting_trigger"))
teardown(conn, RID); cleanup_scope(conn, T)

print("3) INIT create-only / non-destructive")
T = "eminit"; cleanup_scope(conn, T)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
eng._bootstrap_topic_generation_policy_tx(cur, T, "content", "system"); conn.commit()
check("fresh init -> exactly one active, entry_mode=automatic",
      (rc(conn, "SELECT count(*) n FROM topic_generation_policy WHERE tenant_id=%s", (T,))["n"],
       rc(conn, "SELECT entry_mode FROM topic_generation_policy WHERE tenant_id=%s AND status='active'", (T,))["entry_mode"]),
      (1, "automatic"))
eng._bootstrap_topic_generation_policy_tx(cur, T, "content", "system"); conn.commit()
check("re-init is a create-only no-op (still one generation)", rc(conn, "SELECT count(*) n FROM topic_generation_policy WHERE tenant_id=%s", (T,))["n"], 1)
cur.close(); cleanup_scope(conn, T)
# a pre-existing MANUAL generation must NOT be overwritten back to automatic by init.
T2 = "eminitman"; cleanup_scope(conn, T2)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("""INSERT INTO topic_generation_policy (generation_no,status,actor,reason,tenant_id,module,entry_mode)
               VALUES (1,'active','operator','manual',%s,'content','manual')""", (T2,)); conn.commit()
eng._bootstrap_topic_generation_policy_tx(cur, T2, "content", "system"); conn.commit()
check("init NEVER overwrites a pre-existing manual generation",
      rc(conn, "SELECT entry_mode FROM topic_generation_policy WHERE tenant_id=%s AND status='active'", (T2,))["entry_mode"], "manual")
cur.close(); cleanup_scope(conn, T2)

print("4) NO silent fallback")
# (a) absent active policy => NOT provisioned; acceptance creates NO job and NO manual-deferral audit — an
#     explicit third state, never silently automatic OR manual. A DISABLED row keeps bootstrap a no-op
#     (create-only) so no active policy exists at the check.
T, RID = "emabsent", "R-EMABSENT"; cleanup_scope(conn, T); teardown(conn, RID)
cur = conn.cursor()
cur.execute("""INSERT INTO topic_generation_policy (generation_no,status,actor,reason,tenant_id,module,entry_mode)
               VALUES (1,'disabled','operator','rolled back to Stage 1',%s,'content','automatic')""", (T,))
conn.commit(); cur.close()
seed_accept(conn, RID, T)
check("absent active policy -> NO job (Stage 2A not provisioned, not silently automatic)",
      rc(conn, "SELECT count(*) n FROM generation_job WHERE round_id=%s", (RID,))["n"], 0)
check("absent active policy -> NO manual-deferral audit (not silently manual)",
      rc(conn, "SELECT count(*) n FROM audit_log WHERE entity_id=%s AND action='topic_generation_entry_deferred'", (RID,))["n"], 0)
_rm = eng.topic_generation_read_model(conn, RID)
check("read-model: stage2a_enabled=false, entry_mode=None (explicit third state)",
      (_rm["stage2a_enabled"], _rm["entry_mode"]), (False, None))
teardown(conn, RID); cleanup_scope(conn, T)

# (b) an unrecognized entry_mode fails closed at acceptance (defense-in-depth beyond the DB CHECK).
T, RID = "embad", "R-EMBAD"; cleanup_scope(conn, T); teardown(conn, RID)
cur = conn.cursor()
cur.execute("ALTER TABLE topic_generation_policy DROP CONSTRAINT IF EXISTS topic_generation_policy_entry_mode_chk")
cur.execute("""INSERT INTO topic_generation_policy (generation_no,status,actor,reason,tenant_id,module,entry_mode)
               VALUES (1,'active','x','bad',%s,'content','bogus_mode')""", (T,))
conn.commit(); cur.close()
raised = False
try:
    seed_accept(conn, RID, T)          # resolve() coupling reads the bogus mode -> GateError
except eng.GateError:
    raised = True; conn.rollback()
check("unrecognized entry_mode fails closed at acceptance (no silent fallback)", raised, True)
teardown(conn, RID)
cur = conn.cursor()
cur.execute("DELETE FROM topic_generation_policy WHERE tenant_id=%s", (T,))
cur.execute("""ALTER TABLE topic_generation_policy ADD CONSTRAINT topic_generation_policy_entry_mode_chk
               CHECK (entry_mode IN ('automatic','manual'))""")     # restore the DB guard
conn.commit(); cur.close()
# (c) with the CHECK restored, the DB itself rejects an invalid value.
db_rejects = False
try:
    cur = conn.cursor()
    cur.execute("""INSERT INTO topic_generation_policy (generation_no,status,actor,tenant_id,module,entry_mode)
                   VALUES (1,'active','x','emchk','content','nope')""")
    conn.commit(); cur.close()
except Exception:
    conn.rollback(); db_rejects = True
check("DB CHECK rejects an invalid entry_mode at the DB level", db_rejects, True)
cleanup_scope(conn, "emchk")

conn.close()
print("\n" + "="*62)
print("ALL ENTRY-MODE CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*62)
sys.exit(0 if PASS else 1)
