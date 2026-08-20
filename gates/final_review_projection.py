"""#427 — additive backend read projection for one canonical admitted final-review target.
(#429 — corrected: gate-scoped audit is a SEPARATE, honestly gate-scoped evidence group; it is never
promoted to slot-attributable decision evidence, and every evidence group carries an independent,
fail-closed status.)

Server-authoritative, strictly READ-ONLY join of already-persisted evidence for a single admitted
final-review `(gate_id, slot_id)` target. It COMPOSES existing frozen truths and invents none, keeping
each evidence group INDEPENDENTLY attributed by its own canonical persisted keys:

  * exact attached package  -> `final_review_target_package.read` (#423/#425/#426 immutable snapshot)
  * governing assignment    -> `engine._load_gate_snapshot`      (#282/#422 gate-wide frozen snapshot)
  * decision / coverage      -> `engine._authoritative_target_projection` over persisted
                                `gate_token_coverage` (#321 head-correct) + the raw `gate_decision`
                                rows keyed to THIS exact `(gate_id, slot_id)` (canonical slot+snapshot
                                attribution).
  * audit                    -> gate-scoped `audit_log` history ONLY. `audit_log` carries NO canonical
                                column tying a row to a `(gate_id, slot_id, snapshot_id)` triple, so an
                                audit row is exposed as GATE-scoped history and is NEVER reported as
                                slot-attributable decision evidence. Gate association, actor, revision,
                                event kind, outcome, or timestamp proximity is NOT slot linkage.

Canonical attribution rule: a fact is attributed to `(gate, slot, snapshot)` only through an enforced
persisted key/relation, never through inference. Ambiguous, incomplete, conflicting, or
slot-unattributable evidence FAILS CLOSED — the affected group reports a typed non-`recorded` status
with a stable reason code, and it can never be hidden behind another group's success (there is no
combined decision/audit status). A group reports `recorded`/`available` only when the evidence required
for THAT group is canonically complete and unambiguous.

Schema-impossible boundaries (documented, not simulated):
  * Whole-batch / NULL-slot decision ambiguity cannot be persisted — `gate_decision` PK
    `(gate_id, approver_id, slot_id)` forces `slot_id` NOT NULL. The defensive check below can never
    fire against repository-realistic rows; it exists so the code fails closed if that ever changes.
  * Canonical slot attribution of an `audit_log` row is impossible under the current schema (no FK or
    column relates an audit row to a slot/snapshot). Audit therefore stays gate-scoped by construction.

Every value is read from persisted rows. It never re-resolves current Topic/Script/workflow/selection/
production-direction/membership/role/group/label state to reconstruct history, never creates a
target-level assignment snapshot (assignment truth stays gate-wide per #422), never evaluates present
action authorization, and never mutates. Frozen historical eligibility and present action authority are
SEPARATE facts: frozen eligible principals are disclosed as recorded history, never as a present right
to act.

Additivity: this is a NEW read model behind a NEW route. The #423 `/target-package` V1 route and its
response shape are untouched.
"""
import uuid as _uuid

import engine
import final_review_target_package as _pkg

FINAL_REVIEW_STAGE = "final_review"

# top-level typed status
RECORDED = "recorded"
UNKNOWN_HISTORY = "unknown_history"
UNAVAILABLE = "unavailable"
# audit-group-only status: gate-scoped history present but NOT slot-attributable (never `recorded`).
AUDIT_GATE_SCOPED = "gate_scoped_history"

# machine-readable historical-uncertainty reason codes
R_NOT_FINAL_REVIEW_TARGET = "not_a_final_review_target"
R_MISSING_PACKAGE = "missing_target_package_snapshot"
R_MISSING_GATE_SNAPSHOT = "missing_governing_gate_snapshot"
R_INCONSISTENT_SNAPSHOT = "inconsistent_snapshot_reference"
R_LEGACY = "legacy_record_predating_authoritative_snapshots"
R_AMBIGUOUS_DECISION = "ambiguous_decision_attribution"
R_INCOMPLETE_AUDIT = "incomplete_canonical_audit_evidence"
# #429 — narrow code distinguishing slot-unattributable gate-wide audit from slot decision evidence.
R_AUDIT_GATE_SCOPED_ONLY = "audit_gate_scoped_not_slot_attributable"


def _iso(v):
    return v.isoformat() if v is not None and hasattr(v, "isoformat") else v


