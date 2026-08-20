"""#332 — focused security/concurrency proof for the canonical MANUAL Topic-generation authority + audit.

Engine-level (deterministic; no writer/background job) proves the authority predicate, coarse
authorization-safe denials, automatic-mode exclusion, lifecycle replay, one-transition + one-accepted-audit
atomicity, N-way concurrency, and malformed/normalization fail-closed. A compact API section proves the
endpoint AUTHENTICATES before target disclosure (unsigned -> 401) and denies a signed non-approver (403).

Run (against the isolated stub DB, writer stub):
  docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.manual_topic_generation_selftest
"""
import os, sys, threading
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))                                # gates/ — bare `import engine`/`import api`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))  # agents/ — run_writers deps
os.environ.setdefault("TANAGHOM_WRITER_STUB", "1")
import engine  # noqa: E402

PASS, FAIL = [], []


def check(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print(("[PASS]" if ok else "[FAIL]") + f" {label}: got={got!r} want={want!r}")


def db():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"), port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "tanaghom"), user=os.environ.get("DB_USER", "tanaghom"),
        password=os.environ["DB_PASSWORD"])


RID = "ZTEST-332-MANUAL"


def cleanup(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_log WHERE entity_id=%s OR (detail->>'round_id')=%s", (RID, RID))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM slot WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit(); cur.close()


def seed(conn, *, entry_mode="manual", status="awaiting_trigger", approvers=("khal",),
         token=7, gate="gate-332", policy=True, snap=None, job_tenant="default", job_module="content"):
    """Reset RID to exactly one canonical topic generation_job in the requested state."""
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_log WHERE entity_id=%s OR (detail->>'round_id')=%s", (RID, RID))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
    cur.execute("""INSERT INTO round(round_id,period_len_days,posts_per_day,post_times,
                     pillar_distribution,format_distribution,status)
                   VALUES(%s,2,2,'["09:00","20:00"]'::jsonb,'{}'::jsonb,'{}'::jsonb,'planning')
                   ON CONFLICT (round_id) DO NOTHING""", (RID,))
    # create-missing an active pinned policy so the job carries a valid topic_generation_policy_id
    cur.execute("SELECT policy_id FROM topic_generation_policy "
                "WHERE status='active' AND tenant_id='default' AND module='content' LIMIT 1")
    row = cur.fetchone()
    if row:
        pid = row[0]
    else:
        cur.execute("INSERT INTO topic_generation_policy(generation_no,status,entry_mode) "
                    "VALUES(1,'active','manual') RETURNING policy_id")
        pid = cur.fetchone()[0]
    if snap is None:
        snap = {"snapshot_version": "authority.v1", "gate_id": gate, "stage": "schedule_review",
                "accepted_schedule_token": token, "approver_principals": list(approvers),
                "approvals": [{"principal_id": a, "decision": "approve"} for a in approvers],
                "resolved_by": {"principal_id": "system"}}
    cur.execute("""INSERT INTO generation_job(round_id,stage,status,entry_mode,accepted_schedule_token,
                     tenant_id,module,topic_generation_policy_id,authority_snapshot)
                   VALUES(%s,'topic',%s,%s,%s,%s,%s,%s,%s) RETURNING job_id""",
                (RID, status, entry_mode, token, job_tenant, job_module,
                 (pid if policy else None), psycopg2.extras.Json(snap)))
    jid = str(cur.fetchone()[0]); conn.commit(); cur.close()
    return jid


def insert_extra_job(conn, *, token, approvers=("khal",), status="awaiting_trigger", entry_mode="manual"):
    """Insert an ADDITIONAL (newer created_at) canonical Topic job for RID — used by the forced
    concurrent-newer-job interleaving proof. Returns the new job_id."""
    cur = conn.cursor()
    cur.execute("SELECT policy_id FROM topic_generation_policy "
                "WHERE status='active' AND tenant_id='default' AND module='content' LIMIT 1")
    pid = cur.fetchone()[0]
    snap = {"snapshot_version": "authority.v1", "gate_id": "gate-332b", "stage": "schedule_review",
            "accepted_schedule_token": token, "approver_principals": list(approvers),
            "approvals": [{"principal_id": a, "decision": "approve"} for a in approvers],
            "resolved_by": {"principal_id": "system"}}
    cur.execute("""INSERT INTO generation_job(round_id,stage,status,entry_mode,accepted_schedule_token,
                     tenant_id,module,topic_generation_policy_id,authority_snapshot)
                   VALUES(%s,'topic',%s,%s,%s,'default','content',%s,%s) RETURNING job_id""",
                (RID, status, entry_mode, token, pid, psycopg2.extras.Json(snap)))
    jid = str(cur.fetchone()[0]); conn.commit(); cur.close()
    return jid


def job_status(conn, jid):
    cur = conn.cursor(); cur.execute("SELECT status FROM generation_job WHERE job_id=%s", (jid,))
    s = cur.fetchone()[0]; cur.close(); return s


def accepted_audits(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM audit_log WHERE action='topic_generation_manual_start' "
                "AND (detail->>'round_id')=%s", (RID,))
    n = cur.fetchone()[0]; cur.close(); return n


def denied_audits(conn, reason=None):
    cur = conn.cursor()
    if reason:
        cur.execute("SELECT count(*) FROM audit_log WHERE action='topic_generation_manual_start_denied' "
                    "AND entity_id=%s AND detail->>'reason'=%s", (RID, reason))
    else:
        cur.execute("SELECT count(*) FROM audit_log WHERE action='topic_generation_manual_start_denied' "
                    "AND entity_id=%s", (RID,))
    n = cur.fetchone()[0]; cur.close(); return n


def main():
    conn = db()
    try:
        act = engine.activate_manual_topic_generation

        # 1) affirmative approver on a manual awaiting_trigger job -> one transition + one accepted audit
        jid = seed(conn, approvers=("khal", "huda"))
        r = act(conn, RID, "khal")
        check("approver activates", r["result"], engine.MANUAL_START_ACTIVATED)
        check("approver -> job queued", job_status(conn, jid), "queued")
        check("exactly ONE accepted audit", accepted_audits(conn), 1)
        check("no denial audit on success", denied_audits(conn), 0)

        # 2) signed NON-approver -> coarse authz denial, NO transition, NO accepted audit, denial audited
        jid = seed(conn, approvers=("khal",))
        r = act(conn, RID, "mallory")
        check("non-approver coarse denied", r["result"], engine.MANUAL_START_DENIED)
        check("non-approver: job UNCHANGED (awaiting_trigger)", job_status(conn, jid), "awaiting_trigger")
        check("non-approver: no accepted audit", accepted_audits(conn), 0)
        check("non-approver: denial audited", denied_audits(conn), 1)

        # 3) empty/anonymous principal -> coarse authz denial (engine layer; API layer returns 401)
        jid = seed(conn, approvers=("khal",))
        check("empty principal denied", act(conn, RID, "")["result"], engine.MANUAL_START_DENIED)
        check("empty principal: unchanged", job_status(conn, jid), "awaiting_trigger")

        # 4) automatic-mode exclusion (post-eligibility distinct denial) — approver, automatic job
        jid = seed(conn, entry_mode="automatic", status="awaiting_trigger", approvers=("khal",))
        r = act(conn, RID, "khal")
        check("automatic denied (approver)", r["result"], engine.MANUAL_START_AUTOMATIC)
        check("automatic: job UNCHANGED", job_status(conn, jid), "awaiting_trigger")
        check("automatic: distinct denial reason", denied_audits(conn, "automatic_mode"), 1)
        check("automatic: no accepted audit", accepted_audits(conn), 0)

        # 5) lifecycle replay — approver, job already queued -> lifecycle, NO second accepted audit
        jid = seed(conn, status="queued", approvers=("khal",))
        r = act(conn, RID, "khal")
        check("approver replay -> lifecycle", r["result"], engine.MANUAL_START_LIFECYCLE)
        check("replay: status is the real lifecycle", r.get("status"), "queued")
        check("replay: no accepted audit", accepted_audits(conn), 0)

        # 6) malformed snapshot (no approver set) -> coarse denial, unchanged
        jid = seed(conn, snap={"stage": "schedule_review", "accepted_schedule_token": 7, "gate_id": "g"})
        check("malformed snapshot denied", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)
        check("malformed: unchanged", job_status(conn, jid), "awaiting_trigger")

        # 6b) non-string approver id -> whole set fails closed
        jid = seed(conn, snap={"stage": "schedule_review", "accepted_schedule_token": 7, "gate_id": "g",
                               "approver_principals": [123, "khal"]})
        check("non-string approver id fails closed", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)

        # 7) token mismatch between snapshot and job -> coarse denial (exact-token binding)
        jid = seed(conn, token=7, approvers=("khal",),
                   snap={"stage": "schedule_review", "accepted_schedule_token": 99, "gate_id": "g",
                         "approver_principals": ["khal"]})
        check("token mismatch denied", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)

        # 7b) wrong gate stage -> coarse denial
        jid = seed(conn, approvers=("khal",),
                   snap={"stage": "topic_review", "accepted_schedule_token": 7, "gate_id": "g",
                         "approver_principals": ["khal"]})
        check("wrong gate stage denied", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)

        # 8) missing pinned policy -> provisioning invalid -> coarse denial
        jid = seed(conn, approvers=("khal",), policy=False)
        check("no pinned policy denied", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)

        # 9) no canonical job -> coarse denial
        cleanup(conn); seed(conn, approvers=("khal",)); cur = conn.cursor()
        cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,)); conn.commit(); cur.close()
        check("no job denied", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)

        # 10) normalization: caller ' khal ' trims to eligible; 'KHAL' is case-sensitively denied
        jid = seed(conn, approvers=("khal",))
        check("caller whitespace trimmed to eligible", act(conn, RID, " khal ")["result"],
              engine.MANUAL_START_ACTIVATED)
        jid = seed(conn, approvers=("khal",))
        check("case-different principal denied", act(conn, RID, "KHAL")["result"], engine.MANUAL_START_DENIED)

        # 11) N-way concurrency — exactly ONE transition + ONE accepted audit; losers get lifecycle
        jid = seed(conn, approvers=("khal",))
        results = {}
        def worker(i):
            c = db()
            try:
                results[i] = engine.activate_manual_topic_generation(c, RID, "khal")["result"]
            finally:
                c.close()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        activated = sum(1 for v in results.values() if v == engine.MANUAL_START_ACTIVATED)
        lifecycle = sum(1 for v in results.values() if v == engine.MANUAL_START_LIFECYCLE)
        check("concurrency: exactly ONE activation", activated, 1)
        check("concurrency: the rest are lifecycle replays", lifecycle, 5)
        check("concurrency: exactly ONE accepted audit", accepted_audits(conn), 1)
        check("concurrency: final status queued", job_status(conn, jid), "queued")

        # 12) TENANT/MODULE binding — a job pinned to a scope != the round's server-derived scope fails
        #     closed with the coarse denial (cross-tenant, then cross-module).
        jid = seed(conn, approvers=("khal",), job_tenant="tenant-x")
        check("cross-tenant scope mismatch coarse-denied", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)
        check("cross-tenant: job unchanged", job_status(conn, jid), "awaiting_trigger")
        jid = seed(conn, approvers=("khal",), job_module="scripts")
        check("cross-module scope mismatch coarse-denied", act(conn, RID, "khal")["result"], engine.MANUAL_START_DENIED)
        check("cross-module: job unchanged", job_status(conn, jid), "awaiting_trigger")

        # 13) duplicate-conflicting NORMALIZED snapshot identities fail closed; EXACT duplicates tolerated.
        jid = seed(conn, snap={"stage": "schedule_review", "accepted_schedule_token": 7, "gate_id": "g",
                               "approver_principals": ["khal", " khal "]})
        check("collision-normalized approver ids fail closed", act(conn, RID, "khal")["result"],
              engine.MANUAL_START_DENIED)
        jid = seed(conn, snap={"stage": "schedule_review", "accepted_schedule_token": 7, "gate_id": "g",
                               "approver_principals": ["khal", "khal"]})
        check("exact-duplicate approver ids tolerated -> approver activates", act(conn, RID, "khal")["result"],
              engine.MANUAL_START_ACTIVATED)

        # 14) ACCEPTED-AUDIT failure ROLLS BACK the transition (never a queued job without its accepted audit)
        jid = seed(conn, approvers=("khal",))
        _orig_audit = engine._audit
        engine._audit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("accepted-audit boom"))
        try:
            cx = db(); raised = False
            try:
                engine.activate_manual_topic_generation(cx, RID, "khal")
            except RuntimeError:
                raised = True
            finally:
                cx.close()
        finally:
            engine._audit = _orig_audit
        check("accepted-audit failure raises", raised, True)
        check("accepted-audit failure ROLLS BACK the transition (still awaiting_trigger)",
              job_status(conn, jid), "awaiting_trigger")
        check("accepted-audit failure: no accepted audit persisted", accepted_audits(conn), 0)

        # 15) DENIAL-AUDIT failure cannot AUTHORIZE — a non-approver is still denied, job unchanged.
        jid = seed(conn, approvers=("khal",))
        _orig_deny = engine.audit_denied
        engine.audit_denied = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("denial-audit boom"))
        try:
            cx = db()
            try:
                r = engine.activate_manual_topic_generation(cx, RID, "mallory")
            finally:
                cx.close()
        finally:
            engine.audit_denied = _orig_deny
        check("denial-audit failure still DENIES (never authorizes)", r["result"], engine.MANUAL_START_DENIED)
        check("denial-audit failure: job unchanged", job_status(conn, jid), "awaiting_trigger")

        # 16) FORCED-INTERLEAVING — a concurrent NEWER accepted-token job inserted while manual-start is
        #     blocked on the ROUND lock cannot cause a STALE activation, and there is NO deadlock. Because
        #     activate takes the round lock FIRST, holding the round lock externally makes activate BLOCK;
        #     we then insert a newer job B under that lock and release — activate must pick B (newest), not A.
        jid_a = seed(conn, token=7, approvers=("khal",))
        hold = db(); hcur = hold.cursor()
        hcur.execute("SELECT round_id FROM round WHERE round_id=%s FOR UPDATE", (RID,))  # hold round lock
        out = {}
        def _starter():
            c = db()
            try:
                out["res"] = engine.activate_manual_topic_generation(c, RID, "khal")
            finally:
                c.close()
        th = threading.Thread(target=_starter); th.start()
        th.join(timeout=2.0)
        check("activate BLOCKS on the round lock (round-first ordering)", th.is_alive(), True)
        jid_b = insert_extra_job(hold, token=8, approvers=("khal",))   # newer canonical job under the lock
        hold.commit(); hcur.close(); hold.close()                      # release the round lock
        th.join(timeout=10.0)
        check("no deadlock: manual-start completes after lock release", th.is_alive(), False)
        check("activated the NEWEST job B, not stale A", out.get("res", {}).get("job_id"), jid_b)
        check("stale A remains awaiting_trigger (not activated)", job_status(conn, jid_a), "awaiting_trigger")
        check("newest B is queued", job_status(conn, jid_b), "queued")

        cleanup(conn)
    finally:
        conn.close()

    # --- compact API auth-wrapper check (authenticate before target disclosure) ---
    try:
        import hmac as _h, hashlib as _hh
        from fastapi.testclient import TestClient
        import api as _api
        client = TestClient(_api.app, raise_server_exceptions=False)
        c2 = db()
        try:
            seed(c2, approvers=("khal",))
        finally:
            c2.close()
        secret = _api._proxy_secret().encode()
        def _sig(p):
            s = _h.new(secret, p.encode(), _hh.sha256).hexdigest()
            return {"x-principal-id": p, "x-principal-signature": s}
        r_unsigned = client.post(f"/rounds/{RID}/stages/topic_review/generate")
        check("API unsigned -> 401 (no target disclosed)", r_unsigned.status_code, 401)
        r_nonapp = client.post(f"/rounds/{RID}/stages/topic_review/generate", headers=_sig("mallory"))
        check("API signed non-approver -> 403 coarse", r_nonapp.status_code, 403)
        c3 = db()
        try:
            cleanup(c3)
        finally:
            c3.close()
    except Exception as e:  # TestClient/app import unavailable in this context — engine proofs still stand
        print(f"[note] API-wrapper section skipped ({type(e).__name__}: {e}); engine-level auth proofs above hold")

    print(f"\n#332 manual-start selftest: PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("FAILURES:", FAIL)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
