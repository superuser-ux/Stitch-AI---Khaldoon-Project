"""#447 — Stage 4 approval-package preflight and exact source pinning (read-only, server-authoritative).

The read-only GET counterpart of the #439 sign-off COMMAND. For one canonical `(gate_id, slot_id)`
final-review target it answers exactly one question from already-persisted records:

    is this exact IMMUTABLE pinned package still coherent, still governed by the current generation,
    and still in a presently-eligible state for a human final-review sign-off — and if so, what are
    the exact six values that identify it?

It returns the unconditional six-member `final_review_target_package` tuple —
`gate_id, slot_id, snapshot_id, topic_revision, script_revision, workflow_version_id` — the current
governed workflow version, current final-review eligibility, the STRUCTURAL human-authority floor, and
the existing Script-to-Production direction as read-only downstream evidence; or it fails closed with
canonical server-authored reasons.

Hard contract (approved body `20bc914d…7405` + the Codex reconciliation of the critical preflight):

  * READ-ONLY. Every statement is a pure SELECT with no `FOR UPDATE` (the #439 command locks; this
    path must not). It never writes, never advances lifecycle, never grants capability, and never
    invokes a builder / emission / record / provider / secret / model path. An existing production
    direction is OBSERVED, never generated.
  * IDENTITY is `(gate_id, slot_id)` (Q1). There is NO slot-only gate-resolution heuristic: choosing
    "the latest" or "the open" final_review gate for a slot would MINT selection policy in a read
    model. A missing, ambiguous, or unverifiable gate/package identity fails closed.
  * AUTHORITY is STRUCTURAL ONLY (Q2). This module never evaluates a caller, never selects an actor,
    never loads a principal, and never discloses frozen eligible principals or coverage principal IDs.
    It reports only whether `final_review` IS a hard-floor gate under the active actor model. Principal
    authorization remains the sign-off command's server-side responsibility. Building a per-actor
    verdict here would be an authorization-probing GET — explicitly out of scope.
  * The SIX-MEMBER TUPLE IS UNCONDITIONAL. It is emitted only when the immutable package row is
    `recorded` AND every member is present; a partially pinned package is NEVER returned as coherent
    (Q4). A non-admitted / non-snapshotted candidate fails closed.
  * `snapshot_id` is the IMMUTABLE PACKAGE-ROW value (Q5), and #427's package-vs-governing snapshot
    inconsistency check is inherited as fail-closed.
  * PINNED FIELDS ARE THE EVIDENCE; LIVE READS ARE COHERENCE CHECKS ONLY (Q7/Q8). Workflow-version
    divergence (pinned vs currently-active) and production-direction disagreement fail closed. Live
    state never overwrites, replaces, or "refreshes" a pinned value.
  * NO NEW POLICY VOCABULARY (Q6). Every reason code is IMPORTED from an existing canonical
    classification — `final_review_projection` (historical attribution), `stage4_preflight` (#419
    lineage/workflow/direction), and `engine.SIGNOFF_ERROR_STATUS` (present state). Codes are never
    re-typed as string literals here, so the vocabularies cannot drift.
  * PRECEDENCE IS DETERMINISTIC and documented by `REASON_PRECEDENCE` below: missing/unknown
    HISTORICAL proof outranks present-state eligibility whenever both are unavailable.
  * Present-state reason codes are reported as READ-MODEL EVIDENCE, never as command error semantics
    and never as an authorization result. The two ACTOR-DEPENDENT sign-off codes
    (`signoff_not_authorized`, `signoff_hard_floor`) can NEVER be emitted by this module — see
    `NEVER_EMITTED`.

Additivity: a NEW module behind a NEW route. #419's `stage4_preflight` module, route, response shape,
client panel and e2e surface are untouched (Q3), as are #423's `/target-package` and #427's
`/final-review-projection`. No schema, migration, or persisted state is involved.
"""
import actors
import engine
import final_review_projection as _proj
import final_review_target_package as _pkg
import stage4_preflight as _s4

