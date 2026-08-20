#!/usr/bin/env bash
# #389 — build the two v2-dev application images from the EXACT reviewed commit, with immutable
# provenance, using the EXISTING committed recipes (deploy/stitch-vps/Dockerfile.api, workbench/
# Dockerfile) verbatim — so the images are byte-identical in build recipe to the acceptance/production
# images and differ only in tag namespace. Requires a full 40-char lowercase SHA and a clean checkout
# whose HEAD equals it; rejects missing, abbreviated, malformed, dirty, or mismatching input. Both images
# receive the OCI revision label; the workbench additionally bakes the runtime SHA; the gateapi bakes
# /work/BUILD_SHA (asserted at runtime by deploy/v2-dev/gateapi-entrypoint.sh). Prints local image ID +
# revision label + numeric user for each. Never embeds a secret (GIT_SHA is not a secret). No VPS action.
set -euo pipefail

SHA="${1:-${V2DEV_GIT_SHA:-}}"
if [[ -z "${SHA}" ]]; then
  echo "usage: build.sh <full-40-char-sha>   (or export V2DEV_GIT_SHA)" >&2
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

GATEAPI="tanaghom-v2-dev-gateapi:${SHA}"
WORKBENCH="tanaghom-v2-dev-workbench:${SHA}"

echo "[build] gateapi  <- ${SHA} (linux/amd64)"
docker build --platform linux/amd64 -f deploy/stitch-vps/Dockerfile.api --build-arg GIT_SHA="${SHA}" -t "${GATEAPI}" "${REPO}"
echo "[build] workbench <- ${SHA} (linux/amd64)"
docker build --platform linux/amd64 -f workbench/Dockerfile --build-arg GIT_SHA="${SHA}" -t "${WORKBENCH}" "${REPO}/workbench"

echo ""
echo "=== provenance (local image ID + immutable revision label + numeric user) ==="
for img in "${GATEAPI}" "${WORKBENCH}"; do
  id="$(docker inspect --format '{{.Id}}' "${img}")"
  rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${img}")"
  usr="$(docker inspect --format '{{.Config.User}}' "${img}")"
  arch="$(docker inspect --format '{{.Architecture}}' "${img}")"
  echo "  ${img}"
  echo "    local image ID : ${id}"
  echo "    revision label : ${rev}"
  echo "    runtime user   : ${usr}"
  echo "    architecture   : ${arch}"
  if [[ "${rev}" != "${SHA}" ]]; then echo "FATAL: ${img} revision label != build SHA"; exit 3; fi
  if [[ "${usr}" != "10001:10001" && "${usr}" != "10001" ]]; then echo "FATAL: ${img} is not numeric non-root"; exit 3; fi
  if [[ "${arch}" != "amd64" ]]; then echo "FATAL: ${img} architecture is not amd64"; exit 3; fi
done
echo "[build] OK — both images tagged :${SHA}, labelled, numeric non-root, linux/amd64."
