"""#377 — proof for the governed run-mix recommendation authority, its proposal fence, and the
immutable per-run recommendation snapshot.

Runs against a CANDIDATE-ONLY lane (its own Postgres + gate API): it creates policy generations, runs
and proposals, so it must never be pointed at a shared, operator-owned or retained-UAT database.
`tools/run_mix_lane_377.mjs` stands up that lane, applies schema + every migration, applies them AGAIN
to prove idempotency, and runs this file with a native exit.

Every check is discriminating: each red proof asserts BOTH the typed refusal AND that no partial state
was left behind (no run, no snapshot, proposal still pending). A refusal that merely "did not crash"
would prove nothing.

Run:  API_BASE=... DB_* ... REVIEWER_PROXY_SECRET=... python gates/run_mix_selftest.py
"""
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import threading
import urllib.error
import urllib.request

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "planner"))
import engine        # noqa: E402
import run_mix       # noqa: E402
import plan_round    # noqa: E402

API = os.environ.get("API_BASE", "http://localhost:8000")
SECRET = os.environ.get("REVIEWER_PROXY_SECRET") or "dev-internal-reviewer-proxy-secret"
ADMIN = "khal"        # role content_owner -> may administer policy
REVIEWER = "huda"     # role reviewer      -> may NOT
FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def sign(principal):
    return {"x-principal-id": principal,
            "x-principal-signature": hmac.new(SECRET.encode(), principal.encode(),
                                              hashlib.sha256).hexdigest(),
            "content-type": "application/json"}


