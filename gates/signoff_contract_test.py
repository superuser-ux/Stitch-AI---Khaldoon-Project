"""#439 — focused contract test for the Stage 4 dedicated final-review SIGN-OFF command.

ISOLATED ephemeral-Postgres (its OWN throwaway cluster on a private unix socket — no TCP, no shared
DB, no Docker/Compose), applying the committed db/init/schema.sql + every db/migrations/*.sql (incl.
037) in the canonical order. The ephemeral-PG bootstrap + slot/round builders are reused from the
existing #423 harness; this file adds only the sign-off fixtures + assertions.

Proves the engine contract end-to-end against a real DB — present-state authority, immutable-package
binding, staleness, idempotency + one-time tuple uniqueness, concurrency serialized by the package
FOR UPDATE lock, atomic receipt+audit rollback, and V1/V2 conservation — plus dependency-free source
assertions of the thin handler's wire contract (the 401/422 mappings + route additivity live at the
FastAPI/Pydantic boundary, which is not importable here without fastapi).

Run (the ONLY authorized commands for this slice):
    python3 -m py_compile gates/api.py gates/engine.py gates/signoff_contract_test.py
    python3 gates/signoff_contract_test.py
"""
import ast
import os
import re
import sys
import uuid
import inspect
import threading

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2
import psycopg2.extras
import psycopg2.errorcodes
import engine
import final_review_target_package_harness as H   # reuse ephemeral-PG bootstrap + slot/round builders

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_failures = 0


def check(name, cond):
    global _failures
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        _failures += 1


# governed config: final_review is a hard-floor gate (humans only); a human actor passes the floor.
CFG = {
    "actor_model": {"enabled": True, "hard_floors": {"gates": ["final_review"]}},
    "gates": {"final_review": {"scope": "batch", "policy": "fixed"}},
}


def _connect(sock):
    c = psycopg2.connect(host=sock, dbname="postgres", user="postgres",
                         cursor_factory=psycopg2.extras.RealDictCursor)
    c.autocommit = True
    c.cursor().execute("SET lock_timeout='15s'")   # a stuck row lock fails fast, never hangs the suite
    c.autocommit = False
    return c


def build_approved_target(cur, wv, tag, *, eligible="khal", rule="any"):
    """One authoritative, APPROVED final-review target + immutable package. The package pins the current
    topic/script heads (revision 1) so it is fresh; coverage of the single frozen token yields the
    'approved' outcome. Returns the request-binding tuple + provenance for assertions."""
    rid = f"S{tag}"
    H.mint_round(cur, rid)
    sid = f"{rid}-A"
    tid, scid = H.mint_slot(cur, rid, sid, wv, pinnable=True, script_rev=1)
    gid = str(uuid.uuid4())
    cur.execute("INSERT INTO gate (gate_id, scope, stage, policy, rule_key, quorum, status) "
                "VALUES (%s,'batch','final_review','fixed',%s,%s,'open')", (gid, rule, rule))
    snap = str(uuid.uuid4())
    cur.execute("INSERT INTO gate_snapshot (snapshot_id, gate_id, rule_key) VALUES (%s,%s,%s)",
                (snap, gid, rule))
    cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s)", (gid, sid))
    tokid = str(uuid.uuid4())
    cur.execute("INSERT INTO gate_snapshot_token "
                "(snapshot_token_id, snapshot_id, token_kind, token_key, normalized_token) "
                "VALUES (%s,%s,'user',%s,%s)", (tokid, snap, eligible, f"user:{eligible}"))
    cur.execute("INSERT INTO gate_snapshot_eligible (snapshot_token_id, principal_id) VALUES (%s,%s)",
                (tokid, eligible))
    cur.execute("INSERT INTO gate_token_coverage "
                "(gate_id, slot_id, snapshot_id, snapshot_token_id, covering_principal_id) "
                "VALUES (%s,%s,%s,%s,%s)", (gid, sid, snap, tokid, eligible))
    cur.execute("INSERT INTO final_review_target_package "
                "(gate_id, slot_id, snapshot_id, round_id, topic_id, topic_revision, script_id, "
                "script_revision, workflow_version_id, workflow_version_source) "
                "VALUES (%s,%s,%s,%s,%s,1,%s,1,%s,'script_provenance')",
                (gid, sid, snap, rid, tid, scid, wv))
    return {"gate_id": gid, "slot_id": sid, "snapshot_id": snap, "topic_revision": 1,
            "script_revision": 1, "workflow_version_id": wv, "round_id": rid,
            "topic_id": tid, "script_id": scid}


def call(conn, t, actor, key, cfg=CFG, **over):
    """Invoke engine.sign_off with a target's binding tuple, allowing per-field overrides."""
    return engine.sign_off(conn, over.get("gate_id", t["gate_id"]), over.get("slot_id", t["slot_id"]),
                           actor, over.get("snapshot_id", t["snapshot_id"]),
                           over.get("topic_revision", t["topic_revision"]),
                           over.get("script_revision", t["script_revision"]),
                           over.get("workflow_version_id", t["workflow_version_id"]), key, cfg=cfg)


