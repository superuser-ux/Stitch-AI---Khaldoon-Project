# AGENTS.md — Tanaghom (Codex lane)

- **Sync first:** read `docs/directive-bus/executor-log.md` (top entries) — the Claude Code executor
  lane appends a briefing there after every completed directive execution/closeout. Entries are
  informational; they never request action.
- Operating brief: `HANDOFF.md`, then `BUILD_STATE.md`. Directive-bus protocol:
  `docs/directive-bus/README.md`.
- **ETA-based monitoring:** every dispatched or long-running directive task receives an ETA plus
  scheduled live-evidence checks. For an 11-15 minute ETA, inspect at 5, 10, and 15 minutes; use the
  cadence table in `docs/directive-bus/README.md` for other durations. At each check, report
  `state / evidence / revised ETA / next check / risk`, revise the ETA, and intervene immediately on
  stalls, repeated work, scope drift, or blockers instead of waiting for the original ETA.
- Repo rule (from #152): use `React.lazy` + `Suspense` for lazy client chunks in the dashboard —
  `next/dynamic` broke the RSC client-reference manifest on fresh builds on **Next 15.1.4**, where
  #152 was discovered and proved. Both roots now pin exact **Next 15.4.11 / React 19.0.0** (#297);
  `React.lazy` + `Suspense` remains the retained convention and was re-proved there. Whether the trap
  still reproduces on 15.4.11 is deliberately untested — do not switch back without an evidenced
  directive.
- Validation baseline and environment traps (stale servers, stub mode, dev-mode env): see
  `CLAUDE.md` — the same rules apply to any agent lane.
- **Configuration-generation guardrail:** product policy is dynamic only across governed
  configuration generations. Methodology, framework/catalogue, model-route preference, role,
  workflow, and integration policy use a baseline default that may later be overridden by an
  authorized user/organization or proposed by AI; an active run/action snapshots the resolved
  policy and historical records are never silently reinterpreted. Trial applies only to generated
  data retention and environment operation, never to a separate product policy. Keep runtime
  topology/secrets in file/env; do not use bootstrap seeds or hard-coded values to overwrite
  operator-owned policy. **Initialization rule (every governed policy/configuration generation, not
  only trial):** Bootstrap, seed, reset, and migration initialization operations must never overwrite
  existing operator-owned configuration. They may create missing baseline records only; reruns must
  be idempotent and non-destructive. See `docs/directive-bus/README.md` for the mandatory directive
  checklist.
