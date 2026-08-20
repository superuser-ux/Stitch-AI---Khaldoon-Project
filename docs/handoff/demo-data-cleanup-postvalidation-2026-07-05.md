# Demo-Data Cleanup — Post-Validation Report (2026-07-05)

Author: CC (post-cleanup e2e fixture validation)
Prompt: "Post-Cleanup E2E Fixture Validation — CC only (OR)"
Inputs: `docs/handoff/demo-data-cleanup-execution-2026-07-05.md`, snapshot `2026-07-05_precleanup.dump`
Result: **CLEANUP CONFIRMED SAFE — e2e fixtures healthy, full Chromium pack 37/37. No restore needed.**

---

## 1. Pre-validation DB state (cleaned)

| Metric | Value |
|--------|-------|
| Rounds | 6 |
| Slots | 13 |
| e2e fixtures | 6 |
| Protected IDs present (RDIST/RE2E/REDIT/RFIN/RPROD/RSCR) | 6 / 6 |
| Stack | dashboard `:3000` → 200, gate API `:8009` → 200 (sees 6 rounds), API `DB_HOST=db DB_NAME=tanaghom` (cleaned shared dev DB) |

## 2. Command run

```bash
cd dashboard && DASH_URL=http://localhost:3000 API_BASE=http://localhost:8009 npx playwright test --project=chromium
```

## 3. Playwright result

- **37 passed / 0 failed (2.5m)** — exit 0. No flaky, no retries.
- **Failed specs:** none.
- **Fixture-seeding outcome:** healthy. `[e2e] seeding RE2E…` (globalSetup) ran normally; the six `tenant=e2e` fixtures seeded and were exercised by their specs (`approval-visibility`, `production-chain-surface`, `final-stage-surface`, `script-stage-surface`, `schedule-and-topic-surface`, `content-handoff-flow`, `co-creation`, etc.). No missing/corrupt-fixture errors.

## 4. Post-validation DB state

| Metric | Pre-run | Post-run |
|--------|--------:|---------:|
| Rounds | 6 | **20** |
| Slots | 13 | 44 |
| e2e fixtures | 6 | **6** ✓ |
| Protected IDs present | 6 | **6** ✓ |
| `default`-tenant rounds | 0 | **14** |

**What Playwright added:** the suite created **14 fresh `default`-tenant test rounds during the run** — `R1–R14` with labels `1-day run RN (N/day)`, `refresh-stickiness`, `schedule-framework-chain`, `content-handoff-e2e`. These are the suite's own scenario artifacts (`runs-and-generation` and related specs create rounds via the new-run flow), not pre-cleanup leftovers. `RE2E` was reseeded per test as designed. **All 6 protected fixtures preserved and functioning.**

## 5. Cleanup safety verdict

**CONFIRMED SAFE. No restore required.**
- The cleanup removed only sacrificial `default`-tenant clutter; every `tenant=e2e` fixture survived and passed its spec.
- 37/37 green proves the fixtures seed and drive the full review/approval/generation/production flows correctly on the cleaned DB.
- The snapshot `2026-07-05_precleanup.dump` remains available but is **not needed**.

## 6. Key finding — cleanliness is transient on the shared dev DB

The e2e suite is the **source** of the round clutter, not merely a consumer of fixtures: one pack run regenerated 14 `default`-tenant rounds. The original 89-round pile was this same output accumulated across many runs. Implications:
- **Demo-cleanliness is a "last step before the demo" operation**, not a one-time fix. If the e2e pack runs after a cleanup, ~14 test rounds reappear.
- Options (all out of scope here, for the owner to weigh): (a) run cleanup as the final pre-demo step and don't run the pack afterward; (b) point the e2e suite at an isolated/ephemeral DB so it never pollutes the demo DB; (c) have the suite scope + tear down the rounds it creates (like it already does for `RE2E`). Option (b) or (c) is the durable fix; (a) is the immediate operational workaround.

## 7. Recommended next action

- **For an imminent demo:** re-run Stage 2/3-style cleanup of the `default`-tenant rounds as the final step *after* the last e2e run (the same guarded, snapshot-first procedure). The 14 current rounds (R1–R14, all `default`, test-pattern labels, no human reviews) match the proven-sacrificial profile.
- **For a durable fix:** open a follow-up to isolate the e2e suite's DB or make it clean up its created rounds (option b/c above) — this stops the clutter regenerating. Product/infra work, appropriately its own issue.
- No action needed on the fixtures themselves — they are healthy.

## 8. Attestation

- Read + validate only on the DB (counts before/after; `SELECT` only). **No DB restore, no DB cleanup, no `DROP`/`TRUNCATE`/migration.**
- No code edits, no commits, no push, no PR, no GitHub issue mutation, no label hygiene, no Pi, no security/key work.
- `#24` untouched. Groq audit report not committed; `dashboard/.env.local` untouched.
- This report is **uncommitted** (no commit without separate authorization).
