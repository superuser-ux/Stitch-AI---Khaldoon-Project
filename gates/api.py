"""Gate API (M4) — HTTP wrapper over engine.py for the Next.js dashboard.

Sync endpoints (FastAPI runs them in a threadpool); all logic stays in engine.py.

  docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
    -p 8000:8000 -v "$PWD":/work -w /work python:3.12-slim \
    bash -lc "pip install -q -r gates/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000"
"""
import datetime
import os
import sys
import threading
import time
import hashlib
import hmac

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt

# #367 — the closed artifact domain for the per-item Script/Topic actions. A value
# outside this set is rejected by FastAPI as a typed 422 at request parsing, BEFORE the
# handler runs, so an invalid artifact can never reach contract._artifact (which would
# raise an unhandled ValueError). Absent -> defaults "topic" (V1 compatibility).
ScriptArtifact = Literal["topic", "script"]

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # repo root, for integrations/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))  # for run_writers (rework trigger)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "planner"))  # for plan_round (UI run config)
import engine  # noqa: E402
import contract  # noqa: E402  (#313 — governed gate decisions: approve records, request_change sends back)
import provenance  # noqa: E402  (#72 M7 — run-scoped provenance graph read model)
import publication  # noqa: E402  (#200 pub.v1 — first-class manual publication recording)
import jobs  # noqa: E402  (in-process generation-job registry)
import directives  # noqa: E402  (M9·B1 stage contract + directive chain)
import stage4_preflight  # noqa: E402  (#419 — read-only Stage 4 approval-package preflight)
import final_review_target_package  # noqa: E402  (#423 — immutable final-review target-package read)
import final_review_projection  # noqa: E402  (#427 — additive final-review backend read projection)
import final_review_preflight  # noqa: E402  (#447 — read-only Stage 4 approval-package preflight)
import dam  # noqa: E402  (M9·B2 minimal DAM — manual-stage assets)
import sdam  # noqa: E402  (#244 SDAM read-only binding/readiness read model)
import settings_truth  # noqa: E402  (#443 read-only Settings-truth provider/model/route projection)
from integrations import contracts as integ  # noqa: E402  (M9·B2 declared integration seams)
import i18n  # noqa: E402  (shared glossary + copy catalog, served to the dashboard)
try:
    import run_writers  # noqa: E402  (M9 loop-close: the rework trigger runs the writer)
except Exception:       # noqa: BLE001 — provider deps optional; the trigger 503s if unavailable
    run_writers = None
try:
    import plan_round  # noqa: E402  (parametric run planning — POST /rounds)
except Exception:      # noqa: BLE001
    plan_round = None
try:
    import run_mix  # noqa: E402  (#377 — governed run-mix recommendation authority + proposal fence)
except Exception:   # noqa: BLE001 — imports the planner; the endpoints 503 if it is unavailable
    run_mix = None
try:
    import agent as agent_mod  # noqa: E402  (conversational agent — shared runtime for dashboard + bot)
except Exception:             # noqa: BLE001 — optional deps; the endpoint 503s if unavailable
    agent_mod = None

app = FastAPI(title="Tanaghom Gates API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.environ.get("DASHBOARD_ORIGINS") or "http://localhost:3000").split(","),
    allow_methods=["*"], allow_headers=["*"],
)


# #362 correction E / J10 — shutdown state for the ONE shared recovery owner.
_RECOVERY_SHUTDOWN = threading.Event()
_RECOVERY_THREAD = None


@app.on_event("startup")
def _start_topic_generation_recovery():
    """#310 §A — BOUNDED PERIODIC CRASH RECOVERY. A daemon loop drains Topic-generation jobs left
    QUEUED (a crash between the acceptance commit and the post-commit handoff) or stranded 'running'
    with an EXPIRED lease (a worker that died mid-run). It is PERIODIC, not one-shot: on an immediate
    restart the dead worker's lease is still fresh, so the first pass correctly skips it; a later pass
    reclaims it automatically once the lease expires — with NO further gate action. The runner's atomic
    lease-claim keeps this safe alongside the live post-commit path (no double run, never steals an
    actively-heartbeating run). Best-effort; never crashes startup. Poll interval is configurable so a
    healthy service reclaims a crashed job within roughly (lease + poll)."""
    if run_writers is None:
        return
    poll = float(os.environ.get("TANAGHOM_TOPICGEN_RECOVERY_SECONDS", "60"))

    def _loop():
        # #362 correction E / J10 — the loop CONDITION is the shutdown flag. An interruptible wait
        # alone was not enough and was in fact worse than a sleep: once the event is set, `wait`
        # returns immediately every time, so a `while True` loop stops idling and starts spinning the
        # drains as fast as the CPU allows, forever. The exit test has to be the loop itself.
        while not _RECOVERY_SHUTDOWN.is_set():
            try:
                run_writers.dispatch_pending_topic_generation(engine.load_config())
            except Exception as e:                    # noqa: BLE001 — recovery is best-effort
                print(f"[recovery] topic-generation drain skipped: {e}")
            # #362 — the bounded Script drain is the THIRD pass on this ONE shared recovery owner
            # (the rework drain was the second, #321 R6). Its own best-effort try, so a Script
            # failure can never stop the Topic or rework passes — and it is bounded per pass, so a
            # Script backlog cannot monopolise a cycle.
            if _RECOVERY_SHUTDOWN.is_set():
                break                                 # checked BEFORE each pass, not only per cycle
            try:
                run_writers.dispatch_pending_script_generation(engine.load_config())
            except Exception as e:                    # noqa: BLE001 — recovery is best-effort
                print(f"[recovery] script-generation drain skipped: {e}")
            # #321 R6 — the bounded periodic rework drain shares this ONE existing recovery owner. Each
            # pass is a separate best-effort try so a rework-drain failure never stops the topicgen drain
            # (or vice versa). Claim/drive only; no terminalization path. Disabled by
            # TANAGHOM_REWORK_RECOVERY_DISABLED so a deterministic proof run can drive rework ops itself
            # without a background daemon racing it (the drain FUNCTION is proven directly, in-process).
            if _RECOVERY_SHUTDOWN.is_set():
                break
            if not os.environ.get("TANAGHOM_REWORK_RECOVERY_DISABLED"):
                try:
                    _periodic_rework_recovery(engine.load_config())
                except Exception as e:                # noqa: BLE001 — recovery is best-effort
                    print(f"[recovery] rework drain skipped: {e}")
            # Interruptible idle: a bare `time.sleep` made shutdown wait out a full poll interval
            # (default 60s). `wait` returns the instant shutdown is signalled — and because the loop
            # condition above tests the same flag, returning early exits rather than spins.
            if _RECOVERY_SHUTDOWN.wait(poll):
                break
        print("[recovery] recovery owner stopped — all passes ended, nothing terminalized")

    global _RECOVERY_THREAD
    _RECOVERY_SHUTDOWN.clear()
    if run_writers is not None:
        run_writers.reset_script_drain_shutdown()
    _RECOVERY_THREAD = threading.Thread(target=_loop, daemon=True)
    _RECOVERY_THREAD.start()


def begin_recovery_shutdown(timeout=None):
    """#362 correction E / J10 — the shutdown boundary for the shared recovery owner.

    Ordering is the whole point. The Script drain's *stop-before-claim* flag is raised FIRST, so from
    this instant no new Script tenure can be taken no matter where the loop currently is; only then is
    the loop itself asked to exit and the wait interrupted.

    What this deliberately does NOT do:
      * It does not interrupt or terminalize work already running. A Script job in flight keeps its
        lease and finishes, or — if the process dies first — has its lease EXPIRE and is reclaimed
        through the normal fenced path. Marking in-flight work failed on the way out would record a
        terminal outcome nobody actually observed.
      * It does not release ownership. Force-clearing a lease while this process might still commit
        would hand a live tenure to a second worker.
      * It does not wait unboundedly. The join is bounded, so a slow Script job cannot hold shutdown
        open, and — because the drains are separate passes on this one loop — a Script drain that is
        still finishing never blocks the Topic or rework passes from having completed their own.

    Returns True if the loop thread exited within the bound, False if it is still finishing (a
    truthful "still running", not a silent success). Safe to call when no loop was ever started.
    """
    if run_writers is not None:
        run_writers.begin_script_drain_shutdown()   # stop-before-claim, raised first
    _RECOVERY_SHUTDOWN.set()
    t = _RECOVERY_THREAD
    if t is None or not t.is_alive():
        return True
    bound = float(os.environ.get("TANAGHOM_RECOVERY_SHUTDOWN_SECONDS", "30")
                  if timeout is None else timeout)
    t.join(bound)
    return not t.is_alive()


@app.on_event("shutdown")
def _stop_recovery_owner():
    """#362 — bind the shutdown boundary to the process lifecycle.

    Without this the boundary would exist but never fire: `begin_recovery_shutdown` is only meaningful
    if something calls it when the service actually stops. Best-effort by design — a failure here must
    never turn a clean shutdown into a crash — but a bounded wait that does not complete is REPORTED,
    not swallowed silently."""
    try:
        if not begin_recovery_shutdown():
            print("[recovery] shutdown bound elapsed with the recovery loop still finishing "
                  "— in-flight work left to its lease, nothing terminalized")
    except Exception as e:                            # noqa: BLE001 — shutdown must not crash
        print(f"[recovery] shutdown signal skipped: {e}")


def _conn():
    return engine.db_connect()


# #147 (#146 S1) / #387 — the reviewer proxy secret must never fall back to a public constant in a
# production/demo runtime. The dev fallback is used ONLY under an explicit TANAGHOM_DEV_MODE opt-in
# (deterministic local/test), never on accidental env omission or as a fallback for an invalid FILE.
# The resolution logic (env + manager-neutral FILE seam, fail-closed) lives in reviewer_secret.py; the
# dashboard/workbench TS resolvers mirror it exactly so every side fails closed consistently.
import reviewer_secret  # noqa: E402  (#387 manager-neutral reviewer-proxy secret resolver)
from agents import runtime_secret  # noqa: E402

_DEV_REVIEWER_SECRET = reviewer_secret.DEV_REVIEWER_SECRET   # local/dev/test ONLY, gated in the resolver


def _dev_mode():
    return reviewer_secret.dev_mode()


def _reviewer_secret_configured():
    # resolved-source validity (env OR a valid FILE); the dev fixture and any invalid/missing FILE are
    # NOT reported configured. Boolean only — never the value or its source-dependent content.
    return reviewer_secret.status()[0]


def _reviewer_secret_source():
    # non-secret source-kind metadata for /health ("file"/"env"/"dev"/None) — never the value.
    return reviewer_secret.status()[1]


def _runtime_secret_metadata(name, status_fn):
    """Return bounded runtime metadata without exposing a path, value, digest, or error text.

    A declared FILE remains visible as a file source even when it is stale or temporarily missing;
    otherwise the admin surface would hide the distinction between "not configured" and "materializer
    needs attention". Validation itself stays with the existing resolver and remains fail closed.
    """
    file_var = f"{name}_FILE"
    age_var = f"{name}_FILE_MAX_AGE_SECONDS"
    path = (os.environ.get(file_var) or "").strip()
    env_value = (os.environ.get(name) or "").strip()
    configured, resolved_source = status_fn()
    declared_source = "file" if path and not env_value else "env" if env_value and not path else None
    result = {
        "configured": configured,
        "source": resolved_source or declared_source,
        "fresh": configured,
        "age_seconds": None,
        "max_age_seconds": None,
    }
    if not path:
        return result
    try:
        max_age = int((os.environ.get(age_var) or "").strip())
        stat_result = os.stat(path, follow_symlinks=False)
        age = max(0, int(time.time() - stat_result.st_mtime))
        result.update({
            "age_seconds": age,
            "max_age_seconds": max_age if max_age > 0 else None,
            "fresh": configured and max_age > 0 and age <= max_age,
        })
    except (OSError, TypeError, ValueError):
        result["fresh"] = False
    return result


def _proxy_secret():
    try:
        return reviewer_secret.resolve()[0]
    except reviewer_secret.SecretError as e:
        # fail closed — refuse to authenticate outside a validly configured source or explicit dev/test.
        raise HTTPException(500, str(e) + ". Set REVIEWER_PROXY_SECRET (or REVIEWER_PROXY_SECRET_FILE) "
                                         "for demo/production, or set TANAGHOM_DEV_MODE=1 for local/dev/test.")


def _trusted_principal(request: Request):
    principal = (request.headers.get("x-principal-id") or "").strip()
    signature = (request.headers.get("x-principal-signature") or "").strip()
    if not principal and not signature:
        return None
    if not principal or not signature:
        raise HTTPException(401, "incomplete principal proxy headers")
    expect = hmac.new(_proxy_secret().encode("utf-8"), principal.encode("utf-8"),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expect):
        raise HTTPException(401, "invalid principal proxy signature")
    return principal


def _require_trusted_principal(request: Request):
    principal = _trusted_principal(request)
    if not principal:
        raise HTTPException(401, "trusted principal required")
    return principal


def _trusted_actor(request: Request, explicit: str | None = None):
    principal = _require_trusted_principal(request)
    if explicit and explicit != principal:
        raise HTTPException(400, f"actor mismatch: body={explicit!r} header={principal!r}")
    return principal


def _trusted_approval_actor(request: Request, explicit: str | None, conn, gate_id):
    """#10 — `_trusted_actor` for APPROVAL endpoints (decide / undecide / resolve): identical
    resolution (the signed proxy principal is the only authority; a body actor may only echo it),
    but a REJECTED attempt — unsigned caller, or a body actor contradicting the signed principal
    (an approve-on-behalf/spoof attempt) — is audited before the 4xx propagates. The body value is
    kept in the audit detail as non-authoritative context only. See docs/approval-identity-pre-iam.md."""
    try:
        return _trusted_actor(request, explicit)
    except HTTPException as e:
        try:
            principal = _trusted_principal(request)
        except HTTPException:
            principal = None                      # missing/invalid signature -> anonymous denial
        engine.audit_denied(conn, "gate", gate_id, "approval_denied",
                            principal or "unsigned",
                            {"reason": "actor_mismatch" if principal else "unsigned",
                             "body_actor": explicit, "detail": str(e.detail)})
        raise


def _trusted_generation_actor(request: Request, explicit: str | None, conn, round_id):
    """#310 §F — `_trusted_actor` for the Stage 2A generation RETRY (a cost-bearing action): identical
    signed-principal resolution (the existing binding — no new IAM/capability seam), but a REJECTED
    attempt (unsigned caller, or a body actor contradicting the signed principal) is AUDITED before the
    4xx propagates. Mirrors _trusted_approval_actor so denials are traceable and attributed."""
    try:
        return _trusted_actor(request, explicit)
    except HTTPException as e:
        try:
            principal = _trusted_principal(request)
        except HTTPException:
            principal = None
        engine.audit_denied(conn, "round", round_id, "topic_generation_retry_denied",
                            principal or "unsigned",
                            {"reason": "actor_mismatch" if principal else "unsigned",
                             "body_actor": explicit, "detail": str(e.detail)})
        raise


