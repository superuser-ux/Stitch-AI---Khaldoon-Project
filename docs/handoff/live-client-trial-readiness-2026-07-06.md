# Live Client Trial — Readiness Report

Author: CC (read-only preflight; **no mutation, no snapshot, no seed, no writer-mode change**)
Prompt: "Prepare Live Client Trial Environment — CC only (OR)"
Date: 2026-07-06
Result: **STOPPED at hard-stop conditions — the environment is NOT ready for a live client trial. Three blockers require owner decisions before any trial setup can proceed.**

---

## Verdict (read first)

A live client trial cannot be safely prepared on the current stack. Three of the directive's own hard-stop conditions are met simultaneously:

1. **`/health` reports stub mode** — no live generation today.
2. **No data isolation** — the round selector is not tenant-scoped, so a client would see all 209 rounds (203 dev/test + 6 e2e fixtures). A "trial tenant" would not be hidden. No dedicated trial DB/container exists.
3. **No client access model** — the dashboard is an open internal operator surface (admin routes ungated, no login/role scoping); giving a client access exposes admin/dev controls and every tenant's data.

Per the directive I stopped **before** any mutation (no snapshot taken because nothing was mutated). Below are the exact facts and the owner decisions needed.

## 1. Repo / environment identity

| Item | Value |
|------|-------|
| `origin/main` HEAD | `30ccdc4` (`feat(#22)…`) — clean, up to date |
| Dashboard | `http://localhost:3000` (Next.js) |
| API | `http://localhost:8009` (gate API) + `/gw` same-origin proxy |
| DB | `tanaghom` @ container **`tanaghom-db`** (pgvector pg16, `:5433`) — **shared dev DB** |
| Dedicated trial DB/container | **none** (`docker ps` shows only the shared dev stack) |
| Tenant model | `round.tenant_id` exists (`default`, `e2e`) — **but not enforced in the round read model** (see blocker 2) |

## 2. Writer-mode proof (blocker 1)

`GET /health` (both `:8009` and `/gw`): `{"ok":true,"writer_stub":true,"writer_mode":"stub"}`

- The gate API container runs `TANAGHOM_WRITER_STUB=1` → the deterministic `_StubLLM` (fixed hooks, placeholder scripts). **This is exactly what a client trial must NOT use.**
- A `GROQ_API_KEY` **is present** in the container env (value not printed), and the live writer resolves providers from `system_config.yaml` (`cfg["providers"]`). So live mode is *technically* reachable by removing the stub flag + restarting — **but**:
  - The key's validity/quota cannot be proven without a live generation call (would consume real quota; the writer's own fallback treats HTTP 402 / missing key as a `ProviderError`). → hard-stop "live writer credentials … invalid" is unverifiable here.
  - Flipping the **shared dev** container to live changes the whole dev environment and would run real, costed generation against a non-isolated, non-authenticated surface. Not safe to do unilaterally.

## 3. Data isolation (blocker 2)

