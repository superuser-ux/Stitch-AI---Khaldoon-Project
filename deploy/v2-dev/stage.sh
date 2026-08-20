#!/usr/bin/env bash
# #389 (exact-head review hardening) — assemble the SELF-CONTAINED candidate-path layout for
# /srv/tanaghom-v2-dev, off-host, from a clean reviewed checkout. Reviewed source/image provenance
# mechanism that makes the candidate path executable WITHOUT a repository checkout or repo build context.
#
# Hardened (GPT corrections 4–5): assembly happens in a FRESH temporary SIBLING directory; the publish
# target is rejected if it is a symlink or a non-empty directory; the exact allowlist is validated before
# publish; and only after all checks pass is the layout ATOMICALLY published (rename). The MANIFEST uses a
# DETACHED scheme — it is never hashed while being written; it declares the sha256 of every OTHER runtime
# file, plus the two image records (archive sha256 + image ID + OCI revision label + numeric user).
#
#   1. build both app images from the exact clean HEAD (deploy/v2-dev/build.sh — direct docker build);
#   2. export each to an IMMUTABLE OCI archive (`docker save`);
#   3. assemble ONLY the allowed runtime artifacts (runtime docker-compose.yml, load-images.sh, README.md,
#      .env.example, images/*.oci.tar) into the fresh sibling;
#   4. write the detached MANIFEST.txt; validate the exact allowlist (no symlinks, no extras/missing);
#   5. atomically publish to the target path.
#
# `docker load` restores each image with an identical image ID + config labels (a Docker invariant), so
# provenance survives transfer. Writes ONLY inside the sibling/target; NO VPS access, registry push, or
# host mutation. Secrets are never involved (GIT_SHA is not a secret).
#
# Usage:  deploy/v2-dev/stage.sh <full-40-char-sha> <staging-dir>
set -euo pipefail

SHA="${1:-${V2DEV_GIT_SHA:-}}"
STAGE="${2:-}"
fail() { echo "FATAL: $1" >&2; exit "${2:-3}"; }

if [ -z "${SHA}" ] || [ -z "${STAGE}" ]; then
  echo "usage: stage.sh <full-40-char-sha> <staging-dir>" >&2; exit 2
fi
printf '%s' "${SHA}" | grep -Eq '^[0-9a-f]{40}$' || fail "build SHA must be a full lowercase 40-char hex commit id; refusing '${SHA}'" 2

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- publish-target sanity (correction 4): never a symlink; if it exists it must be an empty dir -------
[ -L "${STAGE}" ] && fail "publish target is a symlink: ${STAGE}"
if [ -e "${STAGE}" ]; then
  [ -d "${STAGE}" ] || fail "publish target exists and is not a directory: ${STAGE}"
  [ -z "$(ls -A "${STAGE}" 2>/dev/null)" ] || fail "publish target is a non-empty directory: ${STAGE}"
fi
PARENT="$(cd "$(dirname "${STAGE}")" && pwd -P)"

GATEAPI="tanaghom-v2-dev-gateapi:${SHA}"
WORKBENCH="tanaghom-v2-dev-workbench:${SHA}"

# 1. build from the clean reviewed checkout (build.sh enforces clean tree + HEAD==SHA + provenance).
bash "${HERE}/build.sh" "${SHA}" >/dev/null

# ---- assemble into a FRESH temporary sibling ---------------------------------------------------------
WORK="$(mktemp -d "${PARENT}/.v2dev-stage.XXXXXX")"
cleanup_work() { [ -d "${WORK}" ] && rm -rf "${WORK}" || true; }
trap cleanup_work EXIT

mkdir -p "${WORK}/images"
cp "${HERE}/docker-compose.yml" "${WORK}/docker-compose.yml"
cp "${HERE}/load-images.sh"     "${WORK}/load-images.sh"
cp "${HERE}/README.md"          "${WORK}/README.md"
cp "${HERE}/.env.example"       "${WORK}/.env.example"
chmod 0750 "${WORK}/load-images.sh"

# #387 — the NON-SECRET OpenBao reviewer-proxy materializer + policy + units + README ship as reviewed
# package inputs in the candidate layout (manifest-hashed, allowlisted). They carry NO secret material
# (RoleID/SecretID/tokens/values live only in the root-only host custody tree, never here). The cutover
# copies these manifest-verified artifacts to the host OpenBao infra (/srv/tanaghom-dev/openbao +
# /etc/systemd/system); they are NOT executed from the app candidate path.
mkdir -p "${WORK}/openbao"
cp "${HERE}/openbao/materialize-reviewer-proxy.sh"   "${WORK}/openbao/materialize-reviewer-proxy.sh"
cp "${HERE}/openbao/reviewer-proxy-policy.hcl"       "${WORK}/openbao/reviewer-proxy-policy.hcl"
cp "${HERE}/openbao/tanaghom-reviewer-proxy.service" "${WORK}/openbao/tanaghom-reviewer-proxy.service"
cp "${HERE}/openbao/tanaghom-reviewer-proxy.timer"   "${WORK}/openbao/tanaghom-reviewer-proxy.timer"
cp "${HERE}/openbao/materialize-provider-secret.sh"  "${WORK}/openbao/materialize-provider-secret.sh"
cp "${HERE}/openbao/openrouter-policy.hcl"            "${WORK}/openbao/openrouter-policy.hcl"
cp "${HERE}/openbao/groq-policy.hcl"                  "${WORK}/openbao/groq-policy.hcl"
cp "${HERE}/openbao/iam-session-policy.hcl"           "${WORK}/openbao/iam-session-policy.hcl"
cp "${HERE}/openbao/tanaghom-provider-secret@.service" "${WORK}/openbao/tanaghom-provider-secret@.service"
cp "${HERE}/openbao/tanaghom-provider-secret@.timer"   "${WORK}/openbao/tanaghom-provider-secret@.timer"
cp "${HERE}/openbao/README.md"                       "${WORK}/openbao/README.md"
chmod 0750 "${WORK}/openbao/materialize-reviewer-proxy.sh"
chmod 0750 "${WORK}/openbao/materialize-provider-secret.sh"

