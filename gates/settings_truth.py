"""#443 — the ONE canonical backend read model for the V2 Settings-truth slice.

A bounded, read-only, side-effect-free projection over the EXISTING governed provider/model/route
configuration authority (`system_config` loaded by `engine.load_config`). It creates no second
authority: it reads the config the runner already obeys and reshapes exactly the safe fields the
Settings surface renders.

Hard invariants (directive #443 — authority/redaction/availability):

  * SECRETS NEVER LEAVE.  Provider credentials are referenced in config only by an env-var NAME
    (`api_key_env`, e.g. "GROQ_API_KEY"). That name is a sensitive reference identity, not a
    non-sensitive opaque one, so it is NEVER echoed. Secret-reference output is PRESENCE + TYPE only.
  * ENDPOINT SAFE PROJECTION.  A `base_url` is reduced to scheme + host + optional port + path.
    Userinfo, query strings, and fragments are REMOVED (not classified), so a hostile or
    credential-bearing URL cannot leak through.
  * ROUTE-ROLE LABELS ONLY.  Model routes are exposed under their existing config role keys
    (topic_hook, script, embeddings, …) with the referenced provider/model identity. No generic
    "capability inventory" is synthesized and no permission/capability is inferred from kind/name/role.
  * CONFIGURED-STATE-ONLY AVAILABILITY.  The authority records configured/enabled presence and no
    runtime-availability truth, so availability is reported ONLY as `configured`; anything the config
    does not support (e.g. a route naming a provider absent from the registry) is `unknown` and fails
    closed. No health check, credential validation, probe, discovery, or resolution is performed.
  * GENERATION/PROVENANCE OMITTED.  The canonical authority defines no provider/model/route
    generation or provenance identity, so no such field is emitted; the absence is stated truthfully
    (`provenance.available = false`) WITHOUT synthesizing an identity.
  * NON-MUTATING.  Reading the config initializes, seeds, rewrites, normalizes, and persists nothing.

The projection is deterministic (providers sorted by key, routes sorted by role) so the surface and
its tests observe a stable order.
"""

from urllib.parse import urlsplit, urlunsplit

# The exact authority string the surface/runbook documents as the source of truth.
AUTHORITY = "system_config (governed provider/model/route configuration) via engine.load_config"


def _safe_str(value):
    """Config scalars are rendered verbatim as strings; anything absent/None becomes None (never the
    literal 'None'). No interpretation, no derivation."""
    if value is None:
        return None
    return str(value)


def _safe_endpoint(base_url):
    """Reduce a provider `base_url` to a SAFE projection: scheme + host + optional port + path.
    Userinfo, ALL query strings, and ALL fragments are removed rather than classified, so no
    credential-bearing or malicious URL component can ever be returned. Returns None when no
    scheme+host can be recovered (fail closed)."""
    raw = (base_url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()   # .hostname drops any userinfo and the port
    if not scheme or not host:
        return None                          # no safe identity -> omit (fail closed)
    try:
        port = parts.port                    # invalid ports raise; treat as no safe identity
    except ValueError:
        return None
    netloc = host if port is None else f"{host}:{port}"
    path = parts.path or ""
    # urlunsplit with empty query + fragment guarantees they are dropped, not merely blanked.
    return urlunsplit((scheme, netloc, path, "", ""))


def _secret_reference(api_key_env):
    """PRESENCE + TYPE only. `api_key_env` is a sensitive env-var name and there is no canonical
    non-sensitive opaque identity for it, so identity is OMITTED entirely — only whether a credential
    reference is required, and (when required) the reference TYPE, are returned. The name is never
    echoed."""
    required = bool((api_key_env or "").strip())
    return {"required": required, "type": "env_var_reference" if required else None}


def _provider(key, entry):
    entry = entry if isinstance(entry, dict) else {}
    return {
        "key": key,                                    # canonical existing identifier (config key)
        "kind": _safe_str(entry.get("kind")),          # provider kind (existing config truth)
        "endpoint": _safe_endpoint(entry.get("base_url")),
        "secret_reference": _secret_reference(entry.get("api_key_env")),
        "availability": {"state": "configured"},       # config presence only; nothing stronger
    }


def _hop(hop, provider_keys):
    """One route hop -> provider/model identity + configured-state-only availability. A hop naming a
    provider that is NOT in the registry is `unknown` (fail closed), never assumed available."""
    hop = hop if isinstance(hop, dict) else {}
    provider = _safe_str(hop.get("provider"))
    model = _safe_str(hop.get("model"))
    state = "configured" if provider in provider_keys else "unknown"
    return {"provider": provider, "model": model, "availability": {"state": state}}


def _route(role, spec, provider_keys):
    spec = spec if isinstance(spec, dict) else {}
    primary = _hop(spec.get("primary"), provider_keys) if isinstance(spec.get("primary"), dict) else None
    raw_fallback = spec.get("fallback")
    fallback = [_hop(h, provider_keys) for h in raw_fallback if isinstance(h, dict)] \
        if isinstance(raw_fallback, list) else []
    return {"role": role, "primary": primary, "fallback": fallback}


def project(cfg):
    """Build the safe, deterministic Settings-truth projection from a loaded config mapping. Pure:
    it copies out only the allow-listed safe fields and mutates `cfg` in no way."""
    cfg = cfg if isinstance(cfg, dict) else {}
    providers_cfg = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    models_cfg = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}

    provider_keys = set(providers_cfg.keys())
    providers = [_provider(key, providers_cfg.get(key)) for key in sorted(providers_cfg)]
    routes = [_route(role, models_cfg.get(role), provider_keys) for role in sorted(models_cfg)]

    return {
        "authority": AUTHORITY,
        # No canonical provider/model/route generation or provenance identity exists in the authority;
        # the field is omitted and its absence stated truthfully — never synthesized.
        "provenance": {"available": False},
        "providers": providers,
        "routes": routes,
    }
