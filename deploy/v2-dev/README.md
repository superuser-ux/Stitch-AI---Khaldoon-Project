# `deploy/v2-dev` — isolated V2 development/testing lane for the rebuilt STITCH-VPS (#389)

**Packaging only. This directory authorizes no STITCH-VPS access, mutation, deployment, secret creation,
or runtime action.** It is a committed, exact-SHA-traceable recipe + runbook. Deployment requires a
**separate later critical directive** that references the merged SHA and re-runs the full gate (fresh
read-only host inventory → GPT pre-approval → operator approval → CC adversarial preflight → named Codex
reconciliation → separate deployment release). Neither approval of #389 nor merge of its PR grants
deployment authority.

This lane is an isolated, candidate-owned **sibling** of the local `tanaghom-acc` acceptance lane
(#337/#338/#342/#351). It never adopts, mutates, or shares objects with that namespace, nor with any
shared service on the host.

---

## Topology contract (frozen)

- **Compose project namespace:** `tanaghom-v2-dev` (containers `tanaghom-v2-dev-{db,gateapi,workbench}-1`,
  network `tanaghom-v2-dev_internal`, volumes `tanaghom-v2-dev_{db_data,init_marker}`, images
  `tanaghom-v2-dev-{gateapi,workbench}:<sha>`).
- **Exactly three services:** PostgreSQL/pgvector (internal only, no host port), governed gate API, V2
  workbench. No V1 dashboard, proxy, init 4th service, public listener, DNS, TLS, firewall, Tailscale,
  provider, or shared-service change.
- **Loopback binding (frozen ports, #389 decision 3):** gate API `127.0.0.1:18110→8000`; workbench
  `127.0.0.1:13101→3001`; PostgreSQL has **no** host-published port. A later deployment revalidates both
  ports; an occupied/drifted port is **STOP** unless a separately reviewed deterministic candidate rule is
  authorized.
- **DB image (frozen digest, #389 decision 1):**
  `pgvector/pgvector:pg16@sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb`
  (immutable digest resolved locally via `docker pull`; a mutable tag alone is never acceptable). This
  freezes the already-selected pg16 dependency; it is not a version change.
- **App images:** built OFF-HOST for the VPS architecture (`linux/amd64`) from the **existing committed recipes** (`deploy/stitch-vps/Dockerfile.api`,
  `workbench/Dockerfile`) verbatim — byte-identical build recipe to the acceptance/production images,
  differing only in tag namespace. Numeric non-root `10001`; fatal runtime-SHA mismatch guard. They reach
  the candidate path as **immutable OCI archives** (`docker save`) and are restored with `docker load`
   (`load-images.sh`, provenance-verified against both config and OCI-manifest digests for portability
   across Docker image stores); the runtime compose references them by exact-SHA tag with
  `pull_policy: never`. **No `build:` stanza, no repository checkout, and no repo build context exist at
  the candidate path** — see *Build & transfer mechanism* below.
- **Data class:** synthetic developer data only, with live provider-backed generation available through
  OpenBao-materialized FILE credentials. The on-screen synthetic disclosure remains truthful
  (`TANAGHOM_WORKBENCH_DATA_CLASS=synthetic`, `TANAGHOM_WORKBENCH_LANE_ID=v2-dev-389`).

## Provenance (7 fields per app image)

For each of `gateapi` and `workbench`: (1) exact merged source SHA from a clean checkout (`build.sh`
refuses a dirty tree or `HEAD != SHA`); (2) committed Dockerfile + build-context identity; (3) OCI
`org.opencontainers.image.revision` label `== SHA`; (4) local image ID; (5) **RepoDigest when present, or
the explicit no-registry-digest statement** — this lane never pushes, so field (5) is the explicit
no-registry state, and the transfer artifact's integrity is instead bound by the **OCI archive sha256**
recorded in `MANIFEST.txt`; (6) running container image ID `==` the reviewed build image ID `==` the
loaded image ID (a `docker save`/`load` invariant, re-verified by `load-images.sh`); (7) runtime-reported
SHA `==` merged SHA — for the workbench via `/api/runtime` + its termination guard, and for the gate API
via the baked `/work/BUILD_SHA` **entrypoint guard** (#389 decision 2: `gateapi-entrypoint.sh` fails the
container non-zero if `TANAGHOM_GATEAPI_EXPECTED_SHA != baked BUILD_SHA`; **no product API endpoint is
added**). A mutable tag alone is never provenance.

---

## Build & transfer mechanism (self-contained; #389 exact-head review correction)

The candidate path `/srv/tanaghom-v2-dev` is genuinely executable **without any repository checkout or
repo build context there** — the prior contradiction (compose build contexts `../..` versus a
candidate-path contract that forbids a repo checkout) is resolved by an **image-transfer provenance
mechanism**:

1. **Build (off-host, clean checkout):** `deploy/v2-dev/build.sh <sha>` refuses a dirty tree or
   `HEAD != sha` and builds both app images from the existing committed Dockerfiles.
2. **Stage (off-host):** `deploy/v2-dev/stage.sh <sha> <staging-dir>` exports each image to an immutable
   OCI archive (`docker save`), records its sha256 + image ID + OCI revision label in `MANIFEST.txt`, and
   assembles the staging dir with **only** the allowed runtime artifacts. The staging dir *is* the
   candidate-path layout.
3. **Transfer:** a later deployment directive copies the staging dir to `/srv/tanaghom-v2-dev` (no repo,
   no source tree, no Dockerfile, no build script).
4. **Load + verify (on-host):** `./load-images.sh` requires an **independently-supplied expected
   `MANIFEST.txt` digest** (`V2DEV_EXPECTED_MANIFEST_SHA256`, or arg1) — the value `stage.sh` emits
   **outside** the candidate directory and which travels out-of-band — and verifies it **before any Docker
   mutation**, so a self-consistent archive+manifest rewrite that travels *inside* the candidate dir is
   still rejected. It then validates the **whole-manifest grammar** (exactly one `manifest_version 2`, one
   reviewed SHA, one frozen `db_image` digest, two image records, seventeen file records; no blank/comment/
   unknown/duplicate/trailing lines) and the **exact filesystem structure** (only the candidate root +
   `./images` dir + the declared files; any other directory or entry type is rejected). Records are
   strictly typed (tag, exact archive name, `archive_sha256`, `image_id` syntax, revision == reviewed SHA,
   numeric user); archive paths are regular **non-symlink** files canonically under `./images` (no
   traversal); every declared runtime-file hash is verified (undeclared/missing/stale rejected). It refuses
   to replace a pre-existing tag pointing to a **different** image; then `docker load`s and verifies the
   loaded image ID + revision. Each ref is tracked as introduced **before** its load, and **dedicated
   `INT`/`TERM` handlers** roll back candidate-only and then **terminate with 130/143** (so execution
   cannot resume into further mutation), while idempotent `EXIT`/`ERR` cleanup rolls back on ordinary
   failure — all removing **only** references this invocation introduced (rollback disarmed only after
   BOTH images verify), leaving prior Docker state intact. It never pulls from a registry. The
   **`MANIFEST.txt` is detached** —
   never self-hashed; it declares the sha256 of every *other* runtime file. `stage.sh` assembles into a
   fresh temporary sibling, rejects a symlink/non-empty target, publishes atomically only after the exact
   allowlist validates, and writes the external manifest-digest evidence beside (not inside) the layout.
5. **Run:** verify the existing private ZITADEL network named by `TANAGHOM_IAM_NETWORK` (default
   `tanaghom-iam-dev`) exists, then run `docker compose -p tanaghom-v2-dev -f docker-compose.yml up -d`.
   Only Workbench joins that external network, solely to reach private Caddy at
   `TANAGHOM_OIDC_INTERNAL_BASE_URL`; no ZITADEL container or listener is changed. The canonical browser
   issuer remains `TANAGHOM_OIDC_ISSUER`. The runtime compose has no `build:` and uses
   `pull_policy: never`, so a missing/unloaded image fails closed rather than pulling.

The gate API init orchestrator + entrypoint are baked **into** the image (`COPY . /work`), so the runtime
needs no candidate-path source. `build.sh`, `stage.sh`, `packaging_test.sh`, and the Dockerfiles are
**build-lane** artifacts (committed in the repo, exercised off-host); they are **not** transferred to the
candidate path.

---

## Numeric resource contract (frozen review targets; #389 decision 5)

Static ceilings are encoded in `docker-compose.yml` as **both** top-level `cpus`/`mem_limit` and
`deploy.resources.limits` so the ceiling binds regardless of the target compose's swarm-vs-standalone
reading:

| service   | CPU  | memory  |
|-----------|------|---------|
| db        | 0.75 | 640 MiB |
| gateapi   | 0.75 | 512 MiB |
| workbench | 0.5  | 512 MiB |
| **aggregate** | **2.0** | **1.66 GiB** |

**Admission (a later deployment measures FRESH headroom — never nominal capacity — and STOPs on any
breach; encoded here as dry/static review values, granting no deployment authority):**

- **Disk:** ≥ **8 GiB** free before build; ≥ **4 GiB** free before start.
- **Memory:** ≥ **1,500 MiB** *available* (not total) before start; admission also reads current
  container memory use and cgroup limits.
- **Swap:** STOP if swap use rises by > **256 MiB** during bring-up.
- **OOM:** STOP on any OOM kill of a candidate container.
- **Restart loop:** STOP if any candidate container restarts > **3 times / 10 min**.
- **Load:** STOP if 1-minute load average exceeds **2.5** (3-core host).
- **Observation:** bounded post-start observation ≈ **10 minutes**; candidate-only automatic stop on any
  threshold breach.

Values are frozen in this reviewed package before any future deployment directive — no deployment-time
improvisation.

---

## Candidate deployment path contract (frozen; #389 decision 4)

*No host action is authorized by this package.* A later deployment directive owns creation and enforces:

- **Exact path:** `/srv/tanaghom-v2-dev` (the only candidate path; never a shared path, never a
  repository checkout).
- **Ownership/modes:** owner `administrator:administrator`; directory mode **`0750`**; ordinary package
  files **`0640`**; executable scripts **`0750`**; the runtime secret file **`0600`**.
- **Allowed files (runtime-only, self-contained — no source tree/Dockerfile/build script):** exactly the
  staged set — `docker-compose.yml` (runtime, no `build:`), `load-images.sh`, `README.md`, `.env.example`,
  `MANIFEST.txt`, and `images/tanaghom-v2-dev-{gateapi,workbench}-<sha>.oci.tar` — plus the single runtime
  env/secret file (`.env`, mode `0600`) created by the deployment mechanism.
- **Canonical-path check + symlink-escape prohibition:** the deployment must resolve the real path
  (`realpath`) and refuse any symlink that escapes `/srv/tanaghom-v2-dev`.
- **No bind mount** from repository checkouts or shared-service paths; the compose mounts only the named
  `db_data` volume (no host path) and builds nothing (`pull_policy: never`, images loaded from the staged
  archives). Any pre-existing content at the candidate path is a later-deployment **hard stop** unless it
  exactly matches reviewed provenance (`MANIFEST.txt`) and the deployment directive explicitly handles it.

---

## Shared-service preservation contract (#389 decision-mapped; deployment-time enforcement)

The rebuilt host runs authoritative live shared services that are an **immutable denylist**:
`tanaghum-backup`, `postiz`, `powerfix` (all their Docker containers/images/networks/volumes) and the
path `/srv/tanaghum-primary`. Public listeners **80/443/8080/8443** and loopback listeners
**4007/7233/8081** were observed (2026-07-28); no `tanaghom-*` object/listener/path was present.

Before any future mutation the deployment must **freeze a pre-mutation manifest** capturing, for every
running object: container IDs, image IDs, compose labels, start times, restart counts, health,
networks/attachments, mounts, volumes, listeners, paths, and relevant resource observations.

**Never** stop, restart, recreate, adopt, attach, detach, prune, remove, relabel, re-own, chmod, rewrite,
or otherwise mutate a denylisted object. **No** `docker system/image/volume/network/builder prune`, broad
cleanup, cache reclaim, firewall, proxy, route, or host-service action. A later deployment **STOPs** for
any new shared-service degradation, restart, recreation, health transition, listener change, attachment,
label change, resource-pressure regression, or unexplained baseline difference. A pre-existing non-healthy
state is recorded and attributed; ambiguous ownership/stability is **STOP**.

---

## Exposure evidence contract (deployment-time)

A later deployment may verify loopback binding through listener inspection and a connection attempt to the
host's non-loopback address **from an already authorized observation point** — it must **not** add routes,
firewall rules, proxy entries, tunnels, temporary public listeners, or scanning infrastructure. If no safe
observation path exists, record the limitation and rely on socket evidence.

---

## Initialization & configuration guardrails

- **Ordinary Gate API startup is DB-read-only (#414).** The entrypoint's `init_db.py` verifies schema +
  the candidate-local ownership marker ONLY. A known-owned database is checked read-only — a normal
  restart/recreate writes **zero rows, including zero `audit_log` rows**, so an infrastructure restart can
  never mutate provenance history and a literal persisted-data fingerprint stays byte-identical. It no
  longer loads the methodology catalogue, seeds fixtures, or opens gates.
- Initialize schema **only** on a newly created candidate-owned database volume proven empty before
  initialization. Apply **only** schema/migrations already committed at the exact SHA (`db/init/schema.sql`
  + `db/migrations/*.sql`, currently through `035`). Any new migration/schema requirement is **STOP**.
- A fresh empty DB gets its committed schema + migrations + the ownership marker (committed-manifest hash +
  cluster identity) on the dedicated marker volume. Routine gate recreation preserves it and **does not
  re-apply** non-idempotent migrations; an unrecognized non-empty DB (missing marker / identity or manifest
  drift) **fails closed**.
- **Synthetic fixtures are an EXPLICIT, idempotent, `v2-dev-389`-only step (#414):**
  `deploy/v2-dev/init_fixtures.py`, run deliberately (never by the entrypoint):
  ```
  docker exec tanaghom-v2-dev-gateapi-1 python /work/deploy/v2-dev/init_fixtures.py --confirm
  ```
  It **refuses** (non-zero, no writes) unless the environment declares the synthetic lane
  (`TANAGHOM_LANE_ID=v2-dev-389` AND `TANAGHOM_DATA_CLASS=synthetic`) and `--confirm` is passed. It is
  **create-missing-only** (loads the catalogue only if absent; inserts the RE2E fixture only if absent;
  opens the fixture gate only if not already open — no teardown, no overwrite of operator-owned config) and
  records a candidate-local **fixture marker** = the fixture GENERATION IDENTITY (**generation + source
  revision + cluster identity**; no secrets). A rerun whose marker matches **all three** is a proven
  **no-op (zero writes)**. When the marker does not fully match it **never re-attests arbitrary data**:
  a different generation/cluster-identity **fails closed** (run the documented teardown + recreate); with
  no marker but **any** pre-existing fixture-related row (catalogue, the RE2E round, **or** its dependent
  slots/topics/RE2E-targeted gates) it attests **only** after the data fully validates as the complete
  expected fixture (complete canon catalogue + exact RE2E round/slots + the **exact committed RE2E topic
  set** — refusing missing/extra/substituted/duplicated topics — + open RE2E-targeted gate), else fails
  closed; only a **genuinely empty slate** (no fixture-related row on any surface), or a
  same-generation/same-identity **source-revision refresh**, does create-missing, then **fully validates
  before (re)writing the marker**.
- Never consume a retained/shared DB, overwrite operator-owned configuration generations, or reinterpret
  historical records. Product methodology, workflow, identity, role, provider, integration, and
  configuration authority remain unchanged — the lane packages only behavior already merged at the SHA.

### Required persisted-data fingerprint check (#414 — deployment/recovery preflight, incl. #412)

Any recovery/deployment validation (e.g. #413-style recovery, and the **#412 preflight**) MUST assert
**literal, exception-free** persisted-data equality across an ordinary Gate API restart/recreate — every
table's exact row count **plus `audit_log` count AND `max(id)`** — byte-identical. Because ordinary startup
is now read-only, this equality holds with **no audit-append exception**; any delta is a real defect and a
**STOP**. Reference fingerprint (read-only) — a schema-qualified per-table EXACT count (no `query_to_xml`/
`xpath`: that XPath returned empty and collapsed every non-`audit_log` count to a constant) plus explicit
`audit_log` count and `max(id)`. Because pure SQL cannot parameterize a table name, build the per-table
count query on the server first, then execute it:

```
# 1) build the schema-qualified, deterministic per-table count query (format()/%I = injection-safe)
PERQ=$(docker exec <db> psql -U tanaghom -d tanaghom -tAX -c \
 "SELECT coalesce(string_agg(format('SELECT %L AS k, count(*)::bigint AS n FROM %I.%I', quote_ident(schemaname)||'.'||quote_ident(relname), schemaname, relname), ' UNION ALL ' ORDER BY schemaname, relname), 'SELECT NULL::text AS k, 0::bigint AS n WHERE false') FROM pg_stat_user_tables")

# 2) execute it: md5 over every table's exact count + explicit audit_log count AND max(id)
docker exec <db> psql -U tanaghom -d tanaghom -tAX -c \
 "SELECT md5(coalesce(string_agg(k||'='||n, ',' ORDER BY k),''))||'|audit_count='||(SELECT count(*) FROM audit_log)||'|audit_max='||coalesce((SELECT max(id)::text FROM audit_log),'0') FROM ($PERQ) s"
```

> The authoritative construction is the `fingerprint()` function in `deploy/v2-dev/packaging_test.sh` §6b;
> prefer running §6b over transcribing the two steps above.

`deploy/v2-dev/packaging_test.sh` §6b proves this (fresh-start-seeds-nothing, first fixture init, a
**mandatory, in-place, genuinely-fresh** Gate API restart with **exact** fingerprint equality, a
**post-restart log-boundary** check that the read-only init record is from that restart, no-op rerun, and
lane refusal).

---

## Candidate-only rollback / interruption contract (#389; deployment-time)

Rollback uses the **exact** Compose project and object names — **never** an unscoped `docker compose
down`:

```
# candidate-only teardown (from /srv/tanaghom-v2-dev, exact project scope)
docker compose -p tanaghom-v2-dev -f docker-compose.yml down -v --remove-orphans
docker rmi -f tanaghom-v2-dev-gateapi:<sha> tanaghom-v2-dev-workbench:<sha>   # loaded transferred images
# then remove ONLY the candidate path artifacts under /srv/tanaghom-v2-dev (the staged runtime files +
# images/*.oci.tar + MANIFEST.txt + .env) — never a shared path
```

The deployment must safely handle **interruption between create, start, initialization, and
verification**: preserve bounded **non-secret** failure evidence; remove only allowlisted candidate
objects/path; recheck shared-service parity against the pre-mutation manifest; and **STOP for human
direction on ambiguous ownership**. It must never `prune`, never touch a denylisted object, and never
remove anything outside the candidate object set + `/srv/tanaghom-v2-dev`.

---

## Secret lifecycle

Phase A (this package) uses **synthetic sentinels only** and proves no real secret is needed to build or
validate. A future deployment may generate **fresh development-only** secret values only after its
separate release; those are **never** committed, printed, or placed in shell history, images, build args,
labels, reports, screenshots, logs, comments, or shared secret stores — stored only through the narrowly
scoped reviewed deployment mechanism at mode `0600`, removed and residue-checked on teardown. `.env` is
git-ignored here; only `.env.example` (non-secret) is committed.

### Reviewer-proxy secret: manager-neutral FILE seam (#387)

`REVIEWER_PROXY_SECRET` is **no longer** a container-env value for v2-dev. It is delivered
memory-resident through a manager-neutral FILE seam, so no persistent env-file/container-env authority
holds the credential:

- **Applications stay manager-neutral.** Gate API (`gates/reviewer_secret.py`) and both server-side TS
  signers (`{dashboard,workbench}/lib/reviewer-secret-file.ts`) read a plain file
  (`REVIEWER_PROXY_SECRET_FILE`), validated on **every** sign/verify: absolute, non-symlink (`lstat` +
  `O_NOFOLLOW` + `fstat`-after-open), regular, zero group/world bits, owner root-or-EUID, ≤64 KiB,
  non-empty, mtime within a positive `REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS` (v2-dev = **900 s**)
  and not future-dated beyond 30 s. `FILE` and direct env together **fail closed** (ambiguous); the dev
  fixture is used only under `TANAGHOM_DEV_MODE` and only when neither is set — never as a fallback for
  an invalid FILE. A single bounded retry covers only the transient atomic-replacement race.
- **Only the host adapter knows OpenBao.** `deploy/v2-dev/openbao/materialize-reviewer-proxy.sh` (a
  **non-secret** host adapter) logs in over loopback via a least-privilege AppRole, fetches exactly one
  KV-v2 value, validates it, **revokes the fetched token and proves reuse-denial before publishing**,
  then atomically publishes to the host tmpfs `/run/tanaghom-secrets/reviewer_proxy_secret` (dir `0500`,
  file `0400`, owner `10001:10001`; temp created at final owner/mode before same-dir rename). A systemd
  oneshot (`User=10001` with `RuntimeDirectory=tanaghom-secrets`; the fetch runs as root via the `!`
  `ExecStart` prefix while keeping the filesystem sandbox) + a 5-minute timer refresh it. The materializer, policy, units, and README ship as **non-secret
  reviewed inputs inside the candidate layout** (`openbao/`, manifest-hashed + allowlisted by
  `stage.sh`/`load-images.sh`); the cutover **copies these manifest-verified artifacts** to the host
  OpenBao infrastructure (`/srv/tanaghom-dev/openbao` + `/etc/systemd/system`) — they are not executed
  from the app candidate path. **No secret-bearing artifact enters `/srv/tanaghom-v2-dev`** (RoleID,
  SecretID, tokens, values, generated credentials stay in the root-only host custody tree). No
  application OpenBao SDK or network attachment.
- **Compose** mounts `/run/tanaghom-secrets` **read-only** into gate API + workbench only and sets
  `REVIEWER_PROXY_SECRET_FILE` + `REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS`; the direct
  `REVIEWER_PROXY_SECRET` env is removed from both services.
- **Provider credentials** use the same manager-neutral FILE boundary in the gate API. Separate OpenBao
  AppRoles materialize `openrouter_api_key` and `groq_api_key`; the runtime exposes only configured/source
  metadata and never values. Developer writer stub mode is not forced.
- **Developer IAM session signing** extends that exact materializer template with the allowlisted
  `iam-session` identifier. Its dedicated read-only AppRole can read only
  `tanaghom/data/dev/iam/session` and atomically publishes `iam_session_secret` into the same tmpfs.
  The package freezes issuer `http://iam.localhost:13210`, callback
  `http://127.0.0.1:13101/api/auth/callback`, and post-logout return `http://127.0.0.1:13101/` while
  leaving IAM disabled and the public PKCE client ID operator-supplied. No OIDC client secret exists.
- **Provenance.** `/health` (and `/gw/health`) expose `reviewer_secret_configured` (bool) +
  `reviewer_secret_source` (`file`/`env`/`dev`/`null`) — **never** the value.
- **Rollback (cutover phase).** Restore the prior exact compose/images; materialize the credential into a
  temp root-only `0600` rollback env file (no output); recreate only gate/workbench; verify; remove the
  candidate timer/service/tmpfs material; report restored **env authority as the weaker state**. Retain
  OpenBao data/snapshots/audits/custody. See `deploy/v2-dev/openbao/README.md`.

---

## Local Phase-A validation (authorized; no VPS)

From the repository root, on a clean checkout at the reviewed SHA:

```
deploy/v2-dev/packaging_test.sh
```

This builds both images from the clean head, **stages the actual candidate-path layout** to a temp dir
via `stage.sh` (runtime compose + OCI archives + `MANIFEST.txt` + `load-images.sh`), asserts the staged set
contains only the allowed runtime artifacts (no source tree / Dockerfile / build script / `build:` stanza),
then **removes the locally-built app images and brings the stack up purely from the transferred archives**
(`load-images.sh` → `docker compose up` from the temp staging dir, proving the candidate layout is
executable with no repository present). It runs the full static + provenance + negative + idempotency +
private-stub-smoke matrix and tears down **only** the isolated local v2-dev resources (including the temp
staging dir). It never touches a VPS, a registry push, or the `tanaghom-acc`/#337 lane.

**Test truthfulness (#389 decision 6):** the genuinely affected surfaces are this packaging test and the
`workbench/` TypeScript/production build. This lane does not exercise the V1 dashboard Playwright suite;
no such coverage is claimed.

---

## Hard stops

STOP on: wrong/dirty SHA; uncommitted or host-local recipe; unresolved namespace/path/port/object
collision; external/adopted/shared object; public exposure; live-credential need; schema/product/authority/
dependency change; shared-service mutation; missing numeric thresholds; mutable-tag-only provenance;
non-root/runtime identity failure; secret residue; retained-volume reuse; initialization
overwrite/destruction; inability to prove candidate-only rollback; any expansion beyond packaging-only
scope.

## V2 boundary

This lane does not satisfy, bypass, or modify the V2 vertical-slice ledger. It adds no frontend-local
authority, display-order derivation, lifecycle mutation, provider behavior, schema, or functionality to
make a demonstration pass. It packages only behavior already merged at the selected SHA.
