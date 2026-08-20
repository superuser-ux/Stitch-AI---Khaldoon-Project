# Telegram Control Integration Strategy

Date: 2026-07-02

## Purpose

This note defines the safe integration path for Telegram work while `feat/lunaris-redesign`
continues independently. Telegram is a control-channel surface, not a publish target.

## Scope Position

- `instagram` = publish target
- `telegram` = control channel / review surface / agent surface
- Telegram work should remain aligned to the same gate engine and API contracts as the dashboard

## Current Branch / Worktree Layout

- Main active implementation line:
  `feat/lunaris-redesign`
  Path: `/Users/Kay/Dev/tanaghom`

- Existing Telegram pilot line:
  `feat/telegram-pilot`
  Path: `/Users/Kay/Dev/tanaghom-telegram`

- New clean integration lane:
  `codex/telegram-control-integration`
  Path: `/Users/Kay/Dev/tanaghom-tg-integration`

## What Was Already Verified

- The raw branch divergence looked large, but the true Telegram-specific surface is narrower.
- The uniquely Telegram-focused files are concentrated in:
  - `gates/agent.py`
  - `gates/bot.py`
  - `gates/bot_selftest.py`
  - `gates/cards.py`
  - `gates/contract.py`
  - `gates/requirements.txt`
  - `i18n/ui.json`
  - `scripts/_env.sh`
  - `scripts/run-bot.sh`
  - `scripts/run-dashboard.sh`
  - `scripts/run-gateapi.sh`
  - `system_config.example.yaml`

## Integration Progress

These steps were completed on `codex/telegram-control-integration`:

1. Cherry-picked cleanly:
   - `a8adaa1` `telegram-pilot worktree: parametrized run scripts + RUN_NOTES`

2. Integrated as a manual checkpoint commit:
   - `8ca2eba` `integrate telegram parity surface + bot selftest`

That second checkpoint imported the Telegram parity surface changes while resolving only:

- `BUILD_STATE.md`
- `gates/requirements.txt`

The runtime Telegram files themselves were not the first hard blocker.

## What Is Safe To Continue

The integration branch is the correct place to continue Telegram work.

Safe next target:

- resolve the richer Telegram presentation layer from `4287419`

Expected conflict files for that step:

- `gates/agent.py`
- `gates/bot.py`
- `gates/bot_selftest.py`
- `system_config.example.yaml`

Files that came in without being the hard conflict center:

- `gates/cards.py`
- `gates/contract.py`
- `i18n/ui.json`

## Recommended Integration Order

1. Keep `feat/lunaris-redesign` moving for governance/admin/content-type work.
2. Continue Telegram integration only in `codex/telegram-control-integration`.
3. Bring over Telegram functionality in narrow slices, not as a blind full merge.
4. Resolve the `4287419` card-format layer deliberately.
5. Re-run Telegram-specific verification before taking the remaining Telegram commits.
6. Only after that consider the smaller follow-up commits:
   - `dc6ea31`
   - `b2262a7`
   - `cff2932`
   - `83276d9`
   - `1d58bfd`

## Recommended Validation After Each Slice

- `python gates/bot_selftest.py`
- targeted API self-tests if Telegram touches gate or agent contract behavior
- manual bot smoke run via the run scripts in `scripts/`

## Recommendation

Do not merge `feat/telegram-pilot` directly into `feat/lunaris-redesign`.

Use `codex/telegram-control-integration` as the controlled convergence branch, then merge that
branch back once Telegram-specific conflicts have been resolved and validated in isolation.
