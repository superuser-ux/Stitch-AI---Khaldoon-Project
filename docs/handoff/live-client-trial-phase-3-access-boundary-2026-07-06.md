# Live Client Trial — Phase 3: Locked-Down Access Boundary

Author: CC · Date: 2026-07-06
Prompt: "Phase 3 — Locked-Down Client Trial Access Boundary — CC only (OR)"
Result: **SUCCESS — a locked-down client-trial dashboard exists and is validated. Admin/dev routes are server-blocked, operator controls hidden/removed. Client access is NOT sent — it is localhost-only and awaits an owner-approved outer gate.**

---

## 1. Implementation summary

A minimal, **runtime-gated** client-trial mode (Refs #13 — **not** the full #13 role system). `CLIENT_TRIAL_MODE=true` turns the same build into a locked-down client dashboard; unset, it is the normal operator dashboard.

| File | Role |
|------|------|
| `dashboard/middleware.ts` (new) | **server-enforced gate**: blocks `/admin/*` (redirect → `/`) + sets a readable `client_trial` cookie |
| `dashboard/lib/client-trial.ts` (new) | `useClientTrialMode()` reads the cookie (UI cosmetics only) |
| `dashboard/components/review/app-shell.tsx` | hides New-run planner; **removes persona switcher from the DOM**; persistent trial banner + "Generation: Live" |
| `dashboard/components/review/workflow-lens.tsx` | hides the "Open admin" link in client mode |
| `dashboard/next.config.mjs` + `.gitignore` | `NEXT_DIST_DIR` → isolated `.next-client` build (dev `.next` untouched) |

**Security model:** the route block lives server-side in middleware, so a client tampering with the cookie to un-hide controls still cannot reach a blocked route.

## 2. PR / merge

- Branch `feat/client-trial-mode` · **PR #42** (`Refs #13`, not `Closes`) · squash-merge **`73b5bab`** → `main`. `#13` remains **OPEN**.

## 3. Runtime map (current)

```
DEV     (untouched):     tanaghom `tanaghom`       <- :8009 <- dashboard :3000
TRIAL   operator view:   tanaghom `tanaghom_trial` <- :8012 (LIVE) <- dashboard :3001  [operator-only, NOT locked]
TRIAL   CLIENT surface:  tanaghom `tanaghom_trial` <- :8012 (LIVE) <- dashboard :3002  [LOCKED, CLIENT_TRIAL_MODE=true]  <-- the client surface
```

Client-trial mode flag: **`CLIENT_TRIAL_MODE=true`** (runtime env on the `:3002` process). Trial dashboard URL/port: **`http://localhost:3002`** (localhost only — not exposed).

## 4. Validation (simulated client on :3002 → live trial API :8012)

| Check | Result |
|-------|--------|
| Loads | 200 |
| Points to trial API only | `/gw/health` = `writer_mode:live`; `/gw/rounds` = **2 (only trial rounds)** — no dev/e2e clutter |
| **`/admin/workflows`** | **307 → `/` (blocked)** |
| **`/admin/methodology`** | **307 → `/` (blocked)** |
| Trial banner | visible: "Live client trial · Data is temporary and may be purged" |
| Generation indicator | "Generation: Live" shown |
| New-run planner | hidden (0) |
| Persona switcher | **removed from DOM (0)** — not merely CSS-hidden |
| "Open admin" link | hidden |
| Trial round openable | `round-opt-R2` selectable → client can review |

**Live review path** (validated in Phase 2 on the same live stack): request-change → regenerate (live) → approve all work.

**Regression (no normal-mode breakage):** the identical build run in normal mode (flag off, `:3003`) → `/admin` **200 (not blocked)**, no banner, planner present, no cookie. So flag-off = unchanged operator dashboard.

> Note: the full Playwright pack was deliberately **not** run — it reseeds the e2e fixtures in the dev DB, which the trial constraints forbid touching. Normal-mode behavior was instead proven from the identical build via the `:3003` check; the changes are additive, flag-gated conditionals; `tsc`+build pass; gitleaks clean on the diff.

## 5. Dev untouched proof

Dev `:3000` → 200; dev `:8009` → 209 rounds; dev DB `tanaghom` → 209 rounds, **6 e2e fixtures** (unchanged); dev writer still stub; dev build `.next` never rebuilt (client built to `.next-client`).

## 6. Credentials / access status

- **No client credentials created.** Client-trial mode locks the *surface*; it does not add a login. Who may connect is controlled by the **outer gate** (below), which is **not yet configured**.
- **Access NOT sent.** The client dashboard is **localhost-only**; nothing is publicly reachable.

## 7. Outer access layer — options (prepared, NOT activated; needs owner approval)

The inner gate (route/control lockdown) is done. An **outer network gate** is still required before the client can connect, and must **not** be activated without owner approval:

1. **Tailscale funnel/serve → `:3002`** (recommended) — expose only `:3002` over the existing Tailscale funnel (`…taile18f28.ts.net`), optionally with a Tailscale ACL limiting the client's node. No passwords to manage; encrypted; revocable by turning the funnel off. *(The dev funnel currently points at `:3000` — a client funnel must target `:3002`, and the two must not be confused.)*
2. **Reverse proxy + basic auth in front of `:3002`** — limits *who* connects; credentials handled in the operator's password manager, never in the app or repo.
3. **IP allowlist / VPN** — if the client is on a known network.

Recommendation: **Option 1** (Tailscale to `:3002`), as it adds a network identity gate on top of the app-side lockdown without credential management. **Do not** point a public funnel at `:3002` until you approve.

## 8. Client access pack (draft — do not send until §7 gate + approval)

- **URL:** (the funnel/proxy URL for `:3002`, once the outer gate is approved and configured)
- **Allowed:** view trial rounds · open review surfaces · inspect generated topics/scripts · request changes · regenerate items · approve items · progress the review flow · submit feedback via the agreed path.
- **Forbidden (enforced):** methodology/workflow admin, workflow/stage/gate config, persona/admin switching, dev/debug/admin routes, dev DB/API, environment/writer settings, config/secrets, destructive cleanup, and seeing e2e/dev clutter.
- **Temporary-data warning:** all trial data is disposable and may be reset/purged after evaluation.
- **Known limitations:** single fixed reviewer identity; scripts are generated on demand (approve a topic to generate its script); this is a trial, not production; no persistence guarantee.
- **Support/contact:** (operator contact / feedback channel — owner to set).

### Client access note (ready to send, once access is approved)

> This is a live client trial environment. Generated outputs are real trial outputs, but all trial data is temporary and may be reset or purged after evaluation.
>
> Please test:
> 1. usability and clarity of the review flow
> 2. quality of generated topics and scripts
> 3. request-change / regenerate behavior
> 4. approval flow
> 5. confusing labels or missing controls
> 6. bugs, slow screens, broken states, or unexpected output
> 7. anything that would block real operational use
>
> Please do not enter confidential production data unless explicitly approved.

**Feedback path:** no external tool created. Recommend a shared doc / form / email thread with the 7 categories above (GitHub is operator-internal and should not be client-facing). Owner to choose; I did not create external accounts or send anything.

## 9. Remaining limitations / notes

- **No login** — the surface is locked but does not authenticate individuals; the outer gate (§7) is the access control. A per-client login is the full **#13** (still open).
- The **`:3001`** operator trial dashboard is the *unlocked* trial view — **operator-only; must not be given to the client** (it exposes admin). Only `:3002` is the client surface.
- Trial data remains purgeable (Phase-1 selective purge, trial DB only).

## 10. Exact owner approval needed before sending access

1. **Approve an outer gate** (§7 — recommend Tailscale funnel → `:3002`) and confirm the method.
2. Confirm the **feedback path** (shared doc/form/email).
3. Then I (or you) activate the gate, fill the URL into the access pack, and send the §8 note. **Until then, no access is granted.**

## 11. Attestation

- Locked-down client mode implemented, merged (PR #42), and validated; **client access NOT sent** (localhost-only, no outer gate activated).
- Route block server-enforced; admin controls hidden **and** the persona switcher removed from the DOM.
- **No secret printed or committed** — no `.env*`, no credentials created; the isolated `.next-client` build artifact is gitignored, not committed; the Next-build tsconfig auto-edit was reverted.
- Dev stack (`:3000`/`:8009`/`tanaghom`/e2e fixtures) untouched; trial stack still `writer_mode:live`.
- Not the full #13; `#13` left open. This report is **uncommitted**.