class OpenBody(BaseModel):
    stage: str = "script_review"
    round_id: str | None = None
    slot_ids: list[str] | None = None
    actor: str | None = None


class DecideBody(BaseModel):
    approver_id: str | None = None
    decision: str
    slot_ids: list[str] | None = None       # null/empty = whole batch
    notes: str | None = None
    revision: int | None = None             # approve: WHICH revision (null = head/latest)


class ResolveBody(BaseModel):
    actor: str | None = None
    slot_ids: list[str] | None = None


class SignOffBody(BaseModel):
    """#439 — the exact final-review sign-off request: the four immutable-package binding fields plus
    the idempotency key, and NOTHING else. `extra='forbid'` rejects any unknown field (notably any
    actor/approver/principal/role/authority/outcome/lifecycle field) as a typed 422 at parse time;
    StrictInt rejects non-integer revisions; the handler additionally enforces canonical-lowercase UUID
    text and the trimmed idempotency-key bounds. Revision values are decimal JSON integers >= 1."""
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    topic_revision: StrictInt = Field(ge=1)
    script_revision: StrictInt = Field(ge=1)
    workflow_version_id: str
    idempotency_key: str


class DisposeBody(BaseModel):
    action: str                              # escalate | waive
    reason: str | None = None
    actor: str | None = None


class ApprovalPolicyBody(BaseModel):
    rule: str
    users: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)


class WorkflowTransitionBody(BaseModel):
    from_stage_key: str
    to_stage_key: str
    condition_key: str = "approve"
    enabled: bool = True


class WorkflowStageBody(BaseModel):
    stage_key: str
    stage_label: str | None = None
    stage_group: str | None = None
    enabled: bool = True
    bypassable: bool = False
    mandatory: bool = True
    gate_stage: str | None = None
    stage_kind: str | None = None
    generator_kind: str | None = None
    scope: str | None = None
    policy: str | None = None
    review_statuses: list[str] = Field(default_factory=list)
    approve_to: str | None = None
    changes_to: str | None = None
    reject_to: str | None = None
    rework_mode: str | None = None
    generates_from: str | None = None
    writer_mode: str | None = None
    requires_flag: str | None = None
    allow_partial_batch: bool = False
    enforce_mandatory_reviews: bool = False
    approval_rule: str | None = None


class WorkflowVersionBody(BaseModel):
    notes: str | None = None
    stages: list[WorkflowStageBody] = Field(default_factory=list)
    transitions: list[WorkflowTransitionBody] = Field(default_factory=list)


class MethodologyVersionBody(BaseModel):
    notes: str | None = None


class ContentFormatVersionBody(BaseModel):
    use_case: str | None = None
    lens_fit: list[str] = Field(default_factory=list)
    production_notes: str | None = None
    production_rules: dict = Field(default_factory=dict)
    platform_targets: list[str] = Field(default_factory=list)


class ContentFormatBody(BaseModel):
    format_key: str
    name: str
    description: str | None = None
    use_case: str | None = None
    lens_fit: list[str] = Field(default_factory=list)
    production_notes: str | None = None
    production_rules: dict = Field(default_factory=dict)
    platform_targets: list[str] = Field(default_factory=list)


class ContentFormatCatalogBody(BaseModel):
    format_key: str
    name: str
    description: str | None = None


class ContentFormatResetBody(BaseModel):
    confirm_reset: bool = False


def _json_safe(obj):
    """RealDictRow rows carry datetimes/uuids — let FastAPI's encoder handle them, but
    stringify uuid gate_id/keys explicitly so the dashboard gets stable strings."""
    return obj


@app.get("/i18n")
def i18n_catalog():
    """Glossary + UI copy (AR/EN) — the dashboard renders business-lexicon labels from this
    so the dev->user terms live in ONE place shared with the bot/CLI."""
    return i18n.catalog()


@app.get("/health")
def health():
    try:
        c = _conn(); c.cursor().execute("SELECT 1"); c.close()
        stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
        # #147/#387 — reviewer-secret config surfaced (boolean + source-kind only, never the secret) so
        # observe-only preflight can tell a fail-closed misconfig from a configured/dev runtime and see
        # which authorized source ("file"/"env"/"dev"/null) is active after a FILE cutover.
        openrouter_ok, openrouter_source = runtime_secret.status("OPENROUTER_API_KEY")
        groq_ok, groq_source = runtime_secret.status("GROQ_API_KEY")
        return {"ok": True, "writer_stub": stub, "writer_mode": "stub" if stub else "live",
                "provider_credentials": {
                    "openrouter": {"configured": openrouter_ok, "source": openrouter_source},
                    "groq": {"configured": groq_ok, "source": groq_source},
                },
                "reviewer_secret_configured": _reviewer_secret_configured(),
                "reviewer_secret_source": _reviewer_secret_source(), "dev_mode": _dev_mode(),
                "sdam_stub": _sdam_stub_enabled()}
    except Exception as e:                      # noqa: BLE001
        raise HTTPException(503, f"db unreachable: {e}")


@app.get("/admin/secrets/status")
def admin_secrets_status(request: Request):
    """Safe operational view of the manager-neutral secret boundary.

    OpenBao remains outside the application trust boundary. This endpoint reports only whether each
    materialized runtime input currently passes the existing resolver and, for FILE sources, bounded
    freshness metadata. It cannot read OpenBao, enumerate paths, return values, or rotate credentials.
    """
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        if not engine.can_administer_repetition_policy(c, principal):
            raise HTTPException(403, "secret operations status requires policy administration access")
        return {
            "manager": {
                "kind": "openbao_host_materializer",
                "application_connected": False,
                "values_exposed": False,
            },
            "secrets": {
                "reviewer_proxy": _runtime_secret_metadata(
                    "REVIEWER_PROXY_SECRET", reviewer_secret.status),
                "openrouter": _runtime_secret_metadata(
                    "OPENROUTER_API_KEY", lambda: runtime_secret.status("OPENROUTER_API_KEY")),
                "groq": _runtime_secret_metadata(
                    "GROQ_API_KEY", lambda: runtime_secret.status("GROQ_API_KEY")),
            },
        }
    finally:
        c.close()


@app.get("/stages")
def stages():
    """The stage contract (M9·B1): each stage's generator + consumes/emits directive + gate.
    Lets a surface render the pipeline as a graph of uniform stages."""
    return directives.stages(engine.load_config())


@app.get("/admin/settings/truth")
def admin_settings_truth(request: Request):
    """#443 — the read-only V2 Settings-truth projection: a bounded SAFE view over the EXISTING
    governed provider/model/route configuration authority (`system_config` via load_config). It
    creates no second authority and reads only allow-listed non-secret fields — provider kind, a safe
    endpoint identity (userinfo/query/fragment removed), model identity under existing route-role
    labels, presence/type-only secret references (never a name or value), and configured-state-only
    availability (anything stronger is unknown/fail-closed). Generation/provenance is omitted because
    the authority defines none. It resolves no secret, probes nothing, mutates nothing, and touches no
    DB. Guarded by the existing signed-principal boundary (read-only; no new IAM); the /gw route signs
    the workbench principal server-side in dev/test exactly as it does for the secrets-status read."""
    _require_trusted_principal(request)
    return settings_truth.project(engine.load_config())


# --- #244 SDAM read-only read model (binding identity + readiness current-state) ------------------
# Pure DB reads over the persisted binding + newest-observation evidence — no live ResourceSpace call
# and no mutation. The dual identities are returned distinct; the human slot_id is navigation-only.
@app.get("/sdam/bindings/{binding_id}")
def sdam_binding(binding_id: str, request: Request):
    _require_trusted_principal(request)   # read-only != unauthenticated: reuse the /gw signed boundary
    c = _conn()
    try:
        b = sdam.get_binding(c, binding_id)
        if not b:
            raise HTTPException(404, "binding not found")
        return {"binding_id": str(b["binding_id"]), "asset_id": str(b["asset_id"]),
                "asset_version": b["asset_version"], "slot_id": b["slot_id"],
                "provider_key": b["provider_key"], "external_ref": b["external_ref"],
                "mapping_version": b["mapping_version"]}
    finally:
        c.close()


@app.get("/sdam/bindings/{binding_id}/readiness")
def sdam_readiness(binding_id: str, request: Request):
    _require_trusted_principal(request)   # read-only != unauthenticated: reuse the /gw signed boundary
    c = _conn()
    try:
        if not sdam.get_binding(c, binding_id):
            raise HTTPException(404, "binding not found")
        st = sdam.current_state(c, binding_id)
        if not st:
            return {"binding_id": binding_id, "effective_state": None, "observed": False}
        return {"binding_id": binding_id, "effective_state": st["effective_state"],
                "observed_result": st["observed_result"], "retry_class": st["retry_class"],
                "observation_seq": st["observation_seq"],
                "observed_at": _json_safe(st["observed_at"]), "expires_at": _json_safe(st["expires_at"]),
                "handoff_ready": st["effective_state"] == "ready"}
    finally:
        c.close()


def _rs_client_from_env():
    """#250 — the runtime's restricted read-only ResourceSpace principal, from env NAMES only
    (RESOURCESPACE_BASE_URL/API_USER/API_KEY). Absent/blank = this runtime is truthfully not
    configured for live SDAM reads; callers must surface that, never fabricate availability."""
    base = (os.environ.get("RESOURCESPACE_BASE_URL") or "").strip()
    user = (os.environ.get("RESOURCESPACE_API_USER") or "").strip()
    key = (os.environ.get("RESOURCESPACE_API_KEY") or "").strip()
    if not (base and user and key):
        return None
    return sdam.RSClient(base, user, key)


def _sdam_stub_enabled():
    """#259 — deterministic in-memory SDAM provider for browser/API tests ONLY (default OFF; a real
    run never sets this). Mirrors the TANAGHOM_WRITER_STUB convention; surfaced in /health."""
    return (os.environ.get("TANAGHOM_SDAM_STUB") or "").strip().lower() in ("1", "true", "yes", "on")


def _rs_writer_from_env():
    """#259 S2 — the runtime's restricted least-privilege WRITE ResourceSpace principal, from env
    NAMES only (RESOURCESPACE_RW_USER/RESOURCESPACE_RW_KEY over the same base URL). Absent/blank =
    this runtime cannot register completed edits; the caller reports that truthfully. This principal
    is field-scoped (F99/F100, create at Pending) and never used for reads/verification."""
    if _sdam_stub_enabled():
        return sdam.StubRS()
    base = (os.environ.get("RESOURCESPACE_BASE_URL") or "").strip()
    user = (os.environ.get("RESOURCESPACE_RW_USER") or "").strip()
    key = (os.environ.get("RESOURCESPACE_RW_KEY") or "").strip()
    if not (base and user and key):
        return None
    return sdam.RSClient(base, user, key)


def _rs_reader_or_stub():
    return sdam.StubRS() if _sdam_stub_enabled() else _rs_client_from_env()


@app.post("/slots/{slot_id}/sdam/register-edit")
def sdam_register_edit(slot_id: str, request: Request):
    """#259 S2 — governed completed-edit registration: register the S1-pinned (#255) approved
    master edit as a versioned SDAM completed-edit resource via the phase-audited convergent
    adapter. Explicit action only (not automatic on gate resolution). Server authority = the
    trusted-principal boundary + the adapter's own audit-verified-pin check. Truthful typed
    outcomes: not configured / refused (unpinned/unverified) / unreconciled / ambiguous / provider
    error — never fabricated success."""
    principal = _require_trusted_principal(request)
    writer = _rs_writer_from_env()
    reader = _rs_reader_or_stub()
    if writer is None or reader is None:
        raise HTTPException(503, "SDAM write is not configured on this runtime")
    c = _conn()
    try:
        # The adapter returns a TYPED status. A Phase-D provider failure AFTER the binding exists
        # is `projection_status: pending` + retryable (the registration IS registered) — a 200
        # truthful body, NOT a 5xx. Only pre-binding provider/authority failures propagate as errors.
        return sdam.register_completed_edit(c, writer, reader, slot_id, actor=principal)
    except sdam.SdamRegistrationError as e:
        c.rollback()
        # refusals + reconciliation stops: typed code, bounded message (no provider detail)
        raise HTTPException(409, e.code)
    except (sdam.SdamUnauthorized, sdam.SdamUnavailable, sdam.SdamMalformed) as e:
        c.rollback()
        raise HTTPException(502, "sdam provider error")   # pre-binding only; bounded, no detail
    finally:
        c.close()


@app.get("/slots/{slot_id}/sdam")
def slot_sdam(slot_id: str, request: Request):
    """#250 — slot-keyed read-only SDAM readiness visibility for the Production/Edit surfaces:
    every binding + its newest PERSISTED observation state. Pure DB truth (no live provider call
    on this path); empty bindings = truthfully 'not bound'. Same signed read boundary as the other
    SDAM reads."""
    _require_trusted_principal(request)   # read-only != unauthenticated: reuse the /gw signed boundary
    c = _conn()
    try:
        rows = sdam.list_slot_bindings(c, slot_id)
        return {"slot_id": slot_id,
                "bindings": [{**b, "binding_id": str(b["binding_id"]), "asset_id": str(b["asset_id"]),
                              "created_at": _json_safe(b["created_at"]),
                              "observed_at": _json_safe(b["observed_at"]),
                              "expires_at": _json_safe(b["expires_at"])} for b in rows]}
    finally:
        c.close()


@app.get("/sdam/bindings/{binding_id}/handoff")
def sdam_handoff(binding_id: str, request: Request):
    """#250 — provider-neutral Edit-input handoff read: the EXISTING #244 `build_handoff`
    authorization (fresh+ready only; media resolved live, never persisted). Truthful outcomes:
    runtime not configured for live SDAM reads; newest observation not fresh-ready; or provider
    unavailable/unauthorized/malformed — none of which may be presented as ready."""
    _require_trusted_principal(request)   # read-only != unauthenticated: reuse the /gw signed boundary
    c = _conn()
    try:
        if not sdam.get_binding(c, binding_id):
            raise HTTPException(404, "binding not found")
        rs = _rs_client_from_env()
        if rs is None:
            return {"binding_id": binding_id, "configured": False, "handoff": None,
                    "reason": "live SDAM read is not configured on this runtime"}
        try:
            h = sdam.build_handoff(c, rs, binding_id)
        except sdam.SdamUnauthorized:
            return {"binding_id": binding_id, "configured": True, "handoff": None,
                    "reason": "sdam rejected the read (unauthorized)"}
        except sdam.SdamUnavailable:
            return {"binding_id": binding_id, "configured": True, "handoff": None,
                    "reason": "sdam unavailable"}
        except sdam.SdamMalformed:
            return {"binding_id": binding_id, "configured": True, "handoff": None,
                    "reason": "sdam returned a malformed response"}
        return {"binding_id": binding_id, "configured": True, "handoff": h,
                "reason": None if h else "newest persisted observation is not fresh ready"}
    finally:
        c.close()


