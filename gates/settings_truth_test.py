"""#443 — focused contract test for the Settings-truth read model (gates/settings_truth.py).

Pure and DB-free: it drives settings_truth.project() with synthetic configs (including adversarial
URL/secret inputs) and, when PyYAML is present, against the real system_config.example.yaml to prove
no credential env-var NAME can leak. Covers redaction, authority-backed state semantics, generation
omission-when-absent, deterministic output, route-role labels without capability inference, canonical
identifiers, fail-closed availability, presence/type-only secret refs, and non-mutating projection.

Run: python3 gates/settings_truth_test.py   (from gates/: python3 settings_truth_test.py)
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings_truth  # noqa: E402

_failures = 0


def check(name, cond):
    global _failures
    if cond:
        print(f"  [PASS] {name}")
    else:
        _failures += 1
        print(f"  [FAIL] {name}")


# A config exercising every branch: a provider requiring a credential, one that does not, an
# adversarial credential-bearing/query/fragment URL, a route with a fallback, and a route hop naming a
# provider that is ABSENT from the registry (must fail closed to unknown).
FIXTURE = {
    "providers": {
        "openrouter": {"kind": "openai_chat", "base_url": "https://openrouter.ai/api/v1",
                       "api_key_env": "OPENROUTER_API_KEY", "max_retries": 3},
        "groq": {"kind": "openai_chat", "base_url": "https://api.groq.com/openai/v1",
                 "api_key_env": "GROQ_API_KEY"},
        "ollama": {"kind": "openai_chat", "base_url": "http://host.docker.internal:11434/v1",
                   "api_key_env": ""},
        "hostile": {"kind": "openai_chat",
                    "base_url": "https://user:s3cr3t@evil.example:8443/v1?token=LEAK&x=1#frag",
                    "api_key_env": "HOSTILE_API_KEY"},
    },
    "models": {
        "script": {"temperature": 0.8, "primary": {"provider": "openrouter", "model": "scout"},
                   "fallback": [{"provider": "groq", "model": "llama-3.3"},
                                {"provider": "ghost", "model": "nope"}]},  # 'ghost' is not a provider
        "embeddings": {"primary": {"provider": "ollama", "model": "mxbai-embed-large"}},
    },
}


def main():
    print("== #443 settings-truth read model contract ==")
    out = settings_truth.project(FIXTURE)
    blob = json.dumps(out)
    provs = {p["key"]: p for p in out["providers"]}
    routes = {r["role"]: r for r in out["routes"]}

    # ---- Authority + generation/provenance omission ----
    check("authority names the governed config via load_config",
          "system_config" in out["authority"] and "load_config" in out["authority"])
    check("generation/provenance omitted (available=false), no synthesized identity",
          out["provenance"] == {"available": False})
    check("no 'generation'/'provenance' IDENTITY key anywhere in the projection",
          '"generation_id"' not in blob and '"provenance_id"' not in blob
          and '"generation":' not in blob)

    # ---- Redaction: secret VALUES and credential NAMES never leak ----
    for name in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "HOSTILE_API_KEY", "s3cr3t", "LEAK"):
        check(f"redaction: {name!r} never appears in the projection", name not in blob)

    # ---- Secret reference: presence + type only, identity omitted ----
    check("provider requiring a credential -> required=true, type=env_var_reference, no name",
          provs["groq"]["secret_reference"] == {"required": True, "type": "env_var_reference"})
    check("provider with empty api_key_env -> required=false, type=null",
          provs["ollama"]["secret_reference"] == {"required": False, "type": None})
    check("secret_reference exposes ONLY required+type keys (no name/path/identity)",
          all(set(p["secret_reference"].keys()) == {"required", "type"} for p in out["providers"]))

    # ---- Endpoint safe projection: userinfo/query/fragment removed, not classified ----
    check("clean endpoint preserved (scheme+host+path)",
          provs["groq"]["endpoint"] == "https://api.groq.com/openai/v1")
    check("endpoint keeps an explicit port + path", provs["ollama"]["endpoint"]
          == "http://host.docker.internal:11434/v1")
    check("hostile endpoint: userinfo, query, and fragment fully removed",
          provs["hostile"]["endpoint"] == "https://evil.example:8443/v1")
    check("no endpoint retains a query string or fragment",
          all("?" not in (p["endpoint"] or "") and "#" not in (p["endpoint"] or "")
              and "@" not in (p["endpoint"] or "") for p in out["providers"]))

    # ---- Provider kind + canonical identifiers ----
    check("provider kind exposed verbatim", provs["openrouter"]["kind"] == "openai_chat")
    check("canonical provider key used as identity", provs["openrouter"]["key"] == "openrouter")

    # ---- Availability: configured presence only; unknown fails closed ----
    check("every configured provider reports configured availability",
          all(p["availability"] == {"state": "configured"} for p in out["providers"]))
    check("route hop naming a KNOWN provider -> configured",
          routes["script"]["primary"]["availability"]["state"] == "configured")
    check("route hop naming an ABSENT provider -> unknown (fail closed)",
          routes["script"]["fallback"][1]["availability"]["state"] == "unknown"
          and routes["script"]["fallback"][1]["provider"] == "ghost")

    # ---- Route-role labels only; no capability inference ----
    check("routes are keyed by existing config role labels",
          set(routes.keys()) == {"script", "embeddings"})
    check("no generic 'capabilit...' inventory is synthesized anywhere",
          "capabilit" not in blob.lower())
    check("route exposes provider/model identity + availability only (no permissions/capabilities)",
          set(routes["script"]["primary"].keys()) == {"provider", "model", "availability"})
    check("model identity carried verbatim", routes["script"]["primary"]["model"] == "scout"
          and routes["script"]["fallback"][0]["model"] == "llama-3.3")
    check("route tuning knobs (temperature/max_tokens) are NOT exposed",
          "temperature" not in blob and "max_tokens" not in blob)

    # ---- Deterministic ordering + repeatable ----
    check("providers sorted by key deterministically",
          [p["key"] for p in out["providers"]] == sorted(provs.keys()))
    check("routes sorted by role deterministically",
          [r["role"] for r in out["routes"]] == sorted(routes.keys()))
    check("projection is repeatable (equal on re-run)", settings_truth.project(FIXTURE) == out)

    # ---- Non-mutating ----
    before = copy.deepcopy(FIXTURE)
    settings_truth.project(FIXTURE)
    check("project() does not mutate the input config", FIXTURE == before)

    # ---- Empty / fail-closed shapes ----
    empty = settings_truth.project({})
    check("empty config -> empty providers/routes, authority + omission still stated",
          empty["providers"] == [] and empty["routes"] == []
          and empty["provenance"] == {"available": False})
    malformed = settings_truth.project({"providers": {"x": {"base_url": "not a url"}},
                                        "models": {"r": {"primary": "oops"}}})
    check("unparseable/scheme-less base_url -> endpoint omitted (fail closed)",
          malformed["providers"][0]["endpoint"] is None)
    check("non-dict route primary -> primary omitted (fail closed)",
          malformed["routes"][0]["primary"] is None and malformed["routes"][0]["fallback"] == [])

    # ---- Real authority: prove no credential env NAME leaks from the shipped config ----
    try:
        import yaml  # noqa: F401
        here = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.join(os.path.dirname(here), "system_config.example.yaml")
        with open(cfg_path, "r", encoding="utf-8") as fh:
            real = yaml.safe_load(fh)
        real_blob = json.dumps(settings_truth.project(real))
        leaked = [n for n in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "api_key_env")
                  if n in real_blob]
        check("real system_config projection leaks no credential env NAME", not leaked)
        check("real system_config projection exposes providers + routes",
              '"providers"' in real_blob and '"routes"' in real_blob and "openai_chat" in real_blob)
    except ImportError:
        print("  [skip] PyYAML absent — real system_config leak check not run")

    print("\nALL SETTINGS-TRUTH CHECKS PASSED" if _failures == 0 else f"\nFAILURES: {_failures}")
    sys.exit(0 if _failures == 0 else 1)


if __name__ == "__main__":
    main()