def _unavailable(gate_id, slot_id, identity, reason):
    return {"gate_id": str(gate_id), "slot_id": slot_id, "available": False, "status": UNAVAILABLE,
            "target_identity": identity, "package": None, "assignment": None,
            "decision_evidence": None, "audit_evidence": None, "uncertainty": [reason]}


def read(cur, gate_id, slot_id):
    """Return the typed final-review projection for one `(gate_id, slot_id)`. `cur` is a RealDictCursor.

    Resolves exactly one canonical ADMITTED final-review target. A malformed id, an unknown gate, a
    non-`final_review` gate, or a `(gate, slot)` pair that is not an admitted target all return a
    typed `unavailable` status (never an error). An admitted final-review target returns `recorded`
    when the immutable package snapshot and the governing gate-wide snapshot are both present,
    consistent, and decision/coverage is unambiguously attributable, else `unknown_history` with
    explicit reason codes. Audit is always a separate, gate-scoped group and never gates slot success.
    """
    try:
        _uuid.UUID(str(gate_id))
    except (ValueError, TypeError, AttributeError):
        return _unavailable(gate_id, slot_id, None, R_NOT_FINAL_REVIEW_TARGET)

    # (1) Target identity — canonical persisted gate + admission only; no client-derived values.
    cur.execute(
        "SELECT g.gate_id::text AS gate_id, g.stage AS gate_stage, g.status::text AS gate_status, "
        "(gt.slot_id IS NOT NULL) AS admitted "
        "FROM gate g LEFT JOIN gate_target gt ON gt.gate_id=g.gate_id AND gt.slot_id=%s "
        "WHERE g.gate_id=%s", (slot_id, str(gate_id)))
    grow = cur.fetchone()
    if grow is None:
        return _unavailable(gate_id, slot_id, None, R_NOT_FINAL_REVIEW_TARGET)
    identity = {"gate_id": grow["gate_id"], "slot_id": slot_id, "gate_stage": grow["gate_stage"],
                "gate_status": grow["gate_status"], "admitted": bool(grow["admitted"])}
    if grow["gate_stage"] != FINAL_REVIEW_STAGE or not grow["admitted"]:
        return _unavailable(gate_id, slot_id, identity, R_NOT_FINAL_REVIEW_TARGET)

    # (2) Exact attached package evidence — reused verbatim from the immutable #423 snapshot read model.
    package = _pkg.read(cur, gate_id, slot_id)
    pkg_snapshot_id = (package.get("evidence") or {}).get("snapshot_id") if package.get("recorded") else None

    # (3) Governing assignment evidence — gate-wide frozen snapshot only. Never a target-level snapshot.
    snapshot = engine._load_gate_snapshot(cur, str(gate_id))
    assignment = None
    gov_snapshot_id = None
    if snapshot is not None:
        gov_snapshot_id = str(snapshot["snapshot_id"])
        cur.execute("SELECT snapshot_version, opened_at FROM gate_snapshot WHERE gate_id=%s", (str(gate_id),))
        meta = cur.fetchone() or {}
        assignment = {
            "recorded": True, "status": RECORDED,
            "snapshot_id": gov_snapshot_id,
            "snapshot_version": meta.get("snapshot_version"),
            "opened_at": _iso(meta.get("opened_at")),
            "rule_key": snapshot["rule_key"],
            "tokens": [{"token_kind": t["kind"], "token_key": t["key"],
                        "normalized_token": t["normalized"],
                        # FROZEN historical eligibility — recorded history, NOT present authorization.
                        "eligible_principals": sorted(t["eligible"])}
                       for t in snapshot["tokens"]],
        }

    # (4a) Decision / coverage — CANONICAL slot+snapshot attribution only (keyed by gate_id + slot_id,
    #      coverage additionally carries snapshot_id). Built only when a governing snapshot exists.
    decision_evidence = None
    ambiguous_decisions = False
    if snapshot is not None:
        # Schema-impossible defensive check: `gate_decision` PK forbids a NULL slot_id, so a whole-batch
        # (slot-unattributable) decision cannot be persisted. If one ever appears, fail closed.
        cur.execute("SELECT count(*) AS n FROM gate_decision WHERE gate_id=%s AND slot_id IS NULL",
                    (str(gate_id),))
        ambiguous_decisions = (cur.fetchone()["n"] or 0) > 0

        cur.execute("SELECT approver_id, decision::text AS decision, revision, decided_at "
                    "FROM gate_decision WHERE gate_id=%s AND slot_id=%s "
                    "ORDER BY decided_at, approver_id", (str(gate_id), slot_id))
        decisions = cur.fetchall()
        # Head-correct persisted coverage (projection reads gate_token_coverage; never re-derives it).
        proj = engine._authoritative_target_projection(cur, str(gate_id), snapshot, slot_id, decisions)
        distinct_principals = sorted({c["covered_by"] for c in proj["coverage"] if c["covered_by"]})

        decision_evidence = {
            "recorded": not ambiguous_decisions,
            "status": UNKNOWN_HISTORY if ambiguous_decisions else RECORDED,   # fail closed on ambiguity
            "reasons": [R_AMBIGUOUS_DECISION] if ambiguous_decisions else [],
            "governing_snapshot_id": gov_snapshot_id,
            "outcome": proj["current_outcome"],            # persisted decision state; existing taxonomy
            "approval_count": proj["approval_count"],
            "distinct_principal_coverage": len(distinct_principals),
            "coverage": proj["coverage"],
            "decisions": [{"approver_id": d["approver_id"], "decision": d["decision"],
                           "revision": d["revision"], "decided_at": _iso(d["decided_at"])}
                          for d in decisions],
        }

    # (4b) Audit — GATE-scoped history ONLY. No canonical persisted relation links an audit_log row to
    #      a slot/snapshot, so this group is never slot-attributable and never reports `recorded`. It is
    #      independent: it neither gates slot success nor is hidden behind decision/coverage success.
    cur.execute("SELECT id, action, actor, at FROM audit_log "
                "WHERE entity='gate' AND entity_id=%s ORDER BY at, id", (str(gate_id),))
    audit_events = [{"id": r["id"], "action": r["action"], "actor": r["actor"], "at": _iso(r["at"])}
                    for r in cur.fetchall()]
    audit_evidence = {
        "scope": "gate",
        "slot_attributable": False,
        "status": AUDIT_GATE_SCOPED if audit_events else UNAVAILABLE,
        "reasons": [R_AUDIT_GATE_SCOPED_ONLY] + ([] if audit_events else [R_INCOMPLETE_AUDIT]),
        "events": audit_events,
    }

    return _assemble(gate_id, slot_id, identity, package, assignment, decision_evidence,
                     audit_evidence, pkg_snapshot_id, gov_snapshot_id, ambiguous_decisions)


