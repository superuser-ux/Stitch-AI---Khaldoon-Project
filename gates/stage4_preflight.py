"""#419 — Stage 4 approval-package preflight (read-only, server-authoritative).

Aggregates ONLY existing canonical records to answer one question for a canonical
candidate (a `slot_id`): is the canonical Schedule -> Topic -> Script lineage coherent
and eligible for human final review / production direction, or are there typed
server-authored reasons why not?

Hard contract (matches #419 + the Codex reconciliation):
  * READ-ONLY. Every statement is a pure SELECT. It never writes, and it never calls a
    directive builder / emission / record path (`script_to_production`, `emit_output`,
    `record`) — an existing production direction is OBSERVED via `directives.latest`.
  * Stable typed codes + structured evidence are authoritative. `detail` is display-only
    and must never be parsed by a client to reconstruct lineage/authority/readiness.
  * Consumed workflow-version identity and the currently-active workflow-version identity
    are DISTINCT facts. Both are returned where derivable; neither is ever substituted or
    rebound. Final-review metadata is read from the CANDIDATE'S CONSUMED version, never the
    active one.
  * FAIL CLOSED. Missing / mismatched / inactive / underivable evidence yields a stable
    denial code (`unknown_history` for missing consumed pins / underivable relations), never
    an eligible-by-implication result and never a synthesized/backfilled pin.
    (#419 amendment: a production direction ABSENT before human final review is the one
    non-denial `not_yet_recorded` status; a PERSISTED direction that is malformed or
    stale/mismatched still fails closed.)
  * Agent / AgentRep / provider / secret state is truthful classification only
    (`not_enabled` / `not_recorded` / `not_applicable`) and confers no authority.

No schema/migration is required: every field below is an existing committed column.
"""

# ---- stable, machine-branchable denial / status codes (authoritative) ---------------------------
COHERENT = "coherent"
SLOT_NOT_FOUND = "slot_not_found"
TOPIC_NOT_SELECTED = "topic_not_selected"
SCRIPT_NOT_SELECTED = "script_not_selected"
TOPIC_REVISION_MISSING = "topic_revision_missing"
SCRIPT_REVISION_MISSING = "script_revision_missing"
TOPIC_SCRIPT_MISMATCH = "topic_script_mismatch"
UNKNOWN_HISTORY = "unknown_history"                       # a required consumed pin / relation is not derivable
ACTIVE_WORKFLOW_UNAVAILABLE = "active_workflow_unavailable"
CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE = "consumed_active_workflow_divergence"
FINAL_REVIEW_UNKNOWN = "final_review_unknown"             # final-review metadata not derivable from the consumed version
# #419 amendment — production-direction absence BEFORE human final review is not a denial; it is a
# truthful read-only status. A PERSISTED direction that is malformed or stale/mismatched stays fail-closed.
PRODUCTION_DIRECTION_NOT_YET_RECORDED = "not_yet_recorded"   # non-blocking evidence status (never a denial)
PRODUCTION_DIRECTION_MALFORMED = "production_direction_malformed"   # payload fails the canonical package contract
PRODUCTION_DIRECTION_MISMATCH = "production_direction_mismatch"     # references a different script/slot/revision

# The canonical production-directive package contract, mirrored from gates/directives.py (PACKAGE_FIELDS
# + the ref() shape {"kind","ref":"<kind>:<id>", "revision"?}) so a PERSISTED payload can be validated
# structurally from its existing JSON alone — no builder/emission/record path is imported or invoked.
_PACKAGE_FIELDS = ("intent", "inputs", "parameters", "constraints", "acceptance_criteria", "context")


