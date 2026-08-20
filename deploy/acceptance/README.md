# Private V2 acceptance packaging (#338)

Committed, reproducible, exact-SHA-traceable container packaging for the **local, private, stub-only**
acceptance topology: PostgreSQL/pgvector (internal) + governed API + V2 workbench. **No V1, no public
interface, no VPS/registry, no live secret.** This directory only *packages*; it never deploys.

## Artifacts

| File | Role |
|---|---|
| `../stitch-vps/Dockerfile.api` | Governed API image — numeric non-root, OCI revision label (shared with the public build; default CMD serves only). |
| `../../workbench/Dockerfile` | V2 workbench image — multi-stage Next **standalone**, numeric non-root, OCI revision label + **baked runtime SHA**. |
| `../../workbench/docker-entrypoint.sh` | Terminates non-zero if a runtime `TANAGHOM_WORKBENCH_BUILD_SHA` override diverges from the baked SHA. |
| `init_db.py` | Applies **only existing committed** schema + migrations + catalogue loader + synthetic seed, fail-fast. |
| `gateapi-entrypoint.sh` | Runs `init_db.py` fail-fast, then `uvicorn` — governed init inside gateapi startup (no init service). |
| `docker-compose.yml` | Exactly three services; loopback-only app ports; DB internal; stub default; fail-closed on missing non-secret vars. |
| `build.sh` | Validated exact-SHA build of both images with provenance. |
| `packaging_test.sh` | Automated proof (build/provenance/non-root/closure/sentinel/digest/private-stub-smoke/negatives). |

## Build (exact SHA, clean checkout)

```bash
# from a clean checkout whose HEAD == the reviewed 40-char SHA:
deploy/acceptance/build.sh <full-40-char-sha>
# rejects: missing / abbreviated / malformed / dirty tree / HEAD != SHA
```

Both images are tagged `:<sha>` and carry `org.opencontainers.image.revision=<sha>`; the workbench also
bakes the SHA so its `/api/runtime` reports it. **A tag alone is not the provenance** — verify the
immutable label + a precise local image ID (`docker inspect --format '{{.Id}}'`) and, when you export,
an OCI archive digest (`docker save <img> | sha256sum`). A RepoDigest exists only if you push (this flow
does not).

## Start / health / private-listener verification / teardown

```bash
# required non-secret vars fail closed if unset; secret is injected at runtime only.
export ACC_GIT_SHA=<full-40-char-sha>
export ACC_API_PORT=18110 ACC_WB_PORT=13101
export DB_PASSWORD=<temp> REVIEWER_PROXY_SECRET=<temporary-acceptance-secret>   # runtime-only; never committed

docker compose -f deploy/acceptance/docker-compose.yml up -d --build

# health / runtime identity / stub / canonical /gw:
curl -s http://127.0.0.1:$ACC_WB_PORT/api/runtime            # {"surface":"workbench","build":"<sha>",...}
curl -s http://127.0.0.1:$ACC_WB_PORT/gw/health              # {"writer_mode":"stub",...}
curl -s http://127.0.0.1:$ACC_WB_PORT/gw/rounds              # canonical read through /gw -> API

# private-listener check — app ports bind 127.0.0.1 only; DB has no host port:
docker compose -f deploy/acceptance/docker-compose.yml ps

# teardown removes ONLY these local proof resources (containers, network, and the synthetic DB volume):
docker compose -f deploy/acceptance/docker-compose.yml down -v --remove-orphans
```

### Ownership / fresh-volume contract

