#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "${EUID}" -eq 0 ]] || { echo "FATAL: run deploy with sudo" >&2; exit 2; }
[[ -f "${HERE}/.provision-journal" ]] || { echo "FATAL: provision journal is missing" >&2; exit 3; }
for file in masterkey postgres_password zitadel-secrets.yaml first-instance-steps.yaml; do
  [[ "$(stat -Lc '%a %u %g' "/run/tanaghom-zitadel/current/${file}" 2>/dev/null)" == "400 0 0" ]] || { echo "FATAL: materialized secret file is missing or unsafe" >&2; exit 3; }
done

evidence="${HERE}/evidence/deploy-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${evidence}"
failed=1
on_exit() {
  status=$?
  trap - EXIT INT TERM
  if [[ "${failed}" == 1 ]]; then
    if ! python3 "${HERE}/failure_diagnostics.py" "${HERE}" "${evidence}"; then
      echo "WARNING: secret-safe failure diagnostics could not be retained" >&2
    fi
    if ! "${HERE}/rollback.sh"; then
      echo "FATAL: deployment compensation could not be proven" >&2
      status=70
    fi
  fi
  exit "${status}"
}
trap on_exit EXIT
trap 'exit 130' INT TERM

"${HERE}/provenance.sh" "${evidence}/provenance"

while IFS='|' read -r name tag index _child _source; do
  ref="${tag}@${index}"
  docker pull --platform linux/amd64 "${ref}" > "${evidence}/${name}.pull.txt"
  [[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "${ref}")" == linux/amd64 ]] || { echo "FATAL: ${name} loaded architecture mismatch" >&2; exit 4; }
done < "${HERE}/provenance.lock"

python3 "${HERE}/secret_scan.py" "${HERE}" "${evidence}" predeploy
if grep -Eq '(^|[[:space:]])(POSTGRES_PASSWORD|ZITADEL_MASTERKEY|ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD):' "${evidence}/compose.rendered.yaml"; then
  echo "FATAL: rendered Compose contains a secret-bearing environment key" >&2
  exit 4
fi

printf '%s\n' 'compose=attempted' >> "${HERE}/.provision-journal"
docker compose -p tanaghom-zitadel-dev -f "${HERE}/docker-compose.yml" up -d --wait --wait-timeout 420
printf '%s\n' 'compose=started' >> "${HERE}/.provision-journal"
failed=0
trap - EXIT INT TERM
echo "DEPLOY_VERDICT=PASS evidence=${evidence}"
