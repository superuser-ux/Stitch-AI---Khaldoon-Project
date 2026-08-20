#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DUMP="${1:?usage: restore-db.sh <dump.sql.gz>}"

# the db container only carries POSTGRES_* (least-privilege env injection)
gzip -dc "$DUMP" | docker compose -f "$ROOT/docker-compose.yml" exec -T db sh -lc '
  exec psql -U "${POSTGRES_USER:-tanaghom}" "${POSTGRES_DB:-tanaghom}"
'

