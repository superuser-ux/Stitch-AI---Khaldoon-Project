"""#310 lineage — repetition-policy VALUE snapshot + agent/writer provenance (round-5 BLOCK).

Non-skipping proof of:
  1. same-scope IN-PLACE repetition-policy update after enqueue -> execution + provenance retain the
     ENQUEUE-TIME values (immutable snapshot), keeping the source UUID as lineage.
  2. no managed repetition row -> the production-default snapshot is frozen + recorded truthfully.
  3. provenance identifies the ACTUAL writer/agent identity + contract version + effective actor.
  4. AgentRep stays observe/explain/recommend-only (no generation/retry/policy-mutation authority).

Stub-only; no model/provider call. Isolated :8014 / tanaghom_pr310.
"""
import os, sys
sys.path.insert(0, "/work"); sys.path.insert(0, "/work/gates"); sys.path.insert(0, "/work/agents")
import psycopg2, psycopg2.extras
import engine as eng
import run_writers
import agent as A

PASS = True
def check(label, got, want):
    global PASS; ok = got == want; PASS = PASS and ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")

CFG = eng.load_config()
def db():
    return psycopg2.connect(host=os.environ["DB_HOST"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                            port=os.environ.get("DB_PORT", "5432"))

def teardown_round(conn, rid):
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
    cur = conn.cursor()
    cur.execute("DELETE FROM topic_generation_policy WHERE tenant_id=%s", (tenant,))
    cur.execute("DELETE FROM repetition_policy WHERE tenant_id=%s", (tenant,))
    conn.commit(); cur.close()

def seed_accept(conn, rid, tenant, actor="khal"):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id,module)
                   VALUES (%s,'ln',1,3,'["09:00"]','{}','{}','planning',%s,'content')""", (rid, tenant))
    cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,
                   status,cycle_no,topic_angle,hook_text,format,tenant_id)
                   VALUES (%s,%s,1,'09:00','P1_SELF','1.1','L1','Painful Truth','RESERVED',1,'ز','خ','Hero Reel',%s)""",
                (rid + "-A", rid, tenant))
    conn.commit(); cur.close()
    eng.initialize_schedule_mapping(conn, rid, actor="system", cfg=CFG)
    gid = eng.open_gate(conn, "schedule_review", round_id=rid, actor=actor, cfg=CFG)
    eng.decide(conn, gid, actor, "approve", cfg=CFG)
    eng.resolve(conn, gid, actor=actor, cfg=CFG)

def job_of(conn, rid):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM generation_job WHERE round_id=%s", (rid,)); j = cur.fetchone(); cur.close()
    return j

def prov_of(conn, rid):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT tp.* FROM topic_provenance tp JOIN topic t ON t.topic_id=tp.topic_id
                    WHERE t.round_id=%s ORDER BY tp.created_at LIMIT 1""", (rid,))
    p = cur.fetchone(); cur.close()
    return p

conn = db()

print("1) same-scope IN-PLACE repetition update after enqueue -> snapshot values are immutable")
T = "lnrep"; RID = "R-LNREP"
cleanup_scope(conn, T); teardown_round(conn, RID)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("""INSERT INTO repetition_policy (policy_key, enabled, scope, similarity_threshold,
               max_regenerations, tenant_id, module, updated_at)
               VALUES ('topic_generation', true, 'all', 0.86, 3, %s, 'content', now()) RETURNING policy_id""", (T,))
rep_src = str(cur.fetchone()["policy_id"]); conn.commit()
seed_accept(conn, RID, T)
job = job_of(conn, RID)
snap = job["repetition_policy_snapshot"]
check("job froze the enqueue-time repetition VALUES", (snap["similarity_threshold"], snap["max_regenerations"]), (0.86, 3))
check("snapshot keeps source UUID lineage", snap["source_policy_id"], rep_src)
# IN-PLACE mutation of the SAME scoped row after enqueue.
cur.execute("""UPDATE repetition_policy SET similarity_threshold=0.5, max_regenerations=9, updated_at=now()
               WHERE policy_id=%s""", (rep_src,)); conn.commit()
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
p = prov_of(conn, RID)
check("provenance retains the ENQUEUE-TIME values, not the mutated ones",
      (p["repetition_policy_snapshot"]["similarity_threshold"], p["repetition_policy_snapshot"]["max_regenerations"]),
      (0.86, 3))
check("provenance keeps the source UUID lineage", str(p["repetition_policy_id"]), rep_src)
cur.execute("SELECT similarity_threshold, max_regenerations FROM repetition_policy WHERE policy_id=%s", (rep_src,))
liverow = cur.fetchone()
check("the live row DID change (proving the snapshot is what protected the run)",
      (float(liverow["similarity_threshold"]), liverow["max_regenerations"]), (0.5, 9))
cur.close(); teardown_round(conn, RID); cleanup_scope(conn, T)

print("2) no managed repetition row -> production-default snapshot frozen + recorded")
T = "lndef"; RID = "R-LNDEF"
cleanup_scope(conn, T); teardown_round(conn, RID)
seed_accept(conn, RID, T)                          # scope has NO managed repetition_policy row
job = job_of(conn, RID)
check("job snapshot is the production default", job["repetition_policy_snapshot"]["source"], "production_default")
check("no source UUID (production default)", job["repetition_policy_snapshot"]["source_policy_id"], None)
check("job repetition_policy_id is NULL (production default)", job["repetition_policy_id"], None)
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
p = prov_of(conn, RID)
check("provenance records the production-default snapshot", p["repetition_policy_snapshot"]["source"], "production_default")
check("provenance repetition_policy_id is NULL", p["repetition_policy_id"], None)
teardown_round(conn, RID); cleanup_scope(conn, T)

print("3) provenance identifies the ACTUAL writer/agent identity + contract + effective actor")
T = "lnwriter"; RID = "R-LNW"
cleanup_scope(conn, T); teardown_round(conn, RID)
seed_accept(conn, RID, T, actor="khal")
job = job_of(conn, RID)
check("job pins the governed writer identity + contract",
      (job["writer_agent"], job["writer_contract_version"]), ("writers", "topic-writer.v1"))
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
p = prov_of(conn, RID)
check("provenance records the actual writer agent + contract version",
      (p["writer_agent"], p["writer_contract_version"]), ("writers", "topic-writer.v1"))
check("provenance records the effective (authorizing) actor", p["effective_actor"], "khal")
check("provenance records the actual resolved provider/model/route",
      (p["resolved_provider"], p["resolved_model"], p["execution_route"]), ("stub", "stub:test", "in_process"))
teardown_round(conn, RID); cleanup_scope(conn, T)

print("4) AgentRep stays observe/explain/recommend-only (no generation/retry/policy authority)")
ctx = {"round_id": "R1", "artifact": "topic", "actor": "reviewer@test"}
obs = A._dispatch("generation_status", {}, ctx, allow_commit=False)
check("observe works (read-only)", obs.get("unavailable"), None)
for verb in ("generate_topics", "retry_generation", "update_policy", "approval_policy"):
    d = A._dispatch(verb, {}, ctx, allow_commit=False)
    check(f"AgentRep has NO authority for '{verb}' (not_exposed)", d.get("reason_class"), "not_exposed")

conn.close()
print("\n" + "="*62)
print("ALL LINEAGE / SNAPSHOT / WRITER-PROVENANCE CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*62)
sys.exit(0 if PASS else 1)