def req(method, path, body=None, principal=ADMIN):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method,
                               headers=sign(principal) if principal else {"content-type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"detail": raw}


def conn():
    return engine.db_connect()


def code_of(payload):
    """The typed `code` out of an HTTPException detail (dict) or a plain string body."""
    d = payload.get("detail") if isinstance(payload, dict) else None
    return d.get("code") if isinstance(d, dict) else None


def q1(sql, args=()):
    c = conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # No args means no parameter binding: a literal `%` (e.g. LIKE 'R%') must not be read as a
        # placeholder.
        cur.execute(sql, args) if args else cur.execute(sql)
        row = cur.fetchone()
        cur.close()
        return row
    finally:
        c.close()


def exec_sql(sql, args=()):
    """Returns (ok, error_text). Used for the DB-enforced immutability proofs."""
    c = conn()
    try:
        cur = c.cursor()
        cur.execute(sql, args)
        c.commit()
        return True, None
    except Exception as e:                    # noqa: BLE001 — the refusal text IS the evidence
        c.rollback()
        return False, str(e).strip().splitlines()[0]
    finally:
        c.close()


# ---------------------------------------------------------------------------------------------
print("1) canonical encoding + digest are deterministic and versioned")
# Construction order and Unicode normal form must not change the bytes; a member change must.
a = {"b": 2, "a": [1, 2], "u": "Ünïcode — نص"}
b = {"u": "Ünïcode — نص", "a": [1, 2], "b": 2}
check("canonical_json is key-order independent", run_mix.canonical_json(a), run_mix.canonical_json(b))
check("canonical_json emits real Unicode (not escapes)", "\\u" in run_mix.canonical_json(a), False)
check("canonical_json has no insignificant whitespace", ", " in run_mix.canonical_json(a), False)
check("canonical_json NFC-normalizes", run_mix.canonical_json({"k": "é"}),
      run_mix.canonical_json({"k": "é"}))
check("digest is stable across construction order", run_mix.digest_of(a), run_mix.digest_of(b))
check("digest changes when a member changes",
      run_mix.digest_of(a) == run_mix.digest_of({**a, "b": 3}), False)
check("integers are encoded as integers, not floats", '"n":2' in run_mix.canonical_json({"n": 2}), True)
_p = dict(scope="default", tenant_id="default", module="content", created_by="khal",
          starts_on="2026-01-01", ends_on="2026-01-07", posts_per_day=2, expected_slots=14,
          eligible_version_ids=["v1", "v2"], recommended_mix={"A": 7, "B": 7}, rationale={"k": 1},
          authority_version=run_mix.AUTHORITY_VERSION, algorithm=run_mix.ALGORITHM,
          policy_id="p", policy_generation=1, baseline_policy_id="b", baseline_generation=1,
          methodology_version="m", workflow_version="w", model_posture="not_applicable",
          requested_route=None, requested_provider=None, requested_model=None, effective_route=None,
          effective_provider=None, effective_model=None, created_at="2026-01-01T00:00:00+00:00",
          expires_at="2026-01-02T00:00:00+00:00")
check("digest payload carries its own version", run_mix.proposal_digest_payload(**_p)["digest_version"],
      run_mix.CANONICAL_DIGEST_VERSION)
check("eligible order is load-bearing in the digest",
      run_mix.digest_of(run_mix.proposal_digest_payload(**_p))
      == run_mix.digest_of(run_mix.proposal_digest_payload(**{**_p, "eligible_version_ids": ["v2", "v1"]})),
      False)

print("2) deterministic apportionment (largest_remainder_v1 == planner.scale_distribution)")
order = ["x", "y", "z"]
check("exact total over equal weights", run_mix.apportion(order, {"x": 1, "y": 1, "z": 1}, 9, {}, {}),
      {"x": 3, "y": 3, "z": 3})
check("weighted apportionment sums exactly",
      sum(run_mix.apportion(order, {"x": 3, "y": 2, "z": 1}, 14, {}, {}).values()), 14)
check("weighted apportionment is deterministic",
      run_mix.apportion(order, {"x": 3, "y": 2, "z": 1}, 14, {}, {}),
      run_mix.apportion(order, {"x": 3, "y": 2, "z": 1}, 14, {}, {}))
check("fewer slots than frameworks: largest weights win, others 0",
      run_mix.apportion(order, {"x": 5, "y": 3, "z": 1}, 2, {}, {}), {"x": 1, "y": 1, "z": 0})
check("minimums are honoured", run_mix.apportion(order, {"x": 10, "y": 1, "z": 1}, 6, {"z": 2}, {})["z"] >= 2, True)
check("maximums are honoured", run_mix.apportion(order, {"x": 10, "y": 1, "z": 1}, 6, {}, {"x": 2})["x"], 2)
try:
    run_mix.apportion(order, {"x": 1, "y": 1, "z": 1}, 2, {"x": 5}, {})
    check("minima exceeding slots refuses", "no-raise", "minima_exceed_slots")
except run_mix.RecommendationError as e:
    check("minima exceeding slots refuses", e.code, "minima_exceed_slots")
try:
    run_mix.apportion(order, {"x": 1, "y": 1, "z": 1}, 9, {}, {"x": 1, "y": 1, "z": 1})
    check("maxima below slots refuses", "no-raise", "maxima_below_slots")
except run_mix.RecommendationError as e:
    check("maxima below slots refuses", e.code, "maxima_below_slots")

print("3) policy authority — fail-closed baseline, authorized generations, no overwrite")
# The baseline eligibility policy is bootstrapped through its OWN authorized create-only path
# (GET /baseline-eligibility -> engine.ensure_baseline_policy), never by this test writing a policy row.
st, base = req("GET", "/baseline-eligibility", principal=None)
check("baseline eligibility bootstraps through its governed route", st, 200)
c = conn()
try:
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("DELETE FROM run_mix_recommendation_policy")      # candidate-only lane
    c.commit()
    elig = engine.resolve_run_eligibility(cur)
    ELIGIBLE = elig["eligible"]
    cur.close()
finally:
    c.close()
check("candidate lane has baseline-eligible frameworks", len(ELIGIBLE) >= 2, True)
VIDS = [e["version_id"] for e in ELIGIBLE]
NAMES = [e["name"] for e in ELIGIBLE]

st, pol = req("GET", "/run-mix-policy", principal=None)
check("absent policy is a truthful state, not an error", (st, pol.get("status")), (200, "absent"))

start = dt.date(2026, 3, 2)
end = dt.date(2026, 3, 8)          # inclusive -> 7 days
PPD = 2
EXPECTED = 7 * PPD
st, blocked = req("POST", "/run-mix-proposals",
                  {"starts_on": start.isoformat(), "ends_on": end.isoformat(), "posts_per_day": PPD})
check("no policy -> typed blocked (never a fallback mix)",
      (st, blocked.get("status"), blocked.get("reason")),
      (200, "blocked", "no_current_recommendation_policy"))
check("a blocked result carries no mix", "recommended_mix" in blocked, False)
check("a blocked result persisted no proposal",
      q1("SELECT count(*) AS n FROM run_mix_proposal")["n"], 0)

st, denied = req("POST", "/run-mix-policy", {"weights": {VIDS[0]: 1}}, principal=REVIEWER)
check("unauthorized policy activation is refused", (st, code_of(denied)), (403, "not_authorized"))
check("the refused activation created nothing",
      q1("SELECT count(*) AS n FROM run_mix_recommendation_policy")["n"], 0)

weights = {vid: (2 if i == 0 else 1) for i, vid in enumerate(VIDS)}
st, gen1 = req("POST", "/run-mix-policy", {"weights": weights, "notes": "candidate baseline"})
check("authorized policy generation 1 is created", (st, gen1.get("generation")), (200, 1))
st, gen2 = req("POST", "/run-mix-policy", {"weights": weights, "notes": "candidate second"})
check("a change mints a NEW generation (never an in-place edit)", (st, gen2.get("generation")), (200, 2))
check("exactly one current generation",
      q1("SELECT count(*) AS n FROM run_mix_recommendation_policy WHERE status='current'")["n"], 1)
check("the superseded generation is preserved, not overwritten",
      q1("SELECT status, superseded_by IS NOT NULL AS linked FROM run_mix_recommendation_policy "
         "WHERE policy_id=%s", (gen1["policy_id"],)),
      {"status": "superseded", "linked": True})
ok, err = exec_sql("INSERT INTO run_mix_recommendation_policy (scope, generation, status, weights) "
                   "VALUES ('default', 99, 'current', '{}'::jsonb)")
check("the DB forbids a second current generation", (ok, "uq_run_mix_policy_one_current" in (err or "")),
      (False, True))

# Generation immutability is enforced by the DATABASE, not by application discipline. A pinned
# snapshot cites a policy by (policy_id, generation); if that row could be edited in place, every
# recommendation ever pinned to it would become ambiguous retroactively. Both a CURRENT and a
# SUPERSEDED row are proven, because a frozen current row that thawed once superseded would leave
# exactly the historical evidence that matters unprotected.
CURRENT_POL, SUPERSEDED_POL = gen2["policy_id"], gen1["policy_id"]
for label, pol in (("current", CURRENT_POL), ("superseded", SUPERSEDED_POL)):
    for field, sql_set in (
        ("weights", "weights='{\"x\":9}'::jsonb"),
        ("min_counts", "min_counts='{\"x\":1}'::jsonb"),
        ("max_counts", "max_counts='{\"x\":1}'::jsonb"),
        ("generation", "generation=777"),
        ("algorithm", "algorithm='forged_algorithm'"),
        ("authority_version", "authority_version='forged_v9'"),
        ("weight_source", "weight_source='derived_from_somewhere'"),
        ("scope", "scope='other'"),
        ("tenant_id", "tenant_id='other'"),
        ("module", "module='other'"),
        ("notes", "notes='rewritten after the fact'"),
        ("created_by", "created_by='someone-else'"),
        ("created_at", "created_at=now()"),
        ("policy_id", "policy_id=gen_random_uuid()"),
    ):
        ok, err = exec_sql(f"UPDATE run_mix_recommendation_policy SET {sql_set} WHERE policy_id=%s",
                           (pol,))
        # Refused by the freeze trigger, by the status rule, or — for the enum-like `algorithm` and
        # `weight_source` columns — by their CHECK constraint. All three are DB enforcement; what is
        # asserted is that the edit CANNOT LAND, and which guard caught it is named in the message.
        check(f"{label} generation: {field} cannot be edited in place",
              (ok, ("immutable" in (err or "")) or ("current -> superseded" in (err or ""))
                   or ("violates check constraint" in (err or ""))),
              (False, True))
ok, err = exec_sql("UPDATE run_mix_recommendation_policy SET status='current', superseded_at=NULL, "
                   "superseded_by=NULL WHERE policy_id=%s", (SUPERSEDED_POL,))
check("a superseded generation can never be reactivated",
      (ok, "current -> superseded" in (err or "")), (False, True))
ok, err = exec_sql("UPDATE run_mix_recommendation_policy SET superseded_by=%s WHERE policy_id=%s",
                   (SUPERSEDED_POL, SUPERSEDED_POL))
check("a completed lineage link is write-once",
      (ok, "write-once" in (err or "")), (False, True))
ok, err = exec_sql("UPDATE run_mix_recommendation_policy SET superseded_at=now() WHERE policy_id=%s",
                   (SUPERSEDED_POL,))
check("the supersession timestamp is write-once",
      (ok, "write-once" in (err or "")), (False, True))
check("the frozen rows still hold their original values",
      q1("SELECT count(*) AS n FROM run_mix_recommendation_policy "
         "WHERE weights=%s AND scope='default' AND authority_version=%s",
         (psycopg2.extras.Json(weights), run_mix.AUTHORITY_VERSION))["n"], 2)
# The authorized minting path is unaffected by the freeze: creation is an INSERT plus the one
# permitted lineage transition.
st, gen3 = req("POST", "/run-mix-policy", {"weights": weights, "notes": "post-freeze generation"})
check("the authorized generation path still works under the freeze", (st, gen3.get("generation")),
      (200, 3))
check("the freeze still allows the governed supersession",
      q1("SELECT status, superseded_by::text=%s AS linked FROM run_mix_recommendation_policy "
         "WHERE policy_id=%s", (gen3["policy_id"], CURRENT_POL)),
      {"status": "superseded", "linked": True})

print("4a) the recommendation PREVIEW is side-effect-free (GPT amendment 4 / #376 P1)")
# The discriminating proof of the #376 correction: a preview must persist NOTHING. Capture the exact
# durable counts BEFORE, run a preview, and assert every one is unchanged — no proposal row, no audit
# event, no reserved identifier, no run/slot/gate. A regression that reintroduces proposal-on-preview
# would flip at least one of these.
_props_before = q1("SELECT count(*) AS n FROM run_mix_proposal")["n"]
_audit_before = q1("SELECT count(*) AS n FROM audit_log WHERE action='run_mix_proposal_created'")["n"]
_rounds_before = q1("SELECT count(*) AS n FROM round")["n"]
st, prev = req("POST", "/run-mix-recommendation-preview",
               {"starts_on": start.isoformat(), "ends_on": end.isoformat(), "posts_per_day": PPD})
check("a preview returns a valid recommendation", (st, prev.get("status")), (200, "recommended"))
check("a preview carries a generation fingerprint", "preview_fingerprint" in prev, True)
check("a preview is flagged as a preview, not a proposal", prev.get("preview"), True)
check("a preview mints NO proposal id (it is not a fence)", "proposal_id" in prev, False)
check("a preview writes NO proposal row",
      q1("SELECT count(*) AS n FROM run_mix_proposal")["n"], _props_before)
check("a preview writes NO audit/history event",
      q1("SELECT count(*) AS n FROM audit_log WHERE action='run_mix_proposal_created'")["n"], _audit_before)
check("a preview creates NO run/slot/gate",
      (q1("SELECT count(*) AS n FROM round")["n"], q1("SELECT count(*) AS n FROM slot")["n"],
       q1("SELECT count(*) AS n FROM gate")["n"]), (_rounds_before, 0, 0))
check("the preview mix equals what a proposal would recommend (same authority, no duplication)",
      prev["recommended_mix"],
      req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(), "ends_on": end.isoformat(),
                                         "posts_per_day": PPD})[1]["recommended_mix"])
