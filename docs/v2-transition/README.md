# V2 transition record — one backend authority, two temporary frontend consumers

Produced by **#293 (Stage 0)** under evaluation **#279** and delivery ledger **#294**.
Status: **transition scaffold only.** This record authorises no promotion, retirement, sunset,
default-route switch, deployment, or indefinite dual maintenance.

---

## 1. The shape

There is **one** authority and **two temporary** consumers of it:

```
                    ┌──────────────────────────────┐
                    │  Tanaghom gate API + engine  │   ← SOLE AUTHORITY
                    │  lifecycle · approvals ·     │     (lifecycle, policy resolution,
                    │  policy snapshots · audit ·  │      snapshots, audit, publication
                    │  publication receipts ·      │      receipts, provider/secret
                    │  provider/secret boundaries  │      boundaries, agent contracts)
                    └───────────┬──────────────────┘
                                │  one API build, one database
                ┌───────────────┴────────────────┐
                │                                │
   ┌────────────▼─────────────┐    ┌─────────────▼──────────────┐
   │ V1 — dashboard/          │    │ V2 — workbench/            │
   │ :3000 · DEPLOYABLE       │    │ :3001 · TRANSITION LANE    │
   │ signed /gw proxy         │    │ GET-only allowlisted seam  │
   │ full lifecycle surface   │    │ read-only Stage 0 scaffold │
   │ ships to GFWS            │    │ Mac development only       │
   └──────────────────────────┘    └────────────────────────────┘
```

**V2 is not a second product.** It is another projection over the same authority. It defines no
policy, no engine, no schema, and no shadow model of any conserved contract.

## 2. V1 preservation baseline