class NewRoundBody(BaseModel):
    # Upper bounds cap the planning grid (days × posts_per_day slots) so an extreme input can't drive
    # unbounded planning work; generous operational maxima (a year of days, hourly posting).
    days: int = Field(28, ge=1, le=366)
    posts_per_day: int = Field(2, ge=1, le=24)
    label: str | None = None
    # #276 — OPTIONAL exact per-run mix over the current baseline eligibility set (validated + pinned).
    # Omitting it keeps the existing create contract (legacy managed weights). #271 owns the operator UX.
    format_mix: dict[str, int] | None = None
    # #304 — OPTIONAL absolute placement (ruling B). V1's New Run form has no placement field, so a
    # REQUIRED start would break V1 creation — a named hard stop. Omitting it creates a truthfully
    # UNPLACED run; V2's governed form supplies one. It is never defaulted to "today" nor derived from
    # created_at: an invented start would be indistinguishable from a governed one.
    starts_on: datetime.date | None = None
    # #377 — OPTIONAL governed recommendation binding. When present, the proposal is verified, locked,
    # consumed and snapshotted inside the SAME transaction that creates the run. Omitting it is the
    # unchanged legacy path: the run is created exactly as before and truthfully has no recommendation
    # snapshot (it reads as `unknown` — nothing is inferred or backfilled).
    proposal_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)


class RunMixPolicyBody(BaseModel):
    """#377 — a NEW governed recommendation-policy generation. Weights are keyed by
    content_format_version.version_id (a rename must never re-point a governed weight) and are
    operator-owned: there is no seed and no inferred default."""
    weights: dict[str, int]
    min_counts: dict[str, int] | None = None
    max_counts: dict[str, int] | None = None
    notes: str | None = Field(default=None, max_length=500)
    scope: str = "default"
    actor: str | None = None


class RunMixPreviewBody(BaseModel):
    """#376 — a SIDE-EFFECT-FREE recommendation preview request. The response persists nothing."""
    starts_on: datetime.date
    ends_on: datetime.date          # INCLUSIVE — the operator's selected range end
    posts_per_day: int = Field(2, ge=1, le=24)
    scope: str = "default"


class RunMixProposalBody(BaseModel):
    """#377 — a PROSPECTIVE draft. Creating one creates no run, no slots, no gates and no history."""
    starts_on: datetime.date
    ends_on: datetime.date          # INCLUSIVE — the operator's selected range end
    posts_per_day: int = Field(2, ge=1, le=24)
    ttl_seconds: int | None = Field(default=None, ge=60, le=7 * 24 * 60 * 60)
    scope: str = "default"
    # #376 — the fingerprint the operator's PREVIEW was computed under. When present, proposal creation
    # fails closed if the governed generations moved since the preview (typed recommendation_stale), so
    # a run is never bound to numbers the operator did not see. Absent = no preview to reconcile against.
    expected: dict | None = None


class RunPlacementBody(BaseModel):
    """#304 — a governed correction of a planned run's absolute placement."""
    starts_on: datetime.date
    actor: str | None = None
    # #292 — the caller's expected COMBINED schedule token. Required, exactly like a schedule
    # revision: there is deliberately no legacy bypass, because a placement accepted against a stale
    # view could silently overwrite a concurrently accepted one. Absent/stale -> typed 409.
    schedule_token: int | None = None


@app.get("/baseline-eligibility")
def baseline_eligibility():
    """#276 — the current baseline eligible framework policy (versioned, decoupled from global
    content_format lifecycle) + its eligible frameworks. The narrow read/selection path #271 consumes."""
    if plan_round is None:
        raise HTTPException(503, "planner unavailable")
    try:
        return plan_round.baseline_eligibility_api(engine.load_config())
    except engine.GateError as e:
        raise HTTPException(409, str(e))   # fails closed on zero/ambiguous current policy


def _require_run_mix():
    if run_mix is None:
        raise HTTPException(503, "run-mix recommendation authority unavailable")
    return run_mix


def _run_mix_http(e):
    """A typed authority refusal keeps its own status: a governed refusal must never degrade into a
    generic 500, and the stable `code` is what a caller branches on."""
    return HTTPException(e.status, {"code": e.code, "detail": str(e), **(e.detail or {})})


@app.get("/run-mix-policy")
def get_run_mix_policy(scope: str = "default"):
    """#377 — the CURRENT governed recommendation-policy generation, or a truthful `absent` state.
    Absent is not an error: it means no operator has declared weights yet, and the authority is
    blocked rather than inventing any."""
    rm = _require_run_mix()
    c = _conn()
    try:
        return rm.read_current_policy(c, scope)
    finally:
        c.close()


@app.post("/run-mix-policy")
def create_run_mix_policy(body: RunMixPolicyBody, request: Request):
    """#377 — mint a NEW policy generation (never an in-place edit of the active one). Authorized by
    the same canonical actor check that governs every other policy administration path."""
    rm = _require_run_mix()
    actor = _trusted_actor(request, body.actor)
    c = _conn()
    try:
        return rm.create_policy_generation(
            c, {"weights": body.weights, "min_counts": body.min_counts,
                "max_counts": body.max_counts, "notes": body.notes},
            actor=actor, scope=body.scope)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except rm.RecommendationError as e:
        raise _run_mix_http(e)
    finally:
        c.close()


@app.post("/run-mix-recommendation-preview")
def preview_run_mix_recommendation(body: RunMixPreviewBody, request: Request):
    """#376 — the SIDE-EFFECT-FREE recommendation preview. Returns the same typed recommended/blocked
    result as a proposal would, plus a `preview_fingerprint`, but persists NOTHING: no proposal row, no
    audit event, no reserved identifier. GPT amendment 4 forbids any durable side effect before the
    operator explicitly plans the run, so the composer shows THIS, and mints a proposal only on submit.
    Performs no model call and is not an AI recommendation."""
    rm = _require_run_mix()
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return rm.preview_recommendation(c, starts_on=body.starts_on, ends_on=body.ends_on,
                                         posts_per_day=body.posts_per_day, principal=principal,
                                         scope=body.scope)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except rm.RecommendationError as e:
        raise _run_mix_http(e)
    except engine.GateError as e:
        raise HTTPException(409, str(e))
    finally:
        c.close()


@app.post("/run-mix-proposals")
def create_run_mix_proposal(body: RunMixProposalBody, request: Request):
    """#377 — the canonical recommendation for a PROSPECTIVE run. Returns either a typed valid
    recommendation (exact counts + bounded structured rationale + immutable provenance) or a typed
    blocked state. There is no fallback: a blocked result persists nothing, so durable submission is
    impossible by construction. This performs NO model call and is not an AI recommendation."""
    rm = _require_run_mix()
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return rm.create_proposal(c, starts_on=body.starts_on, ends_on=body.ends_on,
                                  posts_per_day=body.posts_per_day, principal=principal,
                                  ttl_seconds=body.ttl_seconds, expected=body.expected,
                                  scope=body.scope)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except rm.RecommendationError as e:
        raise _run_mix_http(e)
    except engine.GateError as e:
        raise HTTPException(409, str(e))
    finally:
        c.close()


@app.get("/run-mix-proposals/{proposal_id}")
def read_run_mix_proposal(proposal_id: str, request: Request, scope: str = "default"):
    """Owner-and-scope-checked. A guessed id, a foreign proposal and a nonexistent one are the SAME
    typed 404: possession of an identifier confers no authority and nothing extra is disclosed."""
    rm = _require_run_mix()
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return rm.read_proposal(c, proposal_id, principal, scope=scope)
    except rm.RecommendationError as e:
        raise _run_mix_http(e)
    finally:
        c.close()


@app.post("/run-mix-proposals/purge")
def purge_run_mix_proposals(request: Request, scope: str = "default"):
    """Bounded retention for ABANDONED proposals (expired + still pending). A consumed proposal is
    immutable evidence bound to a run and is never removed here."""
    rm = _require_run_mix()
    actor = _require_trusted_principal(request)
    c = _conn()
    try:
        return rm.purge_expired_proposals(c, actor=actor, scope=scope)
    except rm.RecommendationError as e:
        raise _run_mix_http(e)
    finally:
        c.close()


@app.post("/rounds")
def create_round(body: NewRoundBody, request: Request):
    """Plan a fresh round scaled to days × posts_per_day. #276 — eligibility resolves from the current
    baseline policy and an exact `format_mix` (REQUIRED, no weekly/default fallback) is validated against
    it and pins the exact selection. Returns {round_id, total}. The single UI/agent entry to start a run."""
    if plan_round is None:
        raise HTTPException(503, "planner unavailable")
    if body.format_mix is None:
        raise HTTPException(422, "format_mix is required: an exact count per baseline-eligible framework "
                                 "(GET /baseline-eligibility) summing to days×posts_per_day")
    # #377 — the proposal binding is authenticated: a fence is bound to the principal that created it,
    # so the creator must prove the same signed identity. The legacy path stays untouched — no
    # proposal, no principal requirement, no behaviour change (Codex ruling 2).
    principal = _require_trusted_principal(request) if body.proposal_id else None
    if body.idempotency_key and not body.proposal_id:
        raise HTTPException(422, "idempotency_key applies to a governed proposal binding; "
                                 "supply proposal_id or omit both")
    try:
        # #292 — a NEW round is governed from birth: deterministic mapping generation 1 is created
        # from the planning order INSIDE the planner's own transaction, so display codes are
        # server-owned and the combined schedule token exists before any revision/reorder can race,
        # and an initialization failure rolls the whole round back instead of leaving a committed
        # round with no governed mapping. This endpoint deliberately does NOT open a second
        # connection to do it afterwards — that window WAS the defect: the planner had already
        # committed, so a mapping error (or a concurrent reader) could observe an ungoverned round
        # even though the endpoint reported failure. Every authorized creation path goes through the
        # planner, so all of them are covered by construction. Pre-#292 rounds are still NOT touched
        # (legacy by absence); initializing them is a separately governed slice.
        planned = plan_round.plan_round_api(engine.load_config(), body.days, body.posts_per_day,
                                            body.label, format_mix=body.format_mix,
                                            starts_on=body.starts_on, proposal_id=body.proposal_id,
                                            principal=principal,
                                            idempotency_key=body.idempotency_key)
        return planned
    except ValueError as e:
        raise HTTPException(422, str(e))
    except (run_mix.RecommendationError if run_mix else ()) as e:
        # #377 — a typed fence/generation refusal keeps its own status and stable code. It must be
        # caught BEFORE GateError (it is a subclass), or a 404 would be reported as a 409.
        raise _run_mix_http(e)
    except engine.GateError as e:
        raise HTTPException(409, str(e))   # fail-closed baseline policy (missing/ambiguous)
    except (SystemExit, KeyError) as e:
        # The planner uses SystemExit for domain/precondition failures (unknown template, round-id
        # collision, lens-less HCS) and can KeyError on a broken/empty methodology catalogue. Surface
        # these as a clean 500 with a readable reason instead of an uncaught BaseException that would
        # otherwise escape FastAPI's handler and disrupt the request worker.
        raise HTTPException(500, f"planning failed: {e}")


@app.get("/rounds/{round_id}/policy-snapshot")
def round_policy_snapshot(round_id: str):
    """#276 — a run's IMMUTABLE pinned policy snapshot (baseline policy id+gen, selected version IDs,
    exact mix, methodology/workflow versions). A round read resolves from HERE, never the latest policy."""
    c = _conn()
    try:
        snap = engine.round_snapshot(c, round_id)
        if snap is None:
            raise HTTPException(404, f"no policy snapshot for round {round_id}")
        return snap
    finally:
        c.close()


@app.get("/rounds/{round_id}/recommendation-snapshot")
def round_recommendation_snapshot(round_id: str):
    """#377 — a run's IMMUTABLE recommendation evidence: what the authority proposed, what the operator
    submitted, how they differ, the rationale shown, and the generations in force at creation. Resolves
    ONLY from the pinned snapshot and never recomputes, so activating a different policy/methodology
    generation later cannot change a field of it. A run created without a proposal — every pre-#377 run
    and every legacy proposal-less creation — truthfully reports `unknown`."""
    rm = _require_run_mix()
    c = _conn()
    try:
        return rm.round_recommendation(c, round_id)
    except rm.RecommendationError as e:
        raise _run_mix_http(e)
    finally:
        c.close()


@app.get("/rounds/{round_id}")
def get_round(round_id: str):
    """#271 — the run read model powering calendar continuity: exact per-run format_mix + pinned D1
    policy snapshot + truthful per-status lifecycle counts + the COMPLETE positional slot set."""
    c = _conn()
    try:
        return engine.round_detail(c, round_id)
    except engine.GateError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


class ScheduleRevisionBody(BaseModel):
    changes: dict = Field(default_factory=dict)
    actor: str | None = None
    # #292 — REQUIRED server-issued combined schedule token. There is deliberately no optional
    # legacy bypass: a revision without the caller's expected token could silently overwrite a
    # concurrently accepted mapping. Absent/stale -> typed 409 with refresh evidence.
    schedule_token: int | None = None


def _schedule_conflict(e: "engine.ScheduleConflict"):
    """#292 — a stale token is a typed 409 carrying enough CURRENT state to refresh and re-submit;
    never a 400 (the request was well-formed) and never a silent overwrite."""
    return HTTPException(409, {"detail": str(e), "conflict": "stale_schedule_token", **(e.current or {})})


@app.post("/slots/{slot_id}/schedule-revision")
def schedule_revision(slot_id: str, body: ScheduleRevisionBody, request: Request):
    """#271 — governed single-slot schedule revision (day/time/format-within-pinned-policy/topic
    guidance): returns only that slot to Schedule review, preserves canonical id + audit lineage."""
    c = _conn()
    try:
        return engine.revise_schedule_slot(c, slot_id, body.changes,
                                           actor=_trusted_actor(request, body.actor),
                                           expected_token=body.schedule_token)
    except engine.ScheduleConflict as e:
        raise _schedule_conflict(e)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class ScheduleReorderBody(BaseModel):
    order: list[str] = Field(default_factory=list)   # the COMPLETE ordered slot_id permutation
    schedule_token: int | None = None                # REQUIRED expected combined token
    actor: str | None = None


