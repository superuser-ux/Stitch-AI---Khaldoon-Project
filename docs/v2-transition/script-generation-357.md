# #357 — governed Script generation: lane, proof, and teardown

Everything needed to reproduce #357's evidence from committed inputs. Written because the backend
claims in that PR are only worth as much as a reviewer's ability to re-run them.

The lane is **candidate-only**: it is built fresh, it never touches the shared dev database, and its
teardown names exactly the objects it created.

---

## What #357 changed, in one paragraph

Script generation had **no authorization** — the trusted-principal block in
`POST /rounds/{id}/stages/{stage}/generate` sits entirely inside `if mode == "topics"`, so V1's
existing Generate Scripts control, V2, and any agent could start a writer run unauthenticated. It
also had **no durable job**: it used `gates/jobs.py`, an in-process dict capped at 50 with eviction,
so a restart lost the record and `stage_state` would re-offer Generate while work was in flight.
#357 authorizes the *shared* command against the frozen affirmative authority of the accepted
`topic_review` decision, and moves Scripts onto the existing `generation_job` — **removing** the
second mechanism rather than adding one.

---

## 1. Build the lane

Requires the local `tanaghom-db` container running (it hosts the isolated database; nothing else in
it is touched).

```bash
# a fresh, isolated database
docker exec tanaghom-db psql -U tanaghom -d postgres -c "CREATE DATABASE tanaghom_s357"

# committed schema, then EVERY migration in ascending order, fail-fast
docker exec -i tanaghom-db psql -U tanaghom -d tanaghom_s357 -v ON_ERROR_STOP=1 -q < db/init/schema.sql
for m in db/migrations/*.sql; do
  docker exec -i tanaghom-db psql -U tanaghom -d tanaghom_s357 -v ON_ERROR_STOP=1 -q < "$m" || { echo "FAILED $m"; break; }
done
```

Migration `033_script_generation_attempt.sql` is idempotent — rerunning it is a non-destructive
no-op, which is worth confirming once because that property is what makes the lane rebuildable.

## 2. Start the gate API on the lane

The API image is `python:3.12-slim` with dependencies installed **in the container**, so build a
scratch image from an existing gate API rather than reinstalling:

```bash
docker commit tanaghom-gateapi tanaghom-s357-deps:local     # reads the layer; the source container is untouched

SECRET=$(openssl rand -hex 24)                              # runtime-only; never committed or logged
PW=$(docker inspect tanaghom-db --format '{{range .Config.Env}}{{println .}}{{end}}' \
      | awk -F= '/^POSTGRES_PASSWORD=/{print $2}')

docker run -d --name tanaghom-gateapi-s357 --network tanaghom_default -p 127.0.0.1:8357:8357 \
  -v "$PWD":/work -w /work \
  -e PYTHONPATH=/work -e TANAGHOM_CONFIG=/work/system_config.example.yaml \
  -e TANAGHOM_WRITER_STUB=1 -e TANAGHOM_DEV_MODE=1 \
  -e DB_HOST=tanaghom-db -e DB_PORT=5432 -e DB_USER=tanaghom -e DB_NAME=tanaghom_s357 -e DB_PASSWORD="$PW" \
  -e REVIEWER_PROXY_SECRET="$SECRET" \
  tanaghom-s357-deps:local python -m uvicorn gates.api:app --host 0.0.0.0 --port 8357

docker exec tanaghom-gateapi-s357 python loader/load_methodology.py     # committed catalogues
```

**Verify stub mode by EXACT match, never `grep stub`** — `grep` also matches `"writer_stub":false`,
which once ran a whole suite against a live provider:

```bash
curl -s http://127.0.0.1:8357/health     # expect "writer_mode":"stub"
```

## 3. Drive a run to `TOPIC_APPROVED` — canonical routes only

No seed inserts. Every transition goes through the governed chain, because a fixture built any other
way would not exercise the authority this slice depends on:

