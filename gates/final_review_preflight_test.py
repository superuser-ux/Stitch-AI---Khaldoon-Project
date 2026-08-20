"""#447 — runtime-free focused tests for gates/final_review_preflight.py.

No DB, container, network, provider, or secret access: `preflight()` is pure logic over a
RealDict-style cursor, so a recording FakeCursor returning canonical rows keyed by distinctive SQL
fragments is sufficient. Run:

    python3 gates/final_review_preflight_test.py

Proves, against the reconciled #447 rulings:
  * coherent  -> available, all SIX tuple members returned exactly as pinned, zero denials;
  * fail-closed for: non-admitted / unknown gate / non-final_review stage, legacy (no snapshot),
    a recorded row with a NULL tuple member, missing governing gate snapshot, package-vs-governing
    snapshot inconsistency, missing active workflow version, pinned-vs-active workflow divergence,
    a non-enforced human hard floor, a non-open gate, slot-unattributable decisions, a stale governed
    head, a non-approved present outcome, and every production-direction disagreement;
  * the six-member tuple is NEVER emitted partially — a missing member yields `target_package_tuple`
    None rather than a partly-pinned package;
  * DETERMINISTIC precedence — historical proof gaps outrank present-state eligibility when both fail;
  * NO AUTHORIZATION ORACLE — no principal is ever loaded, no eligible-principal set or coverage
    principal id is ever disclosed, and the two actor-dependent sign-off codes are never emitted;
  * NO POLICY VOCABULARY IS INVENTED — every emitted code is identical to an existing canonical
    constant in final_review_projection / stage4_preflight / engine.SIGNOFF_ERROR_STATUS;
  * READ-ONLY — every statement the module executes is a SELECT, with no FOR UPDATE and no
    write/provider/secret/emission path anywhere in the module source.
"""
import copy
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# `engine` imports the psycopg2 DRIVER and PyYAML at module scope. This test never opens a connection,
# a socket, a transaction, or a config file, so when those packages are absent from the host
# interpreter we substitute the minimal import surface engine touches at import time. This keeps the
# test genuinely runtime-free and host-independent; it stubs THIRD-PARTY IMPORTS ONLY and never stubs,
# patches, or replaces any engine logic, gate policy, or authority helper — every assertion below
# exercises the real code paths. `cfg` is always passed explicitly, so the stubbed `yaml.safe_load`
# raises rather than silently standing in for real configuration.
try:                                                     # pragma: no cover - environment dependent
    import yaml  # noqa: F401
except ModuleNotFoundError:                              # pragma: no cover - environment dependent
    import types

    _yaml = types.ModuleType("yaml")

    def _no_yaml(*_a, **_k):
        raise AssertionError("this test must never load configuration from disk; pass cfg explicitly")

    _yaml.safe_load = _yaml.safe_dump = _no_yaml
    sys.modules["yaml"] = _yaml

try:                                                     # pragma: no cover - environment dependent
    import psycopg2  # noqa: F401
except ModuleNotFoundError:                              # pragma: no cover - environment dependent
    import types

    _pg = types.ModuleType("psycopg2")
    _extras = types.ModuleType("psycopg2.extras")
    _errors = types.ModuleType("psycopg2.errors")
    _extras.Json = lambda v: v
    _extras.RealDictCursor = object

    class _StubDbError(Exception):
        pass

    for _name in ("UniqueViolation", "SerializationFailure", "DeadlockDetected", "NotNullViolation"):
        setattr(_errors, _name, type(_name, (_StubDbError,), {}))
    _pg.extras, _pg.errors, _pg.Error = _extras, _errors, _StubDbError
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _extras
    sys.modules["psycopg2.errors"] = _errors

import engine  # noqa: E402
import final_review_projection as _proj  # noqa: E402
import final_review_preflight as frp  # noqa: E402
import stage4_preflight as _s4  # noqa: E402

GATE = "11111111-1111-1111-1111-111111111111"
SLOT = "S1"
SNAP = "22222222-2222-2222-2222-222222222222"
WF = "33333333-3333-3333-3333-333333333333"

FAILURES = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAILURES.append(name)


CFG = {
    # `final_review` with NO rework_mode -> `_gate_review_head` returns None (non-artifact gate),
    # exactly as the #439 sign-off path behaves.
    "gates": {"final_review": {"rule": "any", "approve_to": "READY_FOR_PRODUCTION"}},
    "actor_model": {"enabled": True, "hard_floors": {"gates": ["final_review"], "reviews": []}},
}


