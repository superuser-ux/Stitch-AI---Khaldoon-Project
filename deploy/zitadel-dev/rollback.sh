#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOURNAL="${HERE}/.provision-journal"
OPERATOR_ENV=/srv/tanaghom-dev/openbao/custody/operator.env
SNAPSHOT_DIR=/srv/tanaghom-dev/openbao/snapshots
PROJECT=tanaghom-zitadel-dev
LOGIN_VOLUME=tanaghom-zitadel-dev_login_bootstrap
POSTGRES_VOLUME=tanaghom-zitadel-dev_postgres_data

[[ "${EUID}" -eq 0 ]] || { echo "FATAL: run rollback with sudo" >&2; exit 2; }
[[ -f "${JOURNAL}" && ! -L "${JOURNAL}" ]] || { echo "FATAL: exact provision journal is unavailable" >&2; exit 3; }
[[ "$(stat -c '%a %u %g' "${JOURNAL}")" == "600 0 0" ]] || { echo "FATAL: provision journal metadata is unsafe" >&2; exit 3; }

has_mark() { grep -Fxq -- "$1" "${JOURNAL}"; }
journal_value() { sed -n "s/^$1=//p" "${JOURNAL}" | tail -1; }

postgres_was_present=0
if has_mark compose=attempted; then
  if docker volume inspect "${POSTGRES_VOLUME}" >/dev/null 2>&1; then
    postgres_was_present=1
  fi
  docker compose -p "${PROJECT}" -f "${HERE}/docker-compose.yml" down --remove-orphans >/dev/null
  if docker volume inspect "${LOGIN_VOLUME}" >/dev/null 2>&1; then
    docker volume rm "${LOGIN_VOLUME}" >/dev/null
  fi
fi

[[ -f "${OPERATOR_ENV}" && ! -L "${OPERATOR_ENV}" ]] || { echo "FATAL: OpenBao operator custody unavailable" >&2; exit 3; }
# shellcheck disable=SC1090
source "${OPERATOR_ENV}"
[[ -n "${BAO_ADDR:-}" && -n "${BAO_TOKEN:-}" ]] || { echo "FATAL: OpenBao operator custody incomplete" >&2; exit 3; }
header() { printf 'X-Vault-Token: %s' "${BAO_TOKEN}"; }
api() { curl -sS -m 15 --fail-with-body -H @<(header) "$@"; }
api_code() { curl -sS -m 15 -o /dev/null -w '%{http_code}' -H @<(header) "$@"; }

accessor="$(journal_value secret_accessor)"
if [[ -n "${accessor}" ]]; then
  [[ "${accessor}" =~ ^[A-Za-z0-9-]+$ ]] || { echo "FATAL: journaled SecretID accessor is unsafe" >&2; exit 3; }
  python3 - "${accessor}" <<'PY' | api -X POST --data @- "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev/secret-id-accessor/destroy" >/dev/null
import json, sys
print(json.dumps({"secret_id_accessor": sys.argv[1]}))
PY
  accessor_code="$(python3 - "${accessor}" <<'PY' | api_code -X POST --data @- "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev/secret-id-accessor/lookup"
import json, sys
print(json.dumps({"secret_id_accessor": sys.argv[1]}))
PY
)"
  [[ "${accessor_code}" == 400 || "${accessor_code}" == 404 ]] || { echo "FATAL: SecretID accessor remains queryable" >&2; exit 3; }
fi

if has_mark approle=tanaghom-zitadel-dev; then
  api -X DELETE "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev" >/dev/null
fi
if has_mark policy=tanaghom-zitadel-dev; then
  api -X DELETE "${BAO_ADDR}/v1/sys/policies/acl/tanaghom-zitadel-dev" >/dev/null
fi
for path in masterkey postgres bootstrap-admin; do
  if has_mark "kv=${path}"; then
    api -X DELETE "${BAO_ADDR}/v1/tanaghom/metadata/dev/zitadel/${path}" >/dev/null
  fi
done

for path in masterkey postgres bootstrap-admin; do
  [[ "$(api_code "${BAO_ADDR}/v1/tanaghom/metadata/dev/zitadel/${path}")" == 404 ]] \
    || { echo "FATAL: OpenBao KV residue remains: ${path}" >&2; exit 3; }
done
[[ "$(api_code "${BAO_ADDR}/v1/sys/policies/acl/tanaghom-zitadel-dev")" == 404 ]] \
  || { echo "FATAL: OpenBao policy residue remains" >&2; exit 3; }
[[ "$(api_code "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev")" == 404 ]] \
  || { echo "FATAL: OpenBao AppRole residue remains" >&2; exit 3; }
BAO_TOKEN=""

if has_mark timer=enabled; then
  if systemctl is-enabled --quiet tanaghom-zitadel-secrets.timer; then
    systemctl disable --now tanaghom-zitadel-secrets.timer >/dev/null
  elif systemctl is-active --quiet tanaghom-zitadel-secrets.timer; then
    systemctl stop tanaghom-zitadel-secrets.timer
  fi
fi
if has_mark runtime=created && systemctl is-active --quiet tanaghom-zitadel-secrets.service; then
  systemctl stop tanaghom-zitadel-secrets.service
