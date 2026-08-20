"""#427/#429 — runtime-free unit tests for gates/final_review_projection.py.

No DB, container, or network. Two layers:
  * `_assemble()` is pure logic over already-fetched evidence — exercised across the full typed-status
    and uncertainty-code matrix (recorded / legacy / missing-snapshot / inconsistent / ambiguous /
    gate-scoped-audit / incomplete-audit), including the #429 corrections:
      - gate-wide audit is a SEPARATE `audit_evidence` group, never nested in slot decision evidence;
      - the audit group NEVER reports `recorded`/`available` (only `gate_scoped_history` or `unavailable`);
      - decision/coverage stay reportable when audit is unavailable — groups have independent statuses;
      - ambiguous decision attribution fails closed (decision_evidence not recorded);
      - unavailable audit is never hidden behind a recorded decision/coverage group.
  * `read()`'s early typed-`unavailable` returns (malformed id, unknown gate, non-final-review stage,
    non-admitted pair) are proven with a FakeCursor answering only the identity SELECT.

Run:  python3 gates/final_review_projection_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import final_review_projection as frp  # noqa: E402

FAIL = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAIL.append(name)


def _pkg_recorded(snap="S1"):
    return {"gate_id": "G", "slot_id": "X", "recorded": True, "status": "recorded",
            "evidence": {"snapshot_id": snap, "round_id": "R", "topic_id": "T", "topic_revision": 1,
                         "script_id": "SC", "script_revision": 1, "workflow_version_id": "WV",
                         "workflow_version_source": "script_provenance",
                         "production_direction": {"present": False}, "attached_at": "2026-01-01T00:00:00"}}


def _pkg_unknown():
    return {"gate_id": "G", "slot_id": "X", "recorded": False, "status": "unknown_history",
            "evidence": None}


def _assignment(snap="S1"):
    return {"recorded": True, "status": "recorded", "snapshot_id": snap, "snapshot_version": 1,
            "opened_at": "2026-01-01T00:00:00", "rule_key": "all",
            "tokens": [{"token_kind": "role", "token_key": "reviewer", "normalized_token": "role:reviewer",
                        "eligible_principals": ["khal", "huda"]}]}


def _decision_ev(snap="S1", decisions=None, ambiguous=False):
    return {"recorded": not ambiguous, "status": frp.UNKNOWN_HISTORY if ambiguous else frp.RECORDED,
            "reasons": [frp.R_AMBIGUOUS_DECISION] if ambiguous else [],
            "governing_snapshot_id": snap, "outcome": "approved", "approval_count": 1,
            "distinct_principal_coverage": 1,
            "coverage": [{"token_kind": "role", "token_key": "reviewer",
                          "normalized_token": "role:reviewer", "covered_by": "khal"}],
            "decisions": decisions if decisions is not None else [
                {"approver_id": "khal", "decision": "approve", "revision": None,
                 "decided_at": "2026-01-01T00:00:00"}]}


def _audit_ev(events=None):
    evs = events if events is not None else [{"id": 1, "action": "gate_opened", "actor": "system",
                                              "at": "2026-01-01T00:00:00"}]
    return {"scope": "gate", "slot_attributable": False,
            "status": frp.AUDIT_GATE_SCOPED if evs else frp.UNAVAILABLE,
            "reasons": [frp.R_AUDIT_GATE_SCOPED_ONLY] + ([] if evs else [frp.R_INCOMPLETE_AUDIT]),
            "events": evs}


IDENT = {"gate_id": "G", "slot_id": "X", "gate_stage": "final_review", "gate_status": "open",
         "admitted": True}


def _assemble(**kw):
    args = {"gate_id": "G", "slot_id": "X", "identity": IDENT, "package": _pkg_recorded(),
            "assignment": _assignment(), "decision_evidence": _decision_ev(), "audit_evidence": _audit_ev(),
            "pkg_snapshot_id": "S1", "gov_snapshot_id": "S1", "ambiguous_decisions": False}
    args.update(kw)
    return frp._assemble(args["gate_id"], args["slot_id"], args["identity"], args["package"],
                         args["assignment"], args["decision_evidence"], args["audit_evidence"],
                         args["pkg_snapshot_id"], args["gov_snapshot_id"], args["ambiguous_decisions"])


def test_assemble():
    # 1 — fully recorded, consistent, complete: recorded / available / zero SLOT uncertainty.
    r = _assemble()
    check("full recorded -> status recorded", r["status"] == frp.RECORDED)
    check("full recorded -> available True", r["available"] is True)
    check("full recorded -> no slot uncertainty", r["uncertainty"] == [])
    check("full recorded -> carries all evidence groups incl separate audit_evidence",
          r["target_identity"] and r["package"] and r["assignment"] and r["decision_evidence"]
          and r["audit_evidence"] is not None)

    # #429 CORE — audit is a SEPARATE group, gate-scoped, never nested in decision_evidence, never recorded.
    check("audit is a separate top-level group (not nested in decision_evidence)",
          "audit" not in r["decision_evidence"] and "audit_evidence" in r)
    check("audit group is gate-scoped + not slot-attributable",
          r["audit_evidence"]["scope"] == "gate" and r["audit_evidence"]["slot_attributable"] is False)
    check("audit group never reports recorded/available",
          r["audit_evidence"]["status"] in (frp.AUDIT_GATE_SCOPED, frp.UNAVAILABLE)
          and r["audit_evidence"]["status"] != frp.RECORDED)
    check("audit group always carries the gate-scoped-only reason",
          frp.R_AUDIT_GATE_SCOPED_ONLY in r["audit_evidence"]["reasons"])

    # 2 — legacy target (no immutable package) but governing snapshot present.
    r = _assemble(package=_pkg_unknown(), pkg_snapshot_id=None)
    check("legacy package -> status unknown_history", r["status"] == frp.UNKNOWN_HISTORY)
    check("legacy package -> available False", r["available"] is False)
    check("legacy package -> missing-package + legacy codes",
          frp.R_MISSING_PACKAGE in r["uncertainty"] and frp.R_LEGACY in r["uncertainty"])

    # 3 — missing governing gate snapshot (legacy gate): assignment + decision evidence both absent.
    r = _assemble(package=_pkg_unknown(), assignment=None, decision_evidence=None,
                  pkg_snapshot_id=None, gov_snapshot_id=None)
    check("missing gate snapshot -> code present", frp.R_MISSING_GATE_SNAPSHOT in r["uncertainty"])
    check("missing gate snapshot -> unknown_history", r["status"] == frp.UNKNOWN_HISTORY)
    check("missing gate snapshot -> assignment/decision null",
          r["assignment"] is None and r["decision_evidence"] is None)

    # 4 — inconsistent snapshot reference fails closed (recorded package but snapshot ids diverge).
    r = _assemble(package=_pkg_recorded("S2"), pkg_snapshot_id="S2", gov_snapshot_id="S1",
                  assignment=_assignment("S1"), decision_evidence=_decision_ev("S1"))
    check("inconsistent snapshot -> code present", frp.R_INCONSISTENT_SNAPSHOT in r["uncertainty"])
    check("inconsistent snapshot -> NOT recorded (fail closed)", r["status"] == frp.UNKNOWN_HISTORY)
    check("inconsistent snapshot -> available False", r["available"] is False)

    # 5 — #429 ambiguous decision attribution (schema-impossible today) MUST fail closed.
    r = _assemble(decision_evidence=_decision_ev(ambiguous=True), ambiguous_decisions=True)
    check("ambiguous decision -> top-level code", frp.R_AMBIGUOUS_DECISION in r["uncertainty"])
    check("ambiguous decision -> top-level NOT recorded", r["status"] == frp.UNKNOWN_HISTORY and r["available"] is False)
    check("ambiguous decision -> decision_evidence group itself not recorded",
          r["decision_evidence"]["recorded"] is False and r["decision_evidence"]["status"] != frp.RECORDED
          and frp.R_AMBIGUOUS_DECISION in r["decision_evidence"]["reasons"])

    # 6 — #429 unavailable/incomplete audit is NOT hidden behind recorded decision/coverage.
    r = _assemble(audit_evidence=_audit_ev(events=[]))
    check("no audit events -> audit group unavailable + incomplete code",
          r["audit_evidence"]["status"] == frp.UNAVAILABLE
          and frp.R_INCOMPLETE_AUDIT in r["audit_evidence"]["reasons"])
    check("no audit events -> audit group NOT recorded/available",
          r["audit_evidence"]["status"] != frp.RECORDED)
    check("no audit events -> decision/coverage still recorded (independent groups)",
          r["decision_evidence"]["recorded"] is True and r["status"] == frp.RECORDED)
    check("no audit events -> unavailable audit is not collapsed into slot success (visible in its group)",
          r["audit_evidence"]["events"] == [] and r["audit_evidence"]["slot_attributable"] is False)

    # 7 — frozen eligibility is disclosed as history, structurally separate from any authorization field.
    r = _assemble()
    tok = r["assignment"]["tokens"][0]
    check("frozen eligibility exposed under eligible_principals (history, not authority)",
          "eligible_principals" in tok and "authorized" not in tok and "can_act" not in tok)


class FakeCursor:
    """Answers only the identity SELECT; every access is read-only. Used for read()'s early returns."""
    def __init__(self, row):
        self._row = row
        self._sql = ""

    def execute(self, sql, params=()):
        self._sql = sql

    def fetchone(self):
        if "FROM gate g LEFT JOIN gate_target" in self._sql:
            return self._row
        raise AssertionError("read() ran SQL beyond the identity lookup on an early-return path")


