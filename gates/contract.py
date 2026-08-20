"""The Telegram-pilot CONTRACT boundary — one clean, audited tool surface over the gate engine,
scoped to TOPICS + SCRIPTS.

This is the swappable seam the spec asks for: the bot's inline buttons AND the conversational
agent (and, later, the client's own agent over MCP) call the SAME functions here, so every surface
drives the SAME engine and behaves identically to the dashboard by construction. Nothing here forks
engine behaviour — each function is a thin, stateless wrapper (open its own connection, commit,
return plain JSON-able dicts). Mutating calls return {"error": ...} instead of raising, so a chat
or a button can show the message gracefully. The engine remains the single source of truth and
audits every transition; the human stays the committer (see `commit`).

Contract verbs (== the M6 tool set): plan_round · stage_state · digest · request_change · approve ·
reject · undecide · commit · rework · revisions · restore · rework_from · reopen · dropped · awaiting.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import engine  # noqa: E402

try:                      # provider deps optional; rework 503s cleanly if the writer can't load
    import run_writers as _W  # noqa: E402
except Exception:         # noqa: BLE001
    _W = None

# Topics + scripts only — production/edit/distribution are deferred in Telegram for now.
_STAGE = {"topic": "topic_review", "script": "script_review"}
ARTIFACTS = tuple(_STAGE)


def _cfg():
    return engine.load_config()


def _artifact(a):
    """Normalise 'topic'|'topic_review'|'script'|'script_review' -> 'topic'|'script'."""
    a = (a or "").replace("_review", "")
    if a not in _STAGE:
        raise ValueError(f"artifact must be one of {ARTIFACTS} (topics+scripts only) — got {a!r}")
    return a


def _stage(a):
    return _STAGE[_artifact(a)]


def _conn():
    return engine.db_connect()


def _active_gate(conn, round_id, stage, *, actor, open_if_missing):
    """The active OPEN gate for this round+stage. `open_gate` is idempotent for round-scoped opens
    (it reuses an existing open gate), so this never creates a duplicate."""
    gates = [g for g in engine.list_gates(conn, status="open", round_id=round_id)
             if g["stage"] == stage]
    if gates:
        return gates[0]["gate_id"]
    if open_if_missing:
        return engine.open_gate(conn, stage, round_id=round_id, actor=actor, cfg=_cfg())
    return None


# --------------------------------------------------------------------------- #
# READ — status / digest (no mutation)
# --------------------------------------------------------------------------- #
def plan_round(round_id=None):
    """No id -> the round list (each with its human phase). An id -> that round's status: phase +
    the topic & script stage states (graceful: ready_to_start / reviewing / ready_to_commit /
    awaiting_regeneration / complete / empty) + awaiting/dropped counts."""
    conn = _conn()
    try:
        rounds = engine.list_rounds(conn)
        if not round_id:
            return {"rounds": rounds}
        row = next((r for r in rounds if r["round_id"] == round_id), None)
        if not row:
            return {"error": f"no round {round_id}"}
        cfg = _cfg()
        return {"round_id": round_id, "phase": row.get("phase"), "counts": row,
                "stages": {a: engine.stage_state(conn, round_id, _STAGE[a], cfg=cfg) for a in ARTIFACTS},
                "awaiting": len(engine.list_changes_requested(conn, round_id=round_id, cfg=cfg)),
                "dropped": len(engine.list_dropped(conn, round_id=round_id, cfg=cfg))}
    finally:
        conn.close()


def stage_state(round_id, artifact):
    """The engine read model for a stage: lifecycle state + advisory (recommendation + warnings)."""
    conn = _conn()
    try:
        return engine.stage_state(conn, round_id, _stage(artifact), cfg=_cfg())
    finally:
        conn.close()


def topic_generation(round_id):
    """#310 §F — the Stage 2A Topic-generation read model (OBSERVE): durable job phase/counts/error +
    per-slot results + provenance disclosure. Read-only; the agent observes/explains/recommends from it
    but never starts or retries generation itself (those stay behind the confirmed human binding)."""
    conn = _conn()
    try:
        return engine.topic_generation_read_model(conn, round_id)
    finally:
        conn.close()


def digest(round_id, artifact, *, actor):
    """Summary-first review digest: opens/loads the active review, returns live tallies, a by-pillar
    breakdown, flag counts, the per-item content (business lexicon: hook + why-now [+ script]), and
    the engine advisory. The SAME data the dashboard renders — just summarised for Telegram."""
    stage = _stage(artifact)
    art = _artifact(artifact)
    conn = _conn()
    try:
        gid = _active_gate(conn, round_id, stage, actor=actor, open_if_missing=True)
        gate = engine.get_gate(conn, gid)
        ss = engine.stage_state(conn, round_id, stage, cfg=_cfg())
        by_pillar, scholar, native, items = {}, 0, 0, []
        for t in gate["targets"]:
            by_pillar[t["pillar_code"]] = by_pillar.get(t["pillar_code"], 0) + 1
            scholar += 1 if t.get("needs_scholar_review") else 0
            native += 1 if t.get("needs_native_review") else 0
            last = t["decisions"][-1]["decision"] if t["decisions"] else None
            item = {"slot_id": t["slot_id"], "pillar_code": t["pillar_code"], "hcs_id": t["hcs_id"],
                    "hook_text": t.get("hook_text"), "rationale_ar": t.get("rationale_ar"),
                    "rationale_en": t.get("rationale_en"), "decision": last,
                    "revision": t.get("script_revision") if art == "script" else t.get("topic_revision"),
                    "needs_scholar_review": t.get("needs_scholar_review"),
                    "needs_native_review": t.get("needs_native_review")}
            if art == "script" and t.get("script_ar"):
                s = " ".join(t["script_ar"].split())
                item["script_ar"] = s
            items.append(item)
        return {"round_id": round_id, "artifact": art, "stage": stage, "gate_id": str(gid),
                "state": ss.get("state"), "recommendation": ss.get("recommendation"),
                "warnings": ss.get("warnings", []), "confirm_warnings": ss.get("confirm_warnings", []),
                "by_pillar": by_pillar,
                "flags": {"needs_scholar_review": scholar, "needs_native_review": native},
                "tallies": {"in_review": ss.get("in_review", 0), "approved": ss.get("approved", 0),
                            "sent_back": ss.get("sent_back", 0), "rejected": ss.get("rejected", 0),
                            "pending": ss.get("pending", 0), "awaiting": ss.get("awaiting", 0),
                            "dropped": ss.get("dropped", 0), "advanced": ss.get("advanced", 0)},
                "items": items}
    except engine.GateError as e:
        return {"error": str(e)}
    finally:
        conn.close()


def awaiting(round_id):
    """Slots awaiting regeneration (sent back) for a round, with the reviewer comment."""
    conn = _conn()
    try:
        return engine.list_changes_requested(conn, round_id=round_id, cfg=_cfg())
    finally:
        conn.close()


def dropped(round_id):
    """Slots in the reversible 'dropped' (rejected) state for a round — recoverable via reopen()."""
    conn = _conn()
    try:
        return engine.list_dropped(conn, round_id=round_id, cfg=_cfg())
    finally:
        conn.close()


def revisions(slot_id, artifact):
    """The linear version history for a slot's artifact (each version + comment + provenance)."""
    conn = _conn()
    try:
        return engine.list_revisions(conn, slot_id, artifact=_artifact(artifact))
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# WRITE — per-item decisions (recorded; they DON'T advance until commit)
# --------------------------------------------------------------------------- #
def _decide(round_id, artifact, decision, slot_ids, actor, notes=None, revision=None,
            expected_revision=None, eligibility_check=False):
    stage = _stage(artifact)
    conn = _conn()
    try:
        # #313 P1-A — open/resolve the gate first (idempotent), THEN decide with the CAS/eligibility
        # enforced under a slot lock inside decide's single atomic transaction (no TOCTOU).
        gid = _active_gate(conn, round_id, stage, actor=actor, open_if_missing=True)
        touched = engine.decide(conn, gid, actor, decision, slot_ids=slot_ids, notes=notes,
                                revision=revision, cfg=_cfg(),
                                expected_revision=expected_revision, eligibility_check=eligibility_check)
        return {"ok": True, "gate_id": str(gid), "touched": touched, "decision": decision, "revision": revision}
    except engine.RevisionConflict as e:
        return {"stale_revision": True, "current": e.current, "error": str(e)}
    except engine.GovernedDenial as e:
        return {"governed_denial": e.reason, "error": str(e)}
    except engine.GateError as e:
        return {"error": str(e)}
    finally:
        conn.close()


