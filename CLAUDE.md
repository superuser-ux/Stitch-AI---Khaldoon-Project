# CLAUDE.md — Tanaghom executor instructions

Read `HANDOFF.md` (operating brief), then `BUILD_STATE.md`. Work arrives via the **directive bus**
(`docs/directive-bus/README.md`): GitHub issues labeled `directive:approved`. One issue at a time; no
broad unsliced improvement passes.

## Directive-bus executor protocol (mandatory)

1. Run **only** issues labeled `directive:approved` (the human gate). Never a `pending` one.
2. On start: post an ACK/plan comment, relabel to `directive:running` (strip `pending` + `approved`),
   branch `feat/issue-<n>-<slug>`.
3. Implement + tests → validate → **one bounded PR** labeled `agent:cc` → post the completion report
   under the issue → **hold at the human merge gate. Never self-merge.**
4. **Post-merge executor closeout (default, not optional):** after the operator merges —
   1. verify the PR is actually merged;
   2. sync local `main` to the merge commit;
   3. delete the local working branch;
   4. relabel `directive:running` → `directive:done`;
   5. **close the directive issue** (unless explicitly told to leave it open);
   6. post the final `## ✅ Done` comment with merge SHA, merge time, and residual follow-ups;
   7. only then report completion to the operator.
   Never leave a directive at `running` waiting for operator/Codex cleanup. If a step is blocked
   (e.g. remote-branch deletion is permission-gated), name the exact step and why, and finish the rest.
5. **Merge-gate + queue discipline (#188):** GPT review, when applicable, happens **before** merge —
   a patch/re-review cycle resets that gate (an earlier review does not carry over a patch). Before
   picking up any `directive:approved` issue, read its LATEST comments for a pause/supersession note
   and treat a conflict as a hold. After merge/closeout, consumed or superseded approved directives
   must be normalized (traceable note → relabel → close when satisfied) so the queue stays
   verifiable at a glance.
6. **Codex briefing (operator directive 2026-07-09):** after completing a directive execution (report
   posted / closeout done), brief the Codex lane: PRIMARY — prepend an entry to
   `docs/directive-bus/executor-log.md` (repo `AGENTS.md` points Codex sessions at it); secondary —
   `codex exec --skip-git-repo-check -s read-only "EXECUTOR UPDATE — …"` for the session-history
   record. Note: `codex exec` starts a NEW headless session and cannot reach an already-open
   interactive Codex session — live sessions must be told to read the executor log.
7. **Configuration-generation guardrail (mandatory):** before changing methodology, frameworks,
   model routing, roles/capabilities, workflow/approval policy, or an integration selection, identify
   the baseline default, authorized override, AI recommendation boundary, and the policy/version
   snapshot for active runs/actions. Product policy evolves prospectively through governed
   generations; it must not be silently changed by a bootstrap seed, static code allowlist, or
   trial-only lifecycle mutation. Trial means ephemeral generated data and non-production topology,
   not a separate product model. Preserve runtime/secrets/topology in file/env and stop if truthful
   snapshotting requires an unauthorized schema or authority change. **Initialization rule (applies
   to every governed policy/configuration generation, not only trial):** Bootstrap, seed, reset, and
   migration initialization operations must never overwrite existing operator-owned configuration.
   They may create missing baseline records only; reruns must be idempotent and non-destructive.
   Read the full rule in `docs/directive-bus/README.md` before implementation.

## Validation baseline (all must pass before claiming green)

```bash
docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest
docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest
cd dashboard && npx tsc --noEmit
cd dashboard && DASH_URL=http://localhost:3000 API_BASE=http://localhost:8009 npx playwright test --project=chromium
```

## Validation tiers (#263 — Playwright cadence, one contract)

Every tier is **serial, single-worker, ZERO retries** (config-enforced: `fullyParallel:false`,
`workers:1`, `retries:0`). A failure is reported truthfully — never retried until it passes. Never
run `gates.api_selftest` concurrently with any Playwright tier on the shared dev DB (#179). All
commands run from `dashboard/` with `DASH_URL`/`API_BASE` set.

- **Inner loop (affected):** the changed spec(s) only —
  `npm run test:spec -- e2e/<file>.spec.ts [more specs]`. A changed spec runs alone; it does not
  invoke unrelated specs. Use freely while iterating.
- **PR checkpoint:** explicit relevant spec pack **+ typecheck + production build**, one command —
  `npm run test:pr -- e2e/<relevant>.spec.ts [more]` (runs `tsc --noEmit && next build && playwright
  test` over exactly the specs you name). The production build is mandatory here; never omit it.
  Never claim a targeted run covers unrelated surfaces.
- **Immutable merge head:** exactly **one** full Chromium suite in **stub writer mode** against the
  **exact commit SHA approved for merge**, after all patches and reviews —
  `npm run test:full` (health-verify `"writer_mode":"stub"` first, per the exact-match trap below).
  Any code change, rebase, base merge, or other SHA change **invalidates that result** and requires
  a fresh full-suite gate at the new SHA.

The completion report binds evidence to the exact tested SHA: tier + command, exact included specs,
writer mode, worker/retry config, retry count (0), result, and confirmation that `gates.api_selftest`
did not overlap Playwright on the shared DB.

## Environment traps (learned the hard way)

- The gate API container mounts the live tree but **uvicorn must be restarted** (`docker restart
  tanaghom-gateapi`) to pick up Python changes; `gates.selftest` runs fresh and can pass while the API
  serves stale code.
- The dashboard on :3000 serves a **built** `.next` — rebuild (`./node_modules/.bin/next build`) and
  restart after changes. `next start` needs `TANAGHOM_DEV_MODE=1` or the fail-closed `/gw` reviewer
  proxy 500s everything.
- `pkill -f "next start"` does NOT kill the server (it renames to `next-server`); kill by port:
  `kill $(lsof -tnP -iTCP:3000 -sTCP:LISTEN)`.
- Test suites need the gate API in **stub writer mode** (`-e TANAGHOM_WRITER_STUB=1`); real runs must
  not use it. Restore the prior mode after test runs. Verify the mode with an **exact**
  `"writer_mode":"stub"` match — `grep stub` also matches `"writer_stub":false` (this once ran a
  whole suite against live Groq and burned the daily token quota, #179/#184).
- **Never run `gates.api_selftest` concurrently with the Playwright suite** on the shared dev DB —
  both mutate rounds/gates and the interference produces phantom failures (#179).
- Use `React.lazy` (never `next/dynamic`) for lazy client chunks — `next/dynamic` broke the RSC
  client-reference manifest on **Next 15.1.4**, where #152 was discovered and proved (#152). Both
  frontend roots now pin exact **Next 15.4.11 / React 19.0.0** with `pnpm@10.15.1` (#297);
  `React.lazy` + `Suspense` stays the retained convention and was re-proved at 15.4.11. Whether the
  trap still reproduces there is deliberately untested — reverting needs an evidenced directive.

## Hard rules

- Do not hardcode mutable product policy. Classify values correctly: governed domain policy/defaults
  and versions belong in the domain model; secrets, endpoint/topology wiring, build identity, and
  runtime safety limits stay in config/env; immutable protocol/validation constants stay in code.
  Never move every YAML value to the DB by default and never allow bootstrap seeds to overwrite
  operator-owned configuration.
- No secrets, `.env*`, client-trial data, or production runtime in commits.
- No schema changes unless a directive explicitly allows them — stop and report instead.