class FakeCursor:
    """Returns canonical rows keyed by distinctive SQL fragments and RECORDS every statement, so the
    read-only property is proved from what the module actually executed, not from its source alone."""

    def __init__(self, scen):
        self.scen = scen
        self.executed = []
        self._sql = ""
        self._params = ()

    def execute(self, sql, params=()):
        self.executed.append(sql)
        self._sql = sql
        self._params = params

    # -- single-row reads -------------------------------------------------------------------------
    def fetchone(self):
        s, scen = self._sql, self.scen
        if "FROM final_review_target_package" in s:
            return scen["pkg_row"]
        if "FROM gate_target gt JOIN gate g" in s:                    # _pkg.read stage fallback
            return {"?column?": 1} if scen["is_final_review_target"] else None
        if "FROM gate g LEFT JOIN gate_target gt" in s:               # identity + admission
            return scen["gate"]
        if "FROM gate_snapshot WHERE gate_id" in s:
            return scen["gate_snapshot"]
        if "FROM workflow_version WHERE status='active'" in s:
            return scen["active"]
        if "FROM gate_decision" in s and "slot_id IS NULL" in s:
            return {"n": scen["null_slot_decisions"]}
        if "FROM topic WHERE slot_id" in s:
            return {"r": scen["head_topic"]}
        if "FROM script WHERE slot_id" in s:
            return {"r": scen["head_script"]}
        if "FROM directive" in s:
            return scen["live_direction"]
        return None

    # -- multi-row reads --------------------------------------------------------------------------
    def fetchall(self):
        s, scen = self._sql, self.scen
        if "FROM gate_snapshot_token" in s:
            return scen["tokens"]
        if "FROM gate_snapshot_eligible" in s:
            return scen["eligible"]
        if "FROM gate_token_coverage" in s:
            return scen["coverage"]
        if "FROM gate_decision" in s:
            return scen["decisions"]
        return []


def coherent_scenario():
    return copy.deepcopy({
        "is_final_review_target": True,
        "gate": {"gate_id": GATE, "gate_stage": "final_review", "gate_status": "open",
                 "admitted": True},
        "pkg_row": {
            "gate_id": GATE, "slot_id": SLOT, "snapshot_id": SNAP, "round_id": "R1",
            "topic_id": "T1", "topic_revision": 2, "script_id": "SC1", "script_revision": 3,
            "workflow_version_id": WF, "workflow_version_source": "script_provenance",
            "production_directive_id": "D1", "production_directive_revision": 3,
            "attached_at": None,
        },
        "gate_snapshot": {"snapshot_id": SNAP, "rule_key": "any", "authoritative": True},
        "tokens": [{"snapshot_token_id": "TK1", "token_kind": "user", "token_key": "u1",
                    "normalized_token": "user:u1"}],
        "eligible": [{"principal_id": "P-SECRET"}],
        "coverage": [{"snapshot_token_id": "TK1", "covering_principal_id": "P-SECRET"}],
        "decisions": [{"approver_id": "P-SECRET", "decision": "approve", "revision": None,
                       "decided_at": None}],
        "active": {"version_id": WF, "version_no": 5, "status": "active"},
        "null_slot_decisions": 0,
        "head_topic": 2, "head_script": 3,
        "live_direction": {"directive_id": "D1", "revision": 3},
    })


def run(scen, cfg=None):
    cur = FakeCursor(scen)
    return frp.preflight(cur, GATE, SLOT, cfg=cfg if cfg is not None else copy.deepcopy(CFG)), cur


def codes(r):
    return [d["code"] for d in r["denials"]]