FINAL_REVIEW_STAGE = engine.FINAL_REVIEW_STAGE

# ---- historical-evidence status (reused verbatim from #423/#427) --------------------------------
RECORDED = _proj.RECORDED
UNKNOWN_HISTORY = _proj.UNKNOWN_HISTORY
UNAVAILABLE = _proj.UNAVAILABLE

# ---- eligibility verdict code (reused verbatim from #419) ---------------------------------------
COHERENT = _s4.COHERENT

# ---- canonical reason classifications, IMPORTED (never re-typed) --------------------------------
# tier 1 — historical attribution / immutable proof (#427/#429)
R_NOT_FINAL_REVIEW_TARGET = _proj.R_NOT_FINAL_REVIEW_TARGET
R_MISSING_PACKAGE = _proj.R_MISSING_PACKAGE
R_LEGACY = _proj.R_LEGACY
R_MISSING_GATE_SNAPSHOT = _proj.R_MISSING_GATE_SNAPSHOT
R_INCONSISTENT_SNAPSHOT = _proj.R_INCONSISTENT_SNAPSHOT
# tier 2 — governed generation coherence (#419)
ACTIVE_WORKFLOW_UNAVAILABLE = _s4.ACTIVE_WORKFLOW_UNAVAILABLE
CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE = _s4.CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE
# tier 3 — structural human-authority floor (#419)
FINAL_REVIEW_UNKNOWN = _s4.FINAL_REVIEW_UNKNOWN
# tier 4 — present-state eligibility (#439 canonical map keys, as READ-MODEL evidence)
SIGNOFF_TARGET_UNAVAILABLE = "signoff_target_unavailable"
SIGNOFF_BLOCKED = "signoff_blocked"
SIGNOFF_STALE = "signoff_stale"
# tier 5 — downstream direction coherence (#419)
PRODUCTION_DIRECTION_MISMATCH = _s4.PRODUCTION_DIRECTION_MISMATCH
PRODUCTION_DIRECTION_NOT_YET_RECORDED = _s4.PRODUCTION_DIRECTION_NOT_YET_RECORDED

# The present-state codes above are the EXACT keys of engine.SIGNOFF_ERROR_STATUS; binding them here
# fails at import if #439's canonical map ever drops or renames one, so the vocabularies cannot drift.
for _code in (SIGNOFF_TARGET_UNAVAILABLE, SIGNOFF_BLOCKED, SIGNOFF_STALE):
    assert _code in engine.SIGNOFF_ERROR_STATUS, f"unknown canonical sign-off code {_code!r}"

# The ACTOR-DEPENDENT sign-off codes. This module evaluates no caller, so it can never emit either;
# `_deny` refuses them defensively and the focused test asserts they never appear in any output.
NEVER_EMITTED = ("signoff_not_authorized", "signoff_hard_floor")

# ---- deterministic reason precedence (Q6) -------------------------------------------------------
# Primary `reason_code` = the FIRST entry present in `denials`. Missing/unknown HISTORICAL proof
# (tier 1) outranks governed-generation coherence, the structural authority floor, present-state
# eligibility, and downstream direction coherence — so when history is unavailable the client is told
# that, rather than a present-state symptom derived from evidence that was never established.
REASON_PRECEDENCE = (
    # tier 1 — historical / immutable proof
    R_NOT_FINAL_REVIEW_TARGET,
    R_MISSING_PACKAGE,
    R_LEGACY,
    R_MISSING_GATE_SNAPSHOT,
    R_INCONSISTENT_SNAPSHOT,
    # tier 2 — governed generation coherence
    ACTIVE_WORKFLOW_UNAVAILABLE,
    CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE,
    # tier 3 — structural human-authority floor
    FINAL_REVIEW_UNKNOWN,
    # tier 4 — present-state eligibility
    SIGNOFF_TARGET_UNAVAILABLE,
    SIGNOFF_BLOCKED,
    SIGNOFF_STALE,
    # tier 5 — downstream direction coherence
    PRODUCTION_DIRECTION_MISMATCH,
)

