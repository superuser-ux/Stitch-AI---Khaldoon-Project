# Tanaghom Workbench (V2) — transition lane

**Read the transition record first: [`docs/v2-transition/README.md`](../docs/v2-transition/README.md).**

V2 is a **transition lane, not a second product**. Tanaghom's gate API + engine remain the sole
authority. V2 is another projection over the same API — it defines no policy, no engine, no schema,
and no shadow model of any conserved contract.

**Stage 0 (#293) is read-only.** It invokes no writer, performs no generation, creates no client
run, and makes no generated-content-quality claim. It is **Mac development only** and is never
deployed.

---

## What V2 is allowed to touch

`GET`-only, closed allowlist — the endpoints Tanaghom already leaves intentionally unguarded:

| Method | Path |
|---|---|
| `GET` | `/gw/health` |
| `GET` | `/gw/rounds` |
| `GET` | `/gw/rounds/{round_id}` |

Everything else fails closed at V2's own boundary: a guarded endpoint → `403`, a non-allowlisted
GET → `403`, **`HEAD`/`OPTIONS` → `405` (explicitly refused)**, any other method → `405`, IAM
enabled → `501`. V2 signs no principal and holds no `REVIEWER_PROXY_SECRET`. See
`lib/api-contract.ts`.

> **`HEAD`/`OPTIONS` are refused by declared handlers, not by a framework default.** Next 15
> synthesizes `HEAD` from a `GET` handler (which would run the route and issue a real upstream GET)
> and answers `OPTIONS` itself with `Allow: GET, HEAD, OPTIONS`. Exporting only `GET` is therefore
> **not** sufficient to close the boundary — `app/gw/[...path]/route.ts` exports `HEAD` and
> `OPTIONS` purely to return `405`. Do not remove them.

## Run it

Prerequisites: the gate API on `:8009` (`docker ps` → `tanaghom-gateapi`). V2 reads it via
`API_BASE`.

```bash
# ---- V2 alone (port 3001) ----
cd workbench
pnpm install
pnpm preflight                       # refuses if 3001 is taken — never kills anything
TANAGHOM_WORKBENCH_BUILD_SHA=$(git rev-parse --short HEAD) \
  API_BASE=http://localhost:8009 pnpm dev
# -> http://localhost:3001

# ---- V1 alone (port 3000) — unchanged by #293 ----
cd dashboard
pnpm install
TANAGHOM_DEV_MODE=1 API_BASE=http://localhost:8009 \
  TANAGHOM_BUILD_SHA=$(git rev-parse --short HEAD) pnpm dev
# -> http://localhost:3000

# ---- BOTH, side by side, against the SAME api ----
# Two terminals; each command above as-is. They share one API and one database and
# never collide: different ports, different processes, different build output.
```

Production-mode preview (what the Stage 0 evidence runs against):

```bash
cd workbench && pnpm build
TANAGHOM_WORKBENCH_BUILD_SHA=$(git rev-parse --short HEAD) \
  API_BASE=http://localhost:8009 pnpm start        # :3001
```

### Ports

| Port | Owner | Note |
|---|---|---|
| 3000 | **V1 dashboard** | Production port. V2 must never take it — `pnpm preflight` refuses it outright. |
| 3001 | **V2 workbench** | Default. `PORT=<n>` overrides it for `preflight`, `dev`, and `start` alike. |
| 3106–3109 | V1 IAM e2e specs | Leave free when running V1's suite. |
| 8009 | gate API | Shared authority. |

**Port conflicts fail clearly and V2 never stops another process** (#293 §6). If the port is busy,
`preflight` names the pid/command and exits non-zero; reclaiming it is your deliberate act:
`kill $(lsof -tnP -iTCP:3001 -sTCP:LISTEN)`. Note `pkill -f "next start"` does **not** work — Next
re-execs into `next-server`. Kill by port.

**One port contract.** `scripts/preflight-port.mjs` is the single source of truth: `dev` and
`start` gate on it and then take the port *from* it
(`-p $(node scripts/preflight-port.mjs --print)`), so `PORT=3005 pnpm dev` really does bind 3005.
Never hard-code a port back into those scripts — at `11db665` they did, which silently disconnected
a passing preflight from the process that actually started. `e2e/port-contract.spec.ts` locks this.
Port 3000 is refused on every path, including `--print`.

## Validate

```bash
pnpm verify:brand    # exact canonical marks — fails on any sha256 drift vs dashboard/public/brand/**
pnpm typecheck       # tsc --noEmit
pnpm build           # production build
pnpm validate        # all three, in order

# Discovery — the union of both gates below. Run it to prove nothing was dropped.
pnpm gate:discovery
```

### The two gates (#348)

There is **no single "run everything" command, deliberately.** The two gates need datasets that
cannot coexist: the product-regression lane carries ~18 generated/review runs, while the synthetic
acceptance lane must contain **exactly four** and asserts that fact. One undifferentiated invocation
could only ever be green by weakening one of those contracts, so the *selection* is split and both
assertions stay intact. A generic alias is not provided — it would be a partial selection wearing a
full-suite name, which is the exact false-green this repo has been bitten by.

**Gate 1 — product regression.** Every spec except the acceptance spec, against the deterministic
fixture lane. Needs V1, V2, and the gate API all pointed at that lane:

```bash
V1_URL=http://localhost:<v1-port> \
WB_URL=http://localhost:<v2-port> \
API_BASE=http://localhost:<lane-api-port> \
LANE_DB=<deterministic-lane-db> \
  pnpm gate:regression
```

The lane must be provisioned through the governed chain before this runs — `POST /rounds` → open
`schedule_review` → `decide(approve)` → `resolve` (which bootstraps the Stage 2A policy and mints the
job) → open `topic_review`, plus a governed placement. Seeds alone do **not** create a generation
job, so specs that need generated Topics will fail loudly rather than skip.

**Gate 2 — synthetic acceptance.** Only `acceptance-lane-342.spec.ts`, only against the synthetic
acceptance lane (`tanaghom_acc342`). It requires V2 started with `TANAGHOM_WORKBENCH_LANE_ID` and
`TANAGHOM_WORKBENCH_DATA_CLASS=synthetic`, or the lane banner it asserts will not render:

```bash
WB_URL=http://localhost:<acceptance-v2-port> \
API_BASE=http://localhost:<acceptance-api-port> \
LANE_DB=tanaghom_acc342 \
  pnpm gate:acceptance
```

See `docs/v2-transition/acceptance-lane-342.md` for that lane's topology, seed, reset and teardown.

**Accounting.** `pnpm gate:discovery` lists both projects; the two gates are disjoint by construction
(`testIgnore`/`testMatch` complements) and their counts must sum to it exactly. Report each gate's
outcome separately and the union explicitly — never call either one "the full suite".

Pointing a gate at the wrong lane fails on purpose: the acceptance gate trips its four-run assertion,
and the regression gate trips its reviewed-product preconditions.

Both gates inherit V1's #263 discipline verbatim: **serial, `workers:1`, `retries:0`**. Never run
either concurrently with `gates.api_selftest`, V1's Playwright suite, or a second process addressing
the same lane. Read the **native exit code unpiped** — piping through `tail` hides both the failure
count and the exit status. A failure is reported truthfully — never retried until it passes.

Gate 1 covers Stage 0's D3 scope (branding at 375px/tablet/desktop on **both** V1 and V2, RTL safety,
truthful loading/empty/error states, read-boundary rejections, the non-mutating coexistence proof)
plus the V2 feature specs added since. Gate 2 is human-acceptance evidence for the schedule surface.

## Conventions that are load-bearing here

- **`React.lazy`, never `next/dynamic`** (#152). On **Next 15.1.4**, where #152 was discovered and
  proved, any `next/dynamic()` in a client-entry module broke the RSC client-reference manifest.
  Both roots now pin exact **Next 15.4.11 / React 19.0.0** (#297) — V2 still pins the *same* version
  as V1, which is the point: they are upgraded together. `React.lazy` + `Suspense` remains the
  retained repository convention and was re-proved at 15.4.11. Whether the trap still reproduces
  there is deliberately untested; reverting to `next/dynamic` would need its own evidenced directive.
- **Canonical identifiers only.** `slot_id` is rendered verbatim. V2 derives **no** human-facing
  display code and **no** ordering — that is #292's Stage 1 contract (persisted, versioned,
  audited). Inventing one here would silently pre-empt it.
- **Build identity is runtime truth** (#202 principle). `TANAGHOM_WORKBENCH_BUILD_SHA` is read at
  runtime and nothing is baked. Unset means an explicit `"unknown"`, never a guess.
- **Truthful states only.** A failed read renders as an error with the real upstream detail and a
  retry — never as "empty", never as a fabricated success.
- **Own lockfile.** `workbench/` is a self-contained pnpm project, exactly like `dashboard/`. This
  repo is **not** a monorepo; do not add a root workspace — it would re-hoist V1 and break its
  `pnpm install --frozen-lockfile` Docker build.
