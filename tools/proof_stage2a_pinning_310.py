"""#310 policy-provenance PINNING + tenant/module SCOPING regressions (GPT/Codex round-4 BLOCK).

Non-skipping proof of:
  1. topic-generation policy change AFTER enqueue -> execution uses the PINNED policy, not the new
     active one; provenance records the pinned id.
  2. two independent (tenant, module) scopes -> each gets its OWN baseline; resolution in one scope
     never sees the other (no false multiple-active); each job pins its own scope's policy.
  3. explicit DISABLE in one scope -> that scope falls back to Stage 1 (no job); the other scope is
     unaffected and still enqueues.
  4. repetition-policy change BETWEEN enqueue and execution -> provenance records the PINNED
     repetition-policy identity, never a live/global pick.

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

def seed_accept(conn, rid, tenant):
    """A round in scope (tenant, content) driven through real Schedule acceptance -> a pinned job."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id,module)
                   VALUES (%s,'pin',1,3,'["09:00"]','{}','{}','planning',%s,'content')""", (rid, tenant))
    cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,
                   status,cycle_no,topic_angle,hook_text,format,tenant_id)
                   VALUES (%s,%s,1,'09:00','P1_SELF','1.1','L1','Painful Truth','RESERVED',1,'ز','خ','Hero Reel',%s)""",
                (rid + "-A", rid, tenant))
    conn.commit(); cur.close()
    eng.initialize_schedule_mapping(conn, rid, actor="system", cfg=CFG)
    gid = eng.open_gate(conn, "schedule_review", round_id=rid, actor="khal", cfg=CFG)
    eng.decide(conn, gid, "khal", "approve", cfg=CFG)
    eng.resolve(conn, gid, actor="khal", cfg=CFG)

def job_of(conn, rid):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM generation_job WHERE round_id=%s", (rid,)); j = cur.fetchone(); cur.close()
    return j

conn = db()

print("1) topic-generation policy change AFTER enqueue -> execution uses the PINNED policy")
T = "pintest"; RID = "R-PIN1"
cleanup_scope(conn, T); teardown_round(conn, RID)
seed_accept(conn, RID, T)
job = job_of(conn, RID)
pinned_tgp = str(job["topic_generation_policy_id"])
check("job pinned a topic_generation_policy_id at enqueue", bool(pinned_tgp) and pinned_tgp != "None", True)
# GOVERNED POLICY CHANGE in this scope: supersede the pinned generation with a new active one.
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("UPDATE topic_generation_policy SET status='superseded' WHERE policy_id=%s", (pinned_tgp,))
cur.execute("""INSERT INTO topic_generation_policy (generation_no, supersedes, status, actor, reason, tenant_id, module)
               VALUES (2, %s, 'active', 'op', 'change after enqueue', %s, 'content') RETURNING policy_id""",
            (pinned_tgp, T))
new_tgp = str(cur.fetchone()["policy_id"]); conn.commit()
check("a different generation is now active in scope", new_tgp != pinned_tgp, True)
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
cur.execute("""SELECT DISTINCT tp.topic_generation_policy_id::text AS pid FROM topic_provenance tp
                 JOIN topic t ON t.topic_id=tp.topic_id WHERE t.round_id=%s""", (RID,))
prov_pids = [r["pid"] for r in cur.fetchall()]
check("provenance records the PINNED policy, not the newly-active one", prov_pids, [pinned_tgp])
cur.execute("SELECT topic_generation_policy_id::text AS pid FROM generation_job WHERE round_id=%s", (RID,))
check("the job's pinned policy id is unchanged by the policy change", cur.fetchone()["pid"], pinned_tgp)
cur.close(); teardown_round(conn, RID); cleanup_scope(conn, T)

print("2) two independent (tenant, module) scopes -> own baselines, no cross-scope ambiguity")
TA, TB, RA, RB = "scopeA", "scopeB", "R-PINA", "R-PINB"
for t in (TA, TB): cleanup_scope(conn, t)
for r in (RA, RB): teardown_round(conn, r)
seed_accept(conn, RA, TA); seed_accept(conn, RB, TB)
ja, jb = job_of(conn, RA), job_of(conn, RB)
check("scope A and scope B pinned DIFFERENT baseline policies",
      str(ja["topic_generation_policy_id"]) != str(jb["topic_generation_policy_id"]), True)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
# resolution in each scope returns exactly its own active generation — B never creates ambiguity in A.
polA = eng.resolve_topic_generation_policy(cur, TA, "content")
polB = eng.resolve_topic_generation_policy(cur, TB, "content")
check("scoped resolution returns each scope's own policy (no multiple-active error)",
      (str(polA["policy_id"]) == str(ja["topic_generation_policy_id"]),
       str(polB["policy_id"]) == str(jb["topic_generation_policy_id"])), (True, True))
