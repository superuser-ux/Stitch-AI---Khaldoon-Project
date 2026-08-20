#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-${HERE}/evidence/provenance-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "${OUT}"
command -v docker >/dev/null || { echo "FATAL: docker is required" >&2; exit 2; }
command -v jq >/dev/null || { echo "FATAL: jq is required" >&2; exit 2; }

while IFS='|' read -r name tag index child source; do
  raw="${OUT}/${name}.raw.json"
  inspect="${OUT}/${name}.inspect.txt"
  docker buildx imagetools inspect --raw "${tag}" > "${raw}"
  docker buildx imagetools inspect "${tag}" > "${inspect}"
  got_index="sha256:$(sha256sum "${raw}" | cut -d' ' -f1)"
  got_child="$(jq -r '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") | .digest' "${raw}")"
  [[ "${got_index}" == "${index}" ]] || { echo "FATAL: ${name} index mismatch" >&2; exit 3; }
  [[ "${got_child}" == "${child}" ]] || { echo "FATAL: ${name} linux/amd64 child mismatch" >&2; exit 3; }
  printf '%s|%s|%s|%s|%s|%s\n' "${name}" "${tag}" "${index}" "${child}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${source}" >> "${OUT}/verified.txt"
done < "${HERE}/provenance.lock"

sha256sum "${HERE}/provenance.lock" "${OUT}"/* > "${OUT}/SHA256SUMS"
echo "PROVENANCE_VERDICT=PASS evidence=${OUT}"