def expect(conn, code, conn_build_committed, t, actor, key, **over):
    """Assert engine.sign_off raises SignoffError with the exact code + mapped HTTP status."""
    try:
        call(conn, t, actor, key, **over)
        return False, "no error raised"
    except engine.SignoffError as e:
        ok = (e.code == code and e.http_status == engine.SIGNOFF_ERROR_STATUS[code])
        return ok, f"{e.code}/{e.http_status}"


def audit_rows(cur, signoff_id=None):
    if signoff_id:
        cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='final_review_signoff' "
                    "AND entity_id=%s AND action='final_review_sign_off'", (signoff_id,))
    else:
        cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='final_review_signoff'")
    return cur.fetchone()["n"]


def receipt_rows(cur, gid, sid):
    cur.execute("SELECT count(*) AS n FROM final_review_signoff WHERE gate_id=%s AND slot_id=%s",
                (gid, sid))
    return cur.fetchone()["n"]


# --------------------------------------------------------------------------- #
# Part A — dependency-free source/AST contract (the 401/422 wire mapping + route additivity live at
# the FastAPI/Pydantic boundary, not importable here without fastapi).
# --------------------------------------------------------------------------- #
def source_contract():
    print("\n#439 A — handler wire contract (source/AST, no fastapi import)")
    api_src = open(os.path.join(REPO, "gates", "api.py"), encoding="utf-8").read()
    tree = ast.parse(api_src)

    # SignOffBody forbids unknown fields and uses strict integer revisions.
    body = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.ClassDef) and n.name == "SignOffBody"), None)
    body_src = ast.get_source_segment(api_src, body) if body else ""
    check("SignOffBody exists", body is not None)
    check("SignOffBody forbids unknown fields (extra='forbid' -> 422 for unknown actor/approver/etc.)",
          'extra="forbid"' in (body_src or ""))
    check("SignOffBody revisions are StrictInt >= 1",
          "StrictInt" in (body_src or "") and "ge=1" in (body_src or ""))
    field_names = [n.target.id for n in (body.body if body else [])
                   if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
    check("SignOffBody declares EXACTLY the 5 request fields (no actor/approver/principal/outcome field)",
          set(field_names) == {"snapshot_id", "topic_revision", "script_revision",
                               "workflow_version_id", "idempotency_key"})

    # the handler + its route, actor seam, and typed mappings.
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "sign_off_slot"), None)
    fn_src = ast.get_source_segment(api_src, fn) if fn else ""
    check("sign_off_slot handler exists", fn is not None)
    check("route is POST /gates/{gate_id}/slots/{slot_id}/sign-off",
          '@app.post("/gates/{gate_id}/slots/{slot_id}/sign-off")' in api_src)
    check("handler resolves actor via the EXISTING _trusted_approval_actor seam (no body actor)",
          "_trusted_approval_actor(request, None" in (fn_src or ""))
    check("missing/invalid principal maps to 401 signoff_unauthenticated",
          'status_code == 401' in (fn_src or "") and '"signoff_unauthenticated"' in (fn_src or ""))
    check("malformed/unknown/out-of-bounds request maps to 422 invalid_request",
          '"invalid_request"' in api_src and "422" in (fn_src or ""))
    check("typed SignoffError maps to its public {'error': code} + status",
          "engine.SignoffError" in (fn_src or "") and "e.http_status" in (fn_src or "")
          and '"error": e.code' in (fn_src or ""))
    check("handler delegates the contract to engine.sign_off (no inline authority/idempotency logic)",
          "engine.sign_off(" in (fn_src or ""))

    # V1 decision route + handler unchanged (additive-only).
    check("V1 POST /gates/{gate_id}/decide route preserved",
          '@app.post("/gates/{gate_id}/decide")' in api_src)
    check("V1 decide still binds via _trusted_approval_actor with the body approver (unchanged)",
          "_trusted_approval_actor(request, body.approver_id, c, gate_id)" in api_src)

    # the error-code -> status map is complete + consistent with the directive.
    expected = {
        "signoff_unauthenticated": 401, "signoff_not_authorized": 403, "signoff_hard_floor": 403,
        "signoff_target_unavailable": 404, "signoff_package_mismatch": 404, "signoff_blocked": 409,
        "signoff_stale": 409, "signoff_already_recorded": 409, "idempotency_key_mismatch": 409,
        "signoff_conflict": 409, "invalid_request": 422,
    }
    check("SIGNOFF_ERROR_STATUS matches the directive's exact public mapping",
          engine.SIGNOFF_ERROR_STATUS == expected)

    # engine.sign_off signature: no lifecycle/outcome/actor-override knobs beyond the contract.
    params = list(inspect.signature(engine.sign_off).parameters)
    check("engine.sign_off signature is the exact contract (verified actor + 4 binding fields + key)",
          params[:9] == ["conn", "gate_id", "slot_id", "actor", "snapshot_id", "topic_revision",
                         "script_revision", "workflow_version_id", "idempotency_key"])

    # digest format v1 — deterministic, 64-char lowercase hex, actor-bound, idempotency_key excluded.
    d1 = engine._signoff_request_digest("G", "s", "AAAA", 1, 2, "BBBB", "khal")
    d2 = engine._signoff_request_digest("g", "s", "aaaa", 1, 2, "bbbb", "khal")  # UUIDs canonicalized lower
    d3 = engine._signoff_request_digest("G", "s", "AAAA", 1, 2, "BBBB", "huda")  # different actor
    check("digest is 64-char lowercase sha-256 hex", bool(re.fullmatch(r"[0-9a-f]{64}", d1)))
    check("digest lowercases UUIDs (canonical) — case-insensitive over UUID fields", d1 == d2)
    check("digest is actor-bound (same key, different actor -> different digest)", d1 != d3)