def _production_package_defect(payload, slot_id, script, row_revision):
    """Return None if the persisted directive is a well-formed production-directive package whose
    canonical-row `revision` AND payload script reference BOTH match the SELECTED canonical script
    (exact id + revision) and this slot; else a stable defect code (`production_direction_malformed`
    for a structural failure, `production_direction_mismatch` for a structurally-valid but
    stale/self-contradictory/wrong-target record). Pure JSON + column reads; no builder/emission/record.
    `row_revision` is the persisted `directive.revision` column — the revision the directive carries."""
    if not isinstance(payload, dict) or not payload:
        return PRODUCTION_DIRECTION_MALFORMED
    if (payload.get("type") != "production_directive" or payload.get("from_stage") != "script"
            or payload.get("to_stage") != "production"):
        return PRODUCTION_DIRECTION_MALFORMED
    if any(f not in payload for f in _PACKAGE_FIELDS):
        return PRODUCTION_DIRECTION_MALFORMED
    intent = payload.get("intent")
    if not (isinstance(intent, dict) and intent.get("ar") and intent.get("en")):
        return PRODUCTION_DIRECTION_MALFORMED
    inputs = payload.get("inputs")
    if not isinstance(inputs, list):
        return PRODUCTION_DIRECTION_MALFORMED
    # It must target the SELECTED canonical script (exact id + revision) AND this slot, and the
    # persisted row `revision` column must ALSO equal the selected script revision — a non-empty but
    # arbitrary/wrong-script package, OR a row whose column contradicts its own payload/selected script
    # (e.g. row revision 2 with a payload input revision 3), fails closed rather than passing as present.
    if script:
        if row_revision != script["revision"]:
            return PRODUCTION_DIRECTION_MISMATCH
        want_script = f"script:{script['script_id']}"
        want_slot = f"slot:{slot_id}"
        has_script = any(isinstance(i, dict) and i.get("ref") == want_script
                         and i.get("revision") == script["revision"] for i in inputs)
        has_slot = any(isinstance(i, dict) and i.get("ref") == want_slot for i in inputs)
        if not has_script or not has_slot:
            return PRODUCTION_DIRECTION_MISMATCH
    return None

# Truthful classifications for capability/authority fields that are recorded seams, not live grants.
NOT_APPLICABLE = "not_applicable"
NOT_RECORDED = "not_recorded"


