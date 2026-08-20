"""#310 §F — AgentRep observe/explain/recommend parity + retry-via-existing-binding + audited denial.

Stub-only, isolated. Proves:
  1) OBSERVE parity — the agent can read the Stage 2A job/results read model (basis for explain/recommend).
  2) No second start/retry path from free text — an agent retry attempt is a structured not_exposed denial
     pointing to the confirmed dashboard binding.
  3) Engine retry semantics — a retry refuses unless a FAILED/PARTIAL job exists (never a fresh start),
     and a failed job is reset for a bounded, idempotent re-drive with an attributed audit.
Makes NO model/provider call.
"""
import os, sys
sys.path.insert(0, "/work"); sys.path.insert(0, "/work/gates")
import psycopg2, psycopg2.extras
import engine as eng
import agent as A

PASS = True
def check(label, got, want):
    global PASS; ok = got == want; PASS = PASS and ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")

conn = psycopg2.connect(host=os.environ["DB_HOST"], dbname=os.environ["DB_NAME"],
                        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                        port=os.environ.get("DB_PORT", "5432"))
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

RID = "R1"                      # has a completed Stage 2A job with 4 generated topics
ctx = {"round_id": RID, "artifact": "topic", "actor": "reviewer@test"}

print("1) OBSERVE parity — agent reads the Topic job/results read model")
obs = A._dispatch("generation_status", {}, ctx, allow_commit=False)
check("observe returns the read model phase", obs.get("phase"), "completed")
check("observe surfaces per-slot results", len(obs.get("results", [])) > 0, True)
check("observe discloses provenance (resolved model) for explain/recommend",
      obs["results"][0]["provenance"]["resolved_model"], "stub:test")
check("observe is NOT an unavailable/denied shape", obs.get("unavailable"), None)

print("2) NO second start/retry path from free text — structured, pointing to the confirmed binding")
for verb in ("generate_topics", "retry_generation", "retry_topics"):
    d = A._dispatch(verb, {}, ctx, allow_commit=False)
    check(f"{verb}: not_exposed denial", d.get("reason_class"), "not_exposed")
    check(f"{verb}: names a next step (the dashboard binding)", bool(d.get("next_step")), True)

print("3) engine retry semantics — refuses a non-retryable job (no second start path)")
# R1's job is completed -> retry must refuse.
try:
    eng.retry_topic_generation(conn, RID, "reviewer@test"); refused = False
except eng.GateError as e:
    refused = "nothing to retry" in str(e)
check("completed job -> retry refused (not re-driven)", refused, True)

# a round with NO job -> refuse (retry is not a start path)
try:
    eng.retry_topic_generation(conn, "NO-SUCH-ROUND-310", "reviewer@test"); no_job = False
except eng.GateError as e:
    no_job = "nothing to retry" in str(e)
check("no job -> retry refused (start is the acceptance trigger, not retry)", no_job, True)

print("4) engine retry semantics — a FAILED job is reset + attributed for a bounded re-drive")
cur.execute("SELECT job_id FROM generation_job WHERE round_id=%s ORDER BY created_at DESC LIMIT 1", (RID,))
jid = cur.fetchone()["job_id"]
cur.execute("UPDATE generation_job SET status='failed' WHERE job_id=%s", (jid,))
cur.execute("DELETE FROM audit_log WHERE entity='generation_job' AND entity_id=%s AND action='topic_generation_retry'", (str(jid),))
plan = eng.retry_topic_generation(conn, RID, "reviewer@test")
check("retry returns the SAME durable job (no new job minted)", plan["job_id"], str(jid))
cur.execute("SELECT status FROM generation_job WHERE job_id=%s", (jid,))
check("failed job reset to queued for re-drive", cur.fetchone()["status"], "queued")
cur.execute("SELECT actor, detail FROM audit_log WHERE entity='generation_job' AND entity_id=%s AND action='topic_generation_retry'", (str(jid),))
au = cur.fetchone()
check("retry is attributed to the acting reviewer (audit)", au["actor"], "reviewer@test")
check("retry audit records the from_status (failed)", au["detail"].get("from_status"), "failed")

# restore R1 to completed so the fixture is unchanged for later runs
cur.execute("UPDATE generation_job SET status='completed' WHERE job_id=%s", (jid,))

cur.close(); conn.close()
print("\n" + "="*60)
print("ALL AGENTREP CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*60)
sys.exit(0 if PASS else 1)