def approve(round_id, artifact, slot_ids=None, *, actor, revision=None, expected_revision=None):
    """Record an approval (None/empty slot_ids = the whole batch). Recorded, not yet advanced. #313 —
    `revision` pins the EXACT approved revision (the one the caller saw), never latest/head; and
    `expected_revision` (P1-A) is CAS-checked against head UNDER a slot lock in the SAME transaction that
    records the decision — a concurrent edit/rework can never make the approval attach to a non-head
    revision."""
    return _decide(round_id, artifact, "approve", slot_ids, actor, revision=revision,
                   expected_revision=expected_revision)


def reject(round_id, artifact, slot_id, *, actor, reason=None, eligibility_check=False):
    """Reversible DROP — recoverable (restore via reopen). Distinct from request_change. #313 —
    `eligibility_check` (P1-A) enforces the approved/downstream-advanced #249 boundary UNDER a slot lock
    in the SAME transaction that records the reject decision — no post-approval/downstream reject."""
    return _decide(round_id, artifact, "reject", [slot_id], actor, notes=reason,
                   eligibility_check=eligibility_check)


def request_change(round_id, artifact, slot_id, comment, *, actor):
    """Send an item back for regeneration WITH a comment (the comment IS the rework directive)."""
    if not (comment or "").strip():
        return {"error": "a comment is required to send an item back (it guides the regeneration)"}
    return _decide(round_id, artifact, "request_change", [slot_id], actor, notes=comment)