```
POST /rounds                          {label, period_len_days:28, posts_per_day:1,
                                       post_times:["09:00"], format_mix:{"Hero Reel":28}}
POST /gates                           {round_id, stage:"schedule_review"}   (signed principal)
POST /gates/{id}/decide  {approve}  → POST /gates/{id}/resolve
      … Topic generation runs automatically on schedule acceptance …
POST /gates                           {round_id, stage:"topic_review"}
POST /gates/{id}/decide  {approve}  → POST /gates/{id}/resolve
```

`format_mix` must total `days × posts_per_day` and use framework **display names** (`"Hero Reel"`),
not keys — the planner rejects both mistakes with a typed 422.

Requests are signed as `hmac_sha256(REVIEWER_PROXY_SECRET, principal_id)` in
`x-principal-signature`, with `x-principal-id` alongside.

## 4. Run the proof

```bash
docker exec -e PYTHONPATH=/work tanaghom-gateapi-s357 python -m gates.script_generation_selftest
```

Asserts the authority matrix as three distinguishable outcomes, deterministic attempt identity with
replay returning the same attempt, correlation/idempotency proven not to mint identity, the
downstream-advanced denial, deterministic crash recovery (expired persisted lease → exactly one
winner; live lease never stolen), and Topic non-regression. **Idempotent** — it clears only its own
round's Script attempts at start, so it can be run repeatedly.

For the V2 surface, point a workbench at the lane and run the focused specs:

```bash
cd workbench
PORT=3055 TANAGHOM_DEV_MODE=1 API_BASE=http://127.0.0.1:8357 \
  TANAGHOM_WORKBENCH_BUILD_SHA=$(git rev-parse --short HEAD) \
  REVIEWER_PROXY_SECRET="$SECRET" ./node_modules/.bin/next start -p 3055 &

WB_URL=http://localhost:3055 API_BASE=http://127.0.0.1:8357 \
  ./node_modules/.bin/playwright test --project=product-regression \
  e2e/scripts-generation-357.spec.ts e2e/scripts-stage.spec.ts
```

**Read the native exit code unpiped.** Piping through `tail` hides both the failure count and the
exit status.

### Proving IAM fails closed

Start a second workbench with `TANAGHOM_OIDC_ENABLED=1` on another port: both the decision read and
the command must return **501**, and **no job may be created**. Check the job count on a round with
none — counting a round the selftest already used will show a pre-existing job and read as a failure.

## 5. Teardown — exactly four objects

```bash
kill $(lsof -tnP -iTCP:3055 -sTCP:LISTEN)          # the workbench
docker rm -f tanaghom-gateapi-s357                  # the lane API
docker exec tanaghom-db psql -U tanaghom -d postgres -c "DROP DATABASE tanaghom_s357"
docker rmi tanaghom-s357-deps:local                 # the scratch image
```

Nothing else is removed. `tanaghom-db` itself, every other database in it, and all unrelated
containers/volumes/images stay untouched — verify with a count before and after if in doubt.

---

## Traps this lane hit, so the next reader does not

- **The lane API on `--network container:tanaghom-db` is unreachable from the host.** It shares the
  DB's network namespace, and ports cannot be published to a running container's namespace. Use
  `--network tanaghom_default -p 127.0.0.1:8357:8357` instead — otherwise V2 cannot reach it and you
  are forced into mocks, which is how the two end-to-end defects below stayed hidden.
- **V2's `/gw` GET seam signs nothing.** The action decision is evaluated *for a principal*, so an
  unsigned read always returns `principal_missing` and the control can never become available. #357
  signs the decision read with the same identity the write uses; a surface that mocks the decision
  response cannot detect this, because the mock replaces the very thing whose acquisition is broken.
- **An active attempt dominates both the read and the write.** Mid-run the input set shrinks, so a
  second request would otherwise build a different-but-overlapping manifest and race the first. Any
  test that reuses a round must account for this — the committed proof clears its own attempts first
  for exactly that reason.