@app.get("/rounds/{round_id}/schedule-mapping")
def get_schedule_mapping(round_id: str):
    """#292 — the round's CURRENT accepted display mapping + combined schedule token.

    `legacy: true` (token 0) means the round predates #292 and has no governed mapping: clients keep
    their existing derivation. Otherwise the server-provided display_code is authoritative and is
    what an operator reads and quotes; canonical slot_id stays available as secondary diagnostic
    metadata and never changes."""
    c = _conn()
    try:
        return engine.schedule_mapping(c, round_id)
    finally:
        c.close()


@app.post("/rounds/{round_id}/placement")
def place_run(round_id: str, body: RunPlacementBody, request: Request):
    """#304 — govern a PLANNED run's absolute placement on the calendar.

    Moves the campaign window only. Canonical slot_id, slot day/time, accepted mapping and history are
    untouched — a slot's absolute datetime stays derived from the run's start, so a move re-projects
    the same canonical cells. Authority, concurrency and the freeze predicate are the EXISTING ones
    (#271 schedule_review authority, #292 combined token + round lock, `_downstream_advanced`): stale
    token -> typed 409; material execution begun -> fail closed rather than correct in place."""
    c = _conn()
    try:
        return engine.place_run(c, round_id, body.starts_on, expected_token=body.schedule_token,
                                actor=_trusted_actor(request, body.actor))
    except engine.ScheduleConflict as e:
        raise _schedule_conflict(e)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/rounds/{round_id}/schedule-reorder")
def reorder_schedule(round_id: str, body: ScheduleReorderBody, request: Request):
    """#292 — commit a COMPLETE governed presentation order. Changes only the accepted mapping and
    its human-facing codes; canonical slot_id, lineage, and physical day/time are untouched. Stale
    token -> 409; any downstream-advanced slot -> fail closed, never a cascade or silent remap."""
    c = _conn()
    try:
        return engine.reorder_schedule(c, round_id, body.order, body.schedule_token,
                                       actor=_trusted_actor(request, body.actor))
    except engine.ScheduleConflict as e:
        raise _schedule_conflict(e)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class RunMixBody(BaseModel):
    format_mix: dict[str, int] = Field(default_factory=dict)
    actor: str | None = None


@app.post("/rounds/{round_id}/format-mix")
def revise_round_mix(round_id: str, body: RunMixBody, request: Request):
    """#271 — pre-Schedule-approval run-level mix edit: validate exact total against the run's pinned
    eligibility and deterministically reconcile only uncommitted (RESERVED) slots; committed never remapped."""
    c = _conn()
    try:
        return engine.revise_run_mix(c, round_id, body.format_mix, actor=_trusted_actor(request, body.actor))
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# #362 — the API dispatch's worker identity. A single constant so the claim, the writer's fence and
# the result recorder all present the SAME owner; a mismatch would fence the path against itself.
SCRIPT_API_WORKER = "api"


class _GenArgs:                     # argparse-compatible shim for run_writers.run_topics/run_scripts
    def __init__(self, round_id, manifest=None, job_id=None, claim_token=None, worker=None):
        self.round = round_id; self.slot_ids = None; self.distinct_pillars = False
        self.limit = None; self.dry_run = False
        # #357 — the attempt this execution belongs to. Carried to the writer so each produced
        # revision is bound to it inside the SAME transaction that writes the row.
        self.job_id = job_id
        # #362 — the ownership tenure, carried so the writer's persistence transaction is fenced.
        self.claim_token = claim_token
        self.worker = worker
        # #357 — the governed Script attempt's pinned input contract. When present the writer consumes
        # these tuples verbatim and does NOT reselect slots or re-resolve live configuration.
        self.manifest = manifest


@app.post("/rounds/{round_id}/stages/{stage}/generate")
def generate(round_id: str, stage: str, request: Request):
    """Start a generation job over a stage's pending inputs (the single generation mechanism —
    the dashboard buttons and the Telegram agent both call this)."""
    cfg = engine.load_config()
    gc = engine.stage_cfg(cfg, stage)
    if not gc or gc.get("generator") != "ai" or not gc.get("generates_from"):
        raise HTTPException(409, f"stage {stage} has no AI generator")
    if run_writers is None:
        raise HTTPException(503, "writer unavailable (provider deps not installed)")
    src = gc["generates_from"]; mode = gc["writer_mode"]
    # #312 — V2 cutover: topic generation must never silently fall through to legacy run_topics.
    # Stage 2A rounds activate the canonical job idempotently; if no canonical Stage 2A job exists,
    # fail closed so V2 does not execute legacy topic generation.
    if mode == "topics":
        c = _conn()
        try:
            # #332 — MANUAL Topic start is a governed authority action: AUTHENTICATE the signed principal
            # BEFORE any target disclosure (a coarse authentication denial reveals no target and never
            # invents an actor), then AUTHORIZE against the LOCKED job's immutable Schedule
            # affirmative-approver set (engine.activate_manual_topic_generation). No gateway/service
            # pseudo-authority, no client-supplied actor: the trusted signed principal is the only actor.
            try:
                principal = _require_trusted_principal(request)
            except HTTPException as e:
                probe = None
                try:
                    probe = _trusted_principal(request)      # a validly-signed-but-mismatched header still names a principal
                except HTTPException:
                    probe = None
                engine.audit_denied(c, "round", round_id, "topic_generation_manual_start_denied",
                                    probe or "unsigned", {"reason": "unauthenticated"})
                raise
            outcome = engine.activate_manual_topic_generation(c, round_id, principal)
            res = outcome["result"]
            if res == engine.MANUAL_START_ACTIVATED:
                bg = jobs.start("topics", round_id, "topic", 0,
                                lambda jid=outcome["job_id"]: run_writers.run_stage2a_topic_job(cfg, jid))
                return {"job_id": outcome["job_id"], "stage2a": True, "activated": True, "background_job_id": bg}
            if res == engine.MANUAL_START_LIFECYCLE:
                # idempotent typed replay for the authorized approver (already activated / terminal / busy)
                return {"job_id": outcome.get("job_id"), "stage2a": True, "already": True,
                        "status": outcome.get("status")}
            if res == engine.MANUAL_START_AUTOMATIC:
                raise HTTPException(409, "manual start unavailable: this run's Topic generation is "
                                         "automatic (triggered by governed Schedule acceptance)")
            # coarse authorization-safe denial: missing target / malformed snapshot / non-approver — the
            # externally-indistinguishable authorization failure (target existence/mode never leaked).
            raise HTTPException(403, "not authorized to start this run's Topic generation")
        finally:
            c.close()
    # #357 C1/C4 — SCRIPT generation is a governed authority action on EVERY surface. Before #357 this
    # path fell straight through to the job starter with no authentication, authorization or audit, so
    # V1's existing Generate Scripts control, V2, and any agent could start a writer run unauthenticated.
    # Closing that is the intentional correction of an authorization defect, not a V1 regression: the
    # control is unchanged and still invokes THIS command — it is simply authorized now.
    if mode == "scripts":
        try:
            principal = _require_trusted_principal(request)
        except HTTPException:
            # #357 — the denial audit gets its OWN connection, closed in finally. An unsigned caller
            # is the cheapest request to make in volume, so leaking a connection here is exactly the
            # path an attacker would exhaust: the pool would die on refused requests, not real work.
            ca = _conn()
            try:
                engine.audit_denied(ca, "round", round_id, "script_generation_manual_start_denied",
                                    "unsigned", {"reason": "unauthenticated"})
            finally:
                ca.close()
            raise
        cg = _conn()
        try:
            outcome = engine.create_script_generation_attempt(
                cg, round_id, principal,
                requested={"route": request.headers.get("x-requested-route"),
                           "provider": request.headers.get("x-requested-provider"),
                           "model": request.headers.get("x-requested-model")},
                correlation_id=request.headers.get("x-correlation-id"),
                idempotency_key=request.headers.get("x-idempotency-key"))
        except engine.GovernedDenial as e:
            code = getattr(e, "reason", str(e))
            # Typed, distinguishable denials — never a generic unavailable, 404, or provider failure.
            if code in ("principal_missing", "principal_not_approver"):
                raise HTTPException(403, f"not authorized to start Script generation: {code}")
            raise HTTPException(409, f"Script generation unavailable: {code}")
        finally:
            cg.close()
        # Dispatch only when THIS caller won the durable lease. A replay observes the existing attempt
        # instead of starting a second execution of the same governed work.
        c2 = _conn()
        try:
            # #362 — the claim RETURNS THIS TENURE'S TOKEN, not a boolean. Capturing it is what makes
            # the manual path fenced: without carrying it into the writer and the result recorder,
            # this path would claim a tenure and then write as if unowned, bypassing every guard.
            token = engine.claim_script_generation_job(c2, outcome["job_id"], worker=SCRIPT_API_WORKER)
            manifest = engine.script_attempt_manifest_of(c2, outcome["job_id"]) if token else None
            if manifest is not None:
                # actors live on the job, not the manifest; carry them for provenance attribution
                manifest = {**manifest, "initiating_actor": principal, "effective_actor": principal}
        finally:
            c2.close()
        if token and run_writers is not None:
            def _run_governed_script_attempt(_jid=outcome["job_id"], _man=manifest, _tok=token):
                # Execute the pinned manifest, then close the attempt truthfully: link every produced
                # revision to this attempt and record its terminal state. The job row — not a
                # process-local flag — is what any surface observes afterwards.
                try:
                    run_writers.run_scripts(cfg, _GenArgs(round_id, _man, _jid,
                                                        claim_token=_tok, worker=SCRIPT_API_WORKER))
                finally:
                    c3 = _conn()
                    try:
                        engine.record_script_generation_results(
                            c3, _jid, worker=SCRIPT_API_WORKER, claim_token=_tok)
                    finally:
                        c3.close()
            jobs.start("scripts", round_id, stage, outcome["total"], _run_governed_script_attempt)
        return {"job_id": outcome["job_id"], "total": outcome["total"],
                "manifest_digest": outcome["manifest_digest"],
                "replayed": outcome["replayed"], "already_running": outcome["replayed"],
                "dispatched": bool(token)}

    existing = jobs.find_running(mode, round_id, stage)
    if existing:
        return {"job_id": existing["job_id"], "total": existing["total"], "already_running": True}
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status=%s", (round_id, src))
        total = cur.fetchone()[0]
    finally:
        c.close()
    if total == 0:
        raise HTTPException(409, f"no slots in {src} to generate for {stage}")
    fn = run_writers.run_topics if mode == "topics" else run_writers.run_scripts
    job_id = jobs.start(mode, round_id, stage, total, lambda: fn(cfg, _GenArgs(round_id)))
    return {"job_id": job_id, "total": total}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    """Live status of a background job. `done` is DB-derived from the job's targeted slots/state."""
    rec = jobs.JOBS.get(job_id)
    if rec is None:
        raise HTTPException(404, "unknown job")
    if rec["kind"] == "rework":
        target_status = rec.get("target_status")
        target_slots = rec.get("target_slots") or []

        def _done(r):
            if not target_status or not target_slots:
                return 0
            c = _conn()
            try:
                cur = c.cursor()
                cur.execute("SELECT count(*) FROM slot WHERE slot_id = ANY(%s) AND status=%s",
                            (target_slots, target_status))
                return cur.fetchone()[0]
            finally:
                c.close()
        return jobs.status(job_id, _done)
    gc = engine.stage_cfg(engine.load_config(), rec["stage"])
    out_status = (gc.get("reviews_status") if gc else None)
    out_status = out_status[0] if isinstance(out_status, list) else out_status

    def _done(r):
        c = _conn()
        try:
            cur = c.cursor()
            cur.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status=%s", (r["round_id"], out_status))
            return cur.fetchone()[0]
        finally:
            c.close()
    return jobs.status(job_id, _done)


class AgentBody(BaseModel):
    message: str
    reviewer: str | None = None
    artifact: str | None = None      # topic | script — the stage the reviewer is on (optional)


@app.post("/rounds/{round_id}/agent")
def agent_chat(round_id: str, body: AgentBody, request: Request):
    """The SINGLE conversational-agent entry point — shared by the dashboard Assistant panel and the
    Telegram bot (which converges onto this off its in-process path). The agent RECOMMENDS but
    NEVER commits from free text: allow_commit=False is a hard floor, so committing a batch still
    requires the structured button. Model/provider are config-driven (surfaces.telegram_agent).
    Degrades to 503 'assistant unavailable' when the agent or GROQ key is absent — the rest of the
    dashboard keeps working."""
    if agent_mod is None:
        raise HTTPException(503, "assistant unavailable (agent module not loaded)")
    if not runtime_secret.status("GROQ_API_KEY")[0]:
        raise HTTPException(503, "assistant unavailable (GROQ_API_KEY not configured)")
    try:
        llm = agent_mod.build_llm(engine.load_config())
    except Exception as e:                # noqa: BLE001
        raise HTTPException(503, f"assistant unavailable: {e}")
    reviewer = _trusted_actor(request, body.reviewer)
    ctx = {"round_id": round_id, "artifact": body.artifact, "actor": reviewer}
    result = agent_mod.run([{"role": "user", "content": body.message}], ctx,
                           llm=llm, allow_commit=False)   # HARD FLOOR — no commit from free text
    return {"reply": result.get("text", ""), "actions": result.get("tool_results", [])}


@app.get("/integrations")
def integrations():
    """The declared external integration seams (M9·B2) — provider, stage it fills, directives
    in/out, enabled. Defined + stubbed; integration itself is Phase C."""
    return integ.available(engine.load_config())


@app.get("/slots/{slot_id}/directives")
def slot_directives(slot_id: str):
    """The directive chain for a slot (provenance/lineage), oldest first."""
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        rows = directives.chain(cur, slot_id)
        cur.close()
        return [{**r, "directive_id": str(r["directive_id"])} for r in rows]
    finally:
        c.close()


@app.get("/slots/{slot_id}/stage4_preflight")
def slot_stage4_preflight(slot_id: str):
    """#419 — read-only Stage 4 approval-package preflight for one canonical slot.

    Server-authoritative aggregation of EXISTING canonical records only. Returns stable typed
    reason/denial codes + structured evidence, with the candidate's CONSUMED workflow version and
    the currently-active workflow version kept as distinct facts (fail-closed on divergence /
    missing / underivable evidence). Never writes; observes any production direction without
    generating one. Additive read — no existing shared response shape changes."""
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        result = stage4_preflight.preflight(cur, slot_id)
        cur.close()
        return result
    finally:
        c.close()


@app.get("/gates/{gate_id}/slots/{slot_id}/target-package")
def gate_slot_target_package(gate_id: str, slot_id: str):
    """#423 — read-only immutable Stage-4 target-package evidence for one (gate, slot). Additive V1
    route (no existing shape changes). Typed `recorded` / `unknown_history` / `unavailable` disclosure;
    a pure SELECT of persisted evidence — it invokes no attachment/authority logic and reconstructs
    nothing. Existing gate reads are unchanged and continue to be the shape-stable surfaces."""
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        result = final_review_target_package.read(cur, gate_id, slot_id)
        cur.close()
        return result
    finally:
        c.close()