# --------------------------------------------------------------------------- #
# Part B — engine contract against real ephemeral Postgres.
# --------------------------------------------------------------------------- #
def engine_contract():
    print("\n#439 B — engine contract (isolated ephemeral Postgres)")
    root = data = sock = None
    conn = None
    try:
        root, data, sock = H.start_pg()
        conn = psycopg2.connect(host=sock, dbname="postgres", user="postgres",
                                cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = True
        c0 = conn.cursor()
        has_vector = True
        try:
            c0.execute("CREATE EXTENSION IF NOT EXISTS vector")
            c0.execute("DROP EXTENSION vector")
        except Exception:
            has_vector = False
        c0.close()
        conn.autocommit = False
        H.apply_schema(conn, has_vector)
        cur = conn.cursor()

        cur.execute("SELECT to_regclass('public.final_review_signoff') AS t")
        check("migration 037 applied — final_review_signoff table exists (schema.sql + migrations canonical order)",
              cur.fetchone()["t"] is not None)
        cur.execute("SELECT conname FROM pg_constraint WHERE conname='final_review_signoff_target_fk'")
        check("cross-table FK to final_review_target_package added via guarded ALTER (037)",
              cur.fetchone() is not None)
        conn.commit()

        wv = H.seed_common(cur)
        conn.commit()

        # ---- Happy path: a new sign-off records exactly one immutable receipt + one success audit ----
        t = build_approved_target(cur, wv, "OK")
        conn.commit()
        r = call(conn, t, "khal", "  key-ok  ")   # key trimmed
        cur.execute("SELECT * FROM final_review_signoff WHERE signoff_id=%s", (r["signoff_id"],))
        row = cur.fetchone()
        check("new sign-off returns HTTP-200 receipt with operation/status recorded",
              r["operation"] == "sign_off" and r["status"] == "recorded")
        check("receipt exposes ONLY the 9 contract fields (no actor / digest / provenance leak)",
              set(r) == {"signoff_id", "operation", "status", "gate_id", "slot_id", "snapshot_id",
                         "topic_revision", "script_revision", "workflow_version_id", "recorded_at"})
        check("receipt binds the submitted tuple", r["snapshot_id"] == t["snapshot_id"]
              and r["topic_revision"] == 1 and r["workflow_version_id"] == wv)
        check("stored receipt carries FULL package provenance (round/topic/script ids + wv source)",
              row["round_id"] == t["round_id"] and str(row["topic_id"]) == t["topic_id"]
              and str(row["script_id"]) == t["script_id"] and row["workflow_version_source"] == "script_provenance")
        check("idempotency_key stored TRIMMED", row["idempotency_key"] == "key-ok")
        check("request_digest stored is 64-char lowercase hex", bool(re.fullmatch(r"[0-9a-f]{64}", row["request_digest"])))
        check("exactly one success audit written (entity=final_review_signoff)", audit_rows(cur, r["signoff_id"]) == 1)
        cur.execute("SELECT detail FROM audit_log WHERE entity='final_review_signoff' AND entity_id=%s",
                    (r["signoff_id"],))
        detail = cur.fetchone()["detail"]
        check("success-audit detail carries the full sign-off record",
              all(k in detail for k in ["signoff_id", "gate_id", "slot_id", "snapshot_id", "topic_revision",
                                        "script_revision", "workflow_version_id", "idempotency_key",
                                        "request_digest", "outcome"]))

        # ---- Idempotent replay: identical key + digest -> original receipt, NO second audit ----
        r2 = call(conn, t, "khal", "key-ok")
        check("identical replay returns the ORIGINAL receipt (same signoff_id + recorded_at)",
              r2["signoff_id"] == r["signoff_id"] and r2["recorded_at"] == r["recorded_at"])
        check("replay writes NO second success audit", audit_rows(cur, r["signoff_id"]) == 1)
        check("replay writes NO second receipt row", receipt_rows(cur, t["gate_id"], t["slot_id"]) == 1)

        # ---- Same key, different actor -> different digest -> idempotency_key_mismatch ----
        ok, got = expect(conn, "idempotency_key_mismatch", conn, t, "huda", "key-ok")
        check(f"same key + different actor (digest differs) -> idempotency_key_mismatch [{got}]", ok)

        # ---- Different key for the already-recorded exact tuple -> already_recorded ----
        ok, got = expect(conn, "signoff_already_recorded", conn, t, "khal", "another-key")
        check(f"different key for an already-recorded tuple -> signoff_already_recorded [{got}]", ok)

        # ---- Authorization: actor not FROZEN-eligible -> not_authorized ----
        ta = build_approved_target(cur, wv, "AUTH", eligible="khal"); conn.commit()
        ok, got = expect(conn, "signoff_not_authorized", conn, ta, "huda", "k")
        check(f"actor not frozen-eligible -> signoff_not_authorized (403) [{got}]", ok)

        # ---- Hard floor: an AGENT actor, eligible, still cannot sign off a hard-floor gate ----
        thf = build_approved_target(cur, wv, "HF", eligible="agent.topic"); conn.commit()
        ok, got = expect(conn, "signoff_hard_floor", conn, thf, "agent.topic", "k")
        check(f"non-human eligible actor -> signoff_hard_floor (403) [{got}]", ok)

        # ---- Missing target: unknown gate/slot (no package) -> target_unavailable ----
        ok, got = expect(conn, "signoff_target_unavailable", conn, t, "khal", "k",
                         gate_id=str(uuid.uuid4()), slot_id="nope")
        check(f"unknown gate/slot (missing package) -> signoff_target_unavailable (404) [{got}]", ok)

        # ---- Package mismatch: wrong snapshot / revision / wv -> package_mismatch ----
        tm = build_approved_target(cur, wv, "MM"); conn.commit()
        ok, got = expect(conn, "signoff_package_mismatch", conn, tm, "khal", "k", snapshot_id=str(uuid.uuid4()))
        check(f"wrong snapshot_id vs stored package -> signoff_package_mismatch (404) [{got}]", ok)
        ok, got = expect(conn, "signoff_package_mismatch", conn, tm, "khal", "k2", topic_revision=9)
        check(f"wrong topic_revision vs stored package -> signoff_package_mismatch (404) [{got}]", ok)

        # ---- Stale governed head: a post-attachment rework advances the head past the pinned rev ----
        ts = build_approved_target(cur, wv, "STALE"); conn.commit()
        cur.execute("INSERT INTO topic (topic_id, slot_id, hcs_id, round_id, revision) VALUES (%s,%s,'1.1',%s,2)",
                    (str(uuid.uuid4()), ts["slot_id"], ts["round_id"]))
        conn.commit()
        ok, got = expect(conn, "signoff_stale", conn, ts, "khal", "k", topic_revision=1)
        check(f"stale topic head (head=2 > pinned=1) -> signoff_stale (409) [{got}]", ok)
        ts2 = build_approved_target(cur, wv, "STALE2"); conn.commit()
        cur.execute("INSERT INTO script (script_id, slot_id, hcs_id, revision) VALUES (%s,%s,'1.1',2)",
                    (str(uuid.uuid4()), ts2["slot_id"]))
        conn.commit()
        ok, got = expect(conn, "signoff_stale", conn, ts2, "khal", "k", script_revision=1)
        check(f"stale script head (head=2 > pinned=1) -> signoff_stale (409) [{got}]", ok)

        # ---- Present state not approved -> blocked (rejected / request_change / pending / not-open) ----
        trej = build_approved_target(cur, wv, "REJ"); conn.commit()
        cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) VALUES (%s,%s,'khal','reject')",
                    (trej["gate_id"], trej["slot_id"]))
        conn.commit()
        ok, got = expect(conn, "signoff_blocked", conn, trej, "khal", "k")
        check(f"rejected present state -> signoff_blocked (409) [{got}]", ok)

        trc = build_approved_target(cur, wv, "RC"); conn.commit()
        cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                    "VALUES (%s,%s,'khal','request_change')", (trc["gate_id"], trc["slot_id"]))
        conn.commit()
        ok, got = expect(conn, "signoff_blocked", conn, trc, "khal", "k")
        check(f"request_change present state -> signoff_blocked (409) [{got}]", ok)

        tpend = build_approved_target(cur, wv, "PEND"); conn.commit()
        cur.execute("DELETE FROM gate_token_coverage WHERE gate_id=%s", (tpend["gate_id"],))  # uncovered -> pending
        conn.commit()
        ok, got = expect(conn, "signoff_blocked", conn, tpend, "khal", "k")
        check(f"pending/unavailable present-state evidence -> signoff_blocked (409) [{got}]", ok)

        tpark = build_approved_target(cur, wv, "PARK"); conn.commit()
        cur.execute("UPDATE gate SET status='superseded' WHERE gate_id=%s", (tpark["gate_id"],))
        conn.commit()
        ok, got = expect(conn, "signoff_blocked", conn, tpark, "khal", "k")
        check(f"non-open (parked/superseded) gate -> signoff_blocked (409) [{got}]", ok)

        # legacy gate: a non-authoritative snapshot => _load_gate_snapshot returns None => no
        # authoritative present-state evidence to approve against => fail closed (blocked).
        tlg = build_approved_target(cur, wv, "LEG"); conn.commit()
        cur.execute("UPDATE gate_snapshot SET authoritative=false WHERE gate_id=%s", (tlg["gate_id"],))
        conn.commit()
        ok, got = expect(conn, "signoff_blocked", conn, tlg, "khal", "k")
        check(f"legacy gate (no authoritative snapshot) -> signoff_blocked (409) [{got}]", ok)

        # ---- Atomic rollback: a success-audit failure rolls back the receipt (no partial write) ----
        trb = build_approved_target(cur, wv, "RB"); conn.commit()
        orig_audit = engine._audit
        engine._audit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom audit"))
        raised = False
        try:
            call(conn, trb, "khal", "k")
        except RuntimeError:
            raised = True
        finally:
            engine._audit = orig_audit
        check("a success-audit failure PROPAGATES (no silent success)", raised)
        check("receipt rolled back atomically on audit failure (no partial receipt row)",
              receipt_rows(cur, trb["gate_id"], trb["slot_id"]) == 0)
        # and the target is still signable afterwards (rollback left a clean slate)
        rok = call(conn, trb, "khal", "k")
        check("target still signable after the rolled-back attempt", rok["status"] == "recorded")

        # ---- Conservation: a successful sign-off mutates NOTHING but its own receipt + audit ----
        tcons = build_approved_target(cur, wv, "CONS"); conn.commit()

        def counts():
            cur.execute("SELECT (SELECT count(*) FROM gate_decision) AS d, "
                        "(SELECT count(*) FROM gate_token_coverage) AS c, "
                        "(SELECT count(*) FROM gate) AS g, (SELECT count(*) FROM slot) AS s, "
                        "(SELECT count(*) FROM gate_snapshot) AS n")
            return dict(cur.fetchone())
        before = counts()
        call(conn, tcons, "khal", "k")
        after = counts()
        check("sign-off writes NO gate_decision / coverage / gate / slot / snapshot mutation",
              before == after)

        # ---- Immutability: the receipt cannot be updated or deleted at the DB boundary ----
        for op, sql in (("UPDATE", "UPDATE final_review_signoff SET actor='x' WHERE signoff_id=%s"),
                        ("DELETE", "DELETE FROM final_review_signoff WHERE signoff_id=%s")):
            blocked = False
            try:
                cur.execute(sql, (r["signoff_id"],)); conn.commit()
            except psycopg2.Error:
                conn.rollback(); blocked = True
            check(f"receipt is immutable — {op} rejected at the DB boundary", blocked)

        # ---- #442 Finding 1: authority denial mapped to a public code ONLY on EXACT string equality ----
        # `authorize_gate_decision` has exactly one recognized denial value; the engine maps it to
        # signoff_hard_floor by EXACT equality — never by truthiness, substring, prefix, inferred meaning,
        # or the hard-floor predicate alone. The real agent-actor hard-floor path above proves the helper
        # PRODUCES that value end-to-end -> signoff_hard_floor. Here we drive the seam by monkeypatch to
        # prove the ENGINE'S mapping is exact: every other denial — an unknown/future reason even while the
        # hard-floor configuration is TRUE, or a near-miss variant — fails CLOSED with a bare GateError and
        # writes NO receipt and NO audit. gates/actors.py is untouched.
        RECOGNIZED = f"hard floor: '{engine.FINAL_REVIEW_STAGE}' must be decided by a human"

        def denial_outcome(tag, reason, cfg):
            """Run sign_off with authorize_gate_decision forced to (False, reason); return the outcome tag
            plus receipt count and audit-row delta so 'no side effect' is provable on a fail-closed path."""
            t = build_approved_target(cur, wv, tag); conn.commit()
            audit_before = audit_rows(cur)
            orig = engine.actors.authorize_gate_decision
            engine.actors.authorize_gate_decision = lambda *a, **k: (False, reason)
            try:
                call(conn, t, "khal", "k", cfg=cfg)
                out = "no-error"
            except engine.SignoffError as e:
                out = f"public:{e.code}"               # a public code -> only valid for the exact value
            except engine.GateError:
                out = "fail-closed-nonpublic"          # correct fail-closed refusal, no public code
            finally:
                engine.actors.authorize_gate_decision = orig
            return out, receipt_rows(cur, t["gate_id"], t["slot_id"]), audit_rows(cur) - audit_before

        cfg_nofloor = {"actor_model": {"enabled": True, "hard_floors": {"gates": []}},
                       "gates": {"final_review": {}}}
        # (a) EXACT recognized value + hard-floor cfg TRUE -> the public signoff_hard_floor (403) code.
        o_hf, _, _ = denial_outcome("F1HF", RECOGNIZED, CFG)
        check("exact recognized denial value -> signoff_hard_floor (public 403)",
              o_hf == "public:signoff_hard_floor")
        # (b) UNKNOWN / future reason while hard-floor cfg is TRUE -> fail CLOSED, no public code (#442 core).
        o_un, r_un, a_un = denial_outcome("F1UN", "future-unrecognized-reason", CFG)
        check("unknown/future denial while hard-floor cfg TRUE -> fail closed, NO guessed public code",
              o_un == "fail-closed-nonpublic")
        check("fail-closed unknown-denial path (cfg TRUE) writes NO receipt", r_un == 0)
        check("fail-closed unknown-denial path (cfg TRUE) writes NO audit", a_un == 0)
        # (c) a NEAR-MISS superset of the recognized value is NOT exact -> fail closed (proves the mapping
        #     is exact equality, not substring / prefix / truthiness).
        o_nm, _, _ = denial_outcome("F1NM", RECOGNIZED + " now", CFG)
        check("near-miss denial (superset of recognized value) -> fail closed, NO public code",
              o_nm == "fail-closed-nonpublic")
        # (d) unknown reason while the hard-floor predicate is FALSE also fails closed (unchanged from #441).
        o_nf, r_nf, _ = denial_outcome("F1NF", "some-unrecognized-reason", cfg_nofloor)
        check("unknown denial (hard-floor predicate FALSE) -> fail closed, NO guessed public code",
              o_nf == "fail-closed-nonpublic")
        check("fail-closed (predicate-false) path writes no receipt", r_nf == 0)

        # ---- #441 Finding 2: narrowed race translation — _signoff_race_conflict classifier ----
        # the two NAMED receipt-uniqueness constraints translate; UNRELATED integrity/programming do not.
        traz = build_approved_target(cur, wv, "RACE"); conn.commit()
        signed = call(conn, traz, "khal", "race-key")   # a real committed receipt for this tuple

        def real_exc(sql, params):
            try:
                cur.execute(sql, params); conn.rollback(); return None
            except psycopg2.Error as e:
                conn.rollback(); return e
        # (a) named tuple-uniqueness violation (duplicate canonical tuple, different key)
        e_tuple = real_exc(
            "INSERT INTO final_review_signoff (gate_id, slot_id, snapshot_id, round_id, topic_id, "
            "topic_revision, script_id, script_revision, workflow_version_id, workflow_version_source, "
            "actor, idempotency_key, request_digest, outcome) VALUES "
            "(%s,%s,%s,%s,%s,1,%s,1,%s,'script_provenance','khal','other-key',%s,'recorded')",
            (traz["gate_id"], traz["slot_id"], traz["snapshot_id"], traz["round_id"], traz["topic_id"],
             traz["script_id"], traz["workflow_version_id"], "a" * 64))
        check("named final_review_signoff_tuple_uq violation -> _signoff_race_conflict True",
              isinstance(e_tuple, psycopg2.errors.UniqueViolation)
              and e_tuple.diag.constraint_name == "final_review_signoff_tuple_uq"
              and engine._signoff_race_conflict(e_tuple) is True)
        # (b) named idempotency-uniqueness violation (same key, different tuple)
        e_idem = real_exc(
            "INSERT INTO final_review_signoff (gate_id, slot_id, snapshot_id, round_id, topic_id, "
            "topic_revision, script_id, script_revision, workflow_version_id, workflow_version_source, "
            "actor, idempotency_key, request_digest, outcome) VALUES "
            "(%s,%s,%s,%s,%s,1,%s,2,%s,'script_provenance','khal','race-key',%s,'recorded')",
            (traz["gate_id"], traz["slot_id"], traz["snapshot_id"], traz["round_id"], traz["topic_id"],
             traz["script_id"], traz["workflow_version_id"], "b" * 64))
        check("named final_review_signoff_idem_uq violation -> _signoff_race_conflict True",
              isinstance(e_idem, psycopg2.errors.UniqueViolation)
              and e_idem.diag.constraint_name == "final_review_signoff_idem_uq"
              and engine._signoff_race_conflict(e_idem) is True)
        # (c) an UNRELATED unique violation (final_review_target_package PK) is NOT a sign-off race
        e_unrel = real_exc(
            "INSERT INTO final_review_target_package (gate_id, slot_id, snapshot_id, round_id, topic_id, "
            "topic_revision, script_id, script_revision, workflow_version_id, workflow_version_source) "
            "VALUES (%s,%s,%s,%s,%s,1,%s,1,%s,'script_provenance')",
            (traz["gate_id"], traz["slot_id"], traz["snapshot_id"], traz["round_id"], traz["topic_id"],
             traz["script_id"], traz["workflow_version_id"]))
        check("UNRELATED unique violation (package PK) -> _signoff_race_conflict False",
              isinstance(e_unrel, psycopg2.errors.UniqueViolation)
              and engine._signoff_race_conflict(e_unrel) is False)
        # (d) foreign-key, (e) check, (f) not-null violations are NOT sign-off races
        e_fk = real_exc(
            "INSERT INTO final_review_signoff (gate_id, slot_id, snapshot_id, round_id, topic_id, "
            "topic_revision, script_id, script_revision, workflow_version_id, workflow_version_source, "
            "actor, idempotency_key, request_digest, outcome) VALUES "
            "(%s,'no-such-slot',%s,%s,%s,1,%s,1,%s,'script_provenance','khal','k',%s,'recorded')",
            (str(uuid.uuid4()), traz["snapshot_id"], traz["round_id"], traz["topic_id"],
             traz["script_id"], traz["workflow_version_id"], "c" * 64))
        check("foreign-key violation -> _signoff_race_conflict False (propagates)",
              isinstance(e_fk, psycopg2.errors.ForeignKeyViolation) and engine._signoff_race_conflict(e_fk) is False)
        # check + not-null use the VALID target (FK passes) with a RANDOM snapshot + fresh key so only the
        # intended column constraint fires (never the tuple/idem unique).
        e_ck = real_exc(
            "INSERT INTO final_review_signoff (gate_id, slot_id, snapshot_id, round_id, topic_id, "
            "topic_revision, script_id, script_revision, workflow_version_id, workflow_version_source, "
            "actor, idempotency_key, request_digest, outcome) VALUES "
            "(%s,%s,%s,%s,%s,1,%s,1,%s,'script_provenance','khal','ck-key',%s,'BAD')",
            (traz["gate_id"], traz["slot_id"], str(uuid.uuid4()), traz["round_id"],
             traz["topic_id"], traz["script_id"], traz["workflow_version_id"], "d" * 64))
        check("check violation (outcome!='recorded') -> _signoff_race_conflict False",
              isinstance(e_ck, psycopg2.errors.CheckViolation) and engine._signoff_race_conflict(e_ck) is False)
        e_nn = real_exc(
            "INSERT INTO final_review_signoff (gate_id, slot_id, snapshot_id, round_id, topic_id, "
            "topic_revision, script_id, script_revision, workflow_version_id, workflow_version_source, "
            "actor, idempotency_key, request_digest, outcome) VALUES "
            "(%s,%s,%s,%s,%s,1,%s,1,%s,'script_provenance',NULL,'nn-key',%s,'recorded')",
            (traz["gate_id"], traz["slot_id"], str(uuid.uuid4()), traz["round_id"],
             traz["topic_id"], traz["script_id"], traz["workflow_version_id"], "e" * 64))
        check("not-null violation (actor NULL) -> _signoff_race_conflict False",
              isinstance(e_nn, psycopg2.errors.NotNullViolation) and engine._signoff_race_conflict(e_nn) is False)
        # (g) serialization (40001) + (h) deadlock (40P01) classes translate; programming/type do NOT.
        # #442 F3 — SQLSTATE evidence (class names alone are insufficient): the psycopg2 error registry is
        # a bounded, in-process, DB-free mechanism that binds each EXACT SQLSTATE string to the EXACT
        # concrete class the engine translates. errorcodes gives the canonical SQLSTATE value; lookup()
        # resolves that SQLSTATE back to the same class object used in _signoff_race_conflict / the boundary.
        check("SQLSTATE 40001 <-> SerializationFailure (errorcodes + registry lookup)",
              psycopg2.errorcodes.SERIALIZATION_FAILURE == "40001"
              and psycopg2.errors.lookup("40001") is psycopg2.errors.SerializationFailure)
        check("SQLSTATE 40P01 <-> DeadlockDetected (errorcodes + registry lookup)",
              psycopg2.errorcodes.DEADLOCK_DETECTED == "40P01"
              and psycopg2.errors.lookup("40P01") is psycopg2.errors.DeadlockDetected)
        check("SerializationFailure (40001) -> _signoff_race_conflict True",
              engine._signoff_race_conflict(psycopg2.errors.SerializationFailure()) is True)
        check("DeadlockDetected (40P01) -> _signoff_race_conflict True",
              engine._signoff_race_conflict(psycopg2.errors.DeadlockDetected()) is True)
        check("ProgrammingError -> _signoff_race_conflict False",
              engine._signoff_race_conflict(psycopg2.errors.ProgrammingError()) is False)
        check("non-DB exception (TypeError) -> _signoff_race_conflict False",
              engine._signoff_race_conflict(TypeError("x")) is False)

        # ---- #441 Finding 2 end-to-end: the sign_off BOUNDARY translates only races, atomically ----
        def audit_raises(exc):
            def _boom(*a, **k):
                raise exc
            return _boom
        for label, exc, expect_conflict in (
                ("SerializationFailure", psycopg2.errors.SerializationFailure(), True),
                ("DeadlockDetected", psycopg2.errors.DeadlockDetected(), True),
                ("unrelated RuntimeError", RuntimeError("boom"), False)):
            tb = build_approved_target(cur, wv, "BND" + label[:3]); conn.commit()
            orig = engine._audit
            engine._audit = audit_raises(exc)
            outcome = None
            caught = None
            try:
                call(conn, tb, "khal", "k")
                outcome = "no error"
            except engine.SignoffError as se:
                outcome = f"signoff:{se.code}"
                caught = se
            except Exception as ue:
                outcome = f"raw:{type(ue).__name__}"
            finally:
                engine._audit = orig
            if expect_conflict:
                check(f"boundary translates {label} -> signoff_conflict (409)",
                      outcome == "signoff:signoff_conflict")
                # #442 F2 — the ORIGINAL exception object is retained as __cause__, with its concrete type.
                check(f"boundary retains the original {label} object as __cause__ (identity)",
                      caught is not None and caught.__cause__ is exc)
                check(f"boundary __cause__ concrete type is {label}",
                      caught is not None and type(caught.__cause__) is type(exc))
            else:
                check(f"boundary leaves {label} unclassified (propagates raw)", outcome == "raw:RuntimeError")
            check(f"boundary rolls back the receipt after {label} (no partial write)",
                  receipt_rows(cur, tb["gate_id"], tb["slot_id"]) == 0)

        # ---- Concurrency: the package FOR UPDATE lock serializes same-target sign-offs ----
        # identical concurrent requests -> exactly one receipt + one audit, both return the same id
        tci = build_approved_target(cur, wv, "CONC1"); conn.commit()
        res = _run_concurrent(sock, tci, [("khal", "same"), ("khal", "same")])
        ids = {x["signoff_id"] for x in res if isinstance(x, dict)}
        check("concurrent identical requests -> exactly ONE receipt row",
              receipt_rows(cur, tci["gate_id"], tci["slot_id"]) == 1)
        check("concurrent identical requests -> ONE success audit (no double effect)",
              audit_rows(cur, next(iter(ids))) == 1 if ids else False)
        check("concurrent identical requests -> both callers see the SAME signoff_id",
              len([x for x in res if isinstance(x, dict)]) == 2 and len(ids) == 1)

        # conflicting concurrent requests (same tuple, different keys) -> one wins, one already_recorded
        tcc = build_approved_target(cur, wv, "CONC2"); conn.commit()
        res2 = _run_concurrent(sock, tcc, [("khal", "k-a"), ("khal", "k-b")])
        wins = [x for x in res2 if isinstance(x, dict)]
        errs = [x for x in res2 if isinstance(x, engine.SignoffError)]
        check("concurrent conflicting requests -> exactly ONE receipt row",
              receipt_rows(cur, tcc["gate_id"], tcc["slot_id"]) == 1)
        check("concurrent conflicting requests -> one success + one signoff_already_recorded",
              len(wins) == 1 and len(errs) == 1 and errs[0].code == "signoff_already_recorded")

    finally:
        if conn is not None:
            conn.close()
        if root is not None:
            H.cleanup(root, data)


def _run_concurrent(sock, t, specs):
    """Run len(specs) sign_off calls on SEPARATE connections, released together by a barrier so they
    contend on the package FOR UPDATE lock. Returns each thread's receipt dict or SignoffError."""
    barrier = threading.Barrier(len(specs))
    out = [None] * len(specs)
    conns = [_connect(sock) for _ in specs]

    def worker(i, actor, key):
        try:
            barrier.wait(timeout=20)
            out[i] = engine.sign_off(conns[i], t["gate_id"], t["slot_id"], actor, t["snapshot_id"],
                                     1, 1, t["workflow_version_id"], key, cfg=CFG)
        except engine.SignoffError as e:
            out[i] = e
        except Exception as e:  # surface any unexpected failure as the result for assertion
            out[i] = e

    threads = [threading.Thread(target=worker, args=(i, a, k)) for i, (a, k) in enumerate(specs)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    for c in conns:
        c.close()
    return out


if __name__ == "__main__":
    print("#439 Stage 4 final-review sign-off contract test")
    source_contract()
    engine_contract()
    print(f"\n{'ALL #439 CONTRACT CHECKS PASSED' if _failures == 0 else f'FAILED ({_failures})'}")
    sys.exit(0 if _failures == 0 else 1)
