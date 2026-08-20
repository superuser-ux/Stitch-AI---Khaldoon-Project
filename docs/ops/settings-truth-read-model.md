# Settings-truth read model (#443)

A bounded, **read-only** V2 Settings surface that projects the existing governed
provider/model/route configuration. It introduces **no second authority**, resolves no secret, probes
nothing, and mutates nothing.

## Authority (source of truth)

- **Canonical authority:** `system_config` (the `providers:` endpoint registry and `models:`
  per-stage route table), loaded by `gates/engine.py::load_config`. This is the same configuration the
  writer runner already obeys — the read model reshapes only its safe fields.
- **Backend read model:** `gates/settings_truth.py::project(cfg)` — pure, deterministic, side-effect
  free.
- **API read seam:** `GET /admin/settings/truth` (`gates/api.py`), guarded by the existing
  signed-principal boundary (`_require_trusted_principal`; **no new IAM**). Reachable from V2 through
  the allow-listed `/gw` proxy (`workbench/lib/api-contract.ts`), which signs the workbench principal
  server-side in an explicit dev/test runtime exactly as it does for the secrets-status read.
- **Surface:** `workbench/app/admin/settings/page.tsx` → `workbench/components/settings-admin.tsx`
  (`/admin/settings`).

## What it exposes (allow-listed, non-secret)

| Field | Source | Rule |
|---|---|---|
| Provider `key`, `kind` | `providers.<key>.kind` | verbatim canonical identifiers |
| Endpoint | `providers.<key>.base_url` | **safe projection**: scheme + host + optional port + path; **userinfo, all query strings, and all fragments removed** (not classified) |
| Secret reference | `providers.<key>.api_key_env` | **presence + type only** (`required`, `type`); the env-var **name is never echoed**, and no identity is emitted (no canonical non-sensitive opaque identity exists) |
| Route roles | `models.<role>` | existing **route-role labels** only (`topic_hook`, `script`, …) with primary/fallback provider+model identity |
| Availability | config presence | **`configured` only**; a route hop naming a provider absent from the registry is **`unknown` (fail closed)** |
| Generation / provenance | — | **omitted**; the authority defines none, so `provenance.available = false` — no identity is synthesized |

## Non-goals / hard stops (enforced)

- No secret values, tokens, credentials, decrypted material, env contents, secret-store paths, or the
  credential env-var **name** anywhere (UI, API, logs, tests, fixtures, DB).
- No provider health check, credential validation, network probe, model discovery, secret resolution,
  or runtime routing — availability is configuration truth only.
- No provider/model/route mutation, policy rewrite, DB/schema migration, seed, backfill,
  normalization, or new persistence authority. Reading the config initializes/persists nothing.
- No generic capability inventory and no permission/capability inference from kind, model name, or
  route role.
- V1 behavior and active runtime routing are unchanged.

## Evidence

- **Contract/unit:** `python3 gates/settings_truth_test.py` — redaction (no secret value/env name;
  endpoints stripped of userinfo/query/fragment), presence/type-only secret refs, generation
  omission, configured/unknown fail-closed availability, route-role labels without capability
  inference, canonical identifiers, deterministic ordering, non-mutating projection, and a leak check
  against the real `system_config.example.yaml`.
- **Bounded browser check:** `workbench/e2e/settings-admin.spec.ts` (product-regression project) —
  proves populated / empty / unavailable / error states and horizontal-overflow-free layout at
  desktop and 375px, using non-persistent `page.route` mocks (no operator-config mutation).

## Remaining prerequisites (out of this slice)

- **Config generation/provenance authority.** No governed provider/model/route generation identity
  exists; exposing one requires a product/authority decision (governed configuration generations),
  not a read-model change here.
- **IAM / secret store.** A first-class capability inventory, per-provider credential lifecycle, and
  secret-store integration remain owned by IAM/secret custody (#187) and are deliberately not
  implemented by this read-only slice.