def test_read_early_returns():
    r = frp.read(FakeCursor(None), "not-a-uuid", "X")
    check("malformed gate_id -> unavailable", r["status"] == frp.UNAVAILABLE and r["available"] is False)
    check("malformed gate_id -> not-final-review-target reason",
          r["uncertainty"] == [frp.R_NOT_FINAL_REVIEW_TARGET])
    check("malformed gate_id -> audit_evidence key present (null)", r["audit_evidence"] is None)

    gid = "11111111-1111-1111-1111-111111111111"
    r = frp.read(FakeCursor(None), gid, "X")
    check("unknown gate -> unavailable, null identity", r["status"] == frp.UNAVAILABLE and r["target_identity"] is None)

    r = frp.read(FakeCursor({"gate_id": gid, "gate_stage": "script_review", "gate_status": "open",
                             "admitted": True}), gid, "X")
    check("non-final-review stage -> unavailable with identity",
          r["status"] == frp.UNAVAILABLE and r["target_identity"]["gate_stage"] == "script_review")

    r = frp.read(FakeCursor({"gate_id": gid, "gate_stage": "final_review", "gate_status": "open",
                             "admitted": False}), gid, "X")
    check("non-admitted pair -> unavailable", r["status"] == frp.UNAVAILABLE and r["target_identity"]["admitted"] is False)


if __name__ == "__main__":
    print("#427/#429 final_review_projection runtime-free unit tests")
    test_assemble()
    test_read_early_returns()
    print()
    if FAIL:
        print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
        sys.exit(1)
    print("ALL #427/#429 final_review_projection unit checks PASSED")
    sys.exit(0)
