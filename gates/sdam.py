"""SDAM (ResourceSpace) read-only adapter — #244.

Provider-neutral identity binding + append-only readiness observations. SDAM/ResourceSpace stays
authoritative for files/renditions/metadata/taxonomy/workflow/permissions/history; Tanaghom persists
ONLY (1) an opaque provider-neutral identity binding and (2) minimum immutable decision-provenance
evidence. This module is READ-ONLY toward ResourceSpace (restricted `stitch_readonly` userkey). The
application-side `sdam.append` write guard is a trial convention, NOT a DB authority boundary.

ResourceSpace-specific external-ref shape validation lives HERE (not the DB), preserving the
anti-coupling boundary. A future provider is an additive vocabulary change — no gate-engine change.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from psycopg2.extras import Json

PROVIDER = "resourcespace"
VIDEO_RESOURCE_TYPE = 3
TANAGHOM_FIELD_REF = 99
READINESS_FIELD_REF = 100      # #259 S2 — tanaghom_readiness projection (machine token only)
PENDING_ARCHIVE = -2           # completed-edit resources register at Pending Submission
PROJECTION_GENERATION = 1      # gN prefix for the reversible field-100 token
DIGEST_ALGO = "sha256"
DIGEST_SCHEMA_VERSION = 1
MAPPING_VERSION = 1
DEFAULT_POLICY_VERSION = 1

# result_code -> retry_class (mirrors the DB CHECK matrix; single source in-app)
RETRY_BY_RESULT = {
    "ready": "refresh_ttl",
    "not_ready_pending": "retry_pending",
    "unavailable": "retry_backoff",
    "not_ready_missing": "retry_reconcile",
    "unauthorized": "no_retry",
    "malformed": "no_retry",
    "not_ready_lineage_mismatch": "no_retry",
    "not_ready_taxonomy_mismatch": "no_retry",
    "not_ready_ambiguous": "no_retry",
}
_DIGEST_BEARING = {"ready", "not_ready_lineage_mismatch", "not_ready_taxonomy_mismatch"}
# RS workflow/archive states (evidence only; never persisted raw)
_PENDING = {-2, -1}   # Pending Submission / Pending Review -> not consumable, not missing
_ACTIVE = 0


class SdamUnavailable(Exception):
    """transport / 5xx / timeout -> result_code=unavailable (retryable backoff)."""


class SdamUnauthorized(Exception):
    """auth / 401 -> result_code=unauthorized (no retry until authority/config changes)."""


class SdamMalformed(Exception):
    """unparseable/invalid provider response -> result_code=malformed (no retry)."""


class ScanIncomplete(Exception):
    """pagination could not prove completeness -> fail closed (ambiguous/unavailable)."""


# --------------------------------------------------------------------------- #
# ResourceSpace read-only userkey client (authmode=userkey; sign=sha256(key+query))
# --------------------------------------------------------------------------- #
class RSClient:
    def __init__(self, base_url, user, key, timeout=15, page_size=200, safety_cap=100000):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self._key = key  # opaque secret; never logged
        self.timeout = timeout
        self.page_size = page_size
        self.safety_cap = safety_cap

    def _get(self, params):
        # one encoder, once: sign the exact query string, send it verbatim + &sign=
        query = urllib.parse.urlencode([("user", self.user)] + list(params))
        sign = hashlib.sha256((self._key + query).encode("utf-8")).hexdigest()
        url = f"{self.base_url}/api/?{query}&sign={sign}"
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "tanaghom-sdam-ro"}), timeout=self.timeout)
            body = r.read(200000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SdamUnauthorized(f"HTTP {e.code}")
            raise SdamUnavailable(f"HTTP {e.code}")
        except Exception as e:  # timeout / connection / DNS
            raise SdamUnavailable(f"{type(e).__name__}")
        try:
            return json.loads(body)
        except ValueError:
            # RS returns 'Invalid signature' as a 401-equivalent plaintext on bad auth
            if "invalid signature" in body.lower():
                raise SdamUnauthorized("invalid signature")
            raise SdamMalformed("non-JSON response")

    def get_resource_data(self, ref):
        d = self._get([("function", "get_resource_data"), ("param1", ref)])
        return d if isinstance(d, dict) and d.get("ref") is not None else None

    # --- #259 S2 write surface (writer principal only; field-scoped F99/F100, no delete) ------ #
    # A separate RSClient constructed with the WRITE user/key performs these; the read principal
    # is never used for a write and keeps its own client. Both go through the same signed _get.
    def create_resource(self, resource_type=VIDEO_RESOURCE_TYPE, archive=PENDING_ARCHIVE):
        """Create ONE resource at the given workflow state; returns the opaque provider ref (str).
        Live-proven in #258 (writer -> Pending -2). A malformed/failed create fails closed."""
        d = self._get([("function", "create_resource"), ("param1", str(resource_type)),
                       ("param2", str(archive))])
        ref = str(d).strip().strip('"') if d is not None else ""
        if not valid_rs_external_ref(ref):
            raise SdamMalformed(f"create_resource returned an invalid ref shape")
        return ref

    def update_field(self, ref, field, value):
        """Set one metadata field on a resource; returns True on provider success. RS answers a
        bare `false` (not an error) when the principal lacks edit authority on that resource —
        callers treat False as a typed unauthorized/denied outcome, never a silent success."""
        d = self._get([("function", "update_field"), ("param1", str(ref)),
                       ("param2", str(field)), ("param3", value)])
        return d is True or (isinstance(d, str) and d.strip().lower() == "true")

    def field_value(self, ref, field_ref):
        """Exact value of ONE metadata field on a resource, read by ref (index-independent —
        used for #259 verify-on-read of field 99 identity and field 100 projection). None if the
        field is absent/empty."""
        d = self._get([("function", "get_resource_field_data"), ("param1", ref)])
        if not isinstance(d, list):
            raise SdamMalformed("field data not a list")
        for fd in d:
            if fd.get("ref") == field_ref:
                return fd.get("value")
        return None

    def field99(self, ref):
        return self.field_value(ref, TANAGHOM_FIELD_REF)

    def get_resource_path(self, ref):
        d = self._get([("function", "get_resource_path"), ("param1", ref),
                       ("param2", "false"), ("param3", ""), ("param4", "true")])
        if not isinstance(d, str):
            raise SdamMalformed("resource path not a string")
        return d

    def _archive(self, ref):
        d = self.get_resource_data(ref)
        return d.get("archive") if isinstance(d, dict) else None

    def _search_page(self, token, offset):
        d = self._get([("function", "do_search"), ("param1", token),
                       ("param2", VIDEO_RESOURCE_TYPE), ("param3", "resourceid"),
                       ("param4", 0), ("param5", self.page_size), ("param6", "ASC"),
                       ("param7", offset)])
        if not isinstance(d, list):
            raise SdamMalformed("search result not a list")
        return [r.get("ref") for r in d]

    def complete_scan(self, token):
        """Deterministic complete paginated scan bounded to the video type, ASC by resourceid.
        Returns the ordered ref list; fails closed (ScanIncomplete) on cap/duplicate/non-monotonic."""
        refs, offset = [], 0
        while True:
            page = self._search_page(token, offset)
            refs += page
            if len(page) < self.page_size:
                break
            offset += self.page_size
            if offset > self.safety_cap:
                raise ScanIncomplete("safety cap exceeded")
        if refs != sorted(refs) or len(refs) != len(set(refs)):
            raise ScanIncomplete("non-monotonic or duplicate candidates")
        return refs

    def _after_scan(self):
        """Hook (no-op live); tests override it to mutate state between scans and prove fail-closed."""

    def _tuples(self, token):
        # materialize the COMPLETE ordered evidence tuple for every candidate:
        # (resource_ref, exact field-99 bytes, archive/workflow state)
        out = [(ref, self.field99(ref), self._archive(ref)) for ref in self.complete_scan(token)]
        self._after_scan()
        return out

    def resolve_unique(self, token):
        """Scan the domain TWICE and compare the complete ordered evidence tuples
        (resource_ref, field-99 bytes, archive) byte-for-byte; any change fails closed. Then
        byte-compare field 99 on every candidate. Returns ('one', ref) / ('zero', None) /
        ('ambiguous', refs). NEVER trusts title/path/first-result/search-normalization as identity."""
        t1 = self._tuples(token)
        t2 = self._tuples(token)
        if t1 != t2:
            raise ScanIncomplete("candidate evidence tuple changed between scans")
        exact = [ref for (ref, f99, _arch) in t1 if f99 == token]
        if len(exact) == 0:
            return ("zero", None)
        if len(exact) == 1:
            return ("one", exact[0])
        return ("ambiguous", exact)


