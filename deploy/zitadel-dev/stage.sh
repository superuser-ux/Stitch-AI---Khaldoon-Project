#!/usr/bin/env bash
set -euo pipefail

SHA="${1:-}"
TARGET="${2:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "${SHA}" =~ ^[0-9a-f]{40}$ && -n "${TARGET}" ]] || { echo "usage: stage.sh <40-char-sha> <empty-target>" >&2; exit 2; }
[[ "$(git -C "${HERE}/../.." rev-parse HEAD)" == "${SHA}" ]] || { echo "FATAL: HEAD does not match reviewed SHA" >&2; exit 3; }
[[ -z "$(git -C "${HERE}/../.." status --short)" ]] || { echo "FATAL: source worktree is dirty" >&2; exit 3; }
[[ ! -L "${TARGET}" ]] || { echo "FATAL: target is a symlink" >&2; exit 3; }
if [[ -e "${TARGET}" ]]; then [[ -d "${TARGET}" && -z "$(ls -A "${TARGET}")" ]] || { echo "FATAL: target is not an empty directory" >&2; exit 3; }; fi

parent="$(cd "$(dirname "${TARGET}")" && pwd -P)"
work="$(mktemp -d "${parent}/.zitadel-stage.XXXXXX")"
trap 'rm -rf "${work}"' EXIT

files=(
  .gitignore Caddyfile README.md docker-compose.yml packaging_test.sh preflight.sh provenance.lock
  provenance.sh provision.sh deploy.sh failure_diagnostics.py reset-diagnostic.sh rollback.sh
  secret_scan.py stage.sh verify.sh zitadel-config.yaml
  openbao/materialize-zitadel.sh openbao/tanaghom-zitadel-secrets.service
  openbao/tanaghom-zitadel-secrets.timer openbao/zitadel-policy.hcl
)
for file in "${files[@]}"; do
  mkdir -p "${work}/$(dirname "${file}")"
  cp "${HERE}/${file}" "${work}/${file}"
done
chmod 0750 "${work}"/*.sh "${work}/openbao/materialize-zitadel.sh"

{
  echo "manifest_version 1"
  echo "reviewed_sha ${SHA}"
  for file in "${files[@]}"; do
    echo "file ./${file} sha256=$(sha256sum "${work}/${file}" | cut -d' ' -f1)"
  done
} > "${work}/MANIFEST.txt"

expected="$(printf '%s\n' "${files[@]}" MANIFEST.txt | LC_ALL=C sort)"
actual="$(cd "${work}" && find . -type f -print | sed 's#^./##' | LC_ALL=C sort)"
[[ "${actual}" == "${expected}" ]] || { echo "FATAL: staged allowlist mismatch" >&2; exit 3; }
[[ -z "$(find "${work}" -type l -print)" ]] || { echo "FATAL: symlink in staged package" >&2; exit 3; }

if [[ -e "${TARGET}" ]]; then rmdir "${TARGET}"; fi
mv "${work}" "${TARGET}"
trap - EXIT
manifest_sha="$(sha256sum "${TARGET}/MANIFEST.txt" | cut -d' ' -f1)"
printf '%s' "${manifest_sha}" > "${TARGET}.manifest.sha256"
echo "STAGE_VERDICT=PASS MANIFEST_SHA256=${manifest_sha}"