# 2. export immutable OCI archives.
for pair in "gateapi:${GATEAPI}" "workbench:${WORKBENCH}"; do
  svc="${pair%%:*}"; img="${pair#*:}"
  docker save "${img}" -o "${WORK}/images/tanaghom-v2-dev-${svc}-${SHA}.oci.tar"
done

# 4a. detached MANIFEST: structured header + two image records (NEVER self-hashed).
MAN="${WORK}/MANIFEST.txt"
{
  echo "manifest_version 2"
  echo "reviewed_sha ${SHA}"
  echo "db_image pgvector/pgvector:pg16@sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb"
} > "${MAN}"
for pair in "gateapi:${GATEAPI}" "workbench:${WORKBENCH}"; do
  svc="${pair%%:*}"; img="${pair#*:}"
  tar="${WORK}/images/tanaghom-v2-dev-${svc}-${SHA}.oci.tar"
  arch_sha="$(sha256sum "${tar}" | cut -d' ' -f1)"
  img_id="$(docker inspect --format '{{.Id}}' "${img}")"
  oci_manifest="$(tar -xOf "${tar}" index.json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["manifests"]) == 1; print(d["manifests"][0]["digest"])')"
  rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${img}")"
  usr="$(docker inspect --format '{{.Config.User}}' "${img}")"
  [ "${rev}" = "${SHA}" ] || fail "${img} revision label != SHA"
  echo "image ${svc} tag=${img} archive=images/tanaghom-v2-dev-${svc}-${SHA}.oci.tar archive_sha256=${arch_sha} image_id=${img_id} oci_manifest_digest=${oci_manifest} revision=${rev} user=${usr}" >> "${MAN}"
done
# 4b. detached file hashes: every runtime file EXCEPT MANIFEST.txt (so the manifest is never self-hashed).
( cd "${WORK}" && find . -type f | grep -v '^\./MANIFEST\.txt$' | LC_ALL=C sort | while read -r f; do
    echo "file ${f} sha256=$(sha256sum "${f}" | cut -d' ' -f1)"
  done ) >> "${MAN}"

# 4c. validate the exact allowlist in WORK before publishing (no symlinks, exact runtime set).
[ -z "$(find "${WORK}" -type l 2>/dev/null)" ] || fail "symlink present in staged layout"
got="$(cd "${WORK}" && find . -type f | LC_ALL=C sort)"
exp="$(printf '%s\n' \
  "./.env.example" \
  "./MANIFEST.txt" \
  "./README.md" \
  "./docker-compose.yml" \
  "./images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar" \
  "./images/tanaghom-v2-dev-workbench-${SHA}.oci.tar" \
  "./load-images.sh" \
  "./openbao/README.md" \
  "./openbao/groq-policy.hcl" \
  "./openbao/iam-session-policy.hcl" \
  "./openbao/materialize-provider-secret.sh" \
  "./openbao/materialize-reviewer-proxy.sh" \
  "./openbao/openrouter-policy.hcl" \
  "./openbao/reviewer-proxy-policy.hcl" \
  "./openbao/tanaghom-provider-secret@.service" \
  "./openbao/tanaghom-provider-secret@.timer" \
  "./openbao/tanaghom-reviewer-proxy.service" \
  "./openbao/tanaghom-reviewer-proxy.timer" | LC_ALL=C sort)"
[ "${got}" = "${exp}" ] || fail "staged layout != exact allowed file set:"$'\n'"${got}"

# 5. atomically publish only after all checks pass.
if [ -e "${STAGE}" ]; then rmdir "${STAGE}" || fail "publish target not empty at publish time: ${STAGE}"; fi
mv "${WORK}" "${STAGE}"
trap - EXIT

# 6. EXTERNAL trust anchor (GPT correction): emit the final MANIFEST.txt sha256 as release evidence
# OUTSIDE the candidate directory. It is carried out-of-band and supplied to load-images.sh
# (V2DEV_EXPECTED_MANIFEST_SHA256), which verifies it before any Docker mutation — so a self-consistent
# archive+manifest rewrite that travels inside the candidate dir is still rejected.
MAN_SHA="$(sha256sum "${STAGE}/MANIFEST.txt" | cut -d' ' -f1)"
printf '%s' "${MAN_SHA}" > "${STAGE}.manifest.sha256"

echo "[stage] candidate-path layout published at ${STAGE}"
echo "[stage] allowed files: docker-compose.yml load-images.sh README.md .env.example MANIFEST.txt images/*.oci.tar openbao/{reviewer-proxy,provider-secret adapters+policies+units,README.md}"
echo "[stage] MANIFEST_SHA256=${MAN_SHA}"
echo "[stage] external trust anchor written outside the candidate dir: ${STAGE}.manifest.sha256"
