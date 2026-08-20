#!/usr/bin/env bash
# #338 — build the two acceptance application images from the EXACT reviewed commit, with immutable
# provenance. Requires a full 40-char lowercase SHA and a clean checkout whose HEAD equals it; rejects
# missing, abbreviated, malformed, dirty, or mismatching input. Both images receive the OCI revision
# label; the workbench additionally bakes the runtime SHA. Prints the local image ID + revision label +
# numeric user for each. Never embeds a secret (GIT_SHA is not a secret).
set -euo pipefail

SHA="${1:-${ACC_GIT_SHA:-}}"
if [[ -z "${SHA}" ]]; then
  echo "usage: build.sh <full-40-char-sha>   (or export ACC_GIT_SHA)" >&2
  exit 2
fi
if [[ ! "${SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "FATAL: build SHA must be a full lowercase 40-character hex commit id; refusing '${SHA}'" >&2
  exit 2
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && git rev-parse --show-toplevel)"
cd "${REPO}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "FATAL: working tree is dirty — refusing to build a non-reproducible artifact." >&2
  exit 2
fi
HEAD="$(git rev-parse HEAD)"
if [[ "${HEAD}" != "${SHA}" ]]; then
  echo "FATAL: checkout HEAD (${HEAD}) does not equal the requested build SHA (${SHA})." >&2
  exit 2
fi

GATEAPI="tanaghom-acc-gateapi:${SHA}"
WORKBENCH="tanaghom-acc-workbench:${SHA}"

echo "[build] gateapi  <- ${SHA}"
docker build -f deploy/stitch-vps/Dockerfile.api --build-arg GIT_SHA="${SHA}" -t "${GATEAPI}" "${REPO}"
echo "[build] workbench <- ${SHA}"
docker build -f workbench/Dockerfile --build-arg GIT_SHA="${SHA}" -t "${WORKBENCH}" "${REPO}/workbench"

echo ""
echo "=== provenance (local image ID + immutable revision label + numeric user) ==="
for img in "${GATEAPI}" "${WORKBENCH}"; do
  id="$(docker inspect --format '{{.Id}}' "${img}")"
  rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${img}")"
  usr="$(docker inspect --format '{{.Config.User}}' "${img}")"
  echo "  ${img}"
  echo "    local image ID : ${id}"
  echo "    revision label : ${rev}"
  echo "    runtime user   : ${usr}"
  if [[ "${rev}" != "${SHA}" ]]; then echo "FATAL: ${img} revision label != build SHA"; exit 3; fi
  if [[ "${usr}" != "10001:10001" && "${usr}" != "10001" ]]; then echo "FATAL: ${img} is not numeric non-root"; exit 3; fi
done
echo "[build] OK — both images tagged :${SHA}, labelled, numeric non-root."
