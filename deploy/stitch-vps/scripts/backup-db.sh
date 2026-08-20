#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-$ROOT/backups/tanaghom-${TS}.sql.gz}"

mkdir -p "$ROOT/backups"

# the db container only carries POSTGRES_* (least-privilege env injection)
docker compose -f "$ROOT/docker-compose.yml" exec -T db sh -lc '
  exec pg_dump -U "${POSTGRES_USER:-tanaghom}" "${POSTGRES_DB:-tanaghom}"
' | gzip > "$OUT"

printf '%s\n' "$OUT"