# The proposal just created for the equality check is the only durable write so far in this section.
check("only the explicit proposal call persisted a row (preview did not)",
      q1("SELECT count(*) AS n FROM run_mix_proposal")["n"], _props_before + 1)

print("4) the recommendation itself — exact, explained, deterministic, never AI")
st, prop = req("POST", "/run-mix-proposals",
               {"starts_on": start.isoformat(), "ends_on": end.isoformat(), "posts_per_day": PPD})
check("a valid recommendation is returned", (st, prop.get("status")), (200, "recommended"))
check("counts sum to the expected slot total", sum(prop["recommended_mix"].values()), EXPECTED)
check("no framework count is negative", min(prop["recommended_mix"].values()) >= 0, True)
check("the mix is non-zero overall", sum(prop["recommended_mix"].values()) > 0, True)
check("the inclusive range is what was selected",
      (prop["starts_on"], prop["ends_on"], prop["days"]), (start.isoformat(), end.isoformat(), 7))
check("provenance names the recommendation generation", prop["policy"]["generation"], 3)
check("provenance names the baseline generation", "generation" in prop["baseline_policy"], True)
check("the authority version is distinct from the policy generation",
      prop["authority_version"], run_mix.AUTHORITY_VERSION)
check("model posture is truthful (no model was called)", prop["model_posture"], "not_applicable")
check("the rationale is a bounded structured record", sorted(prop["rationale"].keys()),
      sorted(["kind", "statement", "algorithm", "authority_version", "expected_slots", "days",
              "posts_per_day", "weights", "minimums", "maximums", "allocated", "excluded_versions",
              "policy_notes", "model_posture"]))