# Codes whose presence means the HISTORICAL evidence itself is not established (=> UNKNOWN_HISTORY).
_HISTORICAL_CODES = frozenset(
    (R_MISSING_PACKAGE, R_LEGACY, R_MISSING_GATE_SNAPSHOT, R_INCONSISTENT_SNAPSHOT))

# The six unconditional tuple members (#438 decision record / #439 binding fields).
TUPLE_MEMBERS = ("gate_id", "slot_id", "snapshot_id", "topic_revision", "script_revision",
                 "workflow_version_id")

# Truthful classifications for recorded seams that are NOT live grants (reused verbatim from #419).
NOT_APPLICABLE = _s4.NOT_APPLICABLE
NOT_RECORDED = _s4.NOT_RECORDED


def _empty_evidence():
    return {
        "workflow": {"pinned": None, "active": None, "divergent": None},
        "final_review": None,
        "present_state": None,
        "production_direction": None,
        # recorded seams only — never a live grant; reported truthfully (#419 parity).
        "classifications": {
            "agent_execution": NOT_APPLICABLE,
            "agent_rep_delegation": NOT_RECORDED,
            "provider_operation": NOT_APPLICABLE,
            "secret_authority": NOT_APPLICABLE,
        },
    }


def _result(gate_id, slot_id, status, denials, identity=None, package=None, tuple_=None,
            evidence=None):
    """Assemble the typed read model. `available` is True only when NOTHING failed; `reason_code` is
    the deterministic primary reason by `REASON_PRECEDENCE`, or `coherent`. Denials are returned in
    precedence order so the client never has to sort or re-rank server truth."""
    ordered = sorted(denials, key=lambda d: REASON_PRECEDENCE.index(d["code"]))
    available = not ordered
    return {
        "gate_id": str(gate_id), "slot_id": slot_id,
        "available": available,
        "status": status,
        "reason_code": COHERENT if available else ordered[0]["code"],
        "detail": ("the immutable target package is fully pinned, governed by the current generation, "
                   "and presently eligible for human final-review sign-off"
                   if available else ordered[0]["detail"]),
        "target_identity": identity,
        # The immutable #423 evidence, rendered verbatim (never re-derived from live state).
        "package": package,
        # The six unconditional members — emitted ONLY when fully pinned; never partial.
        "target_package_tuple": tuple_,
        "evidence": evidence if evidence is not None else _empty_evidence(),
        "denials": ordered,
    }


