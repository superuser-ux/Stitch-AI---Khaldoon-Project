"""#377 — the canonical governed run-mix RECOMMENDATION authority.

WHAT THIS IS. One server/domain authority that, for a PROSPECTIVE run (inclusive date range +
posts/day), returns either a typed valid recommendation — exact framework counts summing to the
expected slot total, a bounded structured rationale, and immutable provenance — or a typed BLOCKED
result. There is no fallback: no equal distribution, no client heuristic, no fixture default, no
`weekly_count` revival (#276 decommissioned it as allocation authority and it stays decommissioned).

WHAT THIS IS NOT. It is not AI and must never be described as AI. #377's preflight established that
no governed PLANNING model route exists in this repo: every governed route is a content writer driven
by `workflow_stage.writer_mode`, provider selection lives in `system_config.yaml`/env topology
(`agents/providers.py`), and `gates/provenance.py` still declares `used_model_provider` unsupported.
Under GPT amendment 4 a policy-derived recommendation is valid *when truthfully labelled
deterministic*, so that is exactly what this is: an apportionment of an operator-owned governed weight
vector by the deterministic Hamilton/largest-remainder function the planner already ships
(`planner.scale_distribution`). `model_posture` is `not_applicable` and the requested/effective
provenance fields stay empty — deliberately, so a later governed route can fill them without
relabelling anything that happened before it existed.

AUTHORITY SPLIT. This module RECOMMENDS. `planner.validate_format_mix` VALIDATES, unchanged and
still binding: an operator may amend the proposal, and the amended mix is accepted only because the
planner validated it — never because a proposal existed. Provenance never substitutes for validation.

INITIALIZATION. Weights are operator-owned. There is NO seed and no inferred default: a missing
current generation is a typed blocked state (`no_current_recommendation_policy`), mirroring
`engine.ensure_baseline_policy`'s hard-stop rather than seeding an inferred baseline. Creating a
generation goes through `create_policy_generation`, authorized by the same canonical actor check that
governs every other policy administration path.
"""

import datetime as _dt
import hashlib
import json
import sys
import unicodedata
import uuid as _uuid
from pathlib import Path

import psycopg2.extras

import engine

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO / "planner") not in sys.path:
    sys.path.insert(0, str(_REPO / "planner"))
# The apportionment rule is NOT reimplemented here. `largest_remainder_v1` IS this function: Hamilton,
# input-order tie-break, correct when total < len(keys) (the largest weights take the scarce units and
# the rest get 0), never negative. Importing it keeps one deterministic definition in the repo.
from plan_round import scale_distribution  # noqa: E402

# --- version identities. Deliberately DISTINCT from each other, from the policy generation, and from
# --- any commit SHA (GPT amendment 18).
CANONICAL_DIGEST_VERSION = 1
AUTHORITY_VERSION = "run_mix_authority_v1"
ALGORITHM = "largest_remainder_v1"

# Bounded retention for an abandoned proposal: ephemeral generated data, never policy (amendment 9).
DEFAULT_TTL_SECONDS = 24 * 60 * 60
MAX_TTL_SECONDS = 7 * 24 * 60 * 60
# Bounded rationale (amendment 14): fixed keys, integers, and a capped exclusion list. No free prose,
# no chain-of-thought, no quality claim.
MAX_EXCLUSIONS_LISTED = 64
MAX_POLICY_NOTES = 500
MAX_DAYS = 366
MAX_POSTS_PER_DAY = 24

DETERMINISTIC_STATEMENT = (
    "Deterministic apportionment of the current governed recommendation-policy generation over the "
    "current baseline-eligible frameworks. No model was called. This is not an AI recommendation and "
    "makes no claim of optimization, personalization, learning or quality."
)


class RecommendationError(engine.GateError):
    """A typed refusal from this authority. `code` is stable and machine-readable; `status` is the HTTP
    status the API must answer so a governed refusal never degrades into a generic 500."""

    def __init__(self, code, message, status=409, detail=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail or {}


# ---------------------------------------------------------------------------------------------
# Canonical encoding + digest
# ---------------------------------------------------------------------------------------------
def canonical_json(obj) -> str:
    """The ONE canonical encoding the digest is taken over: sorted keys, no insignificant whitespace,
    real Unicode (not \\u escapes) normalized to NFC, integers as integers. Two structurally equal
    payloads therefore encode byte-identically regardless of construction order or input normal form."""
    return unicodedata.normalize(
        "NFC", json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)
    )


def _json_default(o):
    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.isoformat()
    raise TypeError(f"{type(o).__name__} is not canonically encodable")


