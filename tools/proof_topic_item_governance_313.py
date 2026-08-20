"""#313 Stage 2B-1 — canonical per-item Topic governance: B1 (approval/eligibility typed denial,
#249 unconsumed) + B2 (expected-revision CAS, idempotency, append-only overlap protection) proof.

Seeds ONE completed automatic Stage 2A topic round over HTTP (the canonical acceptance -> durable job
path), then asserts per-item governance IN-PROCESS against the same DB. Stub-only; no provider call.
Isolated :8015 / tanaghom_pr313."""
import os
import time
import threading
import psycopg2.extras
import gates.api_selftest as S
import gates.engine as E
import run_writers as RW

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc, **attrs):
    try:
        fn()
    except exc as e:
        ok = all(getattr(e, k, None) == v for k, v in attrs.items())
        detail = " ".join(f"{k}={getattr(e, k, None)!r}" for k in attrs)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {type(e).__name__} {detail}")
        if not ok:
            FAILS.append(label)
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] {label}: wrong exception {type(e).__name__}: {e}")
        FAILS.append(label)
    else:
        print(f"  [FAIL] {label}: no exception raised")
        FAILS.append(label)


def _err(body):
    """Unwrap a FastAPI typed-error body ({"detail": {...}}) to the inner {error, reason, current}."""
    d = body.get("detail") if isinstance(body, dict) else None
    return d if isinstance(d, dict) else (body if isinstance(body, dict) else {})


# --- seed a completed automatic topic round (canonical Stage 2A path) ---
elig = [e["name"] for e in S.GET("/baseline-eligibility")["eligible"]]
mix = {n: 0 for n in elig}
mix[elig[0]] = 2
_, rb = S.POST("/rounds", {"days": 1, "posts_per_day": 2, "label": "#313 gov proof", "format_mix": mix})
rid = rb["round_id"]
_, g = S.POST("/gates", {"stage": "schedule_review", "round_id": rid}, headers=S.AUTH_KHAL)
S.POST(f"/gates/{g['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"}, headers=S.AUTH_KHAL)
S.POST(f"/gates/{g['gate_id']}/resolve", {}, headers=S.AUTH_KHAL)
for _ in range(120):
    m = S.GET(f"/rounds/{rid}/generation")
    if m["phase"] in ("completed", "failed", "partial"):
        break
    time.sleep(0.5)

conn = S.db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED' ORDER BY slot_id", (rid,))
_slots = [r["slot_id"] for r in cur.fetchall()]
slot_id = _slots[0]
slot2 = _slots[1] if len(_slots) > 1 else None


def rows():
    cur.execute("SELECT revision, text_ar, base_revision, idempotency_key FROM topic WHERE slot_id=%s ORDER BY revision", (slot_id,))
    return cur.fetchall()


seed = rows()
check("seed: exactly one topic revision (rev1)", [r["revision"] for r in seed], [1])
orig_ar = seed[0]["text_ar"]

print("1) STRUCTURED EDIT — append-only new revision, prior immutable")
r = E.edit_revision(conn, slot_id, "topic", "text_ar", "زاوية معدّلة ١", actor="khal")
check("edit returns rev2", r["new_revision"], 2)
rr = rows()
check("append-only revisions [1,2]", [x["revision"] for x in rr], [1, 2])
check("rev1 source byte-unchanged (append-only)", rr[0]["text_ar"], orig_ar)
check("rev2 base_revision = 1", rr[1]["base_revision"], 1)

print("2) IDEMPOTENCY — replay returns original revision, no second write")
a = E.edit_revision(conn, slot_id, "topic", "text_ar", "زاوية ٢", actor="khal", idempotency_key="K1")
check("keyed edit -> rev3", a["new_revision"], 3)
b = E.edit_revision(conn, slot_id, "topic", "text_ar", "زاوية ٢", actor="khal", idempotency_key="K1")
check("replay same key -> same rev3", b["new_revision"], 3)
check("replay flagged idempotent", b.get("idempotent_replay"), True)
check("no rev4 minted on replay", [x["revision"] for x in rows()], [1, 2, 3])

