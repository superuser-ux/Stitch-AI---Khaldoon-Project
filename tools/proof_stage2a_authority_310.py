"""#310 authority vs execution vs TRUTHFUL delegation lineage (round-7 correction).

Repository truth: principal.owner_id means ONLY `agent_rep -> the human it acts for` (migration 003).
Generic runtime control/delegation records do not exist (deferred #21/#197). So provenance records:
  - AUTHORITY: the exact accepted gate + ALL approving gate_decision rows (may be multiple).
  - EXECUTION: resolver/trigger actor + writer agent/contract + resolved provider/model/route.
  - AgentRep accountable_owner ONLY when truthfully present (kind='agent_rep'); else null.
  - control_resolution='not_recorded' + controlling_principal/delegation_ref null when no authoritative
    runtime delegation exists — truthful, immutable absence, never approximated from owner_id.

Proves: approver != resolver; multi-approver quorum; real AgentRep accountability captured; ordinary
principals get NO fabricated delegation; later principal changes do not reinterpret frozen history.
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

TEST_PRINCIPALS = ("ar-310", "usr-310", "boss-310", "newboss-310")
def clean_principals(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM principal WHERE owner_id IN %s", (TEST_PRINCIPALS,))
    for pid in TEST_PRINCIPALS:
        cur.execute("DELETE FROM principal WHERE principal_id=%s", (pid,))
    conn.commit(); cur.close(); eng._PRINCIPAL_KINDS = None

def mk_round(conn, rid):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id,module)
                   VALUES (%s,'auth',1,3,'["09:00"]','{}','{}','planning','default','content')""", (rid,))
    cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,
                   status,cycle_no,topic_angle,hook_text,format,tenant_id)
                   VALUES (%s,%s,1,'09:00','P1_SELF','1.1','L1','Painful Truth','RESERVED',1,'ز','خ','Hero Reel','default')""",
                (rid + "-A", rid))
    conn.commit(); cur.close()
    eng.initialize_schedule_mapping(conn, rid, actor="system", cfg=CFG)
    return eng.open_gate(conn, "schedule_review", round_id=rid, actor="system", cfg=CFG)

def add_decision(conn, gid, rid, approver):
    cur = conn.cursor()
    cur.execute("""INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision, revision, decided_at)
                   VALUES (%s,%s,%s,'approve',1,now())""", (gid, rid + "-A", approver))
    conn.commit(); cur.close()

def prov(conn, rid):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT tp.* FROM topic_provenance tp JOIN topic t ON t.topic_id=tp.topic_id
                    WHERE t.round_id=%s ORDER BY tp.created_at LIMIT 1""", (rid,))
    p = cur.fetchone(); cur.close(); return p

def appr_of(auth, pid):
    return next(a for a in auth["approvals"] if a["principal_id"] == pid)

conn = db()

print("A) approver != resolver; ordinary principals carry TRUTHFUL 'not_recorded' delegation absence")
RID = "R-AUTH1"; teardown(conn, RID)
gid = mk_round(conn, RID)
add_decision(conn, gid, RID, "khal")               # AUTHORITY: khal approves
eng.resolve(conn, gid, actor="system", cfg=CFG)    # EXECUTION: system resolves (different actor)
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
p = prov(conn, RID); auth = p["authority_snapshot"]; a_khal = appr_of(auth, "khal")
check("authority approver is khal", auth["approver_principals"], ["khal"])
check("effective_actor is the resolver 'system' (not relabelled approver)", p["effective_actor"], "system")
check("resolved_by recorded separately as 'system'", auth["resolved_by"]["principal_id"], "system")
check("ordinary approver: generic delegation NOT recorded (truthful absence)",
      (a_khal["control_resolution"], a_khal["controlling_principal"], a_khal["delegation_ref"]),
      ("not_recorded", None, None))
check("ordinary approver: no fabricated AgentRep accountability", a_khal["accountable_owner"], None)
check("executor writer + resolver both differ from the approver",
      (p["writer_agent"], auth["resolved_by"]["principal_id"], a_khal["principal_id"]),
      ("writers", "system", "khal"))
teardown(conn, RID)

print("B) multi-approver quorum preserved (never collapsed)")
RID = "R-AUTH2"; teardown(conn, RID)
gid = mk_round(conn, RID)
add_decision(conn, gid, RID, "khal"); add_decision(conn, gid, RID, "nour")
eng.resolve(conn, gid, actor="khal", cfg=CFG)
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
p = prov(conn, RID); auth = p["authority_snapshot"]
check("both approvers preserved", sorted(auth["approver_principals"]), ["khal", "nour"])
check("one approval row per approver", len(auth["approvals"]), 2)
check("each approver truthfully not_recorded for generic delegation",
      sorted(set(a["control_resolution"] for a in auth["approvals"])), ["not_recorded"])