- `GET /rounds` → `engine.list_rounds(conn)` selects **all** rounds grouped by slot — **no `WHERE tenant_id`** filter. The dashboard round selector therefore shows every round regardless of tenant.
- Current DB: **209 rounds** — `default` **203** (dev/test/Playwright clutter, accumulated further by this session's validation runs) + `e2e` **6** fixtures.
- Consequence: a client opening the dashboard today sees a 209-item round list full of `1-day run R…`, `refresh-stickiness`, `RE2E`/`RSCR`/etc. A `tenant=client_trial_*` namespace would **not** be isolated in that view. True isolation requires **either** a dedicated trial DB **or** adding tenant-scoping to the API read models (backend work — out of this directive's scope).

## 4. Access / auth model (blocker 3)

- `dashboard/lib/reviewer-session.ts` signs a `principalId` with an **internal** HMAC proxy secret (`REVIEWER_PROXY_SECRET`, default `"dev-internal-reviewer-proxy-secret"`). This is dashboard→API trust, **not** a client login.
- There is **no authentication / role-scoped client access**: the dashboard defaults an operator principal and exposes admin surfaces (`/admin/methodology`, `/admin/workflows`), the new-run planner, persona switching, and workflow/methodology editors — all ungated. (A demo-persona login surface is tracked but **unimplemented**: issue #13.)
- Consequence: handing a client this URL grants full operator/admin power over all data. Hard-stop "authentication/access model is unclear" + "client access would expose admin-only controls."

## 5. Snapshot / rollback

**Not created** — no mutation was performed (stopped before the mutation steps, as the directive requires when hard-stops are present). A `pg_dump -Fc` snapshot will be the first step **once** the blockers are resolved and a mutation plan is authorized.

## 6. What a real live client trial needs (owner decisions)

**Isolation — choose one:**
- **A (recommended): dedicated trial DB** — a separate Postgres DB/container (`tanaghom_trial`), schema-initialized, seeded fresh. Cleanest isolation; no risk to dev/e2e data; trivially purgeable (drop/reset the DB). Needs a compose/service addition.
- **B: tenant-scoping the read models** — add `tenant_id` filtering to `/rounds` (+ related reads) so a `client_trial` tenant is isolated on the shared DB. This is **backend work** (API change) and must be verified everywhere the UI lists rounds/slots — larger, and still shares the DB.
- **C (last resort): shared DB + selective purge** — only if you accept the client seeing/needing a filtered view; requires the tenant-scoping of B anyway to hide clutter. Not recommended.

**Live writer:**
- Confirm the `GROQ_API_KEY` (or chosen provider) is a valid, quota'd **live** credential, and that `system_config.yaml` `providers` is set for live. Then run the trial stack with `TANAGHOM_WRITER_STUB` **unset** — ideally the *dedicated* trial stack (option A), not the shared dev container.
- I will not print or commit any key; provide/confirm the credential out-of-band.

**Access/auth:**
- Decide the client access path. Options: implement the minimal **#13 persona/login** surface with a restricted client role (hides admin routes), **or** stand up a locked-down read+review-only principal behind the funnel with admin routes removed from the client build. Today there is no safe way to scope a client to review-only.

**Then (once the above are decided):** snapshot → seed 1–2 realistic live rounds in the trial namespace → validate live generation/review/regenerate/approve → selective purge script (dry-run first) → client access note.

## 7. Client access note + feedback categories (prepared, not deliverable yet)

> **This is a live trial environment.** Generated outputs are real trial outputs but may be reset or purged after evaluation. Please test usability, content quality, clarity of the review flow, bugs, confusing labels, and missing controls. **Do not enter confidential production data unless explicitly approved.**

Suggested feedback categories: usability · quality of generated topics/scripts · confusing UI · missing actions · slow/broken flows · unexpected output · bugs/screenshots · overall readiness.

*(Deliver this only once access is actually possible — see blocker 3.)*

## 8. Exact owner actions needed before a live trial

1. **Isolation decision** — approve a dedicated trial DB (option A, recommended) or authorize the tenant-scoping backend change (B).
2. **Live credential** — confirm a valid live provider key + `system_config.yaml` providers; authorize running a (trial) stack in live mode.
3. **Access model** — decide how the client is scoped (implement minimal #13 client role, or a locked-down review-only build with admin routes removed).
4. Then authorize the mutation sequence (snapshot → seed → validate → purge-plan → access).

Each is a distinct decision; I can execute any of them as a separately-scoped directive.

## 9. Attestation

- Read-only preflight only: `git`, `curl /health`, read-only `SELECT count/group`, code/schema greps. **No DB mutation, no snapshot, no seed, no writer-mode change, no restart.**
- **No secret printed or committed** — the `GROQ_API_KEY` value was never displayed (env greps masked to `gsk<redacted>`); `.env*` untouched.
- No e2e fixtures touched; no rounds deleted; no admin routes exposed; no client credentials created/sent.
- This report is **uncommitted**. No unrelated backlog work performed.
