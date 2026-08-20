"""pub.v1 (#199/#200) — first-class publication persistence + governed MANUAL recording.

A pure module (no engine import, like dam/directives) so the spine can import it without cycles;
callers pass the loaded config. Publication is NOT a media asset version: it has its own
identities (intent vs durable occurrence), a DB-enforced idempotency domain, append-only events,
and exact approved-source lineage. Manual recording is a first-class canonical source — never
simulated provider data. This slice writes ONLY: intent creation + the bounded manual
attempt/outcome. Cancellation/reconciliation/correction/retraction exist as reserved typed events
(migration 022) with no commands here.

Eligibility and authority are two separate predicates (#199 D4), both re-evaluated at intent
creation AND at successful manual outcome recording:
  * content eligibility — committed truth only (#9-safe): the slot reached the distribution
    stage's approve_to status AND a resolved distribution gate with a committed approve exists;
    plus the DISTINCT upstream prerequisites: resolved production approval, SDAM raw/raw-cut
    readiness assets, resolved edit approval, and the exact ACTIVE final approved Edit output
    (never inferred from asset presence alone — the gates are required evidence).
  * actor authority — the actor must be named by a DIRECT user assignment on the distribution
    gate's snapshot (#9-safe: role/group membership churn after the snapshot is ambiguous, so
    those paths grant nothing in this slice). Signed identity, asset-write access, or URL
    possession grant nothing.
"""
import uuid
from datetime import datetime

import psycopg2.errors
import psycopg2.extras
from psycopg2.extras import Json

CONTRACT_VERSION = "pub.v1"
ACCOUNTLESS = "-"                      # contract-defined deterministic accountless destination
FIELD_LIMITS = {"platform_key": 100, "destination": 300, "url": 1000, "external_ref": 500,
                "external_object_type": 100, "idempotency_key": 200,
                "destination_account_scope": 300, "provider_key": 100, "notes": 1000}
# states derivable from the append-only event stream (last event wins)
_STATE_BY_EVENT = {
    "intent_created": "ready",
    "scheduled": "scheduled",
    "attempt_started": "attempt-in-progress",
    "attempt_failed": "attempt-failed",
    "attempt_cancelled": "attempt-cancelled",
    "cancelled": "cancelled",
    "published_manually_attested": "published (manually attested)",
    "published_externally_confirmed": "published (externally confirmed)",
    "reconciled": "published (externally confirmed)",
    "corrected_by": "corrected",
    "retracted": "retracted",
}
_TERMINAL_STATES = {"published (manually attested)", "published (externally confirmed)",
                    "cancelled", "corrected", "retracted"}


class PublicationError(Exception):
    """Raised for every refused operation; messages are client-safe. 'conflict:' prefix marks
    explicit conflicts (duplicate/changed-key-data/stale/terminal) for HTTP 409 mapping."""


def _audit(cur, entity_id, action, actor, detail):
    cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
                "VALUES ('publication', %s, %s, %s, "
                "  COALESCE((SELECT kind::text FROM principal WHERE principal_id=%s), 'unknown'), %s)",
                (str(entity_id), action, actor, actor, Json(detail)))