def _audit(conn, entity, entity_id, action, actor, actor_kind, detail):
    """Emit an audit_log event for adapter actions (mirrors the gates audit convention).
    actor_kind reflects the real actor type so attribution matches the observation."""
    conn.cursor().execute(
        "INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
        "VALUES (%s,%s,%s,%s,%s,%s)", (entity, str(entity_id), action, actor, actor_kind, Json(detail)))


def valid_rs_external_ref(ref):
    """ResourceSpace-specific opaque-ref shape (adapter-owned, NOT in the DB): positive integer,
    no leading zero, bounded length."""
    return isinstance(ref, str) and ref.isdigit() and ref[0] != "0" and 1 <= len(ref) <= 18


# --------------------------------------------------------------------------- #
# Binding repository (Tanaghom-side; immutable rows)
# --------------------------------------------------------------------------- #
def create_binding(conn, asset_id, asset_version, slot_id, external_ref, created_by,
                   provider=PROVIDER, mapping_version=MAPPING_VERSION):
    if provider == PROVIDER and not valid_rs_external_ref(external_ref):
        raise ValueError(f"invalid ResourceSpace external_ref shape: {external_ref!r}")
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sdam_asset_binding
             (asset_id, asset_version, slot_id, provider_key, external_ref, mapping_version, created_by, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s, now()) RETURNING binding_id""",
        (asset_id, asset_version, slot_id, provider, external_ref, mapping_version, created_by))
    binding_id = cur.fetchone()[0]
    _audit(conn, "sdam_binding", binding_id, "sdam_binding_created", created_by, "operator",
           {"asset_id": str(asset_id), "asset_version": asset_version, "slot_id": slot_id,
            "provider_key": provider})
    return binding_id


def get_binding(conn, binding_id):
    cur = conn.cursor()
    cur.execute("""SELECT binding_id, asset_id, asset_version, slot_id, provider_key, external_ref,
                          mapping_version FROM sdam_asset_binding WHERE binding_id=%s""", (binding_id,))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("binding_id", "asset_id", "asset_version", "slot_id", "provider_key", "external_ref", "mapping_version")
    return dict(zip(keys, row))


# --------------------------------------------------------------------------- #
# Readiness projection + digest (canonical versioned projection, NOT copies of SDAM state)
# --------------------------------------------------------------------------- #
def _digest(projection):
    return hashlib.sha256(json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def expected_projection(binding):
    return {"asset_id": str(binding["asset_id"]), "asset_version": binding["asset_version"],
            "slot_id": binding["slot_id"], "mapping_version": binding["mapping_version"]}


def observed_projection(binding, field99_value):
    # SDAM-verified identity: the opaque field-99 value must equal the canonical asset_id byte-for-byte.
    return {"asset_id": field99_value, "asset_version": binding["asset_version"],
            "slot_id": binding["slot_id"], "mapping_version": binding["mapping_version"]}


# --------------------------------------------------------------------------- #
# Controlled observation append (through the sole DB write function)
# --------------------------------------------------------------------------- #
def append_observation(conn, binding_id, observation_key, result_code, actor_type, actor_id,
                       expected_digest=None, observed_digest=None, mismatch_code=None,
                       policy_version=DEFAULT_POLICY_VERSION):
    retry_class = RETRY_BY_RESULT[result_code]
    algo = DIGEST_ALGO if result_code in _DIGEST_BEARING else None
    schema = DIGEST_SCHEMA_VERSION if result_code in _DIGEST_BEARING else None
    cur = conn.cursor()
    cur.execute("SELECT sdam_append_observation(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (binding_id, observation_key, result_code, algo, schema, expected_digest,
                 observed_digest, mismatch_code, policy_version, actor_type, actor_id, retry_class))
    return cur.fetchone()[0]


def current_state(conn, binding_id):
    """Newest observation only (ordering authority = observation_seq); expiry -> derived 'stale'."""
    cur = conn.cursor()
    cur.execute(
        """SELECT (CASE WHEN expires_at <= clock_timestamp() THEN 'stale' ELSE result_code END),
                  result_code, retry_class, observation_seq, observed_at, expires_at
             FROM sdam_readiness_observation WHERE binding_id=%s
             ORDER BY observation_seq DESC LIMIT 1""", (binding_id,))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("effective_state", "observed_result", "retry_class", "observation_seq", "observed_at", "expires_at")
    return dict(zip(keys, row))


# --------------------------------------------------------------------------- #
# Readiness evaluation (read-only toward ResourceSpace)
# --------------------------------------------------------------------------- #
def observe_readiness(conn, rs, binding_id, observation_key, actor_type="system", actor_id="sdam-adapter"):
    """Poll the bound resource BY its preserved external_ref, classify one result_code, append one
    immutable observation, and emit an audit event. Pending != missing. `ready` requires that a
    COMPLETE canonical-id scan finds exactly one byte-exact match AND that match equals the bound
    external_ref (resource uniqueness + binding agreement enforced in the adapter). Zero / multiple /
    incomplete / unstable / binding-disagreement / transport / auth / malformed all fail closed with a
    typed result. Returns the result_code."""
    binding = get_binding(conn, binding_id)
    if binding is None:
        raise ValueError("unknown binding")
    ref = int(binding["external_ref"])

    def emit(result_code, expected=None, observed=None, mismatch=None):
        # observation + audit are ONE atomic unit in the CALLER's transaction; the caller owns
        # commit/rollback (repository-style, like create_binding). No internal commit.
        append_observation(conn, binding_id, observation_key, result_code, actor_type, actor_id,
                           expected_digest=expected, observed_digest=observed, mismatch_code=mismatch)
        _audit(conn, "sdam_binding", binding_id, "sdam_readiness_observed", actor_id, actor_type,
               {"result_code": result_code, "observation_key": observation_key})
        return result_code

    try:
        data = rs.get_resource_data(ref)
        if data is None:
            return emit("not_ready_missing")           # bound ref no longer resolves
        if data.get("resource_type") != VIDEO_RESOURCE_TYPE:
            return emit("not_ready_taxonomy_mismatch",
                        expected=_digest({"resource_type": VIDEO_RESOURCE_TYPE}),
                        observed=_digest({"resource_type": data.get("resource_type")}),
                        mismatch="taxonomy_format")
        archive = data.get("archive")
        if archive in _PENDING:
            return emit("not_ready_pending")           # awaiting SDAM review/publishing (not missing)
        if archive != _ACTIVE:
            return emit("not_ready_missing")           # archived/deleted -> not consumable
        # ACTIVE: prove ResourceSpace uniqueness of the canonical asset_id via a complete scan.
        kind, found = rs.resolve_unique(str(binding["asset_id"]))
        if kind == "zero":
            return emit("not_ready_missing")           # no active resource carries the canonical id
        if kind == "ambiguous":
            return emit("not_ready_ambiguous")         # >1 byte-exact carrier -> fail closed
        if found != ref:                                # unique match, but not the bound resource
            return emit("not_ready_lineage_mismatch",
                        expected=_digest({"bound_ref": ref}),
                        observed=_digest({"resolved_ref": found}), mismatch="lineage_asset_version")
        exp = _digest(expected_projection(binding))     # unique byte-exact match == bound ref -> ready
        obs = _digest(observed_projection(binding, str(binding["asset_id"])))
        return emit("ready", expected=exp, observed=obs)
    except SdamUnauthorized:
        return emit("unauthorized")
    except SdamUnavailable:
        return emit("unavailable")
    except ScanIncomplete:
        return emit("not_ready_ambiguous")             # completeness unprovable -> fail closed
    except SdamMalformed:
        return emit("malformed")


# --------------------------------------------------------------------------- #
# Provider-neutral handoff read model (data only; NEVER executes AVP)
# --------------------------------------------------------------------------- #
def list_slot_bindings(conn, slot_id):
    """#250 — slot-keyed READ-ONLY visibility: every binding this slot carries, each with its
    newest persisted observation state (`current_state`: expiry-derived `stale` included). Pure DB
    truth — no live provider call, no write. `effective_state=None` means bound with NO observation
    yet, which the surface must present distinctly from `pending` (an observed pending is provider
    truth; no observation is absence of evidence)."""
    cur = conn.cursor()
    cur.execute("""SELECT binding_id, asset_id, asset_version, provider_key, external_ref,
                          mapping_version, created_at
                     FROM sdam_asset_binding WHERE slot_id=%s
                    ORDER BY created_at, binding_id""", (slot_id,))
    keys = ("binding_id", "asset_id", "asset_version", "provider_key", "external_ref",
            "mapping_version", "created_at")
    out = []
    for r in cur.fetchall():
        b = dict(zip(keys, r))
        st = current_state(conn, str(b["binding_id"]))
        b["effective_state"] = st["effective_state"] if st else None
        b["observed_result"] = st["observed_result"] if st else None
        b["observed_at"] = st["observed_at"] if st else None
        b["expires_at"] = st["expires_at"] if st else None
        b["handoff_ready"] = bool(st and st["effective_state"] == "ready")
        # #259 P1b (follow-up) — projection_pending is SERVER-OBSERVABLE + reload-stable pure DB
        # truth: this binding was registered (sdam_edit_registered) but its field-100 discovery
        # projection is not yet confirmed (no sdam_edit_projection_written for THIS binding_id).
        # The surface offers a governed retry for exactly this state; it never depends on transient
        # client state and never needs a live provider read.
        pc = conn.cursor()
        pc.execute("""SELECT
              EXISTS (SELECT 1 FROM audit_log WHERE entity='sdam_registration'
                        AND action='sdam_edit_registered' AND detail->>'binding_id'=%s),
              EXISTS (SELECT 1 FROM audit_log WHERE entity='sdam_registration'
                        AND action='sdam_edit_projection_written' AND detail->>'binding_id'=%s)""",
                   (str(b["binding_id"]), str(b["binding_id"])))
        registered, projected = pc.fetchone()
        pc.close()
        b["projection_pending"] = bool(registered and not projected)
        out.append(b)
    return out


def build_handoff(conn, rs, binding_id):
    """Emit handoff data ONLY when the newest observation is fresh AND ready. Media source resolved
    live from SDAM (never persisted). AVP must not infer identity/lineage from URLs."""
    st = current_state(conn, binding_id)
    if not st or st["effective_state"] != "ready":
        return None
    binding = get_binding(conn, binding_id)
    return {
        "binding_id": str(binding_id),
        "asset_id": str(binding["asset_id"]),
        "asset_version": binding["asset_version"],
        "mapping_version": binding["mapping_version"],
        "externalRef": {"system": "sdam", "id": binding["external_ref"]},
        "media_source": rs.get_resource_path(int(binding["external_ref"])),  # live
    }


# --------------------------------------------------------------------------- #
# #259 S2 — completed-edit SDAM registration (phase-audited convergent state machine)
# --------------------------------------------------------------------------- #
# Registers the S1-pinned (#255) approved MASTER edit as a versioned completed-edit resource in
# SDAM, keyed on the pinned (asset_id, version, slot_id). Every phase transition is an append-only
# Tanaghom audit event, making partial provider state durably discoverable WITHOUT depending on the
# RS keyword index. Retry is a single convergent entry point that NEVER creates a duplicate
# resource/binding and NEVER fabricates success. Tanaghom decisions stay authoritative; RS is
# mapped media only; field 100 is a machine token, never publish authority.
class SdamRegistrationError(Exception):
    """A registration cannot proceed truthfully (unpinned/unverified pin, ambiguous carrier, or an
    unreconciled provider intent). Carries a typed `code` for the operator-visible state."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _pinned_master_asset(conn, slot_id):
    """The exact approved master edit for a slot, resolved like inspect_slot's approved_edit:
    the slot_approval('edit') pointer + the newest immutable approved_edit_master_pinned audit
    verified against asset truth. Returns (asset_id, version) or raises SdamRegistrationError with
    the truthful refusal code — never guesses identity from the revision number."""
    cur = conn.cursor()
    cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='edit'", (slot_id,))
    pin = cur.fetchone()
    if not pin:
        raise SdamRegistrationError("no_pin", f"{slot_id} has no approved master edit pin")
    revision = pin[0]
    cur.execute("""SELECT detail FROM audit_log
                    WHERE entity='slot' AND entity_id=%s AND action='approved_edit_master_pinned'
                      AND (detail->>'revision')::int = %s ORDER BY id DESC LIMIT 1""",
                (slot_id, revision))
    ev = cur.fetchone()
    if not ev:
        raise SdamRegistrationError("pin_unverified",
                                    f"{slot_id} pin has no matching immutable pin event")
    asset_id = ev[0].get("asset_id")
    cur.execute("""SELECT 1 FROM asset WHERE asset_id=%s AND slot_id=%s AND stage='media_edit'
                    AND kind='edit' AND platform_variant IS NULL AND version=%s""",
                (asset_id, slot_id, revision))
    if not cur.fetchone():
        raise SdamRegistrationError("pin_inconsistent",
                                    f"{slot_id} pin event contradicts asset truth")
    return asset_id, revision