def main():
    print("#447 final_review_preflight focused tests")

    # ---- coherent -------------------------------------------------------------------------------
    r, cur = run(coherent_scenario())
    check("coherent -> available, reason_code=coherent, status=recorded, zero denials",
          r["available"] is True and r["reason_code"] == frp.COHERENT
          and r["status"] == frp.RECORDED and r["denials"] == [])
    check("coherent -> ALL SIX tuple members returned exactly as pinned",
          r["target_package_tuple"] == {"gate_id": GATE, "slot_id": SLOT, "snapshot_id": SNAP,
                                        "topic_revision": 2, "script_revision": 3,
                                        "workflow_version_id": WF})
    check("coherent -> pinned workflow is evidence, active is the coherence check, not divergent",
          r["evidence"]["workflow"]["pinned"]["version_id"] == WF
          and r["evidence"]["workflow"]["pinned"]["source"] == "script_provenance"
          and r["evidence"]["workflow"]["active"]["version_id"] == WF
          and r["evidence"]["workflow"]["divergent"] is False)
    check("coherent -> human floor reported STRUCTURALLY, authorization never evaluated",
          r["evidence"]["final_review"]["human_signoff_required"] is True
          and r["evidence"]["final_review"]["hard_floor_stage"] is True
          and r["evidence"]["final_review"]["authorization_evaluated"] is False)
    check("coherent -> present state reported from the actor-independent checks",
          r["evidence"]["present_state"]["gate_status"] == "open"
          and r["evidence"]["present_state"]["outcome"] == "approved"
          and r["evidence"]["present_state"]["governed_head"] == {"topic": 2, "script": 3})
    check("coherent -> pinned direction is evidence and agrees with the observed live row",
          r["evidence"]["production_direction"]["status"] == frp.RECORDED
          and r["evidence"]["production_direction"]["pinned"]["directive_id"] == "D1")
    check("classifications truthful (not_applicable/not_recorded), never enabled",
          r["evidence"]["classifications"] == {"agent_execution": "not_applicable",
                                               "agent_rep_delegation": "not_recorded",
                                               "provider_operation": "not_applicable",
                                               "secret_authority": "not_applicable"})

    # ---- NO AUTHORIZATION ORACLE ----------------------------------------------------------------
    blob = repr(r)
    check("no eligible principal / coverage principal id is ever disclosed",
          "P-SECRET" not in blob)
    check("no actor-dependent sign-off code can ever be emitted",
          not any(c in blob for c in frp.NEVER_EMITTED))
    check("no principal is ever loaded (no principal table read)",
          not any("FROM principal" in s for s in cur.executed))

    # ---- READ-ONLY proof ------------------------------------------------------------------------
    check("every executed statement is a SELECT",
          all(re.match(r"^\s*SELECT\b", s, re.I) for s in cur.executed) and len(cur.executed) > 0)
    check("no statement takes a FOR UPDATE lock (the #439 command locks; this read must not)",
          not any(re.search(r"\bFOR\s+UPDATE\b", s, re.I) for s in cur.executed))
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "final_review_preflight.py"), encoding="utf-8").read()
    body = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(("#", '"', "*")))
    check("module source contains no write / emission / provider / secret call",
          not re.search(r"\b(INSERT|UPDATE\s+\w+\s+SET|DELETE|COMMIT)\b", body, re.I)
          and not re.search(r"\b(script_to_production|emit_output|record\(|sign_off|"
                            r"load_principal|authorize_gate_decision)\b", body))

    # ---- NO INVENTED VOCABULARY -----------------------------------------------------------------
    canonical = ({v for k, v in vars(_proj).items() if k.startswith("R_")}
                 | {v for k, v in vars(_s4).items() if k.isupper() and isinstance(v, str)}
                 | set(engine.SIGNOFF_ERROR_STATUS))
    check("every precedence code is an EXISTING canonical classification",
          all(c in canonical for c in frp.REASON_PRECEDENCE))

    # ---- identity fail-closed --------------------------------------------------------------------
    sc = coherent_scenario(); sc["gate"] = None; sc["pkg_row"] = None
    sc["is_final_review_target"] = False
    r, _ = run(sc)
    check("unknown gate -> unavailable / not_a_final_review_target, no tuple",
          not r["available"] and r["status"] == frp.UNAVAILABLE
          and r["reason_code"] == frp.R_NOT_FINAL_REVIEW_TARGET
          and r["target_package_tuple"] is None)

    sc = coherent_scenario(); sc["gate"]["admitted"] = False
    r, _ = run(sc)
    check("recorded package but NOT an admitted target -> unavailable, fail closed",
          not r["available"] and r["status"] == frp.UNAVAILABLE
          and r["reason_code"] == frp.R_NOT_FINAL_REVIEW_TARGET)

    sc = coherent_scenario(); sc["gate"]["gate_stage"] = "script_review"
    r, _ = run(sc)
    check("non-final_review gate stage -> unavailable, fail closed",
          not r["available"] and r["status"] == frp.UNAVAILABLE)

    # ---- unconditional tuple ---------------------------------------------------------------------
    sc = coherent_scenario(); sc["pkg_row"] = None
    r, _ = run(sc)
    check("legacy admitted target (no snapshot row) -> unknown_history, missing package + legacy",
          not r["available"] and r["status"] == frp.UNKNOWN_HISTORY
          and r["reason_code"] == frp.R_MISSING_PACKAGE and frp.R_LEGACY in codes(r)
          and r["target_package_tuple"] is None)

    for member, col in (("snapshot_id", "snapshot_id"), ("topic_revision", "topic_revision"),
                        ("script_revision", "script_revision"),
                        ("workflow_version_id", "workflow_version_id")):
        sc = coherent_scenario(); sc["pkg_row"][col] = None
        r, _ = run(sc)
        check(f"NULL tuple member {member!r} -> unknown_history and NO partial tuple emitted",
              not r["available"] and r["status"] == frp.UNKNOWN_HISTORY
              and r["reason_code"] == frp.R_MISSING_PACKAGE and r["target_package_tuple"] is None)

    # ---- snapshot evidence -----------------------------------------------------------------------
    sc = coherent_scenario(); sc["gate_snapshot"] = None
    r, _ = run(sc)
    check("no governing gate snapshot -> unknown_history, missing_governing_gate_snapshot primary",
          not r["available"] and r["status"] == frp.UNKNOWN_HISTORY
          and r["reason_code"] == frp.R_MISSING_GATE_SNAPSHOT)
    check("no governing snapshot ALSO fails present-state closed (no evidence to establish it from)",
          frp.SIGNOFF_TARGET_UNAVAILABLE in codes(r))

    sc = coherent_scenario(); sc["gate_snapshot"]["authoritative"] = False
    r, _ = run(sc)
    check("non-authoritative (legacy) gate snapshot -> fail closed",
          not r["available"] and frp.R_MISSING_GATE_SNAPSHOT in codes(r))

    sc = coherent_scenario()
    sc["gate_snapshot"]["snapshot_id"] = "99999999-9999-9999-9999-999999999999"
    r, _ = run(sc)
    check("package snapshot != governing snapshot -> inconsistent_snapshot_reference, fail closed",
          not r["available"] and r["status"] == frp.UNKNOWN_HISTORY
          and r["reason_code"] == frp.R_INCONSISTENT_SNAPSHOT)

    # ---- governed generation coherence ------------------------------------------------------------
    sc = coherent_scenario(); sc["active"] = None
    r, _ = run(sc)
    check("no active workflow version -> active_workflow_unavailable, fail closed",
          not r["available"] and r["reason_code"] == frp.ACTIVE_WORKFLOW_UNAVAILABLE
          and r["evidence"]["workflow"]["active"] == {"status": "unavailable"})

    sc = coherent_scenario(); sc["active"]["version_id"] = "44444444-4444-4444-4444-444444444444"
    r, _ = run(sc)
    check("pinned vs active workflow divergence -> fail closed, pinned value NEVER rebound",
          not r["available"] and r["reason_code"] == frp.CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE
          and r["evidence"]["workflow"]["divergent"] is True
          and r["target_package_tuple"]["workflow_version_id"] == WF)

    # ---- structural human floor --------------------------------------------------------------------
    cfg = copy.deepcopy(CFG); cfg["actor_model"]["hard_floors"]["gates"] = []
    r, _ = run(coherent_scenario(), cfg=cfg)
    check("final_review not a hard-floor gate -> final_review_unknown, fail closed",
          not r["available"] and r["reason_code"] == frp.FINAL_REVIEW_UNKNOWN
          and r["evidence"]["final_review"]["human_signoff_required"] is False)

    cfg = copy.deepcopy(CFG); cfg["actor_model"]["enabled"] = False
    r, _ = run(coherent_scenario(), cfg=cfg)
    check("actor model disabled -> human floor not assertable, fail closed",
          not r["available"] and r["reason_code"] == frp.FINAL_REVIEW_UNKNOWN)

    # ---- present-state eligibility ------------------------------------------------------------------
    for status in ("closed", "parked"):
        sc = coherent_scenario(); sc["gate"]["gate_status"] = status
        r, _ = run(sc)
        check(f"gate status {status!r} -> signoff_blocked, fail closed",
              not r["available"] and frp.SIGNOFF_BLOCKED in codes(r))

    sc = coherent_scenario(); sc["null_slot_decisions"] = 1
    r, _ = run(sc)
    check("slot-unattributable decisions -> ambiguous present state, signoff_blocked",
          not r["available"] and frp.SIGNOFF_BLOCKED in codes(r))

    sc = coherent_scenario(); sc["head_script"] = 4
    r, _ = run(sc)
    check("governed head advanced past the pinned script revision -> signoff_stale",
          not r["available"] and r["reason_code"] == frp.SIGNOFF_STALE)

    sc = coherent_scenario(); sc["head_topic"] = 5
    r, _ = run(sc)
    check("governed head advanced past the pinned topic revision -> signoff_stale",
          not r["available"] and r["reason_code"] == frp.SIGNOFF_STALE)

    for decision, outcome in (("reject", "rejected"), ("request_change", "changes_requested")):
        sc = coherent_scenario()
        sc["decisions"] = [{"approver_id": "P-SECRET", "decision": decision, "revision": None,
                            "decided_at": None}]
        r, _ = run(sc)
        check(f"present outcome {outcome!r} -> signoff_blocked, fail closed",
              not r["available"] and frp.SIGNOFF_BLOCKED in codes(r)
              and r["evidence"]["present_state"]["outcome"] == outcome)

    sc = coherent_scenario(); sc["coverage"] = []
    r, _ = run(sc)
    check("pending (uncovered) present outcome -> signoff_blocked, fail closed",
          not r["available"] and frp.SIGNOFF_BLOCKED in codes(r)
          and r["evidence"]["present_state"]["outcome"] == "pending")

    # ---- production-direction coherence -------------------------------------------------------------
    sc = coherent_scenario(); sc["live_direction"] = None
    r, _ = run(sc)
    check("pinned direction no longer observable -> production_direction_mismatch",
          not r["available"] and frp.PRODUCTION_DIRECTION_MISMATCH in codes(r))

    sc = coherent_scenario(); sc["live_direction"]["revision"] = 9
    r, _ = run(sc)
    check("observed direction revision != pinned -> production_direction_mismatch",
          not r["available"] and frp.PRODUCTION_DIRECTION_MISMATCH in codes(r))

    sc = coherent_scenario(); sc["live_direction"]["directive_id"] = "D9"
    r, _ = run(sc)
    check("observed direction id != pinned -> production_direction_mismatch",
          not r["available"] and frp.PRODUCTION_DIRECTION_MISMATCH in codes(r))

    sc = coherent_scenario()
    sc["pkg_row"]["production_directive_id"] = None
    sc["pkg_row"]["production_directive_revision"] = None
    r, _ = run(sc)
    check("live direction the package never pinned -> disagreement, fail closed",
          not r["available"] and frp.PRODUCTION_DIRECTION_MISMATCH in codes(r))

    sc = coherent_scenario()
    sc["pkg_row"]["production_directive_id"] = None
    sc["pkg_row"]["production_directive_revision"] = None
    sc["live_direction"] = None
    r, _ = run(sc)
    check("no direction pinned AND none observed -> not_yet_recorded, NOT a denial",
          r["available"] is True
          and r["evidence"]["production_direction"]["status"] == frp.PRODUCTION_DIRECTION_NOT_YET_RECORDED)

    # ---- deterministic precedence ---------------------------------------------------------------------
    sc = coherent_scenario()
    sc["gate_snapshot"]["snapshot_id"] = "99999999-9999-9999-9999-999999999999"   # tier 1
    sc["active"] = None                                                          # tier 2
    sc["gate"]["gate_status"] = "closed"                                         # tier 4
    sc["live_direction"] = None                                                  # tier 5
    r, _ = run(sc)
    check("historical proof gap outranks present-state eligibility when BOTH fail",
          r["reason_code"] == frp.R_INCONSISTENT_SNAPSHOT)
    check("denials are returned pre-sorted in the documented precedence order",
          codes(r) == sorted(codes(r), key=frp.REASON_PRECEDENCE.index))
    check("a tier-1 historical gap sets status=unknown_history even with present-state failures",
          r["status"] == frp.UNKNOWN_HISTORY)

    sc = coherent_scenario()
    sc["gate"]["gate_status"] = "closed"                                         # tier 4 only
    r, _ = run(sc)
    check("present-state-only failure keeps status=recorded (history IS established)",
          r["status"] == frp.RECORDED and not r["available"]
          and r["reason_code"] == frp.SIGNOFF_BLOCKED
          and r["target_package_tuple"] is not None)

    print(f"\n{'ALL PASS' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
