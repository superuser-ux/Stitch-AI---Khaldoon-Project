"""Gate engine (M4) — the single source of truth for the approval workflow.

Every surface (CLI, the FastAPI used by the Next.js dashboard, the Telegram bot)
calls THESE functions, so the transition logic + audit live in exactly one place
(Phase1_Build_Spec §5). All behavior — who may approve, the quorum policy, whether
partial-batch is allowed — comes from `system_config.yaml` (`gates.<stage>`), never
hardcoded.

Model
-----
- A **batch gate** opens over the slots of a round that have reached `DRAFT_ASSIGNED`.
- Approvers record per-slot decisions (`approve` / `reject` / `request_change`); a
  *batch* action just fans the same decision over every still-pending target slot.
- `resolve` tallies each slot against the quorum and moves it:
    approved            -> slot.status APPROVED_ASSIGNED
    reject / change     -> stays DRAFT_ASSIGNED, looped back (recorded for the agent)
- Every transition is written to `audit_log` with actor + timestamp.
"""

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import yaml
from psycopg2.extras import Json

import directives  # M9·B1 — emit the inter-stage directive package at each gate handoff
import dam          # M9·B2 — DAM assets attached to the review surface for manual stages
import actors       # M9·B3 — Unified Actor Model: autonomy × stage-policy × permissions
import jobs         # #265 — in-process generation-job registry (in-flight work = generation pending)

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "system_config.yaml"

DECISIONS = ("approve", "reject", "request_change")

WORKFLOW_KEY = "content_pipeline"
WORKFLOW_STAGE_LIBRARY = [
    ("schedule_review", {"label": "Schedule", "group": "Content"}),
    ("topic_review", {"label": "Topics", "group": "Content"}),
    ("script_review", {"label": "Scripts", "group": "Content"}),
    ("native_review", {"label": "Language sign-off", "group": "Sign-off"}),
    ("scholar_review", {"label": "Religious sign-off", "group": "Sign-off"}),
    ("final_review", {"label": "Publish approval", "group": "Sign-off"}),
    ("production_review", {"label": "Production", "group": "Production"}),
    ("edit_review", {"label": "Media edit", "group": "Production"}),
    ("distribution_review", {"label": "Distribution", "group": "Production"}),
]
WORKFLOW_STAGE_META = {key: meta for key, meta in WORKFLOW_STAGE_LIBRARY}
DEFAULT_WORKFLOW_TRANSITIONS = [
    ("schedule_review", "topic_review", "approve"),
    ("topic_review", "script_review", "approve"),
    ("script_review", "native_review", "needs_native_review"),
    ("script_review", "scholar_review", "needs_scholar_review"),
    ("script_review", "final_review", "ready_for_final"),
    ("native_review", "final_review", "signed_off"),
    ("scholar_review", "final_review", "signed_off"),
    ("final_review", "production_review", "approve"),
    ("production_review", "edit_review", "approve"),
    ("edit_review", "distribution_review", "approve"),
]


class GateError(RuntimeError):
    pass


class ScheduleConflict(GateError):
    """#292 — a STALE combined schedule token. Typed so the API can answer 409 (not 400/500) and
    carry enough current-state evidence for the caller to refresh. It never silently overwrites or
    approximates: the loser of a race is told exactly what it raced against."""

    def __init__(self, message, current):
        super().__init__(message)
        self.current = current


class GateNotReady(GateError):
    """#265 — a review action was refused because generator work for the stage's round is still
    pending (queued / claimed / in-flight / retryable / job-poll fallback). Fail-closed by design:
    no gate is exposed, decided, or committed against a knowably-partial target population."""
    pass


class TargetPackageNotReady(GateNotReady):
    """#423 — a final-review target's immutable Stage-4 package snapshot could not be pinned from
    canonical records at attachment (missing/underivable Topic/Script lineage or consumed workflow
    provenance). This is an ATTACHMENT-READINESS refusal (fail-closed, a GateNotReady) — NEVER an
    authorization denial, and it never re-evaluates membership/policy or alters frozen token coverage,
    ANY/ALL semantics, or who is authorized to act. The whole attachment batch rolls back with zero
    target/snapshot/audit residue; `decide`/`resolve`/reads stop before their writes."""

    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = sorted(candidates)


class RevisionConflict(GateError):
    """#313 — a per-item Topic mutation supplied an `expected_revision` that no longer matches the
    current head (a concurrent edit/rework/restore won the race). Typed so the API answers 409 and
    carries the current head; the loser refreshes, never silently overwrites (mirrors ScheduleConflict
    for the Topic revision axis)."""

    def __init__(self, message, current):
        super().__init__(message)
        self.current = current


class GovernedDenial(GateError):
    """#313 — a governed refusal of a per-item Topic action that is NOT a race: the actor lacks the
    authority the action needs, or the item is past the point where this action is permitted (approved
    or downstream-advanced) and reopening it would require governed reconsideration (#249), which is not
    implemented. Typed so the API answers a governed denial (409/403) with a machine reason and leaves
    #249 unconsumed — never an invented informal reconsideration."""

    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


class SignoffError(GateError):
    """#439 — a typed refusal of a final-review SIGN-OFF command, carrying the EXACT public error
    code + HTTP status the thin API handler returns as `{"error": code}`. Every mapped failure the
    sign-off contract enumerates (authorization, present-state, staleness, idempotency, one-time
    uniqueness, unclassified race) is one of these; the handler never invents a status. Codes and
    statuses are the single source of truth in SIGNOFF_ERROR_STATUS below. `signoff_unauthenticated`
    (401) and `invalid_request` (422) are raised at the handler boundary (trusted-principal seam /
    request parsing), not the engine, but are listed there for one complete, verifiable mapping."""

    def __init__(self, code, http_status):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


# #439 — the ONE canonical final-review sign-off error code -> HTTP status map. The handler and the
# focused contract test both bind to this so the wire contract can never silently drift.
SIGNOFF_ERROR_STATUS = {
    "signoff_unauthenticated": 401,   # handler: missing/invalid trusted principal
    "signoff_not_authorized": 403,    # engine: governed-assignment / action-policy authorization failure
    "signoff_hard_floor": 403,        # engine: actor-model hard-floor failure
    "signoff_target_unavailable": 404,  # engine: missing gate / slot / immutable package
    "signoff_package_mismatch": 404,  # engine: submitted binding tuple != stored package
    "signoff_blocked": 409,           # engine: rejected / request-change / parked / unavailable-or-ambiguous present state
    "signoff_stale": 409,             # engine: stale governed head or stale package revision
    "signoff_already_recorded": 409,  # engine: a different key for an already-recorded exact tuple
    "idempotency_key_mismatch": 409,  # engine: same key, different request digest
    "signoff_conflict": 409,          # engine: unclassified serialization / uniqueness race
    "invalid_request": 422,           # handler: malformed / unknown-field / invalid-type / out-of-bounds request
}


# --------------------------------------------------------------------------- #
# Connection + config
# --------------------------------------------------------------------------- #
def db_connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "tanaghom"),
        user=os.environ.get("DB_USER", "tanaghom"),
        password=os.environ["DB_PASSWORD"])


def load_config(path=None):
    return yaml.safe_load(Path(path or os.environ.get("TANAGHOM_CONFIG", DEFAULT_CONFIG))
                          .read_text(encoding="utf-8"))


def stage_cfg(cfg, stage):
    g = (cfg.get("gates") or {}).get(stage)
    if not g:
        raise GateError(f"no gate config for stage {stage!r} (system_config.yaml gates.{stage})")
    return g


def changes_statuses(cfg):
    """The set of 'awaiting rework' statuses configured across gates (gate.changes_to)."""
    return {gc.get("changes_to") for gc in (cfg.get("gates") or {}).values() if gc.get("changes_to")}


def reject_statuses(cfg):
    """The set of reversible 'dropped' statuses (gate.reject_to). Recoverable via reopen."""
    return {gc.get("reject_to") for gc in (cfg.get("gates") or {}).values() if gc.get("reject_to")}


def parked_statuses(cfg):
    """Statuses excluded from the ACTIVE review + NOT approvable — awaiting-rework OR dropped.
    Both are recoverable (regenerate / reopen); neither is destroyed."""
    return {s for s in (changes_statuses(cfg) | reject_statuses(cfg)) if s}


def resolve_quorum(quorum, approvers):
    """Map the config quorum ('any' | 'all' | N) to the integer number of distinct
    approvals a slot needs."""
    if isinstance(quorum, int):
        return max(1, quorum)
    q = str(quorum).strip().lower()
    if q in ("any", "or"):
        return 1
    if q in ("all", "and"):
        return max(1, len(approvers or []))
    try:
        return max(1, int(q))
    except ValueError:
        raise GateError(f"bad quorum {quorum!r} (expected 'any' | 'all' | 'or' | 'and' | integer)")


def _normalize_rule_key(rule):
    q = str(rule or "any").strip().lower()
    if q == "or":
        return "any"
    if q == "and":
        return "all"
    return q or "any"


def _normalize_assignment_token(token, default_kind="user"):
    raw = token
    if isinstance(token, dict):
        kind = str(token.get("kind") or token.get("type") or default_kind).strip().lower()
        key = str(token.get("key") or token.get("id") or token.get("principal_id") or "").strip()
    else:
        raw = str(token or "").strip()
        if not raw:
            return None
        if ":" in raw:
            kind, key = raw.split(":", 1)
            kind, key = kind.strip().lower(), key.strip()
        else:
            kind, key = default_kind, raw
    if kind == "principal":
        kind = "user"
    if kind not in ("user", "role", "group"):
        raise GateError(f"unsupported approval assignment kind {kind!r}")
    if not key:
        return None
    return f"{kind}:{key}"


def _dedupe_keep_order(items):
    out, seen = [], set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def approval_assignments(gc):
    """Normalized assignment tokens for a gate config.

    Supports both the legacy `approvers` list and the richer CR01 shape:
      approval:
        rule: all|any|and|or|N
        users: [...]
        roles: [...]
        groups: [...]
        assignments: ["user:khal", "role:legal"]
    """
    approval = gc.get("approval") or {}
    tokens = []
    if isinstance(approval, dict):
        for item in approval.get("assignments") or []:
            tokens.append(_normalize_assignment_token(item))
        if not tokens:
            tokens.extend(_normalize_assignment_token(item, default_kind="user")
                          for item in (approval.get("users") or []))
            tokens.extend(_normalize_assignment_token(item, default_kind="role")
                          for item in (approval.get("roles") or []))
            tokens.extend(_normalize_assignment_token(item, default_kind="group")
                          for item in (approval.get("groups") or []))
    if not any(tokens):
        tokens = [_normalize_assignment_token(item) for item in (gc.get("approvers") or [])]
    return _dedupe_keep_order(tokens)


def approval_contract(gc):
    assignments = approval_assignments(gc)
    approval = gc.get("approval") or {}
    raw_rule = approval.get("rule") if isinstance(approval, dict) and approval.get("rule") is not None else gc.get("quorum", "any")
    rule_key = _normalize_rule_key(raw_rule)
    return {"rule_key": rule_key, "assignments": assignments, "quorum_n": resolve_quorum(rule_key, assignments)}


def _contract_from_tokens(rule_key, assignments):
    normalized = _dedupe_keep_order(_normalize_assignment_token(item) for item in assignments)
    norm_rule = _normalize_rule_key(rule_key)
    return {
        "rule_key": norm_rule,
        "assignments": normalized,
        "quorum_n": resolve_quorum(norm_rule, normalized),
    }


def _contract_from_snapshots(rule_key, assignments):
    return _contract_from_tokens(
        rule_key,
        [_token_from_assignment(a["assignment_kind"], a["assignment_key"]) for a in assignments],
    )


def _yaml_stage_approval_contract(cfg, stage):
    gc = stage_cfg(cfg, stage)
    contract = approval_contract(gc)
    approval = gc.get("approval") or {}
    users = []
    roles = []
    groups = []
    if isinstance(approval, dict):
        users = _dedupe_keep_order(str(x).strip() for x in (approval.get("users") or []))
        roles = _dedupe_keep_order(str(x).strip() for x in (approval.get("roles") or []))
        groups = _dedupe_keep_order(str(x).strip() for x in (approval.get("groups") or []))
    if not any((users, roles, groups)):
        for token in contract["assignments"]:
            snap = _assignment_snapshot(token)
            if snap["assignment_kind"] == "user":
                users.append(snap["assignment_key"])
            elif snap["assignment_kind"] == "role":
                roles.append(snap["assignment_key"])
            elif snap["assignment_kind"] == "group":
                groups.append(snap["assignment_key"])
    return {
        "rule_key": contract["rule_key"],
        "quorum": contract["quorum_n"],
        "assignments": [_assignment_snapshot(a) for a in contract["assignments"]],
        "users": users,
        "roles": roles,
        "groups": groups,
        "source": "yaml",
    }


def _db_stage_approval_contract(cur, stage):
    cur.execute("""SELECT p.policy_id, p.rule_key, a.assignment_kind, a.assignment_key
                   FROM approval_policy p
                   LEFT JOIN approval_policy_assignment a ON a.policy_id=p.policy_id
                   WHERE p.stage=%s AND p.tenant_id='default' AND p.module='content'
                   ORDER BY a.assignment_kind, a.assignment_key""", (stage,))
    rows = cur.fetchall()
    if not rows:
        return None
    snapshots = []
    for row in rows:
        if row["assignment_kind"] and row["assignment_key"]:
            snapshots.append({
                "assignment_kind": row["assignment_kind"],
                "assignment_key": row["assignment_key"],
                "resolved_principal_id": row["assignment_key"] if row["assignment_kind"] == "user" else None,
            })
    if not snapshots:
        raise GateError(f"approval override for {stage!r} has no assignments")
    contract = _contract_from_snapshots(rows[0]["rule_key"], snapshots)
    users = [a["assignment_key"] for a in snapshots if a["assignment_kind"] == "user"]
    roles = [a["assignment_key"] for a in snapshots if a["assignment_kind"] == "role"]
    groups = [a["assignment_key"] for a in snapshots if a["assignment_kind"] == "group"]
    return {
        "rule_key": contract["rule_key"],
        "quorum": contract["quorum_n"],
        "assignments": snapshots,
        "users": users,
        "roles": roles,
        "groups": groups,
        "source": "db",
    }


def stage_approval_contract(cfg, stage, conn=None):
    if conn is not None:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            override = _db_stage_approval_contract(cur, stage)
        finally:
            cur.close()
        if override:
            return override
    return _yaml_stage_approval_contract(cfg, stage)


def _assignment_snapshot(token):
    raw = str(token or "").strip()
    if raw.startswith("user:"):
        key = raw.split(":", 1)[1]
        return {"assignment_kind": "user", "assignment_key": key, "resolved_principal_id": key}
    if raw.startswith("role:"):
        return {"assignment_kind": "role", "assignment_key": raw.split(":", 1)[1],
                "resolved_principal_id": None}
    if raw.startswith("group:"):
        return {"assignment_kind": "group", "assignment_key": raw.split(":", 1)[1],
                "resolved_principal_id": None}
    return {"assignment_kind": "user", "assignment_key": raw, "resolved_principal_id": raw}


def _principal_matches_assignment(cur, principal_id, token):
    snap = _assignment_snapshot(token)
    kind, key = snap["assignment_kind"], snap["assignment_key"]
    if kind == "user":
        return principal_id == key
    if kind == "role":
        cur.execute("""SELECT 1 FROM principal_role_member
                       WHERE principal_id=%s AND role_id=%s AND active=true""", (principal_id, key))
        return cur.fetchone() is not None
    if kind == "group":
        cur.execute("""SELECT 1 FROM principal_group_member
                       WHERE principal_id=%s AND group_id=%s AND active=true""", (principal_id, key))
        return cur.fetchone() is not None
    return False


def _token_from_assignment(kind, key):
    return f"{kind}:{key}"


def _gate_assignment_tokens(cur, gate_id):
    cur.execute("""SELECT assignment_kind, assignment_key
                   FROM gate_assignment WHERE gate_id=%s
                   ORDER BY assignment_kind, assignment_key""", (gate_id,))
    return [_token_from_assignment(r["assignment_kind"], r["assignment_key"]) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# #321 R4 — canonical authority for ordinary per-item Topic MUTATIONS (edit / restore / rework).
#
# decide/drop/approve/request_change already enforce the stage-assignment authority + actor hard floor
# for an item at its review stage. edit/restore/rework are mutations of the SAME in-review item at the
# SAME stage, so they bind to the SAME existing authority — closing missing enforcement, NOT creating a
# new permission or product role. Authentication (a signed principal) alone is insufficient. This never
# inherits `workflow.admin` (that stays exclusive to #319 terminalization) and invents no permission.
# Missing / ambiguous assignment fails CLOSED with a typed denial.
# --------------------------------------------------------------------------- #
def _resolve_review_stage(cfg, artifact):
    """The governed review stage that owns per-item mutations of `artifact` — the gate whose
    `rework_mode == artifact`. This is the SAME stage whose approval contract authorizes
    decide/drop/approve/request_change for the item, so all per-item commands share one authority."""
    for name, gc in (cfg.get("gates") or {}).items():
        if gc.get("rework_mode") == artifact:
            return name
    return None


def _authorize_topic_item_mutation(cur, slot_id, artifact, actor, cfg):
    """#321 R4 — enforce the EXISTING stage-assignment authority (+ actor-model hard floor) for an
    ordinary per-item Topic mutation. Raises a typed GovernedDenial and returns nothing on success.

    Authority source, in order (parity with decide's frozen-then-configured resolution):
      1. the FROZEN assignment of the slot's OPEN gate at this stage, if one exists;
      2. else the governed CONFIGURED stage approval contract (`stage_approval_contract`).
    Unlike decide, a MISSING/AMBIGUOUS assignment (no resolvable stage, no assignment tokens, or an
    empty frozen token set) fails CLOSED — never open — per the #321 ruling. Never `workflow.admin`."""
    stage = _resolve_review_stage(cfg, artifact)
    if not stage:
        raise GovernedDenial(
            f"no governed review stage for artifact {artifact!r} — mutation refused (fail closed)",
            reason="no_authority")
    # actor-model hard floor: a non-human may not act on a hard-floor stage (same rule as decide).
    if actors.enabled(cfg):
        ok, why = actors.authorize_gate_decision(cfg, actors.load_principal(cur, actor), stage)
        if not ok:
            raise GovernedDenial(why, reason="hard_floor")
    cur.execute("""SELECT g.gate_id FROM gate g JOIN gate_target t USING (gate_id)
                    WHERE t.slot_id=%s AND g.stage=%s AND g.status='open'
                    ORDER BY g.created_at DESC LIMIT 1""", (slot_id, stage))
    row = cur.fetchone()
    tokens = None
    if row:
        snapshot = _load_gate_snapshot(cur, row["gate_id"])
        if snapshot is not None:
            # A frozen authoritative gate: authorized iff the actor is in the frozen eligible set. An
            # EMPTY required-token set is ambiguous for a mutation -> fail closed (stricter than decide).
            eligible = (set().union(*(t["eligible"] for t in snapshot["tokens"]))
                        if snapshot["tokens"] else set())
            if not snapshot["tokens"]:
                raise GovernedDenial(
                    f"no governed assignment on the open {stage} gate for {slot_id} — mutation refused",
                    reason="no_authority")
            if actor in eligible:
                return
            raise GovernedDenial(
                f"{actor!r} is not assigned to {stage} for {slot_id}", reason="not_authorized")
        tokens = _gate_assignment_tokens(cur, row["gate_id"])
    if not tokens:
        contract = stage_approval_contract(cfg, stage, conn=cur.connection)
        tokens = [_token_from_assignment(a["assignment_kind"], a["assignment_key"])
                  for a in contract["assignments"]]
    if not tokens:
        raise GovernedDenial(
            f"no governed assignment for {stage} — mutation refused (fail closed)", reason="no_authority")
    if any(_principal_matches_assignment(cur, actor, tok) for tok in tokens):
        return
    raise GovernedDenial(f"{actor!r} is not assigned to {stage} for {slot_id}", reason="not_authorized")


# ------------------------------------------------------------------------- #
# #282 (#9 · #197 D1/D3/D6) — authoritative principal-neutral per-token coverage.
# A gate opened after migration 025 carries a FROZEN snapshot (required tokens + the eligible
# effective principals per token, resolved once at open — D3). ANY/ALL both resolve from durable
# per-slot, per-token coverage records (a maximum bipartite matching of approving principals to
# tokens — D1: every ALL token covered by a DISTINCT effective principal). Gates with no snapshot
# (pre-migration) are LEGACY by absence and keep the count-based path unchanged; nothing is inferred
# or backfilled for them.
# ------------------------------------------------------------------------- #
def _resolve_token_eligible(cur, kind, key):
    """The eligible effective principals for ONE assignment token, resolved at gate-open time (this
    result is what gets FROZEN into the snapshot). user -> itself; role/group -> active members."""
    if kind == "user":
        return [key]
    if kind == "role":
        cur.execute("SELECT principal_id FROM principal_role_member WHERE role_id=%s AND active=true", (key,))
    elif kind == "group":
        cur.execute("SELECT principal_id FROM principal_group_member WHERE group_id=%s AND active=true", (key,))
    else:
        return []
    return [r["principal_id"] for r in cur.fetchall()]


def _freeze_gate_snapshot(cur, gate_id, rule_key, tokens):
    """#282 (D3) — freeze the authoritative snapshot at gate-open: the normalized required tokens
    (duplicates/equivalents collapse to one) plus the eligible effective principals for each, so a
    later membership change never re-evaluates this gate. Idempotent: never re-freezes a gate that
    already has a snapshot (the open-reuse path keeps the original freeze)."""
    norm_rule = _normalize_rule_key(rule_key)
    if norm_rule not in ("any", "all"):
        norm_rule = "any"
    cur.execute("SELECT snapshot_id FROM gate_snapshot WHERE gate_id=%s", (gate_id,))
    if cur.fetchone():
        return None
    cur.execute("INSERT INTO gate_snapshot (gate_id, rule_key, authoritative) VALUES (%s,%s,true) "
                "RETURNING snapshot_id", (gate_id, norm_rule))
    snapshot_id = cur.fetchone()["snapshot_id"]
    seen = set()
    for token in tokens:
        snap = _assignment_snapshot(token)
        kind, key = snap["assignment_kind"], snap["assignment_key"]
        normalized = _token_from_assignment(kind, key)
        if normalized in seen:
            continue                                   # duplicate/equivalent token => one requirement
        seen.add(normalized)
        cur.execute("INSERT INTO gate_snapshot_token (snapshot_id, token_kind, token_key, normalized_token) "
                    "VALUES (%s,%s,%s,%s) RETURNING snapshot_token_id",
                    (snapshot_id, kind, key, normalized))
        st_id = cur.fetchone()["snapshot_token_id"]
        for pid in dict.fromkeys(_resolve_token_eligible(cur, kind, key)):
            cur.execute("SELECT 1 FROM principal WHERE principal_id=%s", (pid,))
            if cur.fetchone():                         # only freeze principals that exist (FK-safe)
                cur.execute("INSERT INTO gate_snapshot_eligible (snapshot_token_id, principal_id) "
                            "VALUES (%s,%s) ON CONFLICT DO NOTHING", (st_id, pid))
    return snapshot_id


def _load_gate_snapshot(cur, gate_id):
    """Load a gate's authoritative snapshot (frozen tokens + eligible principals), or None when the
    gate is LEGACY (no authoritative snapshot). Never re-resolves membership — reads only frozen rows."""
    cur.execute("SELECT snapshot_id, rule_key, authoritative FROM gate_snapshot WHERE gate_id=%s", (gate_id,))
    row = cur.fetchone()
    if not row or not row["authoritative"]:
        return None
    snapshot_id = row["snapshot_id"]
    cur.execute("SELECT snapshot_token_id, token_kind, token_key, normalized_token "
                "FROM gate_snapshot_token WHERE snapshot_id=%s ORDER BY normalized_token", (snapshot_id,))
    tokens = []
    for t in cur.fetchall():
        cur.execute("SELECT principal_id FROM gate_snapshot_eligible WHERE snapshot_token_id=%s",
                    (t["snapshot_token_id"],))
        tokens.append({"snapshot_token_id": t["snapshot_token_id"], "kind": t["token_kind"],
                       "key": t["token_key"], "normalized": t["normalized_token"],
                       "eligible": {r["principal_id"] for r in cur.fetchall()}})
    return {"snapshot_id": snapshot_id, "rule_key": _normalize_rule_key(row["rule_key"]), "tokens": tokens}


def _match_tokens(tokens, approvers):
    """Maximum bipartite matching between required tokens and approving principals — edge iff the
    principal is FROZEN-eligible for the token. Returns {snapshot_token_id: principal_id}. Kuhn's
    augmenting-path algorithm: correct where greedy assignment is not (e.g. P eligible for {T1,T2},
    Q eligible for {T1} must resolve to P->T2, Q->T1). Deterministic given stable input order."""
    match = {}                                          # token_id -> principal_id

    def augment(pid, visited):
        for tok in tokens:
            tid = tok["snapshot_token_id"]
            if pid in tok["eligible"] and tid not in visited:
                visited.add(tid)
                if tid not in match or augment(match[tid], visited):
                    match[tid] = pid
                    return True
        return False

    for pid in approvers:
        augment(pid, set())
    return match


def _gate_review_head(cur, cfg, stage, slot_id):
    """#321 P1.4 — the CURRENT head revision an ARTIFACT-review gate reviews for `slot_id`, or None for
    a non-artifact gate (signoff / schedule_review, no rework_mode) whose approvals are
    revision-independent. Used to make coverage/rollups exact-current-revision aware everywhere."""
    artifact = stage_cfg(cfg, stage).get("rework_mode")
    if not artifact:
        return None
    return _head_revision(cur, slot_id, artifact)


def _effective_decisions_for_head(decisions, head_revision):
    """#321 P1.2/P1.4 — the decisions as they count toward APPROVAL quorum/coverage on the EXACT
    current head. An approve for a SUPERSEDED revision (revision set and != head) is dropped from the
    approval tally — its gate_decision row and audit are PRESERVED elsewhere, never deleted. NULL
    revision means "the head" (legacy/low-level). reject/request_change are revision-INDEPENDENT and
    kept as-is. head_revision None (non-artifact gate) => no filtering."""
    if head_revision is None:
        return decisions
    return [d for d in decisions
            if not (d["decision"] == "approve" and d.get("revision") is not None
                    and int(d["revision"]) != int(head_revision))]


def _recompute_slot_coverage(cur, gate_id, slot_id, snapshot, head_revision=None):
    """Recompute + persist the authoritative per-token coverage for ONE slot from its CURRENT approve
    decisions and the frozen eligibility. Serialized per (gate, slot) so concurrent decisions cannot
    double-cover a token; delete-and-insert so coverage always equals the current maximum matching
    (the D1 distinctness invariants are the table's UNIQUE constraints). Returns the matching.
    #321 P1.4 — for an artifact-review gate, `head_revision` restricts coverage to approvals on the
    EXACT current head (NULL revision = head), so persisted coverage — and every read model that
    projects from it — can never present a superseded-revision approval as current coverage."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                ("coverage", f"{gate_id}:{slot_id}"))
    if head_revision is not None:
        cur.execute("SELECT approver_id FROM gate_decision WHERE gate_id=%s AND slot_id=%s "
                    "AND decision='approve' AND (revision IS NULL OR revision=%s) ORDER BY approver_id",
                    (gate_id, slot_id, head_revision))
    else:
        cur.execute("SELECT approver_id FROM gate_decision WHERE gate_id=%s AND slot_id=%s "
                    "AND decision='approve' ORDER BY approver_id", (gate_id, slot_id))
    approvers = [r["approver_id"] for r in cur.fetchall()]
    match = _match_tokens(snapshot["tokens"], approvers)
    cur.execute("DELETE FROM gate_token_coverage WHERE gate_id=%s AND slot_id=%s", (gate_id, slot_id))
    for tid, pid in match.items():
        cur.execute("INSERT INTO gate_token_coverage "
                    "(gate_id, slot_id, snapshot_id, snapshot_token_id, covering_principal_id) "
                    "VALUES (%s,%s,%s,%s,%s)", (gate_id, slot_id, snapshot["snapshot_id"], tid, pid))
    return match


def _reproject_open_gate_coverage(cur, cfg, slot_id, artifact):
    """#321 P1.4 — after the head advances for `slot_id` (edit / restore-as-new-revision), recompute the
    DERIVED per-token coverage for any OPEN authoritative gate at this artifact's review stage that
    targets the slot, so a now-superseded approval drops out of the persisted coverage IMMEDIATELY (the
    read models project from that coverage). Only the derived coverage changes; every gate_decision row
    and all audit/history are preserved (append-only)."""
    stage = _resolve_review_stage(cfg, artifact)
    if not stage:
        return
    cur.execute("""SELECT g.gate_id FROM gate g JOIN gate_target t USING (gate_id)
                    WHERE t.slot_id=%s AND g.stage=%s AND g.status='open'""", (slot_id, stage))
    gate_ids = [r["gate_id"] for r in cur.fetchall()]
    if not gate_ids:
        return
    head = _head_revision(cur, slot_id, artifact)
    for gid in gate_ids:
        snap = _load_gate_snapshot(cur, gid)
        if snap is not None:
            _recompute_slot_coverage(cur, gid, slot_id, snap, head_revision=head)


def _covered_token_ids(cur, gate_id, slot_id):
    cur.execute("SELECT snapshot_token_id FROM gate_token_coverage WHERE gate_id=%s AND slot_id=%s",
                (gate_id, slot_id))
    return {r["snapshot_token_id"] for r in cur.fetchall()}


def _authoritative_outcome(snapshot, decisions, covered_ids):
    """Per-slot outcome for an AUTHORITATIVE gate from persisted coverage. Same precedence as the
    legacy tally (reject > request_change > approve); approval is per-token coverage, never a count:
    ALL needs every frozen token covered (by distinct principals — enforced at persist), ANY needs one."""
    kinds = {d["decision"] for d in decisions}
    if "reject" in kinds:
        return "rejected"
    if "request_change" in kinds:
        return "changes_requested"
    n_tokens = len(snapshot["tokens"])
    if snapshot["rule_key"] == "all":
        return "approved" if n_tokens > 0 and len(covered_ids) >= n_tokens else "pending"
    return "approved" if len(covered_ids) >= 1 else "pending"


def _authoritative_target_projection(cur, gate_id, snapshot, slot_id, decisions):
    """Read-model for ONE authoritative target: outcome + remaining requirement + per-token coverage,
    all projected from the FROZEN snapshot and the persisted coverage — never live membership. Keeps
    engine / API / reviewer-eligibility / remaining-UI / audit on one coverage truth (the #196 defect
    was the old read model re-resolving remaining tokens against current membership)."""
    cur.execute("SELECT snapshot_token_id, covering_principal_id FROM gate_token_coverage "
                "WHERE gate_id=%s AND slot_id=%s", (gate_id, slot_id))
    covered = {r["snapshot_token_id"]: r["covering_principal_id"] for r in cur.fetchall()}
    outcome = _authoritative_outcome(snapshot, decisions, set(covered))
    n_tokens, n_cov = len(snapshot["tokens"]), len(covered)
    coverage = [{"token_kind": t["kind"], "token_key": t["key"], "normalized_token": t["normalized"],
                 "covered_by": covered.get(t["snapshot_token_id"])} for t in snapshot["tokens"]]
    if snapshot["rule_key"] == "any":
        remaining_n = 0 if n_cov >= 1 else 1
        remaining = [] if n_cov >= 1 else [{"assignment_kind": t["kind"], "assignment_key": t["key"]}
                                           for t in snapshot["tokens"]]
    else:
        remaining_n = max(0, n_tokens - n_cov)
        remaining = [{"assignment_kind": t["kind"], "assignment_key": t["key"]}
                     for t in snapshot["tokens"] if t["snapshot_token_id"] not in covered]
    return {"current_outcome": outcome, "approval_count": n_cov,
            "remaining_approvals": 0 if outcome != "pending" else remaining_n,
            "remaining_assignments": remaining if outcome == "pending" else [],
            "coverage": coverage}


def _decision_rollup(decisions, quorum_n):
    approvals = {d["approver_id"] for d in decisions if d["decision"] == "approve"}
    outcome = _slot_outcome(decisions, quorum_n)
    return {
        "current_outcome": outcome,
        "approval_count": len(approvals),
        "remaining_approvals": max(0, quorum_n - len(approvals)) if outcome == "pending" else 0,
    }


def _assignment_satisfied(cur, assignment, approved_by):
    if not approved_by:
        return False
    if assignment["assignment_kind"] == "user":
        return assignment["assignment_key"] in approved_by
    token = _token_from_assignment(assignment["assignment_kind"], assignment["assignment_key"])
    return any(_principal_matches_assignment(cur, approver_id, token) for approver_id in approved_by)


def _remaining_assignment_snapshots(cur, rule_key, assignments, decisions):
    if not assignments:
        return []
    approved_by = sorted({d["approver_id"] for d in decisions if d["decision"] == "approve"})
    norm_rule = _normalize_rule_key(rule_key)
    if norm_rule == "any":
        return [] if approved_by else list(assignments)
    return [assignment for assignment in assignments if not _assignment_satisfied(cur, assignment, approved_by)]


def _enrich_assignment_snapshots(cur, snapshots):
    out = []
    for snap in snapshots:
        kind, key = snap["assignment_kind"], snap["assignment_key"]
        label = key
        if kind == "user":
            cur.execute("SELECT display_name_en FROM principal WHERE principal_id=%s", (key,))
        elif kind == "role":
            cur.execute("SELECT display_name_en FROM principal_role WHERE role_id=%s", (key,))
        else:
            cur.execute("SELECT display_name_en FROM principal_group WHERE group_id=%s", (key,))
        row = cur.fetchone()
        if row:
            label = (row["display_name_en"] if isinstance(row, dict) else row[0]) or key
        out.append({**snap, "display_name_en": label})
    return out


def _canonical_rule(rule):
    rule_key = _normalize_rule_key(rule)
    if rule_key not in ("any", "all"):
        raise GateError(f"unsupported approval rule {rule!r} (expected AND/OR)")
    return "and" if rule_key == "all" else "or"


def _policy_assignments(policy):
    users = _dedupe_keep_order(str(x).strip() for x in (policy.get("users") or []))
    roles = _dedupe_keep_order(str(x).strip() for x in (policy.get("roles") or []))
    groups = _dedupe_keep_order(str(x).strip() for x in (policy.get("groups") or []))
    return {
        "users": [x for x in users if x],
        "roles": [x for x in roles if x],
        "groups": [x for x in groups if x],
    }


def _validate_policy_assignments(cur, assignments):
    for user in assignments["users"]:
        cur.execute("""SELECT 1 FROM principal
                       WHERE principal_id=%s AND active=true""", (user,))
        if cur.fetchone() is None:
            raise GateError(f"unknown or inactive approval user {user!r}")
    for role in assignments["roles"]:
        cur.execute("""SELECT 1 FROM principal_role
                       WHERE role_id=%s AND active=true""", (role,))
        if cur.fetchone() is None:
            raise GateError(f"unknown or inactive approval role {role!r}")
    for group in assignments["groups"]:
        cur.execute("""SELECT 1 FROM principal_group
                       WHERE group_id=%s AND active=true""", (group,))
        if cur.fetchone() is None:
            raise GateError(f"unknown or inactive approval group {group!r}")


def _approval_policy_read_model(cur, cfg, stage):
    contract = _db_stage_approval_contract(cur, stage) or _yaml_stage_approval_contract(cfg, stage)
    return {
        "stage": stage,
        "rule_key": contract["rule_key"],
        "quorum": contract["quorum"],
        "users": contract["users"],
        "roles": contract["roles"],
        "groups": contract["groups"],
        "assignments": _enrich_assignment_snapshots(cur, contract["assignments"]),
        "source": contract.get("source", "yaml"),
    }


_PRINCIPAL_KINDS = None


def _principal_kind(cur, actor):
    """Classify an audit actor (user|agent|agent_rep|system) via the principal registry,
    so every event row records WHICH KIND of principal acted. Cached per process."""
    global _PRINCIPAL_KINDS
    if _PRINCIPAL_KINDS is None:
        cur.execute("SELECT principal_id, kind FROM principal")
        _PRINCIPAL_KINDS = {(r["principal_id"] if isinstance(r, dict) else r[0]):
                            (r["kind"] if isinstance(r, dict) else r[1]) for r in cur.fetchall()}
    return _PRINCIPAL_KINDS.get(actor, "system")


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return str(value)


# ---------------------------------------------------------------------------------------------
# #310 Stage 2A — Topic-generation policy resolution + idempotent job enqueue.
#
# These are pure DB seams: no writer, no provider, no network. The live model call is a separate
# operator-gated step. Everything here is additive and consumes accepted Schedule truth read-only.

_TOPIC_GEN_DEFAULTS = {
    "novelty_lookback_days": 90,
    "novelty_max_exclusions": 24,
    "semantic_near_threshold": 0.82,
}


def _bootstrap_topic_generation_policy_tx(cur, tenant_id="default", module="content", actor="system"):
    """#310 §D — the in-transaction create-only baseline seed for ONE (tenant, module) scope (NO commit).

    Additive, non-destructive, and SCOPE-LOCAL: creates the baseline generation ONLY when none exists
    FOR THIS (tenant_id, module). Another scope's lineage neither suppresses this scope's create-only
    init nor is touched by it. If a generation already exists in this scope — active, superseded, or an
    operator's explicit DISABLE — this is a no-op, so a deliberate scope-local disable (the Stage 1
    rollback) is never undone by a later acceptance. Returns the new policy_id, else None."""
    cur.execute("SELECT count(*) AS n FROM topic_generation_policy WHERE tenant_id=%s AND module=%s",
                (tenant_id, module))
    if cur.fetchone()["n"] > 0:
        return None                          # this scope's operator-owned lineage exists — never touch it
    cur.execute("""INSERT INTO topic_generation_policy
                     (generation_no, supersedes, status, actor, reason, tenant_id, module, entry_mode)
                   VALUES (1, NULL, 'active', %s, 'baseline seed (#310)', %s, %s, 'automatic')
                   ON CONFLICT DO NOTHING
                   RETURNING policy_id""", (actor, tenant_id, module))
    row = cur.fetchone()
    return row["policy_id"] if row else None


def bootstrap_topic_generation_policy(conn, tenant_id="default", module="content", actor="system"):
    """#310 §D — create-only baseline seed for one (tenant, module) scope, standalone (own transaction).
    Idempotent no-op if that scope already has a generation. See _bootstrap_topic_generation_policy_tx
    for the in-transaction variant."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        pid = _bootstrap_topic_generation_policy_tx(cur, tenant_id=tenant_id, module=module, actor=actor)
        conn.commit()
        return pid
    finally:
        cur.close()


def resolve_topic_generation_policy(cur, tenant_id="default", module="content"):
    """#310 §D — resolve EXACTLY ONE active generation FOR THIS (tenant, module) scope, or FAIL CLOSED.

    Scoped by tenant_id+module (the same key as the partial unique index), so another scope's active
    generation can never create a false multiple-active ambiguity here. Zero active in scope ->
    GateError (never infer/recreate). Returns the active generation row; the run pins its policy_id."""
    cur.execute("""SELECT * FROM topic_generation_policy
                    WHERE status='active' AND tenant_id=%s AND module=%s
                    ORDER BY generation_no DESC""", (tenant_id, module))
    rows = cur.fetchall()
    if not rows:
        raise GateError(f"no active topic-generation policy for scope ({tenant_id}/{module}) — "
                        "Stage 2A fails closed rather than inventing one (bootstrap a baseline first)")
    if len(rows) > 1:
        raise GateError(f"ambiguous topic-generation policy: multiple active generations in "
                        f"scope ({tenant_id}/{module})")
    return rows[0]


def get_topic_generation_policy_by_id(cur, policy_id):
    """#310 §D — fetch the EXACT pinned generation by id (execution/recovery reads the identity the
    job froze at enqueue, never the currently-active one). Fail closed if the pinned id is missing."""
    cur.execute("SELECT * FROM topic_generation_policy WHERE policy_id=%s", (policy_id,))
    row = cur.fetchone()
    if not row:
        raise GateError(f"pinned topic-generation policy {policy_id} not found — refusing to "
                        "silently re-resolve the active policy")
    return row


def _pin_repetition_policy_id(cur, tenant_id="default", module="content"):
    """#310 §E / #184 — the exact repetition-policy IDENTITY governing THIS scope, resolved by
    (policy_key, tenant_id, module). Returned to be pinned on the job at enqueue and carried into
    provenance — never a live/global select at persist time. None = no managed row for the scope
    (the production default governs), recorded truthfully as NULL."""
    cur.execute("""SELECT policy_id FROM repetition_policy
                    WHERE policy_key=%s AND tenant_id=%s AND module=%s
                    ORDER BY updated_at DESC NULLS LAST LIMIT 1""",
                (REPETITION_POLICY_KEY, tenant_id, module))
    row = cur.fetchone()
    return row["policy_id"] if row else None


# #310 §E — governed identity/contract of the Stage 2A Topic writer. `writers` is the EXISTING
# authoritative writer actor (audit_log records topic writes as actor='writers', actor_kind='agent');
# the contract version is an explicit governed declaration (like publication.CONTRACT_VERSION), NOT a
# fabricated identity. Pinned on the job at enqueue and carried into provenance.
TOPIC_WRITER_AGENT = "writers"
TOPIC_WRITER_CONTRACT_VERSION = "topic-writer.v1"


def repetition_policy_snapshot(conn, cfg=None, tenant_id="default", module="content"):
    """#310 §E — the COMPLETE effective repetition-policy VALUES captured as an IMMUTABLE, JSON-safe
    snapshot at enqueue. Pinning the source UUID alone is insufficient — the scoped row is mutable in
    place (update_repetition_policy) — so a Stage 2A job freezes the whole value set here and both
    EXECUTES and RECORDS from it, never a live lookup. `source_policy_id` keeps lineage back to the
    (mutable) source row; None means no managed row exists and the production default governs."""
    p = effective_repetition_policy(conn, cfg, tenant_id=tenant_id, module=module)
    ua = p.get("updated_at")
    return {
        "snapshot_version": "reppolicy.v1",
        "policy_key": p["policy_key"],
        "source_policy_id": p.get("policy_id"),
        "enabled": p["enabled"],
        "scope": p["scope"],
        "similarity_threshold": p["similarity_threshold"],
        "max_regenerations": p["max_regenerations"],
        "repeat_modes": p["repeat_modes"],
        "source": p["source"],
        "updated_by": p.get("updated_by"),
        "updated_at": ua.isoformat() if hasattr(ua, "isoformat") else ua,
    }


def _principal_ref(cur, principal_id):
    """#310 §E — the TRUTHFUL governed reference for a principal from the EXISTING registry, recording
    only what the schema authoritatively owns (no IAM/delegation invention):

    - actor_kind, autonomy_level, role, org, scope — the principal's real registry attributes.
    - accountable_owner — `principal.owner_id`, whose sole authoritative meaning (migration 003) is
      `agent_rep -> the human it acts for`. Recorded ONLY for kind='agent_rep'; null otherwise. It is
      AgentRep accountability, NOT a generic controlling-principal or delegation grant.
    - control_resolution / controlling_principal / delegation_ref — GENERIC runtime control/delegation
      records do not exist yet (deferred to the governed #21/#197 delegation slice), so these are the
      explicit, immutable, truthful absence: 'not_recorded' / null / null. Never approximated from
      owner_id. An unregistered principal is likewise all-null."""
    cur.execute("""SELECT kind, owner_id, tenant_id, role, autonomy_level, scope
                     FROM principal WHERE principal_id=%s""", (principal_id,))
    r = cur.fetchone()
    kind = r["kind"] if r else _principal_kind(cur, principal_id)
    accountable_owner = (r["owner_id"] if r else None) if kind == "agent_rep" else None
    return {
        "principal_id": principal_id,
        "actor_kind": kind,
        "autonomy_level": r["autonomy_level"] if r else None,
        "role": r["role"] if r else None,
        "org": r["tenant_id"] if r else None,
        "scope": r["scope"] if r else None,
        "accountable_owner": accountable_owner,      # agent_rep -> human it acts for (else null)
        "control_resolution": "not_recorded",        # generic delegation deferred (#21/#197)
        "controlling_principal": None,
        "delegation_ref": None,
    }


def _schedule_authority_snapshot(cur, gate_id, accepted_schedule_token, resolver_actor="system"):
    """#310 §E — the IMMUTABLE AUTHORITY snapshot: the exact accepted Schedule gate + ALL its approving
    gate_decision rows. This is the GOVERNED AUTHORITY that admitted the run, kept SEPARATE from the
    execution lineage (resolver/trigger actor + writer + provider/model/route) and NEVER collapsed to a
    single actor. A quorum may yield MULTIPLE approvers; each carries its REAL decision principal + actor
    kind, its AgentRep accountable_owner where truthfully present (agent_rep only), and the explicit
    'not_recorded' control/delegation absence (generic runtime delegation is the deferred #21/#197 slice,
    never approximated here). `resolved_by` is the execution trigger (the resolver), recorded distinctly.
    Frozen at enqueue so a later principal/membership change never reinterprets this history."""
    cur.execute("SELECT stage, quorum, rule_key FROM gate WHERE gate_id=%s", (gate_id,))
    g = cur.fetchone() or {}
    cur.execute("""SELECT slot_id, approver_id, decision, revision, decided_at
                     FROM gate_decision WHERE gate_id=%s AND decision='approve'
                    ORDER BY decided_at, approver_id, slot_id""", (gate_id,))
    approvals, principals = [], []
    for d in cur.fetchall():
        ref = _principal_ref(cur, d["approver_id"])          # decision principal + its controlling owner
        approvals.append({**ref, "decision": d["decision"], "slot_id": d["slot_id"],
                          "revision": d["revision"],
                          "decided_at": d["decided_at"].isoformat() if d.get("decided_at") else None})
        if d["approver_id"] not in principals:
            principals.append(d["approver_id"])
    return {
        "snapshot_version": "authority.v1",
        "gate_id": str(gate_id),
        "stage": g.get("stage", "schedule_review"),
        "rule_key": g.get("rule_key"),
        "quorum": g.get("quorum"),
        "accepted_schedule_token": accepted_schedule_token,
        "approver_principals": principals,          # may be MULTIPLE — never collapsed
        "approvals": approvals,
        "resolved_by": _principal_ref(cur, resolver_actor),   # EXECUTION trigger, separate from authority
    }


def _round_scope(cur, round_id):
    """The (tenant_id, module) governance scope of a round — the key that scopes policy resolution,
    bootstrap, and pinning. Defaults to the baseline scope if the round predates the columns."""
    cur.execute("SELECT tenant_id, module FROM round WHERE round_id=%s", (round_id,))
    r = cur.fetchone()
    if not r:
        return "default", "content"
    return (r["tenant_id"] or "default"), (r["module"] or "content")


def enqueue_topic_generation(conn, round_id, accepted_schedule_token, actor="system"):
    """#310 §A — enqueue EXACTLY ONE idempotent Topic-generation job for an accepted run.

    Idempotency is arbitrated by the DB: the unique index on (round_id, accepted_schedule_token,
    stage) plus `ON CONFLICT DO NOTHING RETURNING` means first acceptance mints the job and every
    replay/reread/import/retry/legacy re-trigger resolves to the SAME row — never a second job, never
    a backfill. Fails closed if the pinned policy cannot resolve or the accepted token is absent.

    This does NOT run the writer. It records the accepted portfolio's size and returns the job; the
    runner (separate) advances state and appends attempts under existing Topic identities.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        _lock_round(cur, round_id)                       # same round-first lock as Stage 1 writers
        result = _enqueue_topic_generation_tx(cur, round_id, accepted_schedule_token, actor)
        conn.commit()
        return result
    finally:
        cur.close()


def _enqueue_topic_generation_tx(cur, round_id, accepted_schedule_token, actor="system",
                                 authority_snapshot=None, initial_status="queued"):
    """In-transaction enqueue body — NO lock, NO commit. Used by enqueue_topic_generation (which
    wraps it with a round lock + commit) and by resolve() at the schedule_review acceptance, so the
    job is minted in the SAME transaction as the acceptance (the directive's "reuse the acceptance/
    commit transition to enqueue"). Idempotent: a re-run against the same accepted token returns the
    existing job without a second trigger; a policy that will not resolve or an absent token fails
    closed BEFORE any job row is written."""
    if accepted_schedule_token is None:
        raise GateError("topic generation needs the accepted schedule token — trigger provenance "
                        "is ambiguous without it (fail closed, never backfill)")
    # PIN both policy identities ONCE, at acceptance, scoped by the round's (tenant, module). Frozen on
    # the job so execution/recovery never re-resolves the active policy — a later policy change cannot
    # silently alter this job's behaviour or provenance.
    tenant_id, module = _round_scope(cur, round_id)
    policy = resolve_topic_generation_policy(cur, tenant_id, module)
    # IMMUTABLE repetition snapshot (VALUES, not just the mutable UUID) + writer identity/contract,
    # all frozen ONCE here. Execution reads the snapshot, never a live repetition lookup.
    rep_snap = repetition_policy_snapshot(cur.connection, load_config(), tenant_id, module)
    rep_id = rep_snap["source_policy_id"]
    cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s AND status='SCHEDULE_APPROVED'",
                (round_id,))
    total = cur.fetchone()["n"]
    cur.execute("""INSERT INTO generation_job
                     (round_id, accepted_schedule_token, stage, status, slots_total,
                      trigger_source, actor, tenant_id, module,
                      topic_generation_policy_id, repetition_policy_id, repetition_policy_snapshot,
                      writer_agent, writer_contract_version, authority_snapshot, entry_mode)
                   VALUES (%s,%s,'topic',%s,%s,'schedule_acceptance',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (round_id, accepted_schedule_token, stage) DO NOTHING
                   RETURNING job_id, status""",
                (round_id, accepted_schedule_token, initial_status, total, actor, tenant_id, module,
                 policy["policy_id"], rep_id, Json(rep_snap),
                 TOPIC_WRITER_AGENT, TOPIC_WRITER_CONTRACT_VERSION,
                 Json(authority_snapshot) if authority_snapshot is not None else None,
                 policy["entry_mode"]))
    row = cur.fetchone()
    if not row:
        cur.execute("""SELECT job_id, status FROM generation_job
                        WHERE round_id=%s AND accepted_schedule_token=%s AND stage='topic'""",
                    (round_id, accepted_schedule_token))
        existing = cur.fetchone()
        return {"job_id": str(existing["job_id"]), "status": existing["status"],
                "created": False, "topic_generation_policy_id": str(policy["policy_id"])}
    _audit(cur, "round", round_id, "topic_generation_enqueued", actor,
           {"job_id": str(row["job_id"]), "accepted_schedule_token": accepted_schedule_token,
            "slots_total": total, "tenant_id": tenant_id, "module": module,
            "topic_generation_policy_id": str(policy["policy_id"]),
            "repetition_policy_id": str(rep_id) if rep_id else None})
    return {"job_id": str(row["job_id"]), "status": "queued", "created": True,
            "slots_total": total, "topic_generation_policy_id": str(policy["policy_id"]),
            "repetition_policy_id": str(rep_id) if rep_id else None}


def build_novelty_brief(cur, slot, policy, tenant_id="default"):
    """#310 §B / #268 — a BOUNDED, explainable novelty brief from Tanaghom-owned Topic history.

    Proactive counterpart to the reactive dedup net: instead of only avoiding a treatment AFTER the
    model repeats it, pre-seed the first prompt with a compact exclusion set of recently-used
    territory for THIS slot's accepted lineage (pillar/HCS/framework), newest first. Bounded by the
    pinned policy's lookback window and max-exclusions cap — never the full ledger. #184's
    post-generation semantic dedup remains the authoritative final net; this only steers.

    Returns {version, exclusion_texts, input_topic_ids, selection_reason}. Explainable: the reason
    records exactly why each item was included."""
    lookback = int(policy.get("novelty_lookback_days", 90))
    cap = int(policy.get("novelty_max_exclusions", 24))
    # Same accepted lineage (pillar via hcs, and hcs), within the policy lookback, newest first.
    # `topic.text_ar` is the persisted Arabic topic angle (the model-output "topic_angle" key maps to
    # this column — see process_topic.current_head); `hook_text` is the persisted hook.
    cur.execute("""SELECT t.topic_id, t.text_ar AS topic_angle, t.hook_text
                     FROM topic t
                    WHERE t.tenant_id=%s
                      AND t.hcs_id = %s
                      AND t.created_at >= now() - (%s || ' days')::interval
                      AND t.slot_id IS DISTINCT FROM %s
                    ORDER BY t.created_at DESC
                    LIMIT %s""",
                (tenant_id, slot.get("hcs_id"), str(lookback), slot.get("slot_id"), cap))
    rows = cur.fetchall()
    exclusion_texts = [f"{r['topic_angle']} / {r['hook_text']}" for r in rows if r.get("topic_angle")]
    input_ids = [str(r["topic_id"]) for r in rows]
    return {
        "version": "novelty-v1",
        "exclusion_texts": exclusion_texts,
        "input_topic_ids": input_ids,
        "selection_reason": {
            "scope": {"hcs_id": slot.get("hcs_id"), "pillar_code": slot.get("pillar_code")},
            "lookback_days": lookback, "cap": cap, "selected": len(input_ids),
            "basis": "same accepted HCS lineage, recency-ordered, bounded by pinned policy",
        },
    }


def record_rework_provenance(cur, topic_id, revision, slot_id, actor,
                             resolved_provider, resolved_model, execution_route, tenant_id="default"):
    """#313 — provenance for a MANUAL rework: EXACT and JOB-LESS (Codex blocker 6). A manual rework has
    no Stage 2A generation_job behind it, so job_id stays NULL and every PINNED-generation identity
    (methodology/policy/token/repetition) stays NULL — never fabricated to look job-driven. novelty
    inputs are empty (a manual rework runs no proactive novelty). It records only what ACTUALLY ran: the
    resolved provider/model/route, the effective actor, and the base revision this attempt varies from
    (variant_of_topic_id = the head it reworked). Keyed idempotently on (topic_id, revision)."""
    cur.execute("SELECT topic_id FROM topic WHERE slot_id=%s AND revision=%s", (slot_id, revision - 1))
    base = cur.fetchone()
    # on_persist may pass a plain (tuple) cursor, so read positionally, not by key.
    variant_of = (base["topic_id"] if isinstance(base, dict) else base[0]) if base else None
    cur.execute("""INSERT INTO topic_provenance
                     (topic_id, revision, job_id, effective_actor, resolved_provider, resolved_model,
                      execution_route, variant_of_topic_id, novelty_input_topic_ids, tenant_id)
                   VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (topic_id, revision) DO NOTHING""",
                (topic_id, revision, actor, resolved_provider, resolved_model, execution_route,
                 variant_of, Json([]), tenant_id))


def record_script_rework_provenance(cur, script_id, revision, slot_id, actor,
                                    resolved_provider, resolved_model, execution_route,
                                    tenant_id="default"):
    """#367 R3.3 — provenance for a MANUAL Script rework: the Script counterpart of
    record_rework_provenance, EXACT and JOB-LESS. A manual rework has no Stage 3 generation_job, so
    job_id stays NULL and every pinned-generation identity (methodology/workflow/token) stays NULL —
    never fabricated to look job-driven (amendment 8: unknown/non-applicable stays explicit). It
    records only what actually ran: the resolved provider/model, the effective actor, the manual-rework
    route, and the base Script revision this attempt varies from (the head it reworked). Keyed
    idempotently on (script_id, revision), matching process_script's own provenance conflict key, so a
    resumed/replayed op converges on one row."""
    cur.execute("""INSERT INTO script_provenance
                     (script_id, revision, job_id, slot_id, effective_actor,
                      requested_route, requested_provider, requested_model,
                      effective_route, effective_provider, effective_model,
                      writer_mode, initiating_actor, runtime_build)
                   VALUES (%s,%s,NULL,%s,%s,NULL,NULL,NULL,%s,%s,%s,'scripts',%s,%s)
                   ON CONFLICT (script_id, revision) DO NOTHING""",
                (script_id, revision, slot_id, actor,
                 execution_route, resolved_provider, resolved_model,
                 actor, os.environ.get("TANAGHOM_BUILD_SHA") or "not_applicable"))


def record_topic_provenance(cur, topic_id, revision, job_row, policy_id, resolved_provider,
                            resolved_model, actor, novelty=None):
    """#310 §E — record the exact per-attempt provenance for one generated Topic attempt.

    Keyed (topic_id, revision) — the canonical identity + append-only attempt lineage that already
    exists on `topic`. Records the RESOLVED provider/model/route/actor (not configured intent) and the
    PINNED policy identities the job froze at enqueue (topic_generation_policy_id + repetition_policy_id
    from job_row) — NEVER a live/global select at persist time, so a policy change or another scope's
    policy can never be attributed to this attempt."""
    rid = job_row["round_id"]
    cur.execute("""SELECT methodology_version, baseline_policy_id::text AS schedule_policy_snapshot
                     FROM round_policy_snapshot WHERE round_id=%s""", (rid,))
    snap = cur.fetchone() or {}
    # PINNED, not live: the repetition-policy identity (UUID lineage) AND the IMMUTABLE value snapshot
    # the job froze at enqueue (NULL id = production default). Never a live select at persist time.
    _jget = job_row.get if hasattr(job_row, "get") else (lambda k, d=None: job_row[k] if k in job_row else d)
    rep_id = _jget("repetition_policy_id")
    rep_snap = _jget("repetition_policy_snapshot")
    # ACTUAL writer/agent identity + governed contract version (pinned on the job); effective actor is
    # the authorizing acceptance actor. This is the agent lineage — reused authoritative references,
    # never fabricated: writer_agent is the existing 'writers' audit actor, the contract a governed id.
    writer_agent = _jget("writer_agent")
    writer_contract = _jget("writer_contract_version")
    entry_mode = _jget("entry_mode")          # the governed mode this attempt ran under (pinned on the job)
    # AUTHORITY lineage carried immutably from the job (the gate + approvers + AgentRep accountable
    # owners where truthfully present; generic control/delegation is 'not_recorded') — the run NEVER
    # re-resolves live memberships. `effective_actor` here is the EXECUTION resolver/trigger (job.actor),
    # kept SEPARATE from the authority approvers; the two may legitimately differ.
    authority = _jget("authority_snapshot")
    novelty = novelty or {}
    cur.execute("""INSERT INTO topic_provenance
                     (topic_id, revision, job_id, methodology_version, schedule_policy_snapshot,
                      accepted_schedule_token, repetition_policy_id, repetition_policy_snapshot,
                      topic_generation_policy_id, writer_contract_version, writer_agent,
                      authority_snapshot, entry_mode, resolved_provider, resolved_model, execution_route,
                      effective_actor, novelty_brief_version, novelty_input_topic_ids,
                      novelty_selection_reason)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (topic_id, revision) DO NOTHING""",
                (topic_id, revision, job_row["job_id"], snap.get("methodology_version"),
                 snap.get("schedule_policy_snapshot"), job_row["accepted_schedule_token"],
                 rep_id, Json(rep_snap) if rep_snap is not None else None,
                 policy_id, writer_contract, writer_agent,
                 Json(authority) if authority is not None else None, entry_mode,
                 resolved_provider, resolved_model, "in_process", actor, novelty.get("version"),
                 Json(novelty.get("input_topic_ids", [])), Json(novelty.get("selection_reason"))))


def topic_generation_read_model(conn, round_id):
    """#310 §F — the durable, truthful read model for Stage 2A Topic generation of ONE round.

    Every UI state is read from DURABLE truth, never inferred client-side: `phase` (empty | queued |
    running | partial | failed | completed) comes from the latest generation_job row; `stage2a_enabled`
    is the provisioning flag — absent active policy means Stage 2A is NOT PROVISIONED for this round (no
    generation command is available) and this model is empty (no jobs). Per accepted slot it surfaces the accepted schedule
    facts (Pillar/HCS/format), the canonical Topic identity (topic_id + append-only revision), the Topic
    meaning/title, and the provenance DISCLOSURE (resolved provider/model/route, the novelty-brief
    version, and the pinned generations consumed) — resolved truth, never configured intent."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Provisioning flag — Stage 2A is provisioned by an active generation policy IN THIS ROUND'S SCOPE.
    # Another tenant/module's active policy must not make this round look provisioned.
    _tenant, _module = _round_scope(cur, round_id)
    cur.execute("""SELECT entry_mode FROM topic_generation_policy
                    WHERE status='active' AND tenant_id=%s AND module=%s LIMIT 1""", (_tenant, _module))
    _pol = cur.fetchone()
    stage2a_enabled = _pol is not None
    # entry_mode is resolved from the round's IMMUTABLE acceptance job snapshot (below), NEVER from this
    # live active policy — a later policy-generation change must not reinterpret an existing run.

    # Durable job truth: loading/empty/partial/failed/completed are ALL readable here.
    cur.execute("""SELECT job_id, accepted_schedule_token, stage, status, slots_total, slots_done,
                          slots_failed, trigger_source, error_detail, entry_mode, created_at, updated_at
                     FROM generation_job WHERE round_id=%s ORDER BY created_at""", (round_id,))
    jobs = []
    for j in cur.fetchall():
        jobs.append({"job_id": str(j["job_id"]), "accepted_schedule_token": j["accepted_schedule_token"],
                     "stage": j["stage"], "status": j["status"], "slots_total": j["slots_total"],
                     "slots_done": j["slots_done"], "slots_failed": j["slots_failed"],
                     "trigger_source": j["trigger_source"], "error_detail": j["error_detail"],
                     "entry_mode": j["entry_mode"],
                     "created_at": j["created_at"].isoformat() if j["created_at"] else None,
                     "updated_at": j["updated_at"].isoformat() if j["updated_at"] else None})

    # Per accepted slot: accepted schedule facts + canonical Topic identity + provenance disclosure.
    cur.execute("""SELECT slot_id, pillar_code, hcs_id, format, status, day, time_uae
                     FROM slot WHERE round_id=%s ORDER BY day, time_uae, slot_id""", (round_id,))
    slots = cur.fetchall()
    results = []
    for s in slots:
        cur.execute("""SELECT topic_id, revision, text_ar, hook_text FROM topic
                        WHERE slot_id=%s ORDER BY revision DESC, created_at DESC LIMIT 1""", (s["slot_id"],))
        t = cur.fetchone()
        prov = None
        if t:
            cur.execute("""SELECT resolved_provider, resolved_model, execution_route, novelty_brief_version,
                                  methodology_version, topic_generation_policy_id, accepted_schedule_token
                             FROM topic_provenance WHERE topic_id=%s AND revision=%s
                             ORDER BY created_at DESC LIMIT 1""", (t["topic_id"], t["revision"]))
            prov = cur.fetchone()
        results.append({
            "slot_id": s["slot_id"],
            "accepted": {"pillar_code": s["pillar_code"], "hcs_id": s["hcs_id"], "format": s["format"]},
            "slot_status": s["status"],
            "topic": None if not t else {"topic_id": str(t["topic_id"]), "revision": t["revision"],
                                          "title": t["hook_text"], "meaning": t["text_ar"]},
            "provenance": None if not prov else {
                "resolved_provider": prov["resolved_provider"], "resolved_model": prov["resolved_model"],
                "execution_route": prov["execution_route"],
                "novelty_brief_version": prov["novelty_brief_version"],
                "methodology_version": prov["methodology_version"],
                "topic_generation_policy_id": (str(prov["topic_generation_policy_id"])
                                               if prov["topic_generation_policy_id"] else None),
                "accepted_schedule_token": prov["accepted_schedule_token"]},
        })
    cur.close()
    phase = jobs[-1]["status"] if jobs else "empty"
    # entry_mode from the immutable job snapshot (the accepted run's pinned mode), not live policy.
    entry_mode = jobs[-1]["entry_mode"] if jobs else None
    return {"round_id": round_id, "stage2a_enabled": stage2a_enabled, "entry_mode": entry_mode,
            "phase": phase, "jobs": jobs, "results": results,
            "counts": {"accepted": len(slots), "generated": sum(1 for r in results if r["topic"])}}


def retry_topic_generation(conn, round_id, actor):
    """#310 §F — retry a FAILED/PARTIAL Stage 2A Topic-generation job, through the EXISTING binding.

    This is deliberately NOT a second start path: it refuses unless a retryable job already exists
    (`failed` or `partial`). A completed job, a still-running job, or a round with NO job at all is
    rejected — starting fresh generation stays the schedule-acceptance trigger / dashboard button.
    The retry is bounded and idempotent by construction: process_topic advances a slot to
    TOPIC_PROPOSED, so re-driving the job only re-attempts the slots still at SCHEDULE_APPROVED —
    already-generated Topic identities are never recreated. Attribution + audit record who retried;
    caller (API) has already authorized the actor through the same signed-principal binding as generate.
    Returns the job to re-drive; the caller runs it on the existing background-job mechanism."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #360 — WITHOUT `stage='topic'` this is not merely racy, it is DETERMINISTICALLY wrong: on any
    # round that has reached Scripts the Script attempt is the most recent generation_job, so
    # `ORDER BY created_at DESC LIMIT 1` selects it every time and the UPDATE below would re-queue a
    # Script attempt as a Topic retry.
    cur.execute("""SELECT * FROM generation_job WHERE round_id=%s AND stage='topic'
                    ORDER BY created_at DESC LIMIT 1""", (round_id,))
    job = cur.fetchone()
    if not job:
        cur.close()
        raise GateError("nothing to retry: no Topic-generation job for this round "
                        "(starting generation is the schedule-acceptance trigger, not a retry)")
    if job["status"] not in ("failed", "partial"):
        cur.close()
        raise GateError(f"nothing to retry: the job is '{job['status']}' — only a failed or partial "
                        "job is retryable (a completed or running job is not re-driven)")
    cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s AND status='SCHEDULE_APPROVED'",
                (round_id,))
    remaining = cur.fetchone()["n"]
    # Reset to queued so the runner picks it up; counts are recomputed by the run.
    cur.execute("UPDATE generation_job SET status='queued', updated_at=now() "
                "WHERE job_id=%s AND stage='topic'",
                (job["job_id"],))
    _audit(cur, "generation_job", job["job_id"], "topic_generation_retry", actor,
           {"from_status": job["status"], "remaining_slots": remaining,
            "accepted_schedule_token": job["accepted_schedule_token"]})
    conn.commit()
    cur.close()
    return {"job_id": str(job["job_id"]), "round_id": round_id, "retryable_slots": remaining,
            "accepted_schedule_token": job["accepted_schedule_token"], "retried_by": actor}


# #310 §A — how long a claimed run may go un-heartbeated before a drainer treats it as abandoned and
# reclaims it. The runner heartbeats INDEPENDENTLY (a background keeper on its own connection) at a
# fraction of this interval throughout the whole attempt, so a healthy long run — even one exceeding
# a single provider timeout via verifier/dedup regenerations — keeps extending its lease and is never
# stolen. Configurable so timing-controlled recovery tests can use a short lease.
TOPIC_GENERATION_LEASE_SECONDS = int(os.environ.get("TANAGHOM_TOPICGEN_LEASE_SECONDS", "300"))


def pending_topic_generation_jobs(conn, round_id=None):
    """#310 §A — jobs the durable drain must run: QUEUED (never started) OR a 'running' job whose
    execution lease has EXPIRED (a worker died mid-run without finishing). Returning stale-running
    jobs is what gives BOUNDED CRASH RECOVERY — a claim that died after queued->running but before
    completion is reclaimable, instead of being stranded forever. A 'running' job with a fresh
    heartbeat is deliberately excluded: it is genuinely active and must not be stolen."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #360 — STAGE ISOLATION. `generation_job` is stage-aware and #357 added durable Script rows to
    # it, so a status-only predicate makes a queued or lease-expired SCRIPT attempt visible to the
    # TOPIC drain — which would claim it and run the Topic writer against it. The predicate lives in
    # SQL, not in a caller-side filter: PostgreSQL is the serializer, and an in-memory check would not
    # bind the atomic claim below.
    where = ("stage='topic' AND (status='queued' OR (status='running' AND lease_expires_at IS NOT NULL "
             "AND lease_expires_at < now()))")
    if round_id:
        cur.execute(f"""SELECT job_id, round_id, slots_total FROM generation_job
                         WHERE {where} AND round_id=%s ORDER BY created_at""", (round_id,))
    else:
        cur.execute(f"""SELECT job_id, round_id, slots_total FROM generation_job
                         WHERE {where} ORDER BY created_at""")
    rows = [{"job_id": str(r["job_id"]), "round_id": r["round_id"], "slots_total": r["slots_total"]}
            for r in cur.fetchall()]
    cur.close()
    return rows


def claim_topic_generation_job(conn, job_id, worker="dispatch"):
    """#310 §A — atomically LEASE one job for execution. Wins a QUEUED job, OR reclaims a 'running'
    job whose lease has EXPIRED (abandoned) — never one with a live lease (a genuinely active run).

    Returns True only if THIS caller won the lease; False otherwise (already claimed and alive, or
    completed) — the caller must then NOT run it. `FOR UPDATE SKIP LOCKED` + the atomic UPDATE mean
    exactly one caller transitions the row, so a replayed/duplicated/racing drain never double-runs.
    Sets the lease window + heartbeat so this run is protected until it stops heartbeating."""
    cur = conn.cursor()
    cur.execute("""UPDATE generation_job
                      SET status='running',
                          lease_expires_at = now() + (%s || ' seconds')::interval,
                          heartbeat_at = now(), claimed_by = %s, updated_at = now()
                    WHERE job_id = (SELECT job_id FROM generation_job
                                      WHERE job_id=%s AND stage='topic'
                                        AND (status='queued'
                                             OR (status='running' AND lease_expires_at IS NOT NULL
                                                 AND lease_expires_at < now()))
                                      FOR UPDATE SKIP LOCKED)
                   RETURNING job_id""",
                (str(TOPIC_GENERATION_LEASE_SECONDS), worker, job_id))
    won = cur.fetchone() is not None
    conn.commit(); cur.close()
    return won


def round_topic_generation_job(conn, round_id):
    """#310 — the round's canonical Stage 2A topic generation_job id (latest), or None. Used by the
    Generate endpoint to detect a Stage 2A round (any status) so it never falls back to the legacy
    run_topics path for a governed round — idempotent whether the job is awaiting/queued/running/done."""
    cur = conn.cursor()
    cur.execute("""SELECT job_id FROM generation_job WHERE round_id=%s AND stage='topic'
                    ORDER BY created_at DESC LIMIT 1""", (round_id,))
    row = cur.fetchone(); cur.close()
    return str(row[0]) if row else None


# #332 — typed outcomes of a MANUAL Topic-generation start. Security denials are COARSE: a
# valid-but-non-approver principal and a missing/malformed target are externally indistinguishable
# (MANUAL_START_DENIED). Mode/lifecycle detail is exposed ONLY after immutable-snapshot eligibility.
MANUAL_START_DENIED = "authz_denied"          # no canonical job / malformed snapshot / non-participant
MANUAL_START_AUTOMATIC = "automatic_denied"   # eligible principal, but the job is automatic-mode (invariant)
MANUAL_START_LIFECYCLE = "lifecycle"          # eligible principal, but the job is not awaiting_trigger
MANUAL_START_ACTIVATED = "activated"          # eligible + startable: the one transition happened here


def _normalized_approver_ids(snapshot):
    """#332 — the closed eligible set is the immutable snapshot's affirmative approvers ONLY
    (`approver_principals[]` == gate_decision decision='approve'). `resolved_by` (execution lineage) is
    NEVER read here. Normalize to trimmed non-empty strings; ANY non-string/empty id fails the WHOLE set
    closed (return None) rather than silently dropping an entry. No case/alias/substring expansion."""
    if not isinstance(snapshot, dict):
        return None
    principals = snapshot.get("approver_principals")
    if not isinstance(principals, list) or not principals:
        return None
    seen = {}   # normalized id -> the exact raw string that produced it
    for p in principals:
        if not isinstance(p, str):
            return None
        pid = p.strip()
        if not pid:
            return None
        # EXACT duplicate raw ids are tolerated (deduped); DIFFERENTLY-REPRESENTED ids that normalize to
        # the same value are a duplicate-conflicting collision and FAIL CLOSED — never silently merged.
        if pid in seen and seen[pid] != p:
            return None
        seen[pid] = p
    return set(seen.keys())


def _authority_snapshot_ok(snapshot, job):
    """#332 — structural fail-closed binding of the immutable snapshot to THIS locked job: canonical
    schedule gate stage, EXACT accepted-token match, well-formed gate id, and a well-formed approver
    set. Any mismatch/malformation is a closed failure (indistinguishable coarse denial upstream)."""
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("stage") != "schedule_review":
        return False
    tok = snapshot.get("accepted_schedule_token")
    if tok is None or tok != job.get("accepted_schedule_token"):
        return False
    gid = snapshot.get("gate_id")
    if not isinstance(gid, str) or not gid.strip():
        return False
    return _normalized_approver_ids(snapshot) is not None


def activate_manual_topic_generation(conn, round_id, principal):
    """#332 — AUTHORIZE (immutable Schedule affirmative-approver) + ACTIVATE the round's MANUAL Topic
    generation_job (awaiting_trigger -> queued), all on the SAME plain-`FOR UPDATE` locked row (NO
    `SKIP LOCKED`), with EXACTLY ONE accepted audit in the SAME transaction. Coarse authorization-safe
    denials: a missing/malformed target and a valid non-approver are indistinguishable; mode/lifecycle
    detail is revealed only AFTER eligibility is proven. Authority + provisioning derive from the LOCKED
    job's pinned snapshot/policy/entry_mode — NEVER live policy (a later config generation can't
    reinterpret this already-admitted job). Returns a typed outcome; NEVER partially mutates on a denial.

    `manual differs from automatic only in WHEN the trigger fires, not how` (#310) — the activated job
    runs the SAME run_stage2a_topic_job (pinned policy, novelty, provenance, lease/heartbeat, recovery)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _deny(code, extra=None):
        # Only read-locks are held (no partial writes). Release them, then persist the denial in its OWN
        # committed transaction (audit_denied) so the security trail survives the failed request. The
        # denial STANDS even if the audit write itself fails — a denial-audit failure can never authorize.
        conn.rollback()
        detail = {"reason": "not_authorized", "code": code}
        if extra:
            detail.update(extra)
        try:
            audit_denied(conn, "round", str(round_id), "topic_generation_manual_start_denied", principal, detail)
        except Exception:
            conn.rollback()   # best-effort audit; the coarse denial is returned regardless

    # ROUND-FIRST lock — THE single serialization point (`_lock_round` order), taken BEFORE selecting the
    # job, so a concurrent Schedule acceptance/enqueue (which also locks the round first) cannot interleave
    # to insert a NEWER accepted-token Topic job and leave a stale row as the authorized target. Same lock
    # order as enqueue => no deadlock. Held across authorize + transition + audit.
    cur.execute("SELECT round_id, tenant_id, module FROM round WHERE round_id=%s FOR UPDATE", (round_id,))
    rnd = cur.fetchone()
    if not rnd:
        _deny("no_round"); return {"result": MANUAL_START_DENIED}
    scope_tenant = (rnd.get("tenant_id") or "default")
    scope_module = (rnd.get("module") or "content")

    # Now select+lock the exact latest canonical Topic job UNDER the held round lock (plain FOR UPDATE, NO
    # SKIP LOCKED): concurrent manual starts serialize; the loser re-reads a non-awaiting status -> replay.
    cur.execute("""SELECT job_id, round_id, stage, status, entry_mode, accepted_schedule_token,
                          tenant_id, module, topic_generation_policy_id, authority_snapshot
                     FROM generation_job WHERE round_id=%s AND stage='topic'
                    ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", (round_id,))
    job = cur.fetchone()

    # ---- COARSE authorization-safe denials (target existence/scope/mode NEVER leaked) ----
    if not job:
        _deny("no_canonical_job"); return {"result": MANUAL_START_DENIED}
    snap = job.get("authority_snapshot")
    if not _authority_snapshot_ok(snap, job) or job.get("topic_generation_policy_id") is None:
        _deny("snapshot_or_provisioning_invalid"); return {"result": MANUAL_START_DENIED}
    # tenant/module binding: the pinned job scope MUST equal the server-derived round scope (both under
    # the held round lock) — a corrupted/cross-scope pinned row fails closed with the coarse denial.
    if (job.get("tenant_id") or "default") != scope_tenant or (job.get("module") or "content") != scope_module:
        _deny("scope_mismatch"); return {"result": MANUAL_START_DENIED}
    eligible = _normalized_approver_ids(snap)  # non-None here (verified by _authority_snapshot_ok)
    if (principal or "").strip() not in eligible:
        _deny("not_participant"); return {"result": MANUAL_START_DENIED}

    # ---- principal PROVEN an affirmative Schedule approver; only NOW reveal mode/lifecycle ----
    if job["entry_mode"] != "manual":
        # automatic-mode exclusion is a security invariant with its OWN typed denial (post-eligibility);
        # never convert automatic -> manual or manufacture an awaiting state.
        conn.rollback()
        try:
            audit_denied(conn, "round", str(round_id), "topic_generation_manual_start_denied",
                         principal, {"reason": "automatic_mode", "entry_mode": job["entry_mode"]})
        except Exception:
            conn.rollback()
        return {"result": MANUAL_START_AUTOMATIC}
    if job["status"] != "awaiting_trigger":
        # lifecycle (already activated / running / completed / failed / partial) — NOT an auth failure,
        # and NO second accepted audit: the idempotent typed replay for the authorized approver.
        conn.rollback()
        return {"result": MANUAL_START_LIFECYCLE, "status": job["status"], "job_id": str(job["job_id"])}

    # ---- AUTHORIZED + STARTABLE: the ONE transition + the ONE accepted audit, atomic on THIS row ----
    # The transition and its accepted audit are ONE transaction: if the audit insert (or the commit)
    # fails, the whole thing ROLLS BACK — never a queued job without its actor-attributed accepted audit.
    try:
        # #360 — the row was already selected under `stage='topic'` above, so this is safe by data
        # flow; the predicate makes it safe STRUCTURALLY, so a later change to that SELECT cannot
        # silently turn this into a cross-stage write.
        cur.execute("UPDATE generation_job SET status='queued', updated_at=now() "
                    "WHERE job_id=%s AND stage='topic'", (job["job_id"],))
        _audit(cur, "generation_job", job["job_id"], "topic_generation_manual_start", principal,
               {"round_id": str(round_id), "stage": "topic", "gate_id": snap.get("gate_id"),
                "accepted_schedule_token": job["accepted_schedule_token"],
                "topic_generation_policy_id": str(job["topic_generation_policy_id"]),
                "entry_mode": "manual", "from_status": "awaiting_trigger", "to_status": "queued"})
        conn.commit()
    except Exception:
        conn.rollback()   # accepted-audit / transition failure -> neither is committed
        raise
    finally:
        cur.close()
    return {"result": MANUAL_START_ACTIVATED, "job_id": str(job["job_id"])}


def heartbeat_topic_generation_job(conn, job_id):
    """#310 §A — extend the execution lease while a run makes progress, so a healthy long run is
    never mistaken for abandoned and reclaimed. Called per slot by the runner."""
    cur = conn.cursor()
    cur.execute("""UPDATE generation_job
                      SET lease_expires_at = now() + (%s || ' seconds')::interval,
                          heartbeat_at = now()
                    WHERE job_id=%s AND stage='topic' AND status='running'""",
                (str(TOPIC_GENERATION_LEASE_SECONDS), job_id))
    conn.commit(); cur.close()


_UNSET = object()   # sentinel: distinguish "leave error_detail unchanged" from "clear it to NULL"


def set_generation_job_state(conn, job_id, status=None, done=None, failed=None, error=_UNSET):
    """#310 §A — advance the durable job's truthful state/counts. `error` is TRISTATE: omit it to
    leave error_detail unchanged; pass a typed dict to set it; pass None to CLEAR it. So a job that
    recovers from partial to completed explicitly clears the stale partial error (completed =>
    error_detail IS NULL), instead of carrying a scary message that no longer applies. A TERMINAL
    status (completed/failed) also releases the execution lease — a finished job is not reclaimable."""
    cur = conn.cursor()
    sets, params = ["updated_at=now()"], []
    if status is not None:
        sets.append("status=%s"); params.append(status)
        if status in ("completed", "failed"):
            sets.append("lease_expires_at=NULL")     # terminal: release the lease, not reclaimable
    if done is not None:   sets.append("slots_done=%s"); params.append(done)
    if failed is not None: sets.append("slots_failed=%s"); params.append(failed)
    if error is not _UNSET:
        if error is None:  sets.append("error_detail=NULL")
        else:              sets.append("error_detail=%s"); params.append(Json(error))
    # #360 — the Topic runner's terminal write. Stage-scoped so a wrong-stage job can never receive
    # Topic-shaped terminal state (status/counters/error). Script terminal state has its own
    # `finish_script_generation_job`; this helper has exactly one caller (the Topic runner), so the
    # predicate narrows nothing any caller relies on.
    cur.execute(f"UPDATE generation_job SET {', '.join(sets)} WHERE job_id=%s AND stage='topic'",
                params+[job_id])
    conn.commit(); cur.close()


def _audit(cur, entity, entity_id, action, actor, detail):
    cur.execute(
        "INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (entity, str(entity_id), action, actor, _principal_kind(cur, actor), Json(_jsonable(detail))))


def audit_denied(conn, entity, entity_id, action, actor, detail):
    """#10 — persist a DENIED approval attempt in its OWN committed transaction. Denials raise
    (GateError / HTTP 4xx) and the caller's transaction rolls back with them, so a plain _audit
    would vanish; the security trail must survive the rollback. Call only while the transaction
    holds no partial writes (the authorization guards run before any mutation). An audit failure
    must never mask the denial itself."""
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _audit(cur, entity, entity_id, action, actor, detail)
        conn.commit()
        cur.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _emit_directive_on_transition(cur, slot_id, gate_stage, cfg, actor, strict=False):
    """M9·B1: when a stage's review gate APPROVES (a real status transition), emit that
    stage's OUTPUT directive — the input contract the NEXT stage consumes. Guarded by default:
    a directive failure NEVER blocks a legacy approval (in B1 directives are a memory/provenance
    seam, not yet a hard gate). `strict=True` (#255 S1): the media-edit handoff is part of the
    REQUIRED atomic approval contract — an emission failure PROPAGATES so the caller's
    transaction rolls back the ENTIRE resolution (status, pin, audit, directive together)."""
    if not directives.is_enabled(cfg):
        return
    try:
        stage_name, contract = directives.stage_by_gate(cfg, gate_stage)
        if not stage_name or not contract.get("emits"):
            return
        directives.emit_output(cur, slot_id, stage_name, cfg,
                               actor=actor, actor_kind=_principal_kind(cur, actor))
    except Exception as e:                       # noqa: BLE001 — never break a LEGACY transition
        if strict:
            raise
        print(f"  [directive] emit skipped for {slot_id} @ {gate_stage}: {e}")


# --------------------------------------------------------------------------- #
# Version navigation — approved-revision pointer (revisions are append-only)
# --------------------------------------------------------------------------- #
def _head_revision(cur, slot_id, artifact):
    tbl = "topic" if artifact == "topic" else "script"
    cur.execute(f"SELECT coalesce(max(revision),1) AS r FROM {tbl} WHERE slot_id=%s", (slot_id,))
    r = cur.fetchone()
    return r["r"] if isinstance(r, dict) else r[0]


def approved_revision(cur, slot_id, artifact):
    """The revision recorded as approved for this artifact (the downstream stage reads THIS),
    falling back to the current head if nothing is pinned yet."""
    cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact=%s",
                (slot_id, artifact))
    r = cur.fetchone()
    if r:
        return r["revision"] if isinstance(r, dict) else r[0]
    return _head_revision(cur, slot_id, artifact)


def _record_approval(cur, slot_id, artifact, revision, approver):
    """Pin the approved revision for an artifact (approve v2 even if v3 exists). Audited."""
    cur.execute("INSERT INTO slot_approval (slot_id, artifact, revision, approver, actor_kind) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (slot_id, artifact) DO UPDATE SET "
                "revision=EXCLUDED.revision, approver=EXCLUDED.approver, "
                "actor_kind=EXCLUDED.actor_kind, at=now()",
                (slot_id, artifact, revision, approver, _principal_kind(cur, approver)))
    _audit(cur, "slot", slot_id, "approved_revision", approver,
           {"artifact": artifact, "revision": revision})


def _review_status_for_artifact(cfg, artifact):
    for gc in (cfg.get("gates") or {}).values():
        if gc.get("rework_mode") == artifact and gc.get("reviews_status"):
            rs = gc["reviews_status"]
            return rs[0] if isinstance(rs, list) else rs
    return "TOPIC_PROPOSED" if artifact == "topic" else "DRAFT_ASSIGNED"


def list_revisions(conn, slot_id, artifact="topic"):
    """The full LINEAR revision chain for an artifact (append-only), each with its driving comment,
    change-summary, provenance (base_revision), and whether it's the approved one."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if artifact == "topic":
        # topic_id is the IMMUTABLE identity of THIS revision row (minted per revision); it is exposed
        # truthfully here so a consumer never conflates it with a stable cross-revision identity — the
        # stable per-item key is slot_id (#313 identity disclosure, Codex blocker 4).
        cur.execute("SELECT topic_id::text AS topic_id, revision, hook_text, text_ar AS body, feedback, "
                    "change_summary_ar, change_summary_en, base_revision, created_at FROM topic "
                    "WHERE slot_id=%s ORDER BY revision", (slot_id,))
    else:
        cur.execute("SELECT revision, final_line, left(script_ar,200) AS body, feedback, "
                    "change_summary_ar, change_summary_en, base_revision, model, "
                    "needs_scholar_review, needs_native_review, created_at FROM script "
                    "WHERE slot_id=%s ORDER BY revision", (slot_id,))
    rows = cur.fetchall()
    cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact=%s",
                (slot_id, artifact))
    pin = cur.fetchone()
    pinned = (pin["revision"] if pin else None)
    cur.close()
    for r in rows:
        r["approved"] = (r["revision"] == pinned)
    return rows


def restore_revision(conn, slot_id, artifact, from_revision, actor="system", cfg=None,
                     expected_revision=None, idempotency_key=None, _commit=True, _authorized=False):
    """LINEAR version navigation: make an older revision the new HEAD by appending a NEW revision
    COPIED from `from_revision` (provenance base_revision=from_revision), clearing the approved
    pointer and returning the slot to its review status for re-review. Revisions stay immutable
    (append-only, no tree). A new comment then reworks from this head. Audited.

    #313 per-item governance guards (parity with edit_revision):
      - idempotency_key (topic only): a replay returns the ORIGINAL restored revision, no second write;
      - eligibility: fails closed with GovernedDenial on an approved/downstream-advanced item (#249 unconsumed);
      - expected_revision: optimistic-concurrency CAS against the current head (409 on stale), with the
        (slot_id,revision) unique index as the race backstop."""
    cfg = cfg or load_config()
    if artifact not in ("topic", "script"):
        raise GateError("artifact must be 'topic' or 'script'")
    if idempotency_key is not None and artifact != "topic":
        raise GateError("idempotency_key is supported only for topic restores (#313 Topic-only scope)")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #321 P1.1 — the canonical slot lock is taken FIRST (re-entrant when begin already holds it),
    # before authority, idempotency, eligibility and CAS, so every mutable authorization input is read
    # under the lock. begin_rework_operation authorized under its own held lock and passes _authorized.
    # Any denial or idempotent-replay early return rolls back to release the lock (no write occurred).
    cur.execute("SELECT 1 FROM slot WHERE slot_id=%s FOR UPDATE", (slot_id,))
    try:
        # Authority UNDER the lock, before the idempotency replay — an unauthorized principal can never
        # replay a known key to receive the restored revision without current command authority.
        if not _authorized:
            _authorize_topic_item_mutation(cur, slot_id, artifact, actor, cfg)
        if idempotency_key is not None:
            cur.execute("SELECT revision FROM topic WHERE slot_id=%s AND idempotency_key=%s",
                        (slot_id, idempotency_key))
            prior = cur.fetchone()
            if prior:
                conn.rollback(); cur.close()
                return {"slot_id": slot_id, "artifact": artifact, "from_revision": from_revision,
                        "new_revision": prior["revision"], "idempotent_replay": True}
        cur.execute(f"SELECT * FROM {artifact} WHERE slot_id=%s AND revision=%s", (slot_id, from_revision))
        src = cur.fetchone()
        if not src:
            raise GateError(f"no {artifact} revision {from_revision} for {slot_id}")
        # #313 B1 — restore-as-new-revision reopens the item into review; a mutation, so an approved/
        # downstream-advanced item is fail-closed to a typed GovernedDenial (#249 unimplemented). An
        # in-review / dropped item has no approval pin and no downstream script, so it passes.
        _topic_item_mutation_eligibility(cur, slot_id, artifact)
        head = _head_revision(cur, slot_id, artifact)
        if expected_revision is not None and int(expected_revision) != int(head):
            raise RevisionConflict(
                f"stale expected_revision {expected_revision} for {slot_id} (current head is {head})",
                current=head)
    except GateError:
        conn.rollback(); cur.close(); raise
    new_rev = head + 1
    note = f"restored from v{from_revision}"
    try:
        if artifact == "topic":
            cur.execute(
                """INSERT INTO topic (slot_id, hcs_id, lens, round_id, cycle_no, text_ar, text_en,
                       rationale_ar, rationale_en, hook_text, hook_type, revision, feedback,
                       change_summary_ar, change_summary_en, base_revision, embedding, tenant_id,
                       idempotency_key)
                   SELECT slot_id, hcs_id, lens, round_id, cycle_no, text_ar, text_en,
                       rationale_ar, rationale_en, hook_text, hook_type, %s, %s, NULL, NULL, %s,
                       embedding, tenant_id, %s
                   FROM topic WHERE slot_id=%s AND revision=%s""",
                (new_rev, note, from_revision, idempotency_key, slot_id, from_revision))
            cur.execute("UPDATE slot SET topic_angle=%s, hook_text=%s, hook_type=%s WHERE slot_id=%s",
                        (src["text_ar"], src["hook_text"], src["hook_type"], slot_id))
        else:
            cur.execute(
                """INSERT INTO script (slot_id, hcs_id, lens, script_ar, structure, final_line,
                       delivery_notes, delivery_check, used_islamic_anchor, needs_scholar_review,
                       needs_native_review, flags, model, revision, feedback, change_summary_ar,
                       change_summary_en, base_revision, tenant_id)
                   SELECT slot_id, hcs_id, lens, script_ar, structure, final_line, delivery_notes,
                       delivery_check, used_islamic_anchor, needs_scholar_review, needs_native_review,
                       flags, model, %s, %s, NULL, NULL, %s, tenant_id
                   FROM script WHERE slot_id=%s AND revision=%s""",
                (new_rev, note, from_revision, slot_id, from_revision))
    except psycopg2.errors.UniqueViolation as e:
        conn.rollback(); cur.close()
        raise RevisionConflict(
            f"concurrent revision for {slot_id} (head advanced past {head})", current=head) from e
    review_status = _review_status_for_artifact(cfg, artifact)
    cur.execute("UPDATE slot SET status=%s, updated_at=now() WHERE slot_id=%s", (review_status, slot_id))
    cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact=%s", (slot_id, artifact))
    _audit(cur, "slot", slot_id, "revision_restored", actor,
           {"artifact": artifact, "from_revision": from_revision, "new_revision": new_rev,
            "to_status": review_status})
    # #321 P1.4 — the head advanced; recompute any open-gate coverage (decisions/history untouched).
    _reproject_open_gate_coverage(cur, cfg, slot_id, artifact)
    # #313 P1-B — begin_rework_operation restores WITHOUT committing so the restore + the operation row
    # are one atomic transaction (no orphan restored revision without a durable operation owner).
    if _commit:
        conn.commit()
    cur.close()
    return {"slot_id": slot_id, "artifact": artifact, "from_revision": from_revision,
            "new_revision": new_rev, "status": review_status}


# --------------------------------------------------------------------------- #
# #313 P1-B — durable rework OPERATION state machine (crash / replay / concurrency safe)
# --------------------------------------------------------------------------- #
_REWORK_LEASE_SECONDS = int(os.environ.get("TANAGHOM_REWORK_LEASE_SECONDS", "120"))


def _resolve_rework_lease_seconds():
    """#313 review #5 — the runtime-resolved rework lease, read at CALL time (not frozen at import).
    Claim, heartbeat renewal, AND the heartbeat interval default all resolve through this one function,
    so they can never skew: a short lease injected into the environment after import governs the beat
    cadence too, keeping renewal ahead of expiry instead of leaving the interval pinned to the 120s
    import-time default."""
    return int(os.environ.get("TANAGHOM_REWORK_LEASE_SECONDS", _REWORK_LEASE_SECONDS))


def begin_rework_operation(conn, slot_id, base_revision, comment, actor, idempotency_key,
                           expected_revision=None, artifact="topic", cfg=None):
    """#313 P1-B — atomically OWN a restore+rework operation. Under a slot lock, in ONE transaction:
    resolve the idempotency identity (slot_id, idempotency_key), and for a NEW key perform the restore
    (append a revision) AND record the durable operation row (state=queued) TOGETHER — so a crash can
    never leave a restored revision without a durable owner. A replay returns:
      - action='dedupe'          : the operation already COMPLETED (its generated revision exists);
      - action='dedupe_inflight' : it is RUNNING under a live lease (another worker owns it);
      - action='resume'          : queued/failed/lease-expired — re-drive the generation;
      - action='start'           : a fresh operation was created; drive the generation.
    Raises RevisionConflict (stale CAS) / GovernedDenial (approved/downstream, #249) only for a NEW op."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT 1 FROM slot WHERE slot_id=%s FOR UPDATE", (slot_id,))
    if not cur.fetchone():
        cur.close()
        raise GateError(f"no slot {slot_id}")
    # #321 R4 — rework is a per-item mutation; enforce the SAME canonical stage-assignment authority
    # under the held slot lock, BEFORE the idempotency branch, so an unauthorized actor cannot even
    # probe or resume an operation. Fails closed, typed. Not `workflow.admin` (that is #319-only).
    # #321 R3 — a denial here must release the held slot lock (rollback) before propagating.
    try:
        _authorize_topic_item_mutation(cur, slot_id, artifact, actor, cfg)
    except GateError:
        conn.rollback(); cur.close(); raise
    cur.execute("""SELECT op_id, state, restored_revision, generated_revision,
                          (lease_expires_at IS NOT NULL AND lease_expires_at > now()) AS lease_valid
                     FROM rework_operation WHERE slot_id=%s AND idempotency_key=%s""",
                (slot_id, idempotency_key))
    op = cur.fetchone()
    if op:
        cur.close()
        if op["state"] == "completed":
            return {"action": "dedupe", "op_id": str(op["op_id"]),
                    "generated_revision": op["generated_revision"]}
        if op["state"] == "running" and op["lease_valid"]:
            return {"action": "dedupe_inflight", "op_id": str(op["op_id"])}
        return {"action": "resume", "op_id": str(op["op_id"]),
                "restored_revision": op["restored_revision"]}
    cur.close()
    # NEW op — restore WITHOUT committing (atomic with the op insert), then record the durable op.
    r = restore_revision(conn, slot_id, artifact, base_revision, actor=actor, cfg=cfg,
                         expected_revision=expected_revision, _commit=False, _authorized=True)
    restored = r["new_revision"]
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""INSERT INTO rework_operation (slot_id, idempotency_key, artifact, base_revision,
                       restored_revision, comment, actor, state)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'queued') RETURNING op_id""",
                (slot_id, idempotency_key, artifact, base_revision, restored, comment, actor))
    op_id = cur.fetchone()["op_id"]
    # #321 N1 — immutable lifecycle event: the operation was created (attributable to its actor).
    _audit(cur, "rework_operation", op_id, "rework_started", actor,
           {"controller": actor, "op_id": str(op_id), "slot_id": slot_id, "artifact": artifact,
            "base_revision": base_revision, "restored_revision": restored})
    conn.commit()
    cur.close()
    return {"action": "start", "op_id": str(op_id), "restored_revision": restored}


def claim_rework_operation(conn, op_id, lease_seconds=None, controller="system"):
    """#313 P1-B — atomically CLAIM an operation for this worker: queued/failed/lease-expired -> running
    with a fresh lease AND a fresh `claim_token` (the exclusive ownership handle for this tenure), EXACTLY
    ONCE. Returns the claimed row (carrying claim_token), or None (already completed, or running under a
    live lease held by another worker). A set generated_revision means done — never re-driven.
    #321 N1 — on a durable ownership acquisition, emits `rework_reclaimed` (prior state was a
    lease-expired `running`) or `rework_claimed` (from `queued`/`failed`). A claim that matches zero
    rows (already owned/done) emits nothing."""
    lease_seconds = lease_seconds or _resolve_rework_lease_seconds()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT state FROM rework_operation WHERE op_id=%s", (op_id,))
    _prior = cur.fetchone()
    cur.execute("""UPDATE rework_operation
                     SET state='running', claim_token=gen_random_uuid(),
                         lease_expires_at=now() + make_interval(secs => %s),
                         heartbeat_at=now(), updated_at=now()
                   WHERE op_id=%s AND generated_revision IS NULL
                     AND (state IN ('queued','failed')
                          OR (state='running' AND (lease_expires_at IS NULL OR lease_expires_at < now())))
                   RETURNING *""", (lease_seconds, op_id))
    row = cur.fetchone()
    if row:
        _reclaimed = bool(_prior and _prior["state"] == "running")
        _audit(cur, "rework_operation", op_id,
               "rework_reclaimed" if _reclaimed else "rework_claimed", controller,
               {"controller": controller, "op_id": str(op_id),
                "prior_state": _prior["state"] if _prior else None, "lease_seconds": lease_seconds})
    conn.commit()
    cur.close()
    return row


def heartbeat_rework_operation(conn, op_id, claim_token, lease_seconds=None):
    """#313 P1-1 — renew the lease for THIS owner (fenced by claim_token) so a generation that runs
    longer than the nominal lease is never wrongly reclaimed. Returns True while this worker still owns
    the op; False once ownership has transferred (a new claim minted a new token) or it completed — the
    caller must then stop, because it no longer owns the work."""
    lease_seconds = lease_seconds or _resolve_rework_lease_seconds()
    cur = conn.cursor()
    cur.execute("""UPDATE rework_operation
                     SET lease_expires_at=now() + make_interval(secs => %s), heartbeat_at=now(), updated_at=now()
                   WHERE op_id=%s AND claim_token=%s AND generated_revision IS NULL""",
                (lease_seconds, op_id, claim_token))
    owns = cur.rowcount == 1
    conn.commit()
    cur.close()
    return owns


def complete_rework_operation(cur, op_id, claim_token, generated_revision, controller="system"):
    """#313 P1-B/P1-1 — mark the operation COMPLETED with its generated revision, FENCED by claim_token.
    Called from the writer's on-persist hook, so it commits in the SAME transaction as the generated
    topic revision + provenance. If ownership has transferred (token stale), this matches ZERO rows and
    RAISES — rolling back the stale worker's generation transaction, so a reassigned/duplicate worker
    can neither complete nor leave a duplicate revision. Exactly-once by construction.
    #321 N1 — on the successful completion it appends an immutable `rework_completed` event in the SAME
    atomic transaction as the revision+provenance+completion; a rejected (stale) completion RAISES
    before the event, so no false completion is ever recorded."""
    cur.execute("""UPDATE rework_operation SET state='completed', generated_revision=%s,
                       error_detail=NULL, updated_at=now() WHERE op_id=%s AND claim_token=%s""",
                (generated_revision, op_id, claim_token))
    if cur.rowcount != 1:
        raise GateError(f"rework operation {op_id} ownership lost (stale claim_token) — completion rejected")
    _audit(cur, "rework_operation", op_id, "rework_completed", controller,
           {"controller": controller, "op_id": str(op_id), "generated_revision": generated_revision})


def fail_rework_operation(conn, op_id, claim_token, error, controller="system"):
    """#313 P1-B/P1-1 — mark a running operation FAILED (resumable), FENCED by claim_token. A stale
    worker (ownership transferred) matches zero rows and cannot flip a reassigned op's state.

    #319 — this COMMITS `conn`, so `conn` must carry NO generation work: a connection whose generation
    transaction is still open would have that transaction committed here, persisting the very effects
    the caller is failing. Callers roll back and hand this a CLEAN connection (see
    run_rework_operation). Returns True iff this caller still owned the operation and the failure was
    recorded; False is the truthful stale-owner outcome (nothing written, nothing claimed)."""
    cur = conn.cursor()
    cur.execute("""UPDATE rework_operation SET state='failed', error_detail=%s, updated_at=now()
                   WHERE op_id=%s AND claim_token=%s AND generated_revision IS NULL
                     AND state <> 'terminated'""",
                (str(error)[:500], op_id, claim_token))
    recorded = cur.rowcount == 1
    if recorded:
        # #321 N1 — immutable failure event, emitted ONLY when this caller actually owned the op and the
        # clean failure state was persisted (a stale/fenced no-op writes nothing, N1 and #319-consistent).
        _audit(cur, "rework_operation", op_id, "rework_failed", controller,
               {"controller": controller, "op_id": str(op_id), "reason": str(error)[:500]})
    conn.commit()
    cur.close()
    return recorded


# --------------------------------------------------------------------------- #
# #319 P0 — governed terminalization of an UNSAFELY STRANDED rework operation.
#
# The rework fence (_topic_mutation_state) derives from "an un-generated operation exists", so an
# operation that can never be re-driven fences its Topic item FOREVER with no governed escape. The
# only such state is an operation whose restored SOURCE no longer is the head: the worker's own
# fail-closed source check (run_writers) rejects it on every recovery attempt, permanently. This
# command is the narrow, audited escape — and NOTHING more.
#
# What it may do: move ONE operation to ONE terminal state, releasing that operation's derived fence,
# and append ONE immutable audit row. What it may NOT do: create or select a Topic revision, alter
# provenance, mutate approval/downstream state, or confer #249 reconsideration authority. It writes
# exactly two things: rework_operation's own state fields, and audit_log.
# --------------------------------------------------------------------------- #
REWORK_TERMINAL_STATE = "terminated"          # the ONE allowed terminal failure state (#319)
REWORK_TERMINALIZE_ACTION = "rework_operation_terminated"   # the immutable audit action / replay key
REWORK_TERMINALIZE_PERMISSION = "workflow.admin"            # the ONE existing named authority (#319)


def rework_operation_token(row):
    """#319 — the operation's CANONICAL expected-state token: an opaque, deterministic digest of the
    operation identity a terminalization request believes it is acting on.

    Deterministic and canonical BY CONSTRUCTION: one function derives it, the governed read/API
    contract exposes what it computes, and terminalization revalidates it by calling this same
    function on the row it holds under lock. A client never reconstructs it — it echoes back the token
    the read gave it — so the token cannot skew between reader and writer the way two independently
    formatted strings would.

    It covers exactly the fields that decide eligibility (state, ownership tenure, completion). Any
    transition — a reclaim minting a new claim_token, a completion, a failure — changes `updated_at`
    and therefore the token, so a request formed against a stale view is rejected rather than applied
    to an operation that has moved on. This is #292's combined-token discipline, with no schema
    change: the operation's own durable columns ARE the version."""
    canonical = "|".join((
        str(row["op_id"]),
        str(row["state"]),
        "" if row["generated_revision"] is None else str(row["generated_revision"]),
        "" if row["claim_token"] is None else str(row["claim_token"]),
        row["updated_at"].isoformat(),
    ))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def can_terminalize_rework_operation(cur, principal_id):
    """#319 — authority to terminalize a stranded rework operation: the EXISTING named permission
    `workflow.admin`, held EXPLICITLY by the principal. Nothing else.

    Deliberately NOT a call to actors._has_permission: that helper answers True for everyone while
    `require_permission` is unseeded (a read-but-don't-enforce ramp), which is a sane default for
    advisory checks and an unacceptable one for a fence-releasing command. This check is fail-closed
    unconditionally.

    Role membership does NOT confer it. `principal_role` carries no permissions column, so a role name
    cannot PROVE the holder has `workflow.admin` — inferring authority from `admin`/`workflow_admin`
    would invent authority rather than bind to the existing one. Neither `workflow.assign` nor
    `config.write` is accepted: they are different authorities that happen to co-occur in the broader
    approval-policy predicate. Every principal that passes here already holds strictly greater
    authority today (approval-policy administration), so this is a narrowing, not a broadening."""
    principal = actors.load_principal(cur, principal_id)
    if not principal or principal.get("kind") != "user":
        return False
    return REWORK_TERMINALIZE_PERMISSION in set(principal.get("permissions") or [])


def _rework_terminalization_replay(cur, op_id, idempotency_key):
    """#319 — resolve a terminalization replay from the APPEND-ONLY audit trail, which is the durable
    idempotency record (no schema change: the audit row IS the receipt). Returns the original terminal
    result for a same-key replay, or None. A DIFFERENT key against an already-terminal operation is
    NOT a replay — it is a distinct request arriving too late, and the caller denies it typed, so a
    second actor can never silently inherit the first actor's terminalization as if it were their
    own."""
    cur.execute("""SELECT detail FROM audit_log
                    WHERE entity='rework_operation' AND entity_id=%s AND action=%s
                      AND detail->>'idempotency_key'=%s
                    ORDER BY id LIMIT 1""",
                (str(op_id), REWORK_TERMINALIZE_ACTION, idempotency_key))
    row = cur.fetchone()
    if not row:
        return None
    d = row["detail"]
    return {"op_id": str(op_id), "state": REWORK_TERMINAL_STATE, "terminalized": True,
            "idempotent_replay": True, "reason": d.get("reason"), "actor": d.get("actor")}


def terminalize_rework_operation(conn, op_id, principal_id, expected_op_token, idempotency_key,
                                 reason):
    """#319 P0 — governed terminalization of an UNSAFELY STRANDED rework operation: the ONLY escape
    from a fence that recovery can never clear. Fail-closed, server-side, and audited.

    EVERY step — eligibility, expected-token validation, idempotency lookup, the state transition, and
    the audit append — is serialized under ONE durable lock (the slot row, then the operation row) in
    ONE transaction. That is what makes the zero-migration design sound: the token is validated and
    consumed while the row that produced it is held, so a concurrent claim cannot interleave between
    the check and the write. Lock order (slot, then operation) matches begin_rework_operation, so the
    two can never deadlock against each other.

    ELIGIBLE iff ALL hold — an operation that is genuinely, permanently unre-drivable:
      state='failed' AND generated_revision IS NULL AND the lease has expired AND head != restored.
    That last clause IS the strandedness: the worker's own fail-closed source check rejects such an
    operation on every recovery attempt forever (run_rework_operation), so no winner can ever exist.

    TYPED DENIALS (GovernedDenial.reason), never silent: unauthorized, not_stranded, active_owner,
    recoverable, stale_token, already_terminalized.

    EFFECTS — exactly two tables, by construction: rework_operation's own state fields, and one
    immutable audit_log row. It cannot create/select a revision, touch provenance, or mutate
    approval/downstream state, and it confers NO #249 reconsideration authority: releasing the fence
    returns the item to the SAME governed state it would have had if the rework had never started —
    an approved or downstream-advanced item stays denied by its own #249 guard, untouched here."""
    if not (reason or "").strip():
        raise GateError("terminalization needs a reason (the durable justification)")
    if not idempotency_key:
        raise GateError("terminalization needs an idempotency_key")
    if not expected_op_token:
        raise GateError("terminalization needs an expected_op_token (the operation state it expects)")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Authority FIRST, before any lock: an unauthorized caller must not even serialize against
        # governed work, and the denial audit must not race a lock it never should have taken.
        if not can_terminalize_rework_operation(cur, principal_id):
            conn.rollback()
            audit_denied(conn, "rework_operation", op_id, "rework_terminalization_denied", principal_id,
                         {"reason": "unauthorized",
                          "required_permission": REWORK_TERMINALIZE_PERMISSION})
            raise GovernedDenial(
                f"terminalizing rework operation {op_id} requires the "
                f"{REWORK_TERMINALIZE_PERMISSION} permission", reason="unauthorized")
        cur.execute("SELECT slot_id FROM rework_operation WHERE op_id=%s", (op_id,))
        head_row = cur.fetchone()
        if not head_row:
            raise GateError(f"no rework operation {op_id}")
        # Lock the SLOT first (begin_rework_operation's order), then the OPERATION row. Holding the
        # operation row blocks a concurrent claim_rework_operation UPDATE until this commits — so a
        # reclaim either wins outright (and we deny `recoverable`) or finds a terminal state it cannot
        # claim. There is no window between eligibility and transition.
        cur.execute("SELECT 1 FROM slot WHERE slot_id=%s FOR UPDATE", (head_row["slot_id"],))
        cur.execute("""SELECT op_id, slot_id, state, restored_revision, generated_revision,
                              claim_token, updated_at,
                              (lease_expires_at IS NOT NULL AND lease_expires_at > now()) AS lease_valid
                         FROM rework_operation WHERE op_id=%s FOR UPDATE""", (op_id,))
        op = cur.fetchone()
        # Idempotency is resolved UNDER THE LOCK, so a same-key replay racing the original blocks
        # until it commits and then observes the receipt — never a second transition or audit row.
        replay = _rework_terminalization_replay(cur, op_id, idempotency_key)
        if replay:
            conn.commit()
            return replay
        if op["state"] == REWORK_TERMINAL_STATE:
            raise GovernedDenial(
                f"rework operation {op_id} is already terminalized under a different idempotency key",
                reason="already_terminalized")
        # The token is validated against the row held UNDER LOCK, so it reflects the state this
        # transition will actually apply to — not a state that has since moved on.
        actual_token = rework_operation_token(op)
        if expected_op_token != actual_token:
            raise GovernedDenial(
                f"rework operation {op_id} changed since it was read "
                f"(expected {expected_op_token}, current {actual_token}) — re-read and retry",
                reason="stale_token")
        if op["generated_revision"] is not None or op["state"] == "completed":
            raise GovernedDenial(
                f"rework operation {op_id} completed — it is not stranded", reason="not_stranded")
        if op["state"] == "running" and op["lease_valid"]:
            raise GovernedDenial(
                f"rework operation {op_id} is running under a live lease — a worker still owns it",
                reason="active_owner")
        if op["state"] != "failed":
            raise GovernedDenial(
                f"rework operation {op_id} is {op['state']} — recovery will re-drive it",
                reason="recoverable")
        cur.execute("SELECT coalesce(max(revision),0) AS head FROM topic WHERE slot_id=%s",
                    (op["slot_id"],))
        head = cur.fetchone()["head"]
        if head == op["restored_revision"]:
            raise GovernedDenial(
                f"rework operation {op_id} can still be re-driven from its restored source "
                f"(head {head}) — recovery must run before terminalization",
                reason="recoverable")
        # The ONE allowed transition. `generated_revision` stays NULL and is never written: that it
        # produced no revision is the truth, and the terminal state must not pretend otherwise.
        cur.execute("""UPDATE rework_operation
                          SET state=%s, error_detail=%s, updated_at=now()
                        WHERE op_id=%s AND state='failed' AND generated_revision IS NULL""",
                    (REWORK_TERMINAL_STATE, f"terminalized: {reason.strip()}"[:500], op_id))
        if cur.rowcount != 1:
            raise GateError(f"rework operation {op_id} changed under lock — terminalization rejected")
        _audit(cur, "rework_operation", op_id, REWORK_TERMINALIZE_ACTION, principal_id,
               {"reason": reason.strip(), "actor": principal_id,
                "authority": REWORK_TERMINALIZE_PERMISSION,
                "idempotency_key": idempotency_key,
                "slot_id": op["slot_id"], "from_state": op["state"],
                "to_state": REWORK_TERMINAL_STATE,
                "restored_revision": op["restored_revision"], "head_revision": head,
                "generated_revision": None,
                "stranded_because": "restored source is no longer head — no recovery can win",
                "fence_released": "rework_active",
                "confers_reconsideration": False})
        conn.commit()
        return {"op_id": str(op_id), "state": REWORK_TERMINAL_STATE, "terminalized": True,
                "idempotent_replay": False, "reason": reason.strip(), "actor": principal_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def stranded_rework_operation(conn, op_id):
    """#319 — the governed READ that exposes an operation's canonical expected-state token and whether
    it is terminalization-eligible. The token a client sends back MUST come from here: one function
    (rework_operation_token) computes it for both the read and the write, so client and server can
    never derive it differently."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT op_id, slot_id, state, restored_revision, generated_revision,
                              claim_token, updated_at,
                              (lease_expires_at IS NOT NULL AND lease_expires_at > now()) AS lease_valid
                         FROM rework_operation WHERE op_id=%s""", (op_id,))
        op = cur.fetchone()
        if not op:
            raise GateError(f"no rework operation {op_id}")
        cur.execute("SELECT coalesce(max(revision),0) AS head FROM topic WHERE slot_id=%s",
                    (op["slot_id"],))
        head = cur.fetchone()["head"]
        stranded = (op["state"] == "failed" and op["generated_revision"] is None
                    and not op["lease_valid"] and head != op["restored_revision"])
        return {"op_id": str(op["op_id"]), "slot_id": op["slot_id"], "state": op["state"],
                "restored_revision": op["restored_revision"], "head_revision": head,
                "generated_revision": op["generated_revision"],
                "lease_valid": op["lease_valid"],
                "terminalization_eligible": stranded,
                "expected_op_token": rework_operation_token(op)}
    finally:
        cur.close()


def recoverable_rework_operations(conn, limit=None):
    """#313 P1-B — the operations a recovery drain must re-drive: queued/failed, or running with an
    EXPIRED lease (a worker died mid-generation). Completed operations are never re-driven.
    #319 — a TERMINALIZED operation is never re-driven either: it is terminal by governed decision,
    and its `state` excludes it from the queued/failed set below with no extra predicate.
    #321 R6 — `limit` bounds a single periodic drain pass to at most N oldest-eligible operations
    (deterministic order), so the bounded owner never fans out unboundedly; None keeps the full set for
    the opportunistic per-request path. This SELECTs only eligible ops — it never terminalizes."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = """SELECT op_id::text AS op_id FROM rework_operation
              WHERE generated_revision IS NULL
                AND (state IN ('queued','failed')
                     OR (state='running' AND (lease_expires_at IS NULL OR lease_expires_at < now())))
              ORDER BY created_at, op_id"""
    params = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (int(limit),)
    cur.execute(sql, params)
    ops = [r["op_id"] for r in cur.fetchall()]
    cur.close()
    return ops


# --------------------------------------------------------------------------- #
# #14 Phase 1 — safe inline edit of a plain-text generated field. Appends a NEW revision (COPIED from
# head with one whitelisted text field overridden) so history stays append-only and auditable — the
# SAME discipline as restore_revision/rework, never an in-place mutation. STRUCTURAL fields
# (pillar/format/framework/hook_type/…) are deliberately NOT editable here: changing them can require
# dependent-content cascade/regeneration, which is #51. This never resets status or clears approvals, so
# review counts stay stable; the edit affordance is only offered on in-review items.
# --------------------------------------------------------------------------- #
# Whitelisted plain-text, non-structural fields that may be manually inline-edited, per artifact.
# topic fields are denormalized to slot; script fields are read from the head revision (lateral join),
# so scripts need no slot mirror. Structural/metadata fields stay rejected (deferred to #51).
_SAFE_EDIT_FIELDS = {"topic": ("hook_text", "text_ar"), "script": ("script_ar", "final_line")}
_TOPIC_COPY_COLS = ["slot_id", "hcs_id", "lens", "round_id", "cycle_no", "text_ar", "text_en",
                    "rationale_ar", "rationale_en", "hook_text", "hook_type", "embedding", "tenant_id"]
_SCRIPT_COPY_COLS = ["slot_id", "hcs_id", "lens", "script_ar", "structure", "final_line", "delivery_notes",
                     "delivery_check", "used_islamic_anchor", "needs_scholar_review", "needs_native_review",
                     "flags", "model", "tenant_id"]
_ARTIFACT_COPY_COLS = {"topic": _TOPIC_COPY_COLS, "script": _SCRIPT_COPY_COLS}
# Columns force-overridden (not copied forward) on a manual edit. A human edit to a script re-opens the
# language + religious sign-offs (#66 option-c safety marker) — these flags drive the script_review →
# native_review / scholar_review routing, so a re-review is required, not silently inherited. This is an
# explicit safety re-flag, NOT a recomputation of the checks themselves.
_ARTIFACT_EDIT_FORCE = {"script": {"needs_scholar_review": True, "needs_native_review": True}}


def _topic_item_state(cur, slot_id, artifact="topic"):
    """#313 — the governance-relevant state of one per-item artifact: current slot status, whether an
    approval pin exists, and whether a downstream artifact has advanced past it. Read-only; the single
    source both the mutation guard and the typed-actions read model derive from (no divergence)."""
    cur.execute("SELECT status FROM slot WHERE slot_id=%s", (slot_id,))
    row = cur.fetchone()
    if not row:
        return None
    status = row["status"] if isinstance(row, dict) else row[0]
    cur.execute("SELECT 1 FROM slot_approval WHERE slot_id=%s AND artifact=%s", (slot_id, artifact))
    approved = cur.fetchone() is not None
    downstream = False
    if artifact == "topic":
        cur.execute("SELECT 1 FROM script WHERE slot_id=%s LIMIT 1", (slot_id,))
        downstream = cur.fetchone() is not None
    # #367 — an ACTIVE (un-generated, non-terminal) rework OF THIS ARTIFACT owns the item. Scoped by
    # artifact so a script mutation is fenced by an active SCRIPT rework and a topic mutation by an
    # active TOPIC rework — Topic behaviour is unchanged (topic reworks store artifact='topic'). This
    # state feeds BOTH the mutation guard and the typed action map, so the surface never offers an
    # action the command will refuse.
    cur.execute("SELECT 1 FROM rework_operation WHERE slot_id=%s AND artifact=%s "
                "AND generated_revision IS NULL AND state <> %s LIMIT 1",
                (slot_id, artifact, REWORK_TERMINAL_STATE))
    rework_active = cur.fetchone() is not None
    return {"status": status, "approved": approved, "downstream_advanced": downstream,
            "rework_active": rework_active}


def _topic_item_denied_reason(state):
    """The single reason a per-item MUTATION is fail-closed (approved / downstream-advanced), else None.
    Both are #249-reconsideration territory that is not implemented, so mutation is denied, never reopened."""
    if state["approved"]:
        return "approved"
    if state["downstream_advanced"]:
        return "downstream_advanced"
    # #367 — a live rework owns the item: fenced until it completes/terminalizes. Projected here so the
    # typed action map denies edit/rework/drop/restore while a rework runs, matching the guard.
    if state.get("rework_active"):
        return "rework_active"
    return None


def _topic_item_mutation_eligibility(cur, slot_id, artifact="topic"):
    """#313 B1 — a per-item Topic MUTATION (structured edit, rework, restore-into-review, drop) is
    permitted only while the item is in review. If it is already approved, or a downstream artifact has
    advanced past it, reopening it would require governed reconsideration authority — #249, which is
    `directive:pending`/unimplemented. So raise a typed GovernedDenial and leave #249 UNCONSUMED, never
    a bare reopen. Returns the state on success."""
    state = _topic_item_state(cur, slot_id, artifact)
    if state is None:
        raise GateError(f"no slot {slot_id}")
    reason = _topic_item_denied_reason(state)
    if reason == "approved":
        raise GovernedDenial(
            f"{artifact} for {slot_id} is approved — reopening it requires governed reconsideration "
            f"(#249), which is not available", reason="approved")
    if reason == "downstream_advanced":
        raise GovernedDenial(
            f"topic for {slot_id} has a downstream script — reopening requires governed reconsideration "
            f"(#249), which is not available", reason="downstream_advanced")
    # #313 P1-2 — an ACTIVE rework operation (un-generated) OWNS the item: a competing edit/restore/
    # rework/decision is fail-closed while it runs, so a concurrent mutation can never silently change
    # the rework's restored SOURCE revision from under the worker. It clears the moment the rework
    # completes (generated_revision set).
    # #319 — and it clears on governed TERMINALIZATION, the only other way out. A `failed` operation
    # still fences (it is genuinely resumable, and a competing mutation would change the restored
    # source under the worker that reclaims it — the exact P1-2 hazard). Only the terminal state is
    # excluded, so the escape is bounded to operations a human explicitly, authorizedly ended. Before
    # #319 this predicate keyed on generated_revision ALONE and ignored `state`, so an operation that
    # recovery could never re-drive fenced its item forever with no governed escape.
    # #367 — derive the rework-active fence from the SAME state the action map uses, ARTIFACT-SCOPED
    # (was topic-only and unfiltered). A competing edit/restore/rework/decision is fail-closed while a
    # rework of this artifact runs, so a concurrent mutation can never change the rework's restored
    # SOURCE revision under the worker. Clears when the rework completes (generated_revision set) or is
    # governed-terminalized. Topic behaviour is unchanged.
    if state.get("rework_active"):
        raise GovernedDenial(
            f"{artifact} for {slot_id} has a rework in progress — the item is fenced until it completes",
            reason="rework_active")
    return state


# ---------------------------------------------------------------------------------------------------
# #373 — recovery-action representability. Two governed recovery paths that #372's browser preflight
# proved were backend-capable but unrepresentable in the V2 per-item read model:
#   `reopen`   — reverse a COMMITTED decision (un-reject a dropped item / un-approve). A DISTINCT
#                canonical action from `restore` (=restore_revision, version navigation); the surface
#                label must map 1:1 to reopen and must NOT overload restore_revision (Codex ruling 1).
#   `undecide` — PRE-commit clear of the caller's recorded decision, addressed by an EXACT gate id.
# Both reuse the existing canonical endpoints/engine functions; this only PROJECTS their typed
# availability (and, for undecide, the single authoritative gate id) so the surface never offers what
# the command would refuse. Additive, migration-free, V2-only (topic_item is not read by V1).

def _authoritative_open_gate(cur, slot_id, stage):
    """#373 (Codex ruling 2) — the EXACT open gate for (slot, stage), authoritative ONLY when exactly
    one exists. Returns (gate_id_or_None, count). Zero OR multiple -> None: the client never chooses,
    sorts, or falls back among gates; ambiguity is surfaced as a typed-unavailable action instead.
    (One open gate per (round,stage) is the maintained invariant — advisory-lock serialisation +
    _active_open_gate supersede — so >1 is a defended-against anomaly that still fails closed here.)"""
    if not stage:
        return None, 0
    cur.execute("""SELECT g.gate_id FROM gate g JOIN gate_target t USING (gate_id)
                    WHERE t.slot_id=%s AND g.stage=%s AND g.status='open'""", (slot_id, stage))
    rows = cur.fetchall()
    if len(rows) == 1:
        r = rows[0]
        return (r["gate_id"] if isinstance(r, dict) else r[0]), 1
    return None, len(rows)


def _reopen_action(cur, slot_id, cfg):
    """#373 — typed availability of canonical `reopen`, matching engine.reopen's eligibility EXACTLY so
    the surface never offers what the command refuses: the slot must be in a reversible state (a
    reject/dropped status or a configured approve state) AND a committed decision must exist to reverse.
    Distinct from `restore` (restore_revision); never a semantic alias."""
    cur.execute("SELECT status FROM slot WHERE slot_id=%s", (slot_id,))
    row = cur.fetchone()
    if not row:
        return {"allowed": False, "reason": "no_slot"}
    prior = row["status"] if isinstance(row, dict) else row[0]
    approve_states = {g.get("approve_to") for g in (cfg.get("gates") or {}).values() if g.get("approve_to")}
    if prior not in (reject_statuses(cfg) | approve_states):
        return {"allowed": False, "reason": "nothing_to_reverse"}
    cur.execute("SELECT 1 FROM gate_decision WHERE slot_id=%s LIMIT 1", (slot_id,))
    if not cur.fetchone():
        return {"allowed": False, "reason": "no_decision"}
    return {"allowed": True}


def _undecide_action(cur, slot_id, gate_id, gate_count, actor):
    """#373 (Codex P1) — typed availability of canonical `undecide` (pre-commit clear of a recorded
    decision). undecide clears ONLY the calling principal's decision, so availability is bound to the
    EFFECTIVE TRUSTED PRINCIPAL's own decision — never any approver's. Available ONLY when exactly one
    open gate applies AND THIS actor has an uncommitted decision on it. Zero/multiple gates -> typed
    unavailable; an unsigned reader learns `principal_missing` (matching the projection to what the
    command would actually clear, so the surface can never offer a clear that would delete zero)."""
    if gate_id is None:
        return {"allowed": False, "reason": "ambiguous_gate" if gate_count > 1 else "no_open_gate"}
    if not actor:
        return {"allowed": False, "reason": "principal_missing"}
    cur.execute("SELECT 1 FROM gate_decision WHERE gate_id=%s AND slot_id=%s AND approver_id=%s LIMIT 1",
                (gate_id, slot_id, actor))
    if not cur.fetchone():
        return {"allowed": False, "reason": "no_decision"}
    return {"allowed": True}


def topic_item_actions(cur, slot_id, artifact="topic", cfg=None, actor=None):
    """#313 — the TYPED available/denied per-item action map, derived from the SAME state the mutation
    guard uses (so the surface can never offer an action the command will refuse). Mutations (edit,
    rework, restore, drop) are allowed only in review; approve is offered only while unapproved. inspect
    and history are always available. A denied action carries the machine reason, never a bare hide.
    #373 — additive recovery actions `reopen` (reverse a committed decision) and `undecide` (pre-commit
    clear), each typed from the same durable truth as their commands."""
    state = _topic_item_state(cur, slot_id, artifact)
    if state is None:
        return None
    cfg = cfg or load_config()
    denied = _topic_item_denied_reason(state)

    def mutation():
        return {"allowed": True} if denied is None else {"allowed": False, "reason": denied}

    # #367 — approve is ALSO fenced while a rework of this artifact is active: approving a revision the
    # rework is about to supersede is racy, and the surface must not offer it (backend safety is the
    # stale_revision guard at resolve; this keeps the projection from offering a decision that would be
    # neutralised). already_approved takes precedence when both hold.
    approve = ({"allowed": False, "reason": "already_approved"} if state["approved"]
               else {"allowed": False, "reason": "rework_active"} if state.get("rework_active")
               else {"allowed": True})
    gate_id, gate_count = _authoritative_open_gate(cur, slot_id, _resolve_review_stage(cfg, artifact))
    return {"inspect": {"allowed": True}, "history": {"allowed": True},
            "edit": mutation(), "rework": mutation(), "restore": mutation(),
            "request_change": mutation(), "drop": mutation(), "approve": approve,
            "reopen": _reopen_action(cur, slot_id, cfg),
            "undecide": _undecide_action(cur, slot_id, gate_id, gate_count, actor)}


def topic_item_read_model(conn, slot_id, artifact="topic", actor=None):
    """#313 — ONE server-owned per-item read model: stable slot_id, current status, head + approved
    revision pointers, the immutable append-only revision history (parent/base lineage + provenance +
    which is approved, via list_revisions), the typed available/denied action map, and an explicit
    identity disclosure. Read-only; resolved entirely from durable truth, never inferred client-side.
    Current policy/catalogue values never reinterpret historical revisions (history comes from the
    append-only rows themselves).

    IDENTITY (Codex blocker 4 — surfaced, never silently reinterpreted): `slot_id` is the stable
    per-item identity (Schedule-linked, immutable for the item's life). `topic_id` is minted PER
    REVISION (each revision row has its own — see `revisions[].topic_id`) and is therefore NOT a stable
    cross-revision id. There is no single stable cross-revision topic_id in the shared model; a stable
    head-id would be an ADDITIVE GOVERNED change, deliberately deferred, not silently invented here."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    state = _topic_item_state(cur, slot_id, artifact)
    if state is None:
        cur.close()
        raise GateError(f"no slot {slot_id}")
    head = _head_revision(cur, slot_id, artifact)
    # The ACTUAL approval pin (null when unapproved) — NOT approved_revision(), which falls back to head
    # for downstream reads and would falsely claim an in-review item is approved.
    cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact=%s", (slot_id, artifact))
    _pin = cur.fetchone()
    approved = _pin["revision"] if _pin else None
    cfg = load_config()
    actions = topic_item_actions(cur, slot_id, artifact, cfg, actor)
    # #373 (Codex ruling 2) — the EXACT authoritative gate id `undecide` is addressed to, projected only
    # when exactly one open gate applies (else null -> the surface renders typed-unavailable). The UI
    # consumes this id DIRECTLY: it never derives, sorts, searches, falls back, or chooses among gates.
    _gate_id, _gate_count = _authoritative_open_gate(cur, slot_id, _resolve_review_stage(cfg, artifact))
    cur.close()
    revisions = list_revisions(conn, slot_id, artifact)
    head_row = next((r for r in revisions if r.get("revision") == head), None)
    identity = {
        "stable_key": "slot_id",
        "slot_id": slot_id,
        "head_topic_id": (head_row or {}).get("topic_id"),
        "topic_id_scope": "per_revision",
        "note": ("slot_id is the stable per-item identity; topic_id is minted per revision "
                 "(revisions[].topic_id) and is NOT a stable cross-revision id. A stable head-id "
                 "would be an additive governed change, deferred — not reinterpreted from slot_id."),
    }
    return {"slot_id": slot_id, "artifact": artifact, "status": state["status"],
            "head_revision": head, "approved_revision": approved,
            "downstream_advanced": state["downstream_advanced"],
            "identity": identity,
            "authoritative_gate_id": str(_gate_id) if _gate_id else None,
            "revisions": revisions,
            "actions": actions}


def edit_revision(conn, slot_id, artifact, field, value, actor="system", cfg=None,
                  expected_revision=None, idempotency_key=None):
    """Persist a manual inline edit of a whitelisted plain-text field as a new head revision (append-only,
    provenance base_revision=head, marked 'Manual inline edit' in the change summary). Topic edits update the
    slot's denormalized display fields so the card reflects the edit immediately; script edits are read from
    the head revision (lateral join) so no slot mirror is needed. A manual SCRIPT edit re-opens language +
    religious sign-off (needs_native_review / needs_scholar_review = true) as a safety marker. Returns the
    new revision.

    #313 per-item governance guards:
      - idempotency_key: a replay (double-click/retry) returns the ORIGINAL resulting revision without a
        second revision/audit event (checked first, so a replay after the item advanced is still a no-op).
      - eligibility: fails closed with GovernedDenial on an approved/downstream-advanced item (B1 — never
        silently remains approved under an older decision; #249 stays unconsumed).
      - expected_revision: optimistic-concurrency CAS — a stale expected head raises RevisionConflict (409),
        never a silent overwrite; the DB unique index (slot_id,revision) is the race backstop (B2)."""
    cfg = cfg or load_config()
    cols = _ARTIFACT_COPY_COLS.get(artifact)
    if cols is None:
        raise GateError(f"inline edit is not available for artifact {artifact!r} (topics and scripts only)")
    if field not in _SAFE_EDIT_FIELDS.get(artifact, ()):
        raise GateError(f"field {field!r} is not inline-editable (structural fields are deferred to #51)")
    if not isinstance(value, str) or not value.strip():
        raise GateError("edit value must be non-empty text")
    value = value.strip()
    # #313 — the idempotency_key column exists ONLY on `topic` (mig 029, Topic-only scope). A key on a
    # non-topic artifact fails CLOSED (never silently ignored), so a script edit that supplied one is
    # refused rather than replaying against a missing column. expected_revision (CAS) is schema-free and
    # stays available to both.
    if idempotency_key is not None and artifact != "topic":
        raise GateError("idempotency_key is supported only for topic edits (#313 Topic-only scope)")
    force = _ARTIFACT_EDIT_FORCE.get(artifact, {})
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #321 P1.1 — the canonical slot lock is taken FIRST, before command authority, idempotency,
    # eligibility and CAS, so EVERY mutable authorization input (open-gate / frozen / configured
    # assignment) is read under the lock in the mutation transaction and cannot change before the write.
    # Any denial or idempotent-replay early return rolls back to release the lock (no write occurred).
    cur.execute("SELECT 1 FROM slot WHERE slot_id=%s FOR UPDATE", (slot_id,))
    try:
        # Authority UNDER the lock, before the idempotency replay — so an unauthorized principal can
        # never replay a known key to receive the resulting revision without current command authority.
        _authorize_topic_item_mutation(cur, slot_id, artifact, actor, cfg)
        # Idempotency AFTER authority: a genuine (authorized) replay returns the original revision with
        # no second write / audit / eligibility re-check; an unauthorized replay was already denied above.
        if idempotency_key is not None:
            cur.execute(f"SELECT revision FROM {artifact} WHERE slot_id=%s AND idempotency_key=%s",
                        (slot_id, idempotency_key))
            prior = cur.fetchone()
            if prior:
                conn.rollback(); cur.close()
                return {"slot_id": slot_id, "artifact": artifact, "field": field,
                        "new_revision": prior["revision"], "idempotent_replay": True, **force}
        _topic_item_mutation_eligibility(cur, slot_id, artifact)
        cur.execute(f"SELECT max(revision) AS r FROM {artifact} WHERE slot_id=%s", (slot_id,))
        row = cur.fetchone()
        head = row and row["r"]
        if not head:
            raise GateError(f"no {artifact} revision for {slot_id}")
        if expected_revision is not None and int(expected_revision) != int(head):
            raise RevisionConflict(
                f"stale expected_revision {expected_revision} for {slot_id} (current head is {head})",
                current=head)
    except GateError:
        conn.rollback(); cur.close(); raise
    new_rev = head + 1
    select_exprs, params = [], []
    for col in cols:
        if col == field:
            select_exprs.append("%s"); params.append(value)
        elif col in force:
            select_exprs.append("%s"); params.append(force[col])
        else:
            select_exprs.append(col)
    # idempotency_key is a Topic-only column (#313 mig 029); scripts keep the original INSERT shape.
    idem_col = ", idempotency_key" if artifact == "topic" else ""
    idem_sel = ", %s" if artifact == "topic" else ""
    sql = (f"INSERT INTO {artifact} ({', '.join(cols)}, revision, feedback, "
           f"change_summary_ar, change_summary_en, base_revision{idem_col}) "
           f"SELECT {', '.join(select_exprs)}, %s, NULL, %s, %s, %s{idem_sel} "
           f"FROM {artifact} WHERE slot_id=%s AND revision=%s")
    params += [new_rev, "تعديل يدوي مباشر", "Manual inline edit", head]
    if artifact == "topic":
        params.append(idempotency_key)
    params += [slot_id, head]
    try:
        cur.execute(sql, params)
    except psycopg2.errors.UniqueViolation as e:
        conn.rollback(); cur.close()
        # Lost the (slot_id,revision) race, or a concurrent replay of the same idempotency_key committed
        # first — both are a stale-head condition; the caller refreshes and retries. Never a double-write.
        raise RevisionConflict(
            f"concurrent revision for {slot_id} (head advanced past {head})", current=head) from e
    if artifact == "topic" and field == "hook_text":
        cur.execute("UPDATE slot SET hook_text=%s, updated_at=now() WHERE slot_id=%s", (value, slot_id))
    elif artifact == "topic" and field == "text_ar":
        cur.execute("UPDATE slot SET topic_angle=%s, updated_at=now() WHERE slot_id=%s", (value, slot_id))
    _audit(cur, "slot", slot_id, "revision_edited", actor,
           {"artifact": artifact, "field": field, "new_revision": new_rev,
            **({"idempotency_key": idempotency_key} if idempotency_key else {}),
            **({"reopened_signoff": sorted(force)} if force else {})})
    # #321 P1.4 — the head advanced; recompute any open-gate coverage so a now-superseded approval
    # stops being presented/audited as current coverage. Decisions and history are untouched.
    _reproject_open_gate_coverage(cur, cfg, slot_id, artifact)
    conn.commit(); cur.close()
    return {"slot_id": slot_id, "artifact": artifact, "field": field, "new_revision": new_rev, **force}


# --------------------------------------------------------------------------- #
# Reversible decisions ("git for content") — nothing is destroyed; reverse the pointer
# --------------------------------------------------------------------------- #
def reopen(conn, slot_id, actor="system", cfg=None):
    """Reverse a COMMITTED decision: move a REJECTED (dropped) or just-approved slot BACK to its
    review status for re-review, and clear the approved pin. The audit trail remains append-only;
    any current decision pointers for the latest gate are removed so the reopened slot is fully
    pending again in the active review surface. The return point is the review of the slot's
    latest committed decision."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT status FROM slot WHERE slot_id=%s", (slot_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); raise GateError(f"no such slot {slot_id}")
    prior = row["status"]
    approve_states = {g.get("approve_to") for g in (cfg.get("gates") or {}).values() if g.get("approve_to")}
    if prior not in (reject_statuses(cfg) | approve_states):
        cur.close(); raise GateError(f"{slot_id} is {prior} — nothing to reverse (reopen)")
    cur.execute("SELECT gd.gate_id, g.stage FROM gate_decision gd JOIN gate g USING (gate_id) "
                "WHERE gd.slot_id=%s ORDER BY gd.decided_at DESC LIMIT 1", (slot_id,))
    d = cur.fetchone()
    if not d:
        cur.close(); raise GateError(f"{slot_id}: no decision to reverse")
    rs = stage_cfg(cfg, d["stage"]).get("reviews_status", "DRAFT_ASSIGNED")
    review_status = rs[0] if isinstance(rs, list) else rs
    kind = "un_rejected" if prior in reject_statuses(cfg) else "un_approved"
    cur.execute("DELETE FROM gate_decision WHERE gate_id=%s AND slot_id=%s", (d["gate_id"], slot_id))
    # #282 — the reopened slot has no remaining decisions, so its authoritative per-token coverage is
    # cleared too (operational state follows the decisions). The gate's legacy/authoritative marker and
    # the append-only audit trail are untouched — no silent conversion. Legacy gates have no coverage.
    cur.execute("DELETE FROM gate_token_coverage WHERE gate_id=%s AND slot_id=%s", (d["gate_id"], slot_id))
    cur.execute("UPDATE slot SET status=%s, updated_at=now() WHERE slot_id=%s", (review_status, slot_id))
    cur.execute("DELETE FROM slot_approval WHERE slot_id=%s", (slot_id,))   # current-state pointer; events kept
    _audit(cur, "slot", slot_id, "reopened", actor,
           {"from": prior, "to": review_status, "kind": kind, "gate_id": str(d["gate_id"])})
    conn.commit(); cur.close()
    return {"slot_id": slot_id, "from": prior, "to": review_status, "kind": kind}


def clear_decision(conn, gate_id, approver_id, slot_ids=None, actor=None, cfg=None):
    """PRE-commit reversal (un-decide): clear a recorded per-item decision so the item is pending
    again, before the batch is submitted. The decision pointer is removed; the original decision is
    still in the event log + a `decision_cleared` event is recorded (full traceability)."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT status, stage FROM gate WHERE gate_id=%s", (gate_id,))
    g = cur.fetchone()
    if not g:
        cur.close(); raise GateError(f"no such gate {gate_id}")
    if g["status"] != "open":
        cur.close(); raise GateError(f"this review is already submitted — use reopen to reverse a committed decision")
    # #373 (Codex P1) — undecide clears ONLY THIS principal's decisions. Capture the slots this
    # approver ACTUALLY has a decision on (optionally filtered to the requested slot_ids) BEFORE
    # deleting, so coverage can be recomputed and the audit/return reflect real deletions only.
    if slot_ids:
        cur.execute("SELECT DISTINCT slot_id FROM gate_decision WHERE gate_id=%s AND approver_id=%s "
                    "AND slot_id = ANY(%s)", (gate_id, approver_id, list(slot_ids)))
    else:
        cur.execute("SELECT DISTINCT slot_id FROM gate_decision WHERE gate_id=%s AND approver_id=%s",
                    (gate_id, approver_id))
    affected = [r["slot_id"] for r in cur.fetchall()]
    # Fail closed + TRUTHFUL: if this principal has no recorded decision on the target, delete nothing,
    # report no success, and never audit a phantom clear (a projection bound to any approver could
    # otherwise offer a clear that deletes zero — this is the write-side backstop).
    if not affected:
        conn.rollback(); cur.close()
        raise GateError(f"{approver_id} has no recorded decision to clear on this gate")
    cur.execute("DELETE FROM gate_decision WHERE gate_id=%s AND approver_id=%s AND slot_id = ANY(%s)",
                (gate_id, approver_id, affected))
    # #282 — un-deciding may uncover a token or shift the matching; recompute per-token coverage for
    # the affected slots on an authoritative gate. Legacy gates (snapshot=None) keep the count path.
    snapshot = _load_gate_snapshot(cur, gate_id)
    if snapshot is not None:
        for s in affected:
            _recompute_slot_coverage(cur, gate_id, s, snapshot,
                                     head_revision=_gate_review_head(cur, cfg, g["stage"], s))
    for s in affected:
        _audit(cur, "slot", s, "decision_cleared", actor or approver_id,
               {"gate_id": str(gate_id), "approver": approver_id})
    conn.commit(); cur.close()
    return {"cleared": list(affected)}


# --------------------------------------------------------------------------- #
# #271 — calendar-continuity run read model + governed single-slot schedule revision.
# Consumes the merged D1 (#276) seam: a run's pinned eligibility comes from its immutable
# round_policy_snapshot -> baseline_eligibility_policy generation, never content_format.active.
# --------------------------------------------------------------------------- #
def _even_spread(counts):
    """Round-robin spread of {key: n} into a flat list (occurrences distributed, not clustered),
    preserving key order. Mirrors the planner's even_spread so a run-mix reconcile matches planning."""
    remaining = dict(counts)
    order = list(counts)
    total = sum(counts.values())
    out = []
    while len(out) < total:
        for k in order:
            if remaining[k] > 0:
                out.append(k); remaining[k] -= 1
                if len(out) == total:
                    break
    return out


def _pinned_policy_eligible(cur, round_id):
    """#271 on D1 — the eligible frameworks a run may target for a slot/mix revision: the format rows of
    the run's PINNED baseline-policy generation (round_policy_snapshot → baseline_eligibility_policy), so
    a run stays inside exactly the frameworks it was planned against regardless of any later
    policy/catalogue change. Each row is {name, framework_id, version_id}, deterministically ordered.

    FAILS CLOSED for a snapshotted run whose pinned policy is invalid — a missing policy row, an empty
    eligible set, or ANY pinned version_id that no longer resolves — so an old run can NEVER silently
    adopt the CURRENT policy (pinned-policy determinism, #278 P1). A snapshot's PRESENCE (not the success
    of resolving it) decides the branch: the current-policy fallback is reserved for a genuinely legacy
    run planned before D1, which carries no snapshot at all."""
    cur.execute("SELECT baseline_policy_id::text AS bpid FROM round_policy_snapshot WHERE round_id=%s",
                (round_id,))
    row = cur.fetchone()
    if not row:
        return list(resolve_run_eligibility(cur)["eligible"])   # legacy run — no D1 snapshot to pin
    bpid = row["bpid"]
    cur.execute("SELECT generation, eligible_version_ids FROM baseline_eligibility_policy WHERE policy_id=%s",
                (bpid,))
    pol = cur.fetchone()
    if not pol:
        raise GateError(f"run {round_id} pins baseline policy {bpid}, which no longer exists — "
                        "pinned-policy determinism fails closed (no current-policy fallback for a snapshotted run)")
    ids = list(pol["eligible_version_ids"] or [])
    if not ids:
        raise GateError(f"run {round_id}'s pinned baseline policy {bpid} (gen {pol['generation']}) has no "
                        "eligible versions — pinned-policy determinism fails closed")
    cur.execute("""SELECT f.name, v.version_id::text AS version_id,
                          v.production_rules->>'framework_id' AS framework_id
                   FROM content_format_version v
                   JOIN content_format f ON f.content_format_id=v.content_format_id
                   WHERE v.version_id::text = ANY(%s)
                   ORDER BY coalesce((v.production_rules->'planning'->>'sort_order')::int, 9999), f.name""",
                (ids,))
    eligible = [{"name": r["name"], "version_id": r["version_id"], "framework_id": r["framework_id"]}
                for r in cur.fetchall()]
    if len(eligible) != len(set(ids)):
        raise GateError(f"run {round_id}'s pinned policy {bpid} references {len(set(ids))} "
                        f"content_format_version(s) but only {len(eligible)} resolve — the pinned policy is "
                        "invalid (versions were reminted); pinned-policy determinism fails closed.")
    return eligible


def _pinned_policy_eligible_names(cur, round_id):
    """The pinned framework NAMES a run may target — the server-enforcement set for slot/mix revision.
    Same fail-closed semantics as _pinned_policy_eligible (raises GateError on an invalid pinned policy)."""
    return {e["name"] for e in _pinned_policy_eligible(cur, round_id)}


def _require_schedule_authority(conn, cur, actor, cfg, entity_id, action):
    """#271 — preserve the EXISTING reviewer authority only (no IAM/reconsideration semantics): a
    governed schedule change is permitted for exactly the principals configured to decide the
    schedule_review gate. Denials are audited and fail closed."""
    approvers = [_token_from_assignment(a["assignment_kind"], a["assignment_key"])
                 for a in stage_approval_contract(cfg, "schedule_review", conn=conn)["assignments"]]
    if approvers and not any(_principal_matches_assignment(cur, actor, a) for a in approvers):
        audit_denied(conn, "slot", entity_id, action + "_denied", actor,
                     {"reason": "not_assigned", "allowed": approvers, "stage": "schedule_review"})
        raise GateError(f"{actor!r} is not an authorized schedule reviewer (allowed: {approvers})")


def round_detail(conn, round_id, cfg=None):
    """#271 — the run read model powering calendar continuity: round meta + the exact per-run
    format_mix + the pinned D1 policy snapshot + truthful per-status lifecycle counts + the COMPLETE
    positional slot set (so the calendar keeps every planned cell, not the active-review subset). A
    later policy/catalogue change never reinterprets the run: it resolves from its stored snapshot."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #304 — starts_on is the run's ONLY authoritative absolute placement. NULL means never
    # governed-placed (legacy, or created through V1's placement-less form): the calendar renders that
    # as explicitly UNPLACED. created_at remains record provenance and is never schedule truth.
    cur.execute("SELECT round_id, label, period_len_days, posts_per_day, post_times, "
                "format_distribution, status, created_at, starts_on FROM round WHERE round_id=%s",
                (round_id,))
    r = cur.fetchone()
    if not r:
        cur.close(); raise GateError(f"no such round {round_id}")
    cur.execute("""SELECT baseline_policy_id::text AS baseline_policy_id, baseline_generation,
                          selected_version_ids, format_mix, methodology_version, workflow_version
                   FROM round_policy_snapshot WHERE round_id=%s""", (round_id,))
    snap = cur.fetchone()
    # join pillar short-code + hcs seq so the calendar can render the canonical content ID for EVERY
    # planned cell (continuity), not only the active-gate targets that carry the full join.
    cur.execute("""SELECT sl.slot_id, sl.day, sl.time_uae, sl.pillar_code, p.code_short AS pillar_short_code,
                          sl.format, sl.hcs_id, h.seq_in_pillar, sl.lens, sl.hook_type,
                          sl.topic_angle, sl.status
                   FROM slot sl
                   LEFT JOIN pillar p ON p.pillar_code=sl.pillar_code
                   LEFT JOIN hcs h ON h.hcs_id=sl.hcs_id
                   WHERE sl.round_id=%s ORDER BY sl.day, sl.time_uae, sl.slot_id""", (round_id,))
    slots = cur.fetchall()
    counts = {}
    for s in slots:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    # #278 P1 — expose the run's FULL pinned eligibility set (incl. zero-count frameworks) so the
    # revision/planning UI can offer any framework the run was planned against, not only the ones that
    # happened to be allocated. Read-model resilience: an invalid pinned policy fails closed to an empty
    # set here (the calendar still renders for continuity) while the mutation endpoints still hard-stop.
    try:
        pinned_eligible = _pinned_policy_eligible(cur, round_id)
    except GateError:
        pinned_eligible = []
    # #306 — resolved while the cursor is still OPEN; this function closes it before returning.
    pinned_taxonomy = _pinned_taxonomy(cur, round_id)
    cur.close()
    return {
        "round_id": r["round_id"], "label": r["label"], "period_len_days": r["period_len_days"],
        "posts_per_day": r["posts_per_day"], "post_times": r["post_times"], "status": r["status"],
        # #308 — the run's authoritative absolute start. round_detail already SELECTs it (#304) but
        # never returned it; the selected-run views need it to project slots over the window and to
        # decide the adaptive initial view. NULL = unplaced (rendered explicitly, never fabricated).
        # ISO string so the client parses one canonical shape.
        "starts_on": r["starts_on"].isoformat() if r.get("starts_on") else None,
        "format_mix": (snap["format_mix"] if snap else None) or r["format_distribution"],
        "pinned_eligible_formats": pinned_eligible,
        # #306 — the dependent taxonomy options as the run's PINNED methodology generation defines
        # them. V2 resolves Pillar -> HCS from this and nothing else: the live catalogue may have
        # moved on, and a run is never reinterpreted against it. A legacy run with no pinned
        # generation gets [] — it has no pinned truth to offer, and inventing one from the live
        # catalogue would be a silent initialization.
        #
        # There is deliberately NO `category` here: no canonical Tanaghom category identity exists in
        # the pinned generation (verified), so per #306's boundary it stays a derived HCS label and
        # gets no persistence, catalogue, generation or authority of its own.
        "pinned_taxonomy": pinned_taxonomy,
        "policy_snapshot": ({"baseline_policy_id": snap["baseline_policy_id"],
                             "baseline_generation": snap["baseline_generation"],
                             "selected_version_ids": snap["selected_version_ids"],
                             "methodology_version": snap["methodology_version"],
                             "workflow_version": snap["workflow_version"]} if snap else None),
        "planned_total": len(slots), "status_counts": counts, "slots": slots,
    }


# #306 Stage 1B — pillar_code/hcs_id join the governed set. They are an ATOMIC PAIR: an HCS is only
# meaningful under its pillar, so accepting one without the other could persist a combination the
# pinned methodology never defined.
#
# Pillar/HCS is REUSABLE CLASSIFICATION LINEAGE, not unique content identity (Codex ruling): several
# slots may legitimately share the same pinned Pillar/HCS. There is deliberately NO duplicate
# rejection and NO uniqueness constraint here. Meaning-based Topic dedup is Stage 2 and is not this
# contract's business.
_SCHEDULE_REVISION_FIELDS = {"day", "time_uae", "format", "topic_guidance", "pillar_code", "hcs_id"}

# ---------------------------------------------------------------------------
# #292 — governed schedule display mapping + the round-scoped COMBINED token.
#
# THE LOCK ORDER IS THE CONTRACT: reorder, revise_schedule_slot, and the first topic persistence
# (agents/run_writers.py::process_topic — the single shared stub+live path) all take the ROUND ROW
# first, then revalidate the combined token under that lock. Without one shared serialization point
# "revalidate the token" and "FOR UPDATE the slots" would touch different rows and never actually
# serialize. Every guarded write in this slice starts with _lock_round().
#
# A DB LOCK IS NEVER HELD ACROSS A MODEL/PROVIDER CALL — process_topic acquires it only after
# generation returns, immediately before its first artifact insert.
# ---------------------------------------------------------------------------

# Slot statuses that are NOT downstream-advanced: the schedule is still the slot's own stage.
_SCHEDULE_OPEN_STATUSES = ("EMPTY", "RESERVED", "SCHEDULE_APPROVED")

# WORKFLOW_STAGE_LIBRARY puts schedule_review at index 0, so "downstream" is exactly
# "any stage after it". Schedule's OWN review decision must never make its own approved slots look
# downstream-advanced — otherwise a normally SCHEDULE_APPROVED round could never be reordered.
_SCHEDULE_STAGE = "schedule_review"


def _lock_round(cur, round_id):
    """#292 — THE single serialization point for every governed schedule write. Taken FIRST, so
    reorder / schedule-revision / first-topic-persist are strictly ordered against each other on the
    one object whose meaning they all change. Held for DB work only."""
    cur.execute("SELECT round_id FROM round WHERE round_id=%s FOR UPDATE", (round_id,))
    if not cur.fetchone():
        raise GateError(f"no such round {round_id}")


def schedule_token(cur, round_id):
    """The round's COMBINED schedule token = its highest accepted mapping generation.

    0 means LEGACY BY ABSENCE: the round predates #292 and has no governed mapping, so both V1 and
    V2 keep deriving presentation exactly as before. Initializing such a round is a separately
    governed slice — never an implicit side effect of a revision or a reorder."""
    cur.execute("SELECT coalesce(max(generation_no), 0) AS token "
                "FROM schedule_display_generation WHERE round_id=%s", (round_id,))
    return cur.fetchone()["token"]


def _downstream_advanced(cur, slot_ids):
    """#292 — the EXACT, STAGE-AWARE downstream predicate, from PERSISTED facts only.

    A slot is downstream-advanced iff its lifecycle left the schedule stage, OR a downstream
    artifact exists, OR a decision was recorded on a gate for a stage AFTER schedule_review.

    The stage qualification is load-bearing: an unqualified gate_decision would make every
    Schedule-approved slot look downstream-advanced and make reorder permanently impossible.
    CHANGES_REQUESTED is deliberately downstream — it is only reachable after topic work began."""
    if not slot_ids:
        return []
    cur.execute("""
        SELECT DISTINCT s.slot_id
          FROM slot s
         WHERE s.slot_id = ANY(%s)
           AND ( s.status::text <> ALL(%s)      -- slot.status is the slot_status ENUM; cast to compare
              OR EXISTS (SELECT 1 FROM topic  t WHERE t.slot_id = s.slot_id)
              OR EXISTS (SELECT 1 FROM script c WHERE c.slot_id = s.slot_id)
              OR EXISTS (SELECT 1 FROM asset  a WHERE a.slot_id = s.slot_id)
              OR EXISTS (SELECT 1 FROM gate_decision d
                           JOIN gate g ON g.gate_id = d.gate_id
                          WHERE d.slot_id = s.slot_id AND g.stage <> %s) )
         ORDER BY s.slot_id
    """, (list(slot_ids), list(_SCHEDULE_OPEN_STATUSES), _SCHEDULE_STAGE))
    return [r["slot_id"] for r in cur.fetchall()]


def _pinned_taxonomy(cur, round_id):
    """#306 — the run's dependent Pillar -> HCS options, straight from its PINNED generation.

    Shape is deliberately flat and canonical: each HCS carries the pillar it belongs to, so the
    client resolves the dependency by filtering — it never infers membership from a label, and an
    HCS can never be offered under a pillar the pinned generation does not put it in."""
    ver = _pinned_methodology_version(cur, round_id)
    if not ver:
        return {"methodology_version": None, "pillars": [], "hcs": []}
    cur.execute("""SELECT pillar_code, code_short, name_en FROM methodology_pillar
                    WHERE version_id=%s ORDER BY code_short, pillar_code""", (ver,))
    pillars = [dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT hcs_id, pillar_code, seq_in_pillar, name_en FROM methodology_hcs
                    WHERE version_id=%s ORDER BY pillar_code, seq_in_pillar""", (ver,))
    hcs = [dict(r) for r in cur.fetchall()]
    return {"methodology_version": str(ver), "pillars": pillars, "hcs": hcs}


def _pinned_methodology_version(cur, round_id):
    """#306 — the methodology generation this run was PINNED to, or None for a legacy run.

    Everything taxonomy-related resolves through this: a later catalogue edit must never reinterpret
    an existing run's classification or its human-facing codes."""
    cur.execute("SELECT methodology_version FROM round_policy_snapshot WHERE round_id=%s", (round_id,))
    r = cur.fetchone()
    return (r or {}).get("methodology_version")


def _pinned_hcs_strict(cur, ver, hcs_id):
    """#306 — the HCS as ONE pinned methodology version defines it, or None. WRITE-PATH ONLY.

    There is deliberately NO live-catalogue fallback here. A taxonomy WRITE resolves against the
    run's pinned generation or it fails closed: falling back to the live catalogue would (a) let a
    LEGACY run be revised against a catalogue it was never planned under, and (b) — because a legacy
    run's schedule token is 0 — accept a mutation that skips minting the required mapping generation.
    Legacy read/display fallback lives elsewhere (_round_slots_ordered) and never touches this path.
    """
    cur.execute("""SELECT h.hcs_id, h.pillar_code, h.seq_in_pillar, h.recommended_lenses,
                          p.code_short AS pillar_short_code
                     FROM methodology_hcs h
                     LEFT JOIN methodology_pillar p
                       ON p.version_id = h.version_id AND p.pillar_code = h.pillar_code
                    WHERE h.version_id=%s AND h.hcs_id=%s""", (ver, hcs_id))
    return cur.fetchone()


def _pinned_lens_and_hook(cur, ver, hcs_id, cycle_no):
    """#306 — resolve the lens AND its hook_type from the SAME pinned methodology version.

    The dependent tuple (pillar, hcs, lens, hook_type) must be internally coherent: planner semantics
    derive hook_type from the selected lens's default_hook_type, so recalculating lens without hook
    would leave a mixed lineage. Both come from methodology_hcs.recommended_lenses +
    methodology_lens.default_hook_type in `ver`. READ-ONLY: lens_history is never written (an override
    is not a walk emission), so cross-run rotation is untouched. Fails closed if the pinned version
    cannot resolve a lens or its hook."""
    cur.execute("SELECT recommended_lenses FROM methodology_hcs WHERE version_id=%s AND hcs_id=%s",
                (ver, hcs_id))
    row = cur.fetchone()
    rec = (row or {}).get("recommended_lenses") or []
    if isinstance(rec, str):
        rec = [x.strip() for x in rec.split(",") if x.strip()]
    if not rec:
        raise GateError(f"HCS {hcs_id} has no recommended lenses in the run's pinned methodology "
                        "generation — it cannot be assigned")
    cur.execute("SELECT lens FROM lens_history WHERE hcs_id=%s AND cycle_no=%s", (hcs_id, (cycle_no or 1) - 1))
    prior = (cur.fetchone() or {}).get("lens")
    start = ((cycle_no or 1) - 1) % len(rec)
    rotated = rec[start:] + rec[:start]
    lens = next((l for l in rotated if l != prior), rotated[0])
    # hook_type from the SAME pinned version's lens definition.
    cur.execute("SELECT default_hook_type FROM methodology_lens WHERE version_id=%s AND lens_id=%s",
                (ver, lens))
    hk = cur.fetchone()
    if not hk or not hk.get("default_hook_type"):
        raise GateError(f"lens {lens} has no default hook_type in the run's pinned methodology "
                        "generation — the dependent tuple cannot be made coherent")
    return lens, hk["default_hook_type"]


def _display_code(pillar_short_code, seq_in_pillar, position, posts_per_day):
    """#292 (D-292-2 ruling: position-derived, generation-owned codes) — the human-facing code a
    generation ASSIGNS to the slot at `position`.

    day/post come from the accepted PRESENTATION position, not from slot.day or the slot_id suffix:
    that is what makes a governed reorder actually renumber. Shape matches V1's expanded form
    (dashboard/lib/content-id.ts) so operators read the same identifier they always have.
    Canonical slot_id is never derived from this and never changes."""
    ppd = max(1, int(posts_per_day or 1))
    day = ((position - 1) // ppd) + 1
    post = ((position - 1) % ppd) + 1
    m = re.search(r"(\d+)", pillar_short_code or "")
    pillar = (m.group(1) if m else "0").zfill(2)
    struggle = str(seq_in_pillar or 0).zfill(2)
    return f"P{pillar}-HS{struggle}-{day:02d}.{post:02d}"


def _commit_generation(cur, round_id, base_token, origin, actor, ordered_slots, posts_per_day):
    """#292 — atomically accept ONE new mapping generation, or lose cleanly.

    Exactly-one-winner is arbitrated by the DB via UNIQUE (round_id, generation_no) + the repo's
    established `ON CONFLICT DO NOTHING RETURNING` idiom (#265/#267, see reconcile_gate_targets):
    only the statement that actually inserted the row sees it in RETURNING. There is NO
    application-level read-then-write. The loser gets no row -> ScheduleConflict (409).

    Runs on the CALLER's cursor inside the caller's transaction, so the generation, its complete
    position set, and the winning audit are one atomic unit: a raise rolls all three back and leaves
    no partial mapping."""
    cur.execute("""INSERT INTO schedule_display_generation
                     (round_id, generation_no, base_generation_no, origin, actor)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (round_id, generation_no) DO NOTHING
                   RETURNING generation_id, generation_no""",
                (round_id, base_token + 1, base_token or None, origin, actor))
    row = cur.fetchone()
    if not row:
        # Another writer already accepted this generation number — we lost the race.
        raise ScheduleConflict(
            f"schedule token {base_token} is stale for {round_id} — another accepted change won this "
            "generation; refresh and re-submit",
            {"round_id": round_id, "current_token": schedule_token(cur, round_id)})
    gen_id, gen_no = row["generation_id"], row["generation_no"]
    for position, s in enumerate(ordered_slots, start=1):
        cur.execute("""INSERT INTO schedule_display_position
                         (generation_id, slot_id, display_position, display_code)
                       VALUES (%s,%s,%s,%s)""",
                    (gen_id, s["slot_id"], position,
                     _display_code(s.get("pillar_short_code"), s.get("seq_in_pillar"),
                                   position, posts_per_day)))
    return gen_id, gen_no


def _round_slots_ordered(cur, round_id):
    """The round's COMPLETE slot set in its current physical planning order. Deterministic tie-break
    on slot_id so an initial/derived generation is reproducible."""
    # pillar_short_code / seq_in_pillar are JOINED (pillar.code_short, hcs.seq_in_pillar) — the same
    # join round_detail uses, so a generation's codes are built from exactly the read model's fields.
    # #306 — PIN-AWARE: resolve code inputs from the run's PINNED methodology generation when it has
    # one, so a later catalogue edit (a re-sequenced seq_in_pillar, a renamed short code) can never
    # re-mint different human-facing codes for an existing run. Legacy runs with no pinned generation
    # fall back to the live catalogue, exactly as before — that is their only truth.
    ver = _pinned_methodology_version(cur, round_id)
    if ver:
        cur.execute("""SELECT s.slot_id, s.day, s.time_uae,
                              mp.code_short AS pillar_short_code, mh.seq_in_pillar
                         FROM slot s
                         LEFT JOIN methodology_hcs mh
                           ON mh.version_id = %s AND mh.hcs_id = s.hcs_id
                         LEFT JOIN methodology_pillar mp
                           ON mp.version_id = %s AND mp.pillar_code = s.pillar_code
                        WHERE s.round_id=%s
                        ORDER BY s.day, s.time_uae, s.slot_id""", (ver, ver, round_id))
        return cur.fetchall()
    cur.execute("""SELECT s.slot_id, s.day, s.time_uae,
                          p.code_short AS pillar_short_code, h.seq_in_pillar
                     FROM slot s
                     LEFT JOIN pillar p ON p.pillar_code = s.pillar_code
                     LEFT JOIN hcs    h ON h.hcs_id      = s.hcs_id
                    WHERE s.round_id=%s
                    ORDER BY s.day, s.time_uae, s.slot_id""", (round_id,))
    return cur.fetchall()


def schedule_mapping(conn, round_id):
    """Read model: the round's CURRENT accepted mapping + token. Legacy rounds (token 0) return no
    positions, so V1/V2 fall back to their existing derivation — preservation by absence."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        token = schedule_token(cur, round_id)
        if not token:
            return {"round_id": round_id, "schedule_token": 0, "legacy": True, "positions": []}
        cur.execute("""SELECT p.slot_id, p.display_position, p.display_code
                         FROM schedule_display_position p
                         JOIN schedule_display_generation g ON g.generation_id = p.generation_id
                        WHERE g.round_id=%s AND g.generation_no=%s
                        ORDER BY p.display_position""", (round_id, token))
        return {"round_id": round_id, "schedule_token": token, "legacy": False,
                "positions": [dict(r) for r in cur.fetchall()]}
    finally:
        cur.close()


def initialize_schedule_mapping(conn, round_id, actor="system", cfg=None):
    """#292 — create generation 1 for a NEW round from its deterministic planning order.

    Called only on round creation. It NEVER runs against a round that already has a generation, and
    it is NEVER applied to pre-#292 rounds: existing rounds stay legacy by absence (no automatic or
    bulk initialization — that remains a separately governed slice)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        _lock_round(cur, round_id)
        if schedule_token(cur, round_id):
            return None                      # idempotent: already governed
        cur.execute("SELECT posts_per_day FROM round WHERE round_id=%s", (round_id,))
        ppd = (cur.fetchone() or {}).get("posts_per_day") or 1
        slots = _round_slots_ordered(cur, round_id)
        if not slots:
            return None
        gen_id, gen_no = _commit_generation(cur, round_id, 0, "initial", actor, slots, ppd)
        _audit(cur, "round", round_id, "schedule_mapping_initialized", actor,
               {"generation_no": gen_no, "slots": len(slots)})
        conn.commit()
        return gen_no
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def reorder_schedule(conn, round_id, order, expected_token, actor="system", cfg=None):
    """#292 — commit a COMPLETE governed presentation order for a round.

    Changes ONLY the accepted presentation mapping and its human-facing codes. Canonical slot_id,
    lineage, and the physical slot.day/time_uae are untouched (those stay revise_schedule_slot's
    domain). Fails closed on any downstream-advanced slot: no cascade, no deletion, no silent remap,
    no historical rewrite."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # _require_schedule_authority audits its OWN denial in a separate committed transaction, so the
    # handlers below must not re-audit it. Everything after it is ours to audit.
    authorized = False
    try:
        _lock_round(cur, round_id)                      # round row FIRST — the serialization point
        _require_schedule_authority(conn, cur, actor, cfg, round_id, "schedule_reorder")
        authorized = True

        token = schedule_token(cur, round_id)
        if not token:
            raise GateError(
                f"{round_id} has no governed schedule mapping (legacy round) — reordering it would "
                "initialize its presentation, which is a separately governed slice")
        if expected_token != token:
            raise ScheduleConflict(
                f"schedule token {expected_token} is stale for {round_id} (current {token}) — "
                "refresh and re-submit",
                {"round_id": round_id, "current_token": token,
                 "positions": schedule_mapping(conn, round_id)["positions"]})

        slots = {s["slot_id"]: s for s in _round_slots_ordered(cur, round_id)}
        if not isinstance(order, list) or not order:
            raise GateError("a reorder needs the complete ordered slot_id list for the round")
        if len(order) != len(slots) or len(set(order)) != len(order) or set(order) != set(slots):
            raise GateError(
                "a reorder must be a COMPLETE permutation of the round's slots "
                f"(expected exactly {sorted(slots)})")

        # Fail closed on downstream advancement — checked under the SAME lock, so an advancement
        # racing this reorder cannot slip between the check and the commit.
        advanced = _downstream_advanced(cur, list(order))
        if advanced:
            raise GateError(
                f"cannot reorder {round_id}: {advanced} already carry downstream content — reorder "
                "changes presentation only and never remaps or rewrites committed artifacts")

        cur.execute("SELECT posts_per_day FROM round WHERE round_id=%s", (round_id,))
        ppd = (cur.fetchone() or {}).get("posts_per_day") or 1
        ordered = [slots[sid] for sid in order]
        prior = {p["slot_id"]: {"position": p["display_position"], "code": p["display_code"]}
                 for p in schedule_mapping(conn, round_id)["positions"]}
        gen_id, gen_no = _commit_generation(cur, round_id, token, "reorder", actor, ordered, ppd)

        cur.execute("""SELECT slot_id, display_position, display_code
                         FROM schedule_display_position WHERE generation_id=%s
                        ORDER BY display_position""", (gen_id,))
        new_positions = [dict(r) for r in cur.fetchall()]
        _audit(cur, "round", round_id, "schedule_reordered", actor,
               {"base_generation": token, "generation_no": gen_no,
                "slots": [p["slot_id"] for p in new_positions],
                "prior": prior,
                "new": {p["slot_id"]: {"position": p["display_position"], "code": p["display_code"]}
                        for p in new_positions}})
        conn.commit()
        return {"round_id": round_id, "schedule_token": gen_no, "positions": new_positions}
    except ScheduleConflict as e:
        conn.rollback()
        # Rejection evidence must never look like an authoritative mutation: no generation, no
        # positions, no mutation audit — and it carries only IDs/tokens/reasons, never the caller's
        # proposed content.
        audit_denied(conn, "round", round_id, "schedule_reorder_rejected", actor,
                     {"reason": "stale_token", "expected": expected_token,
                      "current": e.current.get("current_token")})
        raise
    except GateError as e:
        conn.rollback()
        if authorized:                    # an authority denial already audited itself
            audit_denied(conn, "round", round_id, "schedule_reorder_rejected", actor,
                         {"reason": str(e)[:300]})
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# #314 — TOPIC-WORKBENCH PRESENTATION ORDER (distinct from #292 Schedule order)
#
# A per-round, append-only PRESENTATION order for the Topic workbench, with its OWN token
# (topic_presentation_generation.generation_no) — reordering the Topic presentation never bumps the
# #292 schedule_token and vice-versa. It MIRRORS #292's exactly-one-winner concurrency
# (UNIQUE(round_id, generation_no) + `ON CONFLICT DO NOTHING RETURNING`) but is PRESENTATION ONLY: it
# writes ONLY topic_presentation_generation/_position (+ audit) and changes nothing authoritative — not
# slot placement, Schedule order, disposition, approval, taxonomy, config generation, or Topic revision
# identity. It deliberately does NOT apply the schedule-specific downstream-advanced fail-closed (that
# guards schedule display CODES tied to committed artifacts; a cosmetic Topic-workbench order remaps
# nothing, so blocking it on downstream content would be wrong). Authority reuses the EXACT #292
# schedule-reorder authority (schedule_review principals) — NO new authority.
# ---------------------------------------------------------------------------

def topic_presentation_token(cur, round_id):
    """The round's current Topic-workbench presentation token = its highest accepted generation.
    0 = LEGACY BY ABSENCE (no governed presentation order yet; the workbench derives order as today)."""
    cur.execute("SELECT coalesce(max(generation_no), 0) AS token "
                "FROM topic_presentation_generation WHERE round_id=%s", (round_id,))
    return cur.fetchone()["token"]


def _topic_round_slot_ids(cur, round_id):
    """The round's COMPLETE slot set (ascending slot_id) — the membership a presentation order permutes."""
    cur.execute("SELECT slot_id FROM slot WHERE round_id=%s ORDER BY slot_id", (round_id,))
    return [r["slot_id"] for r in cur.fetchall()]


def _commit_topic_presentation(cur, round_id, base_token, origin, actor, ordered_slots):
    """#314 — atomically accept ONE new presentation generation, or lose cleanly. Exactly-one-winner via
    UNIQUE(round_id, generation_no) + `ON CONFLICT DO NOTHING RETURNING` (the #292 idiom): only the
    inserting statement sees RETURNING; the loser gets no row -> ScheduleConflict. Runs on the caller's
    cursor in the caller's transaction, so the generation + its complete position set + the winning audit
    are one atomic unit."""
    cur.execute("""INSERT INTO topic_presentation_generation
                     (round_id, generation_no, base_generation_no, origin, actor)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (round_id, generation_no) DO NOTHING
                   RETURNING generation_id, generation_no""",
                (round_id, base_token + 1, base_token or None, origin, actor))
    row = cur.fetchone()
    if not row:
        raise ScheduleConflict(
            f"topic presentation token {base_token} is stale for {round_id} — another accepted reorder "
            "won this generation; refresh and re-submit",
            {"round_id": round_id, "current_token": topic_presentation_token(cur, round_id)})
    gen_id, gen_no = row["generation_id"], row["generation_no"]
    for position, sid in enumerate(ordered_slots, start=1):
        cur.execute("""INSERT INTO topic_presentation_position (generation_id, slot_id, display_position)
                       VALUES (%s,%s,%s)""", (gen_id, sid, position))
    return gen_id, gen_no


def topic_presentation(conn, round_id):
    """Read model: the round's CURRENT accepted Topic-workbench presentation order + token. A legacy
    round (token 0) returns no positions, so the workbench keeps its current derivation — preservation
    by absence."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        token = topic_presentation_token(cur, round_id)
        if not token:
            return {"round_id": round_id, "topic_presentation_token": 0, "legacy": True, "positions": []}
        cur.execute("""SELECT p.slot_id, p.display_position
                         FROM topic_presentation_position p
                         JOIN topic_presentation_generation g ON g.generation_id = p.generation_id
                        WHERE g.round_id=%s AND g.generation_no=%s
                        ORDER BY p.display_position""", (round_id, token))
        return {"round_id": round_id, "topic_presentation_token": token, "legacy": False,
                "positions": [dict(r) for r in cur.fetchall()]}
    finally:
        cur.close()


def reorder_topic_presentation(conn, round_id, order, expected_token, actor="system", cfg=None):
    """#314 — commit a COMPLETE governed PRESENTATION order for a round's Topic workbench.

    PRESENTATION ONLY: canonical slot_id, #292 Schedule order/token, disposition, approval, taxonomy,
    methodology/config generation, and Topic revision identity are ALL untouched — this writes only
    topic_presentation_generation/_position (+ audit). Distinct token from #292. Exactly-one-winner via
    ON CONFLICT; a stale token fails closed with a typed ScheduleConflict (409) carrying the current
    order. `order` must be a COMPLETE, duplicate-free permutation of the round's slots. The first reorder
    of a legacy round (expected_token 0) initializes generation 1 (cosmetic; no separate init slice
    needed, unlike #292 schedule which gates display codes)."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    authorized = False
    try:
        _lock_round(cur, round_id)                       # round row FIRST — the serialization point
        # #314 — DETERMINISTIC LOCK ORDER (round -> slots ASCENDING). The position inserts FK-reference
        # every slot; without pre-acquiring those slot locks in a fixed order, a concurrent per-slot
        # mutation (edit/decide/drop taking a slot FOR UPDATE) can deadlock with the piecemeal FK locks.
        # Acquiring them all here (KEY SHARE, ascending) under the round lock gives one total order, so a
        # concurrent per-slot FOR UPDATE serializes cleanly instead of deadlocking. (A forced-interleaving
        # proof, K5, exposed this.)
        cur.execute("SELECT slot_id FROM slot WHERE round_id=%s ORDER BY slot_id FOR KEY SHARE", (round_id,))
        _require_schedule_authority(conn, cur, actor, cfg, round_id, "topic_presentation_reorder")
        authorized = True

        slots = _topic_round_slot_ids(cur, round_id)
        if not isinstance(order, list) or not order:
            raise GateError("a topic presentation reorder needs the complete ordered slot_id list")
        if len(order) != len(slots) or len(set(order)) != len(order) or set(order) != set(slots):
            raise GateError(
                "a topic presentation reorder must be a COMPLETE permutation of the round's slots "
                f"(expected exactly {sorted(slots)})")

        token = topic_presentation_token(cur, round_id)
        if expected_token != token:
            raise ScheduleConflict(
                f"topic presentation token {expected_token} is stale for {round_id} (current {token}) — "
                "refresh and re-submit",
                {"round_id": round_id, "current_token": token,
                 "positions": topic_presentation(conn, round_id)["positions"]})

        prior = {p["slot_id"]: p["display_position"]
                 for p in topic_presentation(conn, round_id)["positions"]}
        gen_id, gen_no = _commit_topic_presentation(cur, round_id, token, "reorder", actor, order)
        cur.execute("""SELECT slot_id, display_position FROM topic_presentation_position
                        WHERE generation_id=%s ORDER BY display_position""", (gen_id,))
        new_positions = [dict(r) for r in cur.fetchall()]
        _audit(cur, "round", round_id, "topic_presentation_reordered", actor,
               {"base_generation": token, "generation_no": gen_no,
                "slots": [p["slot_id"] for p in new_positions],
                "prior": prior,
                "new": {p["slot_id"]: p["display_position"] for p in new_positions}})
        conn.commit()
        return {"round_id": round_id, "topic_presentation_token": gen_no, "positions": new_positions}
    except ScheduleConflict as e:
        conn.rollback()
        # Rejection evidence must never look like an authoritative mutation: no generation, no positions,
        # no mutation audit — only IDs/tokens/reasons, never the caller's proposed order content.
        audit_denied(conn, "round", round_id, "topic_presentation_reorder_rejected", actor,
                     {"reason": "stale_token", "expected": expected_token,
                      "current": e.current.get("current_token")})
        raise
    except psycopg2.errors.DeadlockDetected:
        # A concurrent per-slot mutation (edit/decide/drop) contended the shared slot FK locks and
        # Postgres atomically aborted THIS transaction — no partial/incorrect/lost state. Surface it as a
        # RETRYABLE typed conflict (409), never a 500: the client refreshes the token and retries. (A
        # forced-interleaving proof, K5, exposed this residual serialization hazard.)
        conn.rollback()
        raise ScheduleConflict(
            f"topic presentation reorder for {round_id} hit a concurrent-modification serialization "
            "conflict — atomically rolled back; refresh and retry",
            {"round_id": round_id, "current_token": None, "retryable": True})
    except GateError as e:
        conn.rollback()
        if authorized:                    # an authority denial already audited itself
            audit_denied(conn, "round", round_id, "topic_presentation_reorder_rejected", actor,
                         {"reason": str(e)[:300]})
        raise
    finally:
        cur.close()


def place_run(conn, round_id, starts_on, actor="system", cfg=None, expected_token=None):
    """#304 — the governed absolute placement of a RUN on the calendar.

    This is the only writer of `round.starts_on`. It moves the campaign WINDOW; it never touches
    canonical slot identity, `slot.day`/`slot.time_uae`, accepted content mapping, or history — a
    slot's absolute datetime stays derived (starts_on + day-1 at time_uae), so a run move re-projects
    the same canonical cells rather than rewriting them.

    Four existing contracts are reused rather than re-invented:
      - AUTHORITY: `_require_schedule_authority` (#271) — principal-neutral, exactly the principals
        configured to decide schedule_review. No human-only rule, no IAM/delegation widening.
      - CONCURRENCY: `_lock_round` + the COMBINED `schedule_token` (#292, ruling C). One concurrency
        authority for the whole schedule surface: a reorder invalidates a stale placement proposal and
        vice versa. It over-invalidates rather than under-invalidates, and invents no second token.
      - FREEZE: `_downstream_advanced` (#292) — the exact stage-aware predicate over PERSISTED facts.
        Placement freezes once ANY slot of the run has left the schedule stage. The predicate is
        evaluated HERE, from server state; the UI reads the answer and never computes one.
      - AUDIT: append-only, recording actor, old/new placement, the token, and the timestamp.

    Lock order follows #292's review lesson exactly: only IMMUTABLE identity may be read before the
    lock; every mutable field is re-read under it. Reading the placement or the slot statuses first
    would let a writer commit inside the window and leave this decision acting on a stale snapshot.
    """
    if starts_on is None:
        raise GateError("a run placement needs an absolute start date (starts_on); "
                        "placement is never derived from created_at")
    # The authority contract is resolved from config; callers that do not carry one (the API route
    # does not) must still get a real authority DECISION, not an AttributeError deep inside
    # stage_cfg. Loading it here keeps the endpoint thin and the failure mode a governed 401/403
    # rather than a 500 that looks like the check ran.
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    authorized = False
    try:
        # round_id is immutable identity — the one read allowed before the lock.
        cur.execute("SELECT 1 FROM round WHERE round_id=%s", (round_id,))
        if not cur.fetchone():
            raise GateError(f"no such round {round_id}")
        _lock_round(cur, round_id)
        _require_schedule_authority(conn, cur, actor, cfg, round_id, "run_placement")
        authorized = True

        token = schedule_token(cur, round_id)
        if expected_token is None or int(expected_token) != token:
            raise ScheduleConflict(
                f"schedule token {expected_token} is stale for {round_id} (current {token}) — "
                "refresh and re-submit",
                {"round_id": round_id, "current_token": token})

        # Mutable state, re-read UNDER the lock — this snapshot is what every check below uses.
        cur.execute("SELECT starts_on, period_len_days FROM round WHERE round_id=%s", (round_id,))
        row = cur.fetchone()
        old = row["starts_on"]

        cur.execute("SELECT slot_id FROM slot WHERE round_id=%s", (round_id,))
        slot_ids = [s["slot_id"] for s in cur.fetchall()]
        advanced = _downstream_advanced(cur, slot_ids)
        if advanced:
            # Material execution has begun. Placement is frozen: a later reschedule is a separately
            # approved contract, not a silent correction here.
            raise GateError(
                f"{round_id} placement is frozen — material execution has begun "
                f"({len(advanced)} slot(s) advanced past Schedule). Reopen or use a governed "
                "reschedule contract; placement is not corrected in-place after execution starts")

        cur.execute("UPDATE round SET starts_on=%s WHERE round_id=%s", (starts_on, round_id))
        _audit(cur, "round", round_id, "run_placed", actor,
               {"from": old.isoformat() if old else None,
                "to": starts_on.isoformat() if hasattr(starts_on, "isoformat") else str(starts_on),
                "schedule_token": token, "period_len_days": row["period_len_days"]})
        conn.commit()
        return {"round_id": round_id,
                "starts_on": starts_on.isoformat() if hasattr(starts_on, "isoformat") else str(starts_on),
                "previous_starts_on": old.isoformat() if old else None,
                "schedule_token": token}
    except GateError as e:
        conn.rollback()
        if authorized:                        # an authority denial already audited itself
            audit_denied(conn, "round", round_id, "run_placement_rejected", actor,
                         {"reason": str(e)[:300]})
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def revise_schedule_slot(conn, slot_id, changes, actor="system", cfg=None, expected_token=None):
    """#271 — a governed single-slot schedule revision: a reviewer proposes a change to one slot's
    planned day / time / format (within the run's PINNED D1 policy) / topic guidance. The change is NOT
    silently committed — it returns ONLY that slot to Schedule review (status → RESERVED), keeps the
    slot's canonical id + append-only audit lineage, and recomputes the applicable framework rules at
    the next generation (the writer reads the new format). Downstream artifacts are never deleted or
    remapped; a slot already generating content must be reopened first (no cascade — #51 stays deferred)."""
    cfg = cfg or load_config()
    if not isinstance(changes, dict) or not changes:
        raise GateError("a schedule revision needs at least one changed field "
                        f"(one of {sorted(_SCHEDULE_REVISION_FIELDS)})")
    unknown = set(changes) - _SCHEDULE_REVISION_FIELDS
    if unknown:
        raise GateError(f"not a governed schedule field: {sorted(unknown)} "
                        f"(allowed: {sorted(_SCHEDULE_REVISION_FIELDS)})")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #292 — SAME lock order as reorder and first-topic-persist: the round row first, then the
    # combined token revalidated under it. A revision changes physical placement, which the accepted
    # presentation projects, so it shares one token with reorder: either operation invalidates the
    # other's stale token and no cross-operation conflict can be silently missed.
    #
    # A slot's round_id is IMMUTABLE, so resolving it is the one read allowed before the lock. Every
    # MUTABLE field — status above all — is read only UNDER the round lock. Reading them first would
    # break the contract this comment claims: a writer committing in the window (process_topic
    # persisting the first topic, RESERVED/SCHEDULE_APPROVED -> TOPIC_PROPOSED) would leave the
    # revision validating a stale snapshot and pushing a slot that now carries a topic back to
    # RESERVED, silently reopening downstream content. The combined token cannot catch that: topic
    # persistence changes no schedule mapping, so the token is unchanged and the revision proceeds.
    cur.execute("SELECT round_id FROM slot WHERE slot_id=%s", (slot_id,))
    ident = cur.fetchone()
    if not ident:
        cur.close(); raise GateError(f"no such slot {slot_id}")
    _lock_round(cur, ident["round_id"])
    # Mutable state, re-read under the lock — this snapshot is the one every check below uses.
    cur.execute("""SELECT s.round_id, s.day, s.time_uae, s.format, s.topic_angle, s.status,
                          s.pillar_code, s.hcs_id, s.lens, s.hook_type, s.cycle_no, r.period_len_days
                   FROM slot s JOIN round r ON r.round_id=s.round_id WHERE s.slot_id=%s""", (slot_id,))
    slot = cur.fetchone()
    if not slot:
        cur.close(); raise GateError(f"no such slot {slot_id}")
    _require_schedule_authority(conn, cur, actor, cfg, slot_id, "schedule_revision")
    token = schedule_token(cur, slot["round_id"])
    if expected_token is None or int(expected_token) != token:
        cur.close()
        raise ScheduleConflict(
            f"schedule token {expected_token} is stale for {slot['round_id']} (current {token}) — "
            "refresh and re-submit",
            {"round_id": slot["round_id"], "current_token": token})
    # bounded precondition: revise a slot at/before schedule approval; a slot already in content
    # generation must be reopened first — this slice never cascades a structural change downstream.
    if slot["status"] not in ("RESERVED", "SCHEDULE_APPROVED"):
        cur.close()
        raise GateError(f"{slot_id} is {slot['status']} — reopen it to Schedule review before revising "
                        "its schedule (no downstream content cascade in this slice)")
    sets, params, applied = [], [], {}
    if "format" in changes:
        new_fmt = changes["format"]
        allowed = _pinned_policy_eligible_names(cur, slot["round_id"])
        if new_fmt not in allowed:
            cur.close()
            raise GateError(f"format {new_fmt!r} is not in this run's pinned policy (allowed: {sorted(allowed)})")
        sets.append("format=%s"); params.append(new_fmt); applied["format"] = new_fmt
    if "day" in changes:
        day = changes["day"]
        if isinstance(day, bool) or not isinstance(day, int) or day < 1:
            cur.close(); raise GateError("day must be a positive integer")
        # #278 P1 — bound the revised day to the run's configured period. The calendar is rendered only
        # for days 1..period_len_days; a day past it would keep the canonical slot but drop it off the
        # calendar, breaking continuity. A governed rejection keeps the writer's domain == the reader's.
        period = slot["period_len_days"]
        if period is not None and day > period:
            cur.close()
            raise GateError(f"day {day} is outside the run's configured period (1..{period}) — a schedule "
                            "revision must keep the slot on the calendar (calendar continuity)")
        sets.append("day=%s"); params.append(day); applied["day"] = day
    if "time_uae" in changes:
        t = changes["time_uae"]
        if not isinstance(t, str) or not t.strip():
            cur.close(); raise GateError("time_uae must be a non-empty time string")
        sets.append("time_uae=%s"); params.append(t.strip()); applied["time_uae"] = t.strip()
    if "topic_guidance" in changes:
        g = changes["topic_guidance"]
        if not isinstance(g, str) or not g.strip():
            cur.close(); raise GateError("topic_guidance must be non-empty text")
        sets.append("topic_angle=%s"); params.append(g.strip()); applied["topic_guidance"] = g.strip()
    # #306 Stage 1B — the governed taxonomy override. Pillar and HCS are an ATOMIC PAIR resolved
    # against the run's PINNED methodology generation, never the live catalogue and never a display
    # label: a later catalogue edit must not reinterpret this run, and a label is not identity.
    #
    # What this deliberately does NOT do, and why:
    #   - hcs_cursor: untouched. It is a per-pillar WATERMARK ("the walk last emitted H at cycle C"),
    #     not a ledger of what each slot holds. That statement stays true after an override, so
    #     rewriting it would make a run-local decision silently reinterpret FUTURE runs.
    #   - lens_history: untouched (see _pinned_lens_and_hook). An override is not a walk emission.
    #   - cycle_no: unchanged. It records the RUN's walk position — a fact about when the slot was
    #     planned, not a property of the HCS the operator chose.
    #   - no duplicate rejection: Pillar/HCS is REUSABLE CLASSIFICATION LINEAGE, not unique content
    #     identity (Codex ruling). Slots may legitimately share a pinned Pillar/HCS. Meaning-based
    #     Topic dedup is Stage 2.
    # Consequence, stated rather than hidden: an override does NOT reserve the HCS against the walk,
    # so a later run may allocate it again. Reserving would need a used-HCS set — a new domain model.
    if "pillar_code" in changes or "hcs_id" in changes:
        if not ("pillar_code" in changes and "hcs_id" in changes):
            cur.close()
            raise GateError("pillar_code and hcs_id must be revised together: an HCS is only "
                            "meaningful under its pillar, and accepting one alone could persist a "
                            "combination the pinned methodology never defined")
        new_pillar, new_hcs = changes["pillar_code"], changes["hcs_id"]
        if not isinstance(new_pillar, str) or not isinstance(new_hcs, str) \
                or not new_pillar.strip() or not new_hcs.strip():
            cur.close(); raise GateError("pillar_code and hcs_id must be canonical identities")
        # #306 P1.1 — the WRITE path FAILS CLOSED without a pinned methodology generation. A legacy
        # run (no snapshot) is never revised against the live catalogue: doing so would reinterpret a
        # run against a catalogue it was never planned under, and — because its token is 0 — could
        # accept a mutation that skips minting the required mapping generation. Legacy read/display
        # fallback is elsewhere and does not reach here.
        ver = _pinned_methodology_version(cur, slot["round_id"])
        if not ver:
            cur.close()
            raise GateError(f"{slot['round_id']} has no pinned methodology generation — its taxonomy "
                            "cannot be governed-revised (a legacy run is never reinterpreted against "
                            "the live catalogue)")
        pinned = _pinned_hcs_strict(cur, ver, new_hcs.strip())
        if not pinned:
            cur.close()
            raise GateError(f"HCS {new_hcs} is not in this run's pinned methodology generation — "
                            "a run is never reinterpreted against a later catalogue")
        if pinned["pillar_code"] != new_pillar.strip():
            # Dependent combination fails CLOSED — the pinned generation, not the caller, decides
            # which pillar an HCS belongs to.
            cur.close()
            raise GateError(f"HCS {new_hcs} belongs to pillar {pinned['pillar_code']}, not "
                            f"{new_pillar} — invalid dependent combination")
        # #306 P1.2 — resolve lens AND hook_type together from the SAME pinned version so the full
        # (pillar, hcs, lens, hook_type) tuple is internally coherent. Persisting lens without its
        # hook would leave a mixed lineage. Both are read-only: lens_history is never written.
        lens, hook = _pinned_lens_and_hook(cur, ver, new_hcs.strip(), slot.get("cycle_no"))
        sets.append("pillar_code=%s"); params.append(new_pillar.strip())
        sets.append("hcs_id=%s");      params.append(new_hcs.strip())
        sets.append("lens=%s");        params.append(lens)
        sets.append("hook_type=%s");   params.append(hook)
        applied["pillar_code"] = new_pillar.strip()
        applied["hcs_id"] = new_hcs.strip()
        applied["lens"] = lens
        applied["hook_type"] = hook

    prior = {"day": slot["day"], "time_uae": slot["time_uae"], "format": slot["format"],
             "status": slot["status"], "pillar_code": slot.get("pillar_code"),
             "hcs_id": slot.get("hcs_id"), "lens": slot.get("lens"),
             "hook_type": slot.get("hook_type")}
    sets.append("status='RESERVED'"); sets.append("updated_at=now()")
    cur.execute(f"UPDATE slot SET {', '.join(sets)} WHERE slot_id=%s", params + [slot_id])
    # #292 — a revision moves physical placement, which the accepted presentation projects. Create
    # the corresponding COMPLETE generation in the SAME transaction so the server projection can
    # never be left stale relative to the planning truth it presents. Legacy rounds (token 0) get
    # none: creating one would be an initialization, which is a separately governed slice.
    new_token = token
    if token:
        cur.execute("SELECT posts_per_day FROM round WHERE round_id=%s", (slot["round_id"],))
        ppd = (cur.fetchone() or {}).get("posts_per_day") or 1
        _, new_token = _commit_generation(cur, slot["round_id"], token, "schedule_revision", actor,
                                          _round_slots_ordered(cur, slot["round_id"]), ppd)
    _audit(cur, "slot", slot_id, "schedule_revised", actor,
           {"changes": applied, "prior": prior, "returned_to": "schedule_review",
            "round_id": slot["round_id"], "base_generation": token, "generation_no": new_token})
    conn.commit(); cur.close()
    return {"slot_id": slot_id, "changes": applied, "prior": prior, "status": "RESERVED",
            "returned_to": "schedule_review", "schedule_token": new_token}


def revise_run_mix(conn, round_id, new_mix, actor="system", cfg=None):
    """#271 — a pre-Schedule-approval run-level mix edit through the planning surface. Validates the
    exact total against the run's PINNED D1 eligibility and deterministically reconciles ONLY
    uncommitted (RESERVED) slots; committed/downstream content is NEVER silently remapped (if any slot
    has advanced past RESERVED this fails closed rather than approximating). The pinned policy generation
    is unchanged (no supersession here)."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT status FROM round WHERE round_id=%s", (round_id,))
    r = cur.fetchone()
    if not r:
        cur.close(); raise GateError(f"no such round {round_id}")
    _require_schedule_authority(conn, cur, actor, cfg, round_id, "run_mix_revision")
    cur.execute("SELECT slot_id, status FROM slot WHERE round_id=%s ORDER BY day, time_uae, slot_id",
                (round_id,))
    slots = cur.fetchall()
    committed = [s["slot_id"] for s in slots if s["status"] != "RESERVED"]
    if committed:
        cur.close()
        raise GateError(f"cannot re-mix {round_id}: {len(committed)} slot(s) are past Schedule review — "
                        "committed/downstream content is never remapped (revise those slots individually)")
    total = len(slots)
    allowed = _pinned_policy_eligible_names(cur, round_id)
    if not isinstance(new_mix, dict) or not new_mix:
        cur.close(); raise GateError("format_mix must be a non-empty object of {framework: count}")
    for name, count in new_mix.items():
        if name not in allowed:
            cur.close(); raise GateError(f"framework {name!r} is not in this run's pinned policy (allowed: {sorted(allowed)})")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            cur.close(); raise GateError(f"count for {name!r} must be a non-negative integer")
    if sum(new_mix.values()) != total:
        cur.close(); raise GateError(f"format_mix total {sum(new_mix.values())} must equal the run's {total} slots")
    counts = {name: int(new_mix.get(name, 0)) for name in sorted(new_mix) if name in allowed}
    fmt_seq = _even_spread(counts)
    for slot, fmt in zip(slots, fmt_seq):
        cur.execute("UPDATE slot SET format=%s, updated_at=now() WHERE slot_id=%s", (fmt, slot["slot_id"]))
    persisted = {name: int(new_mix.get(name, 0)) for name in counts}
    cur.execute("UPDATE round SET format_distribution=%s WHERE round_id=%s",
                (psycopg2.extras.Json(persisted), round_id))
    _audit(cur, "round", round_id, "run_mix_revised", actor,
           {"format_mix": persisted, "reconciled_slots": total})
    conn.commit(); cur.close()
    return {"round_id": round_id, "format_mix": persisted, "reconciled_slots": total}


# --------------------------------------------------------------------------- #
# Mandatory sign-offs (M5) — a slot can't reach publish-ready without them
# --------------------------------------------------------------------------- #
def _review_specs(cfg):
    """The configured human reviews (native/religious) with policy mode, flag, gate."""
    r = cfg.get("reviews") or {}
    specs = []
    for name in ("native", "religious"):
        s = r.get(name)
        if isinstance(s, dict) and s.get("flag") and s.get("gate"):
            specs.append({"name": name, "mode": s.get("mode", "reviewer_discretion"),
                          "flag": s["flag"], "gate": s["gate"]})
    return specs


def _spec_by(cfg, *, name=None, gate=None):
    for sp in _review_specs(cfg):
        if (name and sp["name"] == name) or (gate and sp["gate"] == gate):
            return sp
    return None


def _latest_script_flags(cur, slot_id):
    cur.execute("SELECT flags FROM script WHERE slot_id=%s ORDER BY revision DESC, created_at DESC "
                "LIMIT 1", (slot_id,))
    r = cur.fetchone()
    flags = (r or {}).get("flags") if r else None
    return set(flags if isinstance(flags, list) else (flags or []))


def _last_signoff_at(cur, slot_id, stage):
    """Timestamp of the latest sign-off (approve) on `stage` for this slot, or None."""
    cur.execute("SELECT max(gd.decided_at) AS at FROM gate_decision gd JOIN gate g USING (gate_id) "
                "WHERE g.stage=%s AND gd.slot_id=%s AND gd.decision='approve'", (stage, slot_id))
    r = cur.fetchone()
    return r["at"] if r else None


def _disposition(cur, slot_id, review):
    """The reviewer's latest disposition of a review: {disposition, at} or None."""
    cur.execute("SELECT disposition, at FROM slot_review WHERE slot_id=%s AND review=%s",
                (slot_id, review))
    return cur.fetchone()


def _review_pending(cur, slot_id, sp, *, for_gate=False):
    """Does review `sp` currently need a (fresh) sign-off for this slot? Honors policy + the
    reviewer's disposition + RE-ESCALATION (B3): an escalation NEWER than the last sign-off
    re-opens the requirement (the finished-media check). `for_gate` narrows to what a sign-off
    GATE should target (required or escalated only) vs what BLOCKS publish (also un-disposed
    `suggested`)."""
    if sp["flag"] not in _latest_script_flags(cur, slot_id):
        return False
    disp = _disposition(cur, slot_id, sp["name"])
    dval = disp["disposition"] if disp else None
    if dval == "waived":
        return False
    escalated = dval == "escalated"
    if for_gate:
        requires_signoff = sp["mode"] == "required" or escalated
    else:
        requires_signoff = sp["mode"] in ("required", "suggested") or escalated
    if not requires_signoff:
        return False
    signoff_at = _last_signoff_at(cur, slot_id, sp["gate"])
    if signoff_at is None:
        return True
    # already signed — but an escalation recorded AFTER that sign-off re-opens it (finished media)
    if escalated and disp and disp["at"] and disp["at"] > signoff_at:
        return True
    return False


def _review_blockers(cur, slot_id, cfg):
    """Sign-off gates still blocking publish, honoring each review's policy + the reviewer's
    disposition + re-escalation. reviewer_discretion + un-escalated never blocks; a waiver clears
    it; required/suggested/escalated block until a sign-off NEWER than the latest escalation."""
    return [sp["gate"] for sp in _review_specs(cfg) if _review_pending(cur, slot_id, sp)]


def publish_blockers(conn, slot_id, cfg=None):
    """Public: the sign-offs still blocking this slot from publish-ready ([] = clear)."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        return _review_blockers(cur, slot_id, cfg)
    finally:
        cur.close()


def dispose_review(conn, slot_id, review, action, reason=None, actor="system", cfg=None):
    """Reviewer disposes a review: 'escalate' (route to the named reviewer's sign-off gate, the
    safe direction) or 'waive' (skip, with an audited reason). Config drives what's allowed.

    M9·B3: the decision is COMPUTED as f(autonomy × stage-policy × permissions) — a non-human can
    waive only at sufficient autonomy + permission and NEVER a hard-floor review (religious);
    escalation is always permitted. Autonomous decisions are logged + remain human-overridable."""
    cfg = cfg or load_config()
    sp = _spec_by(cfg, name=review)
    if not sp:
        raise GateError(f"no review {review!r} in config reviews")
    if action not in ("escalate", "waive"):
        raise GateError("action must be 'escalate' or 'waive'")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Unified Actor Model: who is acting, and may they act (this) autonomously?
    verdict = {"autonomous": False, "autonomy_level": "human", "actor_kind": "user",
               "hard_floor": actors.is_hard_floor_review(cfg, review), "reason": "actor model off"}
    if actors.enabled(cfg):
        principal = actors.load_principal(cur, actor)
        verdict = actors.authorize_disposition(cfg, principal, review, action)
        if not verdict["allowed"]:
            cur.close()
            raise GateError(verdict["reason"])

    if action == "waive":
        if sp["mode"] == "required":
            cur.close()
            raise GateError(f"{review} review is 'required' — it cannot be waived")
        if not (reason or "").strip():
            cur.close()
            raise GateError("a waiver needs a reason (audited)")
    disposition = "escalated" if action == "escalate" else "waived"
    cur.execute("INSERT INTO slot_review (slot_id, review, disposition, reason, actor, actor_kind) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (slot_id, review) DO UPDATE SET disposition=EXCLUDED.disposition, "
                "reason=EXCLUDED.reason, actor=EXCLUDED.actor, actor_kind=EXCLUDED.actor_kind, at=now()",
                (slot_id, review, disposition, reason, actor, _principal_kind(cur, actor)))
    _audit(cur, "slot", slot_id, f"review_{disposition}", actor,
           {"review": review, "reason": reason, "autonomous": verdict["autonomous"],
            "autonomy_level": verdict["autonomy_level"], "hard_floor": verdict["hard_floor"]})
    if verdict["autonomous"]:                          # every autonomous decision is logged
        _audit(cur, "slot", slot_id, "autonomy_decision", actor,
               {"review": review, "action": action, "autonomy_level": verdict["autonomy_level"],
                "reason": verdict["reason"], "overridable": True})
    conn.commit()
    cur.close()


# --------------------------------------------------------------------------- #
# Open
# --------------------------------------------------------------------------- #
def _active_open_gate(cur, stage, round_id, statuses):
    """Enforce ONE open review per round+stage: return the canonical OPEN gate (the oldest with a
    target still at the review status), and SUPERSEDE the rest — orphans (all targets advanced) AND
    accidental duplicates. Audited. Returns the kept gate_id, or None if there's no active review."""
    cur.execute("""SELECT g.gate_id, count(*) FILTER (WHERE sl.status::text = ANY(%s)) AS active
                   FROM gate g JOIN gate_target t USING (gate_id) JOIN slot sl ON sl.slot_id=t.slot_id
                   WHERE g.status='open' AND g.stage=%s AND sl.round_id=%s
                   GROUP BY g.gate_id ORDER BY g.created_at""", (statuses, stage, round_id))
    keep, supersede = None, []
    for r in cur.fetchall():
        if r["active"] > 0 and keep is None:
            keep = r["gate_id"]                 # the canonical open gate (oldest still-active)
        else:
            supersede.append(r["gate_id"])      # orphan (advanced) or a duplicate
    if supersede:
        cur.execute("UPDATE gate SET status='superseded' WHERE gate_id::text = ANY(%s)", ([str(g) for g in supersede],))
        for gid in supersede:
            _audit(cur, "gate", gid, "gate_superseded", "system", {"stage": stage, "round_id": round_id})
    return keep


def open_gate(conn, stage, slot_ids=None, round_id=None, actor="system", cfg=None):
    """Open a batch gate over DRAFT_ASSIGNED slots for `stage`. Targets are the given
    slot_ids, else every DRAFT_ASSIGNED slot in round_id, else all DRAFT_ASSIGNED slots.
    Quorum is resolved from config and stored on the gate as an integer. Returns gate_id."""
    cfg = cfg or load_config()
    gc = stage_cfg(cfg, stage)
    policy = stage_approval_contract(cfg, stage, conn=conn)
    approvers = [_token_from_assignment(a["assignment_kind"], a["assignment_key"])
                 for a in policy["assignments"]]
    rule_key = policy["rule_key"]
    quorum_n = policy["quorum"]

    # which slot status(es) this gate reviews — a LIST lets a sign-off gate re-open over
    # finished-media stages (B3: native/scholar re-escalation at PRODUCED/EDITED).
    rs = gc.get("reviews_status", "DRAFT_ASSIGNED")
    statuses = rs if isinstance(rs, list) else [rs]
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #265 — serialize open/reuse PER round+stage inside this transaction (advisory xact lock,
    # self-released at commit/rollback): two concurrent FIRST opens must converge to one canonical
    # gate. The loser blocks here until the winner commits, then finds the winner's gate below and
    # reuses it — the active-gate lookup, target selection, creation/reconciliation, and audit all
    # share the lock's transaction, so no interleaving can observe "no gate" twice.
    if round_id:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (f"gate_open:{stage}", round_id))
    # IDEMPOTENT (round-scoped opens): one active review per round+stage. If an open gate already
    # exists, REUSE it (and supersede orphans/duplicates) — no second gate, no wrong-stage class.
    # On reuse we RECONCILE its target set (#265) so slots that became review-eligible AFTER the
    # gate first opened (partial/late generation, or a legacy inconsistent gate) are appended —
    # atomically, in this same transaction, before the commit.
    # #265 — server-authoritative generation-complete gate, BEFORE any reuse or open: a generated
    # stage must not start (or resurface) a review while its writer still owes input. A slot still
    # at the writer-input status is not-yet-generated (queued/claimed/retryable/job-poll-fallback
    # work all sit there until the writer flips it), and a still-running generation job marks the
    # in-flight window even when every row is already written — so this fails closed WITHOUT
    # inferring completeness from generated-row counts, and never false-blocks once every planned
    # slot has terminally generated.
    if round_id:
        pend = _generation_pending(cur, round_id, stage, gc)
        if pend:
            cur.close()
            raise GateNotReady(
                f"generation incomplete for {stage} · {round_id}: {pend['pending_input']} slot(s) "
                f"still awaiting generation"
                + ("; a generation job is in flight" if pend["running_job"] else "")
                + " — finish generating before starting review.")
    if round_id and not slot_ids:
        existing = _active_open_gate(cur, stage, round_id, statuses)
        if existing:
            _audit(cur, "gate", existing, "gate_reused", actor, {"stage": stage, "round_id": round_id})
            reconcile_gate_targets(cur, existing, cfg=cfg, actor=actor)
            conn.commit(); cur.close()
            return existing
    if slot_ids:
        cur.execute("SELECT slot_id FROM slot WHERE slot_id = ANY(%s) AND status::text = ANY(%s) "
                    "ORDER BY slot_id", (list(slot_ids), statuses))
    elif round_id:
        cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status::text = ANY(%s) "
                    "ORDER BY slot_id", (round_id, statuses))
    else:
        cur.execute("SELECT slot_id FROM slot WHERE status::text = ANY(%s) ORDER BY slot_id",
                    (statuses,))
    targets = [r["slot_id"] for r in cur.fetchall()]
    # #265 — slot-scoped/global opens (no round_id given) are guarded too: derive the candidate
    # rounds from the targets themselves and refuse while any of them still owes generator work.
    if targets and not round_id and gc.get("generator") == "ai":
        cur.execute("SELECT DISTINCT round_id FROM slot WHERE slot_id = ANY(%s) "
                    "AND round_id IS NOT NULL", (targets,))
        for rid_g in [x["round_id"] for x in cur.fetchall()]:
            pend = _generation_pending(cur, rid_g, stage, gc)
            if pend:
                cur.close()
                raise GateNotReady(
                    f"generation incomplete for {stage} · {rid_g}: {pend['pending_input']} slot(s) "
                    f"still awaiting generation"
                    + ("; a generation job is in flight" if pend["running_job"] else "")
                    + " — finish generating before starting review.")
    # sign-off gates only target slots that currently NEED a (fresh) sign-off — required, or
    # escalated and not yet signed after that escalation (re-escalation re-opens the requirement).
    requires_flag = gc.get("requires_flag")
    if requires_flag:
        spec = _spec_by(cfg, gate=stage)        # the review policy for this sign-off gate
        targets = [s for s in targets if spec and _review_pending(cur, s, spec, for_gate=True)]
    if not targets:
        raise GateError(f"no {statuses} slots match — nothing to gate for {stage}")

    # #423 — final-review whole-batch package validation BEFORE any insert. If any target is
    # unpinnable this raises TargetPackageNotReady and nothing is written (no gate/target/snapshot),
    # so the entire open rolls back with zero residue. Pure canonical reads; no authority is touched.
    fr_pkgs = _validate_final_review_batch(cur, targets) if stage == FINAL_REVIEW_STAGE else None

    cur.execute(
        "INSERT INTO gate (scope, stage, policy, rule_key, quorum, status) "
        "VALUES (%s,%s,%s,%s,%s,'open') RETURNING gate_id",
        (gc.get("scope", "batch"), stage, gc.get("policy", "fixed"), rule_key, str(quorum_n)))
    gate_id = cur.fetchone()["gate_id"]
    psycopg2.extras.execute_values(
        cur, "INSERT INTO gate_target (gate_id, slot_id) VALUES %s",
        [(gate_id, s) for s in targets])
    snapshots = [_assignment_snapshot(a) for a in approvers]
    if snapshots:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO gate_assignment (gate_id, assignment_kind, assignment_key, resolved_principal_id) VALUES %s",
            [(gate_id, s["assignment_kind"], s["assignment_key"], s["resolved_principal_id"])
             for s in snapshots],
        )
    # #282 (D3) — freeze the authoritative per-token snapshot at open: normalized required tokens +
    # the eligible effective principals for each. Every gate opened after migration 025 is
    # authoritative; ANY/ALL then resolve from durable per-token coverage, not a distinct-approver count.
    snapshot_id = _freeze_gate_snapshot(cur, gate_id, rule_key, approvers)
    # #423 — persist the immutable Stage-4 package snapshot for each initial final-review target,
    # atomically with the gate/target creation (all packages were pre-validated above).
    if stage == FINAL_REVIEW_STAGE:
        for s in targets:
            _insert_final_review_target_package(cur, gate_id, s, snapshot_id, fr_pkgs[s], actor)
    _audit(cur, "gate", gate_id, "gate_opened", actor,
           {"stage": stage, "targets": len(targets), "quorum": quorum_n, "rule_key": rule_key,
            "approvers": approvers, "authoritative": True})
    conn.commit()
    cur.close()
    return gate_id


def reconcile_gate_targets(cur, gate_id, cfg=None, actor="system"):
    """#265 — converge an OPEN gate's target set onto the CURRENTLY-eligible review-status slots for
    its round+stage. Append-only and idempotent: adds only missing eligible targets; never removes a
    target, alters a decision, duplicates a row, or targets a slot outside the configured review
    status. No missing targets => no write and no audit event.

    Runs on the caller's cursor INSIDE the caller's transaction, so reconciliation is atomic with the
    surrounding op (open-reuse / read / decide / resolve). The gate_target PK (gate_id, slot_id) plus
    `ON CONFLICT DO NOTHING RETURNING` make concurrent reconciles converge to one target per eligible
    slot with no duplicate rows and no duplicate `gate_targets_reconciled` audit events (only the
    statement that actually inserted a row sees it in RETURNING). Returns the slot_ids added."""
    cfg = cfg or load_config()
    cur.execute("SELECT stage, status FROM gate WHERE gate_id=%s", (gate_id,))
    g = cur.fetchone()
    if not g or g["status"] != "open":
        return []                              # only an OPEN gate is reconciled; closed gates are history
    stage = g["stage"]
    gc = stage_cfg(cfg, stage)
    rs = gc.get("reviews_status", "DRAFT_ASSIGNED")
    statuses = rs if isinstance(rs, list) else [rs]
    # a review gate is round-scoped; derive its round from its existing targets (never fabricate one)
    cur.execute("SELECT DISTINCT sl.round_id FROM gate_target t JOIN slot sl ON sl.slot_id=t.slot_id "
                "WHERE t.gate_id=%s", (gate_id,))
    rounds = [r["round_id"] for r in cur.fetchall()]
    if len(rounds) != 1:
        return []                              # empty (degenerate) or defensively cross-round — do nothing
    round_id = rounds[0]
    cur.execute("SELECT slot_id FROM slot WHERE round_id=%s AND status::text = ANY(%s) ORDER BY slot_id",
                (round_id, statuses))
    eligible = [r["slot_id"] for r in cur.fetchall()]
    # sign-off gates only target slots that still NEED a fresh sign-off (mirror open_gate exactly)
    if gc.get("requires_flag"):
        spec = _spec_by(cfg, gate=stage)
        eligible = [s for s in eligible if spec and _review_pending(cur, s, spec, for_gate=True)]
    cur.execute("SELECT slot_id FROM gate_target WHERE gate_id=%s", (gate_id,))
    existing = {r["slot_id"] for r in cur.fetchall()}
    missing = [s for s in eligible if s not in existing]
    if not missing:
        return []
    # #423 — final-review reconciliation is WHOLE-BATCH atomic: validate every missing candidate's
    # package BEFORE inserting any. If any is unpinnable, TargetPackageNotReady rolls the whole batch
    # (and the caller's open-reuse / decide / resolve / read op) back with zero target/snapshot/audit
    # residue — an attachment-readiness refusal, never an authorization result. A legacy gate with no
    # gate-wide snapshot keeps the existing append-only behavior (its targets read as unknown_history;
    # no backfill).
    fr_snapshot_id = None
    fr_pkgs = None
    if stage == FINAL_REVIEW_STAGE:
        fr_snapshot_id = _gate_snapshot_id(cur, gate_id)
        if not fr_snapshot_id:
            # #425 finding 1 — a legacy final-review gate has no gate-wide frozen snapshot, so a new
            # target cannot be admitted with the required package evidence. Fail closed with a typed
            # attachment-readiness refusal BEFORE any write (never an authorization result; it resolves
            # no membership/token/ANY-ALL/authority). Pre-existing legacy targets stay unknown_history —
            # never backfilled, reconstructed, or re-attested.
            raise TargetPackageNotReady(
                f"final-review gate {gate_id} has no gate-wide snapshot (legacy) — cannot admit new "
                f"targets {sorted(missing)} without package evidence; attachment not ready. No target, "
                "snapshot, or audit was written.", missing)
        fr_pkgs = _validate_final_review_batch(cur, missing)
    added = []
    for s in missing:
        cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s) "
                    "ON CONFLICT (gate_id, slot_id) DO NOTHING RETURNING slot_id", (gate_id, s))
        row = cur.fetchone()
        if row:
            added.append(row["slot_id"])
            if fr_snapshot_id:
                _insert_final_review_target_package(cur, gate_id, s, fr_snapshot_id, fr_pkgs[s], actor)
    if added:
        _audit(cur, "gate", gate_id, "gate_targets_reconciled", actor,
               {"stage": stage, "round_id": round_id, "prior_count": len(existing),
                "added": sorted(added), "added_count": len(added),
                "resulting_count": len(existing) + len(added)})
    return added


# --------------------------------------------------------------------------- #
# #423 — immutable final-review target-package snapshots at attachment
# --------------------------------------------------------------------------- #
FINAL_REVIEW_STAGE = "final_review"


def _derive_final_review_target_package(cur, slot_id):
    """Derive the immutable Stage-4 target package for `slot_id` from CANONICAL records in the current
    transaction. Returns a dict of package facts, or None if any required Topic/Script lineage or the
    consumed workflow provenance is unavailable (UNPINNABLE — the attachment must fail closed).

    Pure reads only. It never substitutes current heads, the active workflow, current membership, or UI
    labels. The production direction is OBSERVED (a plain SELECT) and recorded only when actually
    present AND coherent (its revision equals the selected script revision); its absence is not a defect
    here — only missing Topic/Script/workflow provenance makes the package unpinnable."""
    cur.execute("SELECT round_id FROM slot WHERE slot_id=%s", (slot_id,))
    srow = cur.fetchone()
    if not srow:
        return None
    round_id = srow["round_id"]
    cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='topic'", (slot_id,))
    tr = cur.fetchone()
    if not tr:
        return None
    cur.execute("SELECT topic_id, revision FROM topic WHERE slot_id=%s AND revision=%s",
                (slot_id, tr["revision"]))
    topic = cur.fetchone()
    if not topic:
        return None
    cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='script'", (slot_id,))
    sr = cur.fetchone()
    if not sr:
        return None
    cur.execute("SELECT script_id, revision FROM script WHERE slot_id=%s AND revision=%s",
                (slot_id, sr["revision"]))
    script = cur.fetchone()
    if not script:
        return None
    # consumed workflow version — script grain first, then the round plan snapshot; else unpinnable.
    cur.execute("SELECT workflow_version_id FROM script_provenance WHERE script_id=%s AND revision=%s",
                (script["script_id"], script["revision"]))
    prov = cur.fetchone()
    wv_id, wv_src = None, None
    if prov and prov["workflow_version_id"]:
        wv_id, wv_src = prov["workflow_version_id"], "script_provenance"
    else:
        cur.execute("SELECT workflow_version FROM round_policy_snapshot WHERE round_id=%s", (round_id,))
        snap = cur.fetchone()
        if snap and snap["workflow_version"]:
            wv_id, wv_src = snap["workflow_version"], "round_policy_snapshot"
    if not wv_id:
        return None
    # production direction — OBSERVE ONLY; record id/revision only when present AND coherent.
    cur.execute("SELECT directive_id, revision FROM directive WHERE slot_id=%s AND to_stage='production' "
                "AND type='production_directive' ORDER BY revision DESC, created_at DESC LIMIT 1", (slot_id,))
    d = cur.fetchone()
    pd_id = d["directive_id"] if d and d["revision"] == script["revision"] else None
    pd_rev = d["revision"] if pd_id is not None else None
    return {"round_id": round_id, "topic_id": topic["topic_id"], "topic_revision": topic["revision"],
            "script_id": script["script_id"], "script_revision": script["revision"],
            "workflow_version_id": wv_id, "workflow_version_source": wv_src,
            "production_directive_id": pd_id, "production_directive_revision": pd_rev}


def _validate_final_review_batch(cur, slot_ids):
    """Whole-batch pin: derive every candidate's package BEFORE any insert. Returns {slot_id: pkg} on
    success; raises TargetPackageNotReady naming the unpinnable candidate(s) so the batch rolls back
    with zero residue."""
    pkgs, unpinnable = {}, []
    for s in slot_ids:
        pkg = _derive_final_review_target_package(cur, s)
        if pkg is None:
            unpinnable.append(s)
        else:
            pkgs[s] = pkg
    if unpinnable:
        raise TargetPackageNotReady(
            "final-review target package cannot be pinned from canonical records for "
            f"{sorted(unpinnable)} — attachment not ready (Topic/Script lineage or consumed workflow "
            "provenance unavailable); no target, snapshot, or audit was written.", unpinnable)
    return pkgs


def _insert_final_review_target_package(cur, gate_id, slot_id, snapshot_id, pkg, actor):
    """Insert one immutable target-package snapshot for an attached (gate_id, slot_id). Idempotent via
    the PK + ON CONFLICT DO NOTHING RETURNING; the attachment audit is emitted ONLY from a successful
    insert, so replay never duplicates evidence (#423 ruling 5)."""
    cur.execute(
        "INSERT INTO final_review_target_package "
        "(gate_id, slot_id, snapshot_id, round_id, topic_id, topic_revision, script_id, script_revision, "
        " workflow_version_id, workflow_version_source, production_directive_id, production_directive_revision) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (gate_id, slot_id) DO NOTHING RETURNING slot_id",
        (gate_id, slot_id, snapshot_id, pkg["round_id"], pkg["topic_id"], pkg["topic_revision"],
         pkg["script_id"], pkg["script_revision"], pkg["workflow_version_id"], pkg["workflow_version_source"],
         pkg["production_directive_id"], pkg["production_directive_revision"]))
    inserted = cur.fetchone()
    if inserted:
        _audit(cur, "gate", gate_id, "final_review_target_package_attached", actor,
               {"slot_id": slot_id, "snapshot_id": str(snapshot_id),
                "topic_revision": pkg["topic_revision"], "script_revision": pkg["script_revision"],
                "workflow_version_source": pkg["workflow_version_source"]})
    return bool(inserted)


def _gate_snapshot_id(cur, gate_id):
    """The gate-wide frozen snapshot id, or None for a legacy (pre-025) gate with no snapshot."""
    cur.execute("SELECT snapshot_id FROM gate_snapshot WHERE gate_id=%s", (gate_id,))
    row = cur.fetchone()
    return row["snapshot_id"] if row else None


# --------------------------------------------------------------------------- #
# #364 — DURABLE generation truth for the shared gate guards and read projections.
#
# `gates/jobs.py` is an in-process registry with no database authority (it says so itself). Using its
# membership to answer "is generation still in progress?" fails in two distinct ways:
#
#   1. RESTART / EVICTION. The registry is a plain dict; a restart empties it. Durable queued or
#      running work then becomes invisible and a gate can commit over non-terminal generation.
#   2. VOCABULARY. `find_running` matches on a stage string, and two vocabularies are in play. Every
#      lookup passes the GATE stage ('topic_review'), because `stage_cfg` is keyed that way — but the
#      governed Stage 2A paths register the GENERATION stage ('topic') (gates/api.py, the manual
#      activate, retry, and post-commit dispatch sites). Those records therefore never match, in the
#      same live process, with no restart involved. Nothing errors; the lookup just always misses.
#
# The registry is KEPT for what it is actually good for — execution bookkeeping and /jobs/{id}
# progress polling. It simply stops being the authority for whether generation is in progress.
#
# The mapping below is explicit on purpose. No existing configuration value equals the durable stage
# string: `writer_mode` is 'topics'/'scripts' (plural) while `generation_job.stage` is
# 'topic'/'script'. Deriving one from the other by trimming a character would be invention.
GENERATION_STAGE_BY_GATE = {"topic_review": "topic", "script_review": "script"}

# TERMINAL is the CLOSED set, and everything else blocks. This direction matters:
# `generation_job.status` is unconstrained text with no CHECK, so enumerating the blocking states
# instead would fail OPEN for any status outside the enumeration — a future value, a corrupt row, a
# hand-edited record — and a gate would commit over work whose state nobody understands. Defining
# only "finished" and treating every other value as unfinished is the fail-CLOSED reading: an
# unrecognised status is by definition not a proven completion.
#
# The canonical non-terminal states remain `awaiting_trigger | queued | running`. `awaiting_trigger`
# is one of them because a manual-entry job is parked, not finished. Lease expiry is deliberately
# NOT terminal either — an expired lease means the attempt awaits the existing reclaim path, and
# treating it as completion is exactly the false "generation finished" this directive removes.
GENERATION_TERMINAL_STATUSES = ("completed", "partial", "failed")
GENERATION_BLOCKING_STATUSES = ("awaiting_trigger", "queued", "running")   # canonical, not exhaustive


def durable_generation_pending_rounds(cur, round_ids, gate_stage):
    """#364 — the rounds (of those given) that hold NON-TERMINAL durable generation work.

    ONE batched, non-mutating SELECT: the guard walks several rounds, and asking per round would be
    an N+1 inside a lock-holding transaction. Cursor-level by design — it runs inside the caller's
    open transaction, takes no connection, no lock and no commit, and needs no schema change.

    Non-terminal is defined by EXCLUSION from the closed terminal set, never by enumerating the
    blocking states — see GENERATION_TERMINAL_STATUSES. An unknown status blocks.

    Returns {round_id: job_id} for blocked rounds; empty when nothing is pending. A gate stage with
    no durable generation stage (every non-generative stage) maps to nothing and blocks nothing.
    """
    stage = GENERATION_STAGE_BY_GATE.get(gate_stage)
    if not stage or not round_ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (round_id) round_id, job_id::text AS job_id
                     FROM generation_job
                    WHERE round_id = ANY(%s) AND stage = %s AND NOT (status = ANY(%s))
                    ORDER BY round_id, created_at""",
                (list(round_ids), stage, list(GENERATION_TERMINAL_STATUSES)))
    out = {}
    for r in cur.fetchall():
        # RealDictCursor at some call sites, plain tuples at others — read by position-independent
        # access where possible so neither cursor factory silently changes the result.
        out[r["round_id"] if isinstance(r, dict) else r[0]] = (r["job_id"] if isinstance(r, dict)
                                                               else r[1])
    return out


def _durable_generation_job(cur, round_id, gate_stage):
    """Single-round convenience over the batched helper. Returns a job_id or None."""
    return durable_generation_pending_rounds(cur, [round_id], gate_stage).get(round_id)


def _generation_pending(cur, round_id, stage, gc):
    """#265 — the server-authoritative generation-completeness predicate for an AI-generated stage:
    truthy while ANY planned slot still owes generator work. Two signals, BOTH must be clear:
      - DB: slots still at the writer-input status (queued / claimed / retryable / job-poll-fallback
        work all sit there until the writer flips them) — restart-safe, never inferred from
        generated-row counts;
      - DURABLE (#364): a non-terminal `generation_job` row for this round+stage — covers the
        in-flight window where every row may already be written but the writer's pass has not
        terminally finished. Read from PostgreSQL, so it survives restart and registry eviction.
    Returns {"pending_input": n, "running_job": id|None}, or None when generation is complete
    (or the stage has no AI generator)."""
    if gc.get("generator") != "ai":
        return None
    n = _pending_input_count(cur, round_id, gc)
    # #364 — the in-flight signal is now the DURABLE job, not registry membership. Same predicate,
    # same return shape; only the source of truth changed.
    running = _durable_generation_job(cur, round_id, stage)
    if n or running:
        return {"pending_input": n, "running_job": running}
    return None


def _guard_generation_complete(cur, cfg, gate_id, stage, status, round_ids=None):
    """#265 — fail closed (GateNotReady) when an OPEN gate on an AI-generated stage is read,
    decided, or committed while its round still owes generator work: the eligible population is
    knowably in flux, so reconciliation cannot complete and no partial target set may be served or
    acted on. `round_ids` may be passed when already known; otherwise derived from the gate's own
    targets (never fabricated)."""
    gc = stage_cfg(cfg, stage)
    if status != "open" or gc.get("generator") != "ai":
        return
    if round_ids is None:
        cur.execute("SELECT DISTINCT sl.round_id FROM gate_target t JOIN slot sl "
                    "ON sl.slot_id=t.slot_id WHERE t.gate_id=%s", (gate_id,))
        round_ids = [r["round_id"] for r in cur.fetchall()]
    # #364 — ONE durable query for every round, then the per-round input count. Previously this
    # walked rounds calling the whole predicate each time (an N+1 inside a lock-holding transaction).
    durable = durable_generation_pending_rounds(cur, round_ids, stage)
    for rid in round_ids:
        n = _pending_input_count(cur, rid, gc)
        job = durable.get(rid)
        pend = {"pending_input": n, "running_job": job} if (n or job) else None
        if pend:
            raise GateNotReady(
                f"review for {stage} · {rid} is held until generation completes "
                f"({pend['pending_input']} item(s) still awaiting generation"
                + ("; a generation job is in flight" if pend["running_job"] else "")
                + ") — the open gate will be reconciled to the complete population before use.")


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def list_rounds(conn):
    """Rounds present, with how many slots sit at each review status — for a round selector."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #304 — starts_on rides the run selector so the V2 calendar can place runs from ONE read.
    # NULL is surfaced as-is: an unplaced run is rendered explicitly, never back-filled from
    # created_at and never hidden.
    cur.execute("SELECT max(r.label) AS label, max(r.period_len_days) AS period_len_days, "
                "max(r.posts_per_day) AS posts_per_day, max(r.starts_on) AS starts_on, "
                "slot.round_id, count(*) AS slots, "
                "count(*) FILTER (WHERE slot.status='RESERVED')          AS reserved, "
                "count(*) FILTER (WHERE slot.status='SCHEDULE_APPROVED') AS schedule_approved, "
                "count(*) FILTER (WHERE slot.status='TOPIC_PROPOSED')   AS topic_proposed, "
                "count(*) FILTER (WHERE slot.status='TOPIC_APPROVED')   AS topic_approved, "
                "count(*) FILTER (WHERE slot.status='CHANGES_REQUESTED') AS changes_requested, "
                "count(*) FILTER (WHERE slot.status='REJECTED')         AS rejected, "
                "count(*) FILTER (WHERE slot.status='DRAFT_ASSIGNED')   AS draft, "
                "count(*) FILTER (WHERE slot.status='APPROVED_ASSIGNED') AS approved, "
                "count(*) FILTER (WHERE slot.status='SCHEDULED')        AS scheduled "
                "FROM slot JOIN round r USING (round_id) "
                "WHERE slot.round_id IS NOT NULL GROUP BY slot.round_id ORDER BY slot.round_id")
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        r["phase"] = _round_phase(r)
    return rows


def list_principals(conn, kind=None, active=True, module=None, tenant_id=None):
    """Active principals with normalized role/group memberships — foundation read model for
    reviewer/user selection and future approval assignment UIs."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = """SELECT p.principal_id, p.kind, p.display_name_ar, p.display_name_en, p.role,
                  p.active, p.tenant_id, p.module,
                  coalesce(array_remove(array_agg(DISTINCT prm.role_id), NULL), '{}') AS roles,
                  coalesce(array_remove(array_agg(DISTINCT pgm.group_id), NULL), '{}') AS groups
           FROM principal p
           LEFT JOIN principal_role_member prm
             ON prm.principal_id=p.principal_id AND prm.active=true
           LEFT JOIN principal_group_member pgm
             ON pgm.principal_id=p.principal_id AND pgm.active=true"""
    where, params = [], []
    if kind:
        where.append("p.kind=%s"); params.append(kind)
    if active is not None:
        where.append("p.active=%s"); params.append(active)
    if module:
        where.append("p.module=%s"); params.append(module)
    if tenant_id:
        where.append("p.tenant_id=%s"); params.append(tenant_id)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " GROUP BY p.principal_id ORDER BY p.kind, p.principal_id"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def list_principal_roles(conn, active=True, module=None, tenant_id=None):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = """SELECT pr.role_id, pr.display_name_ar, pr.display_name_en, pr.active, pr.tenant_id, pr.module,
                  count(prm.principal_id) FILTER (WHERE prm.active=true) AS members
           FROM principal_role pr
           LEFT JOIN principal_role_member prm ON prm.role_id=pr.role_id"""
    where, params = [], []
    if active is not None:
        where.append("pr.active=%s"); params.append(active)
    if module:
        where.append("pr.module=%s"); params.append(module)
    if tenant_id:
        where.append("pr.tenant_id=%s"); params.append(tenant_id)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " GROUP BY pr.role_id ORDER BY pr.role_id"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def list_principal_groups(conn, active=True, module=None, tenant_id=None):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = """SELECT pg.group_id, pg.display_name_ar, pg.display_name_en, pg.active, pg.tenant_id, pg.module,
                  count(pgm.principal_id) FILTER (WHERE pgm.active=true) AS members
           FROM principal_group pg
           LEFT JOIN principal_group_member pgm ON pgm.group_id=pg.group_id"""
    where, params = [], []
    if active is not None:
        where.append("pg.active=%s"); params.append(active)
    if module:
        where.append("pg.module=%s"); params.append(module)
    if tenant_id:
        where.append("pg.tenant_id=%s"); params.append(tenant_id)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " GROUP BY pg.group_id ORDER BY pg.group_id"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def can_administer_approval_policies(conn, principal_id):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    principal = actors.load_principal(cur, principal_id)
    if not principal or principal.get("kind") != "user":
        cur.close()
        return False
    perms = set(principal.get("permissions") or [])
    if {"workflow.admin", "workflow.assign", "config.write"} & perms:
        cur.close()
        return True
    if principal.get("role") in {"content_owner", "admin", "workflow_admin"}:
        cur.close()
        return True
    cur.execute("""SELECT 1 FROM principal_role_member
                   WHERE principal_id=%s AND active=true
                     AND role_id IN ('content_owner', 'admin', 'workflow_admin')""", (principal_id,))
    ok = cur.fetchone() is not None
    cur.close()
    return ok


def list_stage_approval_policies(conn, principal_id=None, cfg=None):
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        return {
            "can_administer": bool(principal_id and can_administer_approval_policies(conn, principal_id)),
            "policies": [_approval_policy_read_model(cur, cfg, stage)
                         for stage in (cfg.get("gates") or {}).keys()],
        }
    finally:
        cur.close()


def update_stage_approval_policy(conn, stage, policy, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer approval policies")
    cfg = load_config()
    stage_cfg(cfg, stage)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _approval_policy_read_model(cur, cfg, stage)
        rule = _canonical_rule(policy.get("rule") or policy.get("rule_key") or before["rule_key"])
        assignments = _policy_assignments(policy)
        if not any(assignments.values()):
            raise GateError("approval policy needs at least one user, role, or group")
        _validate_policy_assignments(cur, assignments)
        cur.execute("""INSERT INTO approval_policy (stage, rule_key, updated_by, tenant_id, module)
                       VALUES (%s,%s,%s,'default','content')
                       ON CONFLICT (stage, tenant_id, module)
                       DO UPDATE SET rule_key=EXCLUDED.rule_key, updated_by=EXCLUDED.updated_by,
                                     updated_at=now()
                       RETURNING policy_id""", (stage, _normalize_rule_key(rule), actor))
        policy_id = cur.fetchone()["policy_id"]
        cur.execute("DELETE FROM approval_policy_assignment WHERE policy_id=%s", (policy_id,))
        rows = []
        for key in assignments["users"]:
            rows.append((policy_id, "user", key))
        for key in assignments["roles"]:
            rows.append((policy_id, "role", key))
        for key in assignments["groups"]:
            rows.append((policy_id, "group", key))
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO approval_policy_assignment (policy_id, assignment_kind, assignment_key)
               VALUES %s""",
            rows,
        )
        after = _approval_policy_read_model(cur, cfg, stage)
        _audit(cur, "approval_policy", stage, "approval_policy_updated", actor, {
            "stage": stage,
            "before": before,
            "after": after,
        })
        conn.commit()
        return {**after, "updated_by": actor}
    finally:
        cur.close()


# --------------------------------------------------------------------------- #
# #190 (#172 S1) — authenticated-user → principal binding (read model only)
# IAM proves identity; Tanaghom decides authority. This lookup is the ONLY thing IdP identity
# feeds: which operating principal (if any) an authenticated (issuer, subject) is bound to.
# Nothing here is an authorization input — authority stays with assignments/policies/hard floors.
# --------------------------------------------------------------------------- #
def resolve_user_identity(conn, issuer, subject):
    """Return the ACTIVE binding for (issuer, subject) or None. SELECT-only."""
    if not issuer or not subject:
        return None
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT ui.principal_id, ui.email, ui.display_name,
                          p.display_name_en AS principal_display_name_en, p.kind AS principal_kind,
                          p.active AS principal_active
                   FROM user_identity ui
                   JOIN principal p ON p.principal_id = ui.principal_id
                   WHERE ui.issuer=%s AND ui.subject=%s AND ui.active=true""", (issuer, subject))
    row = cur.fetchone()
    cur.close()
    if not row or not row["principal_active"] or row["principal_kind"] != "user":
        # inactive principals and non-user principals never become an authenticated human's identity
        return None
    return row


# --------------------------------------------------------------------------- #
# #194 (#172 S2) — governed identity-binding lifecycle administration
# Administers AUTHENTICATION bindings only. Authority comes from the SAME persisted policy_admin
# contract (#184) that #172 designated for binding administration — never from IdP claims, request
# fields, or client state. principal_id is never updated on an existing row (no reassignment).
# --------------------------------------------------------------------------- #
IDENTITY_FIELD_LIMITS = {"issuer": 512, "subject": 512, "email": 320, "display_name": 200}
IDENTITY_LIST_MAX_LIMIT = 100


def can_administer_identity_bindings(conn, principal_id, cfg=None):
    """#194 — same persisted authority contract as policy administration (engine.policy_admin),
    designated for identity-binding administration by the #172 architecture decision."""
    return can_administer_repetition_policy(conn, principal_id, cfg)


def _identity_field(payload, name, required=False):
    raw = payload.get(name)
    if raw is None or str(raw).strip() == "":
        if required:
            raise GateError(f"{name} is required")
        return None
    value = str(raw).strip()
    limit = IDENTITY_FIELD_LIMITS[name]
    if len(value) > limit:
        raise GateError(f"{name} exceeds {limit} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise GateError(f"{name} contains control characters")
    return value


def _identity_subject(payload):
    """#195 review — subjects are OPAQUE, case-sensitive identifiers: preserved exactly as
    entered (no trimming, case folding, or Unicode rewriting). Prohibited/overlong/wrong-type
    input is rejected, never repaired or coerced."""
    raw = payload.get("subject")
    if raw is None or raw == "":
        raise GateError("subject is required")
    if not isinstance(raw, str):
        raise GateError("subject must be a string")
    value = raw
    if len(value) > IDENTITY_FIELD_LIMITS["subject"]:
        raise GateError(f"subject exceeds {IDENTITY_FIELD_LIMITS['subject']} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise GateError("subject contains control characters")
    return value


def _expected_canonical_issuer():
    """The trusted server-configured canonical issuer (same canonical form S1 produces), when the
    runtime knows it. None when unconfigured (dev/test DBs without a live IdP)."""
    raw = (os.environ.get("TANAGHOM_OIDC_ISSUER") or "").strip()
    return raw.rstrip("/") or None


def _identity_issuer(payload):
    """#195 re-review — the trusted canonical issuer comes ONLY from server configuration
    (TANAGHOM_OIDC_ISSUER on the gate API): issuer-dependent administration FAILS CLOSED when it
    is absent — request or row data is never self-validating. Submitted input must equal the
    configured issuer exactly; noncanonical input (padding, trailing slash) is rejected, never
    silently normalized."""
    expected = _expected_canonical_issuer()
    if not expected:
        raise GateError("identity-binding administration requires the gate API's configured "
                        "sign-in provider (TANAGHOM_OIDC_ISSUER) — refusing rather than trusting "
                        "request data")
    raw = payload.get("issuer")
    if raw is None or raw == "":
        raise GateError("issuer is required")
    if not isinstance(raw, str):
        raise GateError("issuer must be a string")
    value = raw
    if len(value) > IDENTITY_FIELD_LIMITS["issuer"]:
        raise GateError(f"issuer exceeds {IDENTITY_FIELD_LIMITS['issuer']} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise GateError("issuer contains control characters")
    if value != value.strip():
        raise GateError("issuer has leading/trailing whitespace — enter the exact canonical issuer")
    if value.endswith("/"):
        raise GateError("issuer must be canonical (no trailing slash) — matching S1 session issuers")
    if value != expected:
        raise GateError(f"issuer must be this server's configured sign-in provider ({expected})")
    return value


def audit_identity_rejection(conn, actor, operation, error):
    """#195 re-review — attributable rejection audit for request-shape failures caught at the API
    layer AFTER signed-actor verification (unauthenticated noise never reaches this)."""
    _identity_denied(conn, actor, "identity_binding.denied",
                     {"operation": operation, "reason": "invalid_input", "error": str(error)[:300]})


def _identity_denied(conn, actor, action, detail):
    # attributable denial/rejection: audited in its OWN committed transaction (survives the raise)
    audit_denied(conn, "user_identity", detail.get("identity_id") or detail.get("subject") or "-",
                 action, actor, detail)


def _identity_row(cur, identity_id):
    cur.execute("""SELECT ui.identity_id::text AS identity_id, ui.issuer, ui.subject,
                          ui.principal_id, ui.email, ui.display_name, ui.active,
                          ui.created_by, ui.created_at, ui.updated_by, ui.updated_at,
                          p.display_name_en AS principal_display_name_en,
                          p.kind AS principal_kind, p.active AS principal_active
                   FROM user_identity ui JOIN principal p ON p.principal_id = ui.principal_id
                   WHERE ui.identity_id::text=%s""", (str(identity_id),))
    return cur.fetchone()


def list_user_identities(conn, principal_id, limit=25, offset=0, cfg=None):
    """Bounded, authorized, deterministic list (issuer, subject order; server pagination)."""
    cfg = cfg or load_config()
    if not can_administer_identity_bindings(conn, principal_id, cfg):
        _identity_denied(conn, principal_id, "identity_binding.denied",
                         {"operation": "list", "reason": "not_identity_admin"})
        raise GateError(f"{principal_id!r} may not administer identity bindings")
    limit = max(1, min(int(limit or 25), IDENTITY_LIST_MAX_LIMIT))
    offset = max(0, int(offset or 0))
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT count(*) AS n FROM user_identity")
    total = cur.fetchone()["n"]
    cur.execute("""SELECT ui.identity_id::text AS identity_id, ui.issuer, ui.subject,
                          ui.principal_id, ui.email, ui.display_name, ui.active,
                          ui.created_by, ui.created_at, ui.updated_by, ui.updated_at,
                          p.display_name_en AS principal_display_name_en,
                          p.active AS principal_active
                   FROM user_identity ui JOIN principal p ON p.principal_id = ui.principal_id
                   ORDER BY ui.issuer, ui.subject
                   LIMIT %s OFFSET %s""", (limit, offset))
    rows = cur.fetchall()
    cur.close()
    return {"bindings": rows, "total": total, "limit": limit, "offset": offset}


def create_user_identity(conn, payload, actor="system", cfg=None):
    """Insert-only create of one exact (issuer, subject) -> principal binding. Duplicate tuples
    (active OR inactive) are explicit conflicts — never a silent overwrite/upsert."""
    cfg = cfg or load_config()
    if not can_administer_identity_bindings(conn, actor, cfg):
        _identity_denied(conn, actor, "identity_binding.denied",
                         {"operation": "create", "reason": "not_identity_admin"})
        raise GateError(f"{actor!r} may not administer identity bindings")
    # #195 review — every attributable validation rejection of an AUTHENTICATED admin is audited
    # (no partial mutation state exists yet: validation precedes all writes).
    try:
        issuer = _identity_issuer(payload)          # exact canonical form only, never normalized
        subject = _identity_subject(payload)        # preserved EXACTLY (opaque, case-sensitive)
        email = _identity_field(payload, "email")
        display_name = _identity_field(payload, "display_name")
        target_raw = payload.get("principal_id")
        if target_raw is not None and not isinstance(target_raw, str):
            raise GateError("principal_id must be a string")
        target = (target_raw or "").strip()
        if not target:
            raise GateError("principal_id is required")
    except GateError as e:
        _identity_denied(conn, actor, "identity_binding.denied",
                         {"operation": "create", "reason": "invalid_input", "error": str(e)})
        raise
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT principal_id, kind, active FROM principal WHERE principal_id=%s", (target,))
        p = cur.fetchone()
        if not p or not p["active"] or p["kind"] != "user":
            _identity_denied(conn, actor, "identity_binding.denied",
                             {"operation": "create", "reason": "invalid_target",
                              "target_principal": target, "subject": subject})
            raise GateError(f"binding target must be an existing ACTIVE user principal (got {target!r})")
        cur.execute("""INSERT INTO user_identity (issuer, subject, principal_id, email, display_name,
                                                  created_by, updated_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (issuer, subject) DO NOTHING
                       RETURNING identity_id::text AS identity_id""",
                    (issuer, subject, target, email, display_name, actor, actor))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            _identity_denied(conn, actor, "identity_binding.conflict",
                             {"operation": "create", "reason": "duplicate_tuple", "subject": subject,
                              "issuer": issuer,
                              "hint": "the tuple already exists (active or inactive); use reactivate"})
            raise GateError("conflict: a binding for this issuer + subject already exists "
                            "(reactivate the existing one instead — bindings are never overwritten)")
        _audit(cur, "user_identity", row["identity_id"], "identity_binding.created", actor, {
            "issuer": issuer, "subject": subject, "target_principal": target,
            "resulting_status": "active",
        })
        conn.commit()
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        out = _identity_row(cur2, row["identity_id"])
        cur2.close()
        return out
    finally:
        cur.close()


def _other_usable_identity_admin_exists(cur, cfg, exclude_identity_id, usable_issuer):
    """#194/#195 self-lockout proof: another ACTIVE binding **for the currently usable issuer**
    (the server-configured canonical issuer, else the issuer of the binding being deactivated —
    a stale/different-issuer binding cannot be signed in with and therefore never counts) to an
    ACTIVE user principal satisfying the policy_admin contract."""
    roles, perms = _policy_admin_contract(cfg)
    cur.execute("""SELECT count(*) AS n
                   FROM user_identity ui
                   JOIN principal p ON p.principal_id = ui.principal_id
                   WHERE ui.active = true
                     AND ui.identity_id::text <> %s
                     AND ui.issuer = %s
                     AND p.active = true AND p.kind = 'user'
                     AND (p.role = ANY(%s)
                          OR p.permissions ?| %s
                          OR EXISTS (SELECT 1 FROM principal_role_member m
                                     WHERE m.principal_id = p.principal_id AND m.active = true
                                       AND m.role_id = ANY(%s)))""",
                (str(exclude_identity_id), usable_issuer, sorted(roles), sorted(perms), sorted(roles)))
    return cur.fetchone()["n"] > 0


def _binding_is_admin_usable(cur, cfg, row, usable_issuer):
    """Is THIS binding one an identity administrator could currently sign in with?"""
    if not row["active"] or row["issuer"] != usable_issuer:
        return False
    if not row["principal_active"] or row["principal_kind"] != "user":
        return False
    roles, perms = _policy_admin_contract(cfg)
    cur.execute("""SELECT 1 FROM principal p
                   WHERE p.principal_id = %s
                     AND (p.role = ANY(%s)
                          OR p.permissions ?| %s
                          OR EXISTS (SELECT 1 FROM principal_role_member m
                                     WHERE m.principal_id = p.principal_id AND m.active = true
                                       AND m.role_id = ANY(%s)))""",
                (row["principal_id"], sorted(roles), sorted(perms), sorted(roles)))
    return cur.fetchone() is not None


def set_user_identity_active(conn, identity_id, active_target, actor="system", cfg=None):
    """Compare-and-set lifecycle transition (deactivate: true->false; same-tuple reactivate:
    false->true). principal_id is NEVER modified. Stale/concurrent transitions return explicit
    conflicts. Self-deactivation fails closed unless another usable identity admin remains."""
    cfg = cfg or load_config()
    if not can_administer_identity_bindings(conn, actor, cfg):
        _identity_denied(conn, actor, "identity_binding.denied",
                         {"operation": "deactivate" if not active_target else "reactivate",
                          "identity_id": str(identity_id), "reason": "not_identity_admin"})
        raise GateError(f"{actor!r} may not administer identity bindings")
    op = "reactivate" if active_target else "deactivate"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        row = _identity_row(cur, identity_id)
        if not row:
            _identity_denied(conn, actor, "identity_binding.denied",
                             {"operation": op, "identity_id": str(identity_id),
                              "reason": "unknown_binding"})
            raise GateError(f"no such binding {identity_id}")
        if active_target and (not row["principal_active"] or row["principal_kind"] != "user"):
            _identity_denied(conn, actor, "identity_binding.denied",
                             {"operation": op, "identity_id": str(identity_id),
                              "reason": "target_ineligible", "target_principal": row["principal_id"]})
            raise GateError("conflict: the bound principal is no longer an active user principal")
        if not active_target:
            # #195 review — the lockout invariant is CROSS-ROW (two admins concurrently
            # deactivating distinct own bindings would each see the other still active), so any
            # deactivation of an admin-usable binding serializes on a transaction-scoped advisory
            # lock, re-reads under the lock, and requires ANOTHER currently usable admin binding —
            # usable meaning: for the exact issuer sign-ins actually use (the server-configured
            # canonical issuer when known, else this binding's own issuer — a stale/different
            # issuer never counts). Applies to self AND non-self deactivation: the last usable
            # administrator sign-in can never be removed by anyone.
            # #195 re-review — the trusted issuer comes ONLY from server configuration; without it
            # administrator-lockout safety cannot be proven, so deactivation FAILS CLOSED (row or
            # request data is never a substitute for the trusted issuer).
            usable_issuer = _expected_canonical_issuer()
            if not usable_issuer:
                _identity_denied(conn, actor, "identity_binding.denied",
                                 {"operation": op, "identity_id": str(identity_id),
                                  "reason": "issuer_config_absent"})
                raise GateError("deactivation requires the gate API's configured sign-in provider "
                                "(TANAGHOM_OIDC_ISSUER) — lockout safety cannot be proven without it")
            if _binding_is_admin_usable(cur, cfg, row, usable_issuer):
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('user_identity_admin_lockout')::bigint)")
                row = _identity_row(cur, identity_id)   # re-read under the serialization lock
                if row and row["active"] \
                        and not _other_usable_identity_admin_exists(cur, cfg, identity_id, usable_issuer):
                    _identity_denied(conn, actor, "identity_binding.denied",
                                     {"operation": op, "identity_id": str(identity_id),
                                      "reason": "last_usable_admin_lockout",
                                      "usable_issuer": usable_issuer,
                                      "target_principal": row["principal_id"]})
                    raise GateError("conflict: this is the last usable administrator sign-in — "
                                    "deactivating it would lock administration out")
                if not row:
                    _identity_denied(conn, actor, "identity_binding.denied",
                                     {"operation": op, "identity_id": str(identity_id),
                                      "reason": "unknown_binding"})
                    raise GateError(f"no such binding {identity_id}")
        cur.execute("""UPDATE user_identity
                       SET active=%s, updated_by=%s, updated_at=now()
                       WHERE identity_id::text=%s AND active=%s
                       RETURNING identity_id""",
                    (active_target, actor, str(identity_id), not active_target))
        if not cur.fetchone():
            conn.rollback()
            _identity_denied(conn, actor, "identity_binding.conflict",
                             {"operation": op, "identity_id": str(identity_id),
                              "reason": "stale_state",
                              "hint": "the binding changed concurrently; refetch and retry"})
            raise GateError("conflict: the binding was changed by someone else — refresh and retry")
        _audit(cur, "user_identity", str(identity_id),
               f"identity_binding.{'reactivated' if active_target else 'deactivated'}", actor, {
                   "issuer": row["issuer"], "subject": row["subject"],
                   "target_principal": row["principal_id"],
                   "previous_status": "inactive" if active_target else "active",
                   "resulting_status": "active" if active_target else "inactive",
               })
        conn.commit()
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        out = _identity_row(cur2, identity_id)
        cur2.close()
        return out
    finally:
        cur.close()


# --------------------------------------------------------------------------- #
# #184 — managed topic-repetition policy (foundation)
# The ACTIVE dedup/repetition policy is DB-managed and centrally derived here; the writers
# consume effective_repetition_policy() instead of reading scattered config. audit_log carries
# the change/exception history; the repetition_policy row is the persistence (migration 020).
# --------------------------------------------------------------------------- #
REPETITION_POLICY_KEY = "topic_generation"
REPETITION_SCOPES = ("all", "round", "hcs", "current_cycle")
# Modes enforceable with the CURRENT data model (slot.format). The jsonb column keeps the model
# open (e.g. cross_platform once platform is a slot-level dimension) — unknown modes are rejected
# rather than silently accepted, so the policy never overstates what it enforces.
REPETITION_REPEAT_MODES = ("cross_format",)


def _policy_admin_contract(cfg):
    """#184 — who holds top-level policy authority NOW. Config-driven seam (engine.policy_admin)
    rather than user ids: today's real holder is the super admin / content owner; the future
    unified-principal / AgentRep direction remaps this in ONE place without touching enforcement."""
    pa = (cfg.get("engine") or {}).get("policy_admin") or {}
    roles = set(pa.get("roles") or ["super_admin", "admin", "content_owner"])
    perms = set(pa.get("permissions") or ["config.write", "policy.admin"])
    return roles, perms


def can_administer_repetition_policy(conn, principal_id, cfg=None):
    cfg = cfg or load_config()
    roles, perms = _policy_admin_contract(cfg)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        principal = actors.load_principal(cur, principal_id)
        if not principal or principal.get("kind") != "user":
            return False
        if set(principal.get("permissions") or []) & perms:
            return True
        if principal.get("role") in roles:
            return True
        cur.execute("""SELECT 1 FROM principal_role_member
                       WHERE principal_id=%s AND active=true AND role_id = ANY(%s)""",
                    (principal_id, sorted(roles)))
        return cur.fetchone() is not None
    finally:
        cur.close()


def effective_repetition_policy(conn, cfg=None, tenant_id="default", module="content"):
    """#184 — the single derivation point for the ACTIVE topic-repetition policy, scoped by
    (tenant, module). A managed DB row wins; otherwise the strict production default applies: NO
    same-topic reuse across ALL prior history (#183 — the legacy config `scope: hcs` was too narrow
    and is deliberately no longer the effective default), with the legacy config tunables
    (threshold / regeneration tries / enabled) as the bootstrap fallback. `policy_id` is the source
    row's UUID (None for the production default) — the lineage a #310 snapshot pins to."""
    cfg = cfg or load_config()
    legacy = (cfg.get("engine") or {}).get("dedup_safety_net") or {}
    policy = {
        "policy_key": REPETITION_POLICY_KEY,
        "policy_id": None,
        "enabled": bool(legacy.get("enabled", True)),
        "scope": "all",
        "similarity_threshold": float(legacy.get("similarity_threshold", 0.86)),
        "max_regenerations": int(legacy.get("max_regenerations", 3)),
        "repeat_modes": {},
        "source": "production_default",
        "updated_by": None,
        "updated_at": None,
    }
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT policy_id, enabled, scope, similarity_threshold, max_regenerations,
                          repeat_modes, updated_by, updated_at
                   FROM repetition_policy
                   WHERE policy_key=%s AND tenant_id=%s AND module=%s""",
                (REPETITION_POLICY_KEY, tenant_id, module))
    row = cur.fetchone()
    cur.close()
    if row:
        policy.update({
            "policy_id": str(row["policy_id"]),
            "enabled": bool(row["enabled"]),
            "scope": row["scope"],
            "similarity_threshold": (float(row["similarity_threshold"])
                                     if row["similarity_threshold"] is not None
                                     else policy["similarity_threshold"]),
            "max_regenerations": (int(row["max_regenerations"])
                                  if row["max_regenerations"] is not None
                                  else policy["max_regenerations"]),
            "repeat_modes": {k: bool(v) for k, v in (row["repeat_modes"] or {}).items()},
            "source": "managed",
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        })
    return policy


def get_repetition_policy(conn, principal_id=None, cfg=None):
    """Read model: the effective policy + what the model supports + whether the caller may edit."""
    cfg = cfg or load_config()
    return {
        "policy": effective_repetition_policy(conn, cfg),
        "scopes": list(REPETITION_SCOPES),
        "repeat_modes_supported": list(REPETITION_REPEAT_MODES),
        "can_administer": bool(principal_id and can_administer_repetition_policy(conn, principal_id, cfg)),
    }


def update_repetition_policy(conn, policy, actor="system", cfg=None):
    """#184 — top-level-authority-gated policy write, audited with before/after."""
    cfg = cfg or load_config()
    if not can_administer_repetition_policy(conn, actor, cfg):
        audit_denied(conn, "repetition_policy", REPETITION_POLICY_KEY,
                     "repetition_policy_update_denied", actor,
                     {"reason": "not_policy_admin", "requested": policy})
        raise GateError(f"{actor!r} may not administer the repetition policy")
    # SPARSE update semantics: omitted (None/absent) fields preserve the current managed/effective
    # state — a partial write never resets unrelated fields. `repeat_modes`, when provided, is the
    # full statement of active modes (pass {} to clear them); when omitted, existing modes persist.
    before = effective_repetition_policy(conn, cfg)
    scope = str(policy["scope"]).strip() if policy.get("scope") is not None else before["scope"]
    if scope not in REPETITION_SCOPES:
        raise GateError(f"bad scope {scope!r} (expected one of {REPETITION_SCOPES})")
    modes_in = policy.get("repeat_modes")
    modes = ({k: bool(v) for k, v in modes_in.items()} if modes_in is not None
             else dict(before["repeat_modes"]))
    unknown = set(modes) - set(REPETITION_REPEAT_MODES)
    if unknown:
        raise GateError(f"unsupported repeat modes {sorted(unknown)} "
                        f"(supported/enforceable now: {list(REPETITION_REPEAT_MODES)})")
    threshold = (float(policy["similarity_threshold"])
                 if policy.get("similarity_threshold") is not None
                 else before["similarity_threshold"])
    if not 0.5 <= threshold <= 1.0:
        raise GateError(f"similarity_threshold {threshold} out of range (0.5–1.0)")
    tries = (int(policy["max_regenerations"]) if policy.get("max_regenerations") is not None
             else before["max_regenerations"])
    if not 0 <= tries <= 10:
        raise GateError(f"max_regenerations {tries} out of range (0–10)")
    enabled = bool(policy["enabled"]) if policy.get("enabled") is not None else before["enabled"]
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""INSERT INTO repetition_policy
                       (policy_key, enabled, scope, similarity_threshold, max_regenerations,
                        repeat_modes, updated_by, tenant_id, module)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'default','content')
                       ON CONFLICT (policy_key, tenant_id, module)
                       DO UPDATE SET enabled=EXCLUDED.enabled, scope=EXCLUDED.scope,
                                     similarity_threshold=EXCLUDED.similarity_threshold,
                                     max_regenerations=EXCLUDED.max_regenerations,
                                     repeat_modes=EXCLUDED.repeat_modes,
                                     updated_by=EXCLUDED.updated_by, updated_at=now()""",
                    (REPETITION_POLICY_KEY, enabled, scope, threshold, tries, Json(modes), actor))
        after = effective_repetition_policy(conn, cfg)
        _audit(cur, "repetition_policy", REPETITION_POLICY_KEY, "repetition_policy_updated", actor,
               {"before": before, "after": after})
        conn.commit()
    finally:
        cur.close()
    return get_repetition_policy(conn, principal_id=actor, cfg=cfg)


def _ordered_workflow_stage_keys(cfg):
    configured = list((cfg.get("gates") or {}).keys())
    preferred = [stage for stage, _ in WORKFLOW_STAGE_LIBRARY if stage in configured]
    extras = [stage for stage in configured if stage not in preferred]
    return preferred + extras


def _stage_review_statuses(gc):
    statuses = gc.get("reviews_status")
    if isinstance(statuses, list):
        return statuses
    return [statuses] if statuses else []


def _workflow_stage_seed_rows(cfg):
    rows = []
    for ordinal, stage_key in enumerate(_ordered_workflow_stage_keys(cfg), start=1):
        gc = stage_cfg(cfg, stage_key)
        meta = WORKFLOW_STAGE_META.get(stage_key, {"label": stage_key, "group": "Workflow"})
        contract = stage_approval_contract(cfg, stage_key)
        rows.append({
            "stage_key": stage_key,
            "stage_label": meta["label"],
            "stage_group": meta["group"],
            "ordinal": ordinal,
            "enabled": True,
            "bypassable": bool(gc.get("policy") == "adhoc"),
            "mandatory": gc.get("kind", "transition") != "signoff",
            "gate_stage": stage_key,
            "stage_kind": gc.get("kind", "transition"),
            "generator_kind": gc.get("generator"),
            "scope": gc.get("scope"),
            "policy": gc.get("policy"),
            "review_statuses": _stage_review_statuses(gc),
            "approve_to": gc.get("approve_to"),
            "changes_to": gc.get("changes_to"),
            "reject_to": gc.get("reject_to"),
            "rework_mode": gc.get("rework_mode"),
            "generates_from": gc.get("generates_from"),
            "writer_mode": gc.get("writer_mode"),
            "requires_flag": gc.get("requires_flag"),
            "allow_partial_batch": bool(gc.get("allow_partial_batch")),
            "enforce_mandatory_reviews": bool(gc.get("enforce_mandatory_reviews")),
            "approval_rule": contract["rule_key"],
        })
    return rows


def _workflow_transition_seed_rows(stage_keys):
    allowed = set(stage_keys)
    rows = []
    for from_stage, to_stage, condition_key in DEFAULT_WORKFLOW_TRANSITIONS:
        if from_stage in allowed and to_stage in allowed:
            rows.append({
                "from_stage_key": from_stage,
                "to_stage_key": to_stage,
                "condition_key": condition_key,
                "enabled": True,
            })
    return rows


def _seed_workflow_version(cur, workflow_id, version_no, status, source, actor, cfg, notes=None):
    cur.execute("""INSERT INTO workflow_version
                   (workflow_id, version_no, status, source, notes, created_by, updated_by,
                    activated_by, activated_at, tenant_id, module)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                           CASE WHEN %s='active' THEN now() ELSE NULL END,
                           'default','content')
                   RETURNING version_id""",
                (workflow_id, version_no, status, source, notes, actor, actor,
                 actor if status == "active" else None, status))
    version_id = str(cur.fetchone()["version_id"])
    stage_rows = _workflow_stage_seed_rows(cfg)
    psycopg2.extras.execute_values(
        cur,
        """INSERT INTO workflow_stage
           (version_id, stage_key, stage_label, stage_group, ordinal, enabled, bypassable, mandatory,
            gate_stage, stage_kind, generator_kind, scope, policy, review_statuses, approve_to,
            changes_to, reject_to, rework_mode, generates_from, writer_mode, requires_flag,
            allow_partial_batch, enforce_mandatory_reviews, approval_rule)
           VALUES %s""",
        [(
            version_id, row["stage_key"], row["stage_label"], row["stage_group"], row["ordinal"],
            row["enabled"], row["bypassable"], row["mandatory"], row["gate_stage"],
            row["stage_kind"], row["generator_kind"], row["scope"], row["policy"],
            Json(row["review_statuses"]), row["approve_to"], row["changes_to"], row["reject_to"],
            row["rework_mode"], row["generates_from"], row["writer_mode"], row["requires_flag"],
            row["allow_partial_batch"], row["enforce_mandatory_reviews"], row["approval_rule"],
        ) for row in stage_rows],
    )
    transition_rows = _workflow_transition_seed_rows([row["stage_key"] for row in stage_rows])
    if transition_rows:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO workflow_transition
               (version_id, from_stage_key, to_stage_key, condition_key, enabled)
               VALUES %s""",
            [(
                version_id, row["from_stage_key"], row["to_stage_key"], row["condition_key"],
                row["enabled"],
            ) for row in transition_rows],
        )
    return version_id


def _ensure_workflow_seed(conn, cfg=None, actor="system"):
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT version_id FROM workflow_version
                       WHERE tenant_id='default' AND module='content' AND status='active'
                       ORDER BY activated_at DESC NULLS LAST, created_at DESC
                       LIMIT 1""")
        if cur.fetchone():
            return
        cur.execute("""INSERT INTO workflow (workflow_key, name, description, created_by, tenant_id, module)
                       VALUES (%s,%s,%s,%s,'default','content')
                       ON CONFLICT (workflow_key, tenant_id, module)
                       DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description,
                                     updated_at=now()
                       RETURNING workflow_id""",
                    (WORKFLOW_KEY, "Content pipeline", "Default Tanaghom workflow", actor))
        workflow_id = str(cur.fetchone()["workflow_id"])
        cur.execute("SELECT coalesce(max(version_no), 0) AS max_version FROM workflow_version WHERE workflow_id=%s",
                    (workflow_id,))
        version_no = int(cur.fetchone()["max_version"]) + 1
        version_id = _seed_workflow_version(cur, workflow_id, version_no, "active", "seed", actor, cfg,
                                            notes="Seeded from system_config.yaml")
        _audit(cur, "workflow_version", version_id, "workflow_version_seeded", actor, {
            "workflow_key": WORKFLOW_KEY,
            "version_no": version_no,
        })
        conn.commit()
    finally:
        cur.close()


def _workflow_stage_read_model(cur, version_id):
    cur.execute("""SELECT stage_id::text AS stage_id, stage_key, stage_label, stage_group, ordinal,
                          enabled, bypassable, mandatory, gate_stage, stage_kind, generator_kind,
                          scope, policy, review_statuses, approve_to, changes_to, reject_to,
                          rework_mode, generates_from, writer_mode, requires_flag,
                          allow_partial_batch, enforce_mandatory_reviews, approval_rule
                   FROM workflow_stage
                   WHERE version_id=%s
                   ORDER BY ordinal, stage_key""", (version_id,))
    rows = cur.fetchall()
    for row in rows:
        row["review_statuses"] = list(row.get("review_statuses") or [])
    return rows


def _workflow_transition_read_model(cur, version_id):
    cur.execute("""SELECT transition_id::text AS transition_id, from_stage_key, to_stage_key,
                          condition_key, enabled
                   FROM workflow_transition
                   WHERE version_id=%s
                   ORDER BY from_stage_key, to_stage_key, condition_key""", (version_id,))
    return cur.fetchall()


def _workflow_version_read_model(cur, version_id):
    cur.execute("""SELECT w.workflow_id::text AS workflow_id, w.workflow_key, w.name, w.description,
                          v.version_id::text AS version_id, v.version_no, v.status, v.source, v.notes,
                          v.created_by, v.updated_by, v.activated_by, v.created_at, v.updated_at,
                          v.activated_at
                   FROM workflow_version v
                   JOIN workflow w ON w.workflow_id=v.workflow_id
                   WHERE v.version_id=%s""", (version_id,))
    row = cur.fetchone()
    if not row:
        raise GateError(f"unknown workflow version {version_id}")
    row["stages"] = _workflow_stage_read_model(cur, version_id)
    row["transitions"] = _workflow_transition_read_model(cur, version_id)
    return row


def _workflow_versions_summary(cur, workflow_id):
    cur.execute("""SELECT version_id::text AS version_id, version_no, status, source, notes,
                          created_by, updated_by, activated_by, created_at, updated_at, activated_at
                   FROM workflow_version
                   WHERE workflow_id=%s
                   ORDER BY version_no DESC""", (workflow_id,))
    return cur.fetchall()


def _ensure_methodology_seed(conn, actor="system"):
    cur = conn.cursor()
    try:
        cur.execute("""SELECT 1 FROM methodology_version
                       WHERE tenant_id='default' AND module='content'
                       LIMIT 1""")
        if cur.fetchone():
            return
    finally:
        cur.close()
    try:
        from loader import load_methodology as methodology_loader
    except Exception as e:  # pragma: no cover - defensive import seam
        raise GateError(f"methodology loader unavailable: {e}") from e
    methodology_loader.sync_versioned_seed(conn, actor=actor)


def _methodology_version_read_model(cur, version_id):
    cur.execute("""SELECT m.methodology_id::text AS methodology_id, m.methodology_key, m.name, m.description,
                          v.version_id::text AS version_id, v.version_no, v.status, v.source, v.notes,
                          v.source_digest, v.source_manifest, v.created_by, v.updated_by, v.activated_by,
                          v.created_at, v.updated_at, v.activated_at
                   FROM methodology_version v
                   JOIN methodology m ON m.methodology_id=v.methodology_id
                   WHERE v.version_id=%s""", (version_id,))
    row = cur.fetchone()
    if not row:
        raise GateError(f"unknown methodology version {version_id}")
    cur.execute("""SELECT pillar_code, code_short, name_en, name_ar, scope
                   FROM methodology_pillar
                   WHERE version_id=%s
                   ORDER BY code_short, pillar_code""", (version_id,))
    row["pillars"] = cur.fetchall()
    cur.execute("""SELECT lens_id, name_ar, name_en, viewer_state, primary_action, default_hook_type
                   FROM methodology_lens
                   WHERE version_id=%s
                   ORDER BY lens_id""", (version_id,))
    row["lenses"] = cur.fetchall()
    cur.execute("""SELECT name, function
                   FROM methodology_hook_type
                   WHERE version_id=%s
                   ORDER BY name""", (version_id,))
    row["hook_types"] = cur.fetchall()
    cur.execute("""SELECT hcs_id, pillar_code, seq_in_pillar, name_en, name_ar, core_wound,
                          how_it_shows_up, false_belief, earthquake_sentence, islamic_anchor,
                          recommended_lenses, recommended_formats, value_ladder, voice_status, anchor_status
                   FROM methodology_hcs
                   WHERE version_id=%s
                   ORDER BY pillar_code, seq_in_pillar, hcs_id""", (version_id,))
    row["hcs"] = cur.fetchall()
    row["counts"] = {
        "pillars": len(row["pillars"]),
        "lenses": len(row["lenses"]),
        "hook_types": len(row["hook_types"]),
        "hcs": len(row["hcs"]),
    }
    return row


def _methodology_versions_summary(cur, methodology_id):
    cur.execute("""SELECT version_id::text AS version_id, version_no, status, source, notes, source_digest,
                          created_by, updated_by, activated_by, created_at, updated_at, activated_at,
                          (SELECT count(*) FROM methodology_pillar p WHERE p.version_id=v.version_id) AS pillar_count,
                          (SELECT count(*) FROM methodology_lens l WHERE l.version_id=v.version_id) AS lens_count,
                          (SELECT count(*) FROM methodology_hook_type h WHERE h.version_id=v.version_id) AS hook_type_count,
                          (SELECT count(*) FROM methodology_hcs c WHERE c.version_id=v.version_id) AS hcs_count
                   FROM methodology_version v
                   WHERE methodology_id=%s
                   ORDER BY version_no DESC""", (methodology_id,))
    return cur.fetchall()


def list_methodologies(conn, principal_id=None):
    _ensure_methodology_seed(conn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT methodology_id::text AS methodology_id, methodology_key, name, description
                       FROM methodology
                       WHERE tenant_id='default' AND module='content'
                       ORDER BY created_at, methodology_key""")
        rows = []
        active_version = None
        for row in cur.fetchall():
            row["versions"] = _methodology_versions_summary(cur, row["methodology_id"])
            row["active_version_id"] = next((v["version_id"] for v in row["versions"] if v["status"] == "active"), None)
            rows.append(row)
            if row["active_version_id"]:
                active_version = _methodology_version_read_model(cur, row["active_version_id"])
        return {
            "can_administer": bool(principal_id and can_administer_approval_policies(conn, principal_id)),
            "methodologies": rows,
            "active_version": active_version,
        }
    finally:
        cur.close()


def get_methodology_version(conn, version_id=None, *, active=False):
    _ensure_methodology_seed(conn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if active:
            cur.execute("""SELECT version_id::text AS version_id
                           FROM methodology_version
                           WHERE tenant_id='default' AND module='content' AND status='active'
                           ORDER BY activated_at DESC NULLS LAST, created_at DESC
                           LIMIT 1""")
            row = cur.fetchone()
            if not row:
                raise GateError("no active methodology version")
            version_id = row["version_id"]
        if not version_id:
            raise GateError("methodology version id required")
        return _methodology_version_read_model(cur, version_id)
    finally:
        cur.close()


def create_methodology_version_draft(conn, methodology_key="tanaghom_core", actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer methodologies")
    _ensure_methodology_seed(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT methodology_id::text AS methodology_id
                       FROM methodology
                       WHERE methodology_key=%s AND tenant_id='default' AND module='content'""",
                    (methodology_key,))
        methodology = cur.fetchone()
        if not methodology:
            raise GateError(f"unknown methodology {methodology_key}")
        methodology_id = methodology["methodology_id"]
        cur.execute("""SELECT coalesce(max(version_no), 0) AS max_version
                       FROM methodology_version
                       WHERE methodology_id=%s""", (methodology_id,))
        version_no = int(cur.fetchone()["max_version"]) + 1
        cur.execute("""SELECT version_id::text AS version_id
                       FROM methodology_version
                       WHERE methodology_id=%s AND status='active'
                       ORDER BY version_no DESC
                       LIMIT 1""", (methodology_id,))
        active_version = cur.fetchone()
        cur.execute("""INSERT INTO methodology_version
                       (methodology_id, version_no, status, source, notes, created_by, updated_by,
                        tenant_id, module)
                       VALUES (%s,%s,'draft','admin',%s,%s,%s,'default','content')
                       RETURNING version_id::text AS version_id""",
                    (methodology_id, version_no, "Draft cloned from active methodology", actor, actor))
        version_id = cur.fetchone()["version_id"]
        if active_version:
            cur.execute("""INSERT INTO methodology_pillar
                           (version_id, pillar_code, code_short, name_en, name_ar, scope)
                           SELECT %s, pillar_code, code_short, name_en, name_ar, scope
                           FROM methodology_pillar
                           WHERE version_id=%s""", (version_id, active_version["version_id"]))
            cur.execute("""INSERT INTO methodology_lens
                           (version_id, lens_id, name_ar, name_en, viewer_state, primary_action, default_hook_type)
                           SELECT %s, lens_id, name_ar, name_en, viewer_state, primary_action, default_hook_type
                           FROM methodology_lens
                           WHERE version_id=%s""", (version_id, active_version["version_id"]))
            cur.execute("""INSERT INTO methodology_hook_type (version_id, name, function)
                           SELECT %s, name, function
                           FROM methodology_hook_type
                           WHERE version_id=%s""", (version_id, active_version["version_id"]))
            cur.execute("""INSERT INTO methodology_hcs
                           (version_id, hcs_id, pillar_code, seq_in_pillar, name_en, name_ar, core_wound,
                            how_it_shows_up, false_belief, earthquake_sentence, islamic_anchor,
                            recommended_lenses, recommended_formats, value_ladder, voice_status, anchor_status)
                           SELECT %s, hcs_id, pillar_code, seq_in_pillar, name_en, name_ar, core_wound,
                                  how_it_shows_up, false_belief, earthquake_sentence, islamic_anchor,
                                  recommended_lenses, recommended_formats, value_ladder, voice_status, anchor_status
                           FROM methodology_hcs
                           WHERE version_id=%s""", (version_id, active_version["version_id"]))
        _audit(cur, "methodology_version", version_id, "methodology_version_created", actor, {
            "methodology_key": methodology_key,
            "version_no": version_no,
        })
        conn.commit()
        return get_methodology_version(conn, version_id)
    finally:
        cur.close()


def update_methodology_version(conn, version_id, payload, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer methodologies")
    _ensure_methodology_seed(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _methodology_version_read_model(cur, version_id)
        if before["status"] != "draft":
            raise GateError("only draft methodology versions may be edited")
        notes = str(payload.get("notes") or "").strip() or None
        cur.execute("""UPDATE methodology_version
                       SET notes=%s, updated_by=%s, updated_at=now()
                       WHERE version_id=%s""", (notes, actor, version_id))
        after = _methodology_version_read_model(cur, version_id)
        _audit(cur, "methodology_version", version_id, "methodology_version_updated", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def activate_methodology_version(conn, version_id, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer methodologies")
    _ensure_methodology_seed(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _methodology_version_read_model(cur, version_id)
        if before["status"] == "active":
            return before
        cur.execute("""SELECT methodology_id::text AS methodology_id
                       FROM methodology_version
                       WHERE version_id=%s""", (version_id,))
        row = cur.fetchone()
        if not row:
            raise GateError(f"unknown methodology version {version_id}")
        try:
            from loader import load_methodology as methodology_loader
        except Exception as e:  # noqa: BLE001
            raise GateError(f"methodology loader unavailable: {e}") from e
        methodology_loader.materialize_methodology_version(conn, version_id)
        cur.execute("""UPDATE methodology_version
                       SET status='inactive', updated_by=%s, updated_at=now()
                       WHERE methodology_id=%s AND status='active' AND version_id<>%s""",
                    (actor, row["methodology_id"], version_id))
        cur.execute("""UPDATE methodology_version
                       SET status='active', updated_by=%s, updated_at=now(),
                           activated_by=%s, activated_at=now()
                       WHERE version_id=%s""", (actor, actor, version_id))
        cur.execute("""UPDATE methodology
                       SET updated_at=now()
                       WHERE methodology_id=%s""", (row["methodology_id"],))
        after = _methodology_version_read_model(cur, version_id)
        _audit(cur, "methodology_version", version_id, "methodology_version_activated", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def _content_format_active_version(cur, content_format_id):
    cur.execute("""SELECT version_id::text AS version_id, version_no, status, source, use_case, lens_fit,
                          production_notes, production_rules, platform_targets, source_digest,
                          created_by, updated_by, activated_by, created_at, updated_at, activated_at
                   FROM content_format_version
                   WHERE content_format_id=%s AND status='active'
                   ORDER BY version_no DESC
                   LIMIT 1""", (content_format_id,))
    return cur.fetchone()


def _content_format_versions_summary(cur, content_format_id):
    cur.execute("""SELECT version_id::text AS version_id, version_no, status, source, use_case, lens_fit,
                          production_notes, production_rules, platform_targets, source_digest,
                          created_by, updated_by, activated_by, created_at, updated_at, activated_at
                   FROM content_format_version
                   WHERE content_format_id=%s
                   ORDER BY version_no DESC""", (content_format_id,))
    return cur.fetchall()


def _content_format_read_model(cur, content_format_id):
    cur.execute("""SELECT content_format_id::text AS content_format_id, format_key, name, description,
                          active, lifecycle_status, archived_at, archived_by,
                          created_by, updated_by, created_at, updated_at
                   FROM content_format
                   WHERE content_format_id=%s""", (content_format_id,))
    row = cur.fetchone()
    if not row:
        raise GateError(f"unknown content format {content_format_id}")
    row["versions"] = _content_format_versions_summary(cur, row["content_format_id"])
    row["active_version"] = _content_format_active_version(cur, row["content_format_id"])
    return row


def _ensure_content_type_registry(conn, actor="system"):
    cur = conn.cursor()
    try:
        cur.execute("""SELECT count(*) FROM content_format
                       WHERE tenant_id='default' AND module='content'""")
        if cur.fetchone()[0]:
            return
    finally:
        cur.close()
    try:
        from loader import load_methodology as methodology_loader
    except Exception as e:  # noqa: BLE001
        raise GateError(f"content-type bootstrap unavailable: {e}") from e
    methodology_loader.bootstrap_content_formats(conn, actor=actor)


def list_content_formats(conn, principal_id=None):
    _ensure_methodology_seed(conn)
    _ensure_content_type_registry(conn, actor=principal_id or "system")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT platform_id::text AS platform_id, platform_key, name, channel_role,
                              description, active, config, created_by, updated_by, created_at, updated_at
                       FROM platform
                       WHERE tenant_id='default' AND module='content'
                       ORDER BY active DESC, channel_role, name, platform_key""")
        platforms = cur.fetchall()
        cur.execute("""SELECT content_format_id::text AS content_format_id, format_key, name, description,
                              active, lifecycle_status, archived_at, archived_by,
                              created_by, updated_by, created_at, updated_at
                       FROM content_format
                       WHERE tenant_id='default' AND module='content'
                       ORDER BY lifecycle_status='archived', name, format_key""")
        formats = []
        for row in cur.fetchall():
            row["versions"] = _content_format_versions_summary(cur, row["content_format_id"])
            row["active_version"] = _content_format_active_version(cur, row["content_format_id"])
            formats.append(row)
        return {
            "can_administer": bool(principal_id and can_administer_approval_policies(conn, principal_id)),
            "platforms": platforms,
            "formats": formats,
        }
    finally:
        cur.close()


def _normalize_text_list(values):
    seen, out = set(), []
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _normalize_json_object(value, field_name):
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise GateError(f"{field_name} must be a JSON object")
    return value


def _normalize_format_key(raw):
    value = str(raw or "").strip().lower()
    if not value:
        raise GateError("content format key required")
    if not all(ch.isalnum() or ch == "_" for ch in value):
        raise GateError("content format key must use lowercase letters, numbers, or underscores")
    return value


def _slot_usage_count_for_format(cur, format_name):
    cur.execute("SELECT count(*) AS n FROM slot WHERE format=%s", (format_name,))
    return int(cur.fetchone()["n"])


def _content_format_version_read_model(cur, version_id):
    cur.execute("""SELECT f.content_format_id::text AS content_format_id, f.format_key, f.name, f.description,
                          f.active, f.lifecycle_status, v.version_id::text AS version_id, v.version_no, v.status, v.source,
                          v.use_case, v.lens_fit, v.production_notes, v.production_rules,
                          v.platform_targets, v.source_digest, v.created_by, v.updated_by,
                          v.activated_by, v.created_at, v.updated_at, v.activated_at
                   FROM content_format_version v
                   JOIN content_format f ON f.content_format_id=v.content_format_id
                   WHERE v.version_id=%s""", (version_id,))
    row = cur.fetchone()
    if not row:
        raise GateError(f"unknown content format version {version_id}")
    return row


# --------------------------------------------------------------------------- #
# #276 (D1) — versioned baseline eligibility policy + immutable round snapshot.
# The baseline policy selects eligible content_format_version IDs INDEPENDENTLY of global
# content_format lifecycle: once a generation is seeded/superseded it is decoupled from later
# catalogue lifecycle/version changes. Exactly one 'current' generation per scope (DB-enforced);
# a governed change creates a new immutable generation that deterministically supersedes the prior.
# --------------------------------------------------------------------------- #
# The authoritative GOVERNED baseline selection is data-driven, NOT global catalogue lifecycle: a
# content_format_version is part of the client-approved baseline when its seed_source marks it a client
# framework. This deliberately EXCLUDES 'legacy_carry_forward' formats (e.g. Pic + Caption) without
# depending on content_format.active — eligibility and catalogue lifecycle stay separate (#276 P1b).
_GOVERNED_BASELINE_SEED_SOURCE = "client_framework_bootstrap"


def _governed_baseline_version_ids(cur, tenant_id="default", module="content"):
    """The authoritative governed baseline selection: active content_format_version IDs explicitly
    marked as client-approved frameworks (seed_source = client_framework_bootstrap). Ordered for
    determinism. Independent of content_format.active — a lifecycle change never edits eligibility."""
    cur.execute("""SELECT v.version_id::text
                   FROM content_format f
                   JOIN content_format_version v ON v.content_format_id=f.content_format_id
                        AND v.status='active'
                   WHERE f.tenant_id=%s AND f.module=%s
                     AND v.production_rules->>'seed_source' = %s
                   ORDER BY coalesce((v.production_rules->'planning'->>'sort_order')::int, 9999), f.name""",
                (tenant_id, module, _GOVERNED_BASELINE_SEED_SOURCE))
    return [r[0] if not isinstance(r, dict) else r["version_id"] for r in cur.fetchall()]


def ensure_baseline_policy(conn, actor="system", scope="default", tenant_id="default", module="content"):
    """CREATE-ONLY seed of baseline generation 1 (guardrail-compliant initialization): if a current
    policy already exists it is a non-destructive no-op (never overwrites operator-owned configuration);
    otherwise generation 1 is created from the AUTHORITATIVE GOVERNED selection (client-approved framework
    versions, NOT the active catalogue / lifecycle flags — #276 P1b). If no authoritative governed
    selection exists, HARD-STOP (never seed an inferred or empty baseline). Idempotent."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT policy_id::text, generation FROM baseline_eligibility_policy
                   WHERE scope=%s AND tenant_id=%s AND module=%s AND status='current'""",
                (scope, tenant_id, module))
    existing = cur.fetchone()
    if existing:
        cur.close()
        return existing
    version_ids = _governed_baseline_version_ids(cur, tenant_id, module)
    if not version_ids:
        cur.close()
        raise GateError("no authoritative governed baseline selection (client-approved framework "
                        "versions) to seed the baseline eligibility policy — fails closed")
    cur.execute("""INSERT INTO baseline_eligibility_policy
                   (scope, generation, status, eligible_version_ids, created_by, tenant_id, module)
                   VALUES (%s, 1, 'current', %s, %s, %s, %s)
                   RETURNING policy_id::text, generation""",
                (scope, psycopg2.extras.Json(version_ids), actor, tenant_id, module))
    row = cur.fetchone()
    _audit(cur, "baseline_policy", row["policy_id"], "baseline_policy_seeded", actor,
           {"scope": scope, "generation": 1, "eligible_count": len(version_ids),
            "selection": "governed_client_frameworks"})
    conn.commit(); cur.close()
    return row


def current_baseline_policy(cur, scope="default", tenant_id="default", module="content"):
    """The one authoritative CURRENT baseline-policy generation for the scope. FAILS CLOSED: zero
    current raises (missing policy) and, defensively, more than one raises (ambiguous) — though the
    partial-unique index makes >1 unreachable. Returns {policy_id, generation, eligible_version_ids}."""
    cur.execute("""SELECT policy_id::text, generation, eligible_version_ids
                   FROM baseline_eligibility_policy
                   WHERE scope=%s AND tenant_id=%s AND module=%s AND status='current'""",
                (scope, tenant_id, module))
    rows = cur.fetchall()
    if not rows:
        raise GateError(f"no current baseline eligibility policy for scope {scope!r} "
                        "— fails closed (seed generation 1 before planning a run)")
    if len(rows) > 1:
        raise GateError(f"ambiguous baseline eligibility policy for scope {scope!r} "
                        f"({len(rows)} current generations) — fails closed")
    r = rows[0]
    if isinstance(r, dict):
        return {"policy_id": r["policy_id"], "generation": r["generation"],
                "eligible_version_ids": r["eligible_version_ids"]}
    return {"policy_id": r[0], "generation": r[1], "eligible_version_ids": r[2]}


def resolve_run_eligibility(cur, scope="default", tenant_id="default", module="content"):
    """#276 read/selection path (consumed by #271): the eligible frameworks for a NEW run, resolved
    from the current baseline policy's pinned content_format_version IDs — NOT from content_format.active
    and NOT from a hard-coded allowlist. Returns {"policy": {...}, "eligible": [{name, format_key,
    version_id, framework_id}, ...]} in deterministic order. Fails closed via current_baseline_policy."""
    policy = current_baseline_policy(cur, scope, tenant_id, module)
    ids = policy["eligible_version_ids"] or []
    if not ids:
        return {"policy": policy, "eligible": []}
    cur.execute("""SELECT f.name, f.format_key, v.version_id::text,
                          v.production_rules->>'framework_id' AS framework_id
                   FROM content_format_version v
                   JOIN content_format f ON f.content_format_id=v.content_format_id
                   WHERE v.version_id::text = ANY(%s)
                   ORDER BY coalesce((v.production_rules->'planning'->>'sort_order')::int, 9999), f.name""",
                (list(ids),))
    eligible = []
    for r in cur.fetchall():
        name, fkey, vid, fid = (r["name"], r["format_key"], r["version_id"], r["framework_id"]) \
            if isinstance(r, dict) else (r[0], r[1], r[2], r[3])
        eligible.append({"name": name, "format_key": fkey, "version_id": vid, "framework_id": fid})
    # #276 — the current policy pins specific content_format_version IDs. If any no longer resolve (e.g.
    # a content-format reset re-minted versions), the policy is INVALID: FAIL CLOSED (hard-stop) rather
    # than approximate. Recovery is a governed policy refresh (a separate directive), out of scope here.
    if len(eligible) != len(set(ids)):
        raise GateError(f"baseline eligibility policy generation {policy['generation']} references "
                        f"{len(set(ids))} content_format_version(s) but only {len(eligible)} resolve — "
                        "the current policy is invalid (content-format versions were reminted); fails "
                        "closed until a governed policy refresh selects a valid generation.")
    return {"policy": policy, "eligible": eligible}


def supersede_baseline_policy(conn, eligible_version_ids, actor="system", scope="default",
                              tenant_id="default", module="content"):
    """Governed prospective change: create a NEW immutable generation that deterministically supersedes
    the prior current one. Never alters prior generations or any pinned round. Reuses the caller's
    authenticated authority (no new authority/UI is invented here). Returns the new current policy."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT policy_id::text, generation FROM baseline_eligibility_policy
                   WHERE scope=%s AND tenant_id=%s AND module=%s AND status='current'""",
                (scope, tenant_id, module))
    prior = cur.fetchone()
    if not prior:
        cur.close()
        raise GateError(f"no current baseline policy to supersede for scope {scope!r}")
    cur.execute("""SELECT coalesce(max(generation),0)+1 AS n FROM baseline_eligibility_policy
                   WHERE scope=%s AND tenant_id=%s AND module=%s""", (scope, tenant_id, module))
    next_gen = cur.fetchone()["n"]
    # free the single-current slot first, then insert the new current (order matters for the index).
    cur.execute("""UPDATE baseline_eligibility_policy SET status='superseded', superseded_at=now()
                   WHERE policy_id=%s""", (prior["policy_id"],))
    cur.execute("""INSERT INTO baseline_eligibility_policy
                   (scope, generation, status, eligible_version_ids, created_by, tenant_id, module)
                   VALUES (%s, %s, 'current', %s, %s, %s, %s)
                   RETURNING policy_id::text, generation""",
                (scope, next_gen, psycopg2.extras.Json(list(eligible_version_ids)), actor,
                 tenant_id, module))
    new_row = cur.fetchone()
    cur.execute("""UPDATE baseline_eligibility_policy SET superseded_by=%s WHERE policy_id=%s""",
                (new_row["policy_id"], prior["policy_id"]))
    _audit(cur, "baseline_policy", new_row["policy_id"], "baseline_policy_superseded", actor,
           {"scope": scope, "generation": next_gen, "prior_policy_id": prior["policy_id"],
            "prior_generation": prior["generation"], "eligible_count": len(list(eligible_version_ids))})
    conn.commit(); cur.close()
    return {"policy_id": new_row["policy_id"], "generation": new_row["generation"]}


def _active_version_id(cur, table, id_col):
    """The single active version_id of a governed record (methodology_version / workflow_version) at
    plan time, or None if none is active. Authoritative existing source for the round snapshot."""
    cur.execute(f"SELECT version_id::text FROM {table} WHERE status='active' "
                "ORDER BY version_no DESC LIMIT 1")
    r = cur.fetchone()
    if not r:
        return None
    return r["version_id"] if isinstance(r, dict) else r[0]


def pin_round_snapshot(cur, round_id, policy, selected_version_ids, format_mix,
                       methodology_version=None, workflow_version=None):
    """Pin the IMMUTABLE resolved policy snapshot for a newly planned run. Append-only: the row can
    never be UPDATEd (DB trigger). Holds only authoritative planning-time values."""
    cur.execute("""INSERT INTO round_policy_snapshot
                   (round_id, baseline_policy_id, baseline_generation, selected_version_ids,
                    format_mix, methodology_version, workflow_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (round_id, policy["policy_id"], policy["generation"],
                 psycopg2.extras.Json(selected_version_ids), psycopg2.extras.Json(format_mix),
                 methodology_version, workflow_version))


def round_snapshot(conn, round_id):
    """Read a run's pinned policy snapshot (the round resolves from HERE, never from the latest
    baseline policy). Returns the snapshot dict or None if the run predates #276."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT round_id, baseline_policy_id::text AS baseline_policy_id,
                              baseline_generation, selected_version_ids, format_mix,
                              methodology_version, workflow_version, created_at
                       FROM round_policy_snapshot WHERE round_id=%s""", (round_id,))
        return cur.fetchone()
    finally:
        cur.close()


def create_content_format(conn, payload, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_methodology_seed(conn, actor=actor)
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        format_key = _normalize_format_key(payload.get("format_key"))
        name = str(payload.get("name") or "").strip()
        if not name:
            raise GateError("content format name required")
        description = str(payload.get("description") or "").strip() or None
        use_case = str(payload.get("use_case") or "").strip() or None
        production_notes = str(payload.get("production_notes") or "").strip() or None
        lens_fit = _normalize_text_list(payload.get("lens_fit") or [])
        platform_targets = _normalize_text_list(payload.get("platform_targets") or [])
        production_rules = _normalize_json_object(payload.get("production_rules"), "production_rules")
        cur.execute("""INSERT INTO content_format
                       (format_key, name, description, active, lifecycle_status, created_by, updated_by, tenant_id, module)
                       VALUES (%s,%s,%s,true,'active',%s,%s,'default','content')
                       RETURNING content_format_id::text AS content_format_id""",
                    (format_key, name, description, actor, actor))
        content_format_id = cur.fetchone()["content_format_id"]
        cur.execute("""INSERT INTO content_format_version
                       (content_format_id, version_no, status, source, use_case, lens_fit,
                        production_notes, production_rules, platform_targets,
                        created_by, updated_by, tenant_id, module)
                       VALUES (%s,1,'draft','admin',%s,%s,%s,%s,%s,%s,%s,'default','content')
                       RETURNING version_id::text AS version_id""",
                    (
                        content_format_id, use_case, Json(lens_fit), production_notes,
                        Json(production_rules), Json(platform_targets), actor, actor,
                    ))
        version_id = cur.fetchone()["version_id"]
        _audit(cur, "content_format", content_format_id, "content_format_created", actor, {
            "format_key": format_key,
            "name": name,
        })
        _audit(cur, "content_format_version", version_id, "content_format_version_created", actor, {
            "content_format_id": content_format_id,
            "version_no": 1,
            "source": "admin",
        })
        conn.commit()
        return _content_format_read_model(cur, content_format_id)
    except psycopg2.errors.UniqueViolation as e:
        conn.rollback()
        raise GateError("content format key already exists") from e
    finally:
        cur.close()


def update_content_format(conn, content_format_id, payload, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_methodology_seed(conn, actor=actor)
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _content_format_read_model(cur, content_format_id)
        format_key = _normalize_format_key(payload.get("format_key") or before["format_key"])
        name = str(payload.get("name") or before["name"]).strip()
        if not name:
            raise GateError("content format name required")
        description = before["description"] if payload.get("description") is None else (str(payload.get("description") or "").strip() or None)
        if name != before["name"] and _slot_usage_count_for_format(cur, before["name"]):
            raise GateError("cannot rename a content format while slots still reference it; reset or clear rounds first")
        cur.execute("""UPDATE content_format
                       SET format_key=%s, name=%s, description=%s, updated_by=%s, updated_at=now()
                       WHERE content_format_id=%s""",
                    (format_key, name, description, actor, content_format_id))
        if before["active"] and before["active_version"]:
            cur.execute("""UPDATE format
                           SET name=%s, format_key=%s, description=%s
                           WHERE name=%s""",
                        (name, format_key, description, before["name"]))
        after = _content_format_read_model(cur, content_format_id)
        _audit(cur, "content_format", content_format_id, "content_format_updated", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    except psycopg2.errors.UniqueViolation as e:
        conn.rollback()
        raise GateError("content format key already exists") from e
    finally:
        cur.close()


def archive_content_format(conn, content_format_id, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _content_format_read_model(cur, content_format_id)
        if before["lifecycle_status"] == "archived":
            return before
        if _slot_usage_count_for_format(cur, before["name"]):
            raise GateError("cannot archive a content format while slots still reference it; reset or clear rounds first")
        cur.execute("""UPDATE content_format
                       SET active=false, lifecycle_status='archived', archived_by=%s, archived_at=now(),
                           updated_by=%s, updated_at=now()
                       WHERE content_format_id=%s""",
                    (actor, actor, content_format_id))
        cur.execute("DELETE FROM format WHERE name=%s", (before["name"],))
        after = _content_format_read_model(cur, content_format_id)
        _audit(cur, "content_format", content_format_id, "content_format_archived", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def restore_content_format(conn, content_format_id, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _content_format_read_model(cur, content_format_id)
        if before["lifecycle_status"] != "archived":
            return before
        cur.execute("""UPDATE content_format
                       SET active=true, lifecycle_status='active', archived_by=null, archived_at=null,
                           updated_by=%s, updated_at=now()
                       WHERE content_format_id=%s""", (actor, content_format_id))
        active_version = _content_format_active_version(cur, content_format_id)
        if active_version:
            try:
                from loader import load_methodology as methodology_loader
            except Exception as e:  # noqa: BLE001
                raise GateError(f"methodology loader unavailable: {e}") from e
            methodology_loader.materialize_content_format_version(conn, active_version["version_id"])
        after = _content_format_read_model(cur, content_format_id)
        _audit(cur, "content_format", content_format_id, "content_format_restored", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def delete_content_format(conn, content_format_id, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _content_format_read_model(cur, content_format_id)
        if _slot_usage_count_for_format(cur, before["name"]):
            raise GateError("cannot delete a content format while slots still reference it; reset or clear rounds first")
        _audit(cur, "content_format", content_format_id, "content_format_deleted", actor, {
            "before": before,
        })
        cur.execute("DELETE FROM format WHERE name=%s", (before["name"],))
        cur.execute("DELETE FROM content_format WHERE content_format_id=%s", (content_format_id,))
        conn.commit()
        return {"deleted": True, "content_format_id": content_format_id}
    finally:
        cur.close()


def reset_content_format_registry(conn, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE TABLE gate_decision, gate_assignment, gate_target, gate, asset, directive, slot_approval, slot_review, script, topic, slot, round RESTART IDENTITY CASCADE")
        cur.execute("DELETE FROM lens_history")
        cur.execute("DELETE FROM hcs_cursor")
        cur.execute("""DELETE FROM audit_log
                       WHERE entity IN ('slot', 'round', 'gate', 'content_format', 'content_format_version')""")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    try:
        from loader import load_methodology as methodology_loader
    except Exception as e:  # noqa: BLE001
        raise GateError(f"content-type bootstrap unavailable: {e}") from e
    methodology_loader.bootstrap_content_formats(conn, actor=actor, reset=True)
    # #276 — a content-format reset re-mints content_format_version IDs and thereby MAY invalidate the
    # pinned baseline_eligibility_policy (it references specific version IDs). Reset MUST NOT delete,
    # replace, or silently recreate operator-owned policy generations — those are governed evidence, and
    # a governed policy maintenance/refresh model is out of scope for D1. The policy is left untouched; if
    # reminting invalidated the current generation, run-eligibility resolution FAILS CLOSED (hard-stop)
    # rather than approximating, until a governed refresh (a separate directive) re-selects a generation.
    return list_content_formats(conn, principal_id=actor)


def create_content_format_version_draft(conn, format_key, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_methodology_seed(conn, actor=actor)
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT content_format_id::text AS content_format_id, lifecycle_status
                       FROM content_format
                       WHERE format_key=%s AND tenant_id='default' AND module='content'""", (format_key,))
        row = cur.fetchone()
        if not row:
            raise GateError(f"unknown content format {format_key}")
        if row["lifecycle_status"] == "archived":
            raise GateError(f"content format {format_key} is archived")
        content_format_id = row["content_format_id"]
        cur.execute("""SELECT coalesce(max(version_no), 0) AS max_version
                       FROM content_format_version
                       WHERE content_format_id=%s""", (content_format_id,))
        version_no = int(cur.fetchone()["max_version"]) + 1
        cur.execute("""SELECT version_id::text AS version_id, use_case, lens_fit, production_notes,
                              production_rules, platform_targets
                       FROM content_format_version
                       WHERE content_format_id=%s AND status='active'
                       ORDER BY version_no DESC
                       LIMIT 1""", (content_format_id,))
        active = cur.fetchone()
        if not active:
            raise GateError(f"content format {format_key} has no active version to clone")
        cur.execute("""INSERT INTO content_format_version
                       (content_format_id, version_no, status, source, use_case, lens_fit,
                        production_notes, production_rules, platform_targets,
                        created_by, updated_by, tenant_id, module)
                       VALUES (%s,%s,'draft','admin',%s,%s,%s,%s,%s,%s,%s,'default','content')
                       RETURNING version_id::text AS version_id""",
                    (
                        content_format_id, version_no, active["use_case"], Json(active["lens_fit"] or []),
                        active["production_notes"], Json(active["production_rules"] or {}),
                        Json(active["platform_targets"] or []), actor, actor,
                    ))
        version_id = cur.fetchone()["version_id"]
        _audit(cur, "content_format_version", version_id, "content_format_version_created", actor, {
            "format_key": format_key,
            "version_no": version_no,
        })
        conn.commit()
        return _content_format_version_read_model(cur, version_id)
    finally:
        cur.close()


def update_content_format_version(conn, version_id, payload, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_methodology_seed(conn, actor=actor)
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _content_format_version_read_model(cur, version_id)
        if before["status"] != "draft":
            raise GateError("only draft content format versions may be edited")
        use_case = str(payload.get("use_case") or "").strip() or None
        production_notes = str(payload.get("production_notes") or "").strip() or None
        lens_fit = _normalize_text_list(payload.get("lens_fit") or [])
        platform_targets = _normalize_text_list(payload.get("platform_targets") or [])
        production_rules = _normalize_json_object(payload.get("production_rules"), "production_rules")
        cur.execute("""UPDATE content_format_version
                       SET use_case=%s, lens_fit=%s, production_notes=%s, production_rules=%s,
                           platform_targets=%s,
                           updated_by=%s, updated_at=now()
                       WHERE version_id=%s""",
                    (
                        use_case, Json(lens_fit), production_notes, Json(production_rules),
                        Json(platform_targets), actor, version_id,
                    ))
        after = _content_format_version_read_model(cur, version_id)
        _audit(cur, "content_format_version", version_id, "content_format_version_updated", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def activate_content_format_version(conn, version_id, actor="system"):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer content formats")
    _ensure_methodology_seed(conn, actor=actor)
    _ensure_content_type_registry(conn, actor=actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _content_format_version_read_model(cur, version_id)
        if before["lifecycle_status"] == "archived":
            raise GateError("cannot activate a version of an archived content format")
        if before["status"] == "active":
            return before
        try:
            from loader import load_methodology as methodology_loader
        except Exception as e:  # noqa: BLE001
            raise GateError(f"methodology loader unavailable: {e}") from e
        methodology_loader.materialize_content_format_version(conn, version_id)
        cur.execute("""UPDATE content_format_version
                       SET status='inactive', updated_by=%s, updated_at=now()
                       WHERE content_format_id=%s AND status='active' AND version_id<>%s""",
                    (actor, before["content_format_id"], version_id))
        cur.execute("""UPDATE content_format_version
                       SET status='active', updated_by=%s, updated_at=now(),
                           activated_by=%s, activated_at=now()
                       WHERE version_id=%s""", (actor, actor, version_id))
        cur.execute("""UPDATE content_format
                       SET updated_by=%s, updated_at=now()
                       WHERE content_format_id=%s""", (actor, before["content_format_id"]))
        after = _content_format_version_read_model(cur, version_id)
        _audit(cur, "content_format_version", version_id, "content_format_version_activated", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def _workflow_stage_payload(payload, cfg):
    stage_key = str(payload.get("stage_key") or "").strip()
    if not stage_key:
        raise GateError("workflow stage missing stage_key")
    if stage_key not in (cfg.get("gates") or {}):
        raise GateError(f"unsupported workflow stage {stage_key!r}")
    meta = WORKFLOW_STAGE_META.get(stage_key, {"label": stage_key, "group": "Workflow"})
    gc = stage_cfg(cfg, stage_key)
    return {
        "stage_key": stage_key,
        "stage_label": str(payload.get("stage_label") or meta["label"]).strip() or meta["label"],
        "stage_group": str(payload.get("stage_group") or meta["group"]).strip() or meta["group"],
        "enabled": bool(payload.get("enabled", True)),
        "bypassable": bool(payload.get("bypassable", False)),
        "mandatory": bool(payload.get("mandatory", True)),
        "gate_stage": str(payload.get("gate_stage") or stage_key).strip() or stage_key,
        "stage_kind": str(payload.get("stage_kind") or gc.get("kind", "transition")).strip() or "transition",
        "generator_kind": payload.get("generator_kind") or gc.get("generator"),
        "scope": payload.get("scope") or gc.get("scope"),
        "policy": payload.get("policy") or gc.get("policy"),
        "review_statuses": list(payload.get("review_statuses") or _stage_review_statuses(gc)),
        "approve_to": payload.get("approve_to") or gc.get("approve_to"),
        "changes_to": payload.get("changes_to") or gc.get("changes_to"),
        "reject_to": payload.get("reject_to") or gc.get("reject_to"),
        "rework_mode": payload.get("rework_mode") or gc.get("rework_mode"),
        "generates_from": payload.get("generates_from") or gc.get("generates_from"),
        "writer_mode": payload.get("writer_mode") or gc.get("writer_mode"),
        "requires_flag": payload.get("requires_flag") or gc.get("requires_flag"),
        "allow_partial_batch": bool(payload.get("allow_partial_batch", gc.get("allow_partial_batch", False))),
        "enforce_mandatory_reviews": bool(payload.get("enforce_mandatory_reviews",
                                                      gc.get("enforce_mandatory_reviews", False))),
        "approval_rule": _normalize_rule_key(payload.get("approval_rule") or stage_approval_contract(cfg, stage_key)["rule_key"]),
    }


def _normalize_workflow_version_payload(payload, cfg):
    stages = payload.get("stages") or []
    if not stages:
        raise GateError("workflow version needs at least one stage")
    out_stages, seen = [], set()
    for ordinal, stage in enumerate(stages, start=1):
        row = _workflow_stage_payload(stage, cfg)
        if row["stage_key"] in seen:
            raise GateError(f"duplicate workflow stage {row['stage_key']!r}")
        seen.add(row["stage_key"])
        row["ordinal"] = ordinal
        out_stages.append(row)
    transitions = []
    for item in payload.get("transitions") or []:
        from_stage = str(item.get("from_stage_key") or "").strip()
        to_stage = str(item.get("to_stage_key") or "").strip()
        if not from_stage or not to_stage:
            raise GateError("workflow transition needs from_stage_key and to_stage_key")
        if from_stage not in seen or to_stage not in seen:
            raise GateError(f"workflow transition references unknown stage {from_stage!r}->{to_stage!r}")
        transitions.append({
            "from_stage_key": from_stage,
            "to_stage_key": to_stage,
            "condition_key": str(item.get("condition_key") or "approve").strip() or "approve",
            "enabled": bool(item.get("enabled", True)),
        })
    if not transitions:
        transitions = _workflow_transition_seed_rows([row["stage_key"] for row in out_stages])
    return {
        "notes": str(payload.get("notes") or "").strip() or None,
        "stages": out_stages,
        "transitions": transitions,
    }


def list_workflows(conn, principal_id=None, cfg=None):
    cfg = cfg or load_config()
    _ensure_workflow_seed(conn, cfg)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT w.workflow_id::text AS workflow_id, w.workflow_key, w.name, w.description
                       FROM workflow w
                       WHERE w.tenant_id='default' AND w.module='content'
                       ORDER BY w.created_at, w.workflow_key""")
        workflows = []
        active_version = None
        for workflow in cur.fetchall():
            versions = _workflow_versions_summary(cur, workflow["workflow_id"])
            workflow["versions"] = versions
            workflow["active_version_id"] = next((v["version_id"] for v in versions if v["status"] == "active"), None)
            workflows.append(workflow)
            if workflow["active_version_id"]:
                active_version = _workflow_version_read_model(cur, workflow["active_version_id"])
        return {
            "can_administer": bool(principal_id and can_administer_approval_policies(conn, principal_id)),
            "workflows": workflows,
            "active_version": active_version,
        }
    finally:
        cur.close()


# ==================================================================================================
# #357 Stage 3A — governed Script generation: attempt identity, frozen authority, durable job.
#
# WHY ANY OF THIS. Before #357, Script generation had no authorization (the trusted-principal block in
# the generic route sits entirely inside `if mode == "topics"`), and no durable job (it used the
# in-process `gates.jobs` dict). Both gaps are closed HERE, by reusing the mechanisms Topics already
# proved rather than inventing parallel ones.
# ==================================================================================================

SCRIPT_MANIFEST_VERSION = "script-manifest/v1"

# #359 Amendment B — the initiating actor for the automatic trigger. A typed system identity, NOT a
# fabricated human: it is never added to `approver_ids`, never treated as a signed principal, and
# never satisfies a manual-command authorization. The accepted decision's frozen snapshot remains the
# only human authority evidence.
SCRIPT_AUTOMATIC_ACTOR = "system:topic_acceptance"


def topic_acceptance_script_targets(conn, gate_id):
    """#359 review fix 3 — the EXACT scope for post-commit Script acceleration.

    Returns the queued Script job_ids this specific gate's acceptance is responsible for: the empty
    list unless `gate_id` is a `topic_review` gate, and then only that gate's round's own queued
    Script attempt(s). An unrelated schedule/script/media gate resolves to [], so it can never
    launch Script work. This is a pure read — it dispatches nothing itself."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT stage FROM gate WHERE gate_id=%s", (gate_id,))
        row = cur.fetchone()
        if not row or row[0] != "topic_review":
            return []
        cur.execute("""SELECT DISTINCT gj.job_id::text
                         FROM gate_target gt
                         JOIN slot s ON s.slot_id = gt.slot_id
                         JOIN generation_job gj ON gj.round_id = s.round_id AND gj.stage='script'
                        WHERE gt.gate_id=%s AND gj.status='queued'""", (gate_id,))
        return [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
SCRIPT_GENERATION_LEASE_SECONDS = int(os.environ.get("TANAGHOM_SCRIPTGEN_LEASE_SECONDS", "300"))
_NOT_APPLICABLE = "not_applicable"


def _canonical_json_v1(value):
    """Canonical JSON for digesting: sorted keys, no insignificant whitespace, UTF-8, `null` for
    absent. Pinned to the manifest VERSION — changing any of these rules changes the version, never
    the meaning of an existing digest."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest_v1(value):
    return hashlib.sha256(_canonical_json_v1(value).encode("utf-8")).hexdigest()


def _topic_authority_snapshot(cur, gate_id):
    """#357 C1 — the IMMUTABLE affirmative authority of the accepted topic_review decision.

    Mirrors _schedule_authority_snapshot: the real approving principals and their decisions, frozen so
    a later membership/assignment/role change can never reinterpret who admitted this work. Current
    assignments, generic roles, IAM, pseudo-principals and client-supplied claims are excluded by
    construction — nothing here reads them."""
    cur.execute("SELECT gate_id::text AS gate_id, stage, quorum, rule_key, status FROM gate WHERE gate_id=%s",
                (gate_id,))
    g = cur.fetchone()
    if not g:
        return None
    cur.execute("""SELECT slot_id, approver_id, decision::text AS decision, revision, decided_at
                     FROM gate_decision WHERE gate_id=%s AND decision='approve'
                    ORDER BY approver_id, slot_id NULLS FIRST, revision""", (gate_id,))
    rows = cur.fetchall() or []
    approvals = [{"slot_id": r["slot_id"], "approver_id": r["approver_id"],
                  "revision": r["revision"], "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None}
                 for r in rows]
    snap = {"gate_id": g["gate_id"], "stage": g["stage"], "quorum": g["quorum"],
            "rule_key": g["rule_key"], "status": g["status"],
            "approver_ids": sorted({a["approver_id"] for a in approvals}),
            "approvals": approvals}
    # The decision GENERATION: a deterministic identity for this exact set of accepted decisions. A
    # further approval (quorum growth, re-approval after rework) yields a different generation, so an
    # attempt authorized under one generation can never be silently attributed to another.
    snap["decision_generation"] = _digest_v1(approvals)
    return snap


def _script_attempt_manifest(cur, round_id, cfg, requested=None):
    """#357 C2 — the canonical ordered manifest that IDENTIFIES one Script attempt.

    This is an EXECUTABLE INPUT CONTRACT, not descriptive metadata: governed execution consumes these
    pinned tuples and this pinned configuration directly. It must therefore contain every input that
    can affect output, and nothing that cannot.

    Returns (manifest, authority_snapshot, error_code). A None manifest always carries an error code —
    the caller fails closed rather than proceeding on a partial manifest."""
    gc = stage_cfg(cfg, "script_review")
    src = gc.get("generates_from")
    if not src:
        return None, None, "stage_not_generative"

    # Eligible items: slots at the configured input status, with their APPROVED topic revision pinned
    # (never head — approving v2 while v3 exists must generate from v2).
    cur.execute("""SELECT s.slot_id,
                          sa.revision AS approved_revision,
                          t.topic_id::text AS topic_id
                     FROM slot s
                     JOIN slot_approval sa ON sa.slot_id = s.slot_id AND sa.artifact = 'topic'
                     LEFT JOIN topic t ON t.slot_id = s.slot_id AND t.revision = sa.revision
                    WHERE s.round_id = %s AND s.status = %s
                    ORDER BY s.slot_id""", (round_id, src))
    items = cur.fetchall() or []
    if not items:
        return None, None, "no_eligible_input"
    if any(i["topic_id"] is None for i in items):
        # An approved revision with no surviving topic row cannot be pinned; refuse rather than guess.
        return None, None, "unresolvable_input_revision"

    # The accepted topic_review decision governing EVERY item. Mixed or superseded generations fail
    # closed: one attempt must rest on one coherent accepted decision.
    cur.execute("""SELECT DISTINCT g.gate_id::text AS gate_id
                     FROM gate g
                     JOIN gate_target gt ON gt.gate_id = g.gate_id
                     JOIN slot s ON s.slot_id = gt.slot_id
                    WHERE s.round_id = %s AND g.stage = 'topic_review' AND g.status = 'approved'""",
                (round_id,))
    gates = [r["gate_id"] for r in (cur.fetchall() or [])]
    if not gates:
        return None, None, "no_accepted_topic_decision"
    if len(gates) > 1:
        return None, None, "mixed_topic_decision_generations"
    authority = _topic_authority_snapshot(cur, gates[0])
    if not authority or not authority["approver_ids"]:
        return None, None, "missing_authority_snapshot"

    wf = active_workflow_stages(cur.connection) if hasattr(cur, "connection") else None
    manifest = {
        "manifest_version": SCRIPT_MANIFEST_VERSION,
        "round_id": round_id,
        "stage": "script",
        # stable slot order — the tuple list is the executable input set
        "items": [{"slot_id": i["slot_id"], "topic_id": i["topic_id"],
                   "topic_revision": i["approved_revision"]} for i in items],
        "source_gate_id": authority["gate_id"],
        "source_decision_generation": authority["decision_generation"],
        "authority_digest": _digest_v1(authority),
        "workflow_version_id": (wf or {}).get("version_id") if wf else None,
        "input_status": src,
        # resolved, output-affecting configuration actually supplied to the writer
        "writer_mode": gc.get("writer_mode"),
        "canonical_route": "POST /rounds/{round_id}/stages/script_review/generate",
        "methodology_version": (cfg.get("methodology") or {}).get("version"),
        "framework_version": (cfg.get("frameworks") or {}).get("version"),
        "writer_contract_version": (cfg.get("models", {}).get("script") or {}).get("contract_version"),
        "prompt_template_version": (cfg.get("models", {}).get("script") or {}).get("prompt_version"),
        "hook_word_min": (cfg.get("voice") or {}).get("hook_word_min"),
        "hook_word_max": (cfg.get("voice") or {}).get("hook_word_max"),
        "script_max_regenerations": (cfg.get("voice") or {}).get("script_max_regenerations"),
        # caller-selectable and therefore IDENTITY: changing these is regeneration, not retry.
        "requested_route": (requested or {}).get("route"),
        "requested_provider": (requested or {}).get("provider"),
        "requested_model": (requested or {}).get("model"),
    }
    return manifest, authority, None


def script_generation_decision(conn, round_id, principal=None, cfg=None, requested=None):
    """#357 C6/F — the SERVER-OWNED typed action decision for Script generation.

    UI, agents and automation PROJECT this; none of them recompute eligibility. Every denial is a
    distinguishable typed reason code — never a generic `unavailable`, a 404, or a provider failure —
    so a caller can tell "you are not an approver" from "the inputs moved" from "nothing to do"."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # #357 C4 — a DURABLE active attempt dominates the decision, whatever the current manifest
        # says. Once execution starts, items move out of the input status and the manifest legitimately
        # changes; looking only for the current digest would miss the in-flight attempt and re-offer
        # Generate. Because this reads the JOB TABLE rather than a process-local registry, an API
        # restart or registry eviction cannot resurrect the offer either.
        cur.execute("""SELECT job_id::text AS job_id, status, manifest_digest
                         FROM generation_job
                        WHERE round_id=%s AND stage='script'
                          AND status IN ('queued','running','awaiting_trigger')
                        ORDER BY created_at DESC LIMIT 1""", (round_id,))
        active = cur.fetchone()
        manifest, authority, err = _script_attempt_manifest(cur, round_id, cfg, requested)
        base = {"action": "script_generate", "round_id": round_id, "stage": "script_review",
                "requires_confirmation": True, "retry_safe": False,
                "manifest_version": SCRIPT_MANIFEST_VERSION}
        if active:
            return {**base, "available": False, "reason_code": "attempt_in_progress",
                    "detail": "A governed Script attempt is already in progress for this run.",
                    "attempt_id": active["job_id"], "job_status": active["status"],
                    "manifest_digest": active["manifest_digest"],
                    "subject_principal": principal, "capability_binding": _NOT_APPLICABLE}
        if err:
            return {**base, "available": False, "reason_code": err,
                    "detail": _SCRIPT_REASON_DETAIL.get(err, "Script generation is not available."),
                    "attempt_id": None, "manifest_digest": None,
                    "subject_principal": principal, "capability_binding": _NOT_APPLICABLE}
        digest = _digest_v1(manifest)
        cur.execute("""SELECT job_id::text AS job_id, status, slots_total, slots_done, slots_failed,
                              error_detail, lease_expires_at, heartbeat_at
                         FROM generation_job
                        WHERE round_id=%s AND stage='script' AND manifest_digest=%s""",
                    (round_id, digest))
        job = cur.fetchone()
        authorized = bool(principal) and principal in (authority["approver_ids"] or [])
        decision = {
            **base,
            "manifest_digest": digest,
            "attempt_id": (job or {}).get("job_id"),
            "job_status": (job or {}).get("status"),
            "input_revisions": manifest["items"],
            "source_gate_id": manifest["source_gate_id"],
            "source_decision_generation": manifest["source_decision_generation"],
            "workflow_version_id": manifest["workflow_version_id"],
            "subject_principal": principal,
            "capability_binding": _NOT_APPLICABLE,
            "retry_safe": bool(job and job["status"] in ("failed",)),
        }
        if not principal:
            return {**decision, "available": False, "reason_code": "principal_missing",
                    "detail": "This action requires a signed principal."}
        if not authorized:
            # Coarse-safe: a valid non-approver and an unknown principal are indistinguishable.
            return {**decision, "available": False, "reason_code": "principal_not_approver",
                    "detail": "Not authorized to start Script generation for this run."}
        if job and job["status"] in ("queued", "running", "awaiting_trigger"):
            return {**decision, "available": False, "reason_code": "attempt_in_progress",
                    "detail": "This exact Script attempt is already in progress."}
        if job and job["status"] in ("completed", "partial"):
            return {**decision, "available": False, "reason_code": "attempt_already_completed",
                    "detail": "This exact Script attempt already produced a result; it is replayed, not regenerated."}
        return {**decision, "available": True, "reason_code": None,
                "detail": "Start governed Script generation for the pinned Topic revisions."}
    finally:
        cur.close()


_SCRIPT_REASON_DETAIL = {
    "stage_not_generative": "The governed workflow does not define an AI generator for this stage.",
    "no_eligible_input": "No approved Topics are waiting for a script.",
    "unresolvable_input_revision": "An approved Topic revision could not be resolved; refusing to guess an input.",
    "no_accepted_topic_decision": "No accepted topic_review decision governs these items.",
    "mixed_topic_decision_generations": "These items span more than one accepted decision; one attempt must rest on one.",
    "missing_authority_snapshot": "The accepted decision carries no affirmative authority to authorize against.",
    "malformed_authority_snapshot": "This attempt's frozen authority cannot be read; refusing rather than assuming.",
}


class ScriptAuthorityUnavailable(GateError):
    """#359 Amendment I — the frozen affirmative authority of an accepted `topic_review` decision is
    missing, malformed, or empty AT THE ACCEPTANCE BOUNDARY.

    This is deliberately NOT a GovernedDenial. A denial is an answer to a request; this is a refusal
    to commit an acceptance at all. Raised from inside the acceptance transaction it propagates out
    unhandled, so `resolve()` never reaches its commit and slot/gate/approval writes roll back
    together with the job — there is no half-accepted gate. The outer owner records the typed audit
    AFTER that rollback, in its own transaction (ruling 2)."""

    def __init__(self, code, round_id=None):
        self.code = code
        self.round_id = round_id
        super().__init__(_SCRIPT_REASON_DETAIL.get(code, code))


def _script_attempt_tx(cur, round_id, cfg, principal=None, requested=None,
                       correlation_id=None, idempotency_key=None,
                       trigger_source="manual_script_start", initiating_actor=None,
                       require_principal=True):
    """#359 ruling 1 — THE one canonical Script-attempt transaction body, shared by the manual
    command and the automatic accepted-decision trigger.

    PURE with respect to transaction ownership: it reads and writes through the caller's cursor and
    NEVER commits, rolls back, opens a connection, calls the committing `_deny` closure, or performs
    a denial-audit side effect. That is not a style rule. `_deny` commits, so invoking it from inside
    the `topic_review` acceptance transaction would commit a HALF-COMPLETED acceptance — slots
    advanced, gate approved, no job — which is precisely the state Amendment A forbids.

    Outcomes are returned as typed data, never raised, with ONE exception: the automatic entry point
    (`require_principal=False`) raises `ScriptAuthorityUnavailable` for missing/malformed/empty
    authority, because Amendment I says that must abort the acceptance rather than answer it.

    Returns {"outcome": ..., ...}:
      replayed  — an active attempt already governs this round; identity unchanged
      created   — this call minted the canonical attempt
      converged — a concurrent caller minted the identical identity first (same digest, one row)
      denied    — a principal-authorization outcome for the MANUAL path (wrapper audits + raises)
      no_start  — a typed non-authority reason for creating nothing (ruling 3): the acceptance
                  stands, no job is fabricated, and the existing typed meaning is preserved
    """
    # #357 B/C4 — an ACTIVE attempt dominates the WRITE path, not merely the read. The unique index
    # alone is insufficient: mid-run, items leave the input status, so a request arriving then builds
    # a manifest over the REMAINING subset — a different identity the index would happily admit.
    cur.execute("""SELECT job_id::text AS job_id, status, slots_total, manifest_digest,
                          authority_snapshot
                     FROM generation_job
                    WHERE round_id=%s AND stage='script'
                      AND status IN ('queued','running','awaiting_trigger')
                    ORDER BY created_at DESC LIMIT 1
                      FOR UPDATE""", (round_id,))
    active = cur.fetchone()
    if active:
        snap = active.get("authority_snapshot")
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except Exception:                          # noqa: BLE001 — unreadable authority is fatal
                snap = None
        approvers = (snap or {}).get("approver_ids") if isinstance(snap, dict) else None
        if not require_principal:
            # AUTOMATIC: idempotent convergence on the attempt that already governs this round. No
            # human principal is invented, and no principal check applies — this is a system
            # consequence of the accepted decision, not a discretionary command (Amendment B).
            # The job's own frozen authority must still be readable; an attempt whose authority
            # cannot be read is one nobody can be shown to be authorized for.
            if not approvers or not isinstance(approvers, list):
                raise ScriptAuthorityUnavailable("malformed_authority_snapshot", round_id)
            return {"outcome": "replayed", "job_id": active["job_id"], "status": active["status"],
                    "total": active["slots_total"], "manifest_digest": active["manifest_digest"]}
        # MANUAL: replay hands back an EXECUTABLE attempt, so it needs the same authority as
        # creation — authorized against THAT JOB'S frozen snapshot, not a freshly resolved one.
        if not principal:
            return {"outcome": "denied", "code": "principal_missing"}
        if not approvers or not isinstance(approvers, list):
            return {"outcome": "denied", "code": "malformed_authority_snapshot"}
        if principal not in approvers:
            return {"outcome": "denied", "code": "principal_not_approver"}
        return {"outcome": "replayed", "job_id": active["job_id"], "status": active["status"],
                "total": active["slots_total"], "manifest_digest": active["manifest_digest"]}

    manifest, authority, err = _script_attempt_manifest(cur, round_id, cfg, requested)
    if err:
        if not require_principal:
            # Ruling 2 vs 3 — the distinction that must not be blurred. ONLY unusable authority
            # aborts the acceptance. `no_eligible_input`, `stage_not_generative`,
            # `unresolvable_input_revision`, `no_accepted_topic_decision` and
            # `mixed_topic_decision_generations` keep their existing typed meanings: no job is
            # fabricated, and an otherwise coherent Topic acceptance still stands.
            if err in ("missing_authority_snapshot", "malformed_authority_snapshot"):
                raise ScriptAuthorityUnavailable(err, round_id)
            return {"outcome": "no_start", "code": err}
        return {"outcome": "denied", "code": err}
    if require_principal:
        if not principal:
            return {"outcome": "denied", "code": "principal_missing"}
        if principal not in (authority["approver_ids"] or []):
            return {"outcome": "denied", "code": "principal_not_approver"}
    elif not (authority.get("approver_ids") or []):
        # Amendment I at its exact point: the accepted decision carries no affirmative authority to
        # freeze onto the job. Abort the acceptance rather than record an unauthorized attempt.
        raise ScriptAuthorityUnavailable("missing_authority_snapshot", round_id)

    digest = _digest_v1(manifest)
    # Ruling 4 — SAME builder, SAME digest, SAME arbitration for both entry points, so automatic and
    # manual cannot diverge in identity. Replay-safe insert against the Script-scoped unique index,
    # then read back: two concurrent callers converge on ONE row.
    _actor = principal if require_principal else (initiating_actor or "system")
    cur.execute("""INSERT INTO generation_job
                     (round_id, stage, status, slots_total, trigger_source, actor,
                      manifest, manifest_digest, manifest_version,
                      source_gate_id, source_gate_generation,
                      initiating_actor, effective_actor, correlation_id, idempotency_key,
                      requested_route, requested_provider, requested_model,
                      authority_snapshot)
                   VALUES (%s,'script','queued',%s,%s,%s,
                           %s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   ON CONFLICT (round_id, manifest_digest) WHERE stage='script' DO NOTHING""",
                (round_id, len(manifest["items"]), trigger_source, _actor,
                 _canonical_json_v1(manifest), digest, SCRIPT_MANIFEST_VERSION,
                 manifest["source_gate_id"], manifest["source_decision_generation"],
                 _actor, principal if require_principal else None,
                 correlation_id, idempotency_key,
                 manifest.get("requested_route"), manifest.get("requested_provider"),
                 manifest.get("requested_model"), _canonical_json_v1(authority)))
    created = cur.rowcount == 1
    cur.execute("""SELECT job_id::text AS job_id, status, slots_total
                     FROM generation_job
                    WHERE round_id=%s AND stage='script' AND manifest_digest=%s""",
                (round_id, digest))
    job = cur.fetchone()
    if created:
        _audit(cur, "round", str(round_id),
               "script_generation_automatic_start_accepted" if not require_principal
               else "script_generation_manual_start_accepted", _actor,
               {"job_id": job["job_id"], "manifest_digest": digest,
                "manifest_version": SCRIPT_MANIFEST_VERSION,
                "trigger_source": trigger_source,
                "source_gate_id": manifest["source_gate_id"],
                "source_decision_generation": manifest["source_decision_generation"],
                "items": len(manifest["items"])})
    return {"outcome": "created" if created else "converged",
            "job_id": job["job_id"], "status": job["status"], "total": job["slots_total"],
            "manifest_digest": digest}


def create_script_generation_attempt(conn, round_id, principal, cfg=None, requested=None,
                                     correlation_id=None, idempotency_key=None):
    """#357 — AUTHORIZE against the frozen Topic authority, then durably mint (or REPLAY) the attempt.

    #359: this is now the TRANSACTION-OWNING WRAPPER around `_script_attempt_tx`. The contract is
    unchanged — same return shape, same typed `GovernedDenial` codes, same append-only denial audit
    that stands even if the audit write itself fails. What moved is only where the commit lives, so
    the automatic accepted-decision trigger can reuse the identical body inside someone else's
    transaction.

    Idempotency is structural, not advisory: the Script-scoped partial unique index on
    (round_id, manifest_digest) means a replay of the same governed manifest cannot insert a second
    job. A duplicate request therefore OBSERVES the existing attempt rather than racing it.
    """
    cfg = cfg or load_config()

    def _deny(code, detail=None):
        try:
            audit_denied(conn, "round", str(round_id), "script_generation_manual_start_denied",
                         principal or "unsigned", {"reason": code, **(detail or {})})
            conn.commit()
        except Exception:                              # noqa: BLE001 — a denial stands regardless
            conn.rollback()
        raise GovernedDenial(_SCRIPT_REASON_DETAIL.get(code, code), code)

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        res = _script_attempt_tx(cur, round_id, cfg, principal=principal, requested=requested,
                                 correlation_id=correlation_id, idempotency_key=idempotency_key)
    except Exception:
        conn.rollback()
        cur.close()
        raise
    if res["outcome"] == "denied":
        # Roll the (read-only) body work back BEFORE auditing, so the denial audit is the only thing
        # this transaction commits.
        conn.rollback()
        cur.close()
        _deny(res["code"])
    conn.commit()
    cur.close()
    return {"job_id": res["job_id"], "status": res["status"], "total": res["total"],
            "manifest_digest": res["manifest_digest"],
            "replayed": res["outcome"] in ("replayed", "converged")}


def claim_script_generation_job(conn, job_id, worker="dispatch"):
    """#357 — atomically LEASE a Script attempt, mirroring claim_topic_generation_job.

    Wins a QUEUED job, or reclaims a 'running' one whose lease has EXPIRED (the worker died without
    finishing) — never one with a live lease. `FOR UPDATE SKIP LOCKED` + the atomic UPDATE mean exactly
    one concurrent caller can win. Returns True only for that winner; everyone else must NOT run it."""
    cur = conn.cursor()
    try:
        # #362 — MINT A FRESH OWNERSHIP TENURE on every claim AND every reclaim.
        #
        # `claimed_by` is a worker NAME (028 calls it diagnostic), so it cannot distinguish two
        # tenures held by the same worker. `claim_token` can: a reclaim mints a new UUID, which
        # instantly invalidates every fenced write the previous owner might still attempt. Amendment
        # L forbids reusing a prior token and forbids encoding the token into `claimed_by`.
        cur.execute("""UPDATE generation_job
                          SET status='running',
                              claim_token = gen_random_uuid(),
                              lease_expires_at = now() + (%s || ' seconds')::interval,
                              heartbeat_at = now(), claimed_by = %s, updated_at = now()
                        WHERE job_id = (SELECT job_id FROM generation_job
                                         WHERE job_id = %s AND stage='script'
                                           AND (status='queued'
                                                OR (status='running' AND lease_expires_at IS NOT NULL
                                                    AND lease_expires_at < now()))
                                         FOR UPDATE SKIP LOCKED)
                        RETURNING claim_token::text""",
                    (str(SCRIPT_GENERATION_LEASE_SECONDS), worker, job_id))
        row = cur.fetchone()
        conn.commit()
        # The token IS the win: a caller that receives one owns this tenure, and every authoritative
        # write it makes must present it. None -> it did not win and must not run.
        return row[0] if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------------------------
# #362 — the FENCED Script ownership surface.
#
# Every function below applies the SAME five-part predicate Amendment L requires:
#   canonical job identity · stage='script' · expected non-terminal state · current claimed_by owner
#   · exact current claim_token
#
# The predicate lives in SQL, in one statement, so ownership is decided by PostgreSQL at write time.
# A separate "am I still the owner?" check followed by a write would be a TOCTOU hole: the reclaim
# can land between the two. Amendment L rules that shape out explicitly.

# Heartbeat cadence. Strictly shorter than the lease with a documented margin (default 300s lease,
# 60s cadence => five heartbeats per lease), so a healthy worker cannot lose ownership to its own
# scheduling jitter, and a dead one is reclaimable within one lease.
# #362 correction C — the OPERATIONAL MARGIN, as one grounded ratio.
#
# A heartbeat cadence is safe only if a worker gets several renewal opportunities inside one lease.
# "Shorter than the lease" is not enough: at lease-1 a single missed beat — a GC pause, a slow
# provider call, one transient DB blip — already loses the lease of a HEALTHY worker, and the drain
# then reclaims work that is still running. Requiring five opportunities per lease means up to four
# consecutive missed beats are survivable before ownership is at risk.
#
# The same ratio sets BOTH the accepted ceiling and the derived default, deliberately: two different
# numbers here would be two different unstated safety claims.
SCRIPT_HEARTBEATS_PER_LEASE = 5


def script_heartbeat_ceiling(lease_seconds=None):
    """The longest cadence that still satisfies the margin. At least 1s for very short leases."""
    lease = int(lease_seconds if lease_seconds is not None
                else SCRIPT_GENERATION_LEASE_SECONDS)
    return max(1, lease // SCRIPT_HEARTBEATS_PER_LEASE)


def _validated_script_heartbeat_seconds(lease_seconds=None):
    """The heartbeat cadence, VALIDATED against the lease margin above.

    Anything unsafe or unparseable FAILS SAFE to the ceiling and says why, rather than being operated
    on. That mirrors the repo's existing convention for runtime limits (`_rework_recovery_batch`
    fails safe to its default on non-numeric or non-positive input) instead of inventing a second
    policy for the same class of setting. Faster cadences than the ceiling are always accepted —
    more frequent renewal is never the unsafe direction.
    """
    lease = int(lease_seconds if lease_seconds is not None
                else SCRIPT_GENERATION_LEASE_SECONDS)
    ceiling = script_heartbeat_ceiling(lease)
    raw = os.environ.get("TANAGHOM_SCRIPTGEN_HEARTBEAT_SECONDS")
    if raw is None or str(raw).strip() == "":
        return ceiling
    try:
        n = int(raw)
    except (TypeError, ValueError):
        print(f"[script-drain] invalid TANAGHOM_SCRIPTGEN_HEARTBEAT_SECONDS={raw!r} "
              f"— using {ceiling}s")
        return ceiling
    if n <= 0:
        print(f"[script-drain] non-positive heartbeat cadence {n}s — using {ceiling}s")
        return ceiling
    if n > ceiling:
        print(f"[script-drain] heartbeat cadence {n}s leaves too little margin against the {lease}s "
              f"lease (need >= {SCRIPT_HEARTBEATS_PER_LEASE} beats per lease) — using {ceiling}s")
        return ceiling
    return n


SCRIPT_HEARTBEAT_SECONDS = _validated_script_heartbeat_seconds()

# Bounded per-pass work for the shared recovery owner (correction D). Mirrors the REWORK drain's
# bounded batch rather than the Topic drain, which selects with no LIMIT at all — copying that would
# let one round's backlog monopolise a recovery cycle and starve Topic and rework progress.
SCRIPT_RECOVERY_BATCH = int(os.environ.get("TANAGHOM_SCRIPTGEN_RECOVERY_BATCH", "5"))


def heartbeat_script_generation_job(conn, job_id, worker, claim_token):
    """#362 — extend THIS tenure's lease, fenced.

    Extends from DATABASE time, never the worker's clock. Returns True only while this worker still
    owns the tenure; False means ownership was lost (reclaimed, terminalised, or never held), and the
    caller must treat itself as non-authoritative from that moment — it may not commit output.

    Cannot revive a queued, terminal, unclaimed, wrong-owner, stale-token or wrong-stage row: each of
    those fails one conjunct of the predicate."""
    cur = conn.cursor()
    try:
        cur.execute("""UPDATE generation_job
                          SET lease_expires_at = now() + (%s || ' seconds')::interval,
                              heartbeat_at = now(), updated_at = now()
                        WHERE job_id = %s
                          AND stage = 'script'
                          AND status = 'running'
                          AND claimed_by = %s
                          AND claim_token = %s::uuid
                        RETURNING job_id""",
                    (str(SCRIPT_GENERATION_LEASE_SECONDS), job_id, worker, claim_token))
        owns = cur.fetchone() is not None
        conn.commit()
        return owns
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def pending_script_generation_jobs(conn, limit=None):
    """#362 — Script attempts the durable drain must recover, BOUNDED per pass.

    Two populations, both meaning 'nobody is executing this': never-started (`queued`), and started
    by a worker that died without finishing (`running` with an EXPIRED lease). A live lease is never
    returned — a healthy run is not a recovery candidate.

    Stage-scoped, so this is the exact mirror of what #360 established for Topic: neither drain can
    ever see the other's rows.
    """
    lim = SCRIPT_RECOVERY_BATCH if limit is None else int(limit)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT job_id::text AS job_id, round_id, slots_total
                         FROM generation_job
                        WHERE stage='script'
                          AND (status='queued'
                               OR (status='running' AND lease_expires_at IS NOT NULL
                                   AND lease_expires_at < now()))
                        ORDER BY created_at
                        LIMIT %s""", (lim,))
        return cur.fetchall()
    finally:
        cur.close()


def script_job_row(conn, job_id):
    """The durable job row, read WITHOUT a stage filter on purpose.

    The caller must be able to see a wrong-stage job in order to refuse it explicitly (correction F's
    bidirectional isolation). Filtering here would make a Topic job indistinguishable from a missing
    one, and 'not found' is a different truth from 'wrong stage'."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT job_id::text AS job_id, round_id, stage, status, slots_total,
                              claimed_by, claim_token::text AS claim_token
                         FROM generation_job WHERE job_id=%s""", (job_id,))
        return cur.fetchone()
    finally:
        cur.close()


def script_attempt_manifest_of(conn, job_id):
    """The immutable manifest persisted with a Script attempt — the executable input contract the
    writer consumes. Read back from the row rather than rebuilt, so execution can never drift from
    what was authorized."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT manifest FROM generation_job WHERE job_id=%s AND stage='script'", (job_id,))
        row = cur.fetchone()
        return (row or {}).get("manifest")
    finally:
        cur.close()


def finish_script_generation_job(conn, job_id, done=0, failed=0, error_detail=None,
                                 worker=None, claim_token=None):
    """Record the terminal state of a Script attempt — FENCED, and it also releases the lease.

    Terminal states are truthful: `completed` only when nothing failed, `partial` when some produced
    and some did not, `failed` when none did.

    #362 correction: ownership is REQUIRED, not optional. A terminal transition and a lease release
    are both authoritative writes — a worker whose tenure was reclaimed must not be able to mark the
    attempt completed, nor release a lease another worker now holds (which would hand a live tenure
    to a third claimant). Earlier this function built its predicate dynamically and simply OMITTED
    the fence when `worker`/`claim_token` were absent, so the weakest caller silently got an
    unfenced UPDATE. There is now ONE static statement that always carries the full predicate, and a
    caller that cannot name its tenure is REFUSED rather than trusted.

    Returns the status string on success, None when the fence rejects the write (including a missing
    or partial ownership claim — fail closed, never a bare UPDATE).
    """
    if worker is None or claim_token is None:
        # Fail closed. Partial ownership is not a weaker claim to be honoured; it is no claim.
        print(f"[fence] refusing terminal write for job {job_id}: ownership not fully specified "
              f"(worker={worker!r}, claim_token={'set' if claim_token else 'missing'})")
        return None
    status = "completed" if failed == 0 and done > 0 else ("partial" if done > 0 else "failed")
    cur = conn.cursor()
    try:
        cur.execute("""UPDATE generation_job
                          SET status=%s, slots_done=%s, slots_failed=%s, error_detail=%s::jsonb,
                              lease_expires_at=NULL, heartbeat_at=now(), updated_at=now()
                        WHERE job_id=%s AND stage='script' AND status='running'
                          AND claimed_by=%s AND claim_token=%s::uuid
                        RETURNING job_id""",
                    (status, done, failed,
                     _canonical_json_v1(error_detail) if error_detail else None, job_id,
                     worker, claim_token))
        won = cur.fetchone() is not None
        conn.commit()
        return status if won else None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def script_tenure_is_current(cur, job_id, worker, claim_token):
    """#362 — is THIS tenure still the owner, decided by the database?

    Used as the guard inside a transaction that is about to persist output or provenance: the check
    and the write share one transaction and one row lock, so a reclaim cannot land between them.
    A NULL stored token never matches, so an unowned row grants no authority."""
    cur.execute("""SELECT 1 FROM generation_job
                    WHERE job_id=%s AND stage='script' AND status='running'
                      AND claimed_by=%s AND claim_token=%s::uuid
                    FOR UPDATE""", (job_id, worker, claim_token))
    return cur.fetchone() is not None


def record_script_generation_results(conn, job_id, runtime_build=None,
                                     worker=None, claim_token=None):
    """#357 — close a Script attempt truthfully. It COUNTS; it never infers.

    Provenance is written by the writer inside the same transaction that produces each revision
    (agents/run_writers.process_script), so a link exists if and only if this attempt actually
    produced the row it describes. This function therefore only reads what production recorded and
    sets the terminal state.

    It deliberately does NOT reconstruct linkage. An earlier revision selected each pinned slot's
    latest Script and attached it to the job — which, for a slot whose writer failed but which
    already held a script from a prior attempt, claimed this attempt produced an older revision.
    Fabricated provenance is worse than missing provenance: nothing downstream can tell it from the
    real thing. Slots that produced nothing are counted as failed and stay unlinked.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT manifest FROM generation_job WHERE job_id=%s AND stage='script'""",
                    (job_id,))
        job = cur.fetchone()
        if not job or not job.get("manifest"):
            return {"linked": 0, "status": None}
        m = job["manifest"] if isinstance(job["manifest"], dict) else json.loads(job["manifest"])
        planned = len(m.get("items") or [])
        # #362 correction — ownership is REQUIRED here too. Closing an attempt is authoritative:
        # it fixes the recorded outcome and releases the lease. A caller that cannot name its tenure
        # is refused, exactly like a caller whose tenure was reclaimed; there is no unfenced path.
        if worker is None or claim_token is None:
            conn.rollback()
            print(f"[fence] refusing to close job {job_id}: ownership not fully specified")
            return {"linked": 0, "planned": planned, "status": None, "fenced_out": True}
        if not script_tenure_is_current(cur, job_id, worker, claim_token):
            conn.rollback()
            return {"linked": 0, "planned": planned, "status": None, "fenced_out": True}
        cur.execute("SELECT count(*) AS n FROM script_provenance WHERE job_id=%s", (job_id,))
        linked = cur.fetchone()["n"]
        status = finish_script_generation_job(conn, job_id, done=linked,
                                              failed=max(0, planned - linked),
                                              worker=worker, claim_token=claim_token)
        return {"linked": linked, "planned": planned, "status": status,
                "fenced_out": status is None}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def active_workflow_stages(conn):
    """#355 — the ACTIVE governed workflow version's stage contract, read WITHOUT any side effect.

    WHY THIS EXISTS SEPARATELY FROM get_workflow_version(). Every existing workflow read calls
    _ensure_workflow_seed(), which, when no active version exists, INSERTs the workflow row with
    `ON CONFLICT ... DO UPDATE SET name, description` — i.e. it can OVERWRITE an operator-owned
    workflow row's metadata as a side effect of a GET. That is acceptable for an administrative
    surface that is about to author a version; it is not acceptable for ordinary read-only
    navigation, which must never mutate what it is describing.

    So this is a pure SELECT. It creates and updates nothing, and it FAILS CLOSED: when there is no
    active version it returns None rather than manufacturing one, and the caller renders an explicit
    unavailable state. Adds no schema, no migration and no authority.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT version_id::text AS version_id, version_no, status
                       FROM workflow_version
                       WHERE tenant_id='default' AND module='content' AND status='active'
                       ORDER BY activated_at DESC NULLS LAST, created_at DESC
                       LIMIT 1""")
        row = cur.fetchone()
        if not row:
            return None
        row["stages"] = _workflow_stage_read_model(cur, row["version_id"])
        return row
    finally:
        cur.close()


def active_workflow_stage_projection(conn):
    """#376 — the CANONICAL ACTIVE-STAGE PROJECTION: the lifecycle stages the resolved active
    governed generation actually ENABLES, and nothing else.

    WHY A SERVER PROJECTION AND NOT A CLIENT FILTER. `active_workflow_stages` returns the full
    generation contract, disabled stages included, and that is correct for an administrative or
    diagnostic reader. But a surface that must show only the LIVE lifecycle would then have to
    fetch-all-and-filter — a second, client-local policy decision about which governed stages count,
    which is exactly the parallel mapping #355 removed and #376 forbids. The decision belongs to
    whoever resolves the generation, so it is made here, once.

    The exclusion is DERIVED FROM THE ARTIFACT'S OWN `enabled` COLUMN — never from a stage-name
    list, a hardcoded omission set, or a config lookup. A stage disappears from the lifecycle only
    because the governed generation disabled it, and re-enabling it in a new generation brings it
    back with no code change.

    `disabled_stage_count` is disclosed so a reader can tell "the generation enables exactly these"
    apart from "the generation declares only these" — two very different truths. The excluded stages
    themselves are deliberately NOT returned: a caller that received them could rebuild the omission
    list this projection exists to prevent. A caller needing them reads the full contract.

    Pure SELECT, side-effect-free, and fail-closed exactly like the endpoint it projects: no active
    version -> None, and the caller renders an explicit unavailable state rather than an invented
    rail. Adds no schema, no migration and no authority.
    """
    snap = active_workflow_stages(conn)
    if snap is None:
        return None
    stages = [s for s in snap["stages"] if s.get("enabled")]
    return {
        "version_id": snap["version_id"],
        "version_no": snap["version_no"],
        "status": snap["status"],
        "stages": stages,
        "disabled_stage_count": len(snap["stages"]) - len(stages),
    }


def get_workflow_version(conn, version_id=None, *, active=False, cfg=None):
    cfg = cfg or load_config()
    _ensure_workflow_seed(conn, cfg)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if active:
            cur.execute("""SELECT version_id::text AS version_id FROM workflow_version
                           WHERE tenant_id='default' AND module='content' AND status='active'
                           ORDER BY activated_at DESC NULLS LAST, created_at DESC
                           LIMIT 1""")
            row = cur.fetchone()
            if not row:
                raise GateError("no active workflow version")
            version_id = row["version_id"]
        if not version_id:
            raise GateError("workflow version id required")
        return _workflow_version_read_model(cur, version_id)
    finally:
        cur.close()


def create_workflow_version_draft(conn, workflow_key=WORKFLOW_KEY, actor="system", cfg=None):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer workflows")
    cfg = cfg or load_config()
    _ensure_workflow_seed(conn, cfg)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT workflow_id::text AS workflow_id FROM workflow
                       WHERE workflow_key=%s AND tenant_id='default' AND module='content'""", (workflow_key,))
        workflow = cur.fetchone()
        if not workflow:
            raise GateError(f"unknown workflow {workflow_key}")
        workflow_id = workflow["workflow_id"]
        cur.execute("SELECT coalesce(max(version_no), 0) AS max_version FROM workflow_version WHERE workflow_id=%s",
                    (workflow_id,))
        version_no = int(cur.fetchone()["max_version"]) + 1
        cur.execute("""SELECT version_id::text AS version_id FROM workflow_version
                       WHERE workflow_id=%s AND status='active'
                       ORDER BY version_no DESC LIMIT 1""", (workflow_id,))
        active_version = cur.fetchone()
        cur.execute("""INSERT INTO workflow_version
                       (workflow_id, version_no, status, source, notes, created_by, updated_by,
                        tenant_id, module)
                       VALUES (%s,%s,'draft','admin',%s,%s,%s,'default','content')
                       RETURNING version_id::text AS version_id""",
                    (workflow_id, version_no, "Draft cloned from active workflow", actor, actor))
        version_id = cur.fetchone()["version_id"]
        if active_version:
            cur.execute("""INSERT INTO workflow_stage
                           (version_id, stage_key, stage_label, stage_group, ordinal, enabled, bypassable,
                            mandatory, gate_stage, stage_kind, generator_kind, scope, policy,
                            review_statuses, approve_to, changes_to, reject_to, rework_mode,
                            generates_from, writer_mode, requires_flag, allow_partial_batch,
                            enforce_mandatory_reviews, approval_rule)
                           SELECT %s, stage_key, stage_label, stage_group, ordinal, enabled, bypassable,
                                  mandatory, gate_stage, stage_kind, generator_kind, scope, policy,
                                  review_statuses, approve_to, changes_to, reject_to, rework_mode,
                                  generates_from, writer_mode, requires_flag, allow_partial_batch,
                                  enforce_mandatory_reviews, approval_rule
                           FROM workflow_stage WHERE version_id=%s""",
                        (version_id, active_version["version_id"]))
            cur.execute("""INSERT INTO workflow_transition
                           (version_id, from_stage_key, to_stage_key, condition_key, enabled)
                           SELECT %s, from_stage_key, to_stage_key, condition_key, enabled
                           FROM workflow_transition WHERE version_id=%s""",
                        (version_id, active_version["version_id"]))
        else:
            _seed_workflow_version(cur, workflow_id, version_no, "draft", "admin", actor, cfg,
                                   notes="Draft seeded from system_config.yaml")
        _audit(cur, "workflow_version", version_id, "workflow_version_created", actor, {
            "workflow_key": workflow_key,
            "version_no": version_no,
        })
        conn.commit()
        return get_workflow_version(conn, version_id, cfg=cfg)
    finally:
        cur.close()


def update_workflow_version(conn, version_id, payload, actor="system", cfg=None):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer workflows")
    cfg = cfg or load_config()
    _ensure_workflow_seed(conn, cfg)
    normalized = _normalize_workflow_version_payload(payload, cfg)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _workflow_version_read_model(cur, version_id)
        if before["status"] != "draft":
            raise GateError("only draft workflow versions may be edited")
        cur.execute("""UPDATE workflow_version
                       SET notes=%s, updated_by=%s, updated_at=now()
                       WHERE version_id=%s""", (normalized["notes"], actor, version_id))
        cur.execute("DELETE FROM workflow_transition WHERE version_id=%s", (version_id,))
        cur.execute("DELETE FROM workflow_stage WHERE version_id=%s", (version_id,))
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO workflow_stage
               (version_id, stage_key, stage_label, stage_group, ordinal, enabled, bypassable, mandatory,
                gate_stage, stage_kind, generator_kind, scope, policy, review_statuses, approve_to,
                changes_to, reject_to, rework_mode, generates_from, writer_mode, requires_flag,
                allow_partial_batch, enforce_mandatory_reviews, approval_rule)
               VALUES %s""",
            [(
                version_id, row["stage_key"], row["stage_label"], row["stage_group"], row["ordinal"],
                row["enabled"], row["bypassable"], row["mandatory"], row["gate_stage"], row["stage_kind"],
                row["generator_kind"], row["scope"], row["policy"], Json(row["review_statuses"]),
                row["approve_to"], row["changes_to"], row["reject_to"], row["rework_mode"],
                row["generates_from"], row["writer_mode"], row["requires_flag"],
                row["allow_partial_batch"], row["enforce_mandatory_reviews"], row["approval_rule"],
            ) for row in normalized["stages"]],
        )
        if normalized["transitions"]:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO workflow_transition
                   (version_id, from_stage_key, to_stage_key, condition_key, enabled)
                   VALUES %s""",
                [(
                    version_id, row["from_stage_key"], row["to_stage_key"], row["condition_key"],
                    row["enabled"],
                ) for row in normalized["transitions"]],
            )
        after = _workflow_version_read_model(cur, version_id)
        _audit(cur, "workflow_version", version_id, "workflow_version_updated", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def activate_workflow_version(conn, version_id, actor="system", cfg=None):
    if not can_administer_approval_policies(conn, actor):
        raise GateError(f"{actor!r} may not administer workflows")
    cfg = cfg or load_config()
    _ensure_workflow_seed(conn, cfg)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        before = _workflow_version_read_model(cur, version_id)
        cur.execute("""SELECT workflow_id FROM workflow_version WHERE version_id=%s""", (version_id,))
        row = cur.fetchone()
        if not row:
            raise GateError(f"unknown workflow version {version_id}")
        workflow_id = row["workflow_id"]
        cur.execute("""UPDATE workflow_version
                       SET status='inactive', updated_by=%s, updated_at=now()
                       WHERE tenant_id='default' AND module='content' AND status='active'""", (actor,))
        cur.execute("""UPDATE workflow_version
                       SET status='active', updated_by=%s, updated_at=now(),
                           activated_by=%s, activated_at=now()
                       WHERE version_id=%s""", (actor, actor, version_id))
        cur.execute("""UPDATE workflow
                       SET updated_at=now()
                       WHERE workflow_id=%s""", (workflow_id,))
        after = _workflow_version_read_model(cur, version_id)
        _audit(cur, "workflow_version", version_id, "workflow_version_activated", actor, {
            "before": before,
            "after": after,
        })
        conn.commit()
        return after
    finally:
        cur.close()


def _principal_assignment_tokens(cur, principal_id):
    tokens = {("user", principal_id)}
    cur.execute("""SELECT role_id FROM principal_role_member
                   WHERE principal_id=%s AND active=true""", (principal_id,))
    tokens.update(("role", r["role_id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall())
    cur.execute("""SELECT group_id FROM principal_group_member
                   WHERE principal_id=%s AND active=true""", (principal_id,))
    tokens.update(("group", r["group_id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall())
    return sorted(tokens)


def list_pending_approvals(conn, principal_id):
    """Open gates the principal can act on — the reviewer-centric 'what's waiting on me?' read model.
    #282 P1.2: an AUTHORITATIVE gate (migration 025) reads the FROZEN snapshot eligibility + per-token
    coverage, so this queue agrees with gate detail, resolve, and audit (an actor frozen-eligible at
    open still sees the gate after a later membership removal; one added after open does not). LEGACY
    gates (no authoritative snapshot) keep live-membership + count-based behavior unchanged."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    tokens = _principal_assignment_tokens(cur, principal_id)          # live tokens (legacy gates only)

    # authoritative open gates where the principal is FROZEN-eligible for some required token
    cur.execute("""SELECT DISTINCT g.gate_id::text AS gate_id
                   FROM gate g
                   JOIN gate_snapshot gs ON gs.gate_id=g.gate_id AND gs.authoritative
                   JOIN gate_snapshot_token gst ON gst.snapshot_id=gs.snapshot_id
                   JOIN gate_snapshot_eligible ge ON ge.snapshot_token_id=gst.snapshot_token_id
                   WHERE g.status='open' AND ge.principal_id=%s""", (principal_id,))
    auth_ids = {r["gate_id"] for r in cur.fetchall()}

    # legacy open gates (no authoritative snapshot) the principal matches via LIVE membership tokens
    legacy_ids = set()
    if tokens:
        clauses, params = [], []
        for kind, key in tokens:
            clauses.append("(ga.assignment_kind=%s AND ga.assignment_key=%s)")
            params.extend([kind, key])
        cur.execute(f"""SELECT DISTINCT g.gate_id::text AS gate_id FROM gate g
                        JOIN gate_assignment ga ON ga.gate_id=g.gate_id
                        WHERE g.status='open'
                          AND g.gate_id NOT IN (SELECT gate_id FROM gate_snapshot WHERE authoritative)
                          AND ({' OR '.join(clauses)})""", params)
        legacy_ids = {r["gate_id"] for r in cur.fetchall()}

    gate_ids = sorted(auth_ids | legacy_ids)
    if not gate_ids:
        cur.close()
        return []
    cur.execute("""SELECT g.gate_id, g.stage, g.rule_key, g.quorum, g.status, g.created_at,
                          max(sl.round_id) AS round_id, count(DISTINCT t.slot_id) AS total_targets
                   FROM gate g JOIN gate_target t ON t.gate_id=g.gate_id
                   JOIN slot sl ON sl.slot_id=t.slot_id
                   WHERE g.gate_id::text = ANY(%s)
                   GROUP BY g.gate_id ORDER BY g.created_at DESC""", (gate_ids,))
    rows = cur.fetchall()
    cur.execute("""SELECT gate_id::text AS gate_id, slot_id FROM gate_target
                   WHERE gate_id::text = ANY(%s) ORDER BY gate_id, slot_id""", (gate_ids,))
    target_map = {}
    for row in cur.fetchall():
        target_map.setdefault(row["gate_id"], []).append(row["slot_id"])
    cur.execute("""SELECT gate_id::text AS gate_id, assignment_kind, assignment_key, resolved_principal_id
                   FROM gate_assignment WHERE gate_id::text = ANY(%s)
                   ORDER BY gate_id, assignment_kind, assignment_key""", (gate_ids,))
    assignment_map = {}
    for row in cur.fetchall():
        assignment_map.setdefault(row["gate_id"], []).append({
            "assignment_kind": row["assignment_kind"], "assignment_key": row["assignment_key"],
            "resolved_principal_id": row["resolved_principal_id"]})
    cur.execute("""SELECT gate_id::text AS gate_id, slot_id, approver_id, decision, revision
                   FROM gate_decision WHERE gate_id::text = ANY(%s)
                   ORDER BY gate_id, slot_id, decided_at, approver_id""", (gate_ids,))
    decisions = {}
    for row in cur.fetchall():
        decisions.setdefault(row["gate_id"], {}).setdefault(row["slot_id"], []).append(row)
    _pa_cfg = load_config()
    out = []
    for r in rows:
        gate_key = str(r["gate_id"])
        gate_decisions = decisions.get(gate_key, {})
        snapshot = _load_gate_snapshot(cur, r["gate_id"])
        if snapshot is not None:
            # authoritative: eligibility + outcome from the frozen snapshot + coverage
            all_assignments = _enrich_assignment_snapshots(
                cur, [{"assignment_kind": t["kind"], "assignment_key": t["key"]} for t in snapshot["tokens"]])
            matched_assignments = [a for a in all_assignments if any(
                t["kind"] == a["assignment_kind"] and t["key"] == a["assignment_key"]
                and principal_id in t["eligible"] for t in snapshot["tokens"])]
            remaining = 0
            for slot_id in target_map.get(gate_key, []):
                slot_decisions = gate_decisions.get(slot_id, [])
                # #321 P1.4 — "mine/currently decided" uses EXACT-current-head semantics for approvals:
                # a superseded approval (head advanced past it) does NOT count as decided, so the
                # reviewer who must re-review the new head is still surfaced as remaining.
                # reject/request_change are revision-independent (kept by _effective_decisions_for_head).
                _eff = _effective_decisions_for_head(
                    slot_decisions, _gate_review_head(cur, _pa_cfg, r["stage"], slot_id))
                mine = any(d["approver_id"] == principal_id for d in _eff)
                outcome = _authoritative_outcome(snapshot, slot_decisions, _covered_token_ids(cur, r["gate_id"], slot_id))
                if outcome == "pending" and not mine:
                    remaining += 1
        else:
            # legacy: live-membership tokens + count-based rollup
            all_assignments = _enrich_assignment_snapshots(cur, assignment_map.get(gate_key, []))
            matched_assignments = [a for a in all_assignments
                                   if (a["assignment_kind"], a["assignment_key"]) in tokens]
            remaining = 0
            for slot_id in target_map.get(gate_key, []):
                slot_decisions = gate_decisions.get(slot_id, [])
                # #321 P1.4 — exact-current-head effective decisions drive BOTH the outcome and "mine".
                _eff = _effective_decisions_for_head(
                    slot_decisions, _gate_review_head(cur, _pa_cfg, r["stage"], slot_id))
                mine = any(d["approver_id"] == principal_id for d in _eff)
                if _decision_rollup(_eff, int(r["quorum"]))["current_outcome"] == "pending" and not mine:
                    remaining += 1
        if remaining > 0:
            r["decided_targets"] = int(r["total_targets"]) - remaining
            r["remaining_targets"] = remaining
            r["all_assignments"] = all_assignments
            r["matched_assignments"] = matched_assignments
            out.append(r)
    cur.close()
    return out


def _round_phase(r):
    """A persistent, human round status from the slot mix (planned -> active -> in-review ->
    awaiting-regeneration -> approved -> scheduled; 'dropped' surfaced separately as a count)."""
    if r["slots"] and r["reserved"] == r["slots"]:
        return "planned"
    if (r["schedule_approved"] and not r["reserved"]
            and not (r["topic_proposed"] or r["draft"] or r["changes_requested"]
                     or r["topic_approved"] or r["approved"] or r["scheduled"])):
        return "titles-pending"
    if r["scheduled"] and not (r["topic_proposed"] or r["draft"] or r["changes_requested"]
                               or r["topic_approved"] or r["approved"] or r["schedule_approved"]):
        return "scheduled"
    if r["topic_proposed"] or r["draft"]:
        return "in-review"
    if r["changes_requested"]:
        return "awaiting-regeneration"
    if r["topic_approved"] or r["approved"] or r["scheduled"]:
        return "approved"
    if r["reserved"] or r["schedule_approved"]:
        return "active"
    if r["rejected"]:
        return "dropped"
    return "active"


def list_changes_requested(conn, round_id=None, cfg=None):
    """Slots parked at an 'awaiting rework' status (CHANGES_REQUESTED), with the reviewer comment
    that sent them back + their current revision — for the surface's 'awaiting regeneration' panel
    and the rework trigger. Optionally scoped to round_id."""
    cfg = cfg or load_config()
    cs = list(changes_statuses(cfg))
    if not cs:
        return []
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = ("SELECT s.slot_id, s.pillar_code, s.status, s.round_id, "
         "  (SELECT gd.notes FROM gate_decision gd WHERE gd.slot_id=s.slot_id "
         "   AND gd.decision='request_change' ORDER BY gd.decided_at DESC LIMIT 1) AS comment, "
         "  COALESCE((SELECT max(revision) FROM topic t WHERE t.slot_id=s.slot_id), "
         "           (SELECT max(revision) FROM script sc WHERE sc.slot_id=s.slot_id), 1) AS revision "
         "FROM slot s WHERE s.status::text = ANY(%s)")
    params = [cs]
    if round_id:
        q += " AND s.round_id=%s"; params.append(round_id)
    q += " ORDER BY s.slot_id"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def list_dropped(conn, round_id=None, cfg=None):
    """Slots in a reversible 'dropped' state (REJECTED) — the recoverable Dropped view. Includes the
    reject note (if any) + hook for display. Optionally scoped to round_id. Restore via reopen()."""
    cfg = cfg or load_config()
    rs = list(reject_statuses(cfg))
    if not rs:
        return []
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = ("SELECT s.slot_id, s.pillar_code, s.status, s.round_id, s.hook_text, s.updated_at, "
         "  (SELECT gd.notes FROM gate_decision gd WHERE gd.slot_id=s.slot_id "
         "   AND gd.decision='reject' ORDER BY gd.decided_at DESC LIMIT 1) AS reason "
         "FROM slot s WHERE s.status::text = ANY(%s)")
    params = [rs]
    if round_id:
        q += " AND s.round_id=%s"; params.append(round_id)
    q += " ORDER BY s.slot_id"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _slot_location(cfg, status):
    """#179 — locate a slot's CURRENT status against the configured stage chain, for the durable
    approved-items trail. Purely descriptive (config-driven, no new state):
      in_review @ stage   — the status is some stage's reviews_status (it moved into that review);
      advanced @ stage    — the status is some stage's approve_to (approved there, awaiting the
                            next step, e.g. generation into the following stage);
      changes / dropped   — sent back for regeneration / recoverable-dropped;
      other               — anything outside the configured chain (shown as the raw status)."""
    if status in changes_statuses(cfg):
        return {"kind": "changes", "stage": None}
    if status in reject_statuses(cfg):
        return {"kind": "dropped", "stage": None}
    for stage_key, _meta in WORKFLOW_STAGE_LIBRARY:
        gc = stage_cfg(cfg, stage_key)
        if not gc:
            continue
        rs = gc.get("reviews_status")
        review_statuses = rs if isinstance(rs, list) else ([rs] if rs else [])
        if status in review_statuses:
            return {"kind": "in_review", "stage": stage_key}
    for stage_key, _meta in WORKFLOW_STAGE_LIBRARY:
        gc = stage_cfg(cfg, stage_key)
        if gc and gc.get("approve_to") == status:
            return {"kind": "advanced", "stage": stage_key}
    return {"kind": "other", "stage": None}


def list_advanced(conn, round_id, stage, cfg=None):
    """#179 — the durable post-commit trail: slots this stage already APPROVED and advanced,
    derived entirely from EXISTING committed state (resolved gates' per-slot decision rollups —
    the same `_slot_outcome` the resolve() commit itself applied — plus each slot's live row).
    Read-only; no new persistence. A later reopen/regeneration simply shows as the item's true
    current location, so the trail never lies about where content is NOW."""
    cfg = cfg or load_config()
    gc = stage_cfg(cfg, stage)
    rs = gc.get("reviews_status", "DRAFT_ASSIGNED")
    review_statuses = rs if isinstance(rs, list) else [rs]
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Include OPEN gates too: a per-item immediate approval partial-resolves and leaves the gate
    # open, but the slot has already committed + advanced. What keeps staged-but-uncommitted
    # approvals out is the slot's LIVE status below: anything still sitting at this stage's review
    # status hasn't moved (and a reopened item truthfully drops back out of the trail into the queue).
    cur.execute("""SELECT g.gate_id::text AS gate_id, g.quorum, t.slot_id
                   FROM gate g
                   JOIN gate_target t USING (gate_id)
                   JOIN slot s ON s.slot_id = t.slot_id
                   WHERE g.stage=%s AND s.round_id=%s
                     AND g.status <> 'superseded'
                     AND NOT (s.status::text = ANY(%s))""", (stage, round_id, review_statuses))
    targets = cur.fetchall()
    if not targets:
        cur.close()
        return []
    gate_ids = sorted({r["gate_id"] for r in targets})
    cur.execute("""SELECT gate_id::text AS gate_id, slot_id, approver_id, decision, decided_at
                   FROM gate_decision WHERE gate_id::text = ANY(%s)
                   ORDER BY decided_at""", (gate_ids,))
    dec_by = {}
    for d in cur.fetchall():
        dec_by.setdefault((d["gate_id"], d["slot_id"]), []).append(d)
    approved = {}   # slot_id -> {approved_at, approved_by} (latest committed approval wins)
    for row in targets:
        ds = dec_by.get((row["gate_id"], row["slot_id"]), [])
        if _slot_outcome(ds, int(row["quorum"])) != "approved":
            continue
        last_approve = [d for d in ds if d["decision"] == "approve"][-1]
        prev = approved.get(row["slot_id"])
        if not prev or last_approve["decided_at"] > prev["approved_at"]:
            approved[row["slot_id"]] = {"approved_at": last_approve["decided_at"],
                                        "approved_by": last_approve["approver_id"]}
    if not approved:
        cur.close()
        return []
    # #219 — additive read-only canonical ID fields (pillar_short_code, seq_in_pillar,
    # pillar_name_en, hcs_name_en) so the completed-trail inspection controls can reuse the exact
    # content-ID formatter + Detailed descriptor the active review cards use. Same joins the active
    # target selection already proves canonical; LEFT so trail membership is unchanged.
    cur.execute("""SELECT s.slot_id, s.round_id, s.status, s.pillar_code, s.hook_text, s.format,
                          s.day, s.time_uae, t.text_ar AS topic_text,
                          p.code_short AS pillar_short_code, p.name_en AS pillar_name_en,
                          h.seq_in_pillar, h.name_en AS hcs_name_en
                   FROM slot s
                   LEFT JOIN topic t ON t.slot_id = s.slot_id
                        AND t.revision = (SELECT max(revision) FROM topic WHERE slot_id = s.slot_id)
                   LEFT JOIN pillar p ON p.pillar_code = s.pillar_code
                   LEFT JOIN hcs h ON h.hcs_id = s.hcs_id
                   WHERE s.slot_id = ANY(%s)""", (sorted(approved),))
    rows = []
    for r in cur.fetchall():
        loc = _slot_location(cfg, r["status"])
        rows.append({**r,
                     "approved_at": approved[r["slot_id"]]["approved_at"],
                     "approved_by": approved[r["slot_id"]]["approved_by"],
                     "location_kind": loc["kind"],
                     "location_stage": loc["stage"],
                     "location_stage_label": WORKFLOW_STAGE_META.get(loc["stage"], {}).get("label") if loc["stage"] else None})
    cur.close()
    rows.sort(key=lambda r: r["slot_id"])
    return rows


def inspect_slot(conn, slot_id, cfg=None):
    """#237 Slice A — status-independent, READ-ONLY inspection projection for ONE slot, so the
    completed trail can open the same content definition the active review card shows. Approval
    changes mutation authority, not information. Everything here is existing persisted truth:
    slot/pillar/HCS/lens context, the slot_approval-PINNED topic/script revision (falling back to
    the head when nothing is pinned — labeled, never silently conflated), full decision history,
    and existing production assets. No writes, no new state; absent artifacts return None and the
    surface must present that as truthful absence, never fabricate."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT s.slot_id, s.round_id, s.status, s.day, s.time_uae, s.format,
                          s.hook_text, s.hook_type, s.topic_angle, s.cycle_no,
                          s.pillar_code, p.code_short AS pillar_short_code,
                          p.name_en AS pillar_name_en, p.name_ar AS pillar_name_ar,
                          s.hcs_id, h.seq_in_pillar, h.name_en AS hcs_name_en, h.name_ar AS hcs_name_ar,
                          s.lens, ln.name_en AS lens_name_en, ln.name_ar AS lens_name_ar
                   FROM slot s
                   JOIN pillar p ON p.pillar_code = s.pillar_code
                   JOIN hcs h ON h.hcs_id = s.hcs_id
                   LEFT JOIN lens ln ON ln.lens_id = s.lens
                   WHERE s.slot_id=%s""", (slot_id,))
    slot = cur.fetchone()
    if not slot:
        cur.close()
        raise GateError(f"no such slot {slot_id}")
    loc = _slot_location(cfg, slot["status"])
    slot["location_kind"] = loc["kind"]
    slot["location_stage"] = loc["stage"]
    slot["location_stage_label"] = (WORKFLOW_STAGE_META.get(loc["stage"], {}).get("label")
                                    if loc["stage"] else None)

    def _artifact(artifact, fields):
        # the slot_approval PIN decides which revision downstream stages read (approve v2 even if
        # v3 exists) — show THAT revision when pinned, else the head, and say which it was.
        cur.execute("SELECT revision, approver, actor_kind, at FROM slot_approval "
                    "WHERE slot_id=%s AND artifact=%s", (slot_id, artifact))
        pin = cur.fetchone()
        cur.execute(f"SELECT max(revision) AS head FROM {artifact} WHERE slot_id=%s", (slot_id,))
        head_row = cur.fetchone()
        head = head_row["head"] if head_row else None
        rev = pin["revision"] if pin else head
        if rev is None:
            return None
        cur.execute(f"SELECT {fields} FROM {artifact} WHERE slot_id=%s AND revision=%s",
                    (slot_id, rev))
        row = cur.fetchone()
        if not row:
            return None
        row["approved"] = bool(pin)
        row["approved_by"] = pin["approver"] if pin else None
        row["approved_at"] = pin["at"] if pin else None
        row["head_revision"] = head
        return row

    slot["topic"] = _artifact("topic",
        "revision, hook_text, text_ar, rationale_ar, rationale_en, feedback, "
        "change_summary_ar, change_summary_en, base_revision, created_at")
    slot["script"] = _artifact("script",
        "revision, script_ar, structure, final_line, delivery_notes, delivery_check, flags, "
        "model, needs_scholar_review, needs_native_review, feedback, "
        "change_summary_ar, change_summary_en, base_revision, created_at")
    cur.execute("""SELECT g.stage, d.approver_id, d.decision, d.notes, d.decided_at
                   FROM gate_decision d JOIN gate g ON g.gate_id = d.gate_id
                   WHERE d.slot_id=%s ORDER BY d.decided_at, d.approver_id""", (slot_id,))
    slot["decisions"] = cur.fetchall()
    slot["assets"] = dam.list_assets(cur, slot_id)
    # #255 S1 — the approved MASTER edit pin vs the current master head, both resolved with the
    # exact master predicate (stage='media_edit', kind='edit', platform_variant IS NULL). The
    # pinned version row is looked up WITHOUT a status filter (supersession must never hide the
    # approved history); the current head is the active master. A later master version must show
    # as drift — the displayed approved edit never silently moves.
    cur.execute("SELECT revision, approver, at FROM slot_approval "
                "WHERE slot_id=%s AND artifact='edit'", (slot_id,))
    edit_pin = cur.fetchone()
    cur.execute("""SELECT asset_id, version FROM asset
                    WHERE slot_id=%s AND stage='media_edit' AND kind='edit'
                      AND platform_variant IS NULL AND status='active'""", (slot_id,))
    masters = cur.fetchall()
    master_head = masters[0] if len(masters) == 1 else None
    if edit_pin:
        # the EXACT pinned asset identity comes from the newest matching IMMUTABLE
        # `approved_edit_master_pinned` audit event — never re-identified from the revision
        # number (the (slot, stage, kind, variant, revision) tuple is not uniquely constrained,
        # so a malformed duplicate row could otherwise be displayed as the approved one). The
        # event's asset row is verified against the master tuple + pinned revision; a missing
        # or contradicted event is reported as a truthful non-verified state, never guessed.
        cur.execute("""SELECT detail FROM audit_log
                        WHERE entity='slot' AND entity_id=%s
                          AND action='approved_edit_master_pinned'
                          AND (detail->>'revision')::int = %s
                        ORDER BY id DESC LIMIT 1""", (slot_id, edit_pin["revision"]))
        pin_event = cur.fetchone()
        pinned_asset_id, pin_evidence = None, "unavailable"     # no matching immutable event
        if pin_event:
            event_asset = pin_event["detail"].get("asset_id")
            cur.execute("""SELECT 1 FROM asset
                            WHERE asset_id=%s AND slot_id=%s AND stage='media_edit'
                              AND kind='edit' AND platform_variant IS NULL AND version=%s""",
                        (event_asset, slot_id, edit_pin["revision"]))
            if cur.fetchone():
                pinned_asset_id, pin_evidence = event_asset, "audit"
            else:
                pin_evidence = "inconsistent"                   # event contradicts asset truth
        slot["approved_edit"] = {
            "pinned_revision": edit_pin["revision"],
            "pinned_asset_id": pinned_asset_id,
            "pin_evidence": pin_evidence,
            "approved_by": edit_pin["approver"],
            "approved_at": edit_pin["at"],
            "current_master_revision": master_head["version"] if master_head else None,
            "current_master_ambiguous": len(masters) > 1,
            "drifted": bool(master_head and master_head["version"] != edit_pin["revision"]),
        }
    else:
        slot["approved_edit"] = None
    cur.close()
    return slot


def list_gates(conn, status=None, round_id=None):
    """Gates with their round (derived from targets). Scoped to round_id when given so each
    surface tab shows only the gate for the selected round + stage."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = ("SELECT g.gate_id, g.stage, g.scope, g.policy, g.quorum, g.status, g.created_at, "
         "       count(t.slot_id) AS targets, max(sl.round_id) AS round_id "
         "FROM gate g LEFT JOIN gate_target t USING (gate_id) "
         "LEFT JOIN slot sl ON sl.slot_id = t.slot_id ")
    params, where = [], []
    if status:
        where.append("g.status=%s"); params.append(status)
    if where:
        q += "WHERE " + " AND ".join(where) + " "
    q += "GROUP BY g.gate_id "
    if round_id:
        q += "HAVING max(sl.round_id)=%s "; params.append(round_id)
    q += "ORDER BY g.created_at DESC"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def get_gate(conn, gate_id):
    """Full gate detail: meta + per-target slot (pillar/HCS/lens/hook + script preview +
    flags) + each approver's decision so far. Used by every review surface."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM gate WHERE gate_id=%s", (gate_id,))
    gate = cur.fetchone()
    if not gate:
        raise GateError(f"no such gate {gate_id}")
    cfg = load_config()
    # #265 — self-heal before returning any gate view: converge the target set so a gate reused
    # across late generation shows the COMPLETE review population. Idempotent no-op when converged.
    # While generator work remains the population is knowably in flux — fail closed (GateNotReady)
    # rather than serve a partial target set as if it were the review.
    if gate["status"] == "open":
        _guard_generation_complete(cur, cfg, gate_id, gate["stage"], gate["status"])
        reconcile_gate_targets(cur, gate_id, cfg=cfg, actor="system")
        conn.commit()
    gc = stage_cfg(cfg, gate["stage"])
    rs = gc.get("reviews_status", "DRAFT_ASSIGNED")
    review_statuses = rs if isinstance(rs, list) else [rs]
    cur.execute("""SELECT ga.assignment_kind, ga.assignment_key, ga.resolved_principal_id,
                          coalesce(p.display_name_en, pr.display_name_en, pg.display_name_en, ga.assignment_key)
                            AS display_name_en
                   FROM gate_assignment ga
                   LEFT JOIN principal p ON p.principal_id=ga.assignment_key AND ga.assignment_kind='user'
                   LEFT JOIN principal_role pr ON pr.role_id=ga.assignment_key AND ga.assignment_kind='role'
                   LEFT JOIN principal_group pg ON pg.group_id=ga.assignment_key AND ga.assignment_kind='group'
                   WHERE ga.gate_id=%s
                   ORDER BY ga.assignment_kind, ga.assignment_key, ga.resolved_principal_id NULLS LAST""",
                (gate_id,))
    assignments = cur.fetchall()
    cur.execute(
        """SELECT t.slot_id, sl.day, sl.time_uae, sl.pillar_code, p.code_short AS pillar_short_code,
                  p.name_en AS pillar_name_en, p.name_ar AS pillar_name_ar,
                  sl.hcs_id, h.seq_in_pillar, h.name_en AS hcs_name_en, h.name_ar AS hcs_name_ar,
                  sl.lens, ln.name_en AS lens_name_en, ln.name_ar AS lens_name_ar, sl.format,
                  sl.hook_text, sl.hook_type, sl.topic_angle, sl.status AS slot_status,
                  tp.rationale_ar, tp.rationale_en, tp.revision AS topic_revision,
                  tp.feedback AS topic_feedback,
                  COALESCE(sc.change_summary_ar, tp.change_summary_ar) AS change_summary_ar,
                  COALESCE(sc.change_summary_en, tp.change_summary_en) AS change_summary_en,
                  sc.script_ar, sc.structure AS script_structure, sc.final_line,
                  sc.model AS script_model,
                  sc.delivery_notes, sc.delivery_check, sc.flags, sc.revision AS script_revision,
                  sc.feedback AS script_feedback,
                  sc.needs_scholar_review, sc.needs_native_review
           FROM gate_target t
           JOIN slot sl ON sl.slot_id = t.slot_id
           JOIN pillar p ON p.pillar_code = sl.pillar_code
           JOIN hcs h ON h.hcs_id = sl.hcs_id
           LEFT JOIN lens ln ON ln.lens_id = sl.lens
           LEFT JOIN LATERAL (SELECT * FROM topic p WHERE p.slot_id=t.slot_id
                              ORDER BY p.revision DESC, p.created_at DESC LIMIT 1) tp ON true
           LEFT JOIN LATERAL (SELECT * FROM script s WHERE s.slot_id=t.slot_id
                              ORDER BY s.revision DESC, s.created_at DESC LIMIT 1) sc ON true
           WHERE t.gate_id=%s AND sl.status::text = ANY(%s)
           ORDER BY sl.day, sl.time_uae, t.slot_id""", (gate_id, review_statuses))
    targets = cur.fetchall()
    cur.execute("SELECT slot_id, approver_id, decision, notes, decided_at, revision "
                "FROM gate_decision WHERE gate_id=%s ORDER BY slot_id, decided_at, approver_id", (gate_id,))
    decisions = cur.fetchall()
    by_slot = {}
    for d in decisions:
        by_slot.setdefault(d["slot_id"], []).append(d)
    # M9·B1: the directive THIS gate's stage had to satisfy (review + directives share one
    # language — "does the output meet the incoming directive's acceptance_criteria?").
    stage_name, _ = directives.stage_by_gate(cfg, gate["stage"])
    # #282 — an authoritative gate projects outcome + remaining + per-token coverage from its frozen
    # snapshot; a legacy gate (no snapshot) keeps the count-based read model and is marked legacy.
    snapshot = _load_gate_snapshot(cur, gate_id)
    gate["authoritative"] = snapshot is not None
    gate["legacy"] = snapshot is None
    for t in targets:
        t["decisions"] = by_slot.get(t["slot_id"], [])
        if snapshot is not None:
            proj = _authoritative_target_projection(cur, gate_id, snapshot, t["slot_id"], t["decisions"])
            t["current_outcome"] = proj["current_outcome"]
            t["approval_count"] = proj["approval_count"]
            t["remaining_approvals"] = proj["remaining_approvals"]
            t["remaining_assignments"] = proj["remaining_assignments"]
            t["coverage"] = proj["coverage"]
        else:
            # #321 P1.4 — legacy count read model: count only approvals on the exact current head for an
            # artifact-review gate (reject/request_change stay revision-independent). Decisions preserved.
            # The SAME effective decision set drives BOTH the rollup AND remaining-assignments, so a
            # superseded approval can never show its assignment satisfied while the outcome is pending.
            _lh = _gate_review_head(cur, cfg, gate["stage"], t["slot_id"])
            _eff = _effective_decisions_for_head(t["decisions"], _lh)
            t.update(_decision_rollup(_eff, int(gate["quorum"])))
            t["remaining_assignments"] = (
                _remaining_assignment_snapshots(cur, gate["rule_key"], assignments, _eff)
                if t["current_outcome"] == "pending" else []
            )
            t["coverage"] = None
        # mandatory sign-offs still blocking this slot from publish-ready (for the surfaces)
        t["review_blockers"] = _review_blockers(cur, t["slot_id"], cfg)
        t["directive"] = (directives.latest(cur, t["slot_id"], stage_name)
                          if stage_name else None)
        # manual-stage work product (raw cuts / edits) for the review card preview
        t["assets"] = dam.list_assets(cur, t["slot_id"], stage=stage_name) if stage_name else []
    cur.close()
    gate["targets"] = targets
    gate["assignments"] = assignments
    return gate


def _coverage_gap(targets, rejected_ids):
    """Pillars whose every in-batch item was dropped (a coverage gap to warn about)."""
    by_pillar = {}
    for t in targets:
        by_pillar.setdefault(t["pillar_code"], []).append(t["slot_id"])
    return sorted(p for p, ids in by_pillar.items() if ids and all(i in rejected_ids for i in ids))


def _pending_input_count(cur, round_id, gc):
    """Slots ready to be GENERATED for this stage (its writer-input status), for AI stages only."""
    src = gc.get("generates_from")
    if not src:
        return 0
    cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s AND status=%s", (round_id, src))
    return cur.fetchone()["n"]


def _transition_chain(cfg):
    """The round's linear lifecycle as an ordered list of TRANSITION gate stages (signoff gates
    attest, they don't move slots — excluded). Derived by walking the config's documented chaining
    (each gate's approve_to feeds the next stage's generates_from / reviews_status); no hardcoded
    stage order. Returns [(stage_key, entry_statuses)], where entry_statuses are the statuses a
    slot occupies while IN that stage (writer-input + review statuses)."""
    gates = {k: v for k, v in (cfg.get("gates") or {}).items() if isinstance(v, dict)}
    trans = {k: v for k, v in gates.items() if v.get("kind", "transition") == "transition"}

    def entries(gc):
        rs = gc.get("reviews_status", [])
        rs = rs if isinstance(rs, list) else [rs]
        gf = gc.get("generates_from")
        return ([gf] if gf else []) + rs

    approve_tos = {v.get("approve_to") for v in trans.values()}
    start = next((k for k in trans if not (set(entries(trans[k])) & approve_tos)), None)
    chain, cur_key, seen = [], start, set()
    while cur_key and cur_key not in seen:
        seen.add(cur_key)
        # claim each status for exactly ONE stage (first claim wins) so the funnel partitions
        claimed = {s for _, sts in chain for s in sts}
        chain.append((cur_key, [s for s in entries(trans[cur_key]) if s not in claimed]))
        nxt = trans[cur_key].get("approve_to")
        cur_key = next((k for k in trans if k not in seen and nxt in entries(trans[k])), None)
    return chain


def funnel(conn, round_id, cfg=None):
    """#134 (count contract #131, Slice B) — the run-level lifecycle funnel: how many slots this
    round has carried into and through each transition stage. READ-ONLY and derived entirely from
    existing state (slot.status buckets + the last request_change/reject gate decision for parked
    attribution) — no persisted counters. DISTINCT from stage_state by contract: stage numbers
    describe one stage's population for review work; funnel numbers explain why per-stage totals
    legitimately differ across the run. Conservation (#131 I5) holds by construction:
      entered(s) == in_stage(s) + awaiting(s) + dropped(s) + advanced(s)
      entered(s+1) == advanced(s);  entered(first) == total planned slots (unmapped asserted empty).
    """
    cfg = cfg or load_config()
    chain = _transition_chain(cfg)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT status::text AS status, count(*) AS n FROM slot WHERE round_id=%s "
                "GROUP BY status", (round_id,))
    counts = {r["status"]: r["n"] for r in cur.fetchall()}
    total = sum(counts.values())

    # parked slots (awaiting rework / dropped) attributed to the stage that parked them — the
    # stage of the most recent request_change / reject decision (statuses are shared across stages)
    parked = list(changes_statuses(cfg)) + list(reject_statuses(cfg))
    parked_by_stage = {}
    if parked:
        cur.execute(
            "SELECT s.status::text AS status, "
            "  (SELECT g.stage FROM gate_decision gd JOIN gate g USING (gate_id) "
            "   WHERE gd.slot_id = s.slot_id AND gd.decision IN ('request_change','reject') "
            "   ORDER BY gd.decided_at DESC LIMIT 1) AS stage "
            "FROM slot s WHERE s.round_id=%s AND s.status::text = ANY(%s)", (round_id, parked))
        first_stage = chain[0][0] if chain else None
        stage_keys = {k for k, _ in chain}
        for r in cur.fetchall():
            stage = r["stage"] if r["stage"] in stage_keys else first_stage
            lane = "awaiting" if r["status"] in changes_statuses(cfg) else "dropped"
            by = parked_by_stage.setdefault(stage, {"awaiting": 0, "dropped": 0})
            by[lane] += 1
    cur.close()

    terminal = (cfg.get("gates") or {}).get(chain[-1][0], {}).get("approve_to") if chain else None
    completed = counts.get(terminal, 0) if terminal else 0
    claimed = {terminal} | set(parked) if terminal else set(parked)
    stages = []
    for key, entry_statuses in chain:
        claimed |= set(entry_statuses)
        p = parked_by_stage.get(key, {})
        stages.append({"stage": key,
                       "in_stage": sum(counts.get(s, 0) for s in entry_statuses),
                       "awaiting": p.get("awaiting", 0), "dropped": p.get("dropped", 0)})
    # advanced(s) = everything that made it past s: later stages' populations + completed
    for i, st in enumerate(stages):
        st["advanced"] = completed + sum(x["in_stage"] + x["awaiting"] + x["dropped"]
                                         for x in stages[i + 1:])
        st["entered"] = st["in_stage"] + st["awaiting"] + st["dropped"] + st["advanced"]
    unmapped = {s: n for s, n in counts.items() if s not in claimed}
    return {"round_id": round_id, "total": total, "completed": completed,
            "terminal_status": terminal, "stages": stages, "unmapped": unmapped}


def stage_state(conn, round_id, stage, cfg=None):
    """The lifecycle state of a stage for a round + an AI ADVISORY for the human commit — so the
    surface never errors on a normal condition (nothing pending) and the commit is an informed,
    human-confirmed checkpoint. Possible `state`:
      generate | ready_to_start | reviewing | ready_to_commit | awaiting_regeneration | complete | empty
    `recommendation` + `warnings` are advisory ONLY (agents recommend; the human commits).
    #265: `generate` DOMINATES while generator work remains — no gate is exposed mid-generation."""
    cfg = cfg or load_config()
    gc = stage_cfg(cfg, stage)
    rs = gc.get("reviews_status", "DRAFT_ASSIGNED")
    review_statuses = rs if isinstance(rs, list) else [rs]
    approve_to = gc.get("approve_to")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT status, count(*) AS n FROM slot WHERE round_id=%s GROUP BY status", (round_id,))
    counts = {r["status"]: r["n"] for r in cur.fetchall()}
    cur.close()
    review_pending = sum(counts.get(s, 0) for s in review_statuses)
    awaiting = sum(counts.get(s, 0) for s in changes_statuses(cfg))
    dropped = sum(counts.get(s, 0) for s in reject_statuses(cfg))
    advanced = counts.get(approve_to, 0) if approve_to else 0

    # generation readiness: slots at this stage's writer-input status (AI stages only)
    cur3 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    pending_input = _pending_input_count(cur3, round_id, gc)
    generator = gc.get("generator")
    # #265 — generation DOMINATES this read model: while any planned slot still owes generator
    # work (writer-input rows remaining, or a generation job still in flight), the stage reports
    # generation truthfully and exposes NO active review gate — so no surface (including the
    # job-poll fallback) can offer start_review against a knowably-partial population.
    # #364 — durable, restart-safe: a non-terminal generation_job for this round+stage. Read on the
    # SAME cursor, before it closes, so this adds no cursor and no round trip of its own.
    running_job = (_durable_generation_job(cur3, round_id, stage)
                   if generator == "ai" else None)
    cur3.close()
    generating = generator == "ai" and (pending_input > 0 or running_job is not None)

    # the ACTIVE open review (orphan/duplicate gates are ignored + auto-superseded) — so a stale
    # open gate whose targets already advanced never makes the stage look like it's "reviewing".
    # During generation the lookup is skipped entirely (gates stay untouched and unexposed).
    active_gid = None
    if not generating:
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        active_gid = _active_open_gate(cur2, stage, round_id, review_statuses)
        conn.commit(); cur2.close()
    gate = None
    if active_gid:
        try:
            gate = get_gate(conn, active_gid)
        except GateNotReady:
            # #265 — a generation job can appear between the snapshot above and this read. A held
            # review is neither missing nor an error: re-snapshot and report the truthful
            # generation-dominant advisory (held-gate warning below) instead of letting the hold
            # escape a READ as a failure the API would misclassify.
            conn.rollback()
            curg = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            pending_input = _pending_input_count(curg, round_id, gc)
            running_job = _durable_generation_job(curg, round_id, stage)
            curg.close()
            generating = True
    approval = stage_approval_contract(cfg, stage, conn=conn)
    cur4 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    approval["assignments"] = _enrich_assignment_snapshots(cur4, approval["assignments"])
    cur4.close()
    info = {"round_id": round_id, "stage": stage, "stage_label": stage,
            "gate_id": str(gate["gate_id"]) if gate else None,
            "review_pending": review_pending, "awaiting": awaiting, "dropped": dropped,
            "advanced": advanced, "in_review": 0, "approved": 0, "sent_back": 0,
            "rejected": 0, "pending": 0, "warnings": [], "reconciliation_ok": True,
            "generator": generator, "pending_input": pending_input,
            "approval_rule": approval["rule_key"], "approval_quorum": approval["quorum"],
            "approval_assignments": approval["assignments"]}

    if gate:
        ts = gate["targets"]
        approved = [t for t in ts if t["current_outcome"] == "approved"]
        sent_back = [t for t in ts if t["current_outcome"] == "changes_requested"]
        rejected = [t for t in ts if t["current_outcome"] == "rejected"]
        undecided = [t for t in ts if t["current_outcome"] == "pending"]
        info.update(in_review=len(ts), approved=len(approved), sent_back=len(sent_back),
                    rejected=len(rejected), pending=len(undecided))
        info["state"] = "ready_to_commit" if (ts and not undecided) else "reviewing"
        warnings = []
        if undecided:
            warnings.append(f"{len(undecided)} item(s) still pending — they will be EXCLUDED if you commit now.")
        gap = _coverage_gap(ts, {t["slot_id"] for t in rejected})
        if gap:
            warnings.append(f"Coverage gap: {', '.join(gap)} fully dropped in this batch.")
        if awaiting:
            warnings.append(f"{awaiting} item(s) awaiting regeneration are excluded from this stage.")
        if not approved and not undecided and (sent_back or rejected):
            warnings.append("Nothing will advance — every item was sent back or dropped.")
        # #265 truthful convergence check: for a transition gate the active review population MUST
        # equal the stage's review-pending count once reconciled (get_gate above self-heals). A
        # residual gap is an inconsistent open gate reconciliation could not heal — surface it and
        # force a confirm; never let a partial gate render as a complete review population. (Sign-off
        # gates legitimately target a subset — only slots still needing a fresh sign-off — so exempt.)
        if gc.get("kind", "transition") != "signoff" and not gc.get("requires_flag") \
                and info["in_review"] != review_pending:
            info["reconciliation_ok"] = False
            warnings.insert(0, f"Inconsistent review gate: {review_pending} item(s) at "
                               f"{'/'.join(review_statuses)} but the active gate targets only "
                               f"{info['in_review']} — reconciliation incomplete; not safe to commit.")
        # which warnings should force an extra confirm (risky: committing EARLY / coverage gap / gap)
        info["confirm_warnings"] = [w for w in warnings if "still pending" in w or "Coverage gap" in w
                                    or "Inconsistent review gate" in w]
        info["warnings"] = warnings
        info["recommendation"] = (
            f"Ready to commit: {len(approved)} will advance to the next stage"
            + (f", {len(rejected)} dropped (recoverable)" if rejected else "") + "."
            if info["state"] == "ready_to_commit"
            else f"{len(undecided)} item(s) still to decide ({len(approved)} approved so far).")
        info["next_action"] = info["state"]            # reviewing | ready_to_commit
    else:
        info["confirm_warnings"] = []
        if generating:
            # #265 — generation first (also fixes the old script-stage "complete-when-empty" quirk):
            # even with review-eligible rows already written, review does not open until every
            # planned slot has terminally generated. Counts stay truthful on both sides.
            info["state"] = info["next_action"] = "generate"
            rec = (f"Generation in progress — {pending_input} item(s) remaining." if running_job
                   else f"{pending_input} item(s) ready to generate.")
            if review_pending:
                rec += (f" {review_pending} generated item(s) await review — review opens when "
                        f"generation completes.")
            info["recommendation"] = rec
            curh = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            curh.execute("""SELECT count(*) AS n FROM gate g WHERE g.status='open' AND g.stage=%s
                            AND EXISTS (SELECT 1 FROM gate_target t JOIN slot sl ON sl.slot_id=t.slot_id
                                        WHERE t.gate_id=g.gate_id AND sl.round_id=%s)""",
                         (stage, round_id))
            held = curh.fetchone()["n"]
            curh.close()
            if held:
                info["reconciliation_ok"] = False
                info["warnings"] = ["An open review gate is held until generation completes — it "
                                    "will be reconciled to the complete population before review "
                                    "resumes."]
        elif review_pending > 0:
            info["state"], info["next_action"] = "ready_to_start", "start_review"
            info["recommendation"] = f"{review_pending} item(s) ready to review."
        elif awaiting > 0:
            info["state"] = info["next_action"] = "awaiting_regeneration"
            info["recommendation"] = f"{awaiting} item(s) awaiting regeneration — regenerate to continue."
        elif advanced > 0:
            # complete ONLY when something actually advanced here — not on inherited 'dropped' alone.
            info["state"] = info["next_action"] = "complete"
            info["recommendation"] = (f"Review complete — {advanced} advanced"
                                      + (f", {dropped} dropped (recoverable)" if dropped else "") + ".")
        else:
            info["state"] = info["next_action"] = "empty"
            info["recommendation"] = "Nothing at this stage yet."
    return info


# --------------------------------------------------------------------------- #
# Decide
# --------------------------------------------------------------------------- #
def decide(conn, gate_id, approver_id, decision, slot_ids=None, notes=None, revision=None, cfg=None,
           expected_revision=None, eligibility_check=False, _commit=True):
    """Record `decision` by `approver_id` over slot_ids (None/empty = every still-target
    slot = a batch action). For 'approve', `revision` records WHICH artifact revision is approved
    (None = the head/latest) — so you can approve v2 even if v3 exists. Validates the gate is open,
    the approver is configured for the stage, and partial-batch is permitted. Audits each slot.

    #313 P1-A — `expected_revision` (approve CAS) and `eligibility_check` (drop) are enforced UNDER a
    slot FOR UPDATE lock IN THIS decision transaction, so the check and the recorded decision are
    ATOMIC (no TOCTOU with a concurrent edit/rework or approval/downstream advance)."""
    if decision not in DECISIONS:
        raise GateError(f"bad decision {decision!r} (expected one of {DECISIONS})")
    if decision == "request_change" and not (notes or "").strip():
        raise GateError("request_change needs a comment — tell the agent what to change "
                        "(this feedback is injected into the regeneration)")
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM gate WHERE gate_id=%s", (gate_id,))
    gate = cur.fetchone()
    if not gate:
        raise GateError(f"no such gate {gate_id}")
    if gate["status"] != "open":
        raise GateError(f"gate {gate_id} is {gate['status']} — not open")
    # #313 P1-A — enforce the per-item CAS / eligibility UNDER a slot lock, in THIS transaction, BEFORE
    # recording the decision. decide() commits exactly once at the end and its helpers never commit, so
    # the lock is held from here through that terminal commit — the check and the recorded decision are
    # atomic. A concurrent edit/rework (which locks+updates the slot row) or approval-commit/downstream
    # (which updates slot status / inserts a script) serializes against this lock, so no stale-head
    # approval and no post-approval/downstream reject decision can be persisted.
    gc = stage_cfg(cfg, gate["stage"])
    # #367 R3.1 — the per-item CAS / eligibility must validate against the artifact THIS gate governs,
    # not a topic literal. `rework_mode` is that artifact (topic|script); a non-artifact gate (signoff/
    # schedule_review) has no head to CAS against, so `_cas_artifact` is None and the block is inert for
    # it exactly as before. This closes a cross-artifact defect: a script approve-with-CAS or drop
    # previously checked the TOPIC head/eligibility.
    _cas_artifact = gc.get("rework_mode")
    if expected_revision is not None or eligibility_check:
        for _sid in (slot_ids or []):
            cur.execute("SELECT 1 FROM slot WHERE slot_id=%s FOR UPDATE", (_sid,))
        if expected_revision is not None:
            _sid = (slot_ids or [None])[0]
            _head = _head_revision(cur, _sid, _cas_artifact or "topic")
            if int(expected_revision) != int(_head):
                raise RevisionConflict(
                    f"stale expected_revision {expected_revision} for {_sid} (current head {_head})",
                    current=_head)
        if eligibility_check:
            for _sid in (slot_ids or []):
                _topic_item_mutation_eligibility(cur, _sid, _cas_artifact or "topic")
    if decision == "request_change" and not gc.get("rework_mode"):
        raise GateError(f"request_change is not supported for {gate['stage']} — approve or drop the item instead")
    approvers = _gate_assignment_tokens(cur, gate_id) or [
        _token_from_assignment(a["assignment_kind"], a["assignment_key"])
        for a in stage_approval_contract(cfg, gate["stage"], conn=conn)["assignments"]
    ]
    # #282 (D3) — authorize the actor against the gate's FROZEN eligibility for an authoritative gate,
    # so an actor eligible when the gate opened stays authorized after a later role/group removal or
    # deactivation (and one added AFTER open is not). Legacy gates (no snapshot) keep live-membership
    # authorization unchanged.
    snapshot = _load_gate_snapshot(cur, gate_id)
    if snapshot is not None:
        eligible = set().union(*(t["eligible"] for t in snapshot["tokens"])) if snapshot["tokens"] else set()
        authorized = (not snapshot["tokens"]) or (approver_id in eligible)
    else:
        authorized = (not approvers) or any(_principal_matches_assignment(cur, approver_id, a) for a in approvers)
    if not authorized:
        # `allowed` stays the configured tokens (stable requirement); `allowed_principals` records the
        # FROZEN eligible set for an authoritative gate (who could actually act, per D3).
        audit_denied(conn, "gate", gate_id, "gate_decision_denied", approver_id,
                     {"stage": gate["stage"], "decision": decision, "reason": "not_assigned",
                      "allowed": approvers, "authoritative": snapshot is not None,
                      "allowed_principals": sorted(eligible) if snapshot is not None else None,
                      "slot_ids": sorted(slot_ids or [])})
        raise GateError(f"approver {approver_id!r} not configured for {gate['stage']} "
                        f"(allowed: {approvers})")
    # M9·B3 hard floor: a non-human can never decide a hard-floor gate (publish / scholar /
    # content sign-off), regardless of autonomy or being configured as an approver.
    if actors.enabled(cfg):
        ok, why = actors.authorize_gate_decision(cfg, actors.load_principal(cur, approver_id),
                                                 gate["stage"])
        if not ok:
            audit_denied(conn, "gate", gate_id, "gate_decision_denied", approver_id,
                         {"stage": gate["stage"], "decision": decision, "reason": "hard_floor",
                          "why": why})
            raise GateError(why)
    # #265 — reconcile before accepting a decision so a late-eligible slot is a real target and a
    # batch decision (slot_ids=None) acts on the COMPLETE population. Append-only; prior decisions
    # are never altered (a newly-added target is simply undecided and loops back on resolve).
    # While generator work remains, decisions fail closed (GateNotReady): never decide against a
    # knowably-partial target set.
    _guard_generation_complete(cur, cfg, gate_id, gate["stage"], gate["status"])
    reconcile_gate_targets(cur, gate_id, cfg=cfg, actor="system")
    cur.execute("SELECT slot_id FROM gate_target WHERE gate_id=%s", (gate_id,))
    all_targets = {r["slot_id"] for r in cur.fetchall()}
    chosen = set(slot_ids) if slot_ids else set(all_targets)
    unknown = chosen - all_targets
    if unknown:
        raise GateError(f"slots not in this gate: {sorted(unknown)}")
    if slot_ids and set(slot_ids) != all_targets and not gc.get("allow_partial_batch", True):
        raise GateError(f"partial-batch not allowed for {gate['stage']}")

    # Integrity guard: never approve a PARKED slot — one awaiting rework (change requested) OR
    # dropped (rejected). Both must be recovered first (regenerate / reopen). Prevents the old
    # "approved despite a change request" silent override, even via a stale gate.
    if decision == "approve":
        cs = parked_statuses(cfg)
        if cs:
            cur.execute("SELECT slot_id FROM slot WHERE slot_id = ANY(%s) AND status::text = ANY(%s)",
                        (sorted(chosen), list(cs)))
            blocked = [r["slot_id"] for r in cur.fetchall()]
            if blocked:
                raise GateError(f"cannot approve {blocked} — parked (awaiting rework or dropped). "
                                f"Regenerate or restore (reopen) it first, then re-review.")

    # #282 — an authoritative gate recomputes per-token coverage in THIS transaction after each
    # decision; a legacy gate (snapshot=None, loaded above for authorization) keeps the count path.
    for s in sorted(chosen):
        cur.execute(
            """INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision, notes, revision)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (gate_id, approver_id, slot_id)
               DO UPDATE SET decision=EXCLUDED.decision, notes=EXCLUDED.notes,
                             revision=EXCLUDED.revision, decided_at=now()""",
            (gate_id, s, approver_id, decision, notes, revision if decision == "approve" else None))
        _audit(cur, "slot", s, "gate_decision", approver_id,
               {"gate_id": str(gate_id), "decision": decision, "notes": notes, "revision": revision})
        if snapshot is not None:
            # #321 P1.4 — persist coverage for the EXACT current head so the coverage_recomputed audit
            # and every read model that projects from gate_token_coverage report current-head coverage,
            # never a superseded-revision approval (kept revision-independent for reject/request_change).
            _dh = _gate_review_head(cur, cfg, gate["stage"], s)
            match = _recompute_slot_coverage(cur, gate_id, s, snapshot, head_revision=_dh)
            covered = set(match)
            # #282 P1.3 — the audit outcome is derived from the FULL persisted decision set for the
            # slot (reject > request_change > coverage), NOT just this decision: a prior reject/
            # request_change followed by an approve must not emit 'approved'. Append-only projection
            # from the SAME snapshot/coverage transaction — never a separate authorization reconstruction.
            cur.execute("SELECT decision FROM gate_decision WHERE gate_id=%s AND slot_id=%s", (gate_id, s))
            all_dec = cur.fetchall()
            _audit(cur, "slot", s, "coverage_recomputed", approver_id,
                   {"gate_id": str(gate_id), "snapshot_id": str(snapshot["snapshot_id"]),
                    "rule_key": snapshot["rule_key"], "required_tokens": len(snapshot["tokens"]),
                    "covered_tokens": len(covered),
                    "covered": [{"token": str(tid), "principal": pid} for tid, pid in match.items()],
                    "outcome": _authoritative_outcome(snapshot, all_dec, covered)})
    # #314 — `_commit=False` lets the bulk driver commit decide's effect ATOMICALLY with the per-item
    # ledger outcome in ONE transaction (parity with restore_revision(_commit=False)); the authority/CAS/
    # eligibility guards above still run under the slot lock and rollback cleanly on any denial.
    if _commit:
        conn.commit()
    cur.close()
    return sorted(chosen)


# --------------------------------------------------------------------------- #
# Resolve
# --------------------------------------------------------------------------- #
def _slot_outcome(decisions, quorum_n):
    """Per-slot tally with precedence reject > request_change > approve."""
    kinds = {}
    for d in decisions:
        kinds.setdefault(d["decision"], set()).add(d["approver_id"])
    if kinds.get("reject"):
        return "rejected"
    if kinds.get("request_change"):
        return "changes_requested"
    if len(kinds.get("approve", set())) >= quorum_n:
        return "approved"
    return "pending"


def resolve(conn, gate_id, actor="system", cfg=None, slot_ids=None):
    """Apply the quorum to every target slot, move the approved ones to the stage's
    `approve_to` status (config), loop the rest back (kept at the review status), set the
    gate status, and audit each transition. Returns {slot_id: outcome}."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM gate WHERE gate_id=%s", (gate_id,))
    gate = cur.fetchone()
    if not gate:
        raise GateError(f"no such gate {gate_id}")
    quorum_n = int(gate["quorum"])
    gc = stage_cfg(cfg, gate["stage"])
    rs = gc.get("reviews_status", "DRAFT_ASSIGNED")     # may be a list for re-escalatable sign-off gates
    review_statuses = rs if isinstance(rs, list) else [rs]
    from_status = rs[0] if isinstance(rs, list) else rs  # only used by transition gates (single status)
    to_status = gc.get("approve_to", "APPROVED_ASSIGNED")
    # #265 — reconcile before committing so the batch acts on the COMPLETE eligible population; a
    # late-eligible slot that is still undecided is loopback-kept at the review status, never
    # silently excluded from the commit (no-op when the gate is already resolved). While generator
    # work remains, the commit fails closed (GateNotReady): a partial batch that silently excludes
    # still-generating slots must never advance.
    _guard_generation_complete(cur, cfg, gate_id, gate["stage"], gate["status"])
    reconcile_gate_targets(cur, gate_id, cfg=cfg, actor=actor)
    cur.execute("SELECT slot_id FROM gate_target WHERE gate_id=%s ORDER BY slot_id", (gate_id,))
    targets = [r["slot_id"] for r in cur.fetchall()]
    chosen = targets if not slot_ids else [slot_id for slot_id in targets if slot_id in set(slot_ids)]
    unknown = set(slot_ids or []) - set(targets)
    if unknown:
        raise GateError(f"slots not in this gate: {sorted(unknown)}")
    cur.execute("SELECT slot_id, approver_id, decision, revision FROM gate_decision WHERE gate_id=%s",
                (gate_id,))
    dec_by_slot = {}
    for d in cur.fetchall():
        dec_by_slot.setdefault(d["slot_id"], []).append(d)
    artifact = gc.get("rework_mode")                  # the artifact this gate approves (topic|script)
    kind = gc.get("kind", "transition")               # transition (moves status) | signoff (attests)
    enforce = bool(gc.get("enforce_mandatory_reviews", False))
    # idempotency: which slots already have signoff/loopback/blocked/stale audits on THIS gate
    cur.execute("SELECT entity_id, action FROM audit_log WHERE entity='slot' "
                "AND action IN ('signoff_recorded','looped_back','blocked_on_review',"
                "'resolve_stale_revision') "
                "AND detail->>'gate_id' = %s", (str(gate_id),))
    seen = {}
    for r in cur.fetchall():
        seen.setdefault(r["action"], set()).add(r["entity_id"])

    # #282 — an authoritative gate resolves each slot from per-token coverage (recomputed here so the
    # commit reflects the current maximum matching); a legacy gate keeps the count-based tally.
    snapshot = _load_gate_snapshot(cur, gate_id)
    outcomes = {}
    for s in chosen:
        # #321 R3/R5 — lock the slot for the ENTIRE per-slot resolution, held through resolve's single
        # terminal commit, so the head/decision read and the transition are atomic against a concurrent
        # edit/rework that advances the head.
        cur.execute("SELECT 1 FROM slot WHERE slot_id=%s FOR UPDATE", (s,))
        # #321 P1.2 — approval quorum/coverage is computed ONLY from approvals on the EXACT current head
        # revision (read under this lock); mixed-revision approvals cannot combine. Approvals for a
        # superseded revision are PRESERVED but do not count toward advancing the current head. reject /
        # request_change precedence is revision-independent. A gate with no artifact (e.g. signoff /
        # schedule_review, no rework_mode) has no head to pin, so it keeps the revision-independent tally.
        _decs = dec_by_slot.get(s, [])
        _cur_head = _head_revision(cur, s, artifact) if artifact else None
        _kinds = {d["decision"] for d in _decs}
        if "reject" in _kinds:
            base = "rejected"
        elif "request_change" in _kinds:
            base = "changes_requested"
        else:
            if _cur_head is not None:
                # V2 approvals always carry an exact revision; NULL (legacy/low-level) means "the head",
                # so it matches the current head. Distinct-revision V2 approvals never merge.
                _head_apprs = sorted({d["approver_id"] for d in _decs if d["decision"] == "approve"
                                      and (d["revision"] is None or int(d["revision"]) == int(_cur_head))})
            else:
                _head_apprs = sorted({d["approver_id"] for d in _decs if d["decision"] == "approve"})
            # a SUPERSEDED approval = an exact-revision approve for a revision that is no longer head
            # (the head advanced past what that principal reviewed).
            _superseded = any(d["decision"] == "approve" and d["revision"] is not None
                              and _cur_head is not None and int(d["revision"]) != int(_cur_head)
                              for d in _decs)
            if snapshot is not None:
                # #321 P1.4 — persist coverage for the exact current head (read-model truth)
                _recompute_slot_coverage(cur, gate_id, s, snapshot, head_revision=_cur_head)
                _covered = _match_tokens(snapshot["tokens"], _head_apprs)   # advancement = head-only match
                _nt = len(snapshot["tokens"])
                _met = (_nt > 0 and len(_covered) >= _nt) if snapshot["rule_key"] == "all" \
                    else (len(_covered) >= 1)
            else:
                _met = len(_head_apprs) >= quorum_n
            if _met:
                base = "approved"
            elif _superseded:
                # at least one recorded approval is for a revision the head has advanced past — that
                # principal must re-review the current head. Fail typed-stale deterministically; a mere
                # not-yet-quorum on the CURRENT head (no superseded approvals) stays 'pending' below.
                base = "stale_revision"
            else:
                base = "pending"
        if base == "stale_revision":
            outcomes[s] = "stale_revision"
            if s not in seen.get("resolve_stale_revision", set()):
                _audit(cur, "slot", s, "resolve_stale_revision", actor,
                       {"current_head": _cur_head, "gate_id": str(gate_id), "stage": gate["stage"],
                        "approved_revisions": sorted({d["revision"] for d in _decs
                                                      if d["decision"] == "approve"
                                                      and d["revision"] is not None}),
                        "note": "quorum not met on the current head — approval(s) preserved for a "
                                "superseded revision; item remains in review"})
            continue
        if base == "approved" and kind == "signoff":
            # record the sign-off; do NOT change the slot's main status
            outcomes[s] = "signed_off"
            if s not in seen.get("signoff_recorded", set()):
                _audit(cur, "slot", s, "signoff_recorded", actor,
                       {"stage": gate["stage"], "gate_id": str(gate_id)})
        elif base == "approved":
            # #321 R5/P1.2 — base is now revision-aware: reaching here means quorum/coverage IS met by
            # approvals on the EXACT current head. So the pin below binds the current head, and the later
            # head can never be represented as approved without its own quorum.
            if enforce:
                missing = _review_blockers(cur, s, cfg)
                if missing:                   # can't reach publish-ready — held until sign-offs done
                    outcomes[s] = "blocked_on_review"
                    if s not in seen.get("blocked_on_review", set()):
                        _audit(cur, "slot", s, "blocked_on_review", actor,
                               {"missing": missing, "gate_id": str(gate_id)})
                    continue
            cur.execute("UPDATE slot SET status=%s, updated_at=now() "
                        "WHERE slot_id=%s AND status=%s", (to_status, s, from_status))
            outcomes[s] = "approved"
            if cur.rowcount:                  # only audit a real transition (idempotent re-resolve)
                _audit(cur, "slot", s, "status_change", actor,
                       {"from": from_status, "to": to_status, "gate_id": str(gate_id)})
                # #321 P1.2 — pin the CURRENT HEAD (the revision the quorum actually reviewed); base
                # reached "approved" only because quorum is met on that exact head. The downstream
                # directive therefore carries the reviewed head, never a superseded revision.
                if artifact:
                    approver = next((d["approver_id"] for d in dec_by_slot.get(s, [])
                                     if d["decision"] == "approve"
                                     and (d["revision"] is None
                                          or int(d["revision"]) == int(_cur_head))), actor)
                    _record_approval(cur, s, artifact, _cur_head or _head_revision(cur, s, artifact),
                                     approver)
                # #255 S1 — atomically pin the EXACT approved MASTER edit when the edit-stage gate
                # approves. Master = the existing DAM tuple (stage='media_edit', kind='edit',
                # platform_variant IS NULL, status='active'); the trigger stage is derived from the
                # gate's config-mapped pipeline stage, never assumed. Exactly ONE active master must
                # exist — zero or multiple FAIL CLOSED (GateError → this whole resolve transaction
                # rolls back: no slot transition, no gate resolution, no partial pin, no cleanup).
                # FOR UPDATE serializes against a concurrent add_asset supersession, so a pin can
                # never diverge from the row it was resolved on. The slot_approval pointer stays the
                # governed CURRENT-STATE pin (cleared only by the existing reopen path); the
                # append-only audit event below is the immutable exact-pin history.
                s1_media_edit = directives.stage_by_gate(cfg, gate["stage"])[0] == "media_edit"
                if s1_media_edit:
                    cur.execute(
                        """SELECT asset_id, version FROM asset
                            WHERE slot_id=%s AND stage='media_edit' AND kind='edit'
                              AND platform_variant IS NULL AND status='active'
                            FOR UPDATE""", (s,))
                    masters = cur.fetchall()
                    if len(masters) != 1:
                        raise GateError(
                            f"approved-master-edit pin failed for {s}: expected exactly one active "
                            f"master edit candidate (stage='media_edit', kind='edit', no platform "
                            f"variant), found {len(masters)} — failing closed, nothing committed")
                    pin_approver = next((d["approver_id"] for d in dec_by_slot.get(s, [])
                                         if d["decision"] == "approve"), actor)
                    _record_approval(cur, s, "edit", masters[0]["version"], pin_approver)
                    _audit(cur, "slot", s, "approved_edit_master_pinned", pin_approver,
                           {"asset_id": str(masters[0]["asset_id"]),
                            "revision": masters[0]["version"],
                            "master": {"stage": "media_edit", "kind": "edit",
                                       "platform_variant": None, "status": "active"},
                            "gate_id": str(gate_id), "gate_stage": gate["stage"]})
                # the approved artifact becomes the next stage's input directive (the handoff).
                # #255 S1: the media-edit handoff is part of the required atomic contract —
                # STRICT emission (a failure rolls back the whole resolution). Legacy stages
                # keep the best-effort seam behavior.
                _emit_directive_on_transition(cur, s, gate["stage"], cfg, actor,
                                              strict=s1_media_edit)
        else:
            outcomes[s] = base
            # request_change -> CHANGES_REQUESTED (awaiting rework); reject -> REJECTED (reversible
            # 'dropped'). Both are DEDICATED states: excluded from any new review + not approvable,
            # and RECOVERABLE (regenerate / reopen) — nothing is destroyed (config changes_to / reject_to).
            target = (gc.get("changes_to") if base == "changes_requested"
                      else gc.get("reject_to") if base == "rejected" else None)
            if target:
                cur.execute("UPDATE slot SET status=%s, updated_at=now() WHERE slot_id=%s AND status=%s",
                            (target, s, from_status))
            if base in ("rejected", "changes_requested") and s not in seen.get("looped_back", set()):
                _audit(cur, "slot", s, "looped_back", actor,
                       {"outcome": base, "stage": gate["stage"], "rework_mode": gc.get("rework_mode"),
                        "to": target, "gate_id": str(gate_id)})

    # gate status: keep it open while any targets remain at the gate's review status, otherwise
    # derive a terminal state from the resolved slot statuses.
    cur.execute("SELECT count(*) AS n FROM slot WHERE slot_id = ANY(%s) AND status::text = ANY(%s)",
                (targets, review_statuses))
    active_remaining = cur.fetchone()["n"]
    if active_remaining > 0:
        gstatus = "open"
    else:
        vals = set(outcomes.values())
        if vals <= {"approved", "signed_off"}:
            gstatus = "approved"
        elif "rejected" in vals:
            gstatus = "rejected"
        else:
            gstatus = "changes_requested"
    cur.execute("UPDATE gate SET status=%s WHERE gate_id=%s", (gstatus, gate_id))
    _audit(cur, "gate", gate_id, "gate_resolved", actor,
           {"status": gstatus, "outcomes": outcomes})

    # #310 Stage 2A — automatic entry: when the SCHEDULE_REVIEW gate accepts (advances slots to
    # SCHEDULE_APPROVED), enqueue exactly one idempotent Topic-generation job IN THIS SAME
    # transaction. It reuses the existing governed acceptance checkpoint (no new trigger, no weakened
    # authority) and is idempotent, so replay/reread/retry never double-fire. A legacy run whose
    # policy cannot resolve fails closed here rather than committing an acceptance with no job. This
    # only fires for the schedule stage; every other gate resolution is unchanged.
    if gate["stage"] == "schedule_review" and any(v in ("approved", "signed_off") for v in outcomes.values()):
        # FALLBACK INTEGRITY: Stage 2A is opt-in by the PRESENCE of an active topic-generation policy.
        # If none is provisioned the feature is dormant and Schedule acceptance proceeds exactly as
        # Stage 1 — the enqueue is skipped, never fail-closing the acceptance. This is also the
        # rollback model: deactivate/remove the policy generation and acceptance reverts to pure
        # Stage 1 with the tables left dormant. Only when Stage 2A IS provisioned does the enqueue run
        # (and a genuine policy/token failure there is a real Stage 2A defect, not a Schedule one).
        # BASELINE (create-only, in this same transaction): a fresh governed deployment has no policy
        # yet, so seed the baseline generation ACTIVE here — this delivers the approved default (Stage
        # 2A on) rather than a silently-dormant feature. It is create-only: if the operator already
        # owns a lineage — including an explicit DISABLE — this is a no-op and the active check below
        # finds nothing, so NO Stage 2A job is minted: Stage 2A is not provisioned for this round and
        # topic generation has no canonical command (the generate endpoint fails closed, #312).
        _rid = None
        for _s in targets:
            cur.execute("SELECT round_id FROM slot WHERE slot_id=%s", (_s,))
            _r = cur.fetchone()
            if _r:
                _rid = _r["round_id"]; break
        if _rid:
            # Everything below is SCOPE-LOCAL to this round's (tenant, module): the baseline seed, the
            # active-policy fallback check, and the pinned enqueue. One scope's policy never suppresses
            # or conflicts with another's, and an explicit disable is scope-local.
            _tenant, _module = _round_scope(cur, _rid)
            _bootstrap_topic_generation_policy_tx(cur, _tenant, _module, actor)
            # Resolve the active generation to read its GOVERNED, IMMUTABLE entry_mode. Absent active
            # policy => Stage 2A is NOT PROVISIONED for this round (no job minted; topic generation has
            # no canonical command — the generate endpoint fails closed) — distinct from 'manual'. The
            # entry_mode (a versioned product-policy choice, NOT a surface branch) selects only the
            # TRIGGER TIMING of the SAME durable Stage 2A job:
            #   automatic -> enqueue 'queued' + (post-commit) dispatch;
            #   manual    -> a V2-governed authorized trigger-timing choice: enqueue the SAME durable
            #                job in 'awaiting_trigger'; an authorized V2 Generate trigger later activates
            #                THIS job into the same canonical runner (identical pins/provenance). The
            #                resolved mode is pinned deterministically in an append-only audit so history
            #                is unambiguous.
            # No silent fallback: an unrecognized entry_mode fails closed.
            cur.execute("""SELECT policy_id, entry_mode FROM topic_generation_policy
                            WHERE status='active' AND tenant_id=%s AND module=%s LIMIT 1""",
                        (_tenant, _module))
            _pol = cur.fetchone()
            if _pol:
                _mode = _pol["entry_mode"]
                if _mode not in ("automatic", "manual"):
                    raise GateError(f"unrecognized topic-generation entry_mode {_mode!r} for scope "
                                    f"({_tenant}/{_module}) — Stage 2A fails closed, no silent fallback")
                _tok = schedule_token(cur, _rid)
                if _tok:                                 # legacy (token 0) has no governed mapping to pin
                    # AUTHORITY snapshot from THIS exact gate + its approving decisions (separate from
                    # the resolver/execution actor). Frozen on the job so history is immutable.
                    _auth = _schedule_authority_snapshot(cur, gate_id, _tok, actor)
                    # AUTOMATIC and MANUAL persist the SAME canonical Stage 2A job with an identical
                    # immutable snapshot (pinned policy + repetition values + authority + writer +
                    # entry_mode). They differ ONLY in TRIGGER TIMING via the initial status:
                    #   automatic     -> 'queued'          => the post-commit dispatch runs it now;
                    #   manual        -> 'awaiting_trigger' => NON-DRAINABLE (excluded from the recovery
                    #                    drainer + auto-dispatch); an authorized V2 Generate trigger
                    #                    later activates THIS same job into the same runner.
                    _init = "queued" if _mode == "automatic" else "awaiting_trigger"
                    _enqueue_topic_generation_tx(cur, _rid, _tok, actor,
                                                 authority_snapshot=_auth, initial_status=_init)

    # #359 Stage 3B — AUTOMATIC entry: when the TOPIC_REVIEW gate accepts, create or converge on the
    # canonical Script attempt IN THIS SAME TRANSACTION. It reuses the existing governed acceptance
    # checkpoint — no new trigger, no new scheduler, no weakened authority — and runs through the one
    # shared body, so automatic and manual cannot diverge in manifest, digest, or job identity.
    #
    # Everything the manifest needs is already written above, uncommitted, in this transaction: the
    # slots are at TOPIC_APPROVED, their approved revisions are pinned, and the gate reads 'approved'.
    #
    # The writer is NOT run here (ruling 5). This only mints durable intent; execution happens after
    # commit through the already-merged Script drain, so correctness never depends on dispatch.
    if gate["stage"] == "topic_review" and any(v in ("approved", "signed_off")
                                               for v in outcomes.values()):
        _srid = None
        for _s in targets:
            cur.execute("SELECT round_id FROM slot WHERE slot_id=%s", (_s,))
            _r = cur.fetchone()
            if _r:
                _srid = _r["round_id"]; break
        if _srid:
            # ScriptAuthorityUnavailable deliberately propagates: it must abort this whole
            # acceptance (Amendment I / ruling 2), and the commit below is never reached. Every
            # other no-start outcome is typed, fabricates nothing, and leaves the acceptance intact
            # (ruling 3).
            _sres = _script_attempt_tx(cur, _srid, cfg, principal=None,
                                       trigger_source="topic_acceptance",
                                       initiating_actor=SCRIPT_AUTOMATIC_ACTOR,
                                       require_principal=False)
            if _sres["outcome"] == "no_start":
                # Append-only evidence that the trigger ran and declined, with the existing typed
                # reason — so "no job" is never indistinguishable from "never evaluated".
                _audit(cur, "round", str(_srid), "script_generation_automatic_start_skipped",
                       SCRIPT_AUTOMATIC_ACTOR,
                       {"reason": _sres["code"], "source_gate_id": str(gate_id)})

    conn.commit()
    cur.close()
    return outcomes


# ===========================================================================
# #314 — BULK TOPIC DISPOSITION (per-item-commit model)
#
# A bulk disposition over N slots in the CLOSED action set {bulk_approve, bulk_request_change,
# bulk_drop}. Each item maps to the EXISTING canonical `decide(approve|request_change|reject)` command
# over exactly its slot, committed INDEPENDENTLY; the bulk_operation_item ledger row is the idempotency +
# recovery + truthful-partial-outcome unit. `decide` is idempotent (gate_decision upsert) and head-STABLE
# (it never mints a topic revision), so re-driving an unsettled item on recovery NEVER duplicates a
# completed disposition nor misreports an unattempted one. Items are driven in ascending-slot_id order (a
# single global lock order -> two batches over overlapping slots can never deadlock). Authority, exact
# revision/CAS, eligibility, fencing, and typed denials are ALL the existing `decide` guarantees — this
# adds NO new authority or semantics, only the durable per-item ledger + its append-only lifecycle audit.
# ===========================================================================

_BULK_ACTION_DECISION = {"bulk_approve": "approve",
                         "bulk_request_change": "request_change",
                         "bulk_drop": "reject"}

_BULK_LEASE_SECONDS = int(os.environ.get("TANAGHOM_BULK_LEASE_SECONDS", "120"))


def _bulk_request_digest(round_id, gate_id, action, actor, comment, ordered_items, tenant_id):
    """Canonical SHA-256 over the IMMUTABLE request. A replay's key must carry the SAME digest, else the
    request changed and the replay is a typed conflict (never a silent wrong-op dedupe)."""
    import hashlib
    import json
    payload = {"tenant_id": tenant_id, "round_id": round_id, "gate_id": str(gate_id), "action": action,
               "actor": actor, "comment": comment or "",
               "items": [{"slot_id": it["slot_id"], "expected_revision": it.get("expected_revision")}
                         for it in ordered_items]}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _authorize_gate_approver(cur, gate_id, actor, cfg):
    """#314 — the CANONICAL gate-approval authority: the actor must be an assigned approver of the gate,
    resolved parity with `decide` (the FROZEN eligibility snapshot if present, else the configured stage
    approval contract). Fail-closed + typed. Reused by bulk CREATION (before any write) and bulk READ, so
    an unauthorized principal is refused BEFORE any durable ledger/audit row exists."""
    snapshot = _load_gate_snapshot(cur, gate_id)
    if snapshot is not None:
        eligible = (set().union(*(t["eligible"] for t in snapshot["tokens"])) if snapshot["tokens"]
                    else set())
        ok = bool(snapshot["tokens"]) and actor in eligible
    else:
        cur.execute("SELECT stage FROM gate WHERE gate_id=%s", (gate_id,))
        stage = (cur.fetchone() or {}).get("stage")
        tokens = _gate_assignment_tokens(cur, gate_id) or (
            [_token_from_assignment(a["assignment_kind"], a["assignment_key"])
             for a in stage_approval_contract(cfg, stage, conn=cur.connection)["assignments"]] if stage else [])
        ok = bool(tokens) and any(_principal_matches_assignment(cur, actor, tok) for tok in tokens)
    if not ok:
        raise GovernedDenial(f"{actor!r} is not an authorized approver for gate {gate_id} "
                             f"(gate approval boundary)", reason="not_authorized")


def _authorize_bulk_read(conn, batch_id, actor, cfg=None):
    """#314 (Codex read-boundary) — a bulk operation's actor/comments/slots/outcomes are governed data:
    only a principal authorized for the batch's gate (the canonical approval boundary) may read it."""
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT gate_id FROM bulk_operation WHERE batch_id=%s", (batch_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); raise GateError(f"no such bulk operation {batch_id}")
    try:
        _authorize_gate_approver(cur, row["gate_id"], actor, cfg)
    finally:
        cur.close()


def begin_bulk_operation(conn, round_id, gate_id, action, slot_items, actor, idempotency_key,
                         comment=None, cfg=None):
    # gate_id may be None — resolve the round's OPEN topic_review gate server-side (the client need not
    # know gate internals; parity with the per-slot governed actions which resolve the gate themselves).
    """#314 — atomically OWN a bulk disposition + its per-item ledger, fail-closed on membership, bound to
    a canonical request digest. Idempotency identity is (round_id, idempotency_key), but the stored
    request_digest is compared on every replay: a replay of the SAME key with a DIFFERENT immutable
    request (gate/action/actor/comment/ordered items/expected revisions) raises a typed GovernedDenial
    (reason='idempotency_key_mismatch') — never silently returns/executes the wrong operation. A matching
    replay resolves to the SAME batch (start|resume|dedupe). `slot_items`=[{slot_id, expected_revision?}]."""
    if action not in _BULK_ACTION_DECISION:
        raise GateError(f"bad bulk action {action!r} (expected one of {sorted(_BULK_ACTION_DECISION)})")
    if action == "bulk_request_change" and not (comment or "").strip():
        raise GateError("bulk_request_change needs a shared comment — tell the agent what to change")
    if not slot_items:
        raise GateError("a bulk operation needs at least one slot")
    # #314 exact-current-head discipline — every item MUST pin a positive expected_revision (no NULL=head).
    for it in slot_items:
        ev = it.get("expected_revision")
        if not isinstance(ev, int) or isinstance(ev, bool) or ev < 1:
            raise GateError(f"each bulk item needs a positive integer expected_revision "
                            f"(exact-current-head discipline); slot {it.get('slot_id')!r} has {ev!r}")
    cfg = cfg or load_config()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # membership fail-closed: the gate must be OPEN, belong to the ROUND, and every item slot must be a
    # TARGET of that gate (∩ the round's slots). No foreign/unknown slot or cross-round gate.
    if gate_id is None:
        cur.execute("""SELECT g.gate_id FROM gate g
                         JOIN gate_target t ON t.gate_id = g.gate_id
                         JOIN slot s ON s.slot_id = t.slot_id
                        WHERE s.round_id=%s AND g.stage='topic_review' AND g.status='open'
                        ORDER BY g.created_at DESC LIMIT 1""", (round_id,))
        r = cur.fetchone()
        if not r:
            cur.close(); raise GateError(f"no open topic_review gate for round {round_id}")
        gate_id = r["gate_id"]
    cur.execute("SELECT gate_id, stage, status FROM gate WHERE gate_id=%s", (gate_id,))
    g = cur.fetchone()
    if not g:
        cur.close(); raise GateError(f"no such gate {gate_id}")
    if g["status"] != "open":
        cur.close(); raise GateError(f"gate {gate_id} is {g['status']} — not open")
    # CREATION AUTHORITY — enforce the canonical gate-approval boundary BEFORE any ledger/audit write, so
    # an unauthorized principal creates ZERO durable rows (no bulk_operation, item, or bulk_started
    # audit). `decide` still re-checks per-item authority at run time; both are required.
    try:
        _authorize_gate_approver(cur, gate_id, actor, cfg)
    except GovernedDenial:
        cur.close(); raise
    cur.execute("SELECT t.slot_id FROM gate_target t JOIN slot s USING (slot_id) "
                "WHERE t.gate_id=%s AND s.round_id=%s", (gate_id, round_id))
    member = {r["slot_id"] for r in cur.fetchall()}
    if not member:
        cur.close()
        raise GateError(f"gate {gate_id} has no targets in round {round_id} (wrong round/gate)")
    foreign = sorted({it["slot_id"] for it in slot_items} - member)
    if foreign:
        cur.close()
        raise GateError(f"slots {foreign} are not targets of gate {gate_id} in round {round_id} "
                        f"(membership fail-closed)")
    tenant_id, _module = _round_scope(cur, round_id)
    ordered = sorted(slot_items, key=lambda it: it["slot_id"])
    digest = _bulk_request_digest(round_id, gate_id, action, actor, comment, ordered, tenant_id)
    cur.execute("""INSERT INTO bulk_operation
                     (round_id, gate_id, action, actor, idempotency_key, request_digest, comment, tenant_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (round_id, idempotency_key) DO NOTHING
                   RETURNING batch_id""",
                (round_id, gate_id, action, actor, idempotency_key, digest, comment, tenant_id))
    row = cur.fetchone()
    if not row:
        cur.execute("""SELECT batch_id, state, request_digest FROM bulk_operation
                        WHERE round_id=%s AND idempotency_key=%s""", (round_id, idempotency_key))
        ex = cur.fetchone()
        conn.rollback(); cur.close()
        if ex["request_digest"] != digest:
            raise GovernedDenial(
                f"idempotency key {idempotency_key!r} for round {round_id} was used for a DIFFERENT "
                f"request — refusing to reinterpret it", reason="idempotency_key_mismatch")
        return {"action": "dedupe" if ex["state"] == "completed" else "resume",
                "batch_id": str(ex["batch_id"])}
    batch_id = row["batch_id"]
    for seq, it in enumerate(ordered, start=1):
        cur.execute("""INSERT INTO bulk_operation_item (batch_id, slot_id, seq, expected_revision)
                       VALUES (%s,%s,%s,%s)""", (batch_id, it["slot_id"], seq, it.get("expected_revision")))
    _audit(cur, "bulk_operation", batch_id, "bulk_started", actor,
           {"round_id": round_id, "gate_id": str(gate_id), "action": action, "request_digest": digest,
            "slots": [it["slot_id"] for it in ordered], "idempotency_key": idempotency_key})
    conn.commit(); cur.close()
    return {"action": "start", "batch_id": str(batch_id)}


def _bulk_claim(conn, batch_id, lease_seconds):
    """Claim the batch for THIS driver: queued/failed/lease-expired -> running with a fresh claim_token,
    EXACTLY ONCE (mirrors claim_rework_operation). Returns the row (carrying claim_token) or None
    (completed, or running under a live lease held by another driver)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT state FROM bulk_operation WHERE batch_id=%s", (batch_id,))
    prior = cur.fetchone()
    cur.execute("""UPDATE bulk_operation
                     SET state='running', claim_token=gen_random_uuid(),
                         lease_expires_at=now() + make_interval(secs => %s),
                         heartbeat_at=now(), updated_at=now()
                   WHERE batch_id=%s AND state IN ('queued','running','failed')
                     AND (state <> 'running' OR lease_expires_at IS NULL OR lease_expires_at < now())
                   RETURNING *""", (lease_seconds, batch_id))
    row = cur.fetchone()
    if row:
        _audit(cur, "bulk_operation", batch_id,
               "bulk_reclaimed" if (prior and prior["state"] == "running") else "bulk_claimed",
               row["actor"], {"prior_state": prior["state"] if prior else None,
                              "lease_seconds": lease_seconds})
    conn.commit(); cur.close()
    return row


def _bulk_owns(conn, batch_id, claim_token):
    """True while THIS driver still owns the running batch (fenced by claim_token)."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bulk_operation WHERE batch_id=%s AND claim_token=%s AND state='running'",
                (batch_id, claim_token))
    owns = cur.fetchone() is not None
    conn.commit(); cur.close()
    return owns


def _settle_item_row(cur, batch_id, claim_token, slot_id, outcome, reason, actor):
    """UPDATE an item's TERMINAL outcome on the GIVEN cursor (NO commit here — the caller commits or rolls
    back), fenced by claim_token + still-pending. Returns True iff this call settled it."""
    cur.execute("""UPDATE bulk_operation_item
                     SET outcome=%s, reason=%s, attempted_at=now(), settled_at=now()
                   WHERE batch_id=%s AND slot_id=%s AND outcome IS NULL
                     AND EXISTS (SELECT 1 FROM bulk_operation b
                                  WHERE b.batch_id=%s AND b.claim_token=%s AND b.state='running')""",
                (outcome, reason, batch_id, slot_id, batch_id, claim_token))
    settled = cur.rowcount == 1
    if settled:
        _audit(cur, "bulk_operation_item", batch_id, "bulk_item_settled", actor,
               {"slot_id": slot_id, "outcome": outcome, "reason": reason})
    return settled


def _drive_and_settle_bulk_item(batch_id, claim_token, gate_id, actor, decision, slot_id,
                                expected_revision, eligibility_check, notes, cfg):
    """Drive ONE item through the canonical `decide` command AND record its ledger outcome ATOMICALLY in
    ONE transaction, fenced by claim_token. On SUCCESS, decide's effect (uncommitted via _commit=False) +
    the 'succeeded' settle commit TOGETHER — or roll back together if ownership was lost mid-flight. On a
    typed denial/conflict, decide's txn rolls back (NO effect) and the outcome is recorded on a fresh
    fenced txn. So a NULL-outcome item PROVABLY has no committed effect — `fail_bulk_operation` marking it
    `not_attempted` can never race a committed effect. Returns the outcome, or None if ownership was lost
    (item stays pending for a fresh claim to re-drive; `decide` is idempotent + head-stable)."""
    conn = db_connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            decide(conn, gate_id, actor, decision, slot_ids=[slot_id], notes=notes,
                   expected_revision=expected_revision, eligibility_check=eligibility_check, cfg=cfg,
                   _commit=False)
            outcome, reason, effect = "succeeded", None, True
        except RevisionConflict as e:
            conn.rollback(); outcome, reason, effect = "stale", str(e), False
        except GovernedDenial as e:
            conn.rollback(); outcome, reason, effect = "denied", (getattr(e, "reason", None) or str(e)), False
        except GateNotReady as e:
            conn.rollback(); outcome, reason, effect = "conflicted", str(e), False
        except GateError as e:
            conn.rollback(); outcome, reason, effect = "denied", str(e), False
        if effect:
            settled = _settle_item_row(cur, batch_id, claim_token, slot_id, outcome, reason, actor)
            if settled:
                conn.commit(); return outcome          # effect + outcome commit atomically
            conn.rollback(); return None               # ownership lost -> undo the effect too; re-drive
        # denial/conflict: NO effect committed -> record the outcome on a fresh, fenced txn
        c2 = db_connect()
        try:
            cur2 = c2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            settled = _settle_item_row(cur2, batch_id, claim_token, slot_id, outcome, reason, actor)
            if settled:
                c2.commit()
            else:
                c2.rollback()
        finally:
            c2.close()
        return outcome if settled else None
    finally:
        conn.close()


def run_bulk_operation(batch_id, actor="system", lease_seconds=None, cfg=None):
    """#314 — drive all UNSETTLED items of a bulk operation to a truthful per-item outcome under an
    exclusive claim_token, in ascending-slot_id order. Idempotent + recoverable: a completed batch returns
    its outcomes unchanged; a crashed batch is resumed (only NULL-outcome items are re-driven; `decide` is
    idempotent + head-stable so re-driving never double-effects). Uses its own connections (db_connect)
    for independent per-item commits. Returns the status read model."""
    cfg = cfg or load_config()
    lease_seconds = lease_seconds or _BULK_LEASE_SECONDS
    conn = db_connect()
    op = _bulk_claim(conn, batch_id, lease_seconds)
    conn.close()
    if not op:
        return bulk_operation_status(batch_id)     # completed, or owned by a live driver — idempotent
    claim = op["claim_token"]; gate_id = op["gate_id"]; action = op["action"]
    comment = op["comment"]; owner = op["actor"]
    decision = _BULK_ACTION_DECISION[action]
    conn = db_connect(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT slot_id, expected_revision FROM bulk_operation_item
                    WHERE batch_id=%s AND outcome IS NULL ORDER BY seq""", (batch_id,))
    pending = cur.fetchall(); conn.commit(); conn.close()
    for it in pending:
        c = db_connect(); owns = _bulk_owns(c, batch_id, claim); c.close()
        if not owns:
            break                                  # ownership transferred — stop; a fresh claim finishes
        _drive_and_settle_bulk_item(batch_id, claim, gate_id, owner, decision, it["slot_id"],
                                    it["expected_revision"], eligibility_check=(action == "bulk_drop"),
                                    notes=comment, cfg=cfg)
    # finalize: mark completed iff we still own AND no item remains pending
    conn = db_connect(); cur = conn.cursor()
    cur.execute("""UPDATE bulk_operation SET state='completed', updated_at=now()
                   WHERE batch_id=%s AND claim_token=%s AND state='running'
                     AND NOT EXISTS (SELECT 1 FROM bulk_operation_item
                                      WHERE batch_id=%s AND outcome IS NULL)""",
                (batch_id, claim, batch_id))
    if cur.rowcount == 1:
        _audit(cur, "bulk_operation", batch_id, "bulk_completed", owner, {})
    conn.commit(); cur.close(); conn.close()
    return bulk_operation_status(batch_id)


def fail_bulk_operation(batch_id, error="stopped", actor="system", lease_seconds=None):
    """Terminally stop a bulk operation, OWNERSHIP-FENCED so `not_attempted` can never race a committed
    effect. First CLAIM the batch (mint a fresh claim_token): if a live driver holds it, the claim
    returns None and we DO NOT race it — we report current state. Once claimed (idle / lease-expired), any
    stale driver is fenced out, so — under our claim — every still-pending (NULL) item is recorded
    `not_attempted` and the batch marked `failed`. Because a driver's effect is ATOMIC with its settle
    (_drive_and_settle_bulk_item), a NULL item provably has NO committed effect, so `not_attempted` is
    truthful. Idempotent."""
    conn = db_connect()
    op = _bulk_claim(conn, batch_id, lease_seconds or _BULK_LEASE_SECONDS)
    if not op:
        conn.close()
        return bulk_operation_status(batch_id)      # completed, or owned by a LIVE driver — never raced
    claim = op["claim_token"]
    cur = conn.cursor()
    cur.execute("""UPDATE bulk_operation_item SET outcome='not_attempted', settled_at=now()
                   WHERE batch_id=%s AND outcome IS NULL
                     AND EXISTS (SELECT 1 FROM bulk_operation b
                                  WHERE b.batch_id=%s AND b.claim_token=%s AND b.state='running')""",
                (batch_id, batch_id, claim))
    n = cur.rowcount
    cur.execute("""UPDATE bulk_operation SET state='failed', error_detail=%s, updated_at=now()
                   WHERE batch_id=%s AND claim_token=%s""", (error, batch_id, claim))
    _audit(cur, "bulk_operation", batch_id, "bulk_failed", actor, {"error": error, "not_attempted": n})
    conn.commit(); cur.close(); conn.close()
    return bulk_operation_status(batch_id)


def bulk_operation_status(batch_id):
    """Read model: the bulk operation header + every per-item outcome (truthful partial results)."""
    conn = db_connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT batch_id, round_id, gate_id, action, actor, state, idempotency_key,
                              comment, error_detail FROM bulk_operation WHERE batch_id=%s""", (batch_id,))
        h = cur.fetchone()
        if not h:
            cur.close(); raise GateError(f"no such bulk operation {batch_id}")
        cur.execute("""SELECT slot_id, seq, expected_revision, outcome, reason
                         FROM bulk_operation_item WHERE batch_id=%s ORDER BY seq""", (batch_id,))
        items = [dict(r) for r in cur.fetchall()]
        cur.close()
        return {"batch_id": str(h["batch_id"]), "round_id": h["round_id"], "gate_id": str(h["gate_id"]),
                "action": h["action"], "actor": h["actor"], "state": h["state"],
                "idempotency_key": h["idempotency_key"], "comment": h["comment"],
                "error_detail": h["error_detail"],
                "items": [{"slot_id": i["slot_id"], "seq": i["seq"],
                           "expected_revision": i["expected_revision"],
                           "outcome": i["outcome"], "reason": i["reason"]} for i in items]}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# #439 — Stage 4 dedicated final-review SIGN-OFF (one immutable receipt; grants no authority)
#
# A narrow governed command: a verified principal signs off an immutable (gate_id, slot_id)
# target-package whose PRESENT state is authoritatively approved. The receipt is the SOLE effect —
# no lifecycle advance, no decision/coverage/snapshot/package mutation, no new authority. Present
# authority is re-evaluated here from the EXISTING frozen snapshot + persisted coverage (never frozen
# historical eligibility, never the V2 read projection). Every mapped failure is a typed SignoffError.
# --------------------------------------------------------------------------- #
def _signoff_error(code):
    return SignoffError(code, SIGNOFF_ERROR_STATUS[code])


def _signoff_request_digest(gate_id, slot_id, snapshot_id, topic_revision, script_revision,
                            workflow_version_id, actor):
    """#439 digest format v1 (identified by operation='sign_off'): lowercase SHA-256 hex over UTF-8
    COMPACT JSON with SORTED keys and NO optional fields. UUIDs are lowercase canonical text; revisions
    are decimal JSON integers; compact separators are ',' and ':'; idempotency_key is EXCLUDED. The
    verified principal (`actor`) is the sole actor bound into the digest, so the same key reused by a
    different actor necessarily changes the digest."""
    payload = {
        "operation": "sign_off",
        "gate_id": str(gate_id).lower(),
        "slot_id": slot_id,
        "snapshot_id": str(snapshot_id).lower(),
        "topic_revision": int(topic_revision),
        "script_revision": int(script_revision),
        "workflow_version_id": str(workflow_version_id).lower(),
        "actor": actor,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _signoff_receipt(row):
    """The exact success/replay receipt. Never returns raw actor/principal identity, provenance
    internals, coverage, or package existence beyond the defined fields."""
    return {
        "signoff_id": str(row["signoff_id"]),
        "operation": "sign_off",
        "status": "recorded",
        "gate_id": str(row["gate_id"]).lower(),
        "slot_id": row["slot_id"],
        "snapshot_id": str(row["snapshot_id"]).lower(),
        "topic_revision": int(row["topic_revision"]),
        "script_revision": int(row["script_revision"]),
        "workflow_version_id": str(row["workflow_version_id"]).lower(),
        "recorded_at": row["recorded_at"].isoformat(),
    }


def _signoff_revalidate_present_authority(cur, cfg, gate_id, slot_id, actor, pkg):
    """Re-evaluate PRESENT authority for a sign-off from authoritative server state, in the directive
    order: live gate + slot, governed head vs pinned package revisions, current APPROVED outcome, then
    governed-assignment authority, actor-model hard floor, and action policy. Frozen historical
    eligibility is NEVER present authority; the V2 projection is not an input. Raises a typed
    SignoffError; returns nothing on success. Calls existing helpers WITHOUT modifying their semantics."""
    cur.execute("SELECT gate_id::text AS gate_id, stage, status::text AS status "
                "FROM gate WHERE gate_id=%s", (gate_id,))
    gate = cur.fetchone()
    if gate is None or gate["stage"] != FINAL_REVIEW_STAGE:
        raise _signoff_error("signoff_target_unavailable")
    if gate["status"] != "open":
        raise _signoff_error("signoff_blocked")            # present state not actionable
    cur.execute("SELECT 1 FROM gate_target WHERE gate_id=%s AND slot_id=%s", (gate_id, slot_id))
    if cur.fetchone() is None:
        raise _signoff_error("signoff_target_unavailable")
    # #282 frozen snapshot governs authoritative resolution; a legacy gate (no snapshot) has no
    # authoritative present-state evidence to approve against — fail closed.
    snapshot = _load_gate_snapshot(cur, gate_id)
    if snapshot is None:
        raise _signoff_error("signoff_blocked")
    # Schema-impossible defensive check: gate_decision forbids a NULL slot_id, so a whole-batch
    # (slot-unattributable) decision cannot be persisted. If one ever appears, fail closed.
    cur.execute("SELECT count(*) AS n FROM gate_decision WHERE gate_id=%s AND slot_id IS NULL", (gate_id,))
    if (cur.fetchone()["n"] or 0) > 0:
        raise _signoff_error("signoff_blocked")
    # Stale governed head or stale package revision: the CURRENT canonical head must still equal the
    # revisions the immutable package pinned (a post-attachment rework advances the head -> stale).
    if (_head_revision(cur, slot_id, "topic") != int(pkg["topic_revision"])
            or _head_revision(cur, slot_id, "script") != int(pkg["script_revision"])):
        raise _signoff_error("signoff_stale")
    # Present APPROVED outcome, projected from the frozen snapshot + persisted head-correct coverage
    # (never a count, never live membership). Anything else (rejected / changes_requested / pending)
    # is a non-actionable present state.
    cur.execute("SELECT approver_id, decision::text AS decision, revision, decided_at "
                "FROM gate_decision WHERE gate_id=%s AND slot_id=%s ORDER BY decided_at, approver_id",
                (gate_id, slot_id))
    decisions = cur.fetchall()
    # #321 — count only decisions effective on the gate's governed head. For a sign-off gate
    # (`final_review`, no rework_mode) `_gate_review_head` is None and `_effective_decisions_for_head`
    # is inert, but threading both seams keeps this on the one coverage/decision truth the projection
    # uses everywhere and stays correct if the stage ever gains an artifact.
    head = _gate_review_head(cur, cfg, FINAL_REVIEW_STAGE, slot_id)
    eff = _effective_decisions_for_head(decisions, head)
    proj = _authoritative_target_projection(cur, gate_id, snapshot, slot_id, eff)
    if proj["current_outcome"] != "approved":
        raise _signoff_error("signoff_blocked")
    # Governed-assignment authority: the actor must be FROZEN-eligible for the gate (parity with decide's
    # #282 D3 authorization — an actor eligible at open stays authorized; one added after open is not).
    eligible = set().union(*(t["eligible"] for t in snapshot["tokens"])) if snapshot["tokens"] else set()
    if snapshot["tokens"] and actor not in eligible:
        raise _signoff_error("signoff_not_authorized")
    # Actor-model hard floor: final_review is a hard-floor gate — a non-human can never sign off,
    # regardless of autonomy or eligibility (same rule as decide). `authorize_gate_decision` returns
    # (allowed, reason); at this base its ONE recognized denial value is the free-text hard-floor
    # message. We map to the public `signoff_hard_floor` code ONLY on EXACT string equality to that
    # recognized value (#442 F1) — never by truthiness, substring, prefix, inferred meaning, or the
    # `is_hard_floor_gate` predicate alone. Any OTHER denial reason (an unknown/future value, even while
    # the hard-floor configuration is true) is UNRECOGNIZED: fail closed WITHOUT a guessed typed/public
    # code (a bare GateError -> unhandled 500). Both refusals reach the sign_off boundary, which rolls
    # the transaction back before any receipt/audit is written — never a mislabeled signoff_hard_floor.
    if actors.enabled(cfg):
        ok, why = actors.authorize_gate_decision(cfg, actors.load_principal(cur, actor), FINAL_REVIEW_STAGE)
        if not ok:
            if why == f"hard floor: '{FINAL_REVIEW_STAGE}' must be decided by a human":
                raise _signoff_error("signoff_hard_floor")
            raise GateError(f"unrecognized gate-decision authorization denial for "
                            f"{FINAL_REVIEW_STAGE!r} — sign-off refused (fail closed, no public mapping)")


# The two NAMED receipt uniqueness constraints (migration 037) whose violation is a genuine same-target
# race — never a foreign-key / check / not-null / unrelated-unique failure.
_SIGNOFF_RACE_CONSTRAINTS = ("final_review_signoff_tuple_uq", "final_review_signoff_idem_uq")


def _signoff_race_conflict(exc):
    """True iff `exc` is a translatable sign-off RACE — a receipt-insert `UniqueViolation` on EITHER
    named receipt uniqueness constraint, or a `SerializationFailure` (SQLSTATE 40001) / `DeadlockDetected`
    (SQLSTATE 40P01). Every other failure — an UNRELATED unique violation, foreign-key, check, not-null,
    connection, syntax, or programming error — returns False and is left to propagate unchanged. The
    deterministic replay / digest-mismatch / already-recorded outcomes are decided by the pre-check
    SELECTs, never by re-reading an insert exception; a violation that reaches the INSERT means a
    concurrent contender slipped past the package FOR UPDATE lock, i.e. a genuine conflict."""
    if isinstance(exc, psycopg2.errors.UniqueViolation):
        return getattr(getattr(exc, "diag", None), "constraint_name", None) in _SIGNOFF_RACE_CONSTRAINTS
    return isinstance(exc, (psycopg2.errors.SerializationFailure, psycopg2.errors.DeadlockDetected))


def sign_off(conn, gate_id, slot_id, actor, snapshot_id, topic_revision, script_revision,
             workflow_version_id, idempotency_key, cfg=None):
    """#439 — record ONE immutable final-review sign-off receipt for an immutable (gate_id, slot_id)
    target-package, or return the ORIGINAL receipt on an identical idempotent replay. `actor` is the
    ALREADY-VERIFIED proxy principal (the handler resolves it via _trusted_approval_actor; the request
    carries no actor field). Grants no authority and advances no lifecycle: the receipt is the sole
    effect. Raises SignoffError (typed public code + HTTP status) on every mapped failure; on any error
    the transaction is rolled back so the receipt never persists.

    One connection, one transaction, exact order: load+lock the package FOR UPDATE -> compare the full
    stored identity + the four submitted binding fields -> idempotency lookup (digest compare) ->
    one-time tuple lookup -> revalidate present state + authority -> insert receipt -> insert exactly one
    success audit on the SAME cursor -> commit. The DB uniqueness + the locked package row serialize
    same-target requests, so a race that slips past the pre-checks (a named receipt-uniqueness violation,
    or a serialization/deadlock failure) is translated to signoff_conflict at the transaction boundary
    via _signoff_race_conflict — a defensive fallback, since a same-target contender cannot insert until
    this transaction commits. Every unrelated failure rolls back and propagates unchanged."""
    cfg = cfg or load_config()
    idempotency_key = (idempotency_key or "").strip()
    snapshot_id = str(snapshot_id).lower()
    workflow_version_id = str(workflow_version_id).lower()
    topic_revision = int(topic_revision)
    script_revision = int(script_revision)
    digest = _signoff_request_digest(gate_id, slot_id, snapshot_id, topic_revision, script_revision,
                                     workflow_version_id, actor)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # (1) Load + LOCK the immutable package row (serializes same-target sign-offs).
        cur.execute(
            "SELECT gate_id::text AS gate_id, slot_id, snapshot_id::text AS snapshot_id, round_id, "
            "topic_id::text AS topic_id, topic_revision, script_id::text AS script_id, script_revision, "
            "workflow_version_id::text AS workflow_version_id, workflow_version_source, "
            "production_directive_id::text AS production_directive_id, production_directive_revision "
            "FROM final_review_target_package WHERE gate_id=%s AND slot_id=%s FOR UPDATE",
            (str(gate_id), slot_id))
        pkg = cur.fetchone()
        if pkg is None:
            raise _signoff_error("signoff_target_unavailable")
        # (2) Compare the four submitted binding fields against the full stored package identity.
        if not (pkg["snapshot_id"].lower() == snapshot_id
                and int(pkg["topic_revision"]) == topic_revision
                and int(pkg["script_revision"]) == script_revision
                and pkg["workflow_version_id"].lower() == workflow_version_id):
            raise _signoff_error("signoff_package_mismatch")
        # (3) Idempotency lookup: (gate_id, slot_id, idempotency_key). Identical digest -> original
        #     receipt (no second audit, nothing written); different digest -> mismatch.
        cur.execute("SELECT * FROM final_review_signoff WHERE gate_id=%s AND slot_id=%s AND idempotency_key=%s",
                    (str(gate_id), slot_id, idempotency_key))
        existing = cur.fetchone()
        if existing is not None:
            if existing["request_digest"] == digest:
                conn.rollback()                              # read-only path: release the lock, write nothing
                return _signoff_receipt(existing)
            raise _signoff_error("idempotency_key_mismatch")
        # (4) One-time tuple lookup: the canonical package tuple may be signed off at most once.
        cur.execute(
            "SELECT 1 FROM final_review_signoff WHERE gate_id=%s AND slot_id=%s AND snapshot_id=%s "
            "AND topic_revision=%s AND script_revision=%s AND workflow_version_id=%s",
            (str(gate_id), slot_id, snapshot_id, topic_revision, script_revision, workflow_version_id))
        if cur.fetchone() is not None:
            raise _signoff_error("signoff_already_recorded")
        # (5) Revalidate present state + authority (approval is never frozen historical eligibility).
        _signoff_revalidate_present_authority(cur, cfg, str(gate_id), slot_id, actor, pkg)
        # (6) Insert the receipt (the sole effect), carrying the full loaded package provenance.
        signoff_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO final_review_signoff (signoff_id, gate_id, slot_id, snapshot_id, round_id, "
            "topic_id, topic_revision, script_id, script_revision, workflow_version_id, "
            "workflow_version_source, production_directive_id, production_directive_revision, "
            "actor, idempotency_key, request_digest, outcome) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'recorded') "
            "RETURNING signoff_id, gate_id, slot_id, snapshot_id, topic_revision, script_revision, "
            "workflow_version_id, recorded_at",
            (signoff_id, str(gate_id), slot_id, snapshot_id, pkg["round_id"], pkg["topic_id"],
             topic_revision, pkg["script_id"], script_revision, workflow_version_id,
             pkg["workflow_version_source"], pkg["production_directive_id"],
             pkg["production_directive_revision"], actor, idempotency_key, digest))
        row = cur.fetchone()
        # (7) Exactly one success audit on the SAME cursor/transaction (no independent commit). A failure
        #     here propagates and rolls the whole transaction back (receipt + audit are atomic).
        _audit(cur, "final_review_signoff", signoff_id, "final_review_sign_off", actor, {
            "signoff_id": signoff_id, "gate_id": str(gate_id), "slot_id": slot_id,
            "snapshot_id": snapshot_id, "topic_revision": topic_revision,
            "script_revision": script_revision, "workflow_version_id": workflow_version_id,
            "idempotency_key": idempotency_key, "request_digest": digest, "outcome": "recorded"})
        # (8) Commit.
        conn.commit()
        return _signoff_receipt(row)
    except SignoffError:
        conn.rollback()                              # typed pre-check refusals propagate unchanged
        raise
    except Exception as e:
        # Transaction boundary: roll back FIRST, then translate ONLY a genuine same-target race (a named
        # receipt-uniqueness violation, or a serialization/deadlock failure) to signoff_conflict, keeping
        # the original exception as the cause. Every other failure (FK / check / not-null / unrelated
        # unique / connection / syntax / programming, incl. a success-audit failure) propagates unchanged.
        conn.rollback()
        if _signoff_race_conflict(e):
            raise _signoff_error("signoff_conflict") from e
        raise