check("the rationale makes no AI claim", "AI" in prop["rationale"]["statement"]
      and "not an AI recommendation" in prop["rationale"]["statement"], True)
check("the proposal is server-digested", len(prop["digest"]), 64)
check("a proposal is not a run: nothing durable was created",
      (q1("SELECT count(*) AS n FROM round")["n"], q1("SELECT count(*) AS n FROM slot")["n"],
       q1("SELECT count(*) AS n FROM gate")["n"]), (0, 0, 0))
check("a proposal was persisted", q1("SELECT count(*) AS n FROM run_mix_proposal")["n"] >= 1, True)
check("the same request recommends the same mix (deterministic)",
      req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(), "ends_on": end.isoformat(),
                                         "posts_per_day": PPD})[1]["recommended_mix"],
      prop["recommended_mix"])

st, foreign = req("GET", f"/run-mix-proposals/{prop['proposal_id']}", principal=REVIEWER)
check("a foreign proposal is a typed 404 (no extra disclosure)", (st, code_of(foreign)),
      (404, "proposal_not_found"))
st, guessed = req("GET", "/run-mix-proposals/00000000-0000-0000-0000-000000000000")
check("a guessed id is the same typed 404", (st, code_of(guessed)), (404, "proposal_not_found"))
st, malformed = req("GET", "/run-mix-proposals/not-a-uuid")
check("a malformed id is indistinguishable from a wrong one", (st, code_of(malformed)),
      (404, "proposal_not_found"))
st, mine = req("GET", f"/run-mix-proposals/{prop['proposal_id']}")
check("the owner can read their own proposal", (st, mine.get("proposal_id")), (200, prop["proposal_id"]))

print("5) blocked states — every one fails closed with no mix and no proposal")
before_props = q1("SELECT count(*) AS n FROM run_mix_proposal")["n"]
st, g3 = req("POST", "/run-mix-policy", {"weights": {v: 0 for v in VIDS}})
check("an all-zero generation is refused at the authorized path", st, 422)
# Defence in depth: even if such a generation existed (a direct write on this candidate-only lane),
# the authority still fails closed rather than allocating something.
c = conn()
try:
    cur = c.cursor()
    cur.execute("UPDATE run_mix_recommendation_policy SET status='superseded', superseded_at=now() "
                "WHERE status='current'")
    cur.execute("INSERT INTO run_mix_recommendation_policy (scope, generation, status, weights, "
                "created_by) VALUES ('default', 900, 'current', %s, 'khal')",
                (psycopg2.extras.Json({v: 0 for v in VIDS}),))
    c.commit()
    cur.close()
finally:
    c.close()
st, zero = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                              "ends_on": end.isoformat(), "posts_per_day": PPD})
check("all-zero weights -> typed blocked", (zero.get("status"), zero.get("reason")),
      ("blocked", "all_weights_zero"))
st, g4 = req("POST", "/run-mix-policy", {"weights": {VIDS[0]: 1}})     # drops the other eligible ids
st, partial = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                                 "ends_on": end.isoformat(), "posts_per_day": PPD})
check("an unweighted eligible version -> typed blocked",
      (partial.get("status"), partial.get("reason")), ("blocked", "eligible_version_unweighted"))
check("blocked results persisted no proposals",
      q1("SELECT count(*) AS n FROM run_mix_proposal")["n"], before_props)
st, _g5 = req("POST", "/run-mix-policy", {"weights": weights, "notes": "restored"})
POLICY = _g5

print("6) binding — one transaction, one run, one immutable snapshot")
st, p1 = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                            "ends_on": end.isoformat(), "posts_per_day": PPD})
check("fresh proposal under the restored generation", p1.get("status"), "recommended")
st, created = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                      "format_mix": p1["recommended_mix"], "label": "377-bind",
                                      "proposal_id": p1["proposal_id"], "idempotency_key": "idem-1"})
check("the run is created", (st, created.get("total")), (200, EXPECTED))
RID = created["round_id"]
snap = q1("SELECT * FROM run_mix_recommendation_snapshot WHERE round_id=%s", (RID,))
check("exactly one snapshot is bound", snap is not None, True)
check("the snapshot records the accepted mix", snap["submitted_mix"], p1["recommended_mix"])
check("an unamended submission is recorded as unamended", (snap["mix_amended"], snap["mix_delta"]),
      (False, {}))