print("3) EXPECTED-REVISION CAS — stale head -> RevisionConflict(409), no write")
raises("stale expected_revision denied", lambda: E.edit_revision(
    conn, slot_id, "topic", "text_ar", "x", actor="khal", expected_revision=1), E.RevisionConflict, current=3)
check("no revision minted on stale CAS", [x["revision"] for x in rows()], [1, 2, 3])

print("4) RESTORE-AS-NEW-REVISION — forward-only head, prior immutable")
res = E.restore_revision(conn, slot_id, "topic", 1, actor="khal")
check("restore v1 -> new head rev4", res["new_revision"], 4)
rr = rows()
check("append-only forward [1,2,3,4]", [x["revision"] for x in rr], [1, 2, 3, 4])
check("rev4 base_revision = 1 (restored-from)", rr[3]["base_revision"], 1)
check("rev4 content == rev1 (restored source)", rr[3]["text_ar"], orig_ar)

print("5) B1 ELIGIBILITY — approved item is fail-closed (#249 unconsumed)")
E._record_approval(cur, slot_id, "topic", 4, "khal")
conn.commit()
raises("edit of approved item denied", lambda: E.edit_revision(
    conn, slot_id, "topic", "text_ar", "x", actor="khal"), E.GovernedDenial, reason="approved")
raises("restore of approved item denied", lambda: E.restore_revision(
    conn, slot_id, "topic", 1, actor="khal"), E.GovernedDenial, reason="approved")
check("no revision minted while approved", [x["revision"] for x in rows()], [1, 2, 3, 4])
cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot_id,))
conn.commit()

print("6) B1 ELIGIBILITY — downstream-advanced (script exists) is fail-closed")
cur.execute("INSERT INTO script (slot_id, hcs_id) VALUES (%s, '1.1')", (slot_id,))
conn.commit()
raises("edit of downstream-advanced item denied", lambda: E.edit_revision(
    conn, slot_id, "topic", "text_ar", "x", actor="khal"), E.GovernedDenial, reason="downstream_advanced")
cur.execute("DELETE FROM script WHERE slot_id=%s", (slot_id,))
conn.commit()

print("7) SOURCE TRUTH — original source revision never overwritten across all mutations")
check("rev1 text_ar still the seeded source", rows()[0]["text_ar"], orig_ar)

print("8) HTTP BOUNDARY — typed 409s over the /slots/{id}/edit endpoint (signed principal)")
if slot2:
    def _err(body):
        d = body.get("detail")
        return d if isinstance(d, dict) else {}
    st, b = S.POST(f"/slots/{slot2}/edit", {"artifact": "topic", "field": "text_ar", "value": "عبر الـ API"}, headers=S.AUTH_KHAL)
    check("HTTP edit rev1 -> 200 rev2", (st, b.get("new_revision")), (200, 2))
    st2, b2 = S.POST(f"/slots/{slot2}/edit", {"artifact": "topic", "field": "text_ar", "value": "x", "expected_revision": 1}, headers=S.AUTH_KHAL)
    check("HTTP stale expected_revision -> 409 stale_revision(current=2)", (st2, _err(b2).get("error"), _err(b2).get("current")), (409, "stale_revision", 2))
    st3, b3 = S.POST(f"/slots/{slot2}/edit", {"artifact": "topic", "field": "text_ar", "value": "ك", "idempotency_key": "HK1"}, headers=S.AUTH_KHAL)
    st3b, b3b = S.POST(f"/slots/{slot2}/edit", {"artifact": "topic", "field": "text_ar", "value": "ك", "idempotency_key": "HK1"}, headers=S.AUTH_KHAL)
    check("HTTP idempotent replay -> same revision, no new write", (st3, st3b, b3.get("new_revision"), b3b.get("new_revision"), b3b.get("idempotent_replay")), (200, 200, 3, 3, True))
    E._record_approval(cur, slot2, "topic", 3, "khal")
    conn.commit()
    st4, b4 = S.POST(f"/slots/{slot2}/edit", {"artifact": "topic", "field": "text_ar", "value": "x"}, headers=S.AUTH_KHAL)
    check("HTTP edit of approved item -> 409 governed_denial(approved)", (st4, _err(b4).get("error"), _err(b4).get("reason")), (409, "governed_denial", "approved"))
    cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot2,))
    conn.commit()

