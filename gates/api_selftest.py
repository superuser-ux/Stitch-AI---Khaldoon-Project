"""API-path proof (coverage gap) — drives the LIVE HTTP API exactly as the dashboard does
(open -> POST decisions -> resolve -> GET) on an isolated round, and asserts DB + API state.
gates/selftest.py only hits the engine in-process; this catches divergences that can only appear
over the FastAPI path, AND proves the closed co-creation loop end to end:

  request_change -> CHANGES_REQUESTED (a dedicated 'awaiting rework' state) -> excluded from any
  new gate + NOT approvable (integrity guard) -> the rework trigger regenerates v2 (the reviewer
  comment IS the rework directive; v2 carries a change-summary) -> back to TOPIC_PROPOSED -> approvable.

The rework REGENERATION is proven in-process with the deterministic stub writer
(TANAGHOM_WRITER_STUB=1) so the assertion is reliable without the live LLM; the HTTP trigger
endpoint is proven for detection/wiring (dry_run).

Run (container on the tanaghom network):
  docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
    -e API_BASE=http://tanaghom-gateapi:8000 -v "$PWD":/work -w /work python:3.12-slim \
    bash -lc "pip install -q -r gates/requirements.txt -r agents/requirements.txt && python gates/api_selftest.py"
"""
import importlib
import json
import os
import sys
import hashlib
import hmac
import urllib.error
import urllib.request

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
os.environ.setdefault("TANAGHOM_WRITER_STUB", "1")   # deterministic offline writer for the rework proof
import engine        # noqa: E402
import run_writers   # noqa: E402
import agent as A    # noqa: E402  (conversational agent — shared runtime, offline-tested here)
import contract as C  # noqa: E402


class ScriptLLM:
    """Offline stand-in for the agent's LLM. Each step is {"tool_calls": [...]} or {"text": "..."}.
    Matches agent.run's contract: llm.step(system, messages, tools)."""
    def __init__(self, plan):
        self.plan, self.i = plan, 0

    def step(self, system, messages, tools):
        s = self.plan[min(self.i, len(self.plan) - 1)]
        self.i += 1
        return s


API = os.environ.get("API_BASE", "http://localhost:8009")
PROXY_SECRET = os.environ.get("REVIEWER_PROXY_SECRET") or "dev-internal-reviewer-proxy-secret"
RID = "RAPI"
COMMENT = "خاطب الأب والأم مش بس الأم"      # a specific, directional rework instruction
SLOTS = [("RAPI-1", "P1_SELF", "1.1"), ("RAPI-2", "P2_RELATIONSHIPS", "2.1"),
         ("RAPI-3", "P3_PARENTING", "3.1"), ("RAPI-4", "P1_SELF", "1.2")]
FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} want={want}")
    if not ok:
        FAILS.append(label)


def _format_version_payload(active_version, *, weekly_count=None):
    production_rules = dict(active_version.get("production_rules") or {})
    planning = dict(production_rules.get("planning") or {})
    if weekly_count is None:
        planning.pop("weekly_count", None)
    else:
        planning["weekly_count"] = weekly_count
    production_rules["planning"] = planning
    return {
        "use_case": active_version.get("use_case"),
        "lens_fit": active_version.get("lens_fit") or [],
        "production_notes": active_version.get("production_notes"),
        "production_rules": production_rules,
        "platform_targets": active_version.get("platform_targets") or [],
    }


# --- HTTP (the dashboard's exact calls) ------------------------------------- #
def _signed(principal):
    sig = hmac.new(PROXY_SECRET.encode("utf-8"), principal.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"x-principal-id": principal, "x-principal-signature": sig}


AUTH_KHAL = _signed("khal")
AUTH_HUDA = _signed("huda")