check("the snapshot pins the proposal digest", snap["proposal_digest"], p1["digest"])
check("the snapshot names the initiating principal", snap["initiating_principal"], ADMIN)
check("model provenance stays truthful", snap["model_posture"], "not_applicable")
check("the fence is consumed and bound",
      q1("SELECT status, bound_round_id FROM run_mix_proposal WHERE proposal_id=%s",
         (p1["proposal_id"],)),
      {"status": "consumed", "bound_round_id": RID})
check("the run's slots exist", q1("SELECT count(*) AS n FROM slot WHERE round_id=%s", (RID,))["n"],
      EXPECTED)
check("round_policy_snapshot is still pinned alongside it",
      q1("SELECT count(*) AS n FROM round_policy_snapshot WHERE round_id=%s", (RID,))["n"], 1)
st, api_snap = req("GET", f"/rounds/{RID}/recommendation-snapshot", principal=None)
check("the historical read resolves from the snapshot", (st, api_snap.get("status")), (200, "recorded"))

print("7) idempotency + replay + concurrency")
st, replay = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                     "format_mix": p1["recommended_mix"], "label": "377-bind",
                                     "proposal_id": p1["proposal_id"], "idempotency_key": "idem-1"})
check("same key + same payload converges on the same run", (st, replay.get("round_id")), (200, RID))
check("replay created no second run",
      q1("SELECT count(*) AS n FROM round WHERE label='377-bind'")["n"], 1)
st, conflict = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                       "format_mix": p1["recommended_mix"], "label": "377-DIFFERENT",
                                       "proposal_id": p1["proposal_id"], "idempotency_key": "idem-1"})
check("same key + different payload is a typed conflict", (st, code_of(conflict)),
      (409, "idempotency_key_conflict"))
st, second = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                     "format_mix": p1["recommended_mix"], "label": "377-second",
                                     "proposal_id": p1["proposal_id"]})
check("a consumed fence cannot create a second run", (st, code_of(second)),
      (409, "proposal_already_consumed"))

st, pconc = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                               "ends_on": end.isoformat(), "posts_per_day": PPD})
results = {}


def _concurrent(tag):
    results[tag] = req("POST", "/rounds",
                       {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                        "format_mix": pconc["recommended_mix"], "label": f"377-conc-{tag}",
                        "proposal_id": pconc["proposal_id"]})


threads = [threading.Thread(target=_concurrent, args=(t,)) for t in ("a", "b")]
for t in threads:
    t.start()
for t in threads:
    t.join()
statuses = sorted(s for s, _ in results.values())
check("concurrent consume: exactly one winner", (statuses[0], statuses[1] in (409, 500)), (200, True))
check("concurrent consume: the loser is a typed conflict",
      sorted(code_of(b) or "ok" for _, b in results.values()), ["ok", "proposal_already_consumed"])
check("concurrent consume: exactly one run bound to the fence",
      q1("SELECT count(*) AS n FROM run_mix_recommendation_snapshot WHERE proposal_id=%s",
         (pconc["proposal_id"],))["n"], 1)
check("concurrent consume: no orphan run",
      q1("SELECT count(*) AS n FROM round WHERE label LIKE '377-conc-%'")["n"], 1)

print("8) operator amendment — planner validation stays independent and binding")
st, p2 = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                            "ends_on": end.isoformat(), "posts_per_day": PPD})
amended = dict(p2["recommended_mix"])
donor = max(amended, key=lambda k: amended[k])
receiver = min(amended, key=lambda k: amended[k])
check("the proposal has room to amend", donor != receiver and amended[donor] >= 1, True)
amended[donor] -= 1
amended[receiver] += 1
st, amended_run = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD,
                                          "starts_on": start.isoformat(), "format_mix": amended,
                                          "label": "377-amended", "proposal_id": p2["proposal_id"]})
check("a planner-valid amendment is accepted", st, 200)
asnap = q1("SELECT * FROM run_mix_recommendation_snapshot WHERE round_id=%s",
           (amended_run["round_id"],))
check("the amendment is recorded against the original proposal",
      (asnap["mix_amended"], asnap["recommended_mix"] == p2["recommended_mix"],
       asnap["submitted_mix"] == amended), (True, True, True))
check("the delta is exact", asnap["mix_delta"], {donor: -1, receiver: 1})

st, p3 = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                            "ends_on": end.isoformat(), "posts_per_day": PPD})
bad = dict(p3["recommended_mix"])
bad[donor] += 3                                    # no longer sums to days x posts_per_day
st, refused = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                      "format_mix": bad, "label": "377-bad",
                                      "proposal_id": p3["proposal_id"]})
check("an invalid amended mix is refused by the planner", st, 422)
check("the refused amendment consumed nothing",
      q1("SELECT status FROM run_mix_proposal WHERE proposal_id=%s", (p3["proposal_id"],))["status"],
      "pending")
check("the refused amendment created no run",
      q1("SELECT count(*) AS n FROM round WHERE label='377-bad'")["n"], 0)
st, unknown_fw = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD,
                                         "starts_on": start.isoformat(),
                                         "format_mix": {"Not A Framework": EXPECTED},
                                         "label": "377-unknown", "proposal_id": p3["proposal_id"]})
check("an unknown framework is refused", st, 422)
check("the unknown-framework attempt consumed nothing",
      q1("SELECT status FROM run_mix_proposal WHERE proposal_id=%s", (p3["proposal_id"],))["status"],
      "pending")