print("9) CANONICAL READ MODEL — /slots/{id}/topic_item, typed action map matches the guard")
rm = S.GET(f"/slots/{slot_id}/topic_item")
check("read model head_revision = 4", rm["head_revision"], 4)
check("read model exposes full append-only history [1,2,3,4]", [r["revision"] for r in rm["revisions"]], [1, 2, 3, 4])
check("in-review: edit action allowed", rm["actions"]["edit"], {"allowed": True})
check("in-review: approve action allowed", rm["actions"]["approve"], {"allowed": True})
E._record_approval(cur, slot_id, "topic", 4, "khal")
conn.commit()
rm2 = S.GET(f"/slots/{slot_id}/topic_item")
check("approved: edit action denied(approved)", rm2["actions"]["edit"], {"allowed": False, "reason": "approved"})
check("approved: approve action denied(already_approved)", rm2["actions"]["approve"], {"allowed": False, "reason": "already_approved"})
check("approved_revision pinned = 4", rm2["approved_revision"], 4)
check("approved: history entry rev4 flagged approved", [r["revision"] for r in rm2["revisions"] if r["approved"]], [4])
cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot_id,))
conn.commit()

print("10) RESTORE — expected-revision CAS + idempotency (B2 parity with edit)")
raises("restore stale expected_revision denied", lambda: E.restore_revision(
    conn, slot_id, "topic", 1, actor="khal", expected_revision=1), E.RevisionConflict, current=4)
check("no revision minted on stale restore CAS", [x["revision"] for x in rows()], [1, 2, 3, 4])
rk = E.restore_revision(conn, slot_id, "topic", 1, actor="khal", idempotency_key="RK1")
check("keyed restore -> rev5", rk["new_revision"], 5)
rk2 = E.restore_revision(conn, slot_id, "topic", 1, actor="khal", idempotency_key="RK1")
check("restore replay same key -> same rev5, idempotent", (rk2["new_revision"], rk2.get("idempotent_replay")), (5, True))
check("no rev6 minted on restore replay", [x["revision"] for x in rows()], [1, 2, 3, 4, 5])

print("11) SCRIPT SAFETY (B1) — idempotency_key is a Topic-only column, fails closed for scripts")
raises("script edit with idempotency_key rejected (topic-only scope)", lambda: E.edit_revision(
    conn, slot_id, "script", "script_ar", "x", actor="khal", idempotency_key="NOPE"), E.GateError)
raises("script restore with idempotency_key rejected (topic-only scope)", lambda: E.restore_revision(
    conn, slot_id, "script", 1, actor="khal", idempotency_key="NOPE"), E.GateError)
# POSITIVE: a plain script edit (no idempotency_key) still works — the artifact-aware INSERT omits the
# topic-only idempotency_key column entirely for scripts, so it never references a missing column.
cur.execute("INSERT INTO script (slot_id, hcs_id, revision, script_ar) VALUES (%s,'1.1',1,'نص أصلي')", (slot_id,))
conn.commit()
sr = E.edit_revision(conn, slot_id, "script", "script_ar", "نص محرَّر", actor="khal")
check("plain script edit -> new revision 2 (artifact-aware INSERT, no idempotency column)", sr["new_revision"], 2)
cur.execute("SELECT count(*) AS c FROM script WHERE slot_id=%s", (slot_id,))
check("script now has 2 append-only revisions", cur.fetchone()["c"], 2)
cur.execute("DELETE FROM script WHERE slot_id=%s", (slot_id,))
conn.commit()