def _registration_event(conn, slot_id, asset_id, action):
    """Newest matching registration phase-event for this slot+asset (append-only discovery)."""
    cur = conn.cursor()
    cur.execute("""SELECT detail FROM audit_log
                    WHERE entity='sdam_registration' AND entity_id=%s AND action=%s
                      AND detail->>'asset_id'=%s ORDER BY id DESC LIMIT 1""",
                (slot_id, action, str(asset_id)))
    r = cur.fetchone()
    return r[0] if r else None


def _binding_for_asset(conn, asset_id, asset_version):
    cur = conn.cursor()
    cur.execute("""SELECT binding_id, external_ref FROM sdam_asset_binding
                    WHERE asset_id=%s AND asset_version=%s AND provider_key=%s""",
                (asset_id, asset_version, PROVIDER))
    r = cur.fetchone()
    return (str(r[0]), r[1]) if r else (None, None)


def _readiness_token(binding_id, state="registered"):
    return f"g{PROJECTION_GENERATION}:{state}:{binding_id}"


def _write_projection(conn, rs_writer, rs_reader, slot_id, asset_id, binding_id, external_ref):
    """Phase D — write field 100 = the machine token, verify BY REF (index-independent), and audit.
    Idempotent: a matching token already present is a no-op success. Returns the token."""
    token = _readiness_token(binding_id)
    if rs_reader.field_value(int(external_ref), READINESS_FIELD_REF) == token:
        return token                                             # already projected (converged)
    if not rs_writer.update_field(external_ref, READINESS_FIELD_REF, token):
        raise SdamUnauthorized("writer denied field-100 projection")
    if rs_reader.field_value(int(external_ref), READINESS_FIELD_REF) != token:
        raise SdamMalformed("field-100 projection not confirmed on read-back")
    _audit(conn, "sdam_registration", slot_id, "sdam_edit_projection_written", "sdam-adapter",
           "system", {"asset_id": str(asset_id), "binding_id": binding_id, "token": token})
    conn.commit()
    return token