def preflight(cur, gate_id, slot_id, cfg=None):
    """Return the typed Stage 4 approval-package preflight for one `(gate_id, slot_id)`.

    `cur` must be a RealDictCursor. Pure SELECTs only. Never raises for a not-eligible outcome — every
    failure fails closed into typed data. Malformed ids, unknown gates, non-`final_review` gates and
    non-admitted pairs return `unavailable`; an admitted target with incomplete immutable proof returns
    `unknown_history`; an admitted target with complete proof returns `recorded` plus an `available`
    eligibility verdict."""
    cfg = cfg if cfg is not None else engine.load_config()
    denials = []

    def deny(code, detail):
        assert code not in NEVER_EMITTED, f"actor-dependent code {code!r} is never emitted by a read model"
        denials.append({"code": code, "detail": detail})

    # ---- (1) Target identity — canonical persisted gate + admission only (no client-derived values).
    # Delegated verbatim to the #427 read model's own identity resolution so the two surfaces can never
    # disagree about what an admitted final-review target IS.
    package = _pkg.read(cur, gate_id, slot_id)
    if package["status"] == UNAVAILABLE:
        # Malformed id, unknown gate, non-final_review stage, or a pair that is not a gate target.
        return _result(gate_id, slot_id, UNAVAILABLE,
                       [{"code": R_NOT_FINAL_REVIEW_TARGET,
                         "detail": "no admitted canonical final_review target resolves this (gate, slot) "
                                   "identity"}],
                       package=package)

    # Admission is proved INDEPENDENTLY of the snapshot row: a persisted package row is not by itself
    # proof that the pair is still a canonical admitted final_review target.
    cur.execute("SELECT g.gate_id::text AS gate_id, g.stage AS gate_stage, g.status::text AS gate_status, "
                "(gt.slot_id IS NOT NULL) AS admitted "
                "FROM gate g LEFT JOIN gate_target gt ON gt.gate_id=g.gate_id AND gt.slot_id=%s "
                "WHERE g.gate_id=%s", (slot_id, str(gate_id)))
    grow = cur.fetchone()
    if grow is None or grow["gate_stage"] != FINAL_REVIEW_STAGE or not grow["admitted"]:
        return _result(gate_id, slot_id, UNAVAILABLE,
                       [{"code": R_NOT_FINAL_REVIEW_TARGET,
                         "detail": "no admitted canonical final_review target resolves this (gate, slot) "
                                   "identity"}],
                       package=package)
    identity = {"gate_id": grow["gate_id"], "slot_id": slot_id, "gate_stage": grow["gate_stage"],
                "gate_status": grow["gate_status"], "admitted": True}

    # ---- (2) The immutable six-member tuple — UNCONDITIONAL, never partial.
    if package["status"] != RECORDED:
        # An admitted legacy target attached before migration 036: the tuple is not derivable and is
        # NEVER synthesized or backfilled from live selections.
        return _result(gate_id, slot_id, UNKNOWN_HISTORY,
                       [{"code": R_MISSING_PACKAGE,
                         "detail": "no immutable final-review target-package snapshot is recorded for "
                                   "this admitted target; the six-member tuple is not derivable"},
                        {"code": R_LEGACY,
                         "detail": "target predates the authoritative target-package snapshot"}],
                       identity=identity, package=package)

    pkg_ev = package["evidence"]
    tuple_ = {"gate_id": package["gate_id"], "slot_id": package["slot_id"],
              "snapshot_id": pkg_ev["snapshot_id"], "topic_revision": pkg_ev["topic_revision"],
              "script_revision": pkg_ev["script_revision"],
              "workflow_version_id": pkg_ev["workflow_version_id"]}
    missing = [m for m in TUPLE_MEMBERS if tuple_[m] is None]
    if missing:
        # A recorded row with a NULL member cannot be repaired by inference — fail closed and emit NO
        # tuple at all (a partially pinned package is never returned).
        return _result(gate_id, slot_id, UNKNOWN_HISTORY,
                       [{"code": R_MISSING_PACKAGE,
                         "detail": f"recorded package snapshot is missing required tuple member(s): "
                                   f"{', '.join(missing)}"}],
                       identity=identity, package=package)

    evidence = _empty_evidence()

    # ---- (3) Governing gate-wide snapshot + the inherited #427 consistency check (Q5).
    snapshot = engine._load_gate_snapshot(cur, str(gate_id))
    if snapshot is None:
        deny(R_MISSING_GATE_SNAPSHOT,
             "no authoritative governing gate snapshot exists for this gate (legacy gate); the pinned "
             "package has no governing assignment truth to be consistent with")
    elif str(snapshot["snapshot_id"]) != str(tuple_["snapshot_id"]):
        # NOTE: the snapshot's frozen tokens / eligible principals are deliberately NOT read, counted,
        # or disclosed here (Q2) — only the snapshot IDENTITY is compared.
        deny(R_INCONSISTENT_SNAPSHOT,
             "the immutable package snapshot reference does not match the gate's governing snapshot")

    # ---- (4) Governed generation coherence — PINNED is evidence, ACTIVE is a coherence check (Q7).
    evidence["workflow"]["pinned"] = {"version_id": tuple_["workflow_version_id"],
                                      "source": pkg_ev["workflow_version_source"]}
    active = _s4._active_workflow_version(cur)
    if not active:
        evidence["workflow"]["active"] = {"status": "unavailable"}
        deny(ACTIVE_WORKFLOW_UNAVAILABLE, "no active workflow version exists for this tenant/module")
    else:
        evidence["workflow"]["active"] = {"version_id": active["version_id"],
                                          "version_no": active["version_no"],
                                          "status": active["status"]}
        divergent = str(tuple_["workflow_version_id"]) != str(active["version_id"])
        evidence["workflow"]["divergent"] = divergent
        if divergent:
            # #419 precedent, inherited: never eligible by implication, never a silent rebinding.
            deny(CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE,
                 "the package pins a workflow version that is no longer the active generation; it "
                 "requires reconsideration under the then-current process (no silent rebinding)")

    # ---- (5) STRUCTURAL human-authority floor (Q2) — a config predicate, never a principal check.
    # `actors.is_hard_floor_gate` is principal-free by construction. No principal is loaded, no actor
    # is selected, no caller is evaluated, and no eligible-principal set is read or disclosed.
    actor_model_enabled = bool(actors.enabled(cfg))
    hard_floor_stage = bool(actors.is_hard_floor_gate(cfg, FINAL_REVIEW_STAGE))
    enforced = actor_model_enabled and hard_floor_stage
    evidence["final_review"] = {
        "stage": FINAL_REVIEW_STAGE,
        "actor_model_enabled": actor_model_enabled,
        "hard_floor_stage": hard_floor_stage,
        "human_signoff_required": enforced,
        "source": "actor_model_hard_floor",
        # Explicit, so no client can read authority into this surface.
        "authorization_evaluated": False,
    }
    if not enforced:
        # #419 precedent: if the human floor is not enforced we cannot ASSERT human-required truth.
        deny(FINAL_REVIEW_UNKNOWN,
             "the existing server authority does not currently enforce a human hard floor on "
             "final_review; human-required truth cannot be asserted")

    # ---- (6) Present-state eligibility — the ACTOR-INDEPENDENT prefix of the #439 revalidation, in
    # the IDENTICAL order, reusing the IDENTICAL helpers. The actor-dependent tail (frozen-eligibility
    # membership + the per-principal hard-floor verdict) is deliberately NOT evaluated here and stays
    # the sign-off command's responsibility. `_signoff_revalidate_present_authority` is NOT called and
    # NOT refactored — #439's merged behaviour is untouched.
    present = {"gate_status": grow["gate_status"], "outcome": None,
               "governed_head": {"topic": None, "script": None}}
    if grow["gate_status"] != "open":
        deny(SIGNOFF_BLOCKED, "the gate's present state is not actionable (gate is not open)")
    if snapshot is not None:
        # Schema-impossible defensive check (gate_decision forbids a NULL slot_id): a slot-unattributable
        # decision cannot be persisted. Fail closed if one ever appears.
        cur.execute("SELECT count(*) AS n FROM gate_decision WHERE gate_id=%s AND slot_id IS NULL",
                    (str(gate_id),))
        if (cur.fetchone()["n"] or 0) > 0:
            deny(SIGNOFF_BLOCKED, "slot-unattributable decision rows make the present state ambiguous")

        head_topic = engine._head_revision(cur, slot_id, "topic")
        head_script = engine._head_revision(cur, slot_id, "script")
        present["governed_head"] = {"topic": head_topic, "script": head_script}
        if (head_topic != int(tuple_["topic_revision"])
                or head_script != int(tuple_["script_revision"])):
            deny(SIGNOFF_STALE,
                 "the current governed head no longer equals the revisions pinned by the immutable "
                 "package (a post-attachment rework advanced the head)")

        cur.execute("SELECT approver_id, decision::text AS decision, revision, decided_at "
                    "FROM gate_decision WHERE gate_id=%s AND slot_id=%s "
                    "ORDER BY decided_at, approver_id", (str(gate_id), slot_id))
        decisions = cur.fetchall()
        head = engine._gate_review_head(cur, cfg, FINAL_REVIEW_STAGE, slot_id)
        eff = engine._effective_decisions_for_head(decisions, head)
        proj = engine._authoritative_target_projection(cur, str(gate_id), snapshot, slot_id, eff)
        # ONLY the outcome is taken. Per-token coverage carries covering PRINCIPAL IDs and is
        # deliberately neither read into the response nor counted (Q2).
        present["outcome"] = proj["current_outcome"]
        if proj["current_outcome"] != "approved":
            deny(SIGNOFF_BLOCKED,
                 f"the present decision outcome is {proj['current_outcome']!r}, which is not an "
                 f"actionable approved state")
    else:
        # No governing snapshot: there is no authoritative present-state evidence to evaluate against.
        deny(SIGNOFF_TARGET_UNAVAILABLE,
             "no governing gate snapshot exists, so present-state eligibility has no authoritative "
             "evidence to be established from")
    evidence["present_state"] = present

    # ---- (7) Script-to-Production direction — READ-ONLY downstream evidence (Q8).
    # The PINNED package columns are the evidence; the live directive read is a COHERENCE CHECK ONLY.
    # No builder / emission / record path is imported or invoked, and a live row NEVER replaces,
    # refreshes, or promotes itself over a pinned value. Its presence is neither approval, sign-off,
    # lifecycle advancement, nor authorization to execute Production.
    pinned_dir = pkg_ev["production_direction"]
    cur.execute("SELECT directive_id::text AS directive_id, revision FROM directive "
                "WHERE slot_id=%s AND to_stage='production' AND type='production_directive' "
                "ORDER BY revision DESC, created_at DESC LIMIT 1", (slot_id,))
    live_dir = cur.fetchone()
    direction = {"pinned": pinned_dir,
                 "observed": ({"present": True, "directive_id": live_dir["directive_id"],
                               "revision": live_dir["revision"]} if live_dir else {"present": False})}
    if pinned_dir.get("present"):
        if live_dir is None:
            direction["status"] = "mismatch"
            deny(PRODUCTION_DIRECTION_MISMATCH,
                 "the package pins a production direction that is no longer observable in canonical "
                 "directive state")
        elif (live_dir["directive_id"] != pinned_dir.get("directive_id")
                or live_dir["revision"] != pinned_dir.get("revision")):
            direction["status"] = "mismatch"
            deny(PRODUCTION_DIRECTION_MISMATCH,
                 "the observed production direction disagrees with the direction pinned by the "
                 "immutable package (different directive id or revision)")
        else:
            direction["status"] = RECORDED
    elif live_dir is not None:
        # A live direction the immutable package never pinned. The pinned fields remain THE evidence,
        # so live state that the package does not account for is a disagreement, not an upgrade.
        # DELIBERATELY CONSERVATIVE: a direction legitimately emitted AFTER attachment also lands here.
        # That is the fail-closed reading of the reconciled ruling, and it is isolated to this branch
        # so a future directive can change it without touching the rest of the contract.
        direction["status"] = "mismatch"
        deny(PRODUCTION_DIRECTION_MISMATCH,
             "a production direction exists in canonical state that the immutable package does not "
             "pin; pinned evidence and observed state disagree")
    else:
        # Absence on BOTH sides is not a disagreement — #419's non-denial evidence status.
        direction["status"] = PRODUCTION_DIRECTION_NOT_YET_RECORDED
    evidence["production_direction"] = direction

    status = UNKNOWN_HISTORY if any(d["code"] in _HISTORICAL_CODES for d in denials) else RECORDED
    return _result(gate_id, slot_id, status, denials, identity=identity, package=package,
                   tuple_=tuple_, evidence=evidence)