print("12) DROP — routes through the governed gate REJECT decision (P1-3), non-destructive, denial on approved")
std, bd = S.POST(f"/slots/{slot_id}/drop", {"reason": "off-brand"}, headers=S.AUTH_KHAL)
check("HTTP drop -> 200 decision_recorded, NOT committed (human floor)", (std, bd.get("decision_recorded"), bd.get("committed")), (200, True, False))
cur.execute("SELECT count(*) AS c FROM gate_decision WHERE slot_id=%s AND decision='reject'", (slot_id,))
check("drop recorded a gate REJECT decision (reuses gate lineage, not a direct status write)", cur.fetchone()["c"] >= 1, True)
check("topic rows preserved after drop (non-destructive)", [x["revision"] for x in rows()], [1, 2, 3, 4, 5])
E._record_approval(cur, slot_id, "topic", 5, "khal")
conn.commit()
sta_d, ba_d = S.POST(f"/slots/{slot_id}/drop", {"reason": "x"}, headers=S.AUTH_KHAL)
check("HTTP drop of APPROVED item -> 409 governed_denial (#249 unconsumed)", (sta_d, _err(ba_d).get("error"), _err(ba_d).get("reason")), (409, "governed_denial", "approved"))
cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot_id,))
conn.commit()

print("13) REWORK PROVENANCE — exact + JOB-LESS (no fabricated job/provider)")
before_head = max(x["revision"] for x in rows())
RW.rework_one(E.load_config(), "topic", slot_id, "خلي الزاوية أوضح", actor="khal")
after = rows()
new_head = max(x["revision"] for x in after)
check("rework appended a new revision", new_head, before_head + 1)
cur.execute("""SELECT p.job_id, p.effective_actor, p.resolved_provider, p.execution_route,
                      p.variant_of_topic_id FROM topic_provenance p JOIN topic t ON t.topic_id=p.topic_id
               WHERE t.slot_id=%s AND t.revision=%s""", (slot_id, new_head))
prov = cur.fetchone()
check("rework provenance recorded", prov is not None, True)
check("rework provenance job_id is NULL (no fabricated job)", prov["job_id"], None)
check("rework provenance effective_actor truthful", prov["effective_actor"], "khal")
check("rework provenance execution_route = manual_rework", prov["execution_route"], "manual_rework")
check("rework provenance resolved_provider = stub (actual, not fabricated)", prov["resolved_provider"], "stub")
check("rework provenance variant_of set (base lineage)", prov["variant_of_topic_id"] is not None, True)


def _prov_count():
    cur.execute("SELECT count(*) AS c FROM topic_provenance p JOIN topic t ON t.topic_id=p.topic_id WHERE t.slot_id=%s", (slot_id,))
    return cur.fetchone()["c"]


print("13b) REWORK REPLAY (P1-4) — the WHOLE restore+rework is idempotent: one revision, one provenance")
h0 = max(x["revision"] for x in rows())
body_rw = {"artifact": "topic", "revision": h0, "comment": "وضّح أكثر", "expected_revision": h0, "idempotency_key": "RWK-IDEM-1"}
st_r1, b_r1 = S.POST(f"/slots/{slot_id}/rework_from", body_rw, headers=S.AUTH_KHAL)
check("rework_from first -> reworking", (st_r1, b_r1.get("reworking")), (200, True))
for _ in range(80):
    if max(x["revision"] for x in rows()) >= h0 + 2:      # restore(h0+1) + generated(h0+2)
        break
    time.sleep(0.5)
after_first = max(x["revision"] for x in rows())
prov_after_first = _prov_count()
st_r2, b_r2 = S.POST(f"/slots/{slot_id}/rework_from", body_rw, headers=S.AUTH_KHAL)
check("rework_from REPLAY same key -> reworking:false, idempotent (no second generation started)",
      (st_r2, b_r2.get("reworking"), b_r2.get("idempotent_replay")), (200, False, True))
