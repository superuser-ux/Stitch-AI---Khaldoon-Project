#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OBSERVE_SECONDS=0
if [[ "${1:-}" == --observe ]]; then OBSERVE_SECONDS="${2:-600}"; fi
[[ "${OBSERVE_SECONDS}" =~ ^[0-9]+$ ]] || { echo "FATAL: observation must be an integer" >&2; exit 2; }
COMPOSE=(docker compose -p tanaghom-zitadel-dev -f "${HERE}/docker-compose.yml")
evidence="${HERE}/evidence/verify-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${evidence}"
verified=0
compensate_on_failure() {
  status=$?
  trap - EXIT INT TERM
  if [[ "${verified}" == 0 ]] && ! "${HERE}/rollback.sh" >/dev/null 2>&1; then
    echo "FATAL: verification compensation could not be proven" >&2
    status=70
  fi
  exit "${status}"
}
trap compensate_on_failure EXIT
trap 'exit 130' INT TERM

services="$("${COMPOSE[@]}" config --services | LC_ALL=C sort | tr '\n' ' ')"
[[ "${services}" == "caddy postgres zitadel-api zitadel-login " ]] || { echo "FATAL: topology is not exactly four services" >&2; exit 3; }

for service in postgres zitadel-api zitadel-login caddy; do
  cid="$("${COMPOSE[@]}" ps -q "${service}")"
  [[ -n "${cid}" ]] || { echo "FATAL: ${service} container is missing" >&2; exit 3; }
  status="$(docker inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}' "${cid}")"
  [[ "${status}" == "running|healthy|0|false" ]] || { echo "FATAL: ${service} state is ${status}" >&2; exit 3; }
done

declare -A memory=( [postgres]=536870912 [zitadel-api]=805306368 [zitadel-login]=402653184 [caddy]=134217728 )
declare -A cpu=( [postgres]=500000000 [zitadel-api]=1000000000 [zitadel-login]=500000000 [caddy]=250000000 )
for service in postgres zitadel-api zitadel-login caddy; do
  cid="$("${COMPOSE[@]}" ps -q "${service}")"
  limits="$(docker inspect --format '{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.Privileged}}|{{.HostConfig.NetworkMode}}' "${cid}")"
  [[ "${limits}" == "${memory[${service}]}|${cpu[${service}]}|false|tanaghom-iam-dev" ]] || { echo "FATAL: ${service} limits/isolation mismatch: ${limits}" >&2; exit 3; }
done
docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}' > "${evidence}/docker-stats.txt"

caddy_id="$("${COMPOSE[@]}" ps -q caddy)"
bindings="$(docker inspect --format '{{json .HostConfig.PortBindings}}' "${caddy_id}")"
[[ "${bindings}" == *'"HostIp":"127.0.0.1","HostPort":"18210"'* ]] || { echo "FATAL: Caddy is not bound to 127.0.0.1:18210" >&2; exit 3; }
[[ "${bindings}" != *'0.0.0.0'* && "${bindings}" != *'::'* ]] || { echo "FATAL: non-loopback candidate exposure" >&2; exit 3; }
[[ "$(docker inspect --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "${caddy_id}")" == tanaghom-iam-dev ]] || { echo "FATAL: candidate network mismatch" >&2; exit 3; }

discovery="$(curl -fsS -m 10 -H 'Host: iam.localhost:13210' http://127.0.0.1:18210/.well-known/openid-configuration)"
[[ "$(jq -r .issuer <<<"${discovery}")" == http://iam.localhost:13210 ]] || { echo "FATAL: issuer mismatch" >&2; exit 3; }
[[ "$(jq -r '.id_token_signing_alg_values_supported | index("RS256") != null' <<<"${discovery}")" == true ]] || { echo "FATAL: RS256 is not advertised" >&2; exit 3; }
jwks="$(curl -fsS -m 10 -H 'Host: iam.localhost:13210' http://127.0.0.1:18210/oauth/v2/keys)"
[[ "$(jq -r '[.keys[] | select(.kty == "RSA")] | length > 0' <<<"${jwks}")" == true ]] || { echo "FATAL: RSA JWKS is absent" >&2; exit 3; }

login_code="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Host: iam.localhost:13210' http://127.0.0.1:18210/ui/v2/login/)"
console_code="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Host: iam.localhost:13210' http://127.0.0.1:18210/ui/console)"
[[ "${login_code}" =~ ^(200|30[1278])$ && "${console_code}" =~ ^(200|30[1278])$ ]] || { echo "FATAL: Login/Console route failed (${login_code}/${console_code})" >&2; exit 3; }

python3 "${HERE}/secret_scan.py" "${HERE}" "${evidence}" runtime

now="$(date +%s)"
for file in masterkey postgres_password zitadel-secrets.yaml first-instance-steps.yaml; do
  meta="$(stat -Lc '%a %u %g %Y' "/run/tanaghom-zitadel/current/${file}")"
  read -r mode uid gid mtime <<<"${meta}"
  [[ "${mode} ${uid} ${gid}" == "400 0 0" ]] || { echo "FATAL: unsafe secret metadata" >&2; exit 3; }
  (( mtime <= now + 30 && now - mtime <= 900 )) || { echo "FATAL: stale or future secret material" >&2; exit 3; }
done

iam_runtime="$(curl -fsS -m 10 http://127.0.0.1:13101/api/runtime)"
[[ "$(jq -r '.iam.enabled // .iam_enabled // false' <<<"${iam_runtime}")" == false ]] || { echo "FATAL: Tanaghom IAM was unexpectedly enabled" >&2; exit 3; }

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

deadline=$(( $(date +%s) + OBSERVE_SECONDS ))
while (( $(date +%s) < deadline )); do
  sleep 30
  for service in postgres zitadel-api zitadel-login caddy; do
    cid="$("${COMPOSE[@]}" ps -q "${service}")"
    [[ "$(docker inspect --format '{{.State.Health.Status}}|{{.RestartCount}}|{{.State.OOMKilled}}' "${cid}")" == "healthy|0|false" ]] \
      || { echo "FATAL: ${service} failed during observation" >&2; exit 3; }
  done
done

python3 "${HERE}/secret_scan.py" "${HERE}" "${evidence}" runtime
printf '%s\n' "issuer=http://iam.localhost:13210" "login_http=${login_code}" "console_http=${console_code}" "observation_seconds=${OBSERVE_SECONDS}" > "${evidence}/acceptance.txt"
verified=1
trap - EXIT INT TERM
echo "VERIFY_VERDICT=PASS issuer=http://iam.localhost:13210 observation_seconds=${OBSERVE_SECONDS} evidence=${evidence}"