run_writers.dispatch_pending_topic_generation(CFG)   # drain both
for rid, jj in ((RA, ja), (RB, jb)):
    cur.execute("""SELECT DISTINCT tp.topic_generation_policy_id::text AS pid FROM topic_provenance tp
                     JOIN topic t ON t.topic_id=tp.topic_id WHERE t.round_id=%s""", (rid,))
    check(f"{rid} provenance pinned to its OWN scope policy",
          [r["pid"] for r in cur.fetchall()], [str(jj["topic_generation_policy_id"])])
cur.close()
for r in (RA, RB): teardown_round(conn, r)
for t in (TA, TB): cleanup_scope(conn, t)

print("3) explicit DISABLE in one scope is scope-local (A -> Stage 1 fallback; B unaffected)")
TA, TB = "disA", "disB"
for t in (TA, TB): cleanup_scope(conn, t)
# provision each scope's baseline via a first acceptance
for rid, t in (("R-DISA0", TA), ("R-DISB0", TB)):
    teardown_round(conn, rid); seed_accept(conn, rid, t)
cur = conn.cursor()
cur.execute("UPDATE topic_generation_policy SET status='disabled' WHERE tenant_id=%s", (TA,)); conn.commit()  # disable A only
# a NEW acceptance in each scope
for rid, t in (("R-DISA1", TA), ("R-DISB1", TB)):
    teardown_round(conn, rid); seed_accept(conn, rid, t)
cur.execute("SELECT count(*) FROM generation_job WHERE round_id='R-DISA1'"); na = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM generation_job WHERE round_id='R-DISB1'"); nb = cur.fetchone()[0]
check("disabled scope A -> new acceptance enqueues NO job (Stage 1 fallback)", na, 0)
check("scope B unaffected -> new acceptance enqueues one job", nb, 1)
# and the disable is not resurrected by acceptance
cur.execute("SELECT count(*) FROM topic_generation_policy WHERE tenant_id=%s AND status='active'", (TA,))
check("disabled scope A has NO active policy after acceptance (not resurrected)", cur.fetchone()[0], 0)
cur.close()
for rid in ("R-DISA0", "R-DISA1", "R-DISB0", "R-DISB1"): teardown_round(conn, rid)
for t in (TA, TB): cleanup_scope(conn, t)

print("4) repetition-policy change between enqueue and execution -> provenance pins the enqueue-time id")
T = "reptest"; RID = "R-PINREP"
cleanup_scope(conn, T); cleanup_scope(conn, "repother"); teardown_round(conn, RID)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
# a managed repetition policy exists for THIS scope BEFORE acceptance -> it is the pinned identity.
cur.execute("""INSERT INTO repetition_policy (policy_key, enabled, scope, similarity_threshold,
               max_regenerations, tenant_id, module, updated_at)
               VALUES ('topic_generation', true, 'all', 0.86, 3, %s, 'content', now())
               RETURNING policy_id""", (T,))
rep1 = str(cur.fetchone()["policy_id"]); conn.commit()
seed_accept(conn, RID, T)
job = job_of(conn, RID)
check("job pinned the enqueue-time repetition policy", str(job["repetition_policy_id"]), rep1)
# CHANGE: a newer enabled repetition policy in another scope — the OLD global 'latest enabled' select
# would have grabbed THIS at persist time. The pinned id must win.
cur.execute("""INSERT INTO repetition_policy (policy_key, enabled, scope, similarity_threshold,
               max_regenerations, tenant_id, module, updated_at)
               VALUES ('topic_generation', true, 'all', 0.9, 5, 'repother', 'content', now() + interval '1 hour')
               RETURNING policy_id""")
rep2 = str(cur.fetchone()["policy_id"]); conn.commit()
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
cur.execute("""SELECT DISTINCT tp.repetition_policy_id::text AS pid FROM topic_provenance tp
                 JOIN topic t ON t.topic_id=tp.topic_id WHERE t.round_id=%s""", (RID,))
check("provenance records the PINNED repetition id, not the later global one",
      [r["pid"] for r in cur.fetchall()], [rep1])
cur.close()
teardown_round(conn, RID); cleanup_scope(conn, T); cleanup_scope(conn, "repother")

conn.close()
print("\n" + "="*62)
print("ALL POLICY-PINNING / SCOPING CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*62)
sys.exit(0 if PASS else 1)
