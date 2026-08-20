# Tanaghom VPS deployment scaffold (STITCH-VPS)

Deployable runtime skeleton for the internal-review VPS. **Posture: internal review /
pre-staging over plain HTTP with demo identity — explicitly NOT production-safe.** OIDC
activation and TLS/domain cutover are separate, deferred gates.

Current operating mode:
- public IP only, HTTP on port `80`
- dashboard exposed through a front proxy (Nginx)
- gate API and database stay private (Docker network / localhost-bound ports)

## Layout

- `docker-compose.yml` — app stack (db / gateapi / dashboard / proxy)
- `Dockerfile.api` — gate API image
- `Dockerfile.dashboard` — dashboard image (deliberately unstamped; see Build identity)
- `nginx/default.conf.template` — front proxy, parameterized by env
- `.env` — host-local secret/runtime values, **never committed** (`.env.example` = placeholders)
- `config/system_config.yaml` — host-local Tanaghom config copy, **never committed**
- `scripts/backup-db.sh` / `scripts/restore-db.sh` — SQL backup/restore helpers
- `backups/` — dump target, gitignored except `.gitkeep`

## Least-privilege environment injection

Each container receives ONLY what it needs — verify with the key-name audit below, never by
printing values:
- **db**: `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` only.
- **gateapi**: DB settings + provider key (`GROQ_*`) + `REVIEWER_PROXY_SECRET` + runtime flags.
- **dashboard**: `API_BASE`, `REVIEWER_PROXY_SECRET`, build/surface/IAM values — **no DB
  password, no provider API key**.
- **proxy**: `PUBLIC_SERVER_NAME` only.

## Writer mode — live vs stub

The gate API treats ANY non-empty `TANAGHOM_WRITER_STUB` as stub-truthy — **including the
string `0`**. Live therefore means the variable is EMPTY or absent (the compose default
`${TANAGHOM_WRITER_STUB:-}` and the `.env.example` line keep it empty). Verify with an exact
match, not a substring grep:

```sh
curl -s http://127.0.0.1:8009/health | grep -o '"writer_stub":[a-z]*,"writer_mode":"[a-z]*"'
# expected on this deployment: "writer_stub":false,"writer_mode":"live"
```

## Build identity (#202)

`/api/runtime` reports the SERVER-RUNTIME `TANAGHOM_BUILD_SHA` — stamped in `.env` at every
deploy/update — and NOTHING else: unset/blank means an explicit `unknown`, and a bake-time
value is never consulted (a stale baked revision must not masquerade as deployed runtime
truth). The image itself is deliberately never baked with a revision (the build context
excludes `.git`, and a baked value would go stale when containers are recreated from an older
image).

## First-time setup

1. Copy `.env.example` to `deploy/stitch-vps/.env` (compose reads the `.env` sibling of
   `docker-compose.yml`) and replace every placeholder.
2. Copy the repo-root `system_config.example.yaml` to `config/system_config.yaml` and adjust.
3. Stamp the build: `sed -i "s/^TANAGHOM_BUILD_SHA=.*/TANAGHOM_BUILD_SHA=$(git rev-parse --short HEAD)/" .env`
4. `docker compose up -d --build`
5. Apply schema + migrations, then load the canonical catalogs (below).
6. Run the validation checklist (below). Keep only port `80` public.

## Schema, migrations, canonical catalogs

Fresh database (first boot only — the deploy stack does NOT auto-run `db/init`):

```sh
cd /path/to/tanaghom
docker compose -f deploy/stitch-vps/docker-compose.yml exec -T db \
  sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/init/schema.sql
for m in db/migrations/*.sql; do
  docker compose -f deploy/stitch-vps/docker-compose.yml exec -T db \
    sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$m" || exit 1
done
```

Canonical catalogs (idempotent UPSERT loader with asserted counts; transcribes the
`methodology/` markdown source of truth):

```sh
python3 loader/load_methodology.py   # see loader/README.md for connection env
```

## Update procedure (every deploy)

1. **Backup first** — `scripts/backup-db.sh` (writes `backups/tanaghom-<UTC>.sql.gz`).
2. Pull the exact revision to deploy: `git fetch && git checkout <revision>`.
3. Apply any NEW migrations (same loop as above — each file is idempotent).
4. Stamp the revision: `sed -i "s/^TANAGHOM_BUILD_SHA=.*/TANAGHOM_BUILD_SHA=$(git rev-parse --short HEAD)/" deploy/stitch-vps/.env`
5. Rebuild + recreate: `docker compose up -d --build` (from `deploy/stitch-vps/`).
6. **Refresh the proxy upstream** — Nginx resolves the dashboard container IP at startup, so a
   recreated dashboard can leave the proxy pointing at a dead upstream:
   `docker compose restart proxy`
7. Run the validation checklist.

## Validation checklist

Run after every deploy/update; every step must pass before calling the deployment good.

1. **Environment propagation (key NAMES only — never print values):**
   ```sh
   docker inspect tanaghom-dashboard --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1 | sort
   docker inspect tanaghom-proxy     --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1 | sort
   ```
   Neither list may contain `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `DB_PASSWORD`, or
   `POSTGRES_PASSWORD`. The db container's list stays `POSTGRES_*` only.
2. **Runtime identity:** `curl -s http://127.0.0.1:3000/api/runtime` reports
   `"surface":"operator"`, `"identity":"demo"`, and `"build":"<the stamped SHA>"` —
   `unknown` only if you deliberately left `TANAGHOM_BUILD_SHA` empty.
3. **Writer truth:** exact-match health check above shows `"writer_stub":false` and
   `"writer_mode":"live"`.
4. **Service health:** `docker compose ps` all Up;
   `curl -s http://127.0.0.1:8009/health` returns `"ok":true`.
5. **Public path:** `curl -s -o /dev/null -w '%{http_code}' http://<public-ip>/` returns `200`
   (through the refreshed proxy).
6. **Canonical baseline** (internal-review acceptance expects exactly):
   ```sh
   docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tc "
     SELECT (SELECT count(*) FROM pillar), (SELECT count(*) FROM lens),
            (SELECT count(*) FROM hook_type), (SELECT count(*) FROM hcs),
            (SELECT count(*) FROM format),
            (SELECT count(*) FROM workflow),
            (SELECT count(*) FROM round)"'
   ```
   Expected: `5 | 5 | 5 | 42 | 4 | 1 | 0` — five pillars, five lenses, five hook types,
   42 HCS records, four content formats, one active workflow, and **zero runs** before
   clean-slate acceptance testing.

## Backup / restore

- `scripts/backup-db.sh` — SQL dump (gzip) into `backups/` (gitignored).
- `scripts/restore-db.sh <dump.sql.gz>` — restore into the live DB.

## Cutover notes

- `PUBLIC_SERVER_NAME=_` is fine for IP-only access today.
- When a real domain is available, change `PUBLIC_SERVER_NAME` and `PUBLIC_BASE_URL`.
- Do not move the database or app ports when switching hostnames.
- Add TLS in a later step without changing the container topology; OIDC/identity binding is a
  separate directive (#187 remains the secret-handling authority).