fi
if has_mark units=created; then
  rm -f /etc/systemd/system/tanaghom-zitadel-secrets.service /etc/systemd/system/tanaghom-zitadel-secrets.timer
  systemctl daemon-reload
fi
if has_mark custody=created; then
  rm -rf "${HERE}/openbao/custody"
  rm -f "${HERE}/.secret-accessor"
fi
if has_mark runtime=created; then
  rm -rf /run/tanaghom-zitadel
fi

if systemctl is-enabled --quiet tanaghom-zitadel-secrets.timer; then
  echo "FATAL: candidate timer remains enabled" >&2
  exit 3
fi
if systemctl is-active --quiet tanaghom-zitadel-secrets.timer tanaghom-zitadel-secrets.service; then
  echo "FATAL: candidate systemd unit remains active" >&2
  exit 3
fi
if systemctl cat tanaghom-zitadel-secrets.timer >/dev/null 2>&1 || systemctl cat tanaghom-zitadel-secrets.service >/dev/null 2>&1; then
  echo "FATAL: candidate systemd unit file remains" >&2
  exit 3
fi
[[ ! -e "${HERE}/openbao/custody" && ! -L "${HERE}/openbao/custody" && ! -e "${HERE}/.secret-accessor" ]] \
  || { echo "FATAL: candidate custody residue remains" >&2; exit 3; }
[[ ! -e /run/tanaghom-zitadel && ! -L /run/tanaghom-zitadel ]] \
  || { echo "FATAL: candidate runtime residue remains" >&2; exit 3; }

[[ -z "$(docker ps -aq --filter label=com.docker.compose.project="${PROJECT}")" ]] \
  || { echo "FATAL: candidate container residue remains" >&2; exit 3; }
if docker network inspect tanaghom-iam-dev >/dev/null 2>&1; then
  echo "FATAL: candidate network residue remains" >&2
  exit 3
fi
if docker volume inspect "${LOGIN_VOLUME}" >/dev/null 2>&1; then
  echo "FATAL: Login PAT volume residue remains" >&2
  exit 3
fi
if [[ "${postgres_was_present}" == 1 ]]; then
  docker volume inspect "${POSTGRES_VOLUME}" >/dev/null 2>&1 \
    || { echo "FATAL: PostgreSQL diagnostic volume was not preserved" >&2; exit 3; }
fi

snapshot="$(journal_value snapshot)"
if [[ -n "${snapshot}" ]]; then
  [[ "${snapshot}" =~ ^${SNAPSHOT_DIR}/zitadel-pilot-[0-9]{8}T[0-9]{6}Z\.snap$ ]] \
    || { echo "FATAL: journaled snapshot path is unsafe" >&2; exit 3; }
  [[ -f "${snapshot}" && ! -L "${snapshot}" && "$(stat -c '%a %u %g' "${snapshot}")" == "600 0 0" ]] \
    || { echo "FATAL: pre-change OpenBao snapshot was not preserved" >&2; exit 3; }
fi

baseline="${HERE}/evidence/preflight-baseline.txt"
[[ -f "${baseline}" && ! -L "${baseline}" ]] || { echo "FATAL: workload identity baseline is unavailable" >&2; exit 3; }
identity_records=0
while IFS='|' read -r kind name object_id _rest; do
  if [[ "${kind}" == listener ]]; then
    [[ -n "${name}" ]] || { echo "FATAL: malformed workload listener baseline record" >&2; exit 3; }
    continue
  fi
  if [[ "${kind}" != container && "${kind}" != network ]]; then
    [[ "${kind}" =~ ^captured_at=[0-9TZ:-]+$ || "${kind}" =~ ^mem_available_mb=[0-9]+$ \
      || "${kind}" =~ ^disk_used_pct=[0-9]+$ || "${kind}" =~ ^load1=[0-9]+([.][0-9]+)?$ ]] \
      || { echo "FATAL: malformed workload identity baseline" >&2; exit 3; }
    continue
  fi
  [[ -n "${name}" && "${object_id}" =~ ^[0-9a-f]{12,64}$ ]] \
    || { echo "FATAL: malformed workload identity baseline record" >&2; exit 3; }
  if [[ "${kind}" == container ]]; then
    current="$(docker inspect --format '{{.Id}}' "${name}" 2>/dev/null)" \
      || { echo "FATAL: preserved workload is missing: ${name}" >&2; exit 3; }
  else
    current="$(docker network inspect --format '{{.Id}}' "${name}" 2>/dev/null)" \
      || { echo "FATAL: preserved network is missing: ${name}" >&2; exit 3; }
  fi
  [[ "${current}" == "${object_id}"* ]] || { echo "FATAL: preserved ${kind} identity drifted: ${name}" >&2; exit 3; }
  identity_records=$((identity_records + 1))
done < "${baseline}"
(( identity_records > 0 )) || { echo "FATAL: workload identity baseline has no identity records" >&2; exit 3; }

rm -f "${JOURNAL}"
postgres_state=absent_not_created
[[ "${postgres_was_present}" == 0 ]] || postgres_state=preserved
echo "ROLLBACK_VERDICT=PASS postgres_volume=${postgres_state} login_volume=absent openbao_snapshot=preserved existing_workloads=stable"