@app.get("/gates/{gate_id}/slots/{slot_id}/final-review-projection")
def gate_slot_final_review_projection(gate_id: str, slot_id: str):
    """#427 — read-only backend final-review projection for one admitted (gate, slot) target. Additive
    V1 route (the #423 /target-package route and shape are unchanged). Server-authoritative join of
    already-persisted evidence only: the immutable target-package snapshot (#423), the gate-wide
    frozen assignment snapshot (#282/#422), and head-correct persisted decision/coverage/audit
    evidence (#321) unambiguously attributable to this target and its governing snapshot. Typed
    `recorded` / `unknown_history` / `unavailable` with machine-readable uncertainty codes; a pure
    SELECT that reconstructs nothing, creates no target-level snapshot, and evaluates no present
    authorization (frozen eligibility is disclosed as history, never as a right to act)."""
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        result = final_review_projection.read(cur, gate_id, slot_id)
        cur.close()
        return result
    finally:
        c.close()


@app.get("/gates/{gate_id}/slots/{slot_id}/approval-preflight")
def gate_slot_approval_preflight(gate_id: str, slot_id: str):
    """#447 — read-only Stage 4 approval-package preflight for one admitted (gate, slot) target.

    Additive V1 route: the #419 `/slots/{slot_id}/stage4_preflight`, #423 `/target-package` and #427
    `/final-review-projection` routes and shapes are unchanged. The read-only GET counterpart of the
    #439 sign-off command — it returns the unconditional six-member immutable package tuple
    (gate_id, slot_id, snapshot_id, topic_revision, script_revision, workflow_version_id), the current
    governed workflow version, current final-review eligibility, the STRUCTURAL human hard-floor, and
    the existing Script-to-Production direction as read-only downstream evidence; or it fails closed
    with canonical typed reasons in deterministic precedence order.

    A pure SELECT: it never writes, never advances lifecycle, never grants capability, generates no
    production direction, and performs no provider/model/secret I/O. It evaluates NO caller, selects
    no actor, and discloses no eligible principals — human authority is reported only as the existing
    server-side structural hard-floor fact, and principal authorization remains the sign-off command's
    responsibility. It can never authorize production."""
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        result = final_review_preflight.preflight(cur, gate_id, slot_id)
        cur.close()
        return result
    finally:
        c.close()


class AssetBody(BaseModel):
    stage: str                               # production | media_edit | distribution
    kind: str                                # raw_cut | edit | image | thumbnail | caption ...
    uri: str | None = None
    storage: str = "reference"
    platform_variant: str | None = None
    meta: dict | None = None
    actor: str | None = None


@app.get("/slots/{slot_id}/assets")
def list_slot_assets(slot_id: str, stage: str | None = None):
    """The DAM assets for a slot (manual-stage work product), optionally filtered by stage."""
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        rows = dam.list_assets(cur, slot_id, stage=stage)
        cur.close()
        return [{**r, "asset_id": str(r["asset_id"])} for r in rows]
    finally:
        c.close()


@app.post("/slots/{slot_id}/assets")
def add_slot_asset(slot_id: str, body: AssetBody, request: Request):
    """Register a media reference (raw cut / edit / variant) on a slot — the manual stage's work."""
    c = _conn()
    try:
        actor = _trusted_actor(request, body.actor)
        aid = dam.add_asset(c, slot_id, body.stage, body.kind, uri=body.uri, storage=body.storage,
                            platform_variant=body.platform_variant, meta=body.meta, actor=actor)
        return {"asset_id": str(aid)}
    finally:
        c.close()


@app.get("/rounds")
def rounds():
    c = _conn()
    try:
        return engine.list_rounds(c)
    finally:
        c.close()


@app.get("/principals")
def principals(kind: str | None = None, active: bool = True, module: str | None = None):
    """Principal registry read model for UI selection surfaces. Roles/groups come from the
    normalized membership tables even while legacy `principal.role` remains present."""
    c = _conn()
    try:
        return engine.list_principals(c, kind=kind, active=active, module=module)
    finally:
        c.close()


@app.get("/principal-roles")
def principal_roles(active: bool = True, module: str | None = None):
    """Normalized role registry for future workflow-assignment/admin UIs."""
    c = _conn()
    try:
        return engine.list_principal_roles(c, active=active, module=module)
    finally:
        c.close()


@app.get("/principal-groups")
def principal_groups(active: bool = True, module: str | None = None):
    """Normalized group registry for future workflow-assignment/admin UIs."""
    c = _conn()
    try:
        return engine.list_principal_groups(c, active=active, module=module)
    finally:
        c.close()


@app.get("/approval-policies")
def approval_policies(request: Request):
    c = _conn()
    try:
        return engine.list_stage_approval_policies(c, principal_id=_trusted_principal(request))
    finally:
        c.close()


@app.get("/stages/{stage}/approval-policy")
def stage_approval_policy(stage: str):
    c = _conn()
    try:
        rows = engine.list_stage_approval_policies(c)
        for policy in rows["policies"]:
            if policy["stage"] == stage:
                return policy
        raise HTTPException(404, f"unknown stage {stage}")
    finally:
        c.close()