time.sleep(1.5)                                            # a wrongly-started thread would append here
check("replay minted NO additional revision", max(x["revision"] for x in rows()), after_first)
check("replay minted NO additional provenance", _prov_count(), prov_after_first)

print("14) HTTP — truthful request_change + approve exact-revision CAS (P1-1, P1-2)")
if slot2:
    stq, bq = S.POST(f"/slots/{slot2}/request_change", {"comment": "clarify the angle"}, headers=S.AUTH_KHAL)
    check("request_change -> decision_recorded, committed:false (truthful, no phantom transition)",
          (stq, bq.get("decision_recorded"), bq.get("committed")), (200, True, False))
    stq0, _ = S.POST(f"/slots/{slot2}/request_change", {"comment": ""}, headers=S.AUTH_KHAL)
    check("request_change without comment -> 400", stq0, 400)
    h2 = S.GET(f"/slots/{slot2}/topic_item")["head_revision"]
    st_stale, b_stale = S.POST(f"/slots/{slot2}/approve", {"expected_revision": h2 - 1}, headers=S.AUTH_KHAL)
    check("STALE approve -> 409 stale_revision (no decision recorded)", (st_stale, _err(b_stale).get("error")), (409, "stale_revision"))
    st_ok, b_ok = S.POST(f"/slots/{slot2}/approve", {"expected_revision": h2}, headers=S.AUTH_KHAL)
    check("EXACT approve -> decision_recorded, pins that revision", (st_ok, b_ok.get("decision_recorded"), b_ok.get("approved_revision")), (200, True, h2))
    cur.execute("SELECT revision FROM gate_decision WHERE slot_id=%s AND decision='approve'", (slot2,))
    recorded = [r["revision"] for r in cur.fetchall()]
    check("EXACT revision pinned in an approval decision; STALE revision never recorded",
          (h2 in recorded, (h2 - 1) in recorded), (True, False))

print("15) BOUNDED INTERLEAVING RACE (P1-A) — concurrent edit vs approve is atomic: no stale approval persisted")
conn.rollback()                                             # fresh snapshot for the assertions below
Hr = max(x["revision"] for x in rows())
lockconn = S.db()
lc = lockconn.cursor()
lc.execute("SELECT 1 FROM slot WHERE slot_id=%s FOR UPDATE", (slot_id,))    # hold the slot lock = an in-flight edit
_res = {}


def _raced_approve():
    _res["st"], _res["b"] = S.POST(f"/slots/{slot_id}/approve", {"expected_revision": Hr}, headers=S.AUTH_KHAL)


_th = threading.Thread(target=_raced_approve)
_th.start()
time.sleep(1.0)                                             # the approve is now BLOCKED on decide()'s FOR UPDATE
E.edit_revision(lockconn, slot_id, "topic", "text_ar", "raced-edit", actor="khal")  # edit under the held lock -> head Hr+1, commit releases
lockconn.close()
_th.join(timeout=15)
check("raced approve (expected the pre-edit head) -> 409 stale_revision (CAS saw the concurrent edit atomically)",
      (_res.get("st"), _err(_res.get("b", {})).get("error")), (409, "stale_revision"))
conn.rollback()
cur.execute("SELECT count(*) AS c FROM gate_decision WHERE slot_id=%s AND decision='approve' AND revision=%s", (slot_id, Hr))
check("NO topic approval decision persisted for the raced (now-superseded) revision", cur.fetchone()["c"], 0)

