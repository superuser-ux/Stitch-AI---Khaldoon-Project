"""Full-lifecycle FLOW proof (regression-protects the chain to SCHEDULED). Drives an isolated round
(RLIFE) over the live API: scripts -> script_review -> final_review (+escalate/waive/sign-off) ->
production (DAM) -> media_edit (DAM) -> distribution -> SCHEDULED, asserting the directive handoff
chain + the manual-stage DAM + the commit checkpoints. Stub writer (TANAGHOM_WRITER_STUB=1) for
determinism. Complements gates/selftest.py (engine) + gates/api_selftest.py (review/version-nav).

  docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
    -e API_BASE=http://tanaghom-gateapi:8000 -v "$PWD":/work -w /work python:3.12-slim \
    bash -lc "pip install -q -r gates/requirements.txt -r agents/requirements.txt && python gates/lifecycle_selftest.py"
"""
import json, os, sys, types, urllib.error, urllib.request
import psycopg2

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
os.environ.setdefault("TANAGHOM_WRITER_STUB", "1")
import engine            # noqa: E402
import run_writers       # noqa: E402

API = os.environ.get("API_BASE", "http://localhost:8009")
RID = "RLIFE"
SLOTS = [("RLIFE-1", "P1_SELF", "1.1"), ("RLIFE-2", "P2_RELATIONSHIPS", "2.1")]
IDS = [s[0] for s in SLOTS]
FAILS = []


def check(label, got, want):
    print(f"  [{'PASS' if got == want else 'FAIL'}] {label}: got={got} want={want}")
    if got != want:
        FAILS.append(label)