def _fetchone(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()


def _selected_revision(cur, slot_id, artifact):
    """The server-approved revision for `artifact` ('topic'|'script') on this slot, or None.
    Selection is server-owned (slot_approval); client-supplied revisions are never authoritative."""
    row = _fetchone(cur, "SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact=%s",
                    (slot_id, artifact))
    return row["revision"] if row else None


def _active_workflow_version(cur, tenant_id="default", module="content"):
    """The currently-active workflow version (the mutable singleton), or None. This is a DISTINCT
    fact from any candidate's consumed version and is never substituted for it."""
    return _fetchone(cur,
                     "SELECT version_id::text AS version_id, version_no, status "
                     "FROM workflow_version WHERE status='active' AND tenant_id=%s AND module=%s",
                     (tenant_id, module))


def _final_review_stage(cur, version_id):
    """The final_review stage row for a SPECIFIC workflow version (the consumed one), or None.
    Reading by version_id is what keeps candidate final-review metadata off the active generation."""
    return _fetchone(cur,
                     "SELECT stage_key, enabled, mandatory, bypassable, stage_kind, generator_kind, "
                     "writer_mode, approval_rule, enforce_mandatory_reviews, approve_to "
                     "FROM workflow_stage WHERE version_id=%s AND stage_key='final_review'",
                     (version_id,))


def preflight(cur, slot_id):
    """Return the typed Stage 4 package-preflight read model for one canonical `slot_id`.

    `cur` must be a RealDictCursor. Returns a dict; `available` is True only for a fully coherent,
    eligible package. `denials` lists every failing check with a stable code. Never raises for a
    normal not-eligible outcome — it fails closed into typed data."""
    denials = []

    def deny(code, detail):
        denials.append({"code": code, "detail": detail})

    evidence = {
        "schedule": None, "topic": None, "script": None,
        "workflow": {"consumed": None, "active": None, "divergent": None},
        "consumed_versions": None,
        "final_review": None,
        "production_direction": None,
        # recorded seams only — never a live grant; reported truthfully.
        "classifications": {
            "agent_execution": NOT_APPLICABLE,
            "agent_rep_delegation": NOT_RECORDED,
            "provider_operation": NOT_APPLICABLE,
            "secret_authority": NOT_APPLICABLE,
        },
    }

    # (1) Schedule / slot identity + lifecycle state.
    slot = _fetchone(cur, "SELECT slot_id, round_id, status, script_ref FROM slot WHERE slot_id=%s",
                     (slot_id,))
    if not slot:
        return {"candidate": {"slot_id": slot_id}, "available": False,
                "reason_code": SLOT_NOT_FOUND,
                "detail": "no canonical schedule slot resolves this candidate identity",
                "evidence": evidence, "denials": [{"code": SLOT_NOT_FOUND, "detail": "slot absent"}]}
    evidence["schedule"] = {"slot_id": slot["slot_id"], "round_id": slot["round_id"],
                            "status": slot["status"]}

    # (2) Selected Topic identity + immutable revision (server-owned selection).
    topic = None
    topic_rev = _selected_revision(cur, slot_id, "topic")
    if topic_rev is None:
        deny(TOPIC_NOT_SELECTED, "no server-approved topic revision on this slot")
    else:
        topic = _fetchone(cur, "SELECT topic_id::text AS topic_id, revision FROM topic "
                               "WHERE slot_id=%s AND revision=%s", (slot_id, topic_rev))
        if not topic:
            deny(TOPIC_REVISION_MISSING,
                 f"approved topic revision {topic_rev} has no canonical topic row")
        else:
            evidence["topic"] = {"topic_id": topic["topic_id"], "revision": topic["revision"]}

    # (3) Selected Script identity + immutable revision (server-owned selection).
    script = None
    script_rev = _selected_revision(cur, slot_id, "script")
    if script_rev is None:
        deny(SCRIPT_NOT_SELECTED, "no server-approved script revision on this slot")
    else:
        script = _fetchone(cur, "SELECT script_id::text AS script_id, revision FROM script "
                                "WHERE slot_id=%s AND revision=%s", (slot_id, script_rev))
        if not script:
            deny(SCRIPT_REVISION_MISSING,
                 f"approved script revision {script_rev} has no canonical script row")
        else:
            evidence["script"] = {"script_id": script["script_id"], "revision": script["revision"]}

    # (4) Consumed generation pins for the selected script (immutable, pinned at generation).
    prov = None
    if script:
        prov = _fetchone(cur,
                         "SELECT workflow_version_id::text AS workflow_version_id, topic_id::text AS topic_id, "
                         "topic_revision, methodology_version, content_format_version, "
                         "framework_version, writer_contract_version "
                         "FROM script_provenance WHERE script_id=%s AND revision=%s",
                         (script["script_id"], script["revision"]))
        if prov:
            evidence["consumed_versions"] = {
                # methodology/content_format have governed version tables; framework/writer-contract are
                # free-text pins with no governing table. A NULL cell is unknown, never synthesized.
                "methodology_version": prov["methodology_version"],
                "content_format_version": prov["content_format_version"],
                "framework_version": prov["framework_version"],
                "writer_contract_version": prov["writer_contract_version"],
            }

    # (4b) Topic <-> Script coherence, proved from the script's pinned consumed input (not slot adjacency).
    if topic and script:
        if not prov:
            deny(UNKNOWN_HISTORY,
                 "selected script has no pinned provenance (pre-#357); topic<->script relation is not derivable")
        elif prov["topic_id"] != topic["topic_id"] or prov["topic_revision"] != topic["revision"]:
            deny(TOPIC_SCRIPT_MISMATCH,
                 "selected script was generated from a different topic revision than the selected topic")

    # (5) CONSUMED workflow version — script grain first, then round-plan snapshot; else unknown.
    consumed_version_id = None
    consumed_source = None
    if prov and prov["workflow_version_id"]:
        consumed_version_id = prov["workflow_version_id"]
        consumed_source = "script_provenance"
    else:
        snap = _fetchone(cur, "SELECT workflow_version FROM round_policy_snapshot WHERE round_id=%s",
                         (slot["round_id"],))
        if snap and snap["workflow_version"]:
            consumed_version_id = snap["workflow_version"]
            consumed_source = "round_policy_snapshot"
    if consumed_version_id:
        evidence["workflow"]["consumed"] = {"version_id": consumed_version_id, "source": consumed_source}
    else:
        evidence["workflow"]["consumed"] = {"status": "unknown"}
        deny(UNKNOWN_HISTORY, "consumed workflow version is not pinned on any existing record")

    # (6) ACTIVE workflow version — a distinct fact; missing is a typed unavailable.
    active = _active_workflow_version(cur)
    if active:
        evidence["workflow"]["active"] = {"version_id": active["version_id"],
                                          "version_no": active["version_no"], "status": active["status"]}
    else:
        evidence["workflow"]["active"] = {"status": "unavailable"}
        deny(ACTIVE_WORKFLOW_UNAVAILABLE, "no active workflow version exists for this tenant/module")

    # (7) Consumed-vs-active divergence — never eligible by implication (Codex reconciliation #4).
    if consumed_version_id and active:
        divergent = consumed_version_id != active["version_id"]
        evidence["workflow"]["divergent"] = divergent
        if divergent:
            deny(CONSUMED_ACTIVE_WORKFLOW_DIVERGENCE,
                 "candidate consumed a workflow version that is no longer the active generation; "
                 "requires reconsideration under the then-current process (no silent rebinding)")

    # (8) Final-review requirement — read from the CONSUMED version only.
    if consumed_version_id:
        fr = _final_review_stage(cur, consumed_version_id)
        if not fr or not fr["enabled"]:
            evidence["final_review"] = {"status": "unknown"}
            deny(FINAL_REVIEW_UNKNOWN,
                 "final_review stage metadata is not derivable/enabled for the consumed workflow version")
        else:
            # Human-required is structural: a review gate with no AI generator whose mandatory reviews
            # are enforced. Reported truthfully; the client must not reconstruct this from prose.
            human_required = (fr["generator_kind"] is None
                              and (bool(fr["enforce_mandatory_reviews"]) or bool(fr["mandatory"])))
            evidence["final_review"] = {
                "required": True,
                "human_required": human_required,
                "source_version_id": consumed_version_id,
                "approval_rule": fr["approval_rule"],
                "enforce_mandatory_reviews": bool(fr["enforce_mandatory_reviews"]),
                "mandatory": bool(fr["mandatory"]),
                "approve_to": fr["approve_to"],
            }
            if not human_required:
                deny(FINAL_REVIEW_UNKNOWN,
                     "consumed final_review stage does not require human sign-off; cannot assert human-required truth")
    else:
        evidence["final_review"] = {"status": "unknown"}
        # already denied UNKNOWN_HISTORY for the consumed version; final-review is consequently underivable.

    # (9) Production direction — OBSERVE ONLY (pure directive read; never generate/emit/refresh/record).
    # #419 amendment: ABSENCE before human final review is read-only `not_yet_recorded` evidence and does
    # NOT deny an otherwise-coherent package. A PERSISTED direction that is malformed (payload is not a
    # populated package) or stale/mismatched (its revision != the selected script revision) stays
    # typed FAIL-CLOSED.
    direction = _fetchone(cur,
                          "SELECT directive_id::text AS directive_id, revision, payload FROM directive "
                          "WHERE slot_id=%s AND to_stage='production' AND type='production_directive' "
                          "ORDER BY revision DESC, created_at DESC LIMIT 1", (slot_id,))
    if not direction:
        evidence["production_direction"] = {"present": False,
                                            "status": PRODUCTION_DIRECTION_NOT_YET_RECORDED}
    else:
        defect = _production_package_defect(direction["payload"], slot_id, script, direction["revision"])
        if defect == PRODUCTION_DIRECTION_MALFORMED:
            evidence["production_direction"] = {"present": True, "status": "malformed",
                                                "directive_id": direction["directive_id"]}
            deny(PRODUCTION_DIRECTION_MALFORMED,
                 "persisted production direction payload is malformed (fails the canonical package contract)")
        elif defect == PRODUCTION_DIRECTION_MISMATCH:
            evidence["production_direction"] = {"present": True, "status": "mismatch",
                                                "directive_id": direction["directive_id"],
                                                "revision": direction["revision"],
                                                "expected_revision": script["revision"] if script else None}
            deny(PRODUCTION_DIRECTION_MISMATCH,
                 "persisted production direction references a different script / revision / slot than the "
                 "selected canonical package")
        else:
            evidence["production_direction"] = {"present": True, "directive_id": direction["directive_id"],
                                                "revision": direction["revision"]}

    available = not denials
    reason_code = COHERENT if available else denials[0]["code"]
    detail = ("canonical Schedule -> Topic -> Script lineage is coherent and eligible for human "
              "final review" if available else denials[0]["detail"])
    return {"candidate": {"slot_id": slot_id}, "available": available, "reason_code": reason_code,
            "detail": detail, "evidence": evidence, "denials": denials}