def register_completed_edit(conn, rs_writer, rs_reader, slot_id, actor="sdam-adapter"):
    """Sole write path for S2 completed-edit registration. Phase-audited + convergent.

    Recovery is deterministic for every partial failure with a KNOWN ref (create-then-field-fail,
    create-then-binding-fail, projection-fail) — all converge on retry with no duplicate resource
    or binding. The ONE irreducible residual is a create whose HTTP response is entirely lost (no
    ref returned, no field-99 written): the provider MAY have created a Pending resource carrying no
    canonical id, which resolve_unique cannot correlate. Because the intent event persists, the
    retry lands on the PRIOR-INTENT path and STOPS fail-closed (`unreconciled_intent`) on zero
    carriers — it never blind-creates a second resource. The possible stray Pending resource is a
    bounded, operator-reconcilable residual (never a duplicate BINDING) — reported here, not claimed
    away, and its cleanup + a clean re-register are the operator's reconciliation step.
    Phase-audited + convergent:
      A intent (commit) -> B provider create + durable created-ref audit (commit) ->
      C binding + registered audit (one txn) + first observation -> D field-100 projection.
    A single call always converges without duplicating a resource/binding; every non-success is a
    truthful typed state. `rs_writer` performs writes; `rs_reader` performs verify-on-read."""
    asset_id, version = _pinned_master_asset(conn, slot_id)      # refuses unpinned/unverified pins

    # step 1: binding already exists -> only complete the projection (recovery case 2 + idempotency).
    # A projection provider failure here is NOT a registration failure — the binding/audit already
    # ARE the truthful registered record — so return a typed retryable status, never a raw error.
    binding_id, external_ref = _binding_for_asset(conn, asset_id, version)
    if binding_id:
        return _finish_projection(conn, rs_writer, rs_reader, slot_id, asset_id, version,
                                  binding_id, external_ref, adopted="binding")

    # #259 P1a — distinguish a FRESH invocation from a PRE-EXISTING intent BEFORE Phase A. Only a
    # fresh call (no prior intent) may create-on-zero; a prior intent with no durable created-ref
    # must recover via resolve_unique and STOP fail-closed on zero (a crash right after the intent
    # commit, before any provider create, must never be indistinguishable from a fresh call).
    prior_intent = _registration_event(conn, slot_id, asset_id, "sdam_edit_registration_intent")
    created = _registration_event(conn, slot_id, asset_id, "sdam_edit_resource_created")
    if created:
        # adopt a recorded resource (recovery case 1); field 99 reconciled SET-OR-STOP:
        #   unset -> the field-99 write never landed; set it now and converge (idempotent);
        #   ==id  -> already correct; proceed; other -> genuine conflict, truthful STOP.
        ref = created["external_ref"]
        current = rs_reader.field99(int(ref))                   # verify-on-read BY REF (index-free)
        if current is None:
            if not rs_writer.update_field(ref, TANAGHOM_FIELD_REF, str(asset_id)):
                raise SdamUnauthorized("writer denied field-99 identity write on adopted resource")
            if rs_reader.field99(int(ref)) != str(asset_id):
                raise SdamMalformed("field-99 identity not confirmed on read-back")
        elif current != str(asset_id):
            raise SdamRegistrationError("unreconciled_intent",
                f"recorded resource {ref} for {slot_id} carries a different canonical id — reconcile")
    elif prior_intent:
        # a prior attempt recorded intent but never a durable created-ref -> recover, NEVER create:
        # resolve_unique adopts a discoverable resource, and zero carriers is a fail-closed STOP.
        kind, found = rs_reader.resolve_unique(str(asset_id))
        if kind == "ambiguous":
            raise SdamRegistrationError("ambiguous", f"multiple RS carriers of {asset_id} — reconcile")
        if kind != "one":
            raise SdamRegistrationError("unreconciled_intent",
                f"intent exists for {slot_id} but no resource carries the canonical id — reconcile")
        ref = str(found)
        _audit(conn, "sdam_registration", slot_id, "sdam_edit_resource_created", actor, "system",
               {"asset_id": str(asset_id), "version": version, "external_ref": ref, "adopted": "scan"})
        conn.commit()
    else:
        # FRESH invocation: record intent, then adopt-or-create. Create-on-zero is allowed ONLY on
        # this fresh path; the created-ref is recorded IMMEDIATELY (before the field-99 write) so a
        # field-write failure leaves a discoverable resource, not an orphan.
        _audit(conn, "sdam_registration", slot_id, "sdam_edit_registration_intent", actor, "system",
               {"asset_id": str(asset_id), "version": version})
        conn.commit()
        kind, found = rs_reader.resolve_unique(str(asset_id))
        if kind == "ambiguous":
            raise SdamRegistrationError("ambiguous", f"multiple RS carriers of {asset_id} — reconcile")
        if kind == "one":
            ref = str(found)
            _audit(conn, "sdam_registration", slot_id, "sdam_edit_resource_created", actor, "system",
                   {"asset_id": str(asset_id), "version": version, "external_ref": ref, "adopted": "scan"})
            conn.commit()
        else:
            ref = rs_writer.create_resource(VIDEO_RESOURCE_TYPE, PENDING_ARCHIVE)
            _audit(conn, "sdam_registration", slot_id, "sdam_edit_resource_created", actor, "system",
                   {"asset_id": str(asset_id), "version": version, "external_ref": ref})
            conn.commit()
            if not rs_writer.update_field(ref, TANAGHOM_FIELD_REF, str(asset_id)):
                raise SdamUnauthorized("writer denied field-99 identity write")
            if rs_reader.field99(int(ref)) != str(asset_id):
                raise SdamMalformed("field-99 identity not confirmed on read-back")

    # Phase C — binding + registered audit in ONE txn, then the first readiness observation
    binding_id = str(create_binding(conn, asset_id, version, slot_id, ref, actor))
    _audit(conn, "sdam_registration", slot_id, "sdam_edit_registered", actor, "system",
           {"asset_id": str(asset_id), "version": version, "binding_id": binding_id, "external_ref": ref})
    conn.commit()
    import uuid as _uuid
    obs = observe_readiness(conn, rs_reader, binding_id, str(_uuid.uuid4()),
                            actor_type="system", actor_id=actor)
    conn.commit()

    # Phase D — projection (typed retryable status on provider failure; binding is already the record)
    return _finish_projection(conn, rs_writer, rs_reader, slot_id, asset_id, version,
                              binding_id, ref, adopted=None, observation=obs)


