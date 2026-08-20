"""#423 — read model for the immutable final-review target-package snapshot.

The SOLE typed disclosure surface for recorded-versus-`unknown_history` target-package evidence. A
pure SELECT: it reads only the persisted snapshot and never reconstructs history from current
selections, membership, the active workflow, or labels, and it never invokes attachment/authority
logic (so an attachment refusal can never surface here as an authorization result). Absence is a
truthful typed status — `unknown_history` for a legacy target (attached before migration 036) or
`unavailable` for a pair that is not a gate target — never an endpoint error.
"""
import uuid as _uuid

RECORDED = "recorded"
UNKNOWN_HISTORY = "unknown_history"
UNAVAILABLE = "unavailable"


def read(cur, gate_id, slot_id):
    """Return the typed target-package evidence for one (gate_id, slot_id). `cur` is a RealDictCursor."""
    try:
        _uuid.UUID(str(gate_id))
    except (ValueError, TypeError, AttributeError):
        return {"gate_id": str(gate_id), "slot_id": slot_id, "recorded": False,
                "status": UNAVAILABLE, "evidence": None}

    cur.execute(
        "SELECT gate_id::text AS gate_id, slot_id, snapshot_id::text AS snapshot_id, round_id, "
        "topic_id::text AS topic_id, topic_revision, script_id::text AS script_id, script_revision, "
        "workflow_version_id::text AS workflow_version_id, workflow_version_source, "
        "production_directive_id::text AS production_directive_id, production_directive_revision, "
        "attached_at "
        "FROM final_review_target_package WHERE gate_id=%s AND slot_id=%s", (str(gate_id), slot_id))
    row = cur.fetchone()
    if row:
        pd = ({"present": True, "directive_id": row["production_directive_id"],
               "revision": row["production_directive_revision"]}
              if row["production_directive_id"] else {"present": False})
        return {"gate_id": row["gate_id"], "slot_id": row["slot_id"], "recorded": True,
                "status": RECORDED,
                "evidence": {
                    "snapshot_id": row["snapshot_id"], "round_id": row["round_id"],
                    "topic_id": row["topic_id"], "topic_revision": row["topic_revision"],
                    "script_id": row["script_id"], "script_revision": row["script_revision"],
                    "workflow_version_id": row["workflow_version_id"],
                    "workflow_version_source": row["workflow_version_source"],
                    "production_direction": pd,
                    "attached_at": row["attached_at"].isoformat() if row["attached_at"] else None,
                }}
    # No snapshot. #425 finding 3 — stage-aware, from PERSISTED canonical gate data: `unknown_history`
    # applies ONLY to an admitted legacy target on a persisted `final_review` gate. A target on any
    # other stage, and a non-target pair, are `unavailable`. Stage is never reconstructed from live
    # Topic/Script/workflow/membership/labels.
    cur.execute("SELECT 1 FROM gate_target gt JOIN gate g ON g.gate_id=gt.gate_id "
                "WHERE gt.gate_id=%s AND gt.slot_id=%s AND g.stage='final_review'", (str(gate_id), slot_id))
    is_final_review_target = cur.fetchone() is not None
    return {"gate_id": str(gate_id), "slot_id": slot_id, "recorded": False,
            "status": UNKNOWN_HISTORY if is_final_review_target else UNAVAILABLE, "evidence": None}