def undecide(round_id, artifact, slot_id, *, actor):
    """Pre-commit undo: clear a recorded decision on an item (back to pending)."""
    stage = _stage(artifact)
    conn = _conn()
    try:
        gid = _active_gate(conn, round_id, stage, actor=actor, open_if_missing=False)
        if not gid:
            return {"error": "no open review to undo"}
        return engine.clear_decision(conn, gid, actor, slot_ids=[slot_id], actor=actor, cfg=_cfg())
    except engine.GateError as e:
        return {"error": str(e)}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# COMMIT — the human-confirmed checkpoint (hard floor: never auto)
# --------------------------------------------------------------------------- #
def commit(round_id, artifact, *, actor, confirmed=False):
    """Advance APPROVED items to the next stage (the engine's resolve) — parks sent-back/dropped
    items (recoverable). HARD FLOOR: this only runs on an explicit human confirmation (confirmed=
    True). An agent may recommend it, but committing is a human gate (Unified Actor Model)."""
    if not confirmed:
        return {"error": "commit is a human-confirmed action — confirm to advance the approved items"}
    stage = _stage(artifact)
    conn = _conn()
    try:
        gid = engine.stage_state(conn, round_id, stage, cfg=_cfg()).get("gate_id")
        if not gid:
            return {"error": "no open review to commit"}
        outcomes = engine.resolve(conn, gid, actor=actor, cfg=_cfg())
        return {"ok": True, "gate_id": str(gid), "outcomes": outcomes}
    except engine.GateError as e:
        return {"error": str(e)}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CYCLIC REGENERATE + VERSION NAVIGATION + REVERSIBLE RECOVERY
# --------------------------------------------------------------------------- #
def rework(round_id, artifact, dry_run=False):
    """Regenerate the round's sent-back items in this stage (the reviewer comment is injected as the
    rework directive) -> a new revision, back for re-review. Background under the real writer; the
    deterministic stub runs synchronously (tests)."""
    art = _artifact(artifact)
    cfg = _cfg()
    conn = _conn()
    try:
        targets = [r["slot_id"] for r in engine.list_changes_requested(conn, round_id=round_id, cfg=cfg)]
    finally:
        conn.close()
    if dry_run or not targets:
        return {"would_rework": len(targets), "slots": targets, "started": 0, "dry_run": dry_run}
    if _W is None:
        return {"error": "the regeneration writer is unavailable here"}
    _W.rework_round(cfg, art, round_id=round_id, quiet=True)
    return {"started": len(targets), "slots": targets, "dry_run": False}


def restore(slot_id, artifact, revision, *, actor):
    """Restore an older revision as the new HEAD (linear, append-only) and send the item back for
    re-review. A subsequent comment reworks from there."""
    conn = _conn()
    try:
        res = engine.restore_revision(conn, slot_id, _artifact(artifact), revision, actor=actor, cfg=_cfg())
        return {"ok": True, **res}
    except engine.GateError as e:
        return {"error": str(e)}
    finally:
        conn.close()


def rework_from(slot_id, artifact, revision, comment, *, actor):
    """Restore revision N as the new HEAD, then regenerate from it addressing `comment`."""
    if not (comment or "").strip():
        return {"error": "a comment is required to rework from a version"}
    art = _artifact(artifact)
    cfg = _cfg()
    conn = _conn()
    try:
        engine.restore_revision(conn, slot_id, art, revision, actor=actor, cfg=cfg)
    except engine.GateError as e:
        return {"error": str(e)}
    finally:
        conn.close()
    if _W is None:
        return {"error": "the regeneration writer is unavailable here"}
    _W.rework_one(cfg, art, slot_id, comment.strip())
    return {"ok": True, "restored_from": revision, "reworked": True}


def reopen(slot_id, *, actor):
    """Restore a dropped (rejected) item — or reverse an approval — back into review. Nothing is
    destroyed; a new audited event records the reversal ('git for content')."""
    conn = _conn()
    try:
        return engine.reopen(conn, slot_id, actor=actor, cfg=_cfg())
    except engine.GateError as e:
        return {"error": str(e)}
    finally:
        conn.close()
