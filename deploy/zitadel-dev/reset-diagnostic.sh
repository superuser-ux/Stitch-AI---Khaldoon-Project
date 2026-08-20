#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT=tanaghom-zitadel-dev
POSTGRES_VOLUME=tanaghom-zitadel-dev_postgres_data

[[ "${EUID}" -eq 0 ]] || { echo "FATAL: run diagnostic reset with sudo" >&2; exit 2; }
[[ ! -e "${HERE}/.provision-journal" ]] || { echo "FATAL: rollback is not proven complete" >&2; exit 3; }
[[ -z "$(docker ps -aq --filter label=com.docker.compose.project="${PROJECT}")" ]] \
  || { echo "FATAL: candidate containers still exist" >&2; exit 3; }
if docker network inspect tanaghom-iam-dev >/dev/null 2>&1; then
  echo "FATAL: candidate network still exists" >&2
  exit 3
fi
[[ -z "$(ss -ltnH 'sport = :18210')" ]] || { echo "FATAL: candidate listener still exists" >&2; exit 3; }

labels="$(docker volume inspect --format '{{ index .Labels "com.docker.compose.project" }}|{{ index .Labels "com.docker.compose.volume" }}' "${POSTGRES_VOLUME}")" \
  || { echo "FATAL: exact diagnostic volume is absent" >&2; exit 3; }
[[ "${labels}" == "${PROJECT}|postgres_data" ]] \
  || { echo "FATAL: diagnostic volume labels are not exact" >&2; exit 3; }
[[ -z "$(docker ps -aq --filter volume="${POSTGRES_VOLUME}")" ]] \
  || { echo "FATAL: diagnostic volume is still attached" >&2; exit 3; }

docker volume rm "${POSTGRES_VOLUME}" >/dev/null
docker volume inspect "${POSTGRES_VOLUME}" >/dev/null 2>&1 \
  && { echo "FATAL: diagnostic volume remains after reset" >&2; exit 3; }
echo "DIAGNOSTIC_RESET_VERDICT=PASS volume=${POSTGRES_VOLUME} scope=candidate-only"