| Item | Value |
|---|---|
| **Baseline SHA** | `bd93fda` (synchronized `main`) |
| **Proposed immutable tag** | `v1/baseline-2026-07-15-bd93fda` — **PROPOSAL ONLY** |
| Production build | `next build` (in `dashboard/`) |
| Production start | `next start -p 3000` |
| Container | `tanaghom-dashboard` |
| Port map | `127.0.0.1:3000:3000` |
| Route | nginx `proxy_pass http://dashboard:3000` |
| Build identity | `TANAGHOM_BUILD_SHA` — **runtime** truth, never baked (#202) |
| Environment | `API_BASE`, `REVIEWER_PROXY_SECRET`, `TANAGHOM_DEV_MODE`, `CLIENT_TRIAL_MODE`, `PUBLIC_BASE_URL`, `TANAGHOM_OIDC_*`, `TANAGHOM_SESSION_SECRET` |
| Lockfile | `dashboard/pnpm-lock.yaml` — authoritative for V1, **unchanged** |

> The tag is **not created, pushed, moved, or mutated** by #293 (D5). Tag creation stays human-gated.

**Shared-backend rule:** changes to the API/database stay backward-compatible with V1 until a later
operator-approved retirement gate. V1 is the deployable client surface for the whole of Stage 0.

## 3. V2 lane contract

| Item | Value |
|---|---|
| Path | `workbench/` |
| Package name | `tanaghom-workbench` |
| Local port | **3001** (never 3000) |
| Build output | `workbench/.next` |
| Runtime identity | `GET /api/runtime` → `surface: "workbench"`, `lane: "v2-transition"`, `identity: "none"` |
| Build identity | `TANAGHOM_WORKBENCH_BUILD_SHA` — runtime truth, distinct env from V1 |
| Package manager | pnpm (same as V1), own self-contained `workbench/pnpm-lock.yaml` |
| API access | `GET`-only, closed allowlist (below) |
| Deployment | **none.** Mac development only. |

### V2's complete read boundary (D2)

V2 may reach **exactly** these, and nothing else:

| Method | Path | Why it is safe |
|---|---|---|
| `GET` | `/gw/health` | `gates/api.py:248` — no principal required |
| `GET` | `/gw/rounds` | `gates/api.py:692` — no principal required |
| `GET` | `/gw/rounds/{round_id}` | `gates/api.py:487` — no principal required |

Everything else fails closed **at V2's own boundary**, before any upstream request:

- a **guarded** endpoint (e.g. `/gw/me/pending-approvals`) → `403`
- a **non-allowlisted** GET (e.g. `/gw/principals`) → `403`
- **`HEAD` and `OPTIONS`** → `405`, refused by **declared handlers**. Next 15 would otherwise
  synthesize `HEAD` from `GET` (running the route and issuing a real upstream GET) and answer
  `OPTIONS` with `Allow: GET, HEAD, OPTIONS`. Exporting only `GET` is **not** sufficient — this was
  a real gap found by Codex's exact-head review of `11db665` and is now closed by declared code
  rather than an assumed framework default.
- **any** mutating method (`POST`/`PUT`/`DELETE`) → `405` (no handler exported)
- IAM/OIDC enabled → `501`, truthfully refusing rather than serving unauthenticated data in an
  authenticated runtime

V2 signs no principal, holds no `REVIEWER_PROXY_SECRET`, and cannot become a parallel authority
path. **Tanaghom still decides authority at decide time (#10).**

## 4. Conserved contracts — V2 duplicates, replaces, and reinterprets none

SDAM/ResourceSpace binding/readiness/handoff/evidence/audit (#233/#244/#250/#255/#259) ·
provider-neutral `pub.v1` persistence + manual receipt, Postiz as a replaceable future executor
(#199/#200) · AVP provider-neutral media-edit contract and BrandShield/KPI/analytics joins as
**documented future integrations, not live** · OIDC→principal mapping and "IAM proves identity;
Tanaghom decides authority" (#172/#190/#194) · principal/role/group/approval authority,
AgentRep/delegation, provenance (#197) · multi-agent/model/provider/tool routing truth (#19) ·
agent capability/binding governance (#21) · cross-system authority mapping (#238) ·
secret-reference separation and #187's independent production secret-authority stream
(**OpenBao/Infisical never becomes Tanaghom IAM or product authority**).

**Stage 0 claims nothing about generation.** It invokes no writer, creates no client run, and makes
no generated-content-quality claim.

## 5. The exit gate

| Field | Value |
|---|---|
| **Owner** | **@Kholio (operator)** — sole decision authority (D4) |
| **When** | After Stage 1 (#292) is accepted against #294's definition of done, and no earlier |
| **Authorised by #293** | **Nothing.** #293 authorises no promote/retire/abandon/extension decision. |

The gate has **exactly three** permitted outcomes:

1. **Promote V2 and retire V1** — requires a separate reviewed directive covering GFWS cutover,
   route/port migration, and a V1 retirement plan.
2. **Abandon V2 and retain V1** — `rm -rf workbench/`, delete this record, revert the #293 PR.
   V1 is untouched by construction, so this costs nothing.
3. **Extend coexistence for a specifically approved bounded period** — requires an explicit end
   date and a named owner. **Indefinite dual maintenance is not an outcome.**

### Measurable decision criteria

The gate is decided on evidence, not preference:

| Criterion | Measure |
|---|---|
| Stage 1 completeness | #292 satisfies #294's Stage 1 exit with no unresolved P0/P1 |
| Contract fidelity | V2 still defines no policy/engine/schema; boundary still closed; conserved contracts untouched |
| Operator acceptance | An operator can perform the Stage 1 job in V2 at 375px/tablet/desktop without a hidden contract gap |
| Branding & accessibility | Exact canonical marks with correct accessible names at all three viewports |
| V1 compatibility | V1 remains independently deployable and unbroken throughout |
| Cost of coexistence | Dual-maintenance burden measured against remaining stages |

**No automatic sunset.** If the gate is not decided, the default is that V1 remains the deployable
product and V2 remains a development-only lane.

## 6. GFWS topology — PROPOSED AND UNEXECUTED

> **Nothing in this section has been executed.** No GFWS filesystem, service, container, route,
> port, Tailscale, DNS, or client-data change was made by #293, and none is authorised by it.
> Any dual-surface deployment or cutover **requires a separate reviewed directive and operator
> approval** (§4).

Were a dual surface ever approved, the *proposed* shape would be: V1 keeps `tanaghom-dashboard`,
`127.0.0.1:3000:3000`, and the nginx root route exactly as today; V2 would need its own service
name, its own loopback port, and its own explicitly reviewed route — never V1's port, service, or
root route. Client DNS/Tailscale would remain unchanged until a promotion directive says otherwise.

**Mac is the development/validation host. GFWS is the client deployment host.** #293 ran only on the
Mac.

## 7. Declared debt (accepted, bounded, not hidden)

| Debt | Consequence | Mitigation / owner |
|---|---|---|
| **Brand copy drift** — V2 holds its own copy of the canonical marks (Next serves per-package `public/`) | V1's mark could change while V2 serves a stale one | `pnpm verify:brand` fails on any sha256 drift against `dashboard/public/brand/**`. Residual: nothing forces it on a V1-only change. |
| **Typography divergence** — V2 uses a system font stack; V1 vendors Geist/Amiri/Cairo/IBM Plex Arabic | V2 is not pixel-identical to V1; Arabic renders with system fonts | Deliberate — §2 forbids bulk-copying V1 source. Belongs to the slice that needs typography. |
| **Two lockfiles** — V1 and V2 can drift on Next/React versions | Divergent framework behaviour over time | Accepted for isolation; a shared root workspace would re-hoist V1 and break its frozen-lockfile Docker build. Both currently pin exact **Next 15.4.11 / React 19.0.0** and `pnpm@10.15.1` (#297). The drift risk is real — it is contained by upgrading both roots together and proving them at one exact head, not by the lockfiles themselves. |
| **Dual maintenance** | Real ongoing cost | Bounded solely by the exit gate above. |
| **#152 trap inherited** | `next/dynamic` broke the RSC client-reference manifest on **Next 15.1.4**, where #152 was discovered and proved | V2 uses `React.lazy` only. That remains the retained convention on **15.4.11** and was re-proved there (#297); whether the trap still reproduces on 15.4.11 is deliberately untested, since nothing depends on the answer. Recorded in `workbench/README.md`. |

## 7a. Two evidence lanes (both mandatory)

Stage 0's truthful-state acceptance has **two** lanes, and neither substitutes for the other. This
distinction was required by Codex's exact-head review of `11db665` (P1.3).

| Lane | What it is | What it proves | Where |
|---|---|---|---|
| **Deterministic automation** | Playwright with `page.route(...).fulfill(...)` inducing failures | The empty/error branches are correct, repeatably, with no sleeps/retries | `workbench/e2e/workbench-shell.spec.ts` |
| **Operator-visible real path** | A **real** Tanaghom API against **isolated ephemeral non-client state** | The states are real product behaviour, not artefacts of a mock | procedure below |

Route interception is valid **regression** evidence. It is **not** operational proof: the binding
clarification on #293 forbids mocked frontend responses as operator-visible acceptance.

### Real-path procedure (reproducible; read-only; never touches client data)

It runs entirely on **isolated ephemeral** infrastructure: a throwaway database, a **real** gate API
on `:8109`, and a throwaway V2 on `:3002`. The shared API (`:8009`), V1 (`:3000`), V2 (`:3001`) and
the `tanaghom` database are never touched — V2 only ever issues GETs.

```bash
# 1. Isolated ephemeral database with the REAL schema (never the tanaghom database)
DBN=tanaghom_wb_stage0_evidence
docker exec -i tanaghom-db sh -lc "psql -U \"\$POSTGRES_USER\" -d postgres \
  -c 'DROP DATABASE IF EXISTS $DBN;' -c 'CREATE DATABASE $DBN;'"
docker exec -i tanaghom-db sh -lc "psql -q -U \"\$POSTGRES_USER\" -d $DBN" < db/init/schema.sql
for f in $(ls db/migrations/*.sql | sort); do
  docker exec -i tanaghom-db sh -lc "psql -q -U \"\$POSTGRES_USER\" -d $DBN" < "$f"; done

# 2. A REAL Tanaghom gate API against it, on an isolated port
docker run -d --name tanaghom-gateapi-ephemeral --network tanaghom_default --env-file .env \
  -e DB_HOST=db -e DB_PORT=5432 -e DB_NAME=$DBN -e TANAGHOM_DEV_MODE=1 -e TANAGHOM_WRITER_STUB=1 \
  -v "$PWD":/work -w /work -p 8109:8000 python:3.12-slim \
  bash -lc "pip install -q -r gates/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000"

# 3. A throwaway V2 pointed at it
cd workbench && PORT=3002 API_BASE=http://localhost:8109 \
  TANAGHOM_WORKBENCH_BUILD_SHA=$(git rev-parse --short HEAD)-evidence pnpm start

# 4. Observe at http://localhost:3002
#    EMPTY    — the real API genuinely has zero rounds -> the empty state, not an error
#    ERROR    — `docker stop tanaghom-gateapi-ephemeral`, reload -> the real failure + Retry
#    RECOVERY — `docker start tanaghom-gateapi-ephemeral`, click Retry -> real recovery

# 5. Tear down (ephemeral only)
docker rm -f tanaghom-gateapi-ephemeral
docker exec -i tanaghom-db sh -lc "psql -U \"\$POSTGRES_USER\" -d postgres -c 'DROP DATABASE $DBN;'"
```

**This lane earned its keep immediately:** it exposed a defect the induced tests could not see —
`RuntimeStrip` used a single `Promise.all` over `/api/runtime` + `/gw/health`, so a genuinely
unreachable API discarded V2's *own successful* identity read and fell back to the `…` **loading**
placeholder, misreporting "still loading" for a known, final build during an outage. The reads are
now independent, and `workbench-shell.spec.ts` carries the regression.

## 8. Sequencing after #293

1. **#292 — Stage 1 Schedule** (owns governed ordering, display-code generations, optimistic
   concurrency). Targets its new interaction UI to V2; V1 gets compatibility support only.
   **Topic work cannot open until Schedule satisfies #294's exit gate.**
2. Bounded synthetic **Mobiscroll** schedule-adapter proof (#279), if #292 is accepted.
3. Separate **Payload / NocoBase / Directus** control-plane proof — **CLOSED as REJECT (#316)**:
   all three were rejected on-merits and #294's external-adapter expectation was **cancelled**;
   Tanaghom-governed authoring is retained. No adapter dependency remains.
4. **#268** remains mandatory at **Stage 2**: proactive bounded history context in the first
   generation prompt, retaining post-generation embedding comparison/retry as defence in depth.
5. In the independent authority lane, **#187**'s production secret-authority choice — including the
   OpenBao reconsideration required by #223 — must resolve before production credential-manager
   adoption or real AVP/Postiz/BrandShield credential activation. It does not block this read-only
   scaffold.
