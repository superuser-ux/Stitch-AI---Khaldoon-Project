# #24 Review-Surface UX Polish — Slice 1 (2026-07-05)

Author: CC (product-polish slice; branch `fix/review-surface-polish-24`)
Prompt: "Begin #24 Review-Surface UX Polish — CC only (OR)"
Base: `origin/main` @ `d3038aa` · Commit: `960e1fe`
Status: **implemented + validated locally; ready for PR on authorization.**

---

## Selected #24 slice

**Item 1 — Disposition summary completeness ("at a glance").** Chosen as the highest-value, lowest-risk slice (it is #24's top-priority item and the directive's #1 priority): pure frontend, no backend, no redesign, cleanly testable.

**Problem:** the review round-status header (`review-surface.tsx`) rendered per-state chips (Pending / Approved / Regen / Dropped) but **no denominator or progress anchor** — a reviewer had to mentally sum the chips to know "how far along am I?". The `disposition` object already computed `total`, but it was never surfaced.

**Change:** added a single **"Reviewed {resolved}/{total}"** progress anchor to the round-status header, sourced from the same `disposition` object so all summaries agree:
- `total` = stage total (`inReview + committedApproved + committedAwaiting + committedDropped`)
- `resolved` = `total − inReview` (committed approvals + regenerations + drops)
- Carries `data-resolved` / `data-total` attributes + a `disposition-progress` testid for robust assertions, and a tooltip explaining the metric.

This is **additive display only** — no state logic, no backend, no API change, all existing testids preserved. It reduces hidden state and makes progress legible without mental reconstruction (item 1's stated intent).

## Files changed (exactly 2)

| File | Change |
|------|--------|
| `dashboard/components/review/review-surface.tsx` | `ListChecks` icon import; `totalCount`/`resolvedCount` derived from `r.disposition`; new `disposition-progress` chip in the round-status header (placed as the leading state metric, before Pending). |
| `dashboard/e2e/integrity-and-dispositions.spec.ts` | In "per-item actions apply immediately", assert the progress anchor reflects committed resolutions: `data-total=3`, `data-resolved=1`, text `1/3` after approving RE2E-1. |

Diff: **+24 / −1**.

## Tests run

| Check | Result |
|-------|--------|
| `tsc --noEmit` | **exit 0 (clean)** |
| `npm run build` | **✓ Compiled successfully** |
| Targeted `integrity-and-dispositions` (chromium) | **9 / 9 passed** (incl. the new progress assertion) |
| Full Chromium pack (change touches shared header) | **36 passed / 1 failed** |
| Failing spec re-run in isolation | `production-chain-surface` **4/4 passed, twice** |

**The 1 full-pack failure is a pre-existing environmental flake, not this change.** `production-chain-surface:58` (approve `REDIT-1` → `approved==1`) timed out under full-pack concurrent load — the documented single-worker-API / route-compilation lag flagged during #1 stabilization ("production-chain:58 intermittent"). It is green 4/4 twice in isolation, and an additive display chip cannot affect REDIT approval persistence. No regression attributable to this slice.

Screenshots: not captured — the functional assertion (`data-resolved`/`data-total` + `1/3` text rendering) is direct visual-value proof; the directive treats screenshots as optional.

## Known remaining #24 items (not in this slice)

2. **Approved-item "vanish" clarity / resolved lane** — a short-lived "just approved" state or resolved lane.
3. **Dropped-lane card detail access** — lightweight expand/detail on dropped items (a `dropped-panel` exists; needs a detail affordance).
4. **Background/progress telemetry for long actions** — durable working/last-known status for generate/regenerate/rework.
5. **Auto-advance when a stage is done** (couples with #12).
- Plus two live-usage notes on the issue: inbox center-column width / space utilization; collapsibility as a broader UI principle.

Each is its own coherent slice; recommend one slice per PR to keep #24 reviewable and avoid redesign creep.

## Playwright-created clutter note

Per the cleanup post-validation finding, this pack run again created ~14 `default`-tenant test rounds. **Not cleaned in this directive** (expected behavior; demo cleanup is reserved for the final pre-demo step).

## Ready for PR?

**Yes** — `fix/review-surface-polish-24` @ `960e1fe` is validated and self-contained (2 files, additive, 1 known-flake aside). Not pushed; no GitHub mutation.

## Exact next authorization needed

- **[A] Open the PR** for slice 1 to `main` (title e.g. `feat(#24): at-a-glance review progress anchor`), keeping #24 open for the remaining items. (Recommended.)
- **[B] Continue on-branch** with slice 2 (approved-item vanish clarity / resolved lane) before opening a PR — larger, but keeps momentum.
- **[C] Hold** — leave the branch local for review.

## Attestation

- No DB cleanup (dev DB used only for normal Playwright validation; the ~14 suite-created rounds left as-is). No demo cleanup run.
- No GitHub mutation, no push, no PR yet. No closed-issue mutation. No label hygiene. No security work. No Pi.
- `git add` used with explicit paths only (never `git add .`); exactly 2 files committed.
- This handoff is uncommitted.