print("16) DURABLE RECOVERY (P1-B) — crash AFTER restore: the operation resumes to exactly one generated revision")
conn.rollback()
h16 = max(x["revision"] for x in rows())
prov16 = _prov_count()
began = E.begin_rework_operation(conn, slot_id, h16, "recover me", "khal", "RCV-1", expected_revision=h16)
check("begin -> start; restore appended under a durable operation owner", (began["action"], began["restored_revision"]), ("start", h16 + 1))
# NO worker ran == a crash right after restore. The operation is durably recoverable.
conn.rollback()
check("the stranded (un-generated) operation is recoverable", began["op_id"] in E.recoverable_rework_operations(conn), True)
RW.run_rework_operation(E.load_config(), began["op_id"])          # recovery re-drives the worker
conn.rollback()
cur.execute("SELECT state, generated_revision FROM rework_operation WHERE op_id=%s", (began["op_id"],))
oprow = cur.fetchone()
check("after recovery the operation is completed with a generated revision", (oprow["state"], oprow["generated_revision"] is not None), ("completed", True))
check("recovery produced EXACTLY ONE generated revision (restore h+1, generated h+2)", max(x["revision"] for x in rows()), h16 + 2)
check("recovery produced EXACTLY ONE provenance row", _prov_count() - prov16, 1)
b_dedupe = E.begin_rework_operation(conn, slot_id, h16, "recover me", "khal", "RCV-1", expected_revision=h16)
check("replay of a COMPLETED operation -> dedupe (no new work)", b_dedupe["action"], "dedupe")
check("dedupe replay minted NO further revision", max(x["revision"] for x in rows()), h16 + 2)

print("17) CONCURRENT REPLAY (P1-B) — two workers on ONE operation: exactly one generated revision/provenance")
conn.rollback()
h17 = max(x["revision"] for x in rows())
prov17 = _prov_count()
b17 = E.begin_rework_operation(conn, slot_id, h17, "concurrent", "khal", "CNC-1", expected_revision=h17)
check("begin -> start (restore h17+1)", (b17["action"], b17["restored_revision"]), ("start", h17 + 1))
_opid = b17["op_id"]


def _worker():
    try:
        RW.run_rework_operation(E.load_config(), _opid)
    except Exception:  # noqa: BLE001
        pass


_ts = [threading.Thread(target=_worker) for _ in range(3)]
[t.start() for t in _ts]
[t.join(timeout=25) for t in _ts]
conn.rollback()
check("concurrent workers produced EXACTLY ONE generated revision (only one claim won)", max(x["revision"] for x in rows()), h17 + 2)
check("concurrent workers produced EXACTLY ONE new provenance row", _prov_count() - prov17, 1)
cur.execute("SELECT state, generated_revision FROM rework_operation WHERE op_id=%s", (_opid,))
o17 = cur.fetchone()
check("the operation is completed exactly once", (o17["state"], o17["generated_revision"]), ("completed", h17 + 2))

print("18) LEASE HEARTBEAT (P1-1) — a rework exceeding the nominal lease stays singly owned via renewal")
conn.rollback()
cur.execute("INSERT INTO rework_operation (slot_id, idempotency_key, base_revision, comment, actor, state) VALUES (%s,'HB-1',1,'hb','khal','queued') RETURNING op_id", (slot2,))
op18 = cur.fetchone()["op_id"]
conn.commit()
c18 = E.claim_rework_operation(conn, op18, lease_seconds=2)
check("claim mints an ownership token, state=running", (c18["claim_token"] is not None, c18["state"]), (True, "running"))
tok18 = c18["claim_token"]
for _ in range(3):
    time.sleep(1.0)
    check("heartbeat (fenced by token) renews ownership across the 2s nominal lease", E.heartbeat_rework_operation(conn, op18, tok18, lease_seconds=2), True)
conn.rollback()
check("op NOT recoverable after > nominal lease elapsed — heartbeat kept it singly owned", op18 in E.recoverable_rework_operations(conn), False)
cur.execute("DELETE FROM rework_operation WHERE op_id=%s", (op18,))
conn.commit()

