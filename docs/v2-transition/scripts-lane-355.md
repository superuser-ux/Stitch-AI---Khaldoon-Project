# #355 — the candidate-only Scripts validation lane

An **isolated, deterministic, candidate-only** topology for validating the V2 Scripts read-first
lens. It exists so the slice's evidence comes from a real governed run rather than from mocks, and
so that run can be rebuilt from committed inputs alone.

**It is candidate-only.** It creates a new database and a new container; it reuses, mutates, resets
and probes nothing that already exists. No shared lane, no accepted lane, no operator-owned
configuration, and no existing test database is touched. Tear it down by dropping exactly the two
objects named at the bottom.

## Why a separate lane at all

The Scripts lens renders a stage whose input contract is `generates_from: TOPIC_APPROVED`. Proving
it truthfully needs a run that has genuinely *reached* `TOPIC_APPROVED` through the governed chain —
not a seeded row that merely says so. Seeds alone do not create a generation job, so a seeded
fixture would prove the surface renders, while proving nothing about the contract it claims to
render.

## Build it

```bash
# 1. A NEW database. Never an existing one.
docker exec tanaghom-db psql -U tanaghom -d postgres -c "CREATE DATABASE tanaghom_s355"

# 2. Committed schema, then EVERY migration in ascending order, fail-fast.
docker exec -i tanaghom-db psql -v ON_ERROR_STOP=1 -U tanaghom -d tanaghom_s355 < db/init/schema.sql
for f in $(ls db/migrations/*.sql | sort); do
  docker exec -i tanaghom-db psql -v ON_ERROR_STOP=1 -U tanaghom -d tanaghom_s355 < "$f"
done

# 3. A gate API on THIS checkout, that database, stub writer, loopback port, temporary secret.
#    The secret is generated at runtime and never committed, logged, or reused.
S355_SECRET=$(python3 -c "import secrets;print(secrets.token_hex(24))")
docker run -d --name tanaghom-gateapi-s355 --network tanaghom_default \
  -e DB_HOST=db -e DB_PORT=5432 -e DB_USER=tanaghom -e DB_PASSWORD=<dev-db-password> \
  -e DB_NAME=tanaghom_s355 \
  -e TANAGHOM_WRITER_STUB=1 -e TANAGHOM_DEV_MODE=1 \
  -e REVIEWER_PROXY_SECRET="$S355_SECRET" \
  -e TANAGHOM_CONFIG=/work/system_config.example.yaml -e PYTHONPATH=/work \
  -v "$PWD":/work -p 127.0.0.1:8355:8000 \
  --entrypoint bash python:3.12-slim \
  -lc 'cd /work && pip install -q -r gates/requirements.txt -r agents/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000'

# Verify posture by EXACT match, never `grep stub` (#179/#184):
curl -s http://127.0.0.1:8355/health   # {"writer_mode":"stub", ...}

# 4. The committed catalogue loader. Without it `/baseline-eligibility` fails closed and the
#    planner cannot run.
docker exec -e PYTHONPATH=/work -e TANAGHOM_CONFIG=/work/system_config.example.yaml \
  tanaghom-gateapi-s355 python /work/loader/load_methodology.py
```

## Drive the governed chain to `TOPIC_APPROVED`

Every step is a canonical route. Nothing is inserted directly.

```
POST /rounds                       -> plans the run (format_mix is keyed by framework NAME and must
                                      total days x posts_per_day — the 28-day template means 28)
POST /gates {stage:schedule_review}-> open the schedule gate            [signed principal]
POST /gates/{id}/decide  approve   -> record the decision               [signed principal]
POST /gates/{id}/resolve           -> commit; slots -> SCHEDULE_APPROVED
                                      *Topic generation starts AUTOMATICALLY here* (stub writer),
                                      leaving slots at TOPIC_PROPOSED
POST /gates {stage:topic_review}   -> open the topic gate               [signed principal]
POST /gates/{id}/decide  approve
POST /gates/{id}/resolve           -> slots -> TOPIC_APPROVED
```

Sign with the lane secret: `x-principal-id: khal` and
`x-principal-signature: HMAC-SHA256(secret, "khal")` hex.

**Observed result:** 28 slots at `TOPIC_APPROVED`, zero script revisions, and
`/rounds/{id}/stages/script_review/state` reporting `pending_input: 28`, `generator: "ai"` — i.e. a
run that fully satisfies the script generation input contract while no script exists yet. That is
exactly the state the read-first lens must render honestly.

A **second** run is planned and deliberately left at `RESERVED`, because a run at `TOPIC_APPROVED`
is downstream-advanced and its schedule is therefore frozen — the reorder specs need a run whose
schedule is still revisable.

## Run the evidence

```bash
# V2 must carry the SAME signing secret: its /gw write path signs server-side.
PORT=3021 TANAGHOM_DEV_MODE=1 API_BASE=http://127.0.0.1:8355 \
  REVIEWER_PROXY_SECRET="$S355_SECRET" pnpm start -p 3021

WB_URL=http://localhost:3021 API_BASE=http://127.0.0.1:8355 \
  REVIEWER_PROXY_SECRET="$S355_SECRET" \
  pnpm gate:regression -- e2e/scripts-stage.spec.ts e2e/scripts-lane-355.spec.ts
```

`scripts-stage.spec.ts` mocks the governed artifact to force divergent/ambiguous/unreadable
mappings. `scripts-lane-355.spec.ts` mocks nothing and asserts against this lane's real read model;
pointed at a lane with no `TOPIC_APPROVED` run it **fails loudly rather than skipping**.

## Known environment prerequisites

- `schedule-reorder.spec.ts`'s final test ("V1 still reads the same governed run") needs the **V1
  dashboard** running against this same lane. It is unrelated to the Scripts slice and fails on a
  V2-only topology.
- `coexistence.spec.ts` likewise requires V1 on `:3000`.

## Teardown — exactly these two objects

```bash
docker rm -f tanaghom-gateapi-s355
docker exec tanaghom-db psql -U tanaghom -d postgres -c "DROP DATABASE tanaghom_s355"
```

Nothing else is removed. The shared `tanaghom-db` server, every other database on it, and every
other container remain untouched.
