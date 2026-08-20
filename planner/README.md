# Planner (M2)

`plan_round.py` is the deterministic round generator (Phase1_Build_Spec §3 / CANON-015).
All behavior is driven by `system_config.yaml` — the pillar mix, weekly format mix,
cursor carry, and lens-rotation rule are config, not code.

## What `plan` does

1. Reads the calendar template from `system_config.yaml` (`calendar.templates.<name>`).
2. Builds the period's slots (`period_len_days × posts_per_day`).
3. Spreads **pillars** to the per-round distribution (e.g. 22/17/9/4/4) and
   **formats** to the per-week distribution (e.g. 4/1/2/2/3/1/1, each week).
4. Assigns each slot an **HCS** by walking `hcs.seq_in_pillar` from the per-pillar
   `hcs_cursor`; when a pillar's list is exhausted the cursor wraps and `cycle_no`
   increments. The cursor is **carried across rounds**.
5. Picks each slot's **lens** from the HCS's `recommended_lenses`, excluding the lens
   used in the previous cycle, and records it in `lens_history`. The **hook type**
   defaults from `lens.default_hook_type`.
6. Inserts the `round` + 56 `slot` rows at status **RESERVED**, advances the cursor,
   and writes an `audit_log` entry per transition — all in one transaction.
7. Prints the generated calendar and verifies the pillar/format mix.

`verify` prints the per-pillar cursor state and the lens-per-cycle history, and proves
that repeated HCS rotated their lens across rounds (acceptance #5).

## Run it

Stack must be up (`docker compose up -d db`) and M1 loaded.

```bash
# plan the next round (auto-numbered R1, R2, ...)
docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db \
  -v "$PWD":/work -w /work python:3.12-slim \
  bash -lc "pip install -q -r planner/requirements.txt && python planner/plan_round.py plan"

# prove the cursor carried + lenses rotated
docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db \
  -v "$PWD":/work -w /work python:3.12-slim \
  bash -lc "pip install -q -r planner/requirements.txt && python planner/plan_round.py verify"
```

(Run from the repo root; on Git Bash for Windows prefix with `MSYS_NO_PATHCONV=1` and
use `"$(pwd -W)"` for the mount source.)

Flags: `--template <name>` (default `calendar.default_template`), `--round-id <Rn>`,
`--label <text>`.