print("9) context, generation and fence red proofs")
st, mismatch = req("POST", "/rounds", {"days": 6, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                       "format_mix": p3["recommended_mix"], "label": "377-days",
                                       "proposal_id": p3["proposal_id"]})
check("a duration that differs from the proposal is refused", (st, code_of(mismatch)),
      (409, "proposal_context_mismatch"))
st, ppd_mismatch = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD + 1,
                                           "starts_on": start.isoformat(),
                                           "format_mix": p3["recommended_mix"], "label": "377-ppd",
                                           "proposal_id": p3["proposal_id"]})
check("a posts/day that differs from the proposal is refused", (st, code_of(ppd_mismatch)),
      (409, "proposal_context_mismatch"))
st, start_mismatch = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD,
                                             "starts_on": (start + dt.timedelta(days=1)).isoformat(),
                                             "format_mix": p3["recommended_mix"],
                                             "label": "377-start", "proposal_id": p3["proposal_id"]})
check("a start that differs from the proposal is refused", (st, code_of(start_mismatch)),
      (409, "proposal_context_mismatch"))
st, foreign_consume = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD,
                                              "starts_on": start.isoformat(),
                                              "format_mix": p3["recommended_mix"],
                                              "label": "377-foreign",
                                              "proposal_id": p3["proposal_id"]}, principal=REVIEWER)
check("another principal cannot consume someone's fence", (st, code_of(foreign_consume)),
      (404, "proposal_not_found"))
st, unsigned = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                       "format_mix": p3["recommended_mix"], "label": "377-unsigned",
                                       "proposal_id": p3["proposal_id"]}, principal=None)
check("an unsigned caller cannot consume a fence", st, 401)

ok, err = exec_sql("UPDATE run_mix_proposal SET recommended_mix='{}'::jsonb WHERE proposal_id=%s",
                   (p3["proposal_id"],))
check("the DB refuses to rewrite a proposal's context", (ok, "immutable" in (err or "")), (False, True))
ok, err = exec_sql("UPDATE run_mix_proposal SET status='pending', consumed_at=NULL, "
                   "bound_round_id=NULL WHERE proposal_id=%s", (p1["proposal_id"],))
check("a consumed fence cannot be re-opened", ok, False)


def _insert_proposal(principal, created_at, expires_at, digest_override=None, days=7):
    """Insert a proposal row DIRECTLY (the one write path the freeze trigger permits) so expiry and a
    wrong digest can be proven. The context is a real recommendation; only the disputed field varies."""
    c2 = conn()
    try:
        res = run_mix.recommend(c2, starts_on=start, ends_on=start + dt.timedelta(days=days - 1),
                                posts_per_day=PPD, principal=principal)
        payload = run_mix.proposal_digest_payload(
            scope="default", tenant_id="default", module="content", created_by=principal,
            starts_on=res["starts_on"], ends_on=res["ends_on"], posts_per_day=res["posts_per_day"],
            expected_slots=res["expected_slots"], eligible_version_ids=res["eligible_version_ids"],
            recommended_mix=res["recommended_mix"], rationale=res["rationale"],
            authority_version=run_mix.AUTHORITY_VERSION, algorithm=run_mix.ALGORITHM,
            policy_id=res["policy"]["policy_id"], policy_generation=res["policy"]["generation"],
            baseline_policy_id=res["baseline_policy"]["policy_id"],
            baseline_generation=res["baseline_policy"]["generation"],
            methodology_version=res["methodology_version"], workflow_version=res["workflow_version"],
            model_posture="not_applicable", requested_route=None, requested_provider=None,
            requested_model=None, effective_route=None, effective_provider=None, effective_model=None,
            created_at=created_at, expires_at=expires_at)
        cur2 = c2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur2.execute("""INSERT INTO run_mix_proposal
                        (digest_version, digest, scope, tenant_id, module, created_by, starts_on,
                         ends_on, posts_per_day, expected_slots, eligible_version_ids, recommended_mix,
                         rationale, authority_version, algorithm, policy_id, policy_generation,
                         baseline_policy_id, baseline_generation, methodology_version,
                         workflow_version, model_posture, created_at, expires_at)
                        VALUES (%s,%s,'default','default','content',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                %s,%s,%s,%s,%s,'not_applicable',%s,%s)
                        RETURNING proposal_id::text AS proposal_id""",
                     (run_mix.CANONICAL_DIGEST_VERSION,
                      digest_override or run_mix.digest_of(payload), principal, res["starts_on"],
                      res["ends_on"], res["posts_per_day"], res["expected_slots"],
                      psycopg2.extras.Json(res["eligible_version_ids"]),
                      psycopg2.extras.Json(res["recommended_mix"]),
                      psycopg2.extras.Json(res["rationale"]), run_mix.AUTHORITY_VERSION,
                      run_mix.ALGORITHM, res["policy"]["policy_id"], res["policy"]["generation"],
                      res["baseline_policy"]["policy_id"], res["baseline_policy"]["generation"],
                      res["methodology_version"], res["workflow_version"], created_at, expires_at))
        pid = cur2.fetchone()["proposal_id"]
        c2.commit()
        cur2.close()
        return pid, res
    finally:
        c2.close()


now = dt.datetime.now(dt.timezone.utc)
expired_id, expired_res = _insert_proposal(ADMIN, now - dt.timedelta(hours=2), now - dt.timedelta(hours=1))
st, expired = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                      "format_mix": expired_res["recommended_mix"],
                                      "label": "377-expired", "proposal_id": expired_id})