@app.put("/stages/{stage}/approval-policy")
def update_stage_approval_policy(stage: str, body: ApprovalPolicyBody, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.update_stage_approval_policy(c, stage, body.model_dump(), actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class RepetitionPolicyBody(BaseModel):
    # All fields default to None: PUT is a SPARSE update — omitted fields preserve the current
    # managed/effective state server-side (engine merge); only provided fields change.
    enabled: bool | None = None
    scope: str | None = None
    similarity_threshold: float | None = None
    max_regenerations: int | None = None
    repeat_modes: dict[str, bool] | None = None


@app.get("/identity/binding")
def identity_binding(issuer: str, subject: str, request: Request):
    """#190 (#172 S1) — resolve an authenticated (issuer, subject) to its bound operating
    principal, or null. Callable ONLY by a system-kind trusted principal (i.e. the dashboard BFF
    itself, which holds the proxy secret) — never by user principals: the mapping is not user
    data, and this endpoint is identity lookup only, NOT an authorization surface."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        caller = engine.actors.load_principal(cur, principal)
        cur.close()
        if not caller or caller.get("kind") != "system":
            raise HTTPException(403, "identity binding lookup requires a system principal")
        row = engine.resolve_user_identity(c, issuer, subject)
        if not row:
            return {"principal_id": None}
        return {"principal_id": row["principal_id"],
                "display_name_en": row["principal_display_name_en"]}
    finally:
        c.close()


def _identity_error(e: "engine.GateError"):
    # explicit conflicts (duplicate tuple / stale CAS / lockout / ineligible target) are 409
    return HTTPException(409 if str(e).startswith("conflict:") else 400, str(e))


@app.get("/identity/bindings")
def identity_bindings(request: Request, limit: int = 25, offset: int = 0):
    """#194 — authorized, bounded, deterministic binding list (authority enforced engine-side)."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.list_user_identities(c, principal, limit=limit, offset=offset)
    except engine.GateError as e:
        raise _identity_error(e)
    finally:
        c.close()


@app.post("/identity/bindings")
async def create_identity_binding(request: Request):
    """#194/#195 — insert-only create; duplicates are explicit 409 conflicts, never upserts.
    AUTHENTICATE-THEN-PARSE: the signed actor is verified BEFORE any body validation, so every
    rejected mutation from a cryptographically valid actor is attributably audited (malformed
    JSON / wrong shape included), while unauthenticated or invalid-signature noise 401s here and
    never produces audit rows. No typed pre-handler validation can bypass the audit path."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
        except Exception as parse_err:  # noqa: BLE001 — any unreadable body from a SIGNED actor
            engine.audit_identity_rejection(c, principal, "create", parse_err)
            raise HTTPException(400, f"invalid request body: {parse_err}")
        return engine.create_user_identity(c, data, actor=principal)
    except engine.GateError as e:
        raise _identity_error(e)
    finally:
        c.close()


@app.post("/identity/bindings/{identity_id}/deactivate")
def deactivate_identity_binding(identity_id: str, request: Request):
    """#194 — CAS active->inactive; self-deactivation fails closed without another usable admin."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.set_user_identity_active(c, identity_id, False, actor=principal)
    except engine.GateError as e:
        raise _identity_error(e)
    finally:
        c.close()


@app.post("/identity/bindings/{identity_id}/reactivate")
def reactivate_identity_binding(identity_id: str, request: Request):
    """#194 — CAS inactive->active for the SAME persisted tuple only (no reassignment path exists)."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.set_user_identity_active(c, identity_id, True, actor=principal)
    except engine.GateError as e:
        raise _identity_error(e)
    finally:
        c.close()


def _publication_error(e: "publication.PublicationError"):
    return HTTPException(409 if str(e).startswith("conflict:") else 400, str(e))


@app.post("/publications")
async def create_publication(request: Request):
    """#200 (pub.v1) — create a publication intent. AUTHENTICATE-THEN-PARSE (the #195 house
    pattern): signed actor first; body validated after, so a valid actor's rejected request is
    attributably audited while unauthenticated noise 401s unaudited. Idempotent: the caller
    supplies a pre-reserved stable idempotency_key; exact replays return existing truth."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
        except Exception as parse_err:  # noqa: BLE001
            publication._denied(c, "-", principal,
                                {"operation": "create_intent", "reason": "invalid_input",
                                 "error": str(parse_err)[:300]})
            raise HTTPException(400, f"invalid request body: {parse_err}")
        return publication.create_intent(c, engine.load_config(), data, actor=principal)
    except publication.PublicationError as e:
        raise _publication_error(e)
    finally:
        c.close()


@app.post("/publications/{intent_id}/manual-outcome")
async def record_publication_outcome(intent_id: str, request: Request):
    """#200 (pub.v1) — the bounded manual attempt + attested outcome (published | failed).
    Eligibility + attestation authority are re-evaluated here; success sets the occurrence once."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
        except Exception as parse_err:  # noqa: BLE001
            publication._denied(c, intent_id, principal,
                                {"operation": "record_manual_outcome", "reason": "invalid_input",
                                 "error": str(parse_err)[:300]})
            raise HTTPException(400, f"invalid request body: {parse_err}")
        return publication.record_manual_outcome(c, engine.load_config(), intent_id, data,
                                                 actor=principal)
    except publication.PublicationError as e:
        raise _publication_error(e)
    finally:
        c.close()


@app.get("/publications")
def list_publications(request: Request, slot_id: str | None = None, round_id: str | None = None,
                      limit: int = 50):
    """#200 (pub.v1) — read publications with derived current state + append-only history."""
    _require_trusted_principal(request)
    c = _conn()
    try:
        return publication.list_publications(c, slot_id=slot_id, round_id=round_id, limit=limit)
    finally:
        c.close()


@app.get("/platforms")
def list_platforms(request: Request):
    """#200 — the platform registry vocabulary (DB truth; the recording UI never hardcodes it)."""
    _require_trusted_principal(request)
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        cur.execute("SELECT platform_key, name FROM platform WHERE active=true "
                    "ORDER BY platform_key")
        return cur.fetchall()
    finally:
        c.close()


@app.get("/repetition-policy")
def repetition_policy(request: Request):
    """#184 — the ACTIVE managed topic-repetition policy (effective values + source + whether the
    caller may administer it). Read model only; enforcement lives in the topic writer path."""
    c = _conn()
    try:
        return engine.get_repetition_policy(c, principal_id=_trusted_principal(request))
    finally:
        c.close()


@app.put("/repetition-policy")
def update_repetition_policy(body: RepetitionPolicyBody, request: Request):
    """#184 — top-level-policy-authority write (server-enforced via the signed-principal path);
    every change is audited with before/after."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.update_repetition_policy(c, body.model_dump(exclude_none=True), actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/workflows")
def workflows(request: Request):
    c = _conn()
    try:
        return engine.list_workflows(c, principal_id=_trusted_principal(request))
    finally:
        c.close()


@app.get("/methodologies")
def methodologies(request: Request):
    c = _conn()
    try:
        return engine.list_methodologies(c, principal_id=_trusted_principal(request))
    finally:
        c.close()


@app.get("/methodology-versions/active")
def active_methodology_version():
    c = _conn()
    try:
        return engine.get_methodology_version(c, active=True)
    finally:
        c.close()


@app.get("/methodology-versions/{version_id}")
def methodology_version(version_id: str):
    c = _conn()
    try:
        return engine.get_methodology_version(c, version_id)
    finally:
        c.close()


@app.post("/methodologies/{methodology_key}/versions/draft")
def create_methodology_draft(methodology_key: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.create_methodology_version_draft(c, methodology_key=methodology_key, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.put("/methodology-versions/{version_id}")
def update_methodology_version(version_id: str, body: MethodologyVersionBody, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.update_methodology_version(c, version_id, body.model_dump(), actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/methodology-versions/{version_id}/activate")
def activate_methodology_version(version_id: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.activate_methodology_version(c, version_id, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/content-formats")
def content_formats(request: Request):
    c = _conn()
    try:
        return engine.list_content_formats(c, principal_id=_trusted_principal(request))
    finally:
        c.close()


@app.post("/content-formats")
def create_content_format(body: ContentFormatBody, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.create_content_format(c, body.model_dump(), actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.put("/content-formats/{content_format_id}")
def update_content_format(content_format_id: str, body: ContentFormatCatalogBody, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.update_content_format(c, content_format_id, body.model_dump(), actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/content-formats/{content_format_id}/archive")
def archive_content_format(content_format_id: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.archive_content_format(c, content_format_id, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/content-formats/{content_format_id}/restore")
def restore_content_format(content_format_id: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.restore_content_format(c, content_format_id, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.delete("/content-formats/{content_format_id}")
def delete_content_format(content_format_id: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.delete_content_format(c, content_format_id, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/content-formats/reset")
def reset_content_formats(body: ContentFormatResetBody, request: Request):
    principal = _require_trusted_principal(request)
    if not body.confirm_reset:
        raise HTTPException(400, "confirm_reset must be true")
    c = _conn()
    try:
        return engine.reset_content_format_registry(c, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/content-formats/{format_key}/versions/draft")
def create_content_format_draft(format_key: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.create_content_format_version_draft(c, format_key=format_key, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.put("/content-format-versions/{version_id}")
def update_content_format_version(version_id: str, body: ContentFormatVersionBody, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.update_content_format_version(c, version_id, body.model_dump(), actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/content-format-versions/{version_id}/activate")
def activate_content_format_version(version_id: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.activate_content_format_version(c, version_id, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/rounds/{round_id}/stages/script_review/action")
def script_generation_action(round_id: str, request: Request):
    """#357 C6/F — the server-owned typed action decision for Script generation.

    UI, agents and automation PROJECT this; none of them recompute eligibility. Unguarded like the rest
    of the read model: the decision itself reports whether the caller's principal is authorized, so an
    unsigned reader learns `principal_missing` rather than being refused the read."""
    c = _conn()
    try:
        principal = _trusted_principal(request)
    except HTTPException:
        principal = None
    try:
        return engine.script_generation_decision(c, round_id, principal)
    finally:
        c.close()


@app.get("/workflow-stages/active")
def active_workflow_stages():
    """#355 — the active governed workflow version's stage contract, read-only and SIDE-EFFECT-FREE.

    Distinct from /workflow-versions/active on purpose: that one seeds a baseline version when none
    is active (and can overwrite an existing workflow row's name/description while doing so), which
    is unacceptable for ordinary navigation. This one is a pure SELECT and fails closed with 404
    when no active version exists. No principal required — the same posture as the rest of the read
    model. Adds no schema, migration or authority.
    """
    c = _conn()
    try:
        snap = engine.active_workflow_stages(c)
        if snap is None:
            raise HTTPException(404, "no active workflow version")
        return snap
    finally:
        c.close()


@app.get("/workflow-stages/active-enabled")
def active_workflow_stage_projection():
    """#376 — the canonical ACTIVE-STAGE PROJECTION: only the stages the resolved active governed
    generation enables.

    Additive and non-breaking: `/workflow-stages/active` keeps returning the FULL contract with its
    existing fail-closed semantics for every existing consumer. This one exists so a lifecycle
    surface never has to fetch-all-and-filter — the "which governed stages are live" decision is made
    where the generation is resolved, not a second time in a client. Same posture as the endpoint it
    projects: pure SELECT, no principal, 404 when nothing is active.
    """
    c = _conn()
    try:
        snap = engine.active_workflow_stage_projection(c)
        if snap is None:
            raise HTTPException(404, "no active workflow version")
        return snap
    finally:
        c.close()


@app.get("/workflow-versions/active")
def active_workflow_version():
    c = _conn()
    try:
        return engine.get_workflow_version(c, active=True)
    finally:
        c.close()


@app.get("/workflow-versions/{version_id}")
def workflow_version(version_id: str):
    c = _conn()
    try:
        return engine.get_workflow_version(c, version_id)
    finally:
        c.close()


@app.post("/workflows/{workflow_key}/versions/draft")
def create_workflow_draft(workflow_key: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.create_workflow_version_draft(c, workflow_key=workflow_key, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.put("/workflow-versions/{version_id}")
def update_workflow_version(version_id: str, body: WorkflowVersionBody, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.update_workflow_version(c, version_id, body.model_dump(), actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/workflow-versions/{version_id}/activate")
def activate_workflow_version(version_id: str, request: Request):
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.activate_workflow_version(c, version_id, actor=principal)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/me/pending-approvals")
def my_pending_approvals(request: Request):
    """Open approval work for the current trusted principal."""
    principal = _require_trusted_principal(request)
    c = _conn()
    try:
        return engine.list_pending_approvals(c, principal)
    finally:
        c.close()


@app.get("/rounds/{round_id}/changes")
def changes(round_id: str, stage: str | None = None):
    """Slots awaiting regeneration (CHANGES_REQUESTED) for a round, with the reviewer comment
    that sent them back — the dashboard's 'awaiting regeneration' panel."""
    cfg = engine.load_config()
    if stage and run_writers is not None:
        gate_stage, changes_status = run_writers._gate_for_rework(cfg, stage)
        rev_table = "topic" if stage == "topic" else "script"
        c = _conn()
        try:
            cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
            rows = run_writers.select_rework(cur, gate_stage, changes_status, rev_table, round_id=round_id)
            cur.close()
            return [{
                "slot_id": row["slot_id"],
                "pillar_code": row["pillar_code"],
                "status": row["status"],
                "round_id": row["round_id"],
                "comment": row.get("rework_note"),
                "revision": max(int(row.get("next_revision") or 1) - 1, 1),
            } for row in rows]
        finally:
            c.close()
    c = _conn()
    try:
        return engine.list_changes_requested(c, round_id=round_id, cfg=cfg)
    finally:
        c.close()


@app.get("/rounds/{round_id}/stages/{stage}/state")
def stage_state(round_id: str, stage: str):
    """The lifecycle state of a stage + the AI advisory (recommendation + warnings) for the human
    batch-commit. Lets the surface render a contextual state (no scary 'no slots' error) and a
    human-confirmed commit affordance."""
    c = _conn()
    try:
        return engine.stage_state(c, round_id, stage)
    except engine.GateNotReady as e:
        # #265 — a held review surfacing through a state read is a HOLD, never a missing resource.
        # The engine reports holds as a truthful generation advisory; this mapping is the backstop.
        raise HTTPException(409, str(e))
    except engine.GateError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@app.get("/rounds/{round_id}/funnel")
def round_funnel(round_id: str):
    """#134 — read-only run-level lifecycle funnel (count contract #131 Slice B): per transition
    stage, how many slots entered / are in the stage / are parked (awaiting, dropped) / advanced.
    Explains legitimate stage-to-stage count differences; NEVER feeds stage-level disposition."""
    c = _conn()
    try:
        return engine.funnel(c, round_id)
    finally:
        c.close()


@app.get("/rounds/{round_id}/provenance")
def provenance_graph(round_id: str):
    """#72 (M7 / #71) — read-only run-scoped provenance graph read model: nodes/edges/timeline
    derived ENTIRELY from persisted data, every entity citing its backing table/field, plus an
    explicit `unsupported[]` list of future-only concepts that are NOT faked. No writes."""
    c = _conn()
    try:
        return provenance.provenance_graph(c, round_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@app.get("/rounds/{round_id}/generation")
def topic_generation(round_id: str):
    """#310 §F — the Stage 2A Topic-generation read model: durable job truth (phase / counts / typed
    error) + per-accepted-slot results (accepted Pillar/HCS/format, canonical Topic identity + meaning/
    title, provenance disclosure). Read-only, entirely from persisted truth. `stage2a_enabled=false`
    (no active generation policy) means Stage 2A is not provisioned for the run (no generation command
    available) — an empty, non-erroring model."""
    c = _conn()
    try:
        return engine.topic_generation_read_model(c, round_id)
    finally:
        c.close()


class GenerationRetryBody(BaseModel):
    actor: str | None = None


@app.post("/rounds/{round_id}/generation/retry")
def topic_generation_retry(round_id: str, body: GenerationRetryBody, request: Request):
    """#310 §F — retry a FAILED/PARTIAL Stage 2A Topic-generation job through the EXISTING binding and
    the same confirmation boundary as generate: signed-principal authorization (unsigned/mismatch =
    AUDITED denial + 403), never a second start path (rejects when there is no retryable job), and
    bounded/idempotent re-drive (only still-SCHEDULE_APPROVED slots; existing Topic identities kept).
    This is NOT Topic regenerate/edit/drop/reorder (Stage 2B) — only a failed job's remaining slots."""
    c = _conn()
    try:
        actor = _trusted_generation_actor(request, body.actor, c, round_id)   # audited denial on reject
        plan = engine.retry_topic_generation(c, round_id, actor)
    except engine.GateError as e:
        raise HTTPException(409, str(e))
    finally:
        c.close()
    if run_writers is None:
        raise HTTPException(503, "writer unavailable (provider deps not installed)")
    cfg = engine.load_config()
    # The durable generation_job (plan["job_id"]) is authoritative; the background job is only the
    # execution vehicle that re-drives run_stage2a_topic_job over the remaining SCHEDULE_APPROVED slots.
    background_job_id = jobs.start("topics", round_id, "topic", plan["retryable_slots"],
                                   lambda: run_writers.run_stage2a_topic_job(cfg, plan["job_id"]))
    return {**plan, "background_job_id": background_job_id, "retried": True}


@app.get("/rounds/{round_id}/stages/{stage}/advanced")
def stage_advanced(round_id: str, stage: str):
    """#179 — durable post-commit trail: what this stage approved & advanced (from resolved gates'
    committed decision rollups) and where each item is NOW. Read-only; no new persistence."""
    c = _conn()
    try:
        return engine.list_advanced(c, round_id, stage)
    finally:
        c.close()


@app.get("/rounds/{round_id}/dropped")
def dropped(round_id: str):
    """Slots in the reversible 'dropped' (REJECTED) state for a round — the recoverable Dropped view."""
    c = _conn()
    try:
        return engine.list_dropped(c, round_id=round_id)
    finally:
        c.close()


class ReopenBody(BaseModel):
    actor: str | None = None


@app.post("/slots/{slot_id}/reopen")
def reopen(slot_id: str, body: ReopenBody, request: Request):
    """Reverse a committed decision (un-reject a dropped item, or un-approve): move it back to its
    review status. Nothing is destroyed — a new audited 'reopened' event ('git for content')."""
    c = _conn()
    try:
        return engine.reopen(c, slot_id, actor=_trusted_actor(request, body.actor))
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class UndecideBody(BaseModel):
    approver_id: str | None = None
    slot_ids: list[str] | None = None
    actor: str | None = None


@app.post("/gates/{gate_id}/undecide")
def undecide(gate_id: str, body: UndecideBody, request: Request):
    """PRE-commit undo: clear a recorded per-item decision (un-approve/un-reject before submit)."""
    c = _conn()
    try:
        approver = _trusted_approval_actor(request, body.approver_id, c, gate_id)
        actor = _trusted_approval_actor(request, body.actor if body.actor else approver, c, gate_id)
        return engine.clear_decision(c, gate_id, approver, slot_ids=body.slot_ids, actor=actor)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/rounds/{round_id}/rework")
def rework(round_id: str, stage: str = "topic", dry_run: bool = False):
    """Close the co-creation loop: regenerate v2 for the round's CHANGES_REQUESTED slots in
    `stage` (topic|script), the reviewer's comment injected as the rework directive. Runs in the
    background (the writer/LLM is slow); the dashboard polls for v2. dry_run=just report targets."""
    cfg = engine.load_config()
    if run_writers is None:
        raise HTTPException(503, "rework writer unavailable (provider deps not installed in this API)")
    gate_stage, changes_status = run_writers._gate_for_rework(cfg, stage)
    rev_table = "topic" if stage == "topic" else "script"
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        queued = run_writers.select_rework(cur, gate_stage, changes_status, rev_table, round_id=round_id)
        cur.close()
        targets = [r["slot_id"] for r in queued]
    finally:
        c.close()
    if dry_run or not targets:
        return {"started": 0, "would_rework": len(targets), "slots": targets, "dry_run": dry_run}
    target_status = engine._review_status_for_artifact(cfg, stage)
    existing = jobs.find_running("rework", round_id, gate_stage)
    if existing:
        return {
            "job_id": existing["job_id"],
            "started": existing["total"],
            "would_rework": existing["total"],
            "slots": existing.get("target_slots") or targets,
            "dry_run": False,
            "already_running": True,
        }

    def _run():
        results = run_writers.rework_round(cfg, stage, round_id=round_id, quiet=True)
        errors = [r for r in results if r.get("result") == "ERROR" or "rework_under_applied" in (r.get("flags") or [])]
        if errors:
            details = "; ".join(
                f"{r['slot_id']}: {r.get('error') or ', '.join(r.get('flags') or []) or r.get('result')}"
                for r in errors
            )
            raise RuntimeError(details)
        if len(results) != len(targets):
            raise RuntimeError(f"expected {len(targets)} rework target(s), processed {len(results)}")

    job_id = jobs.start("rework", round_id, gate_stage, len(targets), _run,
                        meta={"target_slots": targets, "target_status": target_status, "artifact": stage})
    return {"job_id": job_id, "started": len(targets), "would_rework": len(targets), "slots": targets, "dry_run": False}


@app.get("/gates")
def gates(status: str | None = None, round: str | None = None):
    c = _conn()
    try:
        return [{**g, "gate_id": str(g["gate_id"])}
                for g in engine.list_gates(c, status=status, round_id=round)]
    finally:
        c.close()


@app.post("/gates")
def open_gate(body: OpenBody, request: Request):
    c = _conn()
    try:
        actor = _trusted_actor(request, body.actor)
        gid = engine.open_gate(c, body.stage, slot_ids=body.slot_ids,
                               round_id=body.round_id, actor=actor)
        return {"gate_id": str(gid)}
    except engine.GateNotReady as e:
        raise HTTPException(409, str(e))   # #265 — held: generation incomplete (fail-closed)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/gates/{gate_id}")
def gate_detail(gate_id: str):
    c = _conn()
    try:
        g = engine.get_gate(c, gate_id)
        g["gate_id"] = str(g["gate_id"])
        return g
    except engine.GateNotReady as e:
        raise HTTPException(409, str(e))   # #265 — held, NOT missing: never mask the hold as a 404
    except engine.GateError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@app.post("/gates/{gate_id}/decide")
def decide(gate_id: str, body: DecideBody, request: Request):
    c = _conn()
    try:
        approver = _trusted_approval_actor(request, body.approver_id, c, gate_id)
        touched = engine.decide(c, gate_id, approver, body.decision,
                                slot_ids=body.slot_ids, notes=body.notes, revision=body.revision)
        return {"touched": touched}
    except engine.GateNotReady as e:
        raise HTTPException(409, str(e))   # #265 — held: no decision against a partial population
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


def _signoff_canonical_uuid(value):
    """Return the canonical lowercase UUID text, or raise 422 invalid_request. Rejects a malformed or
    non-canonical (e.g. uppercase / braced) UUID — the digest + storage require canonical lowercase."""
    try:
        canonical = str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(422, {"error": "invalid_request"})
    if str(value) != canonical:
        raise HTTPException(422, {"error": "invalid_request"})
    return canonical


@app.post("/gates/{gate_id}/slots/{slot_id}/sign-off")
def sign_off_slot(gate_id: str, slot_id: str, body: SignOffBody, request: Request):
    """#439 — record ONE immutable final-review sign-off receipt for an immutable (gate_id, slot_id)
    target-package, or return the ORIGINAL receipt on an identical idempotent replay. THIN wrapper:
    parse+validate the request (Pydantic forbid-extra + canonical-lowercase UUID + trimmed idempotency
    bounds -> 422 invalid_request), resolve the verified proxy principal via the EXISTING
    _trusted_approval_actor seam (missing/invalid -> 401 signoff_unauthenticated; the seam audits the
    denial), then delegate the whole authority/idempotency/transaction/audit contract to
    engine.sign_off and map each typed SignoffError to its public {"error": code} + HTTP status. The
    request carries no actor field; the signed principal is the sole actor. Grants no authority and the
    V2/Workbench read projection stays read-only and non-authoritative."""
    gid = _signoff_canonical_uuid(gate_id)
    snapshot_id = _signoff_canonical_uuid(body.snapshot_id)
    workflow_version_id = _signoff_canonical_uuid(body.workflow_version_id)
    if not (1 <= len((body.idempotency_key or "").strip()) <= 200):
        raise HTTPException(422, {"error": "invalid_request"})
    c = _conn()
    try:
        try:
            actor = _trusted_approval_actor(request, None, c, gid)
        except HTTPException as e:
            if e.status_code == 401:
                raise HTTPException(401, {"error": "signoff_unauthenticated"})
            raise
        try:
            return engine.sign_off(c, gid, slot_id, actor, snapshot_id, body.topic_revision,
                                   body.script_revision, workflow_version_id, body.idempotency_key)
        except engine.SignoffError as e:
            raise HTTPException(e.http_status, {"error": e.code})
    finally:
        c.close()


@app.get("/slots/{slot_id}/inspect")
def slot_inspect(slot_id: str, request: Request):
    """#237 Slice A — status-independent READ-ONLY inspection projection for one slot: the same
    content definition the active review card shows (pinned/approved artifact revisions, decision
    provenance, assets, publications), so the completed trail keeps full inspection depth.
    Approval changes controls, not visibility. Returns full script content, so it sits behind the
    same signed boundary as /publications."""
    _require_trusted_principal(request)   # read-only != unauthenticated: reuse the /gw signed boundary
    c = _conn()
    try:
        detail = engine.inspect_slot(c, slot_id)
        # publication lineage composed here (module already owns that read model); the projection
        # stays truthful on every stage, not only where the surface preloads publications.
        detail["publications"] = publication.list_publications(c, slot_id=slot_id)
        return detail
    except engine.GateError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@app.get("/slots/{slot_id}/revisions")
def revisions(slot_id: str, artifact: ScriptArtifact = "topic"):
    """The full linear revision chain for a slot's artifact (topic|script) — each version's
    comment, change-summary, provenance, and which is approved. Powers the version-history UI."""
    c = _conn()
    try:
        return engine.list_revisions(c, slot_id, artifact=artifact)
    finally:
        c.close()


@app.get("/slots/{slot_id}/topic_item")
def topic_item(slot_id: str, request: Request, artifact: ScriptArtifact = "topic"):
    """#313 — the ONE canonical per-item Topic read model: stable slot_id, status, head/approved
    revision pointers, immutable revision history (parent/base lineage + provenance + approved flag),
    and the TYPED available/denied action map (so the V2 surface never offers an action the command
    would refuse). Read-only durable truth; a read like /rounds/{id}/generation (no signed boundary —
    topic angle/hook are already surfaced there).

    #373 (Codex P1) — the read stays UNGUARDED (unsigned is fine), but if the caller IS signed we
    resolve the trusted principal and thread it through so `undecide` availability reflects THIS
    principal's own recorded decision (an unsigned reader learns `principal_missing`, exactly like the
    action-decision read). undecide clears only the calling principal, so the projection must be bound
    to it — never any approver — so the surface can never offer a clear that would delete zero."""
    try:
        actor = _trusted_principal(request)
    except HTTPException:
        actor = None
    c = _conn()
    try:
        return engine.topic_item_read_model(c, slot_id, artifact, actor)
    except engine.GateError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


def _raise_topic_governance_http(e):
    """#313 — map typed per-item governance errors to governed HTTP codes. Callers catch engine.GateError
    (RevisionConflict/GovernedDenial subclass it) and dispatch here so a stale-revision race answers 409
    with the current head, and a governed denial (approved/downstream-advanced, #249 unconsumed) answers a
    typed 409 with a machine reason — never a generic 400 that hides the distinction."""
    if isinstance(e, engine.RevisionConflict):
        raise HTTPException(409, {"error": "stale_revision", "current": e.current, "detail": str(e)})
    if isinstance(e, engine.GovernedDenial):
        raise HTTPException(409, {"error": "governed_denial", "reason": e.reason, "detail": str(e)})
    raise HTTPException(400, str(e))


class RestoreBody(BaseModel):
    artifact: ScriptArtifact = "topic"       # #367 — closed topic|script; defaults topic (V1)
    revision: int                            # the older revision to make the new head
    actor: str | None = None
    expected_revision: int | None = None     # #313 optimistic-concurrency CAS: current head expected
    idempotency_key: str | None = None       # #313 replay guard (topic): a repeat returns the original revision


@app.post("/slots/{slot_id}/restore")
def restore(slot_id: str, body: RestoreBody, request: Request):
    """Restore an older revision as the new HEAD (a new revision copied from it) and send the slot
    back for re-review. A new comment then reworks from there. Linear, append-only, audited. #313 adds
    expected-revision CAS (409 stale_revision), idempotent replay (topic), and fail-closed eligibility
    (approved/downstream-advanced → 409 governed_denial, #249 unconsumed)."""
    c = _conn()
    try:
        return engine.restore_revision(c, slot_id, body.artifact, body.revision,
                                       actor=_trusted_actor(request, body.actor),
                                       expected_revision=body.expected_revision,
                                       idempotency_key=body.idempotency_key)
    except engine.GateError as e:
        _raise_topic_governance_http(e)
    finally:
        c.close()


class ReworkFromBody(BaseModel):
    artifact: ScriptArtifact = "topic"       # #367 — closed topic|script; defaults topic (V1)
    revision: int                            # the version to rework FROM
    comment: str                             # the rework directive
    actor: str | None = None
    expected_revision: int | None = None     # #313 CAS on the restore step
    idempotency_key: str | None = None       # #313 replay guard on the restore step (topic)


def _drive_rework_operation(cfg, op_id):
    """Run one durable rework operation in a background thread (the writer worker claims it exactly once)."""
    def _run():
        try:
            run_writers.run_rework_operation(cfg, op_id)
        except Exception as e:                  # noqa: BLE001 — the op is marked failed (resumable); log
            print(f"[rework_op] {op_id} failed: {e}")
    threading.Thread(target=_run, daemon=True).start()


def _recover_rework_operations(cfg, limit=None):
    """#313 P1-B — opportunistic recovery: re-drive any stranded operations (queued/failed, or running
    with an expired lease — e.g. a crash after restore). Each worker claim is atomic, so this is safe to
    call from every rework request and safe under OVERLAPPING invocations (a concurrent claim of the
    same op matches zero rows for the loser); a completed op is never re-driven.
    #321 R6 — `limit` bounds a single pass. This is CLAIM/DRIVE only: it re-drives eligible ops via the
    atomic worker claim and NEVER calls, emulates or triggers terminalization (which stays the explicit
    #319 workflow.admin command). Returns the op_ids it dispatched (observable)."""
    c = _conn()
    try:
        ops = engine.recoverable_rework_operations(c, limit=limit)
    finally:
        c.close()
    for op_id in ops:
        _drive_rework_operation(cfg, op_id)
    return ops


# #321 R6 — the BOUNDED PERIODIC rework recovery owner. It reuses the ONE existing bounded-periodic
# recovery host (the #310 startup daemon below), draining at most TANAGHOM_REWORK_RECOVERY_BATCH
# eligible non-terminal rework operations per pass. Idempotent and overlap-safe (atomic claim),
# bounded (batch cap), observable (logs the count), and it distinguishes active/reclaimable/completed/
# failed/terminal purely through the #319 lease/token claim rules — it never terminalizes.
def _rework_recovery_batch():
    """#321 P1.3 — resolve TANAGHOM_REWORK_RECOVERY_BATCH as a POSITIVE bounded integer. Invalid
    (non-numeric/empty) or non-positive config FAILS SAFE to the default rather than dispatching an
    unbounded or malformed batch; a fat-fingered huge value is clamped to a hard ceiling."""
    raw = os.environ.get("TANAGHOM_REWORK_RECOVERY_BATCH", "10")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        print(f"[recovery] invalid TANAGHOM_REWORK_RECOVERY_BATCH={raw!r} — using default 10")
        return 10
    if n < 1:
        print(f"[recovery] non-positive TANAGHOM_REWORK_RECOVERY_BATCH={n} — using default 10")
        return 10
    return min(n, 1000)


def _periodic_rework_recovery(cfg):
    batch = _rework_recovery_batch()
    driven = _recover_rework_operations(cfg, limit=batch)
    if driven:
        print(f"[recovery] rework drain: dispatched {len(driven)} eligible op(s) (batch cap {batch})")
    return driven


@app.post("/slots/{slot_id}/rework_from")
def rework_from(slot_id: str, body: ReworkFromBody, request: Request):
    """'Rework from this version (with a comment)': restore the chosen revision as the new HEAD, then
    regenerate from it addressing the comment. #313 P1-B — the WHOLE restore+rework is a DURABLE
    operation (rework_operation) keyed idempotently; the restore + operation row are one atomic
    transaction, so a crash/replay/concurrent call never mints a duplicate generated revision. A replay
    resumes unfinished work and deduplicates completed/in-flight duplicates. Writer availability is
    checked BEFORE any restore, so an unavailable writer never leaves an orphan restored revision.
    Inherits fail-closed eligibility (#249) + expected-revision CAS; the resulting revision records
    exact job-less rework provenance."""
    if not (body.comment or "").strip():
        raise HTTPException(400, "rework needs a comment")
    if not body.idempotency_key:
        raise HTTPException(400, "rework needs an idempotency_key (the durable operation identity)")
    # #313 P1-B — check the writer BEFORE any restore, so an unavailable writer cannot leave an orphan.
    if run_writers is None:
        raise HTTPException(503, "rework writer unavailable (provider deps not installed)")
    cfg = engine.load_config()
    actor = _trusted_actor(request, body.actor)
    _recover_rework_operations(cfg)             # re-drive any stranded operation first (crash recovery)
    c = _conn()
    try:
        began = engine.begin_rework_operation(
            c, slot_id, body.revision, body.comment.strip(), actor, body.idempotency_key,
            expected_revision=body.expected_revision, artifact=body.artifact, cfg=cfg)
    except engine.GateError as e:
        _raise_topic_governance_http(e)
    finally:
        c.close()
    action = began["action"]
    if action in ("start", "resume"):
        _drive_rework_operation(cfg, began["op_id"])
        return {"restored_from": body.revision, "reworking": True, "op_id": began["op_id"], "action": action}
    # dedupe (completed) or dedupe_inflight (running under a live lease) — no second generation.
    return {"restored_from": body.revision, "reworking": False, "idempotent_replay": True,
            "op_id": began["op_id"], "action": action,
            **({"generated_revision": began.get("generated_revision")} if action == "dedupe" else {})}


@app.get("/rework_operations/{op_id}")
def rework_operation_read(op_id: str, request: Request):
    """#319 — the governed READ for a rework operation: its state, whether it is
    terminalization-eligible, and the CANONICAL `expected_op_token` a terminalization request must
    echo back. The token is computed by the same engine function the write revalidates with, so a
    client never derives it independently and the two can never skew.

    FAIL-CLOSED, same boundary as the terminalize command it feeds. This read exists ONLY to mint the
    terminalization token and expose the operation's ownership/strandedness — so read authority IS
    terminalize authority: the signed principal must hold the explicit `workflow.admin` permission.
    Leaving it anonymous would hand any caller the exact token the fenced write revalidates, and the
    operation's internal state with it. No role/permission fallback (see
    engine.can_terminalize_rework_operation)."""
    actor = _require_trusted_principal(request)
    c = _conn()
    try:
        cur = c.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
        if not engine.can_terminalize_rework_operation(cur, actor):
            cur.close()
            raise HTTPException(403, {"error": "governed_denial", "reason": "unauthorized",
                                      "detail": f"reading rework operation {op_id} requires the "
                                                f"{engine.REWORK_TERMINALIZE_PERMISSION} permission"})
        cur.close()
        return engine.stranded_rework_operation(c, op_id)
    except engine.GateError as e:
        _raise_topic_governance_http(e)
    finally:
        c.close()


class TerminalizeReworkBody(BaseModel):
    expected_op_token: str                   # #319 the operation state this request was formed against
    idempotency_key: str                     # #319 replay identity (the append-only audit is the receipt)
    reason: str                              # #319 the durable, audited justification
    actor: str | None = None                 # may only echo the signed principal


@app.post("/rework_operations/{op_id}/terminalize")
def terminalize_rework_operation(op_id: str, body: TerminalizeReworkBody, request: Request):
    """#319 P0 — governed terminalization of an UNSAFELY STRANDED rework operation: the only escape
    from a `rework_active` fence that recovery can never clear. Requires the existing `workflow.admin`
    permission held explicitly by the signed principal. Every check is server-side and fail-closed;
    every refusal is a typed reason (unauthorized / not_stranded / active_owner / recoverable /
    stale_token / already_terminalized), never a silent no-op.

    It moves ONE operation to ONE terminal state, releases that operation's derived fence, and appends
    ONE immutable audit row. It creates no revision, alters no provenance, mutates no
    approval/downstream state, and confers NO #249 reconsideration authority."""
    if not (body.reason or "").strip():
        raise HTTPException(400, "terminalization needs a reason")
    if not (body.idempotency_key or "").strip():
        raise HTTPException(400, "terminalization needs an idempotency_key")
    if not (body.expected_op_token or "").strip():
        raise HTTPException(400, "terminalization needs an expected_op_token")
    actor = _trusted_actor(request, body.actor)
    c = _conn()
    try:
        return engine.terminalize_rework_operation(
            c, op_id, actor, body.expected_op_token.strip(), body.idempotency_key.strip(),
            body.reason.strip())
    except engine.GateError as e:
        _raise_topic_governance_http(e)
    finally:
        c.close()


class EditBody(BaseModel):
    artifact: ScriptArtifact = "topic"       # #367 — closed topic|script; defaults topic (V1)
    field: str                               # whitelisted plain-text field (topic: hook_text|text_ar; script: script_ar|final_line)
    value: str                               # the human-entered replacement text
    actor: str | None = None
    expected_revision: int | None = None     # #313 optimistic-concurrency CAS: current head the edit expects
    idempotency_key: str | None = None       # #313 replay guard: a repeat returns the original revision


@app.post("/slots/{slot_id}/edit")
def edit_slot(slot_id: str, body: EditBody, request: Request):
    """#14/#313 — persist a manual inline edit of a whitelisted plain-text field (topic: hook_text/text_ar;
    script: script_ar/final_line) as a new head revision (append-only, audited). A manual script edit
    re-opens language/religious sign-off. Structural fields are rejected (deferred to #51). #313 adds
    optimistic-concurrency (`expected_revision` → 409 stale_revision), idempotent replay
    (`idempotency_key`), and fail-closed eligibility (approved/downstream-advanced → 409 governed_denial,
    #249 unconsumed)."""
    c = _conn()
    try:
        return engine.edit_revision(c, slot_id, body.artifact, body.field, body.value,
                                    actor=_trusted_actor(request, body.actor),
                                    expected_revision=body.expected_revision,
                                    idempotency_key=body.idempotency_key)
    except engine.GateError as e:
        _raise_topic_governance_http(e)
    finally:
        c.close()


def _round_of_slot(slot_id):
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT round_id FROM slot WHERE slot_id=%s", (slot_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        c.close()


def _raise_decision_result(res):
    """#313 P1-A — map a contract decision result's typed error to governed HTTP. The CAS (stale_revision)
    and eligibility (governed_denial) are enforced atomically INSIDE the decision transaction, so a
    refusal here means NO decision was persisted."""
    if res.get("stale_revision"):
        raise HTTPException(409, {"error": "stale_revision", "current": res.get("current"),
                                  "detail": res.get("error")})
    if res.get("governed_denial"):
        raise HTTPException(409, {"error": "governed_denial", "reason": res["governed_denial"],
                                  "detail": res.get("error")})
    if res.get("error"):
        raise HTTPException(409, {"error": "decision_refused", "detail": res["error"]})


class DropBody(BaseModel):
    reason: str | None = None                # optional attributable rationale for the drop
    actor: str | None = None
    artifact: ScriptArtifact = "topic"       # #367 R3.2 — closed topic|script; defaults topic (V1)


@app.post("/slots/{slot_id}/drop")
def drop_slot(slot_id: str, body: DropBody, request: Request):
    """#313 (Codex P1-3 + P1-A) — DROP routes through the EXISTING governed gate REJECT decision, NOT a
    direct slot-status mutation. The approved/downstream-advanced (#249) eligibility is enforced UNDER a
    slot lock in the SAME transaction that records the reject decision (atomic — no post-approval/
    downstream reject can be persisted). Shares the gate's frozen authority/quorum, decision, audit and
    reject/resolve lineage; preserves the human commit floor (the REJECTED transition happens at commit,
    recoverable via reopen/restore — nothing destroyed). Fail-closed → 409 governed_denial."""
    actor = _trusted_actor(request, body.actor)
    rid = _round_of_slot(slot_id)
    if not rid:
        raise HTTPException(404, f"no slot {slot_id}")
    res = contract.reject(rid, body.artifact, slot_id, actor=actor, reason=body.reason,
                          eligibility_check=True)
    if not res.get("ok"):
        _raise_decision_result(res)
    return {"slot_id": slot_id, "decision_recorded": True, "committed": False,
            "note": "drop = a governed gate REJECT decision recorded; the REJECTED transition is the human commit floor",
            "result": res}


class ApproveBody(BaseModel):
    expected_revision: int                   # #313 CAS — the exact revision the caller saw and approves
    actor: str | None = None
    artifact: ScriptArtifact = "topic"       # #367 R3.2 — closed topic|script; defaults topic (V1)


@app.post("/slots/{slot_id}/approve")
def approve_slot(slot_id: str, body: ApproveBody, request: Request):
    """#313 (Codex P1-1 + P1-A) — RECORD a governed approval decision for one item through the EXISTING
    gate (authority + assignment/quorum + audit). The exact `expected_revision` is CAS-checked against
    head UNDER a slot lock in the SAME transaction that records the decision — atomic, so a concurrent
    edit/rework can never make the approval attach to a non-head revision; stale → 409 stale_revision
    with NO decision recorded. The decision PINS that exact revision. It does NOT advance/commit: the
    advance is the HUMAN commit floor, never auto-run by V2's signed principal."""
    actor = _trusted_actor(request, body.actor)
    rid = _round_of_slot(slot_id)
    if not rid:
        raise HTTPException(404, f"no slot {slot_id}")
    res = contract.approve(rid, body.artifact, [slot_id], actor=actor, revision=body.expected_revision,
                           expected_revision=body.expected_revision)
    if not res.get("ok"):
        _raise_decision_result(res)
    return {"slot_id": slot_id, "decision_recorded": True, "committed": False,
            "approved_revision": body.expected_revision,
            "note": "approval decision recorded for the EXACT revision (atomic CAS); advance/commit is the human floor",
            "result": res}


class RequestChangeBody(BaseModel):
    comment: str                             # the attributable rationale = the rework directive
    actor: str | None = None
    artifact: ScriptArtifact = "topic"       # #367 — closed topic|script; defaults topic for V1


@app.post("/slots/{slot_id}/request_change")
def request_change_slot(slot_id: str, body: RequestChangeBody, request: Request):
    """#313 (Codex P1-2) — governed request-change: RECORD a send-back decision WITH an attributable
    rationale through the existing gate authority + audit. TRUTHFUL semantics: this RECORDS the decision;
    the item does NOT transition to CHANGES_REQUESTED until the human commit floor. The comment IS the
    rework directive."""
    if not (body.comment or "").strip():
        raise HTTPException(400, "request_change needs a comment (it guides the regeneration)")
    actor = _trusted_actor(request, body.actor)
    rid = _round_of_slot(slot_id)
    if not rid:
        raise HTTPException(404, f"no slot {slot_id}")
    res = contract.request_change(rid, body.artifact, slot_id, body.comment.strip(), actor=actor)
    if isinstance(res, dict) and res.get("error"):
        raise HTTPException(409, {"error": "governed_denial", "detail": res["error"]})
    return {"slot_id": slot_id, "decision_recorded": True, "committed": False,
            "note": "change-request decision recorded; the send-back transition is the human commit floor",
            "result": res}


@app.post("/slots/{slot_id}/review/{review}/dispose")
def dispose(slot_id: str, review: str, body: DisposeBody, request: Request):
    """Reviewer disposes a suggested review: escalate (route to the named reviewer) or waive."""
    c = _conn()
    try:
        engine.dispose_review(c, slot_id, review, body.action, reason=body.reason,
                              actor=_trusted_actor(request, body.actor))
        return {"ok": True}
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


def _abort_acceptance_audit(c, round_id, gate_id, code, _open=None):
    """#359 review fix 1 — record the aborted-acceptance denial ONLY after the failed acceptance
    transaction's release is ESTABLISHED, never alongside it.

    `engine.resolve()` propagates ScriptAuthorityUnavailable unhandled, so `c` still owns the failed
    transaction with its locks live. Release is attempted in order: rollback, then — if rollback
    itself throws — a forced close/terminate. The separate audit connection is opened ONLY once one
    of those establishes release. If neither can (rollback AND close both throw), the audit is
    SKIPPED and the refusal still stands: a denial record is never worth committing beside a
    transaction we cannot prove we released.

    Returns "audited" | "skipped_unreleased" | "audit_failed". `_open` is the audit-connection
    factory (defaults to `_conn`), injectable so the ordering/failure behaviour is unit-testable.
    """
    opener = _open or _conn
    released = None
    try:
        c.rollback()
        released = "rollback"
    except Exception:                                  # noqa: BLE001 — rollback failed; force release
        try:
            c.close()
            released = "close"
        except Exception:                              # noqa: BLE001 — release cannot be established
            released = None
    if released is None:
        print("[script-start] acceptance-abort audit SKIPPED: original transaction release could "
              "not be established — refusal preserved, nothing audited")
        return "skipped_unreleased"
    ca = opener()
    try:
        engine.audit_denied(ca, "round", str(round_id or ""),
                            "script_generation_automatic_start_denied",
                            engine.SCRIPT_AUTOMATIC_ACTOR,
                            {"reason": code, "gate_id": gate_id, "released_via": released,
                             "effect": "topic_review acceptance aborted — nothing committed"})
        ca.commit()
        return "audited"
    except Exception:                                  # noqa: BLE001 — the refusal stands regardless
        ca.rollback()
        return "audit_failed"
    finally:
        ca.close()


@app.post("/gates/{gate_id}/resolve")
def resolve(gate_id: str, body: ResolveBody, request: Request):
    c = _conn()
    try:
        outcomes = engine.resolve(c, gate_id, actor=_trusted_approval_actor(request, body.actor, c, gate_id),
                                  slot_ids=body.slot_ids)
        # #310 §A — post-commit execution handoff. A schedule_review acceptance may have enqueued a
        # Topic-generation job IN the (now-committed) acceptance transaction, with NO provider call
        # inside it. Launch the durable dispatch in the BACKGROUND so queued jobs execute; the runner
        # claims each atomically (exactly once), so this is safe even if a later resolve drains again.
        if run_writers is not None:
            pend = engine.pending_topic_generation_jobs(c)
            if pend:
                _cfg = engine.load_config()
                jobs.start("topics", pend[0]["round_id"], "topic",
                           sum((j["slots_total"] or 0) for j in pend),
                           lambda: run_writers.dispatch_pending_topic_generation(_cfg))
            # #359 ruling 5 + review fix 3 — post-commit ACCELERATION, scoped STRICTLY to THIS
            # topic_review acceptance's own queued Script job(s). It is NOT the global drain: an
            # unrelated schedule/script/media gate resolve returns no targets and dispatches nothing.
            # Correctness still does not depend on this — the job is durable and the merged #362 drain
            # recovers it regardless — so a failure here must leave a queued, recoverable job, never
            # erase, replace, or terminalize one. Each specific job is run by id, not by a broad pass.
            try:
                _targets = engine.topic_acceptance_script_targets(c, gate_id)
                if _targets:
                    _scfg = engine.load_config()
                    jobs.start("scripts", gate_id, "script", 0,
                               lambda t=tuple(_targets): [run_writers.run_governed_script_job(_scfg, _j)
                                                          for _j in t])
            except Exception as e:                     # noqa: BLE001 — acceleration is best-effort
                print(f"[script-start] post-commit dispatch skipped (job remains queued): {e}")
        return {"outcomes": outcomes}
    except engine.ScriptAuthorityUnavailable as e:
        # #359 Amendment I / ruling 2 — abort. `engine.resolve()` does NOT roll back on this
        # exception (it propagates out unhandled), so `c` still owns the failed acceptance
        # transaction with its locks live. Roll it back HERE, explicitly, BEFORE the audit — so the
        # separate audit connection never runs alongside a half-open acceptance, and the comment's
        # "AFTER that rollback" is literally true. The refusal stands even if this rollback throws.
        _abort_acceptance_audit(c, e.round_id, gate_id, e.code)
        raise HTTPException(409, f"topic acceptance aborted: {e.code}")
    except engine.GateNotReady as e:
        raise HTTPException(409, str(e))   # #265 — held: no commit against a partial population
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ===========================================================================
# #314 — Bulk Topic disposition + Topic-workbench presentation order (V2 seam)
# ===========================================================================

@app.get("/rounds/{round_id}/topic-presentation")
def get_topic_presentation(round_id: str):
    """#314 — the round's CURRENT accepted Topic-workbench presentation order + its token. `legacy: true`
    (token 0) means no governed presentation order yet: the workbench keeps its current derivation.
    PRESENTATION ONLY — distinct from #292 Schedule order."""
    c = _conn()
    try:
        return engine.topic_presentation(c, round_id)
    finally:
        c.close()


class TopicPresentationReorderBody(BaseModel):
    order: list[str]                             # the COMPLETE ordered slot_id permutation of the round
    topic_presentation_token: int                # optimistic-concurrency token (0 for the first reorder)
    actor: str | None = None


@app.post("/rounds/{round_id}/topic-presentation-reorder")
def reorder_topic_presentation(round_id: str, body: TopicPresentationReorderBody, request: Request):
    """#314 — commit a COMPLETE governed PRESENTATION order for a round's Topic workbench. PRESENTATION
    ONLY: canonical slot_id, #292 Schedule order/token, disposition, approval, taxonomy, config, and Topic
    revision identity are untouched. Stale token -> 409 (typed); reuses #292 schedule_review authority."""
    c = _conn()
    try:
        return engine.reorder_topic_presentation(c, round_id, body.order, body.topic_presentation_token,
                                                 actor=_trusted_actor(request, body.actor))
    except engine.ScheduleConflict as e:
        raise _schedule_conflict(e)
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class BulkItemBody(BaseModel):
    slot_id: str
    expected_revision: int = Field(ge=1)         # MANDATORY per-item CAS: the exact topic head the caller pinned (no NULL=head — #314 exact-current-head discipline)


class BulkOperationBody(BaseModel):
    gate_id: str | None = None                   # optional — omitted => server resolves the round's open topic_review gate
    action: str                                  # bulk_approve | bulk_request_change | bulk_drop
    items: list[BulkItemBody]
    idempotency_key: str                         # replay identity: (round_id, idempotency_key)
    comment: str | None = None                   # shared request_change comment (required for that action)
    actor: str | None = None                     # may only echo the signed principal


@app.post("/rounds/{round_id}/bulk-operations")
def create_bulk_operation(round_id: str, body: BulkOperationBody, request: Request):
    """#314 — create AND drive a bulk Topic disposition over the closed action set {bulk_approve,
    bulk_request_change, bulk_drop}. Each item maps to the existing canonical `decide` command in its own
    transaction; the durable ledger records a TRUTHFUL per-item outcome (succeeded|denied|conflicted|
    stale|failed|not_attempted). Idempotent on (round_id, idempotency_key): a replay resumes/returns the
    same batch. Authority / exact-revision CAS / eligibility / fencing are ALL `decide`'s guarantees."""
    c = _conn()
    try:
        actor = _trusted_actor(request, body.actor)   # signed principal; gate resolved server-side
        items = [{"slot_id": it.slot_id, "expected_revision": it.expected_revision} for it in body.items]
        begun = engine.begin_bulk_operation(c, round_id, body.gate_id, body.action, items, actor,
                                            body.idempotency_key, comment=body.comment)
    except engine.GovernedDenial as e:
        raise HTTPException(409, {"error": "governed_denial", "reason": e.reason, "detail": str(e)})
    except engine.GateError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()
    # drive on independent per-item connections (idempotent + recoverable); returns truthful outcomes
    status = engine.run_bulk_operation(begun["batch_id"], actor=actor)
    return {"resolution": begun["action"], **status}


@app.get("/bulk-operations/{batch_id}")
def read_bulk_operation(batch_id: str, request: Request):
    """#314 — the bulk operation's header + truthful per-item outcomes. GOVERNED read: the caller must be
    an authorized approver of the batch's gate (tenant-scoped by the round's approver set / frozen
    snapshot) — not merely any signed principal. Fail-closed 403 otherwise."""
    actor = _require_trusted_principal(request)
    c = _conn()
    try:
        engine._authorize_bulk_read(c, batch_id, actor)
        return engine.bulk_operation_status(batch_id)
    except engine.GovernedDenial as e:
        raise HTTPException(403, {"error": "governed_denial", "reason": e.reason, "detail": str(e)})
    except engine.GateError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()
