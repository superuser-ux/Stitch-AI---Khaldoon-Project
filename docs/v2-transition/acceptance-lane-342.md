# V2 schedule acceptance lane (#342)

A small, explicitly synthetic, resettable lane for **human** acceptance of the V2 schedule surface.

It exists because the corrected FullCalendar preview (#340) proved rendered geometry against a
database carrying ~102 legacy synthetic runs. That is not client data — but it is not credible
acceptance evidence either. A reviewer cannot read a coherent schedule out of a hundred unrelated
leftovers, and nothing on screen said the data was synthetic, so any screenshot of it carried an
implied claim it had not earned.

**What this lane is:** four synthetic runs, one per placement state, on a dedicated throwaway
database, with the surface itself stating that the data is synthetic.
**What this lane is not:** a release gate, a full-suite run, or evidence about client data. It
proves a human can inspect the schedule surface and that placement stays governed. Nothing more.

## Topology

Every component is isolated and disposable. Nothing here touches the shared `tanaghom` database,
the shared gate API on `:8009`, V1 on `:3000`, V2 on `:3001`, the canonical checkout, the VPS, or
any client data.

| component | value | isolated from |
|---|---|---|
| database | `tanaghom_acc342` | the shared `tanaghom` database |
| gate API | `:8110` (container `tanaghom-gateapi-acc342`) | the shared API on `:8009` |
| workbench | `:3008` | V1 `:3000`, V2 `:3001` |
| tenant | `acc342` | client tenants |
| run ids | `ACC342-*` | every other round id |

Run every command from an **isolated worktree**, never the canonical checkout.

## Bring the lane up

```bash
# 0. From an isolated worktree at the exact SHA under acceptance.
WT=$(pwd)            # e.g. .../wt-342
DBN=tanaghom_acc342

# 1. Throwaway database with the REAL schema (never the `tanaghom` database).
docker exec -i tanaghom-db sh -lc "psql -U \"\$POSTGRES_USER\" -d postgres \
  -c 'DROP DATABASE IF EXISTS $DBN;' -c 'CREATE DATABASE $DBN;'"
docker exec -i tanaghom-db sh -lc "psql -q -U \"\$POSTGRES_USER\" -d $DBN" < db/init/schema.sql
for f in $(ls db/migrations/*.sql | sort); do
  docker exec -i tanaghom-db sh -lc "psql -q -U \"\$POSTGRES_USER\" -d $DBN" < "$f"; done

# 2. A REAL gate API against it, on an isolated port. Writer stub: the lane exercises PLACEMENT,
#    which is governed schedule authority — it must never call a live provider.
docker run -d --name tanaghom-gateapi-acc342 --network tanaghom_default \
  --env-file /path/to/.env -e DB_HOST=db -e DB_PORT=5432 -e DB_NAME=$DBN \
  -e TANAGHOM_DEV_MODE=1 -e TANAGHOM_WRITER_STUB=1 \
  -v "$WT":/work -w /work -p 8110:8000 python:3.12-slim \
  bash -lc "pip install -q -r gates/requirements.txt -r agents/requirements.txt && \
            uvicorn gates.api:app --host 0.0.0.0 --port 8000"

# 3. Methodology reference data. A FRESH database has empty pillar/lens/hook_type/format/hcs
#    tables, and slots carry foreign keys into them — without this the seed fails with
#    `slot_pillar_code_fkey`. Use the canonical loader (idempotent, transcribes the markdown
#    source of truth); never hand-insert reference rows, which would fork the methodology.
docker exec -w /work -e DB_NAME=$DBN tanaghom-gateapi-acc342 sh -lc \
  "pip install -q -r loader/requirements.txt && python loader/load_methodology.py"

# 4. Seed the four synthetic scenarios (idempotent — this is also the RESET).
docker exec -w /work tanaghom-gateapi-acc342 python gates/acc342_lane_seed.py

# 5. The workbench, DECLARING itself a synthetic lane so the banner can render.
cd workbench && API_BASE=http://localhost:8110 TANAGHOM_DEV_MODE=1 \
  TANAGHOM_WORKBENCH_BUILD_SHA=$(git rev-parse --short HEAD) \
  TANAGHOM_WORKBENCH_LANE_ID=acc342 TANAGHOM_WORKBENCH_DATA_CLASS=synthetic \
  npx next build && npx next start -p 3008
```

Open `http://localhost:3008`.

> `TANAGHOM_WORKBENCH_DATA_CLASS=synthetic` is what makes the banner appear. It is **opt-in on
> purpose**: an undeclared process renders no banner rather than a reassuring default, so the label
> can never appear on a surface that might be pointed at real data.

## The four scenarios

| run | window | state | what it demonstrates |
|---|---|---|---|
| `ACC342-MULTI` | 4 days | placed | a multi-day window on the grid |
| `ACC342-ONEDAY` | 1 day | placed | the degenerate window where off-by-one errors surface |
| `ACC342-PLAN` | 3 days | **unplaced** | stated as unplaced, never drawn at a guessed date |
| `ACC342-FROZEN` | 2 days | placed, downstream-advanced | the server refuses placement |

Dates are anchored to a fixed Monday (`2026-07-13`), never "today", so the lane is re-inspectable
next week and comparable against an earlier screenshot. Override with `ACC342_ANCHOR=YYYY-MM-DD`.

`ACC342-FROZEN` is frozen by advancing exactly one slot to `TOPIC_PROPOSED`, which satisfies the
first disjunct of the server's own `_downstream_advanced` predicate. The refusal therefore comes
from the real governed rule, not from a flag the fixture invented.

## Reset

Re-run the seed. It is idempotent: `teardown()` deletes every row it can create, scoped to the
`ACC342-` prefix, child rows first.

```bash
docker exec -w /work tanaghom-gateapi-acc342 python gates/acc342_lane_seed.py
```

The script **refuses to run** against `tanaghom` or `postgres`, so a forgotten `DB_NAME` cannot
seed fixtures into the shared database.

**Determinism check.** A reset restores the exact seeded shape regardless of what a session did to
the lane — including placements a browser test committed. After re-running the seed, this must
print exactly `4|10` (four rounds, ten slots):

```bash
docker exec -i tanaghom-db sh -lc "psql -U \"\$POSTGRES_USER\" -d tanaghom_acc342 -At -c \
  \"SELECT (SELECT count(*) FROM round WHERE round_id LIKE 'ACC342-%'), \
           (SELECT count(*) FROM slot  WHERE round_id LIKE 'ACC342-%')\""
```

Note this is the shape after `teardown()` **and** `seed()`, which is what the script does — it is not
a zero-residue assertion. To check residue alone, run only the teardown and expect `0|0`:

```bash
docker exec -w /work tanaghom-gateapi-acc342 python -c \
  "import sys; sys.path.insert(0,'gates'); import engine, acc342_lane_seed as s; s.teardown(engine.db_connect())"
```

Verified in practice: after browser tests moved `ACC342-MULTI` to a different date, a reset returned
it to its seeded `2026-07-14` window with no leftover rows.

## Teardown and retention

The lane is **ephemeral by default**. Nothing in it is evidence once the PR is reviewed; retain it
only while a human review is actually open, and say so explicitly if you do.

```bash
docker rm -f tanaghom-gateapi-acc342
kill $(lsof -tnP -iTCP:3008 -sTCP:LISTEN)          # never pkill: `next start` re-execs as next-server
docker exec -i tanaghom-db sh -lc "psql -U \"\$POSTGRES_USER\" -d postgres \
  -c 'DROP DATABASE IF EXISTS tanaghom_acc342;'"
```

Dropping the database is the real teardown: it removes the fixtures, the audit rows, and any state
a session left behind, with no cleanup discipline to get wrong.

## What this lane does not prove

- **Not** repository-wide validation. The full Playwright topology is separately blocked (V1 is not
  on `:3000`; fixture coverage is incomplete) and is owned by **#285**, not here.
- **Not** release or production readiness, and not client acceptance.
- **Not** a claim about the placeability *indication* in the UI. That flag is derived client-side
  and is not the server's freeze predicate; the server decides on submit and its typed refusal is
  surfaced verbatim. Correcting that divergence is out of scope here — see the PR for #342.