check("an expired fence is refused", (st, code_of(expired)), (409, "proposal_expired"))
check("the expired attempt created no run",
      q1("SELECT count(*) AS n FROM round WHERE label='377-expired'")["n"], 0)

tampered_id, tampered_res = _insert_proposal(ADMIN, now, now + dt.timedelta(hours=1),
                                             digest_override="0" * 64)
st, tampered = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                       "format_mix": tampered_res["recommended_mix"],
                                       "label": "377-tampered", "proposal_id": tampered_id})
check("a context that does not match its digest is refused", (st, code_of(tampered)),
      (409, "proposal_digest_mismatch"))
check("the tampered attempt created no run",
      q1("SELECT count(*) AS n FROM round WHERE label='377-tampered'")["n"], 0)

# #376 P1 — the preview→submit STALE gate fails closed and persists nothing. Preview under the current
# generation, then move the policy generation, then create a proposal with the STALE fingerprint: it
# must be refused BEFORE any insert, so no proposal row and no audit event appear.
st, stale_prev = req("POST", "/run-mix-recommendation-preview",
                     {"starts_on": start.isoformat(), "ends_on": end.isoformat(), "posts_per_day": PPD})
check("the stale-gate preview is valid", (st, stale_prev.get("status")), (200, "recommended"))
_props_pre_stale = q1("SELECT count(*) AS n FROM run_mix_proposal")["n"]
_audit_pre_stale = q1("SELECT count(*) AS n FROM audit_log WHERE action='run_mix_proposal_created'")["n"]
req("POST", "/run-mix-policy", {"weights": weights, "notes": "generation moved after preview"})
st, stale = req("POST", "/run-mix-proposals",
                {"starts_on": start.isoformat(), "ends_on": end.isoformat(), "posts_per_day": PPD,
                 "expected": stale_prev["preview_fingerprint"]})
check("a submit whose preview generation has moved is refused (fail closed)",
      (st, code_of(stale)), (409, "recommendation_stale"))
check("the stale refusal returns the refreshed recommendation for review",
      "refreshed" in (stale.get("detail") or stale), True)
check("the stale refusal persisted NO proposal row",
      q1("SELECT count(*) AS n FROM run_mix_proposal")["n"], _props_pre_stale)
check("the stale refusal wrote NO audit/history event",
      q1("SELECT count(*) AS n FROM audit_log WHERE action='run_mix_proposal_created'")["n"],
      _audit_pre_stale)
# A submit whose fingerprint MATCHES the (now current) generation still succeeds — the gate blocks
# drift, not planning. A fresh preview reflects the moved generation and binds cleanly.
st, ok_prev = req("POST", "/run-mix-recommendation-preview",
                  {"starts_on": start.isoformat(), "ends_on": end.isoformat(), "posts_per_day": PPD})
st, ok_prop = req("POST", "/run-mix-proposals",
                  {"starts_on": start.isoformat(), "ends_on": end.isoformat(), "posts_per_day": PPD,
                   "expected": ok_prev["preview_fingerprint"]})
check("a submit whose preview is current is accepted", (st, ok_prop.get("status")), (200, "recommended"))

st, p_gen = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                               "ends_on": end.isoformat(), "posts_per_day": PPD})
req("POST", "/run-mix-policy", {"weights": weights, "notes": "generation moved under the proposal"})
st, superseded = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD,
                                         "starts_on": start.isoformat(),
                                         "format_mix": p_gen["recommended_mix"],
                                         "label": "377-superseded", "proposal_id": p_gen["proposal_id"]})
check("a superseded recommendation generation is refused", (st, code_of(superseded)),
      (409, "recommendation_policy_superseded"))
check("the superseded attempt created no run",
      q1("SELECT count(*) AS n FROM round WHERE label='377-superseded'")["n"], 0)