print("19) OWNERSHIP FENCING (P1-1) — a stale worker cannot heartbeat/complete/fail after reassignment")
cur.execute("INSERT INTO rework_operation (slot_id, idempotency_key, base_revision, comment, actor, state) VALUES (%s,'SF-1',1,'sf','khal','queued') RETURNING op_id", (slot2,))
op19 = cur.fetchone()["op_id"]
conn.commit()
tok1 = E.claim_rework_operation(conn, op19, lease_seconds=60)["claim_token"]
cur.execute("UPDATE rework_operation SET lease_expires_at=now() - interval '1 minute' WHERE op_id=%s", (op19,))
conn.commit()
tok2 = E.claim_rework_operation(conn, op19, lease_seconds=60)["claim_token"]   # a NEW worker reclaims the expired op
check("re-claim after lease expiry mints a DIFFERENT ownership token", tok2 != tok1, True)
check("stale worker (old token) cannot HEARTBEAT", E.heartbeat_rework_operation(conn, op19, tok1), False)
raises("stale worker cannot COMPLETE (fenced -> raises, rolls back its generation)", lambda: E.complete_rework_operation(conn.cursor(), op19, tok1, 999), E.GateError)
conn.rollback()
E.fail_rework_operation(conn, op19, tok1, "stale")            # stale fail -> no-op
conn.rollback()
cur.execute("SELECT state FROM rework_operation WHERE op_id=%s", (op19,))
check("stale fail did NOT flip the reassigned op's state", cur.fetchone()["state"], "running")
E.complete_rework_operation(conn.cursor(), op19, tok2, 998)   # the CURRENT owner completes fine
conn.commit()
cur.execute("SELECT state, generated_revision FROM rework_operation WHERE op_id=%s", (op19,))
r19 = cur.fetchone()
check("the current owner (new token) completes exactly once", (r19["state"], r19["generated_revision"]), ("completed", 998))
cur.execute("DELETE FROM rework_operation WHERE op_id=%s", (op19,))
conn.commit()

print("20) SOURCE FENCE (P1-2) — an active rework fences competing edit/restore/decision (source cannot silently change)")
conn.rollback()
h20 = max(x["revision"] for x in rows())
prov20 = _prov_count()
b20 = E.begin_rework_operation(conn, slot_id, h20, "src", "khal", "SRC-1", expected_revision=h20)
check("begin -> active op restored to head (owns the item)", (b20["action"], b20["restored_revision"]), ("start", h20 + 1))
raises("EDIT is fenced while a rework is active (source cannot change)", lambda: E.edit_revision(conn, slot_id, "topic", "text_ar", "sneaky", actor="khal"), E.GovernedDenial, reason="rework_active")
raises("RESTORE is fenced while a rework is active", lambda: E.restore_revision(conn, slot_id, "topic", 1, actor="khal"), E.GovernedDenial, reason="rework_active")
sta20, ba20 = S.POST(f"/slots/{slot_id}/drop", {"reason": "x"}, headers=S.AUTH_KHAL)
check("DROP decision is fenced while a rework is active", (sta20, _err(ba20).get("reason")), (409, "rework_active"))
RW.run_rework_operation(E.load_config(), b20["op_id"])       # worker completes the rework -> exactly one generated revision
conn.rollback()
check("rework produced EXACTLY ONE generated revision from the RESTORED source (h20+2)", max(x["revision"] for x in rows()), h20 + 2)
check("rework produced EXACTLY ONE provenance row", _prov_count() - prov20, 1)
check("after completion the item is UN-fenced (edit allowed again)", E.edit_revision(conn, slot_id, "topic", "text_ar", "now ok", actor="khal")["new_revision"], h20 + 3)