def _denied(conn, entity_id, actor, detail):
    """Attributable denial in its OWN committed transaction (survives the raise); call only while
    the transaction holds no partial writes."""
    try:
        conn.rollback()
        cur = conn.cursor()
        _audit(cur, entity_id, "publication_denied", actor, detail)
        conn.commit()
        cur.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _field(payload, name, required=False):
    raw = payload.get(name)
    if raw is None or raw == "":
        if required:
            raise PublicationError(f"{name} is required")
        return None
    if not isinstance(raw, str):
        raise PublicationError(f"{name} must be a string")
    if len(raw) > FIELD_LIMITS[name]:
        raise PublicationError(f"{name} exceeds {FIELD_LIMITS[name]} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise PublicationError(f"{name} contains control characters")
    return raw


def _distribution_cfg(cfg):
    gc = ((cfg or {}).get("gates") or {}).get("distribution_review") or {}
    return {"approve_to": gc.get("approve_to", "SCHEDULED")}


def eligibility_evidence(cur, cfg, slot_id):
    """The committed-truth prerequisite chain, or a PublicationError naming what is missing.
    Returns the exact stable references frozen onto the publication row."""
    cur.execute("SELECT slot_id, status::text AS status, round_id FROM slot WHERE slot_id=%s", (slot_id,))
    slot = cur.fetchone()
    if not slot:
        raise PublicationError(f"unknown content item {slot_id}")
    approve_to = _distribution_cfg(cfg)["approve_to"]
    if slot["status"] != approve_to:
        raise PublicationError("this item has not passed publishing approval yet")

    def _approved_gate(stage):
        # committed truth ONLY: the gate must be RESOLVED to 'approved' (an approve decision on an
        # open/partial/rejected/changes-requested gate is not a committed approval and never counts)
        cur.execute("""SELECT g.gate_id FROM gate g
                       JOIN gate_target t ON t.gate_id = g.gate_id AND t.slot_id = %s
                       JOIN gate_decision d ON d.gate_id = g.gate_id
                            AND (d.slot_id = %s OR d.slot_id IS NULL) AND d.decision = 'approve'
                       WHERE g.stage = %s AND g.status = 'approved'
                       ORDER BY g.created_at DESC LIMIT 1""", (slot_id, slot_id, stage))
        row = cur.fetchone()
        return row["gate_id"] if row else None

    distribution_gate = _approved_gate("distribution_review")
    if not distribution_gate:
        raise PublicationError("no committed publishing approval exists for this item")
    production_gate = _approved_gate("production_review")
    if not production_gate:
        raise PublicationError("this item has no committed production approval")
    edit_gate = _approved_gate("edit_review")
    if not edit_gate:
        raise PublicationError("this item has no committed edit approval")

    cur.execute("""SELECT asset_id FROM asset
                   WHERE slot_id=%s AND stage='production' AND kind IN ('raw', 'raw_cut')
                     AND status='active' ORDER BY asset_id""", (slot_id,))
    raw_ids = [r["asset_id"] for r in cur.fetchall()]
    if not raw_ids:
        raise PublicationError("no raw footage is registered for this item")
    cur.execute("""SELECT asset_id, version, platform_variant FROM asset
                   WHERE slot_id=%s AND stage='media_edit' AND kind='edit' AND status='active'
                   ORDER BY version DESC LIMIT 1""", (slot_id,))
    edit_output = cur.fetchone()
    if not edit_output:
        raise PublicationError("no final approved edit exists for this item — raw footage alone "
                               "cannot be published")
    cur.execute("""SELECT script_id FROM script WHERE slot_id=%s
                   ORDER BY revision DESC, created_at DESC LIMIT 1""", (slot_id,))
    script = cur.fetchone()
    return {
        "slot_id": slot["slot_id"],
        "script_id": script["script_id"] if script else None,
        "edit_output_asset_id": edit_output["asset_id"],
        "edit_output_version": edit_output["version"],
        "edit_output_rendition": edit_output["platform_variant"],
        "distribution_gate_id": distribution_gate,
        "production_gate_id": production_gate,
        "edit_gate_id": edit_gate,
        "raw_asset_ids": raw_ids,
    }


def actor_may_attest(cur, actor, distribution_gate_id):
    """Actor authority — the evidenced UNAMBIGUOUS path only: an active user principal named by a
    DIRECT user assignment on the distribution gate's snapshot. Role/group membership is
    deliberately NOT honored here: membership churn after the snapshot makes those paths ambiguous
    while #9's assignment-basis persistence is unresolved. A snapshot-less gate grants nothing.
    Widening beyond direct-user requires a future directive, never a default."""
    cur.execute("SELECT kind::text AS kind, active FROM principal WHERE principal_id=%s", (actor,))
    p = cur.fetchone()
    if not p or not p["active"] or p["kind"] != "user":
        return False
    cur.execute("""SELECT 1 FROM gate_assignment
                   WHERE gate_id=%s AND assignment_kind='user' AND assignment_key=%s""",
                (distribution_gate_id, actor))
    return cur.fetchone() is not None


def _platform_known(cur, platform_key):
    cur.execute("""SELECT 1 FROM platform WHERE platform_key=%s AND active=true""", (platform_key,))
    return cur.fetchone() is not None


def _next_seq(cur, intent_id):
    """Atomic per-intent sequence: the publication row is locked FOR UPDATE by the caller's
    transaction before this runs; UNIQUE (intent, seq) remains the final arbiter."""
    cur.execute("SELECT COALESCE(max(event_seq), 0) + 1 AS s FROM publication_event "
                "WHERE publication_intent_id=%s", (str(intent_id),))
    return cur.fetchone()["s"]


def _event(cur, intent_id, seq, event_type, source, actor, detail, occurred_at=None,
           provider_reported_at=None):
    cur.execute("""INSERT INTO publication_event
                   (publication_intent_id, event_seq, event_type, event_source, actor, detail,
                    occurred_at, provider_reported_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (str(intent_id), seq, event_type, source, actor, Json(detail),
                 occurred_at, provider_reported_at))


def _uuid_or_none(value, name):
    """Validate id inputs BEFORE they reach SQL: a malformed id is an invalid request (400-class
    denial), never a database type error surfacing as a 500."""
    if value is None or value == "":
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise PublicationError(f"{name} is not a valid id")


def _row(cur, intent_id):
    cur.execute("SELECT * FROM publication WHERE publication_intent_id=%s", (str(intent_id),))
    return cur.fetchone()


def _ids_eq(a, b):
    if a is None or b is None:
        return a is None and b is None
    return str(a) == str(b)


def _raw_ids(cur, intent_id):
    """The frozen raw readiness set — normalized publication_raw_asset rows (native NO ACTION
    FKs), read in stable order for set comparison and the read model."""
    cur.execute("SELECT asset_id FROM publication_raw_asset WHERE publication_intent_id=%s "
                "ORDER BY asset_id", (str(intent_id),))
    return [str(r["asset_id"]) for r in cur.fetchall()]


def _stale_lineage_fields(cur, pub, evidence):
    """The frozen lineage the intent bound at creation vs the CURRENT committed eligibility
    evidence — every field, not just the edit output. Any drift means the frozen truth no longer
    describes what would be published, so outcome recording must fail closed (the drifted fields
    are named in the attributable denial audit)."""
    stale = []
    if not _ids_eq(pub["distribution_gate_id"], evidence["distribution_gate_id"]):
        stale.append("distribution_gate_id")
    if not _ids_eq(pub["production_gate_id"], evidence["production_gate_id"]):
        stale.append("production_gate_id")
    if not _ids_eq(pub["edit_gate_id"], evidence["edit_gate_id"]):
        stale.append("edit_gate_id")
    if not _ids_eq(pub["script_id"], evidence["script_id"]):
        stale.append("script_id")
    if not _ids_eq(pub["edit_output_asset_id"], evidence["edit_output_asset_id"]):
        stale.append("edit_output_asset_id")
    if pub["edit_output_version"] != evidence["edit_output_version"]:
        stale.append("edit_output_version")
    if pub["edit_output_rendition"] != evidence["edit_output_rendition"]:
        stale.append("edit_output_rendition")
    if (_raw_ids(cur, pub["publication_intent_id"])
            != sorted(str(x) for x in evidence["raw_asset_ids"])):
        stale.append("raw_asset_ids")
    return stale


def _bound_fields_match(cur, existing, evidence, payload, provider_key, scope, destination,
                        corrects):
    """Exact replay = EVERY bound immutable field identical: destination scoping, the full frozen
    lineage (script revision, edit output asset+version+rendition, all three gates, raw readiness
    set), and the correction link. Any difference under the same key is a hard conflict."""
    return (existing["provider_key"] == provider_key
            and existing["destination_account_scope"] == scope
            and existing["platform_key"] == payload.get("platform_key")
            and existing["destination"] == destination
            and existing["execution_source"] == "manual"
            and existing["contract_version"] == CONTRACT_VERSION
            and str(existing["slot_id"]) == evidence["slot_id"]
            and _ids_eq(existing["script_id"], evidence["script_id"])
            and str(existing["edit_output_asset_id"]) == str(evidence["edit_output_asset_id"])
            and existing["edit_output_version"] == evidence["edit_output_version"]
            and existing["edit_output_rendition"] == evidence["edit_output_rendition"]
            and _ids_eq(existing["distribution_gate_id"], evidence["distribution_gate_id"])
            and _ids_eq(existing["production_gate_id"], evidence["production_gate_id"])
            and _ids_eq(existing["edit_gate_id"], evidence["edit_gate_id"])
            and _raw_ids(cur, existing["publication_intent_id"])
                == sorted(str(x) for x in evidence["raw_asset_ids"])
            and _ids_eq(existing["corrects_publication_intent_id"], corrects))


def create_intent(conn, cfg, payload, actor):
    """Idempotent intent creation. The caller supplies a PRE-RESERVED stable idempotency_key
    (generated before the first mutation and identical across retries). Exact replay returns the
    existing truth; the same key with ANY different bound immutable field is a hard conflict."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        try:
            slot_id = str(payload.get("slot_id") or "")
            if not slot_id:
                raise PublicationError("slot_id is required")
            platform_key = _field(payload, "platform_key", required=True)
            idempotency_key = _field(payload, "idempotency_key", required=True)
            provider_key = _field(payload, "provider_key") or "manual"
            scope = _field(payload, "destination_account_scope") or ACCOUNTLESS
            destination = _field(payload, "destination")
            url = _field(payload, "url")
            corrects = _uuid_or_none(payload.get("corrects_publication_intent_id"),
                                     "corrects_publication_intent_id")
            if not _platform_known(cur, platform_key):
                raise PublicationError(f"unknown platform {platform_key!r}")
            if corrects and not _row(cur, corrects):
                raise PublicationError("corrects_publication_intent_id is not a known publication")
        except PublicationError as e:
            _denied(conn, payload.get("slot_id") or "-", actor,
                    {"operation": "create_intent", "reason": "invalid_input", "error": str(e)[:300]})
            raise
        try:
            evidence = eligibility_evidence(cur, cfg, slot_id)
        except PublicationError as e:
            _denied(conn, slot_id, actor,
                    {"operation": "create_intent", "reason": "not_eligible", "error": str(e)[:300]})
            raise
        if not actor_may_attest(cur, actor, evidence["distribution_gate_id"]):
            _denied(conn, slot_id, actor,
                    {"operation": "create_intent", "reason": "not_authorized"})
            raise PublicationError(f"{actor!r} may not record publications for this item")

        cur.execute("""INSERT INTO publication
                       (contract_version, execution_source, provider_key, destination_account_scope,
                        platform_key, destination, url, idempotency_key,
                        slot_id, script_id, edit_output_asset_id, edit_output_version,
                        edit_output_rendition, distribution_gate_id, production_gate_id,
                        edit_gate_id, corrects_publication_intent_id, created_by)
                       VALUES ('pub.v1', 'manual', %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (provider_key, destination_account_scope, idempotency_key)
                       DO NOTHING
                       RETURNING publication_intent_id""",
                    (provider_key, scope, platform_key, destination, url, idempotency_key,
                     evidence["slot_id"], evidence["script_id"], evidence["edit_output_asset_id"],
                     evidence["edit_output_version"], evidence["edit_output_rendition"],
                     evidence["distribution_gate_id"], evidence["production_gate_id"],
                     evidence["edit_gate_id"], corrects, actor))
        made = cur.fetchone()
        if made:
            intent_id = made["publication_intent_id"]
            # the frozen raw readiness set — MUST land before the first event (the junction's
            # freeze trigger pins set membership once the intent has any history)
            cur.execute("""INSERT INTO publication_raw_asset (publication_intent_id, asset_id)
                           SELECT %s, unnest(%s::uuid[])""",
                        (str(intent_id), [str(x) for x in evidence["raw_asset_ids"]]))
            _event(cur, intent_id, 1, "intent_created", "manual", actor,
                   {"platform_key": platform_key, "idempotency_key": idempotency_key})
            _audit(cur, intent_id, "publication_intent_created", actor,
                   {"slot_id": slot_id, "platform_key": platform_key,
                    "edit_output_asset_id": str(evidence["edit_output_asset_id"])})
            conn.commit()
            return get_publication(conn, intent_id)
        # idempotency-domain hit: exact replay OR changed-data conflict
        conn.rollback()
        cur.execute("""SELECT * FROM publication
                       WHERE provider_key=%s AND destination_account_scope=%s AND idempotency_key=%s""",
                    (provider_key, scope, idempotency_key))
        existing = cur.fetchone()
        if existing and _bound_fields_match(cur, existing, evidence, payload, provider_key, scope,
                                            destination, corrects):
            return get_publication(conn, existing["publication_intent_id"])   # exact replay
        _denied(conn, slot_id, actor,
                {"operation": "create_intent", "reason": "idempotency_key_conflict",
                 "idempotency_key": idempotency_key})
        raise PublicationError("conflict: this operation key was already used with different "
                               "publication data — a changed publication needs a new operation")
    finally:
        cur.close()


def record_manual_outcome(conn, cfg, intent_id, payload, actor):
    """The bounded manual attempt + attested outcome ('published' | 'failed'). Eligibility and
    attestation authority are re-evaluated here; stale/reopened/superseded lineage denies success.
    Success sets the durable occurrence exactly once."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        try:
            intent_id = _uuid_or_none(intent_id, "publication id")
            if not intent_id:
                raise PublicationError("publication id is required")
            outcome = str(payload.get("outcome") or "")
            if outcome not in ("published", "failed"):
                raise PublicationError("outcome must be 'published' or 'failed'")
            url = _field(payload, "url")
            external_ref = _field(payload, "external_ref")
            external_object_type = _field(payload, "external_object_type")
            notes = _field(payload, "notes")
            occurred_at = payload.get("occurred_at")
            if occurred_at is not None:
                if not isinstance(occurred_at, str):
                    raise PublicationError("occurred_at must be an ISO-8601 timestamp string")
                try:
                    datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
                except ValueError:
                    raise PublicationError("occurred_at is not a valid ISO-8601 timestamp")
        except PublicationError as e:
            _denied(conn, str(intent_id), actor,
                    {"operation": "record_manual_outcome", "reason": "invalid_input",
                     "error": str(e)[:300]})
            raise

        cur.execute("SELECT * FROM publication WHERE publication_intent_id=%s FOR UPDATE",
                    (str(intent_id),))
        pub = cur.fetchone()
        if not pub:
            _denied(conn, str(intent_id), actor,
                    {"operation": "record_manual_outcome", "reason": "unknown_publication"})
            raise PublicationError("unknown publication")
        if pub["publication_occurrence_id"] is not None:
            conn.rollback()
            _denied(conn, str(intent_id), actor,
                    {"operation": "record_manual_outcome", "reason": "already_published"})
            raise PublicationError("conflict: this publication is already recorded — a corrected "
                                   "repost is a new linked publication, never a change to this one")
        # re-evaluate BOTH predicates at success recording (stale lineage denies)
        try:
            evidence = eligibility_evidence(cur, cfg, pub["slot_id"])
        except PublicationError as e:
            conn.rollback()
            _denied(conn, str(intent_id), actor,
                    {"operation": "record_manual_outcome", "reason": "stale_eligibility",
                     "error": str(e)[:300]})
            raise PublicationError(f"conflict: approvals changed since this was prepared — {e}")
        stale = _stale_lineage_fields(cur, pub, evidence)
        if stale:
            conn.rollback()
            _denied(conn, str(intent_id), actor,
                    {"operation": "record_manual_outcome", "reason": "stale_lineage",
                     "stale_fields": stale})
            raise PublicationError("conflict: the approved source changed since this was prepared "
                                   f"({', '.join(stale)}) — record a new publication for the "
                                   "current truth instead")
        if not actor_may_attest(cur, actor, pub["distribution_gate_id"]):
            conn.rollback()
            _denied(conn, str(intent_id), actor,
                    {"operation": "record_manual_outcome", "reason": "not_authorized"})
            raise PublicationError(f"{actor!r} may not record publications for this item")

        seq = _next_seq(cur, intent_id)
        _event(cur, intent_id, seq, "attempt_started", "manual", actor,
               {"notes": notes} if notes else {})
        if outcome == "failed":
            _event(cur, intent_id, seq + 1, "attempt_failed", "manual", actor,
                   {"reason": (notes or "not recorded")[:300]})
            _audit(cur, intent_id, "publication_attempt_failed", actor, {"slot_id": pub["slot_id"]})
            conn.commit()
            return get_publication(conn, intent_id)
        try:
            cur.execute("""UPDATE publication
                           SET publication_occurrence_id = gen_random_uuid(),
                               attested_by = %s,
                               url = COALESCE(%s, url),
                               external_ref = %s,
                               external_object_type = %s,
                               occurred_at = COALESCE(%s::timestamptz, now()),
                               recorded_at = now()
                           WHERE publication_intent_id = %s""",
                        (actor, url, external_ref, external_object_type, occurred_at,
                         str(intent_id)))
        except psycopg2.errors.UniqueViolation:
            # the scoped external-ref uniqueness (provider, account scope, object type, ref) —
            # the same provider-local object can never be claimed by two publications
            _denied(conn, str(intent_id), actor,
                    {"operation": "record_manual_outcome", "reason": "external_ref_conflict",
                     "external_ref": external_ref})
            raise PublicationError("conflict: that post reference is already recorded on another "
                                   "publication")
        _event(cur, intent_id, seq + 1, "published_manually_attested", "manual", actor,
               {"url": url, "external_ref": external_ref, "notes": notes},
               occurred_at=occurred_at)
        _audit(cur, intent_id, "publication_recorded", actor,
               {"slot_id": pub["slot_id"], "platform_key": pub["platform_key"], "url": url})
        conn.commit()
        return get_publication(conn, intent_id)
    finally:
        cur.close()


def derive_state(events):
    if not events:
        return "ready"
    return _STATE_BY_EVENT.get(events[-1]["event_type"], "unknown")


def get_publication(conn, intent_id):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    pub = _row(cur, intent_id)
    if not pub:
        cur.close()
        return None
    cur.execute("""SELECT event_seq, event_type, event_source, actor, detail, occurred_at, created_at
                   FROM publication_event WHERE publication_intent_id=%s ORDER BY event_seq""",
                (str(intent_id),))
    events = cur.fetchall()
    pub["raw_asset_ids"] = _raw_ids(cur, intent_id)   # read-model field name is API contract
    cur.close()
    pub["events"] = events
    pub["current_state"] = derive_state(events)
    return pub


def list_publications(conn, slot_id=None, round_id=None, limit=50):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = """SELECT p.* FROM publication p JOIN slot s ON s.slot_id = p.slot_id WHERE true"""
    params = []
    if slot_id:
        q += " AND p.slot_id=%s"; params.append(slot_id)
    if round_id:
        q += " AND s.round_id=%s"; params.append(round_id)
    q += " ORDER BY p.created_at DESC LIMIT %s"; params.append(max(1, min(int(limit or 50), 100)))
    cur.execute(q, params)
    rows = cur.fetchall()
    for r in rows:
        cur.execute("""SELECT event_seq, event_type, event_source, actor, occurred_at, created_at
                       FROM publication_event WHERE publication_intent_id=%s ORDER BY event_seq""",
                    (str(r["publication_intent_id"]),))
        r["events"] = cur.fetchall()
        r["raw_asset_ids"] = _raw_ids(cur, r["publication_intent_id"])
        r["current_state"] = derive_state(r["events"])
    cur.close()
    return rows