def digest_of(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def proposal_digest_payload(*, scope, tenant_id, module, created_by, starts_on, ends_on,
                            posts_per_day, expected_slots, eligible_version_ids, recommended_mix,
                            rationale, authority_version, algorithm, policy_id, policy_generation,
                            baseline_policy_id, baseline_generation, methodology_version,
                            workflow_version, model_posture, requested_route, requested_provider,
                            requested_model, effective_route, effective_provider, effective_model,
                            created_at, expires_at) -> dict:
    """Exactly what the digest covers (GPT amendment 7). Adding or removing a member is a
    `digest_version` bump, not a silent edit — the version is part of the payload, so an old digest can
    never be re-derived under new rules and pass."""
    return {
        "digest_version": CANONICAL_DIGEST_VERSION,
        "authority_version": authority_version,
        "algorithm": algorithm,
        "scope": {"scope": scope, "tenant_id": tenant_id, "module": module},
        "principal": created_by,
        "window": {"starts_on": _as_date_str(starts_on), "ends_on": _as_date_str(ends_on),
                   "posts_per_day": int(posts_per_day), "expected_slots": int(expected_slots)},
        "eligible_version_ids": list(eligible_version_ids),      # ORDERED — order is load-bearing
        "recommended_mix": {k: int(v) for k, v in recommended_mix.items()},
        "rationale": rationale,
        "generations": {
            "recommendation_policy_id": str(policy_id),
            "recommendation_policy_generation": int(policy_generation),
            "baseline_policy_id": str(baseline_policy_id),
            "baseline_generation": int(baseline_generation),
            "methodology_version": methodology_version,
            "workflow_version": workflow_version,
        },
        "model": {
            "posture": model_posture,
            "requested_route": requested_route, "requested_provider": requested_provider,
            "requested_model": requested_model, "effective_route": effective_route,
            "effective_provider": effective_provider, "effective_model": effective_model,
        },
        "created_at": _as_iso(created_at),
        "expires_at": _as_iso(expires_at),
    }


def request_digest_of(*, proposal_id, days, posts_per_day, starts_on, format_mix, label, principal) -> str:
    """The idempotency payload: what a caller asked for when creating the run. Same key + same payload
    converges; same key + different payload is a typed conflict (amendment 10)."""
    return digest_of({
        "digest_version": CANONICAL_DIGEST_VERSION,
        "proposal_id": str(proposal_id),
        "days": int(days),
        "posts_per_day": int(posts_per_day),
        "starts_on": _as_date_str(starts_on),
        "format_mix": {k: int(v) for k, v in (format_mix or {}).items()},
        "label": label,
        "principal": principal,
    })


def _as_date_str(d):
    if d is None:
        return None
    if isinstance(d, _dt.datetime):
        return d.date().isoformat()
    if isinstance(d, _dt.date):
        return d.isoformat()
    return str(d)


def _as_iso(t):
    if t is None:
        return None
    if isinstance(t, _dt.datetime):
        return t.astimezone(_dt.timezone.utc).isoformat()
    return str(t)


def _parse_date(value, field):
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO-8601 date (YYYY-MM-DD)")


# ---------------------------------------------------------------------------------------------
# Governed policy generations (operator-owned; create-missing-only; never overwritten)
# ---------------------------------------------------------------------------------------------
def current_policy(cur, scope="default", tenant_id="default", module="content"):
    """The one CURRENT recommendation-policy generation for the scope, or None. Zero current is a
    normal, truthful state here — it means no operator has declared weights yet, and the authority is
    blocked rather than inventing any."""
    cur.execute("""SELECT policy_id::text AS policy_id, scope, generation, status, weight_source,
                          weights, min_counts, max_counts, algorithm, authority_version, notes,
                          created_by, created_at, tenant_id, module
                   FROM run_mix_recommendation_policy
                   WHERE scope=%s AND tenant_id=%s AND module=%s AND status='current'""",
                (scope, tenant_id, module))
    return cur.fetchone()


def read_current_policy(conn, scope="default", tenant_id="default", module="content"):
    """API-facing read of the current generation. `absent` is a truthful state, not an error: it means
    no operator has declared weights yet and the authority is blocked rather than inventing any."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        row = current_policy(cur, scope, tenant_id, module)
    finally:
        cur.close()
    if not row:
        return {"status": "absent", "scope": scope,
                "detail": "no current run-mix recommendation policy generation for this scope"}
    return {"status": "current", "policy_id": row["policy_id"], "generation": row["generation"],
            "scope": row["scope"], "tenant_id": row["tenant_id"], "module": row["module"],
            "weight_source": row["weight_source"], "algorithm": row["algorithm"],
            "authority_version": row["authority_version"], "weights": row["weights"],
            "min_counts": row["min_counts"], "max_counts": row["max_counts"],
            "notes": row["notes"], "created_by": row["created_by"],
            "created_at": _as_iso(row["created_at"]), "model_posture": "not_applicable"}


def _normalize_weight_map(raw, field):
    """A weight/min/max map is {content_format_version.version_id: non-negative integer}. Keyed by
    VERSION ID, never by name: a rename must not silently re-point a governed weight."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{field} must be an object of {{version_id: integer}}")
    out = {}
    for k, v in raw.items():
        key = str(k).strip()
        if not key:
            raise ValueError(f"{field} contains an empty version id")
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{field}[{key!r}] must be an integer")
        if v < 0:
            raise ValueError(f"{field}[{key!r}] must be >= 0")
        out[key] = v
    return out