def _req(m, p, b=None):
    data = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(f"{API}{p}", data=data, method=m, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, json.load(x)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def GET(p): return _req("GET", p)[1]
def POST(p, b=None): return _req("POST", p, b or {})
def open_gate(stage, ids=None):
    return POST("/gates", {"stage": stage, "round_id": RID, "actor": "khal", **({"slot_ids": ids} if ids else {})})[1]["gate_id"]
def decide(g, who, dec, ids): POST(f"/gates/{g}/decide", {"approver_id": who, "decision": dec, "slot_ids": ids})
def commit(g, who="khal"): return POST(f"/gates/{g}/resolve", {"actor": who})[1]
def directive_to(slot, to):
    ds = [d for d in GET(f"/slots/{slot}/directives") if d["to_stage"] == to]
    return ds[-1] if ds else None
def states():
    cur = conn.cursor(); cur.execute("SELECT slot_id, status FROM slot WHERE round_id=%s", (RID,))
    return dict(cur.fetchall())


def db():
    return psycopg2.connect(host=os.environ.get("DB_HOST", "db"), port=int(os.environ.get("DB_PORT", "5432")),
                            dbname="tanaghom", user="tanaghom", password=os.environ["DB_PASSWORD"])


def teardown():
    cur = conn.cursor()
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    for t in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
        cur.execute(f"DELETE FROM {t} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RLIFE-%%'")
    cur.execute("DELETE FROM slot WHERE round_id=%s", (RID,)); cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()


def seed():
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,pillar_distribution,
                   format_distribution,status,tenant_id) VALUES (%s,'lifecycle',1,2,'["09:00"]','{}','{}','planning','lifecycle')""", (RID,))
    for sid, pillar, hcs in SLOTS:
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no,
                       topic_angle,hook_text,tenant_id) VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','TOPIC_APPROVED',1,
                       'زاوية','هوك','lifecycle')""", (sid, RID, pillar, hcs))
        cur.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,hook_text,hook_type,revision,tenant_id)
                       VALUES (%s,%s,'L1',%s,1,'زاوية','هوك','Painful Truth',1,'lifecycle')""", (sid, hcs, RID))
        cur.execute("INSERT INTO slot_approval (slot_id,artifact,revision,approver) VALUES (%s,'topic',1,'khal')", (sid,))
    conn.commit()


def main():
    global conn
    conn = db()
    teardown(); seed()
    print(f"seeded {RID}: {states()}  (API={API})")

    # generate scripts (stub) for the approved topics -> DRAFT_ASSIGNED
    run_writers.run_scripts(engine.load_config(), types.SimpleNamespace(
        slot_ids=None, round=RID, distinct_pillars=False, limit=None, dry_run=False))
    check("scripts generated -> DRAFT_ASSIGNED", sorted(set(states().values())), ["DRAFT_ASSIGNED"])

    # script_review -> APPROVED_ASSIGNED + the script->production handoff
    g = open_gate("script_review"); decide(g, "khal", "approve", IDS); commit(g)
    check("script_review advanced both -> APPROVED_ASSIGNED", states(), {i: "APPROVED_ASSIGNED" for i in IDS})
    check("script->production directive emitted for both",
          all(directive_to(s, "production") for s in IDS), True)
    d = directive_to("RLIFE-1", "production")
    check("...carries a script input + acceptance_criteria",
          bool(any(i.get("kind") == "script" for i in d["payload"]["inputs"]) and d["payload"]["acceptance_criteria"]), True)

    # native dispositions: escalate one, waive the other (governance) + sign-off; then final_review
    check("escalate native on RLIFE-1", POST("/slots/RLIFE-1/review/native/dispose", {"action": "escalate", "actor": "khal"})[0], 200)
    check("waive native on RLIFE-2 (reason required)",
          POST("/slots/RLIFE-2/review/native/dispose", {"action": "waive", "reason": "clean", "actor": "khal"})[0], 200)
    gn = open_gate("native_review")
    check("native sign-off gate targets only the escalated slot",
          [t["slot_id"] for t in GET(f"/gates/{gn}")["targets"]], ["RLIFE-1"])
    decide(gn, "nour", "approve", ["RLIFE-1"]); commit(gn, "nour")
    gf = open_gate("final_review")
    decide(gf, "khal", "approve", IDS); commit(gf)
    decide(gf, "huda", "approve", IDS); o = commit(gf)
    check("final_review (quorum all) advanced both -> READY_FOR_PRODUCTION",
          all(v == "approved" for v in o["outcomes"].values()) and states() == {i: "READY_FOR_PRODUCTION" for i in IDS}, True)

    # production (DAM raw cut) -> PRODUCED + production->media directive
    for s in IDS:
        POST(f"/slots/{s}/assets", {"stage": "production", "kind": "raw_cut", "uri": f"placeholder://raw/{s}", "actor": "khal"})
    gp = open_gate("production_review")
    check("manual stage accepted the DAM raw-cut on every target",
          all(any(a["kind"] == "raw_cut" for a in t["assets"]) for t in GET(f"/gates/{gp}")["targets"]), True)
    decide(gp, "khal", "approve", IDS); commit(gp)
    check("production advanced both -> PRODUCED", states(), {i: "PRODUCED" for i in IDS})
    md = directive_to("RLIFE-1", "media_edit")
    check("production->media directive references the raw-cut (DAM input)",
          bool(md and any(i.get("asset_kind") == "raw_cut" for i in md["payload"]["inputs"])), True)

    # media_edit (DAM edit) -> EDITED + media->distribution directive
    for s in IDS:
        POST(f"/slots/{s}/assets", {"stage": "media_edit", "kind": "edit", "uri": f"placeholder://edit/{s}", "actor": "khal"})
    ge = open_gate("edit_review"); decide(ge, "khal", "approve", IDS); commit(ge)
    check("edit advanced both -> EDITED", states(), {i: "EDITED" for i in IDS})
    check("media_edit->distribution directive emitted for both",
          all(directive_to(s, "distribution") for s in IDS), True)

    # distribution (publish hard-floor) -> SCHEDULED
    gd = open_gate("distribution_review"); decide(gd, "khal", "approve", IDS); commit(gd)
    check("distribution advanced both -> SCHEDULED (publish-ready)", states(), {i: "SCHEDULED" for i in IDS})
    check("distribution is terminal — no further handoff directive", directive_to("RLIFE-1", "published"), None)
    # the handoff chain from this round's start (TOPIC_APPROVED) onward — script->production->
    # media_edit->distribution (topic->script is emitted at the topic stage, covered by api_selftest)
    chain = {d["to_stage"] for d in GET("/slots/RLIFE-1/directives")}
    check("handoff chain present: production -> media_edit -> distribution",
          {"production", "media_edit", "distribution"} <= chain, True)

    teardown(); conn.close()
    print(f"\n{'='*64}\n{'ALL LIFECYCLE CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}\n{'='*64}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
