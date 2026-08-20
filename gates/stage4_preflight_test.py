"""#419 — runtime-free unit tests for gates/stage4_preflight.py.

No DB, container, or network: `stage4_preflight.preflight()` is pure logic over a RealDict-style
cursor, so a FakeCursor that returns canonical rows keyed by the SQL is sufficient. Run:

    python3 gates/stage4_preflight_test.py

Proves the fail-closed decision matrix: a coherent package is eligible; and each discriminator
(mismatched topic/script, missing/absent selection, absent provenance -> unknown_history, missing
consumed workflow -> unknown_history, missing active version, consumed-vs-active divergence,
underivable/disabled final-review, absent production direction) fails closed with the exact stable
code, never eligible-by-implication; and agent/AgentRep/provider/secret stay truthful classifications.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_preflight as s4  # noqa: E402

CV = "wf-consumed-uuid"   # consumed workflow version
AV = "wf-consumed-uuid"   # active == consumed in the coherent baseline (no divergence)

FAILURES = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAILURES.append(name)


class FakeCursor:
    """Returns canonical rows keyed by distinctive SQL fragments; every access is read-only."""
    def __init__(self, scen):
        self.scen = scen
        self._sql = ""
        self._params = ()

    def execute(self, sql, params=()):
        self._sql = sql
        self._params = params

    def fetchone(self):
        s, p, scen = self._sql, self._params, self.scen
        if "FROM slot WHERE slot_id" in s:
            return scen["slot"]
        if "FROM slot_approval" in s:
            artifact = p[1]
            rev = scen["topic_rev"] if artifact == "topic" else scen["script_rev"]
            return {"revision": rev} if rev is not None else None
        if "FROM topic WHERE slot_id" in s:
            return scen["topic"]
        if "FROM script WHERE slot_id" in s:
            return scen["script"]
        if "FROM script_provenance" in s:
            return scen["prov"]
        if "FROM round_policy_snapshot" in s:
            return scen["snapshot"]
        if "FROM workflow_version WHERE status='active'" in s:
            return scen["active"]
        if "FROM workflow_stage" in s:
            return scen["final_review"]
        if "FROM directive" in s:
            return scen["direction"]
        return None


def valid_pkg(script_id, revision, slot_id):
    """A structurally-canonical production-directive package (mirrors gates/directives.py) that
    references the given script (id + revision) and slot."""
    return {
        "schema_version": "1.0", "type": "production_directive",
        "from_stage": "script", "to_stage": "production",
        "intent": {"ar": "x", "en": "y"},
        "inputs": [{"kind": "script", "ref": f"script:{script_id}", "revision": revision},
                   {"kind": "slot", "ref": f"slot:{slot_id}"}],
        "parameters": {}, "constraints": [], "acceptance_criteria": [],
        "context": {"script_revision": revision},
    }


def coherent_scenario():
    return copy.deepcopy({
        "slot": {"slot_id": "S1", "round_id": "R1", "status": "APPROVED_ASSIGNED", "script_ref": "sc1"},
        "topic_rev": 2, "script_rev": 3,
        "topic": {"topic_id": "T1", "revision": 2},
        "script": {"script_id": "SC1", "revision": 3},
        "prov": {"workflow_version_id": CV, "topic_id": "T1", "topic_revision": 2,
                 "methodology_version": "m1", "content_format_version": "cf1",
                 "framework_version": "fw1", "writer_contract_version": "wc1"},
        "snapshot": {"workflow_version": CV},
        "active": {"version_id": AV, "version_no": 5, "status": "active"},
        "final_review": {"stage_key": "final_review", "enabled": True, "mandatory": True,
                         "bypassable": False, "stage_kind": "transition", "generator_kind": None,
                         "writer_mode": None, "approval_rule": "and",
                         "enforce_mandatory_reviews": True, "approve_to": "READY_FOR_PRODUCTION"},
        "direction": {"directive_id": "D1", "revision": 3, "payload": valid_pkg("SC1", 3, "S1")},
    })


def run(scen):
    return s4.preflight(FakeCursor(scen), "S1")


def codes(r):
    return {d["code"] for d in r["denials"]}


def main():
    print("#419 stage4_preflight unit tests")

    # coherent -> eligible, zero denials.
    r = run(coherent_scenario())
    check("coherent -> available, reason_code=coherent, no denials",
          r["available"] is True and r["reason_code"] == s4.COHERENT and r["denials"] == [])
    check("coherent -> both consumed and active workflow returned, not divergent",
          r["evidence"]["workflow"]["consumed"]["version_id"] == CV
          and r["evidence"]["workflow"]["active"]["version_id"] == AV
          and r["evidence"]["workflow"]["divergent"] is False)
    check("coherent -> final_review human_required true from consumed version",
          r["evidence"]["final_review"]["human_required"] is True
          and r["evidence"]["final_review"]["source_version_id"] == CV)
    check("classifications truthful (not_applicable/not_recorded), never enabled",
          r["evidence"]["classifications"] == {"agent_execution": "not_applicable",
                                               "agent_rep_delegation": "not_recorded",
                                               "provider_operation": "not_applicable",
                                               "secret_authority": "not_applicable"})

    # slot missing -> slot_not_found.
    sc = coherent_scenario(); sc["slot"] = None
    r = run(sc)
    check("slot missing -> slot_not_found, not available",
          r["available"] is False and r["reason_code"] == s4.SLOT_NOT_FOUND)

    # topic not selected -> topic_not_selected.
    sc = coherent_scenario(); sc["topic_rev"] = None
    r = run(sc)
    check("no approved topic -> topic_not_selected, not available",
          not r["available"] and s4.TOPIC_NOT_SELECTED in codes(r))

    # script revision selected but row missing -> script_revision_missing.
    sc = coherent_scenario(); sc["script"] = None
    r = run(sc)
    check("approved script revision with no script row -> script_revision_missing",
          not r["available"] and s4.SCRIPT_REVISION_MISSING in codes(r))

    # topic<->script mismatch (provenance points at a different topic revision).
    sc = coherent_scenario(); sc["prov"]["topic_revision"] = 1
    r = run(sc)
    check("provenance topic revision != selected topic -> topic_script_mismatch",
          not r["available"] and s4.TOPIC_SCRIPT_MISMATCH in codes(r))

    # no provenance (pre-#357) -> unknown_history (relation not derivable). Consumed still via snapshot.
    sc = coherent_scenario(); sc["prov"] = None
    r = run(sc)
    check("absent provenance -> unknown_history (relation underivable), not available",
          not r["available"] and s4.UNKNOWN_HISTORY in codes(r))

    # consumed workflow not derivable anywhere -> unknown_history.
    sc = coherent_scenario(); sc["prov"]["workflow_version_id"] = None; sc["snapshot"] = None
    r = run(sc)
    check("no consumed workflow on script or round snapshot -> unknown_history",
          not r["available"] and s4.UNKNOWN_HISTORY in codes(r)
          and r["evidence"]["workflow"]["consumed"] == {"status": "unknown"})

    # active workflow unavailable -> typed unavailable.
    sc = coherent_scenario(); sc["active"] = None
    r = run(sc)
    check("no active workflow version -> active_workflow_unavailable",
          not r["available"] and s4.ACTIVE_WORKFLOW_UNAVAILABLE in codes(r))

    # consumed != active -> divergence, never eligible by implication; both returned, no rebinding.
    sc = coherent_scenario(); sc["active"] = {"version_id": "wf-ACTIVE-OTHER", "version_no": 9, "status": "active"}
    r = run(sc)
    check("consumed != active -> consumed_active_workflow_divergence, not available",
          not r["available"] and s4.CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE in codes(r))
    check("divergence -> both distinct identities returned, divergent=True (no rebinding)",
          r["evidence"]["workflow"]["consumed"]["version_id"] == CV
          and r["evidence"]["workflow"]["active"]["version_id"] == "wf-ACTIVE-OTHER"
          and r["evidence"]["workflow"]["divergent"] is True)

    # final_review disabled/absent for consumed version -> final_review_unknown.
    sc = coherent_scenario(); sc["final_review"] = None
    r = run(sc)
    check("no final_review stage on consumed version -> final_review_unknown",
          not r["available"] and s4.FINAL_REVIEW_UNKNOWN in codes(r))
    sc = coherent_scenario(); sc["final_review"]["enabled"] = False
    r = run(sc)
    check("disabled final_review stage -> final_review_unknown",
          not r["available"] and s4.FINAL_REVIEW_UNKNOWN in codes(r))

    # final_review present but AI-generated (not human) -> cannot assert human-required -> final_review_unknown.
    sc = coherent_scenario(); sc["final_review"]["generator_kind"] = "llm"
    r = run(sc)
    check("final_review with an AI generator -> final_review_unknown (no human-required truth)",
          not r["available"] and s4.FINAL_REVIEW_UNKNOWN in codes(r))

    # #419 amendment: production direction ABSENT before final review -> not_yet_recorded, NON-BLOCKING
    # (an otherwise-coherent package stays eligible).
    sc = coherent_scenario(); sc["direction"] = None
    r = run(sc)
    check("absent production direction -> not_yet_recorded, still eligible (non-blocking)",
          r["available"] is True and r["reason_code"] == s4.COHERENT
          and r["evidence"]["production_direction"] == {"present": False, "status": "not_yet_recorded"})

    # P1: an ARBITRARY non-empty payload is NOT a valid package -> fail closed (malformed).
    sc = coherent_scenario(); sc["direction"]["payload"] = {"x": 1}
    r = run(sc)
    check("arbitrary non-empty payload -> production_direction_malformed",
          not r["available"] and s4.PRODUCTION_DIRECTION_MALFORMED in codes(r))
    sc = coherent_scenario(); sc["direction"]["payload"] = None
    r = run(sc)
    check("null payload -> production_direction_malformed",
          not r["available"] and s4.PRODUCTION_DIRECTION_MALFORMED in codes(r))
    # missing a canonical package field -> malformed.
    sc = coherent_scenario(); del sc["direction"]["payload"]["acceptance_criteria"]
    r = run(sc)
    check("package missing a canonical field -> production_direction_malformed",
          not r["available"] and s4.PRODUCTION_DIRECTION_MALFORMED in codes(r))

    # P1: a STRUCTURALLY-VALID package that references a DIFFERENT script -> fail closed (mismatch).
    sc = coherent_scenario(); sc["direction"]["payload"] = valid_pkg("SC-OTHER", 3, "S1")
    r = run(sc)
    check("valid package referencing a different script -> production_direction_mismatch",
          not r["available"] and s4.PRODUCTION_DIRECTION_MISMATCH in codes(r))
    # valid package but wrong script revision -> mismatch.
    sc = coherent_scenario(); sc["direction"]["payload"] = valid_pkg("SC1", 2, "S1")
    r = run(sc)
    check("valid package with wrong script revision -> production_direction_mismatch",
          not r["available"] and s4.PRODUCTION_DIRECTION_MISMATCH in codes(r))
    # valid package but wrong slot reference -> mismatch.
    sc = coherent_scenario(); sc["direction"]["payload"] = valid_pkg("SC1", 3, "S-OTHER")
    r = run(sc)
    check("valid package referencing a different slot -> production_direction_mismatch",
          not r["available"] and s4.PRODUCTION_DIRECTION_MISMATCH in codes(r))
    # P1 follow-up: the persisted directive.revision COLUMN must also equal the selected script
    # revision. A self-contradictory row (column=2, valid payload input revision=3) fails closed.
    sc = coherent_scenario(); sc["direction"]["revision"] = 2   # payload stays valid at rev 3; column stale
    r = run(sc)
    check("directive-row revision != selected script revision -> production_direction_mismatch",
          not r["available"] and s4.PRODUCTION_DIRECTION_MISMATCH in codes(r))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL stage4_preflight unit tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