def _assemble(gate_id, slot_id, identity, package, assignment, decision_evidence, audit_evidence,
              pkg_snapshot_id, gov_snapshot_id, ambiguous_decisions):
    """Pure typed-status + uncertainty assembly over already-fetched evidence (no DB access).

    Precondition (guaranteed by `read`): `identity` is an admitted `final_review` target. The result is
    therefore `recorded` or `unknown_history`, never `unavailable`. Top-level success reflects the
    canonical SLOT evidence (package + governing snapshot + unambiguous decision/coverage) only; the
    gate-scoped `audit_evidence` group carries its own independent status and never affects it.
    """
    uncertainty = []
    pkg_status = package.get("status")

    if assignment is None:
        uncertainty.append(R_MISSING_GATE_SNAPSHOT)
    if pkg_status == UNKNOWN_HISTORY:
        uncertainty += [R_MISSING_PACKAGE, R_LEGACY]
    elif pkg_status != RECORDED:                     # defensive: unexpected package status
        uncertainty.append(R_MISSING_PACKAGE)

    inconsistent = bool(pkg_snapshot_id and gov_snapshot_id and pkg_snapshot_id != gov_snapshot_id)
    if inconsistent:
        uncertainty.append(R_INCONSISTENT_SNAPSHOT)
    if ambiguous_decisions:                          # schema-impossible today; fail closed if it occurs
        uncertainty.append(R_AMBIGUOUS_DECISION)
    # Audit is a SEPARATE, self-describing gate-scoped group: its "gate-scoped only" fact and any
    # unavailability live in `audit_evidence.status`/`.reasons`, never rolled into the slot-evidence
    # uncertainty and never allowed to read as slot success. Top-level uncertainty and `recorded`
    # therefore describe the canonical SLOT evidence only — audit can never hide behind them, and its
    # unavailability can never downgrade genuinely recorded decision/coverage.

    recorded = (pkg_status == RECORDED and assignment is not None and not inconsistent
                and not ambiguous_decisions)
    status = RECORDED if recorded else UNKNOWN_HISTORY

    return {"gate_id": str(gate_id), "slot_id": slot_id, "available": recorded, "status": status,
            "target_identity": identity, "package": package, "assignment": assignment,
            "decision_evidence": decision_evidence, "audit_evidence": audit_evidence,
            "uncertainty": uncertainty}