Governed init runs fail-fast inside gateapi startup (before uvicorn) and applies **only** existing
committed schema + migrations + catalogue loader + synthetic seed, unchanged — it writes **no** new
state into PostgreSQL. Ownership of an initialized database is proven by a **container-local marker**
(in the gateapi container's writable layer, not a volume) that binds the complete committed
initialization manifest to the database cluster identity. Consequences:

- A **same-container restart** (`docker compose restart gateapi`) keeps the marker → recognized → healthy.
- **Recreating** the gateapi container (`up --force-recreate`, replacement, or a new stack) against a
  **retained non-empty DB** loses the marker → **fails closed** and refuses to serve.
- A marker whose manifest or database identity does not match → **fails closed**.

The acceptance lane is fresh-synthetic-only: to re-run, tear down with `down -v` and recreate with a
**fresh volume**. Never point a recreated stack at a retained database.

### The lane declares itself synthetic (#351)

Because the data here is synthetic, the workbench service is given two literal, non-secret
declarations so the surface says so on screen:

| variable | value |
|---|---|
| `TANAGHOM_WORKBENCH_DATA_CLASS` | `synthetic` |
| `TANAGHOM_WORKBENCH_LANE_ID` | `private-acceptance-337` |
| `TANAGHOM_WORKBENCH_DEV_PRINCIPAL` | unset → `khal`; explicit `khal` or `huda` only, with `TANAGHOM_DEV_MODE=1` |

`/api/runtime` then reports both, and the workbench renders its synthetic-lane banner with that
stable lane id, so a human reviewer never has to be told out-of-band what they are looking at.

This declaration is made **here, by the topology**, and deliberately not defaulted in application
code. The workbench resolves `data_class` to `unknown` — and renders **no** banner — unless the
declared value resolves to `synthetic`. A code-level default of `synthetic` would make every
deployment claim synthetic data, including one pointed at something real, which is worse than saying
nothing.

**How the value is resolved (existing behaviour, unchanged by #351).** `laneDataClass()` in
`workbench/app/api/runtime/route.ts` **trims and lowercases** the environment value before comparing
it, so `synthetic`, `Synthetic`, and `" SYNTHETIC "` all resolve to `synthetic` and correctly
disclose the lane. Anything that does not match after that normalization — `real`, `synthetic-ish`,
a stale value, an empty string, or the variable being absent — resolves to `unknown` and renders no
banner. It fails closed: the only reassuring answer requires an explicit, matching declaration.

The committed value here is the plain lowercase literal, so it does not rely on that normalization.

Both are scoped to the workbench service only. This file declares each service's environment
explicitly and uses no anchors, aliases, `x-` extensions, `env_file`, or merge keys, so neither value
can reach `db` or `gateapi`.

### Two-principal local acceptance

Two separate Workbench server instances may use the same private acceptance Gate API and synthetic
database by setting `TANAGHOM_WORKBENCH_DEV_PRINCIPAL` independently:

```bash
# Workbench A — default/backwards-compatible Khal fixture
TANAGHOM_WORKBENCH_DEV_PRINCIPAL=khal TANAGHOM_DEV_MODE=1 \
  API_BASE=http://127.0.0.1:18114 PORT=13114 pnpm start

# Workbench B — bounded Huda fixture, separate server process/port
TANAGHOM_WORKBENCH_DEV_PRINCIPAL=huda TANAGHOM_DEV_MODE=1 \
  API_BASE=http://127.0.0.1:18114 PORT=13115 pnpm start
```

This is server-side identity setup only. `/gw` signs the selected canonical fixture principal with
the existing HMAC contract; the browser cannot choose or override it, and the Gate API remains the
authority for assignment, quorum, decisions, sign-off, and resolve. The selector is rejected outside
explicit development mode and rejects every principal other than `khal` or `huda`. IAM mode continues
to use the authenticated session principal and does not use this seam.

`workbench/e2e/private-acceptance-declaration.spec.ts` locks all of this: the committed declarations,
workbench-only scoping, the unchanged private topology, and the banner's positive **and** negative
behaviour. It reads the committed compose file statically and mocks `/api/runtime` — it never builds
an image and never instantiates this three-service lane.

## Automated proof

```bash
ACC_API_PORT=18110 ACC_WB_PORT=13101 deploy/acceptance/packaging_test.sh
```

Proves: clean-head build; labels == head; numeric non-root; standalone file closure; runtime acceptance
secret absent from every image layer/config/label/history/filesystem (sentinel, never printed); local
image ID + OCI archive digest recorded; three-service private stub stack healthy with fresh committed
initialization; workbench runtime SHA == build head; `workbench → /gw → API` smoke; loopback-only ports;
no V1. Negative guards: a SHA ≠ clean HEAD is rejected; a divergent runtime SHA override terminates the
workbench non-zero.

## Boundaries

Acceptance-only and local. No VPS path, production restart policy, registry coordinate, public
interface, live-secret name, host networking, destructive host cleanup, or #337-lane command lives here.
Secrets are runtime-only. Initialization invokes existing committed schema/migrations/catalogue/seed
**unchanged** — it adds no schema, migration, seed, authority, or configuration logic.