def _req(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def GET(path, headers=None):
    return _req("GET", path, headers=headers)[1]


def POST(path, body, headers=None):
    return _req("POST", path, body, headers=headers)


def PUT(path, body, headers=None):
    return _req("PUT", path, body, headers=headers)


# --- DB ground truth -------------------------------------------------------- #
def db():
    return psycopg2.connect(host=os.environ.get("DB_HOST", "db"),
                            port=int(os.environ.get("DB_PORT", "5432")),
                            dbname=os.environ.get("DB_NAME", "tanaghom"),
                            user=os.environ.get("DB_USER", "tanaghom"),
                            password=os.environ["DB_PASSWORD"])


def slot_states(conn):
    cur = conn.cursor()
    cur.execute("SELECT slot_id, status FROM slot WHERE round_id=%s ORDER BY slot_id", (RID,))
    return dict(cur.fetchall())


def dump(conn, label):
    print(f"\n----- DB after {label} -----  slots: {slot_states(conn)}")


def teardown(conn):
    cur = conn.cursor()
    # #250 — sdam fixture rows are append-only/immutable BY DESIGN; bypass the guards transiently
    # for THIS isolated round's teardown only (their enforcement is proven in sdam_selftest).
    cur.execute("SET session_replication_role = replica")
    cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id LIKE 'RAPI-%%')")
    cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id LIKE 'RAPI-%%'")
    cur.execute("SET session_replication_role = DEFAULT")
    cur.execute("DELETE FROM asset WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    for tbl in ("directive", "topic", "script"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RAPI-%%' OR entity_id IN "
                "(SELECT gate_id::text FROM gate g JOIN gate_target t USING(gate_id) "
                " JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    cur.execute("DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM slot  WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()


def seed(conn):
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id)
                   VALUES (%s,'api-selftest',1,4,'["09:00"]','{}','{}','planning','selftest')""", (RID,))
    for sid, pillar, hcs in SLOTS:
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,topic_angle,hook_text,tenant_id)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','TOPIC_PROPOSED',1,
                       'الزاوية الأصلية','هوك أصلي',%s)""", (sid, RID, pillar, hcs, "selftest"))
        cur.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,
                       rationale_ar,rationale_en,hook_text,hook_type,revision,tenant_id)
                       VALUES (%s,%s,'L1',%s,1,'الزاوية الأصلية','سبب','reason','هوك أصلي',
                       'Painful Truth',1,%s)""", (sid, hcs, RID, "selftest"))
    conn.commit()


# --- the reproduction + the closed loop ------------------------------------- #
def main():
    conn = db()
    teardown(conn); seed(conn)
    print(f"seeded {RID}: {slot_states(conn)}  (API={API}, stub={os.environ.get('TANAGHOM_WRITER_STUB')})")

    # P) planner ratio-scaling — pure function, no DB
    print("\nP) planner ratio-scaling")
    from planner.plan_round import scale_distribution
    base = {"P1_SELF": 22, "P2_RELATIONSHIPS": 17, "P3_PARENTING": 9, "P4_WORK": 4, "P5_MEANING_ALLAH": 4}
    r56 = scale_distribution(base, 56)
    check("28x2: scaling reproduces the exact configured mix", r56, base)
    check("28x2: sums to 56", sum(r56.values()), 56)
    r6 = scale_distribution(base, 6)
    check("3x2: sums to exactly 6", sum(r6.values()), 6)
    check("3x2: every count is a non-negative int", all(isinstance(v, int) and v >= 0 for v in r6.values()), True)
    check("1x1: sums to 1", sum(scale_distribution(base, 1).values()), 1)
    r2 = scale_distribution(base, 2)   # tiny: total < #pillars
    check("1x2 tiny-run: sums to 2, no crash, no negatives", (sum(r2.values()), min(r2.values())), (2, 0))
    check("1x2 tiny-run: the two biggest pillars win the slots", (r2["P1_SELF"], r2["P2_RELATIONSHIPS"]), (1, 1))

    from planner.plan_round import effective_template, synth_post_times, get_template
    check("synth_post_times keeps configured 2-up times", synth_post_times(2, ["09:00", "20:00"]), ["09:00", "20:00"])
    check("synth_post_times spreads 3-up", len(synth_post_times(3, ["09:00", "20:00"])), 3)
    _, base_tmpl = get_template(engine.load_config(), None)
    et = effective_template(base_tmpl, 3, 2)
    check("effective_template totals to days*ppd", sum(et["pillar_distribution"].values()), 6)
    check("effective_template weekly totals to ppd*7", sum(et["format_distribution_weekly"].values()), 14)

    # Q) POST /rounds — parametric planning + cursor integrity across two rounds
    print("\nQ) POST /rounds")

    def _wipe_round(rid):
        c = conn.cursor()
        c.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (rid,))
        c.execute("DELETE FROM topic_provenance WHERE topic_id IN (SELECT topic_id FROM topic WHERE round_id=%s)", (rid,))
        c.execute("DELETE FROM generation_job WHERE round_id=%s", (rid,))
        for tbl in ("directive", "slot_approval", "slot_review", "asset", "topic", "script"):
            c.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid,))
        c.execute("DELETE FROM slot WHERE round_id=%s", (rid,))
        c.execute("DELETE FROM topic WHERE round_id=%s", (rid,))
        c.execute("DELETE FROM round WHERE round_id=%s", (rid,))
        c.execute("DELETE FROM audit_log WHERE entity_id=%s OR entity_id LIKE %s", (rid, rid + "-%"))
        conn.commit()

    # #276 — POST /rounds requires an exact format_mix over the baseline eligibility set (no fallback).
    _elig276 = [e["name"] for e in GET("/baseline-eligibility")["eligible"]]
    def _mix(total):
        m = {n: 0 for n in _elig276}; m[_elig276[0]] = total; return m
    st, b1 = POST("/rounds", {"days": 3, "posts_per_day": 2, "label": "selftest A", "format_mix": _mix(6)})
    check("POST /rounds returns 200", st, 200)
    r1 = b1["round_id"]
    check("planned round has days*ppd = 6 slots", b1["total"], 6)
    cur0 = conn.cursor(); cur0.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status='RESERVED'", (r1,))
    check("all 6 slots are RESERVED", cur0.fetchone()[0], 6); cur0.close()
    st2, b2 = POST("/rounds", {"days": 2, "posts_per_day": 2, "format_mix": _mix(4)})
    r2 = b2["round_id"]
    check("second round is a distinct id", r2 != r1, True)
    cur0 = conn.cursor(); cur0.execute("SELECT label FROM round WHERE round_id=%s", (r2,))
    check("unlabeled round gets a dynamic fallback label", cur0.fetchone()[0], f"2-day run {r2} (2/day)"); cur0.close()
    cur0 = conn.cursor(); cur0.execute("SELECT count(*) FROM slot WHERE round_id IN (%s,%s)", (r1, r2))
    check("both rounds planned without error (10 slots total)", cur0.fetchone()[0], 10); cur0.close()
    st3, _ = POST("/rounds", {"days": 0, "posts_per_day": 2})
    check("POST /rounds rejects days < 1 (422)", st3, 422)
    # extremes: upper bounds cap the planning grid so a hostile/typo input can't drive unbounded work
    check("POST /rounds rejects days over the cap (422)", POST("/rounds", {"days": 100000, "posts_per_day": 2})[0], 422)
    check("POST /rounds rejects posts_per_day over the cap (422)", POST("/rounds", {"days": 3, "posts_per_day": 100})[0], 422)
    # planner normalization guards (pure, no DB): degenerate distributions must never crash or go negative
    from planner.plan_round import scale_distribution, even_spread, synth_post_times
    check("scale_distribution: all-zero weights -> zeros", scale_distribution({"a": 0, "b": 0}, 14), {"a": 0, "b": 0})
    check("scale_distribution: total < #keys sums to total (no negatives)", sum(scale_distribution({"a": 1, "b": 1, "c": 1}, 2).values()), 2)
    check("scale_distribution: total 0 -> zeros", scale_distribution({"a": 3, "b": 1}, 0), {"a": 0, "b": 0})
    check("even_spread: empty -> []", even_spread([]), [])
    check("synth_post_times: ppd=1 -> single 09:00", synth_post_times(1, ["09:00", "13:00"]), ["09:00"])
    _wipe_round(r1); _wipe_round(r2)

    # #276 — baseline eligibility policy + immutable round snapshot over HTTP.
    pol276 = GET("/baseline-eligibility")
    e276 = [e["name"] for e in pol276["eligible"]]
    check("#276 GET /baseline-eligibility exposes a versioned policy + eligible frameworks",
          (pol276["policy"].get("generation") is not None, len(e276) >= 1), (True, True))
    st276, r276 = POST("/rounds", {"days": 3, "posts_per_day": 2, "label": "276 http mix",
                                   "format_mix": {**{n: 0 for n in e276}, e276[0]: 6}})
    check("#276 POST /rounds accepts an exact format_mix over the baseline eligibility set", st276, 200)
    check("#276 POST /rounds rejects a format_mix framework outside the eligibility set (422)",
          POST("/rounds", {"days": 1, "posts_per_day": 2, "format_mix": {"Not Eligible": 2}})[0], 422)
    snap276 = GET(f"/rounds/{r276['round_id']}/policy-snapshot")
    check("#276 round policy-snapshot pins policy gen + exact mix + selected version IDs",
          (snap276["baseline_generation"] == pol276["policy"]["generation"],
           snap276["format_mix"].get(e276[0]), bool(snap276["selected_version_ids"].get(e276[0]))),
          (True, 6, True))
    _wipe_round(r276["round_id"])

    # R) generation jobs — plan, approve schedule (status), generate topics, poll to done (stub writer)
    print("\nR) generation jobs")
    import time as _t
    _, rg = POST("/rounds", {"days": 2, "posts_per_day": 2, "format_mix": _mix(4)})   # 4 RESERVED slots
    rgid = rg["round_id"]
    _, gs = POST("/gates", {"stage": "schedule_review", "round_id": rgid}, headers=AUTH_KHAL)
    POST(f"/gates/{gs['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"}, headers=AUTH_KHAL)
    POST(f"/gates/{gs['gate_id']}/resolve", {}, headers=AUTH_KHAL)
    # #332 — these rounds are AUTOMATIC (default entry_mode): generation is dispatched at Schedule
    # RESOLVE, and the MANUAL /generate endpoint now requires a signed principal (unsigned -> 401) and
    # is a typed automatic-mode DENIAL for an automatic round (even for the eligible approver khal).
    # The auto-dispatched job still completes; the poll below proves the automatic flow end to end.
    stg, jb = POST(f"/rounds/{rgid}/stages/topic_review/generate", {}, headers=AUTH_KHAL)
    check("#332 manual generate on an AUTOMATIC round is a typed automatic-mode denial (409)", stg, 409)
    check("#332 unsigned manual generate is refused before target disclosure (401)",
          POST(f"/rounds/{rgid}/stages/topic_review/generate", {})[0], 401)
    # Poll THROUGH the non-terminal phases (queued | awaiting_trigger | running) and stop only on an
    # explicit terminal phase (completed | failed | partial). Breaking on `!= running` would let an
    # initial `queued` observation terminate the poll before the durable job runs (#312 Codex BLOCK).
    final = None
    for _ in range(120):
        rm = GET(f"/rounds/{rgid}/generation")
        if rm["phase"] in ("completed", "failed", "partial"):
            final = rm
            break
        _t.sleep(0.5)
    else:
        final = rm   # timed out non-terminal — carry the last observation so the assertion fails truthfully
    check("topic generation read model reaches completed", final and final["phase"], "completed")
    check("topic generation read model counts generated slots", final["counts"]["generated"], 4)
    cur0 = conn.cursor(); cur0.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED'", (rgid,))
    check("all 4 slots generated -> TOPIC_PROPOSED", cur0.fetchone()[0], 4); cur0.close()
    stg2, _ = POST(f"/rounds/{rgid}/stages/topic_review/generate", {}, headers=AUTH_KHAL)
    check("#332 re-generate on an automatic round stays a typed automatic-mode denial (409)", stg2, 409)

    _, rnf = POST("/rounds", {"days": 2, "posts_per_day": 2, "format_mix": _mix(4)})
    rnfid = rnf["round_id"]
    _, gs2 = POST("/gates", {"stage": "schedule_review", "round_id": rnfid}, headers=AUTH_KHAL)
    POST(f"/gates/{gs2['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"}, headers=AUTH_KHAL)
    POST(f"/gates/{gs2['gate_id']}/resolve", {}, headers=AUTH_KHAL)
    cur0 = conn.cursor()
    cur0.execute("DELETE FROM generation_job WHERE round_id=%s AND stage='topic'", (rnfid,))
    conn.commit(); cur0.close()
    # #332 — with the canonical job deleted, a signed eligible approver gets the COARSE
    # authorization-safe denial (a missing target is indistinguishable from a non-participant; the
    # endpoint never leaks target existence). Unsigned still fails authentication first (401).
    st_nf, _body_nf = POST(f"/rounds/{rnfid}/stages/topic_review/generate", {}, headers=AUTH_KHAL)
    check("#332 no canonical Stage 2A job -> coarse authorization-safe denial (403)", st_nf, 403)
    check("#332 unsigned generate refused before target disclosure (401)",
          POST(f"/rounds/{rnfid}/stages/topic_review/generate", {})[0], 401)

    check("unknown job id -> 404", _req("GET", "/jobs/does-not-exist")[0], 404)
    _wipe_round(rgid)
    _wipe_round(rnfid)

    # F) #134 run-level funnel (count contract #131 Slice B) — I5 conservation on the
    #    deterministic 7d×2 = 14 repro (the #47 investigation shape), end to end over HTTP.
    print("\nF) run-level funnel (#134 / contract #131 I5)")

    def _funnel_conserves(f, label):
        for s in f["stages"]:
            check(f"funnel[{label}] {s['stage']}: entered = in+awaiting+dropped+advanced",
                  s["entered"], s["in_stage"] + s["awaiting"] + s["dropped"] + s["advanced"])
        for a, b in zip(f["stages"], f["stages"][1:]):
            check(f"funnel[{label}] entered({b['stage']}) == advanced({a['stage']})",
                  b["entered"], a["advanced"])
        check(f"funnel[{label}] every slot mapped (unmapped empty)", f["unmapped"], {})
        check(f"funnel[{label}] first stage entered == total",
              f["stages"][0]["entered"] if f["stages"] else None, f["total"])

    _, rf = POST("/rounds", {"days": 7, "posts_per_day": 2, "label": "funnel repro", "format_mix": _mix(14)})
    rfid = rf["round_id"]
    f0 = GET(f"/rounds/{rfid}/funnel")
    check("funnel[planned] 7d×2 -> total 14", f0["total"], 14)
    check("funnel[planned] schedule holds all 14 (in_stage)", f0["stages"][0]["in_stage"], 14)
    check("funnel[planned] topics not entered yet", f0["stages"][1]["entered"], 0)
    _funnel_conserves(f0, "planned")
    # approve the whole schedule through the real gate flow
    _, gs = POST("/gates", {"stage": "schedule_review", "round_id": rfid}, headers=AUTH_KHAL)
    POST(f"/gates/{gs['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"}, headers=AUTH_KHAL)
    POST(f"/gates/{gs['gate_id']}/resolve", {}, headers=AUTH_KHAL)
    f1 = GET(f"/rounds/{rfid}/funnel")
    check("funnel[schedule-approved] topics entered == schedule advanced == 14",
          (f1["stages"][1]["entered"], f1["stages"][0]["advanced"]), (14, 14))
    _funnel_conserves(f1, "schedule-approved")
    # generate topics (stub writer) and review: park 1 (request_change), drop 1, approve 12
    _, jbf = POST(f"/rounds/{rfid}/stages/topic_review/generate", {})
    # Poll THROUGH queued | awaiting_trigger | running; stop only on terminal completed | failed | partial.
    jfinal = None
    for _ in range(240):
        rm = GET(f"/rounds/{rfid}/generation")
        if rm["phase"] in ("completed", "failed", "partial"):
            jfinal = rm
            break
        _t.sleep(0.5)
    else:
        jfinal = rm   # timed out non-terminal — carry the last observation so the assertion fails truthfully
    check("funnel repro: topic generation read model reaches completed", jfinal and jfinal["phase"], "completed")
    check("funnel repro: topic generation read model counts generated slots", jfinal["counts"]["generated"], 14)
    cur0 = conn.cursor(); cur0.execute("SELECT slot_id FROM slot WHERE round_id=%s ORDER BY slot_id", (rfid,))
    fids = [r[0] for r in cur0.fetchall()]; cur0.close()
    _, gt = POST("/gates", {"stage": "topic_review", "round_id": rfid}, headers=AUTH_KHAL)
    POST(f"/gates/{gt['gate_id']}/decide", {"approver_id": "khal", "decision": "request_change",
                                            "slot_ids": [fids[0]], "notes": "غيّر الزاوية"}, headers=AUTH_KHAL)
    POST(f"/gates/{gt['gate_id']}/decide", {"approver_id": "khal", "decision": "reject",
                                            "slot_ids": [fids[1]]}, headers=AUTH_KHAL)
    POST(f"/gates/{gt['gate_id']}/decide", {"approver_id": "khal", "decision": "approve",
                                            "slot_ids": fids[2:]}, headers=AUTH_KHAL)
    POST(f"/gates/{gt['gate_id']}/resolve", {}, headers=AUTH_KHAL)
    f2 = GET(f"/rounds/{rfid}/funnel")
    tf = next(s for s in f2["stages"] if s["stage"] == "topic_review")
    check("funnel[post-review] topic lanes: 0 in / 1 awaiting / 1 dropped / 12 advanced",
          (tf["in_stage"], tf["awaiting"], tf["dropped"], tf["advanced"]), (0, 1, 1, 12))
    check("funnel[post-review] scripts entered == topic advanced == 12",
          next(s for s in f2["stages"] if s["stage"] == "script_review")["entered"], 12)
    check("funnel[post-review] total still 14 (nothing lost)", f2["total"], 14)
    _funnel_conserves(f2, "post-review")
    _wipe_round(rfid)

    # 0) GATE HYGIENE — open_gate idempotent + stage_state ignores ORPHAN/stale gates (isolated round)
    print("\n0) gate idempotency + orphan handling")
    c0 = conn.cursor()
    c0.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RIDEM')")
    for tbl in ("directive", "slot_approval", "topic", "slot"):
        c0.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE 'RIDEM-%%'")
    c0.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RIDEM-%%'")
    c0.execute("DELETE FROM round WHERE round_id='RIDEM'")
    c0.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,pillar_distribution,
                  format_distribution,status,tenant_id) VALUES ('RIDEM','idem',1,2,'["09:00"]','{}','{}','planning','selftest')""")
    for sid, p, h in (("RIDEM-1", "P1_SELF", "1.1"), ("RIDEM-2", "P2_RELATIONSHIPS", "2.1")):
        c0.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no,
                      topic_angle,hook_text,tenant_id) VALUES (%s,'RIDEM',1,'09:00',%s,%s,'L1','Painful Truth','TOPIC_PROPOSED',1,'a','h','selftest')""", (sid, p, h))
        c0.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,hook_text,hook_type,revision,tenant_id)
                      VALUES (%s,%s,'L1','RIDEM',1,'a','h','Painful Truth',1,'selftest')""", (sid, h))
    conn.commit(); c0.close()
    g1 = POST("/gates", {"stage": "topic_review", "round_id": "RIDEM", "actor": "khal"}, headers=AUTH_KHAL)[1]["gate_id"]
    g1b = POST("/gates", {"stage": "topic_review", "round_id": "RIDEM", "actor": "khal"}, headers=AUTH_KHAL)[1]["gate_id"]
    check("open_gate IDEMPOTENT — same round+stage returns ONE open gate", g1b, g1)
    # advance both targets via a slot-scoped gate, leaving g1 ORPHAN (its targets have moved on)
    gs = POST("/gates", {"stage": "topic_review", "round_id": "RIDEM", "slot_ids": ["RIDEM-1", "RIDEM-2"], "actor": "khal"}, headers=AUTH_KHAL)[1]["gate_id"]
    POST(f"/gates/{gs}/decide", {"approver_id": "khal", "decision": "approve", "slot_ids": ["RIDEM-1", "RIDEM-2"]}, headers=AUTH_KHAL)
    POST(f"/gates/{gs}/resolve", {"actor": "khal"}, headers=AUTH_KHAL)
    check("stage_state IGNORES the orphan open gate (not 'reviewing')",
          GET("/rounds/RIDEM/stages/topic_review/state")["state"] != "reviewing", True)
    c0 = conn.cursor(); c0.execute("SELECT status FROM gate WHERE gate_id=%s", (g1,))
    check("orphan gate auto-SUPERSEDED", c0.fetchone()[0], "superseded")
    c0.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RIDEM')")
    for tbl in ("directive", "slot_approval", "topic", "slot"):
        c0.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE 'RIDEM-%%'")
    c0.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RIDEM-%%'"); c0.execute("DELETE FROM round WHERE round_id='RIDEM'")
    conn.commit(); c0.close()

    # 0b) #265 GATE RECONCILIATION over HTTP — fail-closed while generation is incomplete (409 held,
    #     never 404), then bounded reconciliation heals a seeded-legacy partial gate on read.
    print("\n0b) #265 generated-slot -> review-gate convergence (HTTP)")
    cg = conn.cursor()

    def _wipe_265a():
        cw = conn.cursor()
        cw.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                   "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='R265A')")
        for tbl in ("directive", "slot_approval", "topic", "slot"):
            cw.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE 'R265A-%%'")
        cw.execute("DELETE FROM audit_log WHERE entity_id LIKE 'R265A-%%'")
        cw.execute("DELETE FROM round WHERE round_id='R265A'")
        conn.commit(); cw.close()

    _wipe_265a()
    cg.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                  pillar_distribution,format_distribution,status,tenant_id)
                  VALUES ('R265A','r265a',3,2,'["09:00"]','{}','{}','planning','selftest')""")
    for i, (p, h) in enumerate((("P1_SELF", "1.1"), ("P2_RELATIONSHIPS", "2.1"), ("P1_SELF", "1.2"),
                                ("P3_PARENTING", "3.1"), ("P2_RELATIONSHIPS", "2.2"), ("P1_SELF", "1.3")), 1):
        cg.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,
                      status,cycle_no,topic_angle,hook_text,tenant_id)
                      VALUES (%s,'R265A',%s,'09:00',%s,%s,'L1','Painful Truth',%s,1,'a','h','selftest')""",
                   (f"R265A-{i}", i, p, h, "TOPIC_PROPOSED" if i <= 2 else "SCHEDULE_APPROVED"))
    conn.commit()

    st_o, body_o = POST("/gates", {"stage": "topic_review", "round_id": "R265A", "actor": "khal"},
                        headers=AUTH_KHAL)
    check("#265 API: start_review 409-held while 4 slots still await generation",
          (st_o, "generation incomplete" in (body_o.get("detail") or "")), (409, True))
    ss_g = GET("/rounds/R265A/stages/topic_review/state")
    check("#265 API: stage stays generate with NO gate mid-generation (truthful counts)",
          (ss_g["state"], ss_g["gate_id"], ss_g["review_pending"], ss_g["pending_input"]),
          ("generate", None, 2, 4))

    # seeded legacy inconsistency (regression fixture): an open 2-target gate left behind
    cg.execute("SELECT rule_key, quorum FROM gate WHERE stage='topic_review' ORDER BY created_at DESC LIMIT 1")
    _pol = cg.fetchone()
    cg.execute("INSERT INTO gate (scope,stage,policy,rule_key,quorum,status) "
               "VALUES ('batch','topic_review','fixed',%s,%s,'open') RETURNING gate_id",
               (_pol[0] if _pol else "any", _pol[1] if _pol else "1"))
    gid265 = str(cg.fetchone()[0])
    cg.execute("INSERT INTO gate_target (gate_id,slot_id) VALUES (%s,'R265A-1'),(%s,'R265A-2')",
               (gid265, gid265))
    conn.commit()
    st_d, body_d = _req("GET", f"/gates/{gid265}")
    check("#265 API: gate READ is 409-held (never 404) while generation is incomplete",
          (st_d, "held until generation completes" in (body_d.get("detail") or "")), (409, True))
    st_dec, _ = POST(f"/gates/{gid265}/decide",
                     {"approver_id": "khal", "decision": "approve", "slot_ids": ["R265A-1"]},
                     headers=AUTH_KHAL)
    check("#265 API: decide is 409-held while generation is incomplete", st_dec, 409)
    st_res, _ = POST(f"/gates/{gid265}/resolve", {"actor": "khal"}, headers=AUTH_KHAL)
    check("#265 API: commit (resolve) is 409-held while generation is incomplete", st_res, 409)
    ss_h = GET("/rounds/R265A/stages/topic_review/state")
    check("#265 API: held legacy gate stays hidden with an operator-visible warning",
          (ss_h["gate_id"], any("held until generation completes" in w for w in ss_h["warnings"])),
          (None, True))

    # generation completes -> the SAME gate reconciles to the full population on read
    cg.execute("UPDATE slot SET status='TOPIC_PROPOSED' WHERE round_id='R265A'")
    conn.commit()
    ss_r = GET("/rounds/R265A/stages/topic_review/state")
    check("#265 API: after generation the legacy gate reconciles — state/gate/population agree",
          (ss_r["gate_id"], ss_r["in_review"], ss_r["review_pending"], ss_r["reconciliation_ok"]),
          (gid265, 6, 6, True))
    gd265 = GET(f"/gates/{gid265}")
    check("#265 API: reconciled gate serves ALL 6 targets over HTTP", len(gd265["targets"]), 6)
    cg.execute("SELECT count(*) FROM audit_log WHERE entity='gate' AND entity_id=%s "
               "AND action='gate_targets_reconciled'", (gid265,))
    check("#265 API: reconciliation audited exactly once", cg.fetchone()[0], 1)
    fun265 = GET("/rounds/R265A/funnel")
    check("#265 API: funnel agrees with the reconciled stage (topic in_stage=6)",
          next(s for s in fun265["stages"] if s["stage"] == "topic_review")["in_stage"], 6)
    cg.close()
    _wipe_265a()

    # 1) OPEN topic_review (4 targets)
    check("open gate rejects unsigned caller", POST("/gates", {"stage": "topic_review", "round_id": RID, "actor": "khal"})[0], 401)
    st, body = POST("/gates", {"stage": "topic_review", "round_id": RID, "actor": "khal"}, headers=AUTH_KHAL)
    check("open returns 200", st, 200)
    gid = body["gate_id"]
    check("API: open gate has 4 targets", GET(f"/gates?status=open&round={RID}")[0]["targets"], 4)
    gd = GET(f"/gates/{gid}")
    check("gate preserves raw rule_key", gd["rule_key"], "any")
    check("gate snapshots assignments", [a["assignment_key"] for a in gd["assignments"]], ["khal"])
    st_mm, body_mm = POST("/gates", {"stage": "topic_review", "round_id": RID, "actor": "huda"},
                          headers=AUTH_KHAL)
    check("signed proxy rejects body actor mismatch", st_mm, 400)
    check("...open mismatch mentions mismatch", "mismatch" in (body_mm.get("detail") or ""), True)
    myq = GET("/me/pending-approvals", headers=AUTH_KHAL)
    rapi_q = [q for q in myq if q.get("round_id") == RID and q.get("stage") == "topic_review"]
    check("trusted principal sees the RAPI approval queue", len(rapi_q), 1)
    check("...queue reports all 4 remaining targets", rapi_q[0]["remaining_targets"], 4)
    workflows = GET("/workflows", headers=AUTH_KHAL)
    check("workflow catalog exposes an active version", bool(workflows["active_version"]), True)
    check("workflow admin rights surface for khal", workflows["can_administer"], True)
    methodologies = GET("/methodologies", headers=AUTH_KHAL)
    check("methodology catalog exposes an active version", bool(methodologies["active_version"]), True)
    check("active methodology version carries all 42 HCS rows", methodologies["active_version"]["counts"]["hcs"], 42)
    check("methodology catalog surfaces admin rights for khal", methodologies["can_administer"], True)
    active_methodology = GET("/methodology-versions/active")
    check("active methodology endpoint returns the same active version",
          active_methodology["version_id"], methodologies["active_version"]["version_id"])
    methodology_key = methodologies["methodologies"][0]["methodology_key"]
    st_mdraft, methodology_draft = POST(f"/methodologies/{methodology_key}/versions/draft", {},
                                        headers=AUTH_KHAL)
    check("methodology draft clone endpoint returns 200", st_mdraft, 200)
    st_msave, methodology_saved = PUT(f"/methodology-versions/{methodology_draft['version_id']}", {
        "notes": "api selftest methodology draft",
    }, headers=AUTH_KHAL)
    check("methodology draft update endpoint returns 200", st_msave, 200)
    check("methodology draft update persists notes", methodology_saved["notes"], "api selftest methodology draft")
    st_mact, methodology_active = POST(f"/methodology-versions/{methodology_draft['version_id']}/activate", {},
                                       headers=AUTH_KHAL)
    check("methodology activate endpoint returns 200", st_mact, 200)
    check("methodology activate endpoint marks the draft active", methodology_active["status"], "active")
    check("active methodology endpoint points at the newly activated version",
          GET("/methodology-versions/active")["version_id"], methodology_draft["version_id"])
    format_catalog = GET("/content-formats", headers=AUTH_KHAL)
    check("content-format catalog exposes seeded platforms", sorted(p["platform_key"] for p in format_catalog["platforms"]),
          ["instagram", "telegram"])
    check("content-format catalog exposes the managed bootstrap content types", len(format_catalog["formats"]), 4)
    format_key = format_catalog["formats"][0]["format_key"]
    st_fdraft, format_draft = POST(f"/content-formats/{format_key}/versions/draft", {}, headers=AUTH_KHAL)
    check("content-format draft clone endpoint returns 200", st_fdraft, 200)
    st_fsave, format_saved = PUT(f"/content-format-versions/{format_draft['version_id']}", {
        "use_case": "api selftest use case",
        "lens_fit": ["L1", "L5"],
        "production_notes": "api selftest production notes",
        "platform_targets": ["instagram", "telegram"],
    }, headers=AUTH_KHAL)
    check("content-format draft update endpoint returns 200", st_fsave, 200)
    check("content-format draft update persists use case", format_saved["use_case"], "api selftest use case")
    st_fact, format_active = POST(f"/content-format-versions/{format_draft['version_id']}/activate", {},
                                  headers=AUTH_KHAL)
    check("content-format activate endpoint returns 200", st_fact, 200)
    check("content-format activate endpoint marks the draft active", format_active["status"], "active")
    updated_formats = GET("/content-formats", headers=AUTH_KHAL)
    format_row = next(row for row in updated_formats["formats"] if row["format_key"] == format_key)
    check("content-format catalog points to the newly activated version",
          format_row["active_version"]["version_id"], format_draft["version_id"])
    st_after_formats, planned_after_formats = POST("/rounds", {"days": 1, "posts_per_day": 2, "label": "selftest post-format activation", "format_mix": _mix(2)})
    check("POST /rounds still works after content-format activation", st_after_formats, 200)
    _wipe_round(planned_after_formats["round_id"])
    st_sparse_draft, sparse_draft = POST(f"/content-formats/{format_key}/versions/draft", {}, headers=AUTH_KHAL)
    check("content-format sparse planning draft clone returns 200", st_sparse_draft, 200)
    st_sparse_save, sparse_saved = PUT(
        f"/content-format-versions/{sparse_draft['version_id']}",
        _format_version_payload(format_row["active_version"], weekly_count=0),
        headers=AUTH_KHAL,
    )
    check("content-format sparse planning draft update returns 200", st_sparse_save, 200)
    check("content-format sparse planning stores weekly_count=0",
          (((sparse_saved["production_rules"] or {}).get("planning") or {}).get("weekly_count")), 0)
    st_sparse_activate, sparse_active = POST(
        f"/content-format-versions/{sparse_draft['version_id']}/activate",
        {},
        headers=AUTH_KHAL,
    )
    check("content-format sparse planning activation returns 200", st_sparse_activate, 200)
    check("content-format sparse planning version becomes active", sparse_active["status"], "active")
    # #276 — weekly_count no longer drives round allocation (the operator format_mix does); a version's
    # weekly_count remains stored metadata. POST /rounds still succeeds regardless of a sparse weekly_count.
    st_sparse_round, sparse_round = POST("/rounds", {"days": 1, "posts_per_day": 2, "label": "selftest sparse-format mix", "format_mix": _mix(2)})
    check("#276 POST /rounds succeeds with an exact mix regardless of a version's weekly_count", st_sparse_round, 200)
    cur_sparse = conn.cursor()
    cur_sparse.execute("SELECT format_distribution FROM round WHERE round_id=%s", (sparse_round["round_id"],))
    sparse_dist = cur_sparse.fetchone()[0]
    if isinstance(sparse_dist, str):
        sparse_dist = json.loads(sparse_dist)
    check("#276 round persists the EXACT operator mix (sum = days×posts_per_day = 2)", sum(sparse_dist.values()), 2)
    cur_sparse.close()
    _wipe_round(sparse_round["round_id"])
    updated_formats = GET("/content-formats", headers=AUTH_KHAL)
    format_row = next(row for row in updated_formats["formats"] if row["format_key"] == format_key)
    st_heavy_draft, heavy_draft = POST(f"/content-formats/{format_key}/versions/draft", {}, headers=AUTH_KHAL)
    check("content-format heavy planning draft clone returns 200", st_heavy_draft, 200)
    st_heavy_save, heavy_saved = PUT(
        f"/content-format-versions/{heavy_draft['version_id']}",
        _format_version_payload(format_row["active_version"], weekly_count=99),
        headers=AUTH_KHAL,
    )
    check("content-format heavy planning draft update returns 200", st_heavy_save, 200)
    check("content-format heavy planning stores weekly_count=99",
          (((heavy_saved["production_rules"] or {}).get("planning") or {}).get("weekly_count")), 99)
    st_heavy_activate, heavy_active = POST(
        f"/content-format-versions/{heavy_draft['version_id']}/activate",
        {},
        headers=AUTH_KHAL,
    )
    check("content-format heavy planning activation returns 200", st_heavy_activate, 200)
    check("content-format heavy planning version becomes active", heavy_active["status"], "active")
    st_heavy_round, heavy_round = POST("/rounds", {"days": 2, "posts_per_day": 2, "label": "selftest heavy-format mix", "format_mix": _mix(4)})
    check("#276 POST /rounds succeeds with an exact mix regardless of a heavy weekly_count", st_heavy_round, 200)
    cur_heavy = conn.cursor()
    cur_heavy.execute("SELECT format_distribution FROM round WHERE round_id=%s", (heavy_round["round_id"],))
    heavy_dist = cur_heavy.fetchone()[0]
    if isinstance(heavy_dist, str):
        heavy_dist = json.loads(heavy_dist)
    check("#276 round persists the exact operator mix (sum = days×posts_per_day = 4)", sum(heavy_dist.values()), 4)
    _, heavy_gs = POST("/gates", {"stage": "schedule_review", "round_id": heavy_round["round_id"]}, headers=AUTH_KHAL)
    POST(f"/gates/{heavy_gs['gate_id']}/decide", {"approver_id": "khal", "decision": "approve"}, headers=AUTH_KHAL)
    POST(f"/gates/{heavy_gs['gate_id']}/resolve", {}, headers=AUTH_KHAL)
    cur_heavy.close()
    heavy_topic_state = GET(f"/rounds/{heavy_round['round_id']}/stages/topic_review/state")
    check("topic stage exposes generate next_action after schedule approval under drifted formats",
          heavy_topic_state["next_action"], "generate")
    st_heavy_generate, heavy_job = POST(f"/rounds/{heavy_round['round_id']}/stages/topic_review/generate", {})
    check("topic generation still opens under drifted formats", st_heavy_generate, 200)
    check("topic generation under drifted formats returns the Stage 2A contract", heavy_job.get("stage2a"), True)
    # Poll THROUGH queued | awaiting_trigger | running; stop only on terminal completed | failed | partial.
    heavy_final = None
    for _ in range(120):
        rm = GET(f"/rounds/{heavy_round['round_id']}/generation")
        if rm["phase"] in ("completed", "failed", "partial"):
            heavy_final = rm
            break
        _t.sleep(0.5)
    else:
        heavy_final = rm   # timed out non-terminal — carry the last observation so the assertion fails truthfully
    check("topic generation under drifted formats reaches completed", heavy_final and heavy_final["phase"], "completed")
    check("topic generation under drifted formats counts generated slots", heavy_final["counts"]["generated"], 4)
    _wipe_round(heavy_round["round_id"])
    st_draft, draft = POST(f"/workflows/{workflows['workflows'][0]['workflow_key']}/versions/draft", {},
                           headers=AUTH_KHAL)
    check("workflow draft clone endpoint returns 200", st_draft, 200)
    stage_patch = [s for s in draft["stages"] if s["stage_key"] != "scholar_review"]
    stage_patch[0]["stage_label"] = "API draft"
    transitions_patch = [t for t in draft["transitions"]
                         if t["from_stage_key"] != "scholar_review" and t["to_stage_key"] != "scholar_review"]
    st_wf, wf_updated = PUT(f"/workflow-versions/{draft['version_id']}", {
        "notes": "api selftest workflow draft",
        "stages": stage_patch,
        "transitions": transitions_patch,
    }, headers=AUTH_KHAL)
    check("workflow draft update endpoint returns 200", st_wf, 200)
    check("workflow draft update persists edited label", wf_updated["stages"][0]["stage_label"], "API draft")
    st_act, wf_active = POST(f"/workflow-versions/{draft['version_id']}/activate", {}, headers=AUTH_KHAL)
    check("workflow activate endpoint returns 200", st_act, 200)
    check("workflow activate endpoint marks the draft active", wf_active["status"], "active")
    check("active workflow endpoint points at the newly activated version",
          GET("/workflow-versions/active")["version_id"], draft["version_id"])
    check("workflow draft creation is rejected for non-admin reviewer",
          POST(f"/workflows/{workflows['workflows'][0]['workflow_key']}/versions/draft", {},
               headers=AUTH_HUDA)[0], 400)

    # 2) APPROVE 2 · REQUEST_CHANGE 1 (with a directional comment) · REJECT 1
    check("decide rejects unsigned caller", POST(f"/gates/{gid}/decide", {"approver_id": "khal", "decision": "approve",
                                  "slot_ids": ["RAPI-1", "RAPI-2"]})[0], 401)
    POST(f"/gates/{gid}/decide", {"approver_id": "khal", "decision": "approve",
                                  "slot_ids": ["RAPI-1", "RAPI-2"]}, headers=AUTH_KHAL)
    st_rc, _ = POST(f"/gates/{gid}/decide", {"approver_id": "khal", "decision": "request_change",
                    "slot_ids": ["RAPI-3"], "notes": COMMENT}, headers=AUTH_KHAL)
    check("request_change with comment -> 200", st_rc, 200)
    check("API rejects request_change without a comment",
          POST(f"/gates/{gid}/decide", {"approver_id": "khal", "decision": "request_change",
               "slot_ids": ["RAPI-3"], "notes": ""}, headers=AUTH_KHAL)[0], 400)
    POST(f"/gates/{gid}/decide", {"approver_id": "khal", "decision": "reject", "slot_ids": ["RAPI-4"]}, headers=AUTH_KHAL)
    st_dm, body_dm = POST(f"/gates/{gid}/decide", {"approver_id": "huda", "decision": "approve",
                                                   "slot_ids": ["RAPI-1"]}, headers=AUTH_KHAL)
    check("signed proxy rejects body approver mismatch", st_dm, 400)
    check("...decide mismatch mentions mismatch", "mismatch" in (body_dm.get("detail") or ""), True)

    # #10 approval-identity hardening: every denied approval attempt leaves an audit row,
    # and assignment authorization (not just the signature) gates who may decide.
    aud = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    aud.execute("SELECT actor, detail FROM audit_log WHERE entity='gate' AND entity_id=%s "
                "AND action='approval_denied' ORDER BY at", (str(gid),))
    denied_rows = aud.fetchall(); aud.close()
    check("unsigned decide attempt is audited as 'unsigned'",
          any(r["actor"] == "unsigned" and r["detail"].get("reason") == "unsigned" for r in denied_rows), True)
    check("spoofed body-approver attempt is audited against the signed principal",
          any(r["actor"] == "khal" and r["detail"].get("reason") == "actor_mismatch"
              and r["detail"].get("body_actor") == "huda" for r in denied_rows), True)
    st_ua, body_ua = POST(f"/gates/{gid}/decide", {"approver_id": "huda", "decision": "approve",
                                                   "slot_ids": ["RAPI-1"]}, headers=AUTH_HUDA)
    check("signed but UNASSIGNED approver cannot decide (assignment authorization)",
          (st_ua, "not configured" in (body_ua.get("detail") or "")), (400, True))
    aud = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    aud.execute("SELECT actor, detail FROM audit_log WHERE entity='gate' AND entity_id=%s "
                "AND action='gate_decision_denied' ORDER BY at", (str(gid),))
    ua_rows = aud.fetchall(); aud.close()
    check("unassigned decide attempt is audited with reason=not_assigned",
          any(r["actor"] == "huda" and r["detail"].get("reason") == "not_assigned" for r in ua_rows), True)
    myq2 = GET("/me/pending-approvals", headers=AUTH_KHAL)
    rapi_q2 = [q for q in myq2 if q.get("round_id") == RID and q.get("stage") == "topic_review"]
    check("current principal pending queue clears for the RAPI gate after deciding every target", rapi_q2, [])

    # stage advisory: all 4 decided -> ready to commit (the human-confirmed checkpoint)
    sst = GET(f"/rounds/{RID}/stages/topic_review/state")
    check("stage state = ready_to_commit once all are decided", sst["state"], "ready_to_commit")
    check("advisory tallies: 2 will advance", sst["approved"], 2)
    check("no pending -> no 'commit early' confirm warning", sst["confirm_warnings"], [])

    # 3) RESOLVE
    _, res = POST(f"/gates/{gid}/resolve", {"actor": "khal"}, headers=AUTH_KHAL)
    check("resolve outcomes", {k: res["outcomes"][k] for k in sorted(res["outcomes"])},
          {"RAPI-1": "approved", "RAPI-2": "approved", "RAPI-3": "changes_requested", "RAPI-4": "rejected"})
    dump(conn, "resolve")
    s = slot_states(conn)
    check("DB: approved -> TOPIC_APPROVED", [s["RAPI-1"], s["RAPI-2"]], ["TOPIC_APPROVED", "TOPIC_APPROVED"])
    check("DB: change-requested -> CHANGES_REQUESTED (awaiting rework)", s["RAPI-3"], "CHANGES_REQUESTED")
    check("DB: rejected -> REJECTED (reversible 'dropped', NOT destroyed)", s["RAPI-4"], "REJECTED")
    # #134 — the funnel reconciles the same mixed outcome (2 advanced / 1 awaiting / 1 dropped)
    frapi = GET(f"/rounds/{RID}/funnel")
    trapi = next(x for x in frapi["stages"] if x["stage"] == "topic_review")
    check("funnel[RAPI] topic lanes reconcile the resolve outcome",
          (trapi["in_stage"], trapi["awaiting"], trapi["dropped"], trapi["advanced"]), (0, 1, 1, 2))
    _funnel_conserves(frapi, "RAPI")
    # #237 Slice A — status-independent read-only inspection over the LIVE HTTP path: the completed
    # trail's detail fetch. Same signed boundary as /publications (401 unsigned); full definition
    # (pinned topic + provenance + lineage arrays) for an item that ALREADY advanced; 404 unknown.
    check("#237 inspect rejects an unsigned caller (read-only != unauthenticated)",
          _req("GET", "/slots/RAPI-2/inspect")[0], 401)
    st_ins, insp = _req("GET", "/slots/RAPI-2/inspect", headers=AUTH_KHAL)
    check("#237 inspect serves the ADVANCED item's full definition over HTTP "
          "(pinned+approved topic, decisions, assets[], publications[])",
          (st_ins, insp.get("slot_id"), insp.get("status"),
           bool(insp.get("topic")) and insp["topic"]["text_ar"] is not None,
           insp["topic"]["approved"] if insp.get("topic") else None,
           isinstance(insp.get("assets"), list), isinstance(insp.get("publications"), list),
           any(d["decision"] == "approve" for d in insp.get("decisions", []))),
          (200, "RAPI-2", "TOPIC_APPROVED", True, True, True, True, True))
    check("#237 inspect of an unknown slot -> 404 (no fabricated rows)",
          _req("GET", "/slots/RAPI-NOPE/inspect", headers=AUTH_KHAL)[0], 404)
    # #250 — slot-keyed read-only SDAM visibility + provider-neutral handoff over the LIVE HTTP
    # path. Fixtures via the EXISTING sole write paths only (dam.add_asset / sdam.create_binding /
    # sdam.append_observation); this runtime has NO ResourceSpace env, so the handoff read must
    # truthfully report configured:false — never fabricate availability.
    import dam as dam_mod            # noqa: E402
    import sdam as sdam_mod          # noqa: E402
    check("#250 sdam slot view rejects an unsigned caller", _req("GET", "/slots/RAPI-2/sdam")[0], 401)
    st_nb, nb = _req("GET", "/slots/RAPI-1/sdam", headers=AUTH_KHAL)
    check("#250 unbound slot -> truthful empty bindings (not an error, not fabricated)",
          (st_nb, nb.get("bindings")), (200, []))
    aid_sdam = dam_mod.add_asset(conn, "RAPI-2", "production", "raw", actor="apitest")
    bid_sdam = str(sdam_mod.create_binding(conn, aid_sdam, 1, "RAPI-2", "60006", "apitest")); conn.commit()
    st_b0, b0 = _req("GET", "/slots/RAPI-2/sdam", headers=AUTH_KHAL)
    check("#250 bound with NO observation -> effective_state null, never handoff_ready",
          (st_b0, len(b0["bindings"]), b0["bindings"][0]["effective_state"],
           b0["bindings"][0]["handoff_ready"], b0["bindings"][0]["external_ref"]),
          (200, 1, None, False, "60006"))   # suite-unique ref: never collides with e2e residuals
    bnd = sdam_mod.get_binding(conn, bid_sdam)
    sdam_mod.append_observation(conn, bid_sdam, "apitest-ready", "ready", "system", "apitest",
                                expected_digest=sdam_mod._digest(sdam_mod.expected_projection(bnd)),
                                observed_digest=sdam_mod._digest(
                                    sdam_mod.observed_projection(bnd, str(bnd["asset_id"]))))
    conn.commit()
    st_b1, b1 = _req("GET", "/slots/RAPI-2/sdam", headers=AUTH_KHAL)
    check("#250 fresh ready observation -> effective_state ready + handoff_ready over HTTP",
          (st_b1, b1["bindings"][0]["effective_state"], b1["bindings"][0]["handoff_ready"]),
          (200, "ready", True))
    check("#250 handoff read rejects an unsigned caller",
          _req("GET", f"/sdam/bindings/{bid_sdam}/handoff")[0], 401)
    check("#250 handoff for an unknown binding -> 404",
          _req("GET", "/sdam/bindings/00000000-0000-0000-0000-000000000000/handoff",
               headers=AUTH_KHAL)[0], 404)
    st_h, h = _req("GET", f"/sdam/bindings/{bid_sdam}/handoff", headers=AUTH_KHAL)
    check("#250 handoff on an RS-unconfigured runtime is TRUTHFUL: configured:false, no handoff, "
          "reasoned — never fabricated media",
          (st_h, h.get("configured"), h.get("handoff"), bool(h.get("reason"))),
          (200, False, None, True))
    # #255 S1 — the inspect projection serializes the approved-master-edit pin truthfully over
    # HTTP: absent pin -> null; pinned + newer master -> distinct pinned/current with drift.
    check("#255 inspect: no edit pin -> approved_edit null (truthful absence)",
          _req("GET", "/slots/RAPI-2/inspect", headers=AUTH_KHAL)[1].get("approved_edit"), None)
    ed1 = dam_mod.add_asset(conn, "RAPI-2", "media_edit", "edit", uri="e://v1", actor="apitest")
    cur_pin = conn.cursor()
    cur_pin.execute("INSERT INTO slot_approval (slot_id, artifact, revision, approver, actor_kind) "
                    "VALUES ('RAPI-2','edit',1,'khal','user') "
                    "ON CONFLICT (slot_id, artifact) DO UPDATE SET revision=1")
    # the immutable pin event the engine writes at resolution — the projection derives the EXACT
    # pinned asset identity from it (never re-identified from the revision number)
    cur_pin.execute("INSERT INTO audit_log (entity, entity_id, action, actor, detail) "
                    "VALUES ('slot','RAPI-2','approved_edit_master_pinned','khal', "
                    "jsonb_build_object('asset_id', %s::text, 'revision', 1))", (str(ed1),))
    conn.commit()
    dam_mod.add_asset(conn, "RAPI-2", "media_edit", "edit", uri="e://v2", actor="apitest")
    conn.commit()
    st_ae, ae = _req("GET", "/slots/RAPI-2/inspect", headers=AUTH_KHAL)
    aep = ae.get("approved_edit") or {}
    check("#255 inspect: pinned approved master vs current head serialized DISTINCTLY (drift true, "
          "pinned asset from the immutable audit event)",
          (st_ae, aep.get("pinned_revision"), aep.get("current_master_revision"),
           aep.get("drifted"), aep.get("pinned_asset_id") == str(ed1),
           aep.get("pin_evidence"), aep.get("current_master_ambiguous")),
          (200, 1, 2, True, True, "audit", False))
    # #259 S2 — the governed register-edit endpoint: signed boundary + truthful not-configured
    # (this suite runtime has no RESOURCESPACE_RW_* env, so registration must report 503, never
    # attempt a provider write or fabricate success).
    check("#259 register-edit rejects an unsigned caller",
          _req("POST", "/slots/RAPI-2/sdam/register-edit")[0], 401)
    check("#259 register-edit on an RS-write-unconfigured runtime -> 503 (never a silent write)",
          POST("/slots/RAPI-2/sdam/register-edit", {}, headers=AUTH_KHAL)[0], 503)

    # 4) REVERSIBLE REJECT ("git for content"): dropped -> recoverable -> reopen -> active
    dropped = GET(f"/rounds/{RID}/dropped")
    check("the rejected item is in the recoverable Dropped view", [d["slot_id"] for d in dropped], ["RAPI-4"])
    check("both parked states are excluded — no active review to open",
          POST("/gates", {"stage": "topic_review", "round_id": RID, "actor": "khal"}, headers=AUTH_KHAL)[0], 400)
    _, ro = POST("/slots/RAPI-4/reopen", {}, headers=AUTH_KHAL)
    check("reopen un-rejects the dropped item", ro["kind"], "un_rejected")
    check("DB: reopened item is active again (TOPIC_PROPOSED)", slot_states(conn)["RAPI-4"], "TOPIC_PROPOSED")
    check("...and no longer in the Dropped view", GET(f"/rounds/{RID}/dropped"), [])
    check("full history preserved: RAPI-4 still at revision 1 (reopen never destroys)",
          GET("/slots/RAPI-4/revisions?artifact=topic")[-1]["revision"], 1)
    # the restored item makes the stage start-able again — a contextual state, NOT an error
    check("stage state with the restored item = ready_to_start (no scary error)",
          GET(f"/rounds/{RID}/stages/topic_review/state")["state"], "ready_to_start")

    # 5) EXCLUSION + INTEGRITY GUARD: re-open targets the restored slot, excludes the parked one;
    #    even a stale gate cannot approve a parked (awaiting-rework) slot.
    _, body2 = POST("/gates", {"stage": "topic_review", "round_id": RID, "actor": "khal"}, headers=AUTH_KHAL)
    g2 = body2["gate_id"]
    check("re-open targets the restored slot (RAPI-4), excludes the awaiting-rework one (RAPI-3)",
          [t["slot_id"] for t in GET(f"/gates/{g2}")["targets"]], ["RAPI-4"])
    cur = conn.cursor()
    cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s, 'RAPI-3')", (g2,))  # simulate staleness
    conn.commit()
    check("integrity guard: approving a parked slot is refused (400)",
          POST(f"/gates/{g2}/decide", {"approver_id": "khal", "decision": "approve",
               "slot_ids": ["RAPI-3"]}, headers=AUTH_KHAL)[0], 400)

    # 6) THE TRIGGER (detection/wiring): /changes lists it; /rework (dry_run) reports it
    changes = GET(f"/rounds/{RID}/changes")
    check("API /changes: lists the awaiting-rework slot + its comment",
          [(c["slot_id"], c["comment"]) for c in changes], [("RAPI-3", COMMENT)])
    _, rk = POST(f"/rounds/{RID}/rework?stage=topic&dry_run=true", {})
    check("API /rework (dry_run): would regenerate exactly the awaiting-rework slot",
          (rk["would_rework"], rk["slots"]), (1, ["RAPI-3"]))

    # 7) CLOSE THE LOOP (in-process stub writer): regenerate v2 from the comment
    cfg = engine.load_config()
    results = run_writers.rework_round(cfg, "topic", round_id=RID, quiet=True)
    check("rework processed the awaiting-rework slot", [r["slot_id"] for r in results], ["RAPI-3"])
    dump(conn, "rework")
    cur.execute("""SELECT revision, text_ar, change_summary_en, change_summary_ar, feedback
                   FROM topic WHERE slot_id='RAPI-3' ORDER BY revision DESC LIMIT 1""")
    v2 = cur.fetchone()
    check("v2 stored as revision 2", v2[0], 2)
    check("v2 is comment-RESPONSIVE (addresses the comment's direction, not a blind re-roll)",
          ("الأب والأم" in (v2[1] or "")), True)
    check("v2 carries a bilingual change-summary ('how this addresses your comment')",
          bool(v2[2] and v2[3]), True)
    check("the reviewer comment was passed in as the rework directive", v2[4], COMMENT)
    cur.execute("SELECT count(*) FROM topic WHERE slot_id='RAPI-3'")
    check("v1 kept as history (2 revisions)", cur.fetchone()[0], 2)
    check("DB: reworked slot returns to TOPIC_PROPOSED for re-review", slot_states(conn)["RAPI-3"], "TOPIC_PROPOSED")

    # 8) re-review now approvable (the guard no longer fires once reworked)
    _, body3 = POST("/gates", {"stage": "topic_review", "round_id": RID, "actor": "khal"}, headers=AUTH_KHAL)
    g3 = body3["gate_id"]
    check("API: RAPI-3 is back in the review queue",
          "RAPI-3" in [t["slot_id"] for t in GET(f"/gates/{g3}")["targets"]], True)
    check("approving the reworked slot now SUCCEEDS",
          POST(f"/gates/{g3}/decide", {"approver_id": "khal", "decision": "approve",
               "slot_ids": ["RAPI-3"]}, headers=AUTH_KHAL)[0], 200)
    POST(f"/gates/{g3}/resolve", {"actor": "khal"}, headers=AUTH_KHAL)
    check("DB: reworked + approved slot -> TOPIC_APPROVED", slot_states(conn)["RAPI-3"], "TOPIC_APPROVED")

    # ---- version navigation uses RAPI-4 (still TOPIC_PROPOSED, rev 1); gates scoped to it -------
    def cycle(slot, comment):                # one request_change -> resolve -> stub rework
        _, g = POST("/gates", {"stage": "topic_review", "slot_ids": [slot], "actor": "khal"}, headers=AUTH_KHAL)
        POST(f"/gates/{g['gate_id']}/decide", {"approver_id": "khal", "decision": "request_change",
             "slot_ids": [slot], "notes": comment}, headers=AUTH_KHAL)
        POST(f"/gates/{g['gate_id']}/resolve", {"actor": "khal"}, headers=AUTH_KHAL)
        run_writers.rework_round(cfg, "topic", round_id=RID, quiet=True)

    # 9) CYCLIC: v1 -> v2 -> v3, each driven by the LATEST comment (not the first)
    print("\n9) cyclic co-creation (v1 -> v2 -> v3)")
    C1, C2 = "وضّح الزاوية أكثر", "خاطب الشباب تحديدًا"
    cycle("RAPI-4", C1)
    cycle("RAPI-4", C2)
    revs = GET("/slots/RAPI-4/revisions?artifact=topic")
    check("history chains v1->v2->v3 (append-only)", [r["revision"] for r in revs], [1, 2, 3])
    check("each revision records its OWN driving comment", [r["feedback"] for r in revs], [None, C1, C2])
    check("provenance is linear (base_revision chain)", [r["base_revision"] for r in revs], [None, 1, 2])
    body3 = revs[-1]["body"] or ""
    check("v3 reflects the SECOND (latest) comment, not the first",
          (C2 in body3) and (C1 not in body3), True)

    # 10) #321 R5 — EXACT decision validity. Recording an approval for a NON-head revision (v2 while
    # v3 is head) no longer advances the item: resolve fails typed-STALE under the canonical slot lock,
    # because a newer UNREVIEWED head (v3) exists. The decision is PRESERVED (never deleted); the slot
    # does not move; the later head is never represented as approved. Re-approving the CURRENT head is
    # the governed way forward, and only then does the topic->script directive emit (carrying v3).
    print("\n10) #321 R5 — approve a non-head revision fails stale; re-approve the head advances")
    _, gC = POST("/gates", {"stage": "topic_review", "slot_ids": ["RAPI-4"], "actor": "khal"}, headers=AUTH_KHAL)
    POST(f"/gates/{gC['gate_id']}/decide", {"approver_id": "khal", "decision": "approve",
         "slot_ids": ["RAPI-4"], "revision": 2}, headers=AUTH_KHAL)
    _, rrb = POST(f"/gates/{gC['gate_id']}/resolve", {"actor": "khal"}, headers=AUTH_KHAL)
    check("R5 resolve reports RAPI-4 as typed stale_revision (not approved)",
          (rrb or {}).get("outcomes", {}).get("RAPI-4"), "stale_revision")
    _sc = conn.cursor()
    _sc.execute("SELECT count(*) FROM audit_log WHERE entity='slot' AND entity_id='RAPI-4' "
                "AND action='resolve_stale_revision'")
    _stale_audits = _sc.fetchone()[0]
    _sc.close(); conn.rollback()
    check("R5 immutable resolve_stale_revision audit recorded", _stale_audits >= 1, True)
    revs = GET("/slots/RAPI-4/revisions?artifact=topic")
    check("R5 no approval pin created while head (v3) is unreviewed",
          [r["revision"] for r in revs if r["approved"]], [])
    _dc = conn.cursor()
    _dc.execute("SELECT revision FROM gate_decision WHERE gate_id=%s AND slot_id='RAPI-4' "
                "AND decision='approve'", (gC["gate_id"],))
    _pinned = [r[0] for r in _dc.fetchall()]
    _dc.close(); conn.rollback()
    check("R5 the recorded decision is PRESERVED (still pinned to v2, never deleted)", _pinned, [2])
    check("R5 NO topic->script directive emitted for a stale resolve",
          [d for d in GET("/slots/RAPI-4/directives") if d["to_stage"] == "script"], [])
    # re-approve the CURRENT head (v3) -> advances + pins v3, and the directive now carries v3
    POST(f"/gates/{gC['gate_id']}/decide", {"approver_id": "khal", "decision": "approve",
         "slot_ids": ["RAPI-4"], "revision": 3, "expected_revision": 3}, headers=AUTH_KHAL)
    POST(f"/gates/{gC['gate_id']}/resolve", {"actor": "khal"}, headers=AUTH_KHAL)
    revs = GET("/slots/RAPI-4/revisions?artifact=topic")
    check("R5 re-approving the current head (v3) advances + pins v3",
          [r["revision"] for r in revs if r["approved"]], [3])
    sdir = [d for d in GET("/slots/RAPI-4/directives") if d["to_stage"] == "script"][-1]
    check("topic->script directive carries the APPROVED head revision (v3)", sdir["revision"], 3)
    check("...and its context.topic_revision is v3 too",
          sdir["payload"]["context"]["topic_revision"], 3)

    # 11) RESTORE governance (#313 B1): restore reopens an item INTO review, so an APPROVED item is
    # fail-closed to the #249 governed denial (reconsideration unimplemented) — never a bare reopen. The
    # sanctioned reversal is /reopen (reversible commit, §12); only once back in review may restore run.
    print("\n11) restore governance — #249 fence on approved, then reopen -> restore -> rework")
    dcode, dbody = POST("/slots/RAPI-4/restore", {"artifact": "topic", "revision": 1}, headers=AUTH_KHAL)
    ddetail = dbody.get("detail", dbody) if isinstance(dbody, dict) else {}
    check("restore of an APPROVED item is #249 governed-denied (409) — #249 stays unconsumed",
          (dcode, ddetail.get("error"), ddetail.get("reason")), (409, "governed_denial", "approved"))
    # governed reversal first (reversible commit), THEN restore is eligible again
    POST("/slots/RAPI-4/reopen", {}, headers=AUTH_KHAL)
    check("reopen brought the approved item back to review (approval pin cleared)",
          (slot_states(conn)["RAPI-4"],
           [r["revision"] for r in GET("/slots/RAPI-4/revisions?artifact=topic") if r["approved"]]),
          ("TOPIC_PROPOSED", []))
    _, rst = POST("/slots/RAPI-4/restore", {"artifact": "topic", "revision": 1}, headers=AUTH_KHAL)
    check("restore of the reopened (in-review) item appends a new head (v4) copied from v1", rst["new_revision"], 4)
    revs = GET("/slots/RAPI-4/revisions?artifact=topic")
    v1body = next(r["body"] for r in revs if r["revision"] == 1)
    v4 = next(r for r in revs if r["revision"] == 4)
    check("v4 provenance = based on v1 (linear restore, not a branch)", v4["base_revision"], 1)
    check("v4 content is a copy of v1", v4["body"], v1body)
    check("restore kept the item in review with no approval pin",
          (slot_states(conn)["RAPI-4"], [r["revision"] for r in revs if r["approved"]]),
          ("TOPIC_PROPOSED", []))
    C3 = "اربطه بمثال يومي"
    cycle("RAPI-4", C3)                       # rework from the restored head -> v5
    revs = GET("/slots/RAPI-4/revisions?artifact=topic")
    check("full history preserved + linear (v1..v5)", [r["revision"] for r in revs], [1, 2, 3, 4, 5])
    check("v5 derived from the restored head v4", revs[-1]["base_revision"], 4)
    check("v5 reflects the new comment", C3 in (revs[-1]["body"] or ""), True)

    # 12) REVERSIBLE COMMIT (batch checkpoint): a committed approval is recoverable (un-approve)
    print("\n12) reversible commit — un-approve a committed item")
    check("RAPI-1 was committed-approved earlier", slot_states(conn)["RAPI-1"], "TOPIC_APPROVED")
    _, un = POST("/slots/RAPI-1/reopen", {}, headers=AUTH_KHAL)
    check("reopen un-approves a committed item", un["kind"], "un_approved")
    check("DB: un-approved item is back in review (TOPIC_PROPOSED)", slot_states(conn)["RAPI-1"], "TOPIC_PROPOSED")
    check("history preserved through the reversal (revision intact)",
          GET("/slots/RAPI-1/revisions?artifact=topic")[-1]["revision"], 1)
    check("nothing left in the Dropped view (un-approve != reject)", GET(f"/rounds/{RID}/dropped"), [])

    # S) conversational agent — reply + the commit HARD FLOOR (offline scripted LLM + live endpoint)
    print("\nS) agent — reply, commit hard floor + #144 unavailable-action contract")
    cs = conn.cursor()
    cs.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RAGT')")
    for tbl in ("directive", "slot_approval", "topic", "slot"):
        cs.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE 'RAGT-%%'")
    cs.execute("DELETE FROM round WHERE round_id='RAGT'")
    cs.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                  pillar_distribution,format_distribution,status,tenant_id)
                  VALUES ('RAGT','agent',1,2,'["09:00"]','{}','{}','planning','selftest')""")
    cs.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no,topic_angle,hook_text,tenant_id)
                  VALUES ('RAGT-1','RAGT',1,'09:00','P1_SELF','1.1','L1','Painful Truth','TOPIC_PROPOSED',1,'a','h','selftest')""")
    cs.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,hook_text,hook_type,revision,tenant_id)
                  VALUES ('RAGT-1','1.1','L1','RAGT',1,'a','h','Painful Truth',1,'selftest')""")
    conn.commit(); cs.close()

    def _slot_status(sid):
        c = conn.cursor(); c.execute("SELECT status FROM slot WHERE slot_id=%s", (sid,)); v = c.fetchone()[0]; c.close(); return v

    ctx = {"round_id": "RAGT", "artifact": "topic", "actor": "khal"}
    # reply path (offline): a status tool then a text answer -> non-empty reply + the engine tool ran
    rep = A.run([{"role": "user", "content": "status?"}], ctx,
                llm=ScriptLLM([{"tool_calls": [{"id": "1", "name": "status", "arguments": {}}]},
                               {"text": "There are items to review."}]), allow_commit=False)
    check("agent returns a non-empty reply", bool((rep.get("text") or "").strip()), True)
    check("agent drove the engine (status tool ran)", [a["name"] for a in rep["tool_results"]], ["status"])

    # #144 — structured unavailable-action fallback (contract #143 / inventory #130): blocked or
    # unknown actions return {unavailable, action, reason_class, next_step}, never improvised text.
    def _agent_tool_result(tool_name, arguments=None, actor="khal"):
        r = A.run([{"role": "user", "content": "do it"}], {**ctx, "actor": actor},
                  llm=ScriptLLM([{"tool_calls": [{"id": "1", "name": tool_name,
                                                  "arguments": arguments or {}}]},
                                 {"text": "ok"}]), allow_commit=False)
        return next((a["result"] for a in r["tool_results"] if a["name"] == tool_name), {})

    ne = _agent_tool_result("plan_run")
    check("#144 run creation -> not_exposed with actionable next_step",
          (ne.get("unavailable"), ne.get("action"), ne.get("reason_class"), "dashboard" in (ne.get("next_step") or "")),
          (True, "plan_run", "not_exposed", True))
    ge = _agent_tool_result("generate")
    check("#144 generation start -> not_exposed", (ge.get("unavailable"), ge.get("reason_class")), (True, "not_exposed"))
    ad = _agent_tool_result("approval_policy")
    check("#144 admin policy action -> not_exposed", (ad.get("unavailable"), ad.get("reason_class")), (True, "not_exposed"))
    uk = _agent_tool_result("frobnicate_the_widgets")
    check("#144 unknown tool -> not_exposed with next_step (no raw 'unknown tool' text)",
          (uk.get("unavailable"), uk.get("reason_class"), bool(uk.get("next_step")), "unknown tool" in str(uk)),
          (True, "not_exposed", True, False))
    # dependency_unavailable: classify a backing-service outage (patch the contract fn, restore after)
    _orig_rework = A.C.rework
    try:
        def _down(*a, **k): raise RuntimeError("rework writer unavailable (provider deps not installed)")
        A.C.rework = _down
        dep = _agent_tool_result("rework")
        check("#144 backing-service outage -> dependency_unavailable",
              (dep.get("unavailable"), dep.get("reason_class")), (True, "dependency_unavailable"))
    finally:
        A.C.rework = _orig_rework

    # approve the slot so a REAL commit WOULD advance it (decided -> ready_to_commit)
    C.approve("RAGT", "topic", ["RAGT-1"], actor="khal")
    check("approved-but-not-committed slot stays TOPIC_PROPOSED", _slot_status("RAGT-1"), "TOPIC_PROPOSED")
    # #144 not_authorized: an unassigned actor's approve is denied by the engine and classified
    na = _agent_tool_result("approve", {"slot_ids": ["RAGT-1"]}, actor="huda")
    check("#144 unassigned actor -> not_authorized (engine denial classified)",
          (na.get("unavailable"), na.get("reason_class"), "huda" in (na.get("next_step") or "")),
          (True, "not_authorized", True))
    # HARD FLOOR: a free-text "commit" must be refused and must NOT advance the batch
    flo = A.run([{"role": "user", "content": "اعتمد الدفعة"}], ctx,
                llm=ScriptLLM([{"tool_calls": [{"id": "1", "name": "commit", "arguments": {}}]},
                               {"text": "I can't commit from chat — tap Commit."}]), allow_commit=False)
    commit_res = next((a["result"] for a in flo["tool_results"] if a["name"] == "commit"), {})
    check("free-text commit is REFUSED as #144 human_confirm_required (hard floor)",
          (commit_res.get("unavailable"), commit_res.get("reason_class"), bool(commit_res.get("next_step"))),
          (True, "human_confirm_required", True))
    check("free-text commit did NOT advance the batch", _slot_status("RAGT-1"), "TOPIC_PROPOSED")
    # the STRUCTURED path still advances (the button == a confirmed commit)
    C.commit("RAGT", "topic", actor="khal", confirmed=True)
    check("structured (confirmed) commit DOES advance", _slot_status("RAGT-1"), "TOPIC_APPROVED")
    # The conversational agent is a LIVE-provider path. Assert the expectation EXPLICITLY from the
    # CONFIGURED credential state so credential/readiness DRIFT is never masked — an unconditional
    # "200 or 503" pass would hide a silently-missing key in a live env, or an unexpected 503 when a key
    # IS set. In THIS governed no-live-provider/stub gate GROQ_API_KEY is absent by design, so the
    # endpoint must FAIL CLOSED to a typed 503 carrying the missing-credential detail, with NO fabricated
    # reply. A separate LIVE validation (credential explicitly present) requires 200 + reply — but this
    # PR gate never calls a live provider. RESIDUAL (follow-up): derive provider readiness from the
    # governed capability matrix rather than a bare env probe (capability-matrix readiness integration).
    st_a, body_a = POST("/rounds/RAGT/agent", {"message": "summarize this round in one line", "reviewer": "khal", "artifact": "topic"}, headers=AUTH_KHAL)
    _detail_a = str(body_a.get("detail", "") if isinstance(body_a, dict) else body_a)
    if os.environ.get("GROQ_API_KEY"):
        check("POST /rounds/{id}/agent returns 200 + a reply when GROQ is configured (live validation)",
              (st_a, isinstance(body_a, dict) and "reply" in body_a), (200, True))
    else:
        check("POST /rounds/{id}/agent fails closed to a typed 503 (missing GROQ credential), no fabricated reply",
              (st_a, "GROQ_API_KEY" in _detail_a, isinstance(body_a, dict) and "reply" in body_a),
              (503, True, False))
    cs = conn.cursor()
    cs.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RAGT')")
    for tbl in ("directive", "slot_approval", "topic", "slot"):
        cs.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE 'RAGT-%%'")
    cs.execute("DELETE FROM round WHERE round_id='RAGT'"); cs.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RAGT-%%'")
    conn.commit(); cs.close()

    # #89 — the content-format "sparse"/"heavy" tests above ACTIVATE drifted managed versions
    # (weekly_count=0 and =99). Restore the canonical content-format registry at the very end (after all
    # assertions) so those test values — especially 3sec_reel_caption=99 — never leak into the DB and skew
    # later managed planning distribution. /content-formats/reset re-seeds the canonical formats.
    # #276 — capture the operator-owned baseline policy generation BEFORE the reset re-mints versions.
    _pol_before_reset = GET("/baseline-eligibility")["policy"]["policy_id"]
    st_cf_reset, _ = POST("/content-formats/reset", {"confirm_reset": True}, headers=AUTH_KHAL)
    check("content-format registry restored to canonical after drift tests (#89)", st_cf_reset, 200)
    # #276 — reset re-mints content_format_version IDs but MUST NOT delete, replace, or recreate the
    # operator-owned baseline_eligibility_policy generation; and after a reminting reset run-eligibility
    # FAILS CLOSED (invalid policy) rather than approximating.
    _cur_pol = conn.cursor()
    _cur_pol.execute("SELECT count(*) FROM baseline_eligibility_policy WHERE policy_id=%s", (_pol_before_reset,))
    check("#276 content-format reset PRESERVES the baseline policy generation (not deleted/recreated)",
          _cur_pol.fetchone()[0], 1)
    _cur_pol.close()
    check("#276 after a reminting reset the baseline policy is invalid → fails closed (409, no approximation)",
          _req("GET", "/baseline-eligibility")[0], 409)
    # test-env recovery only (NOT product reset behaviour): drop the now-invalid generation so the endpoint
    # re-seeds a valid baseline from the new governed versions for downstream consumers.
    _cur_fix = conn.cursor()
    _cur_fix.execute("UPDATE baseline_eligibility_policy SET superseded_by=NULL")
    _cur_fix.execute("DELETE FROM baseline_eligibility_policy")
    conn.commit(); _cur_fix.close()
    check("#276 a fresh governed seed re-establishes a valid baseline after reset",
          len(GET("/baseline-eligibility")["eligible"]) >= 1, True)

    # #147 (#146 S1) — reviewer proxy secret fails closed outside explicit dev/test.
    print("\nT) reviewer proxy secret — fail-closed outside dev/test (#147)")
    import fastapi
    import importlib
    api = importlib.import_module("api")
    _saved = (os.environ.get("REVIEWER_PROXY_SECRET"), os.environ.get("TANAGHOM_DEV_MODE"))
    try:
        os.environ["REVIEWER_PROXY_SECRET"] = "real-secret-xyz"; os.environ.pop("TANAGHOM_DEV_MODE", None)
        check("#147 configured secret is used verbatim", api._proxy_secret(), "real-secret-xyz")
        check("#147 configured secret reported configured", api._reviewer_secret_configured(), True)
        os.environ.pop("REVIEWER_PROXY_SECRET", None); os.environ["TANAGHOM_DEV_MODE"] = "1"
        check("#147 dev-mode + no secret uses dev fallback", api._proxy_secret(), api._DEV_REVIEWER_SECRET)
        check("#147 dev-mode not reported as configured", api._reviewer_secret_configured(), False)
        os.environ.pop("REVIEWER_PROXY_SECRET", None); os.environ.pop("TANAGHOM_DEV_MODE", None)
        try:
            api._proxy_secret(); failed_closed = False
        except fastapi.HTTPException as e:
            failed_closed = (e.status_code == 500 and "not configured" in str(e.detail))
        check("#147 missing secret + no dev-mode FAILS CLOSED (500, no silent fallback)", failed_closed, True)
        # empty-string secret is treated as unset, not an empty HMAC key
        os.environ["REVIEWER_PROXY_SECRET"] = ""
        check("#147 empty-string secret is not reported configured", api._reviewer_secret_configured(), False)
    finally:
        for k, v in (("REVIEWER_PROXY_SECRET", _saved[0]), ("TANAGHOM_DEV_MODE", _saved[1])):
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    # the running API reports the two config booleans on /health (dev_mode true in this test container)
    h = GET("/health")
    check("#147 /health exposes reviewer_secret_configured + dev_mode booleans",
          ("reviewer_secret_configured" in h and isinstance(h.get("dev_mode"), bool)), True)

    # --- #190 (#172 S1): identity binding lookup (system-gated, read-only) ---- #
    print("\n----- #190 identity binding (/identity/binding) -----")
    ib_cur = conn.cursor()
    ib_cur.execute("DELETE FROM user_identity WHERE issuer='https://apitest-idp'")
    ib_cur.execute("""INSERT INTO user_identity (issuer, subject, principal_id, created_by)
                      VALUES ('https://apitest-idp', 'sub-khal', 'khal', 'api-selftest')""")
    conn.commit()
    AUTH_SYSTEM = _signed("system")
    b = GET("/identity/binding?issuer=https://apitest-idp&subject=sub-khal", headers=AUTH_SYSTEM)
    check("#190 system principal resolves a bound identity", b.get("principal_id"), "khal")
    b2 = GET("/identity/binding?issuer=https://apitest-idp&subject=sub-nobody", headers=AUTH_SYSTEM)
    check("#190 unbound identity resolves to null (no fallback identity)", b2.get("principal_id"), None)
    st_user, _ = _req("GET", "/identity/binding?issuer=https://apitest-idp&subject=sub-khal",
                      headers=AUTH_KHAL)
    check("#190 USER principals may not read identity bindings", st_user, 403)
    st_unsigned, _ = _req("GET", "/identity/binding?issuer=https://apitest-idp&subject=sub-khal")
    check("#190 unsigned binding lookup is rejected", st_unsigned, 401)
    ib_cur.execute("DELETE FROM user_identity WHERE issuer='https://apitest-idp'")
    conn.commit(); ib_cur.close()

    # --- #194 (#172 S2): identity-binding lifecycle over the API -------------- #
    print("\n----- #194 identity-binding lifecycle (authority, conflicts, CAS) -----")
    # #195 re-review — creates/deactivations require the gate API's CONFIGURED trusted issuer
    # (fail-closed otherwise; the config-absent proofs live in gates.selftest §17 where the env
    # can be flipped in-process). The test drill runs the API with TANAGHOM_OIDC_ISSUER set.
    ISS_API = (os.environ.get("TANAGHOM_OIDC_ISSUER") or "").strip().rstrip("/")
    check("#195 drill precondition: the gate API has a configured trusted issuer", bool(ISS_API), True)
    ib2 = conn.cursor()
    ib2.execute("DELETE FROM user_identity WHERE issuer=%s AND subject LIKE 'apitest-%%'", (ISS_API,))
    conn.commit()
    st_l_unsigned, _ = _req("GET", "/identity/bindings")
    check("#194 unsigned list rejected", st_l_unsigned, 401)
    st_l_huda, _ = _req("GET", "/identity/bindings", headers=AUTH_HUDA)
    check("#194 non-admin list denied", st_l_huda, 400)
    st_c, made = POST("/identity/bindings",
                      {"issuer": ISS_API, "subject": "apitest-sub-h", "principal_id": "huda"},
                      headers=AUTH_KHAL)
    check("#194 admin create returns the active binding", (st_c, made["active"]), (200, True))
    st_dup, _ = POST("/identity/bindings",
                     {"issuer": ISS_API, "subject": "apitest-sub-h", "principal_id": "nour"},
                     headers=AUTH_KHAL)
    check("#194 duplicate tuple is HTTP 409 (explicit conflict, no reassignment path)", st_dup, 409)
    lst = GET("/identity/bindings?limit=2&offset=0", headers=AUTH_KHAL)
    check("#194 list is bounded + deterministic (limit honored, total reported)",
          (len(lst["bindings"]) <= 2, isinstance(lst["total"], int), lst["limit"]), (True, True, 2))
    iid = made["identity_id"]
    st_d, after_d = POST(f"/identity/bindings/{iid}/deactivate", {}, headers=AUTH_KHAL)
    check("#194 deactivate 200, principal unchanged", (st_d, after_d["active"], after_d["principal_id"]),
          (200, False, "huda"))
    b_off = GET(f"/identity/binding?issuer={ISS_API}&subject=apitest-sub-h", headers=AUTH_SYSTEM)
    check("#194 deactivated binding no longer resolves (revocation source of truth)",
          b_off.get("principal_id"), None)
    st_stale, _ = POST(f"/identity/bindings/{iid}/deactivate", {}, headers=AUTH_KHAL)
    check("#194 stale transition is HTTP 409", st_stale, 409)
    st_r, after_r = POST(f"/identity/bindings/{iid}/reactivate", {}, headers=AUTH_KHAL)
    check("#194 same-tuple reactivate 200 with same principal",
          (st_r, after_r["active"], after_r["principal_id"]), (200, True, "huda"))
    st_mut_huda, _ = POST(f"/identity/bindings/{iid}/deactivate", {}, headers=AUTH_HUDA)
    check("#194 non-admin mutation denied", st_mut_huda, 400)
    # #195 re-review — signed MALFORMED create requests: authenticated-then-audited (each 400s
    # with an attributable invalid_input audit and NO binding mutation); unauthenticated malformed
    # noise 401s with NO audit rows.
    ib2.execute("SELECT count(*) FROM audit_log WHERE entity='user_identity' AND detail->>'reason'='invalid_input'")
    inv_before = ib2.fetchone()[0]
    malformed = [
        {"issuer": ISS_API, "principal_id": "huda"},                                # missing subject
        {"issuer": None, "subject": "apitest-x", "principal_id": "huda"},           # null issuer
        {"issuer": ISS_API, "subject": "apitest-x", "principal_id": 123},           # wrong type
        {"issuer": ISS_API, "subject": "x" * 513, "principal_id": "huda"},          # overlong
        "just-a-string",                                                             # non-object body
    ]
    mal_statuses = [POST("/identity/bindings", m, headers=AUTH_KHAL)[0] for m in malformed]
    req_raw = urllib.request.Request(API + "/identity/bindings", data=b"{not-json",
                                     headers={**AUTH_KHAL, "Content-Type": "application/json"},
                                     method="POST")
    try:
        urllib.request.urlopen(req_raw)
        raw_status = 200
    except urllib.error.HTTPError as e:
        raw_status = e.code
    mal_statuses.append(raw_status)
    ib2.execute("SELECT count(*) FROM audit_log WHERE entity='user_identity' AND detail->>'reason'='invalid_input'")
    inv_after = ib2.fetchone()[0]
    ib2.execute("SELECT count(*) FROM user_identity WHERE issuer=%s AND subject LIKE 'apitest-%%'", (ISS_API,))
    rows_after_malformed = ib2.fetchone()[0]
    check("#195 signed malformed creates: all 400, each attributably audited, zero mutations",
          (mal_statuses, inv_after - inv_before >= 6, rows_after_malformed), 
          ([400, 400, 400, 400, 400, 400], True, 1))
    # unauthenticated malformed noise: 401, and NO new user_identity audit rows
    ib2.execute("SELECT count(*) FROM audit_log WHERE entity='user_identity'")
    noise_before = ib2.fetchone()[0]
    st_noise, _ = POST("/identity/bindings", {"issuer": None}, headers=None)
    ib2.execute("SELECT count(*) FROM audit_log WHERE entity='user_identity'")
    noise_after = ib2.fetchone()[0]
    check("#195 unauthenticated malformed noise: 401 and NOT audited",
          (st_noise, noise_after - noise_before), (401, 0))

    # #195 review — pagination beyond the first page with >100 records (server max page = 100)
    ib2.execute("""INSERT INTO user_identity (issuer, subject, principal_id, created_by)
                   SELECT %s, 'apitest-bulk-' || lpad(g::text, 4, '0'), 'huda', 'api-selftest'
                   FROM generate_series(1, 120) g""", (ISS_API,))
    conn.commit()
    page1 = GET("/identity/bindings?limit=100&offset=0", headers=AUTH_KHAL)
    page2 = GET("/identity/bindings?limit=100&offset=100", headers=AUTH_KHAL)
    check("#195 >100 records paginate deterministically past page 1",
          (len(page1["bindings"]), page1["total"] >= 121, len(page2["bindings"]) >= 21,
           page1["bindings"][-1]["subject"] < page2["bindings"][0]["subject"]),
          (100, True, True, True))
    st_over, over_body = _req("GET", "/identity/bindings?limit=500&offset=0", headers=AUTH_KHAL)
    check("#195 page size is capped server-side", (st_over, len(over_body["bindings"])), (200, 100))
    ib2.execute("DELETE FROM user_identity WHERE issuer=%s AND subject LIKE 'apitest-%%'", (ISS_API,))
    ib2.execute("DELETE FROM audit_log WHERE entity='user_identity'")
    conn.commit(); ib2.close()

    # --- #184: managed topic-repetition policy over the API ------------------ #
    print("\n----- #184 repetition policy (authority-gated, audited) -----")
    rp_cur = conn.cursor()
    rp_cur.execute("DELETE FROM repetition_policy")
    rp_cur.execute("DELETE FROM audit_log WHERE entity='repetition_policy'")
    conn.commit()
    rp = GET("/repetition-policy", headers=AUTH_KHAL)
    check("#184 effective default is strict (scope all, production_default)",
          (rp["policy"]["scope"], rp["policy"]["source"]), ("all", "production_default"))
    check("#184 top-level authority sees can_administer", rp["can_administer"], True)
    check("#184 non-admin does NOT see can_administer",
          GET("/repetition-policy", headers=AUTH_HUDA)["can_administer"], False)
    st_unsigned, _ = PUT("/repetition-policy", {"scope": "hcs"})
    check("#184 unsigned policy write is rejected", st_unsigned, 401)
    st_huda, _ = PUT("/repetition-policy", {"scope": "hcs"}, headers=AUTH_HUDA)
    check("#184 signed non-admin policy write is denied", st_huda, 400)
    st_khal, body_khal = PUT("/repetition-policy",
                             {"scope": "all", "repeat_modes": {"cross_format": True}},
                             headers=AUTH_KHAL)
    check("#184 top-level authority updates the policy",
          (st_khal, body_khal["policy"]["source"], body_khal["policy"]["repeat_modes"].get("cross_format")),
          (200, "managed", True))
    st_bad, _ = PUT("/repetition-policy", {"repeat_modes": {"teleport": True}}, headers=AUTH_KHAL)
    check("#184 unsupported repeat modes are rejected, never silently accepted", st_bad, 400)
    # sparse update over the API: one field changes, the managed rest survives
    st_sparse, body_sparse = PUT("/repetition-policy", {"similarity_threshold": 0.91},
                                 headers=AUTH_KHAL)
    check("#184 sparse PUT preserves unrelated managed fields",
          (st_sparse, body_sparse["policy"]["similarity_threshold"],
           body_sparse["policy"]["repeat_modes"].get("cross_format"),
           body_sparse["policy"]["scope"], body_sparse["policy"]["enabled"]),
          (200, 0.91, True, "all", True))
    rp_cur = conn.cursor()
    rp_cur.execute("""SELECT count(*) FROM audit_log
                      WHERE entity='repetition_policy' AND action='repetition_policy_updated'""")
    updated_audits = rp_cur.fetchone()[0]
    rp_cur.execute("""SELECT count(*) FROM audit_log
                      WHERE entity='repetition_policy' AND action='repetition_policy_update_denied'
                        AND actor='huda'""")
    denied_audits = rp_cur.fetchone()[0]
    # restore the strict default shape (managed row, no modes) so the suite leaves no active exception
    PUT("/repetition-policy", {"scope": "all", "repeat_modes": {}}, headers=AUTH_KHAL)
    rp_cur.execute("DELETE FROM repetition_policy")
    rp_cur.execute("DELETE FROM audit_log WHERE entity='repetition_policy'")
    conn.commit()
    rp_cur.close()
    check("#184 policy change is audited (before/after) and denial is audited",
          (updated_audits >= 1, denied_audits >= 1), (True, True))

    # --- #200: pub.v1 manual publication recording over the API -------------- #
    print("\n----- #200 pub.v1 publications (governed manual recording) -----")
    pb = conn.cursor()

    def _pub_api_cleanup():
        # ONE psycopg2 transaction: trigger DISABLE/ENABLE + deletes commit or roll back together,
        # so the guards can never be left disabled by a mid-cleanup failure.
        pb.execute("ALTER TABLE publication_event DISABLE TRIGGER trg_publication_event_immutable")
        pb.execute("ALTER TABLE publication DISABLE TRIGGER trg_publication_frozen")
        pb.execute("ALTER TABLE publication_raw_asset DISABLE TRIGGER trg_publication_raw_asset_frozen")
        pb.execute("DELETE FROM publication_raw_asset WHERE publication_intent_id IN "
                   "(SELECT publication_intent_id FROM publication WHERE slot_id LIKE 'APUB-%%')")
        pb.execute("DELETE FROM publication_event WHERE publication_intent_id IN "
                   "(SELECT publication_intent_id FROM publication WHERE slot_id LIKE 'APUB-%%')")
        pb.execute("DELETE FROM publication WHERE slot_id LIKE 'APUB-%%'")
        pb.execute("ALTER TABLE publication_raw_asset ENABLE TRIGGER trg_publication_raw_asset_frozen")
        pb.execute("ALTER TABLE publication ENABLE TRIGGER trg_publication_frozen")
        pb.execute("ALTER TABLE publication_event ENABLE TRIGGER trg_publication_event_immutable")
        pb.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                   "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='APUB')")
        for _t in ("asset", "script", "topic", "slot_approval", "slot_review", "directive"):
            pb.execute(f"DELETE FROM {_t} WHERE slot_id LIKE 'APUB-%%'")
        pb.execute("DELETE FROM slot WHERE round_id='APUB'")
        pb.execute("DELETE FROM round WHERE round_id='APUB'")
        pb.execute("DELETE FROM audit_log WHERE entity='publication' OR entity_id LIKE 'APUB-%%'")
        conn.commit()

    _pub_api_cleanup()
    pb.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                  pillar_distribution,format_distribution,status) VALUES
                  ('APUB','pub-api-e2e',1,4,'["09:00"]','{}','{}','planned')""")
    for sid, sstatus in (("APUB-1", "SCHEDULED"), ("APUB-2", "EDITED")):
        pb.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                      hook_type,status,cycle_no,format) VALUES
                      (%s,'APUB',1,'09:00','P1_SELF','1.1','L1','Painful Truth',%s,1,'Hero Reel')""",
                   (sid, sstatus))
        pb.execute("INSERT INTO script (slot_id,hcs_id,lens,script_ar,revision) "
                   "VALUES (%s,'1.1','L1','نص',1)", (sid,))
    for stage in ("production_review", "edit_review", "distribution_review"):
        pb.execute("""INSERT INTO gate (scope, stage, policy, rule_key, quorum, status)
                      VALUES ('batch',%s,'fixed','any','1','approved') RETURNING gate_id""", (stage,))
        _gid = pb.fetchone()[0]
        pb.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,'APUB-1')", (_gid,))
        pb.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                   "VALUES (%s,'APUB-1','khal','approve')", (_gid,))
        if stage == "distribution_review":
            pb.execute("""INSERT INTO gate_assignment (gate_id, assignment_kind, assignment_key,
                          resolved_principal_id) VALUES (%s,'user','khal','khal')""", (_gid,))
    for stage, kind in (("production", "raw_cut"), ("media_edit", "edit")):
        pb.execute("""INSERT INTO asset (slot_id, stage, kind, uri, storage, version, status, created_by)
                      VALUES ('APUB-1', %s, %s, %s, 'reference', 1, 'active', 'apitest')""",
                   (stage, kind, f"placeholder://{kind}/APUB-1"))
    conn.commit()

    pb.execute("SELECT count(*) FROM audit_log WHERE entity='publication'")
    pub_audits_before = pb.fetchone()[0]
    st_unsigned, _ = POST("/publications", {"slot_id": "APUB-1", "platform_key": "instagram",
                                            "idempotency_key": "api-key-1"})
    pb.execute("SELECT count(*) FROM audit_log WHERE entity='publication'")
    check("#200 unsigned create is 401 and NEVER audited (unauthenticated noise)",
          (st_unsigned, pb.fetchone()[0]), (401, pub_audits_before))
    st_malformed, _ = POST("/publications", "not-an-object", headers=AUTH_KHAL)
    pb.execute("""SELECT count(*) FROM audit_log WHERE entity='publication'
                  AND action='publication_denied' AND actor='khal'""")
    check("#200 signed malformed body is 400 AND attributably audited",
          (st_malformed, pb.fetchone()[0] >= 1), (400, True))
    st_inel, _ = POST("/publications", {"slot_id": "APUB-2", "platform_key": "instagram",
                                        "idempotency_key": "api-key-2"}, headers=AUTH_KHAL)
    check("#200 unapproved item is refused over the API", st_inel, 400)
    st_unauth, _ = POST("/publications", {"slot_id": "APUB-1", "platform_key": "instagram",
                                          "idempotency_key": "api-key-3"}, headers=AUTH_HUDA)
    check("#200 signed-but-unauthorized actor is refused", st_unauth, 400)
    st_ok, made = POST("/publications", {"slot_id": "APUB-1", "platform_key": "instagram",
                                         "idempotency_key": "api-key-4"}, headers=AUTH_KHAL)
    check("#200 authorized create returns the intent with derived state",
          (st_ok, made["current_state"], made["execution_source"], made["contract_version"]),
          (200, "ready", "manual", "pub.v1"))
    st_replay, replay = POST("/publications", {"slot_id": "APUB-1", "platform_key": "instagram",
                                               "idempotency_key": "api-key-4"}, headers=AUTH_KHAL)
    check("#200 exact replay returns the SAME intent (idempotent create)",
          (st_replay, replay["publication_intent_id"] == made["publication_intent_id"]), (200, True))
    st_conflict, _ = POST("/publications", {"slot_id": "APUB-1", "platform_key": "telegram",
                                            "idempotency_key": "api-key-4"}, headers=AUTH_KHAL)
    check("#200 key reuse with different bound data is HTTP 409", st_conflict, 409)
    st_dest_conflict, _ = POST("/publications", {"slot_id": "APUB-1", "platform_key": "instagram",
                                                 "idempotency_key": "api-key-4",
                                                 "destination": "@elsewhere"}, headers=AUTH_KHAL)
    check("#200 key reuse with a different destination is HTTP 409 (destination is bound)",
          st_dest_conflict, 409)
    st_done, done = POST(f"/publications/{made['publication_intent_id']}/manual-outcome",
                         {"outcome": "published", "url": "https://ig.example/p/api-1"},
                         headers=AUTH_KHAL)
    check("#200 manual attested outcome sets the occurrence + derived published state",
          (st_done, done["current_state"], done["publication_occurrence_id"] is not None,
           [e["event_type"] for e in done["events"]]),
          (200, "published (manually attested)", True,
           ["intent_created", "attempt_started", "published_manually_attested"]))
    st_again, _ = POST(f"/publications/{made['publication_intent_id']}/manual-outcome",
                       {"outcome": "published"}, headers=AUTH_KHAL)
    check("#200 second outcome on a published intent is HTTP 409", st_again, 409)
    st_list_unsigned, _ = _req("GET", "/publications?round_id=APUB")
    check("#200 unsigned list is 401", st_list_unsigned, 401)
    listed = GET("/publications?round_id=APUB", headers=AUTH_KHAL)
    check("#200 signed list returns the round's publications with history",
          (len(listed) >= 1, all("current_state" in r and "events" in r for r in listed)),
          (True, True))
    _pub_api_cleanup()
    pb.close()

    # #319 P0 — MECHANICALLY invoke the stale-rework rollback / permanent-fence proof. Importing the
    # module RUNS it; it raises SystemExit(1) on any failed check, so THIS mandatory command fails
    # when the proof fails. It is wired here rather than left standalone precisely so it cannot decay
    # into an unwired narrative harness that no gate ever executes.
    print(f"\n{'='*64}\n#319 — stale rework rollback + permanent-fence recovery proof\n{'='*64}")
    try:
        importlib.import_module("tools.proof_rework_recovery_319")
    except SystemExit as e:
        if e.code:
            FAILS.append("#319 stale-rework rollback / permanent-fence recovery proof")

    # #321 R10 — MECHANICALLY invoke the focused Topic-governance proofs as the V2 per-PR gate. The
    # pre-existing #313 per-item governance proof (previously unwired) and the new #321 hardening proof
    # (authority / lock / exact-decision / bounded-recovery / provenance / audit) both run here so they
    # cannot decay into unwired narrative harnesses. Each raises SystemExit(1) on any failed check.
    for _mod, _label in (("tools.proof_topic_item_governance_313", "#313 topic-governance proof"),
                         ("tools.proof_topic_governance_321", "#321 topic-governance hardening proof"),
                         ("tools.proof_bulk_operation_314",
                          "#314 bulk-operation + topic-presentation proof")):
        print(f"\n{'='*64}\n{_label}\n{'='*64}")
        try:
            importlib.import_module(_mod)
        except SystemExit as e:
            if e.code:
                FAILS.append(_label)

    teardown(conn)
    conn.close()
    print(f"\n{'='*64}\n{'ALL API CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}\n{'='*64}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