def create_policy_generation(conn, payload, actor="system", scope="default",
                             tenant_id="default", module="content"):
    """Mint a NEW governed recommendation-policy generation and supersede the current one.

    This is the ONLY authorized way an active policy comes into existence — including for candidate
    fixtures (GPT amendment 3: no executor-created active policy merely for tests). It never edits an
    existing generation in place: the prior current row is marked superseded and the new generation is
    appended, so history stays readable and an already-pinned snapshot is unaffected."""
    if not engine.can_administer_approval_policies(conn, actor):
        raise RecommendationError("not_authorized",
                                  f"{actor!r} may not administer run-mix recommendation policy",
                                  status=403)
    weights = _normalize_weight_map(payload.get("weights"), "weights")
    if not weights:
        raise ValueError("weights is required: an integer weight per baseline-eligible "
                         "content_format_version id")
    if not any(w > 0 for w in weights.values()):
        raise ValueError("weights must contain at least one positive weight")
    min_counts = _normalize_weight_map(payload.get("min_counts"), "min_counts")
    max_counts = _normalize_weight_map(payload.get("max_counts"), "max_counts")
    for k, v in max_counts.items():
        if k in min_counts and min_counts[k] > v:
            raise ValueError(f"min_counts[{k!r}] exceeds max_counts[{k!r}]")
    notes = payload.get("notes")
    notes = str(notes)[:MAX_POLICY_NOTES] if notes else None

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT policy_id::text AS policy_id, generation
                       FROM run_mix_recommendation_policy
                       WHERE scope=%s AND tenant_id=%s AND module=%s AND status='current'
                       FOR UPDATE""", (scope, tenant_id, module))
        prior = cur.fetchone()
        generation = (prior["generation"] + 1) if prior else 1
        if prior:
            # Supersede FIRST: the partial unique index is evaluated per statement, so inserting a
            # second 'current' row while the prior one is still current is a constraint violation.
            # The zero-current window exists only inside this transaction and is invisible outside it.
            cur.execute("""UPDATE run_mix_recommendation_policy
                           SET status='superseded', superseded_at=now() WHERE policy_id=%s""",
                        (prior["policy_id"],))
        cur.execute("""INSERT INTO run_mix_recommendation_policy
                       (scope, generation, status, weight_source, weights, min_counts, max_counts,
                        algorithm, authority_version, notes, created_by, tenant_id, module)
                       VALUES (%s,%s,'current','explicit',%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING policy_id::text AS policy_id, generation, created_at""",
                    (scope, generation, psycopg2.extras.Json(weights),
                     psycopg2.extras.Json(min_counts), psycopg2.extras.Json(max_counts),
                     ALGORITHM, AUTHORITY_VERSION, notes, actor, tenant_id, module))
        row = cur.fetchone()
        if prior:
            # Complete the lineage link now that the successor has an identity.
            cur.execute("""UPDATE run_mix_recommendation_policy SET superseded_by=%s
                           WHERE policy_id=%s""", (row["policy_id"], prior["policy_id"]))
        engine._audit(cur, "run_mix_policy", row["policy_id"], "run_mix_policy_created", actor,
                      {"scope": scope, "generation": row["generation"],
                       "weighted_versions": len(weights),
                       "supersedes": prior["policy_id"] if prior else None})
        conn.commit()
        return {"policy_id": row["policy_id"], "generation": row["generation"],
                "status": "current", "scope": scope, "tenant_id": tenant_id, "module": module,
                "weight_source": "explicit", "algorithm": ALGORITHM,
                "authority_version": AUTHORITY_VERSION, "weights": weights,
                "min_counts": min_counts, "max_counts": max_counts, "notes": notes,
                "created_by": actor, "created_at": _as_iso(row["created_at"])}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------------------------
# Deterministic apportionment
# ---------------------------------------------------------------------------------------------
def apportion(order, weights, total, mins, maxs):
    """Allocate exactly `total` units over `order` (canonical eligible order) by
    `largest_remainder_v1`, honouring per-key minima and maxima.

    Deterministic in every branch: `order` is the canonical eligible order, `scale_distribution` is
    Hamilton with an input-order tie-break, and the capping loop walks `order`. Raises
    RecommendationError with a stable code when the policy cannot satisfy the request — it never
    approximates and never silently drops a constraint."""
    alloc = {k: int(mins.get(k, 0)) for k in order}
    for k in order:
        cap = maxs.get(k)
        if cap is not None and alloc[k] > cap:
            raise RecommendationError("minimum_exceeds_maximum",
                                      f"policy minimum for {k} exceeds its maximum", status=409,
                                      detail={"version_id": k})
    if sum(alloc.values()) > total:
        raise RecommendationError("minima_exceed_slots",
                                  "the policy minimums require more slots than the run has",
                                  status=409,
                                  detail={"minimum_total": sum(alloc.values()), "expected_slots": total})
    remaining = total - sum(alloc.values())
    while remaining > 0:
        free = {k: weights[k] for k in order
                if weights.get(k, 0) > 0 and (maxs.get(k) is None or alloc[k] < maxs[k])}
        if not free:
            raise RecommendationError("maxima_below_slots",
                                      "the policy maximums cannot absorb the run's slot total",
                                      status=409,
                                      detail={"unallocated": remaining, "expected_slots": total})
        add = scale_distribution(free, remaining)
        progressed = False
        for k in order:
            want = int(add.get(k, 0))
            if want <= 0:
                continue
            cap = maxs.get(k)
            room = want if cap is None else min(want, cap - alloc[k])
            take = max(0, min(room, remaining))
            if take:
                alloc[k] += take
                remaining -= take
                progressed = True
        if not progressed:
            raise RecommendationError("maxima_below_slots",
                                      "the policy maximums cannot absorb the run's slot total",
                                      status=409,
                                      detail={"unallocated": remaining, "expected_slots": total})
    return alloc


# ---------------------------------------------------------------------------------------------
# The recommendation itself
# ---------------------------------------------------------------------------------------------
def _blocked(reason, detail_message, **extra):
    out = {"status": "blocked", "reason": reason, "detail": detail_message,
           "model_posture": "not_applicable", "authority_version": AUTHORITY_VERSION}
    out.update(extra)
    return out


def recommend(conn, *, starts_on, ends_on, posts_per_day, principal,
              scope="default", tenant_id="default", module="content"):
    """The canonical recommendation. Returns a typed dict:

        {"status": "recommended", ...}  — exact counts summing to expected_slots, rationale, provenance
        {"status": "blocked", "reason": <stable code>, ...} — no fallback, no partial mix

    A blocked result is a real governed state, not an error: the caller must show it and must not
    enable durable submission. Malformed INPUT (bad dates, out-of-range posts/day) raises ValueError —
    that is a caller bug, not a governed state, and the API answers 422."""
    start = _parse_date(starts_on, "starts_on")
    end = _parse_date(ends_on, "ends_on")
    if end < start:
        raise ValueError("ends_on must be on or after starts_on (the range is inclusive)")
    days = (end - start).days + 1
    if days > MAX_DAYS:
        raise ValueError(f"the selected range spans {days} days; the maximum is {MAX_DAYS}")
    ppd = int(posts_per_day)
    if ppd < 1 or ppd > MAX_POSTS_PER_DAY:
        raise ValueError(f"posts_per_day must be between 1 and {MAX_POSTS_PER_DAY}")
    expected = days * ppd

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        policy = current_policy(cur, scope, tenant_id, module)
        if not policy:
            return _blocked("no_current_recommendation_policy",
                            "No governed run-mix recommendation policy generation is active for this "
                            "scope. An authorized operator must declare the framework weights before a "
                            "run can be proposed.",
                            starts_on=start.isoformat(), ends_on=end.isoformat(),
                            posts_per_day=ppd, expected_slots=expected)
        try:
            elig = engine.resolve_run_eligibility(cur, scope, tenant_id, module)
        except engine.GateError as e:
            return _blocked("baseline_eligibility_unavailable", str(e),
                            starts_on=start.isoformat(), ends_on=end.isoformat(),
                            posts_per_day=ppd, expected_slots=expected)
        eligible = elig["eligible"]
        if not eligible:
            return _blocked("no_eligible_frameworks",
                            "The current baseline eligibility policy offers no frameworks, so there is "
                            "nothing to allocate.",
                            starts_on=start.isoformat(), ends_on=end.isoformat(),
                            posts_per_day=ppd, expected_slots=expected)

        order = [e["version_id"] for e in eligible]
        name_of = {e["version_id"]: e["name"] for e in eligible}
        weights = dict(policy["weights"] or {})
        mins = dict(policy["min_counts"] or {})
        maxs = dict(policy["max_counts"] or {})

        # FAIL CLOSED on a moved eligible set. If the baseline policy now offers a version this
        # generation never weighted, the authority has no governed opinion about it — re-weighting or
        # defaulting it to zero would both be inventions.
        unweighted = [v for v in order if v not in weights]
        if unweighted:
            return _blocked("eligible_version_unweighted",
                            "The active recommendation-policy generation declares no weight for "
                            f"{len(unweighted)} currently eligible framework version(s). A new governed "
                            "generation must weight them before a run can be proposed.",
                            unweighted_version_ids=unweighted[:MAX_EXCLUSIONS_LISTED],
                            starts_on=start.isoformat(), ends_on=end.isoformat(),
                            posts_per_day=ppd, expected_slots=expected)
        eligible_weights = {v: int(weights[v]) for v in order}
        if not any(w > 0 for w in eligible_weights.values()):
            return _blocked("all_weights_zero",
                            "Every currently eligible framework has weight 0 in the active generation, "
                            "so the policy expresses no allocation.",
                            starts_on=start.isoformat(), ends_on=end.isoformat(),
                            posts_per_day=ppd, expected_slots=expected)

        eligible_mins = {v: int(mins[v]) for v in order if v in mins}
        eligible_maxs = {v: int(maxs[v]) for v in order if v in maxs}
        try:
            by_version = apportion(order, eligible_weights, expected, eligible_mins, eligible_maxs)
        except RecommendationError as e:
            return _blocked(e.code, str(e), starts_on=start.isoformat(), ends_on=end.isoformat(),
                            posts_per_day=ppd, expected_slots=expected, **(e.detail or {}))

        mix = {name_of[v]: by_version[v] for v in order}
        # Defensive: the apportionment contract is "exactly total". If that ever failed we would be
        # about to hand the planner a mix it must reject anyway — say so here instead.
        if sum(mix.values()) != expected:
            raise RecommendationError("apportionment_total_mismatch",
                                      f"apportionment produced {sum(mix.values())} of {expected} slots",
                                      status=500)

        excluded = [{"version_id": v, "reason": "not_in_current_baseline_eligibility"}
                    for v in sorted(set(weights) - set(order))][:MAX_EXCLUSIONS_LISTED]
        rationale = {
            "kind": "deterministic_policy_apportionment",
            "statement": DETERMINISTIC_STATEMENT,
            "algorithm": ALGORITHM,
            "authority_version": AUTHORITY_VERSION,
            "expected_slots": expected,
            "days": days,
            "posts_per_day": ppd,
            "weights": eligible_weights,
            "minimums": eligible_mins,
            "maximums": eligible_maxs,
            "allocated": {name_of[v]: by_version[v] for v in order},
            "excluded_versions": excluded,
            "policy_notes": policy.get("notes"),
            "model_posture": "not_applicable",
        }
        return {
            "status": "recommended",
            "starts_on": start.isoformat(), "ends_on": end.isoformat(),
            "posts_per_day": ppd, "days": days, "expected_slots": expected,
            "eligible_version_ids": order,
            "recommended_mix": mix,
            "rationale": rationale,
            "authority_version": AUTHORITY_VERSION,
            "algorithm": ALGORITHM,
            "model_posture": "not_applicable",
            "policy": {"policy_id": policy["policy_id"], "generation": policy["generation"]},
            "baseline_policy": {"policy_id": elig["policy"]["policy_id"],
                                "generation": elig["policy"]["generation"]},
            "methodology_version": engine._active_version_id(cur, "methodology_version", "methodology_id"),
            "workflow_version": engine._active_version_id(cur, "workflow_version", "workflow_id"),
            "principal": principal,
            "scope": scope, "tenant_id": tenant_id, "module": module,
        }
    finally:
        cur.close()


def _normalize_fingerprint(fp):
    """A client-echoed fingerprint, coerced to the exact shape and types recommendation_fingerprint
    produces, so the stale-check compares like with like rather than str-vs-int or list-vs-tuple. Keys
    absent from the echo are compared as their canonical absence (None / []); an outright wrong echo
    simply fails the equality and is treated as stale, which is the fail-closed outcome."""
    fp = fp or {}
    return {
        "policy_id": fp.get("policy_id"),
        "policy_generation": fp.get("policy_generation"),
        "baseline_policy_id": fp.get("baseline_policy_id"),
        "baseline_generation": fp.get("baseline_generation"),
        "methodology_version": fp.get("methodology_version"),
        "workflow_version": fp.get("workflow_version"),
        "expected_slots": fp.get("expected_slots"),
        "eligible_version_ids": list(fp.get("eligible_version_ids") or []),
    }


def recommendation_fingerprint(result):
    """The governed-generation identity a recommendation was computed under. Two recommendations with
    the SAME fingerprint are byte-identical, because the apportionment is deterministic — so this is
    exactly what a preview and a submit compare to decide whether the world moved between them. The
    recommended mix is deliberately NOT part of it: the operator amends the mix on purpose, and an
    amendment is not drift. What must not silently change is the policy/baseline/methodology/workflow
    generation and the eligible set the numbers were derived from."""
    return {
        "policy_id": result["policy"]["policy_id"],
        "policy_generation": result["policy"]["generation"],
        "baseline_policy_id": result["baseline_policy"]["policy_id"],
        "baseline_generation": result["baseline_policy"]["generation"],
        "methodology_version": result["methodology_version"],
        "workflow_version": result["workflow_version"],
        "expected_slots": result["expected_slots"],
        "eligible_version_ids": list(result["eligible_version_ids"]),
    }


def preview_recommendation(conn, *, starts_on, ends_on, posts_per_day, principal,
                           scope="default", tenant_id="default", module="content"):
    """#376 ruling — the SIDE-EFFECT-FREE recommendation preview. It is `recommend()` and nothing more:
    a pure read (SELECTs only), it INSERTs no proposal, writes NO audit/history, reserves NO identifier
    and commits nothing. GPT amendment 4 forbids any durable side effect before the operator explicitly
    plans the run, so the preview the composer shows must not be a proposal — it is only a calculation.

    It carries a `preview_fingerprint` so the eventual submit can prove the governed generations have not
    moved since the operator saw these numbers. No proposal exists yet; one is minted only by an explicit
    Plan run, gated on this fingerprint still being current (see create_proposal's `expected`)."""
    result = recommend(conn, starts_on=starts_on, ends_on=ends_on, posts_per_day=posts_per_day,
                       principal=principal, scope=scope, tenant_id=tenant_id, module=module)
    if result["status"] != "recommended":
        return result
    result = dict(result)
    result["preview"] = True
    result["preview_fingerprint"] = recommendation_fingerprint(result)
    # A preview is NOT a proposal: it has no id, no digest-of-a-row, and no expiry, and it must never be
    # mistaken for one. Those fields are added only by create_proposal, on explicit submit.
    return result


def create_proposal(conn, *, starts_on, ends_on, posts_per_day, principal, ttl_seconds=None,
                    expected=None, scope="default", tenant_id="default", module="content"):
    """Recommend, and — only when the result is a valid recommendation — persist the durable fence.

    This is the FIRST durable act, and it happens only on an explicit Plan run (GPT amendment 4): a
    persisted proposal is a reserved identifier + an audit row, so nothing calls this at preview time.

    `expected` (#376 ruling) is the fingerprint the operator's preview was computed under. When it is
    supplied and the CURRENT governed generations no longer match it — a policy/baseline/methodology/
    workflow activation happened between preview and submit — this FAILS CLOSED with a typed
    `recommendation_stale` and inserts NOTHING: the operator must review the refreshed recommendation
    rather than have a run silently created against numbers they never saw. The check runs BEFORE the
    insert, so a stale submit leaves no trace.

    A blocked result persists NOTHING: there is no proposal to consume, so durable submission is
    impossible by construction rather than by a UI promise. A persisted proposal is not a run: no
    slots, no gates, no history, no workflow. It expires."""
    result = recommend(conn, starts_on=starts_on, ends_on=ends_on, posts_per_day=posts_per_day,
                       principal=principal, scope=scope, tenant_id=tenant_id, module=module)
    if result["status"] != "recommended":
        return result

    if expected is not None:
        current_fp = recommendation_fingerprint(result)
        if canonical_json(current_fp) != canonical_json(_normalize_fingerprint(expected)):
            raise RecommendationError(
                "recommendation_stale",
                "the governed policy or configuration changed after this recommendation was previewed; "
                "review the refreshed recommendation before planning the run",
                status=409,
                detail={"previewed": _normalize_fingerprint(expected), "current": current_fp,
                        "refreshed": {k: result[k] for k in (
                            "recommended_mix", "rationale", "expected_slots", "eligible_version_ids",
                            "policy", "baseline_policy", "methodology_version", "workflow_version")}})

    ttl = int(ttl_seconds or DEFAULT_TTL_SECONDS)
    if ttl < 60 or ttl > MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 60 and {MAX_TTL_SECONDS}")

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # The timestamps come from the DATABASE clock and are resolved BEFORE the insert, so the digest
        # covers exactly the values that get stored and the row is digest-correct from birth. Writing
        # the digest afterwards would need an UPDATE, which the freeze trigger rightly refuses.
        cur.execute("SELECT now() AS created_at, now() + (%s || ' seconds')::interval AS expires_at",
                    (str(ttl),))
        clock = cur.fetchone()
        digest = digest_of(proposal_digest_payload(
            scope=scope, tenant_id=tenant_id, module=module, created_by=principal,
            starts_on=result["starts_on"], ends_on=result["ends_on"],
            posts_per_day=result["posts_per_day"], expected_slots=result["expected_slots"],
            eligible_version_ids=result["eligible_version_ids"],
            recommended_mix=result["recommended_mix"], rationale=result["rationale"],
            authority_version=AUTHORITY_VERSION, algorithm=ALGORITHM,
            policy_id=result["policy"]["policy_id"], policy_generation=result["policy"]["generation"],
            baseline_policy_id=result["baseline_policy"]["policy_id"],
            baseline_generation=result["baseline_policy"]["generation"],
            methodology_version=result["methodology_version"],
            workflow_version=result["workflow_version"], model_posture="not_applicable",
            requested_route=None, requested_provider=None, requested_model=None,
            effective_route=None, effective_provider=None, effective_model=None,
            created_at=clock["created_at"], expires_at=clock["expires_at"]))
        # The digest is SERVER-generated (amendment 6: no unsigned client digest) and inserted with the
        # row it describes.
        cur.execute("""INSERT INTO run_mix_proposal
                       (digest_version, digest, scope, tenant_id, module, created_by, starts_on,
                        ends_on, posts_per_day, expected_slots, eligible_version_ids, recommended_mix,
                        rationale, authority_version, algorithm, policy_id, policy_generation,
                        baseline_policy_id, baseline_generation, methodology_version, workflow_version,
                        model_posture, created_at, expires_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               'not_applicable',%s,%s)
                       RETURNING proposal_id::text AS proposal_id, created_at, expires_at""",
                    (CANONICAL_DIGEST_VERSION, digest, scope, tenant_id, module, principal,
                     result["starts_on"], result["ends_on"], result["posts_per_day"],
                     result["expected_slots"], psycopg2.extras.Json(result["eligible_version_ids"]),
                     psycopg2.extras.Json(result["recommended_mix"]),
                     psycopg2.extras.Json(result["rationale"]), AUTHORITY_VERSION, ALGORITHM,
                     result["policy"]["policy_id"], result["policy"]["generation"],
                     result["baseline_policy"]["policy_id"], result["baseline_policy"]["generation"],
                     result["methodology_version"], result["workflow_version"],
                     clock["created_at"], clock["expires_at"]))
        row = cur.fetchone()
        engine._audit(cur, "run_mix_proposal", row["proposal_id"], "run_mix_proposal_created", principal,
                      {"expected_slots": result["expected_slots"],
                       "policy_generation": result["policy"]["generation"],
                       "model_posture": "not_applicable"})
        conn.commit()
        result = dict(result)
        result.update({"proposal_id": row["proposal_id"], "digest": digest,
                       "digest_version": CANONICAL_DIGEST_VERSION,
                       "created_at": _as_iso(row["created_at"]),
                       "expires_at": _as_iso(row["expires_at"])})
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def read_proposal(conn, proposal_id, principal, scope="default", tenant_id="default", module="content"):
    """Owner-and-scope-checked read. A guessed id, a foreign proposal, or a cross-scope read is the
    SAME typed denial as a nonexistent one (amendment 8): possession of an identifier confers no
    authority and the response discloses nothing extra."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        row = _select_proposal(cur, proposal_id)
        if not row or row["created_by"] != principal or row["scope"] != scope \
           or row["tenant_id"] != tenant_id or row["module"] != module:
            raise RecommendationError("proposal_not_found",
                                      "no such proposal for this principal and scope", status=404)
        return _proposal_view(row)
    finally:
        cur.close()


def _canonical_proposal_id(proposal_id):
    """Validate the identifier shape in PYTHON. Letting Postgres reject a malformed uuid would abort the
    surrounding transaction — and this runs inside the planner's run-creating transaction. A malformed
    id is indistinguishable from a wrong one, by design (amendment 8)."""
    try:
        return str(_uuid.UUID(str(proposal_id)))
    except (TypeError, ValueError, AttributeError):
        raise RecommendationError("proposal_not_found", "no such proposal for this principal and scope",
                                  status=404)


def _select_proposal(cur, proposal_id, for_update=False):
    canonical_id = _canonical_proposal_id(proposal_id)
    cur.execute("""SELECT proposal_id::text AS proposal_id, status, digest_version, digest, scope,
                              tenant_id, module, created_by, starts_on, ends_on, posts_per_day,
                              expected_slots, eligible_version_ids, recommended_mix, rationale,
                              authority_version, algorithm, policy_id::text AS policy_id,
                              policy_generation, baseline_policy_id::text AS baseline_policy_id,
                              baseline_generation, methodology_version, workflow_version,
                              model_posture, requested_route, requested_provider, requested_model,
                              effective_route, effective_provider, effective_model, created_at,
                              expires_at, consumed_at, bound_round_id
                   FROM run_mix_proposal WHERE proposal_id=%s""" + (" FOR UPDATE" if for_update else ""),
                (canonical_id,))
    return cur.fetchone()


def _proposal_view(row):
    return {
        "status": "recommended" if row["status"] == "pending" else "consumed",
        "proposal_id": row["proposal_id"], "digest": row["digest"],
        "digest_version": row["digest_version"],
        "starts_on": _as_date_str(row["starts_on"]), "ends_on": _as_date_str(row["ends_on"]),
        "posts_per_day": row["posts_per_day"], "expected_slots": row["expected_slots"],
        "eligible_version_ids": row["eligible_version_ids"],
        "recommended_mix": row["recommended_mix"], "rationale": row["rationale"],
        "authority_version": row["authority_version"], "algorithm": row["algorithm"],
        "model_posture": row["model_posture"],
        "policy": {"policy_id": row["policy_id"], "generation": row["policy_generation"]},
        "baseline_policy": {"policy_id": row["baseline_policy_id"],
                            "generation": row["baseline_generation"]},
        "methodology_version": row["methodology_version"],
        "workflow_version": row["workflow_version"],
        "created_at": _as_iso(row["created_at"]), "expires_at": _as_iso(row["expires_at"]),
        "consumed_at": _as_iso(row["consumed_at"]), "bound_round_id": row["bound_round_id"],
    }


def purge_expired_proposals(conn, actor="system", scope="default", tenant_id="default", module="content"):
    """Bounded retention for abandoned proposals (amendment 9). Only PENDING expired rows are removed —
    a consumed proposal is immutable evidence bound to a run and is never deleted here. This repo has
    no scheduler, so retention is enforced by an authorized operator call plus the expiry check every
    consume already performs; nothing silently resurrects an expired fence."""
    if not engine.can_administer_approval_policies(conn, actor):
        raise RecommendationError("not_authorized", f"{actor!r} may not purge proposals", status=403)
    cur = conn.cursor()
    try:
        cur.execute("""DELETE FROM run_mix_proposal
                       WHERE status='pending' AND expires_at <= now()
                         AND scope=%s AND tenant_id=%s AND module=%s""",
                    (scope, tenant_id, module))
        removed = cur.rowcount
        conn.commit()
        return {"purged": removed}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------------------------
# Binding: consume the fence and pin the snapshot INSIDE the run-creating transaction
# ---------------------------------------------------------------------------------------------
def begin_binding(cur, *, proposal_id, principal, days, posts_per_day, starts_on, format_mix, label,
                  scope="default", tenant_id="default", module="content", idempotency_key=None):
    """Phase 1, inside the planner's transaction and BEFORE any durable run state exists.

    Returns ("replay", {round_id, ...}) when this exact request already produced a run, or
    ("proceed", proposal_row, request_digest) when the fence is valid and locked for this transaction.
    Every refusal is a typed RecommendationError and leaves no partial state, because nothing has been
    written yet when it raises."""
    proposal_id = _canonical_proposal_id(proposal_id)
    req_digest = request_digest_of(proposal_id=proposal_id, days=days, posts_per_day=posts_per_day,
                                   starts_on=starts_on, format_mix=format_mix, label=label,
                                   principal=principal)
    if idempotency_key:
        # Canonical idempotency (amendment 10): the snapshot row IS the record of what a key produced,
        # so convergence and conflict are decided by durable evidence rather than by an in-memory cache.
        cur.execute("""SELECT round_id, request_digest FROM run_mix_recommendation_snapshot
                       WHERE proposal_id=%s AND idempotency_key=%s""",
                    (str(proposal_id), idempotency_key))
        prior = cur.fetchone()
        if prior:
            prior_digest = prior["request_digest"] if isinstance(prior, dict) else prior[1]
            prior_round = prior["round_id"] if isinstance(prior, dict) else prior[0]
            if prior_digest != req_digest:
                raise RecommendationError(
                    "idempotency_key_conflict",
                    "this idempotency key was already used with a different request payload",
                    status=409, detail={"bound_round_id": prior_round})
            return ("replay", {"round_id": prior_round}, req_digest)

    row = _select_proposal(cur, proposal_id, for_update=True)
    if not row or row["created_by"] != principal or row["scope"] != scope \
       or row["tenant_id"] != tenant_id or row["module"] != module:
        raise RecommendationError("proposal_not_found",
                                  "no such proposal for this principal and scope", status=404)
    if row["status"] == "consumed":
        raise RecommendationError("proposal_already_consumed",
                                  "this proposal has already created a run", status=409,
                                  detail={"bound_round_id": row["bound_round_id"]})

    cur.execute("SELECT now() > %s AS expired", (row["expires_at"],))
    expired = cur.fetchone()
    expired = expired["expired"] if isinstance(expired, dict) else expired[0]
    if expired:
        raise RecommendationError("proposal_expired",
                                  "this proposal has expired; request a fresh recommendation",
                                  status=409, detail={"expires_at": _as_iso(row["expires_at"])})

    # The stored context must still hash to the stored digest. This is what makes a direct row edit —
    # or any future code path that tried to rewrite a proposal — detectable rather than merely
    # discouraged, and it is the "altered digest" red proof's hook.
    recomputed = digest_of(proposal_digest_payload(
        scope=row["scope"], tenant_id=row["tenant_id"], module=row["module"],
        created_by=row["created_by"], starts_on=row["starts_on"], ends_on=row["ends_on"],
        posts_per_day=row["posts_per_day"], expected_slots=row["expected_slots"],
        eligible_version_ids=row["eligible_version_ids"], recommended_mix=row["recommended_mix"],
        rationale=row["rationale"], authority_version=row["authority_version"],
        algorithm=row["algorithm"], policy_id=row["policy_id"],
        policy_generation=row["policy_generation"], baseline_policy_id=row["baseline_policy_id"],
        baseline_generation=row["baseline_generation"], methodology_version=row["methodology_version"],
        workflow_version=row["workflow_version"], model_posture=row["model_posture"],
        requested_route=row["requested_route"], requested_provider=row["requested_provider"],
        requested_model=row["requested_model"], effective_route=row["effective_route"],
        effective_provider=row["effective_provider"], effective_model=row["effective_model"],
        created_at=row["created_at"], expires_at=row["expires_at"]))
    if recomputed != row["digest"]:
        raise RecommendationError("proposal_digest_mismatch",
                                  "the proposal's stored context no longer matches its canonical "
                                  "digest", status=409)

    # The submitted run must be the run that was proposed.
    if int(posts_per_day) != int(row["posts_per_day"]):
        raise RecommendationError("proposal_context_mismatch",
                                  "posts_per_day differs from the proposal", status=409,
                                  detail={"proposed": row["posts_per_day"], "submitted": int(posts_per_day)})
    proposed_days = (row["ends_on"] - row["starts_on"]).days + 1
    if int(days) != proposed_days:
        raise RecommendationError("proposal_context_mismatch",
                                  "the run duration differs from the proposal's inclusive range",
                                  status=409, detail={"proposed_days": proposed_days, "submitted_days": int(days)})
    if _as_date_str(starts_on) != _as_date_str(row["starts_on"]):
        raise RecommendationError("proposal_context_mismatch",
                                  "starts_on differs from the proposal", status=409,
                                  detail={"proposed": _as_date_str(row["starts_on"]),
                                          "submitted": _as_date_str(starts_on)})
    if int(days) * int(posts_per_day) != int(row["expected_slots"]):
        raise RecommendationError("proposal_context_mismatch",
                                  "the submitted slot total differs from the proposal", status=409,
                                  detail={"proposed": row["expected_slots"],
                                          "submitted": int(days) * int(posts_per_day)})
    return ("proceed", row, req_digest)


def verify_generations(cur, row, elig, scope="default", tenant_id="default", module="content"):
    """Phase 2, still inside the transaction: the governed generations the proposal was computed under
    must still be the current ones. A policy activation, a baseline change, or a methodology/workflow
    activation between preview and submit is a real conflict — the operator must see the newly resolved
    plan rather than have a stale proposal silently create a run."""
    policy = current_policy(cur, scope, tenant_id, module)
    if not policy:
        raise RecommendationError("recommendation_policy_unavailable",
                                  "no current run-mix recommendation policy generation", status=409)
    if policy["policy_id"] != row["policy_id"] or policy["generation"] != row["policy_generation"]:
        raise RecommendationError("recommendation_policy_superseded",
                                  "the recommendation policy generation changed since this proposal",
                                  status=409,
                                  detail={"proposed_generation": row["policy_generation"],
                                          "current_generation": policy["generation"]})
    if elig["policy"]["policy_id"] != row["baseline_policy_id"] \
       or elig["policy"]["generation"] != row["baseline_generation"]:
        raise RecommendationError("baseline_policy_superseded",
                                  "the baseline eligibility generation changed since this proposal",
                                  status=409,
                                  detail={"proposed_generation": row["baseline_generation"],
                                          "current_generation": elig["policy"]["generation"]})
    current_ids = [e["version_id"] for e in elig["eligible"]]
    if list(row["eligible_version_ids"] or []) != current_ids:
        raise RecommendationError("eligible_set_changed",
                                  "the baseline-eligible framework set changed since this proposal",
                                  status=409)
    mv = engine._active_version_id(cur, "methodology_version", "methodology_id")
    wv = engine._active_version_id(cur, "workflow_version", "workflow_id")
    if mv != row["methodology_version"] or wv != row["workflow_version"]:
        raise RecommendationError("configuration_generation_changed",
                                  "the active methodology/workflow generation changed since this "
                                  "proposal", status=409)


def bind_snapshot(cur, *, row, round_id, submitted_mix, principal, request_digest,
                  idempotency_key=None):
    """Phase 3: pin the immutable recommendation snapshot and consume the fence, in the SAME
    transaction that just created the run. If anything after this raises, the planner rolls back and
    neither the run nor this evidence exists — there is no window in which a proposal is consumed
    without a run, or a run exists with a half-written recommendation."""
    recommended = {k: int(v) for k, v in (row["recommended_mix"] or {}).items()}
    submitted = {k: int(v) for k, v in (submitted_mix or {}).items()}
    keys = sorted(set(recommended) | set(submitted))
    delta = {k: submitted.get(k, 0) - recommended.get(k, 0)
             for k in keys if submitted.get(k, 0) != recommended.get(k, 0)}
    cur.execute("""INSERT INTO run_mix_recommendation_snapshot
                   (round_id, proposal_id, digest_version, proposal_digest, authority_version,
                    algorithm, policy_id, policy_generation, baseline_policy_id, baseline_generation,
                    methodology_version, workflow_version, starts_on, ends_on, posts_per_day,
                    expected_slots, eligible_version_ids, recommended_mix, submitted_mix, mix_amended,
                    mix_delta, rationale, model_posture, requested_route, requested_provider,
                    requested_model, effective_route, effective_provider, effective_model,
                    initiating_principal, effective_principal, scope, tenant_id, module,
                    idempotency_key, request_digest)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (round_id, row["proposal_id"], row["digest_version"], row["digest"],
                 row["authority_version"], row["algorithm"], row["policy_id"], row["policy_generation"],
                 row["baseline_policy_id"], row["baseline_generation"], row["methodology_version"],
                 row["workflow_version"], row["starts_on"], row["ends_on"], row["posts_per_day"],
                 row["expected_slots"], psycopg2.extras.Json(row["eligible_version_ids"]),
                 psycopg2.extras.Json(recommended), psycopg2.extras.Json(submitted),
                 bool(delta), psycopg2.extras.Json(delta), psycopg2.extras.Json(row["rationale"]),
                 row["model_posture"], row["requested_route"], row["requested_provider"],
                 row["requested_model"], row["effective_route"], row["effective_provider"],
                 row["effective_model"], row["created_by"], principal, row["scope"], row["tenant_id"],
                 row["module"], idempotency_key, request_digest))
    cur.execute("""UPDATE run_mix_proposal
                   SET status='consumed', consumed_at=now(), bound_round_id=%s
                   WHERE proposal_id=%s AND status='pending'""",
                (round_id, row["proposal_id"]))
    if cur.rowcount != 1:
        # Unreachable while the row is locked FOR UPDATE by this transaction; kept because a silent
        # zero-row update here would be a proposal consumed by someone else while we created a run.
        raise RecommendationError("proposal_already_consumed",
                                  "this proposal was consumed concurrently", status=409)
    engine._audit(cur, "run_mix_proposal", row["proposal_id"], "run_mix_proposal_consumed", principal,
                  {"round_id": round_id, "mix_amended": bool(delta)})


def round_recommendation(conn, round_id):
    """The historical read. Resolves ONLY from the pinned snapshot and never recomputes: activating a
    different policy/methodology generation afterwards cannot change a field of it. A run planned
    before #377 — or through the proposal-less legacy path — truthfully has none."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT round_id, proposal_id::text AS proposal_id, digest_version,
                              proposal_digest, authority_version, algorithm, policy_id::text AS policy_id,
                              policy_generation, baseline_policy_id::text AS baseline_policy_id,
                              baseline_generation, methodology_version, workflow_version, starts_on,
                              ends_on, posts_per_day, expected_slots, eligible_version_ids,
                              recommended_mix, submitted_mix, mix_amended, mix_delta, rationale,
                              model_posture, requested_route, requested_provider, requested_model,
                              effective_route, effective_provider, effective_model,
                              initiating_principal, effective_principal, scope, tenant_id, module,
                              created_at
                       FROM run_mix_recommendation_snapshot WHERE round_id=%s""", (round_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT 1 FROM round WHERE round_id=%s", (round_id,))
            if not cur.fetchone():
                raise RecommendationError("round_not_found", f"no such run {round_id!r}", status=404)
            return {"status": "unknown", "round_id": round_id,
                    "detail": "This run was created without a governed recommendation proposal, so no "
                              "recommendation was made. Nothing is inferred for it."}
        out = dict(row)
        out["status"] = "recorded"
        out["starts_on"] = _as_date_str(row["starts_on"])
        out["ends_on"] = _as_date_str(row["ends_on"])
        out["created_at"] = _as_iso(row["created_at"])
        return out
    finally:
        cur.close()