print("21) WORKER-LEVEL LEASE + HEARTBEAT RECONNECT (P1-1/#5) — heartbeat env UNSET, interval derived from runtime lease")
conn.rollback()
h21 = max(x["revision"] for x in rows())
prov21 = _prov_count()
b21 = E.begin_rework_operation(conn, slot_id, h21, "long-running", "khal", "LONG-1", expected_revision=h21)
opid21 = b21["op_id"]
# #5 — leave TANAGHOM_REWORK_HEARTBEAT_SECONDS UNSET so the beat interval must be DERIVED. Pin the
# import-time constant to a large, DIVERGENT value (120) to prove the derivation tracks the RUNTIME lease,
# not the frozen import default: under the old code the interval would be max(1,120/4)=30s > the 3s lease
# and the op would be wrongly reclaimed; the fix derives max(1, runtime_lease/4)=1s, staying ahead of expiry.
_saved_import_lease = E._REWORK_LEASE_SECONDS
E._REWORK_LEASE_SECONDS = 120
os.environ.pop("TANAGHOM_REWORK_HEARTBEAT_SECONDS", None)
for _k, _v in {"TANAGHOM_REWORK_LEASE_SECONDS": "3",
               "TANAGHOM_REWORK_TEST_DELAY_SECONDS": "5", "TANAGHOM_REWORK_TEST_HB_KILL": "2"}.items():
    os.environ[_k] = _v
# runtime lease resolution wins over the divergent import-time constant, and the derived beat stays ahead of expiry
check("runtime-resolved lease (3) wins over the frozen import-time constant (120)",
      (E._resolve_rework_lease_seconds(), E._REWORK_LEASE_SECONDS), (3, 120))
_derived_interval = max(1, E._resolve_rework_lease_seconds() / 4)
check("derived heartbeat interval (1.0s) stays strictly AHEAD of the runtime lease (3s) — old code would be 30s",
      (_derived_interval, _derived_interval < 3), (1.0, True))
w1 = {}


def _worker1():
    try:
        w1["r"] = RW.run_rework_operation(E.load_config(), opid21)
    except Exception as e:  # noqa: BLE001
        w1["err"] = e


th1 = threading.Thread(target=_worker1)
th1.start()
time.sleep(4.0)   # > the 3s nominal lease: only heartbeat renewal (incl. a reconnect after the kill) keeps it owned
w2 = RW.run_rework_operation(E.load_config(), opid21)   # a competing recovery worker attempts to reclaim mid-generation
check("competing worker canNOT reclaim a heartbeat-renewed op past the nominal lease (single ownership)", w2, None)
conn.rollback()
cur.execute("SELECT state, generated_revision FROM rework_operation WHERE op_id=%s", (opid21,))
mid = cur.fetchone()
check("op still RUNNING + singly owned mid-generation (heartbeat reconnected after the induced kill)",
      (mid["state"], mid["generated_revision"]), ("running", None))
th1.join(timeout=25)
E._REWORK_LEASE_SECONDS = _saved_import_lease
for _k in ("TANAGHOM_REWORK_LEASE_SECONDS", "TANAGHOM_REWORK_HEARTBEAT_SECONDS",
           "TANAGHOM_REWORK_TEST_DELAY_SECONDS", "TANAGHOM_REWORK_TEST_HB_KILL"):
    os.environ.pop(_k, None)
conn.rollback()
check("worker 1 completed EXACTLY ONE generated revision from the restored source (h21+2)", max(x["revision"] for x in rows()), h21 + 2)
check("worker-level rework produced EXACTLY ONE provenance row", _prov_count() - prov21, 1)
cur.execute("SELECT state, generated_revision FROM rework_operation WHERE op_id=%s", (opid21,))
fin = cur.fetchone()
check("the operation completed exactly once", (fin["state"], fin["generated_revision"]), ("completed", h21 + 2))

# cleanup this proof's round (provenance FKs topic, so delete it first)
cur.execute("DELETE FROM rework_operation WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
cur.execute("DELETE FROM topic_provenance WHERE topic_id IN (SELECT topic_id FROM topic WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s))", (rid,))
cur.execute("DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
cur.execute("DELETE FROM topic WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
cur.execute("DELETE FROM generation_job WHERE round_id=%s", (rid,))
conn.commit()

print()
if FAILS:
    print("FAILURES:", FAILS)
    raise SystemExit(1)
print("=" * 62)
print("ALL TOPIC-ITEM GOVERNANCE (#313 B1 eligibility + B2 CAS/idempotency) CHECKS PASSED")
print("=" * 62)