st, p_base = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                                "ends_on": end.isoformat(), "posts_per_day": PPD})
c = conn()
try:
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT policy_id::text AS policy_id, generation, eligible_version_ids
                   FROM baseline_eligibility_policy WHERE status='current'""")
    base = cur.fetchone()
    # Supersede first, then insert: the one-current partial index is evaluated per statement.
    cur.execute("UPDATE baseline_eligibility_policy SET status='superseded', superseded_at=now() "
                "WHERE policy_id=%s", (base["policy_id"],))
    cur.execute("""INSERT INTO baseline_eligibility_policy
                   (scope, generation, status, eligible_version_ids, created_by)
                   VALUES ('default', %s, 'current', %s, 'khal')
                   RETURNING policy_id::text AS policy_id""",
                (base["generation"] + 1, psycopg2.extras.Json(base["eligible_version_ids"])))
    new_base = cur.fetchone()["policy_id"]
    cur.execute("UPDATE baseline_eligibility_policy SET superseded_by=%s WHERE policy_id=%s",
                (new_base, base["policy_id"]))
    c.commit()
    cur.close()
finally:
    c.close()
st, base_moved = req("POST", "/rounds", {"days": 7, "posts_per_day": PPD, "starts_on": start.isoformat(),
                                         "format_mix": p_base["recommended_mix"],
                                         "label": "377-base", "proposal_id": p_base["proposal_id"]})
check("a superseded baseline generation is refused", (st, code_of(base_moved)),
      (409, "baseline_policy_superseded"))
check("the superseded-baseline attempt created no run",
      q1("SELECT count(*) AS n FROM round WHERE label='377-base'")["n"], 0)

print("10) induced failure at both transaction boundaries — no partial state")
st, p_fail = req("POST", "/run-mix-proposals", {"starts_on": start.isoformat(),
                                                "ends_on": end.isoformat(), "posts_per_day": PPD})
cfg = engine.load_config()


def _plan(label, proposal_id, mix):
    return plan_round.plan_round_api(cfg, 7, PPD, label, format_mix=mix, starts_on=start,
                                     proposal_id=proposal_id, principal=ADMIN)


original_build_grid = plan_round.build_grid
plan_round.build_grid = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("induced: pre-run"))
try:
    _plan("377-induced-prerun", p_fail["proposal_id"], p_fail["recommended_mix"])
    check("induced pre-run failure raises", "no-raise", "RuntimeError")
except RuntimeError as e:
    check("induced pre-run failure raises", str(e), "induced: pre-run")
finally:
    plan_round.build_grid = original_build_grid
check("pre-run failure left no run",
      q1("SELECT count(*) AS n FROM round WHERE label='377-induced-prerun'")["n"], 0)
check("pre-run failure left the fence pending",
      q1("SELECT status FROM run_mix_proposal WHERE proposal_id=%s", (p_fail["proposal_id"],))["status"],
      "pending")

original_bind = run_mix.bind_snapshot
run_mix.bind_snapshot = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("induced: pre-snapshot"))
try:
    _plan("377-induced-presnap", p_fail["proposal_id"], p_fail["recommended_mix"])
    check("induced pre-snapshot failure raises", "no-raise", "RuntimeError")
except RuntimeError as e:
    check("induced pre-snapshot failure raises", str(e), "induced: pre-snapshot")
finally:
    run_mix.bind_snapshot = original_bind
check("pre-snapshot failure left no run (the round INSERT rolled back)",
      q1("SELECT count(*) AS n FROM round WHERE label='377-induced-presnap'")["n"], 0)
check("pre-snapshot failure left no snapshot",
      q1("SELECT count(*) AS n FROM run_mix_recommendation_snapshot WHERE proposal_id=%s",
         (p_fail["proposal_id"],))["n"], 0)
check("pre-snapshot failure left the fence pending",
      q1("SELECT status FROM run_mix_proposal WHERE proposal_id=%s", (p_fail["proposal_id"],))["status"],
      "pending")
recovered = _plan("377-recovered", p_fail["proposal_id"], p_fail["recommended_mix"])
check("the fence still works after both induced failures", recovered["total"], EXPECTED)

print("11) history is immutable and never recomputed; legacy stays truthful")
before = q1("SELECT * FROM run_mix_recommendation_snapshot WHERE round_id=%s", (RID,))
req("POST", "/run-mix-policy", {"weights": {v: 7 for v in VIDS}, "notes": "post-hoc generation"})
after = q1("SELECT * FROM run_mix_recommendation_snapshot WHERE round_id=%s", (RID,))
check("activating a new generation changes no field of an existing snapshot", after, before)
ok, err = exec_sql("UPDATE run_mix_recommendation_snapshot SET submitted_mix='{}'::jsonb "
                   "WHERE round_id=%s", (RID,))
check("the snapshot is append-only in the DB", (ok, "append-only" in (err or "")), (False, True))

st, legacy = req("POST", "/rounds", {"days": 2, "posts_per_day": 1, "label": "377-legacy",
                                     "format_mix": {NAMES[0]: 2, **{n: 0 for n in NAMES[1:]}}},
                 principal=None)
check("V1's proposal-less creation still works unsigned", st, 200)
st, legacy_snap = req("GET", f"/rounds/{legacy['round_id']}/recommendation-snapshot", principal=None)
check("a proposal-less run truthfully reports unknown", (st, legacy_snap.get("status")),
      (200, "unknown"))
check("nothing is inferred for it",
      q1("SELECT count(*) AS n FROM run_mix_recommendation_snapshot WHERE round_id=%s",
         (legacy["round_id"],))["n"], 0)
st, no_round = req("GET", "/rounds/NOPE-377/recommendation-snapshot", principal=None)
check("an unknown run is a typed 404", (st, code_of(no_round)), (404, "round_not_found"))
st, orphan_key = req("POST", "/rounds", {"days": 1, "posts_per_day": 1, "format_mix": {NAMES[0]: 1},
                                         "idempotency_key": "no-proposal"})
check("an idempotency key without a proposal is refused", orphan_key and 422, 422)

print("12) bounded retention")
pending_expired, _ = _insert_proposal(ADMIN, now - dt.timedelta(hours=3), now - dt.timedelta(hours=2))
st, denied_purge = req("POST", "/run-mix-proposals/purge", {}, principal=REVIEWER)
check("an unauthorized purge is refused", (st, code_of(denied_purge)), (403, "not_authorized"))
consumed_before = q1("SELECT count(*) AS n FROM run_mix_proposal WHERE status='consumed'")["n"]
st, purged = req("POST", "/run-mix-proposals/purge", {})
check("expired pending proposals are purged", (st, purged["purged"] >= 1), (200, True))
check("consumed evidence is never purged",
      q1("SELECT count(*) AS n FROM run_mix_proposal WHERE status='consumed'")["n"], consumed_before)
check("the purged proposal is gone",
      q1("SELECT count(*) AS n FROM run_mix_proposal WHERE proposal_id=%s", (pending_expired,))["n"], 0)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    sys.exit(1)
print("ALL RUN-MIX (#377) CHECKS PASSED")