teardown(conn, RID)

print("C) real AgentRep accountability captured; ordinary principals NOT fabricated; D) immutable history")
RID = "R-AUTH3"; teardown(conn, RID); clean_principals(conn)
cur = conn.cursor()
cur.execute("""INSERT INTO principal (principal_id, kind, tenant_id, module) VALUES
               ('boss-310','user','default','content'),('newboss-310','user','default','content')""")
# a REAL agent_rep with its accountable human (owner_id's only authoritative meaning).
cur.execute("""INSERT INTO principal (principal_id, kind, owner_id, tenant_id, module, autonomy_level)
               VALUES ('ar-310','agent_rep','boss-310','default','content','recommend')""")
conn.commit(); cur.close(); eng._PRINCIPAL_KINDS = None
gid = mk_round(conn, RID)
add_decision(conn, gid, RID, "khal")               # authorized approver advances the slot
add_decision(conn, gid, RID, "ar-310")             # a real agent_rep decision, recorded with accountability
eng.resolve(conn, gid, actor="system", cfg=CFG)
run_writers.dispatch_pending_topic_generation(CFG, round_id=RID)
p = prov(conn, RID); auth = p["authority_snapshot"]
a_ar = appr_of(auth, "ar-310"); a_kh = appr_of(auth, "khal")
check("agent_rep approver: real kind preserved", a_ar["actor_kind"], "agent_rep")
check("agent_rep approver: accountable_owner recorded (its truthful meaning)", a_ar["accountable_owner"], "boss-310")
check("agent_rep approver: generic delegation STILL not_recorded (null)",
      (a_ar["control_resolution"], a_ar["controlling_principal"], a_ar["delegation_ref"]),
      ("not_recorded", None, None))
check("ordinary approver khal: NO fabricated accountability/delegation",
      (a_kh["accountable_owner"], a_kh["controlling_principal"], a_kh["control_resolution"]),
      (None, None, "not_recorded"))
check("executor writer != accountable owner", p["writer_agent"] != a_ar["accountable_owner"], True)
# D) mutate the agent_rep's accountable owner AFTER the fact — frozen history must not change.
cur = conn.cursor()
cur.execute("UPDATE principal SET owner_id='newboss-310' WHERE principal_id='ar-310'"); conn.commit()
cur.close(); eng._PRINCIPAL_KINDS = None
check("later principal change does NOT reinterpret frozen history",
      appr_of(prov(conn, RID)["authority_snapshot"], "ar-310")["accountable_owner"], "boss-310")
teardown(conn, RID); clean_principals(conn)

print("E) _principal_ref truthfulness (unit)")
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("""INSERT INTO principal (principal_id, kind, tenant_id, module) VALUES ('boss-310','user','default','content')""")
cur.execute("""INSERT INTO principal (principal_id, kind, owner_id, tenant_id, module, autonomy_level)
               VALUES ('ar-310','agent_rep','boss-310','default','content','recommend')""")
# an ordinary user WITH owner_id set must NOT be read as delegation (owner_id is agent_rep-only meaning).
cur.execute("""INSERT INTO principal (principal_id, kind, owner_id, tenant_id, module)
               VALUES ('usr-310','user','boss-310','default','content')""")
conn.commit(); eng._PRINCIPAL_KINDS = None
ar = eng._principal_ref(cur, "ar-310")
usr = eng._principal_ref(cur, "usr-310")
un = eng._principal_ref(cur, "nobody-310")
check("agent_rep -> accountable_owner captured", (ar["actor_kind"], ar["accountable_owner"]), ("agent_rep", "boss-310"))
check("agent_rep -> generic delegation still absent", (ar["controlling_principal"], ar["control_resolution"]), (None, "not_recorded"))
check("ordinary user w/ owner_id -> NO fabricated accountable_owner", (usr["actor_kind"], usr["accountable_owner"]), ("user", None))
check("unregistered -> all-null, not_recorded",
      (un["accountable_owner"], un["controlling_principal"], un["control_resolution"]), (None, None, "not_recorded"))
cur.close(); clean_principals(conn)

conn.close()
print("\n" + "="*62)
print("ALL AUTHORITY / TRUTHFUL-DELEGATION CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*62)
sys.exit(0 if PASS else 1)