def _finish_projection(conn, rs_writer, rs_reader, slot_id, asset_id, version, binding_id,
                       external_ref, adopted, observation=None):
    """#259 P1b — Phase D as a TYPED per-phase outcome. Once the binding exists the registration IS
    registered; a field-100 write/read-back provider failure is `projection_pending` + retryable,
    NEVER a raw provider error that reads as a failed registration."""
    base = {"binding_id": binding_id, "external_ref": external_ref,
            "asset_id": str(asset_id), "version": version, "adopted": adopted}
    if observation is not None:
        base["observation"] = observation
    try:
        token = _write_projection(conn, rs_writer, rs_reader, slot_id, asset_id, binding_id, external_ref)
        return {**base, "state": "registered", "projection": token,
                "projection_status": "written", "retryable": False}
    except (SdamUnauthorized, SdamUnavailable, SdamMalformed):
        conn.rollback()   # discard only the unconfirmed projection; binding/audit already committed
        return {**base, "state": "registered", "projection": None,
                "projection_status": "pending", "retryable": True,
                "reason": "completed edit is registered; the discovery projection is pending — retry"}


# --------------------------------------------------------------------------- #
# #259 — env-gated in-memory test stub (analogous to TANAGHOM_WRITER_STUB).
# --------------------------------------------------------------------------- #
# ONLY used when TANAGHOM_SDAM_STUB is truthy (default OFF; a real run never touches it — the API
# health surfaces the flag). It is a deterministic, process-local ResourceSpace so browser/API
# tests can drive the governed register/retry action end-to-end WITHOUT a live provider. It shares
# one store across the writer and reader instances the endpoint constructs per request, so a
# projection written by the "writer" is read back by the "reader" exactly as the real server would.
class StubRS(RSClient):
    _STORE = {}          # {ref(str): {field_ref(int): value}} — shared, process-local

    def __init__(self):
        pass             # no base URL / key: never makes a network call

    @classmethod
    def reset(cls):
        cls._STORE = {}

    def create_resource(self, resource_type=VIDEO_RESOURCE_TYPE, archive=PENDING_ARCHIVE):
        ref = str(max([int(r) for r in self._STORE] + [900000]) + 1)
        self._STORE[ref] = {"__archive__": archive, "__type__": resource_type}
        return ref

    def update_field(self, ref, field, value):
        self._STORE.setdefault(str(ref), {})[int(field)] = value
        return True

    def field_value(self, ref, field_ref):
        return self._STORE.get(str(ref), {}).get(int(field_ref))

    def field99(self, ref):
        return self.field_value(ref, TANAGHOM_FIELD_REF)

    def get_resource_data(self, ref):
        r = self._STORE.get(str(ref))
        return {"ref": ref, "archive": r.get("__archive__", PENDING_ARCHIVE),
                "resource_type": r.get("__type__", VIDEO_RESOURCE_TYPE)} if r else None

    def get_resource_path(self, ref):
        return f"stub://sdam/resource/{ref}"    # never a real signed URL

    def resolve_unique(self, token):
        exact = [r for r, v in self._STORE.items() if v.get(TANAGHOM_FIELD_REF) == token]
        if len(exact) == 0:
            return ("zero", None)
        if len(exact) == 1:
            return ("one", exact[0])
        return ("ambiguous", exact)
