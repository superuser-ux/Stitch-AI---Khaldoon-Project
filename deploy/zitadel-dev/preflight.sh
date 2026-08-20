#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_MANIFEST="${1:-${ZITADEL_EXPECTED_MANIFEST_SHA256:-}}"
[[ "${EUID}" -eq 0 ]] || { echo "FATAL: run preflight with sudo" >&2; exit 2; }
[[ "${EXPECTED_MANIFEST}" =~ ^[0-9a-f]{64}$ ]] || { echo "FATAL: expected manifest SHA-256 is required" >&2; exit 2; }
[[ -f "${HERE}/MANIFEST.txt" && ! -L "${HERE}/MANIFEST.txt" ]] || { echo "FATAL: package manifest missing or unsafe" >&2; exit 3; }
[[ "$(sha256sum "${HERE}/MANIFEST.txt" | cut -d' ' -f1)" == "${EXPECTED_MANIFEST}" ]] || { echo "FATAL: package manifest digest mismatch" >&2; exit 3; }

while read -r kind path digest extra; do
  [[ "${kind}" == file && -z "${extra:-}" && "${path}" == ./* && "${digest}" == sha256=* ]] || continue
  file="${HERE}/${path#./}"
  [[ -f "${file}" && ! -L "${file}" ]] || { echo "FATAL: package file missing or unsafe: ${path}" >&2; exit 3; }
  [[ "$(sha256sum "${file}" | cut -d' ' -f1)" == "${digest#sha256=}" ]] || { echo "FATAL: package file digest mismatch: ${path}" >&2; exit 3; }
done < "${HERE}/MANIFEST.txt"

for command in curl docker jq openssl python3 systemctl; do command -v "${command}" >/dev/null || { echo "FATAL: ${command} is required" >&2; exit 3; }; done
docker compose version >/dev/null
docker buildx version >/dev/null

mem_available="$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)"
disk_used="$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
load1="$(awk '{print $1}' /proc/loadavg)"
(( mem_available >= 1800 )) || { echo "FATAL: available memory below 1800 MiB" >&2; exit 4; }
(( disk_used < 85 )) || { echo "FATAL: root disk use is 85% or higher" >&2; exit 4; }
awk -v current_load="${load1}" 'BEGIN {exit !(current_load <= 2.5)}' || { echo "FATAL: load1 exceeds 2.5" >&2; exit 4; }
[[ -z "$(ss -H -ltn 'sport = :13210 or sport = :18210')" ]] || { echo "FATAL: candidate port is occupied" >&2; exit 4; }

[[ -z "$(docker ps -a --format '{{.Names}}' | grep '^tanaghom-zitadel-dev-' || true)" ]] || { echo "FATAL: candidate containers already exist" >&2; exit 4; }
[[ -z "$(docker network ls --format '{{.Name}}' | grep '^tanaghom-iam-dev$' || true)" ]] || { echo "FATAL: candidate network already exists" >&2; exit 4; }
[[ -z "$(docker volume ls --format '{{.Name}}' | grep '^tanaghom-zitadel-dev_' || true)" ]] || { echo "FATAL: candidate volumes already exist" >&2; exit 4; }
while IFS='|' read -r name tag index _child _source; do
  ref="${tag}@${index}"
  if docker image inspect "${ref}" >/dev/null 2>&1; then
    [[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "${ref}")" == linux/amd64 ]] \
      || { echo "FATAL: cached exact image architecture mismatch: ${name}" >&2; exit 4; }
    [[ "${name}" != zitadel && "${name}" != login ]] \
      || { echo "FATAL: ZITADEL-specific image residue exists: ${name}" >&2; exit 4; }
  fi
done < "${HERE}/provenance.lock"

for path in "${HERE}/openbao/custody" "${HERE}/.secret-accessor" "${HERE}/.provision-journal" /run/tanaghom-zitadel; do
  [[ ! -e "${path}" && ! -L "${path}" ]] || { echo "FATAL: pre-existing candidate custody/runtime object: ${path}" >&2; exit 4; }
done
for unit in tanaghom-zitadel-secrets.service tanaghom-zitadel-secrets.timer; do
  systemctl cat "${unit}" >/dev/null 2>&1 && { echo "FATAL: candidate systemd unit already exists" >&2; exit 4; } || true
done

OPERATOR_ENV=/srv/tanaghom-dev/openbao/custody/operator.env
[[ -f "${OPERATOR_ENV}" && "$(stat -c '%a %u %g' "${OPERATOR_ENV}")" == "600 0 0" ]] || { echo "FATAL: OpenBao operator custody unavailable" >&2; exit 4; }
# shellcheck disable=SC1090
source "${OPERATOR_ENV}"
[[ -n "${BAO_ADDR:-}" && -n "${BAO_TOKEN:-}" ]] || { echo "FATAL: OpenBao operator custody incomplete" >&2; exit 4; }
health="$(curl -fsS -m 5 "${BAO_ADDR}/v1/sys/health")"
[[ "$(jq -r '.initialized and (.sealed|not)' <<<"${health}")" == true ]] || { echo "FATAL: OpenBao is unavailable or sealed" >&2; exit 4; }

api_code() { curl -sS -m 5 -o /dev/null -w '%{http_code}' -H @<(printf 'X-Vault-Token: %s' "${BAO_TOKEN}") "$1" || true; }
for path in masterkey postgres bootstrap-admin; do
  [[ "$(api_code "${BAO_ADDR}/v1/tanaghom/metadata/dev/zitadel/${path}")" == 404 ]] || { echo "FATAL: OpenBao KV object already exists: ${path}" >&2; exit 4; }
done
[[ "$(api_code "${BAO_ADDR}/v1/sys/policies/acl/tanaghom-zitadel-dev")" == 404 ]] || { echo "FATAL: OpenBao policy already exists" >&2; exit 4; }
[[ "$(api_code "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev")" == 404 ]] || { echo "FATAL: OpenBao AppRole already exists" >&2; exit 4; }
BAO_TOKEN=""

mkdir -p "${HERE}/evidence"
{
  echo "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "mem_available_mb=${mem_available}"
  echo "disk_used_pct=${disk_used}"
  echo "load1=${load1}"
  docker ps --format 'container|{{.Names}}|{{.ID}}|{{.Image}}|{{.Status}}|{{.Ports}}'
  docker network ls --format 'network|{{.Name}}|{{.ID}}'
  ss -H -ltnp | sed 's/^/listener|/'
} > "${HERE}/evidence/preflight-baseline.txt"
echo "PREFLIGHT_VERDICT=PASS mem_available_mb=${mem_available} disk_used_pct=${disk_used} load1=${load1}"
