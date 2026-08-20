#!/usr/bin/env bash
# #389 (exact-head review hardening, round 2) — candidate-path image loader + provenance verifier. Runs on
# the deployment host FROM the candidate path (/srv/tanaghom-v2-dev), against the transferred immutable OCI
# archives + detached MANIFEST.txt written by deploy/v2-dev/stage.sh.
#
# Trust model (GPT corrections):
#   * EXTERNAL trust anchor — the archives and manifest travel together, so internal consistency is not
#     enough. An INDEPENDENTLY supplied expected MANIFEST.txt sha256 (V2DEV_EXPECTED_MANIFEST_SHA256, or
#     arg1) is required and verified BEFORE any Docker mutation. stage.sh emits this digest outside the
#     candidate directory as release evidence.
#   * WHOLE-MANIFEST grammar — exactly one `manifest_version 2`, one reviewed_sha, one frozen db_image, two
#     image records, the exact file records, and NO blank/comment/unknown/duplicate/trailing lines.
#   * EXACT filesystem structure — only the candidate root + ./images dir + the declared files may exist;
#     any other directory or entry type is rejected.
#   * STRICT records — typed fields; exact archive names; regular non-symlink files canonically under
#     ./images; every declared runtime-file hash verified; undeclared/missing/stale rejected.
#   * SAFE mutation — no ambiguous replacement of a pre-existing tag; ERR/INT/TERM/EXIT rollback traps
#     armed once loading begins remove ONLY references introduced by this invocation, disarmed only after
#     BOTH images are fully verified. Never pulls from a registry; touches no shared object.
#
# Usage:  V2DEV_EXPECTED_MANIFEST_SHA256=<64hex> ./load-images.sh      (or: ./load-images.sh <64hex>)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAN="${HERE}/MANIFEST.txt"
DB_IMAGE_LINE="db_image pgvector/pgvector:pg16@sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb"

fail() { echo "FATAL: $1" >&2; exit "${2:-3}"; }

# ---- manifest presence (regular, non-symlink) --------------------------------------------------------
[ -e "${MAN}" ] || fail "MANIFEST.txt not found beside load-images.sh" 2
[ -L "${MAN}" ] && fail "MANIFEST.txt is a symlink" 2
[ -f "${MAN}" ] || fail "MANIFEST.txt is not a regular file" 2

# ---- (1) EXTERNAL trust anchor: independently-supplied expected digest, verified before any mutation --
EXP="${V2DEV_EXPECTED_MANIFEST_SHA256:-${1:-}}"
[ -n "${EXP}" ] || fail "an independently-supplied expected MANIFEST sha256 is required (V2DEV_EXPECTED_MANIFEST_SHA256 or arg1)" 2
printf '%s' "${EXP}" | grep -Eq '^[0-9a-f]{64}$' || fail "expected manifest digest malformed" 2
GOT_MAN="$(sha256sum "${MAN}" | cut -d' ' -f1)"
[ "${GOT_MAN}" = "${EXP}" ] || fail "MANIFEST.txt digest (${GOT_MAN}) != independently-supplied expected digest; refusing before any Docker mutation"

# ---- (3) whole-manifest grammar ----------------------------------------------------------------------
nlines="$(grep -c '' "${MAN}" || true)"
allowed="$(grep -cE '^(manifest_version |reviewed_sha |db_image |image |file )' "${MAN}" || true)"
[ "${nlines}" = "${allowed}" ] || fail "manifest contains blank/comment/unknown/trailing lines"
# 22 = manifest_version + reviewed_sha + db_image + 2 image records + 17 runtime file records.
[ "${nlines}" = "22" ] || fail "manifest must contain exactly 22 records (got ${nlines})"
[ "$(grep -c '^manifest_version ' "${MAN}" || true)" = "1" ] || fail "manifest must have exactly one manifest_version line"
[ "$(grep '^manifest_version ' "${MAN}")" = "manifest_version 2" ] || fail "manifest_version must be exactly '2'"
[ "$(grep -c '^reviewed_sha ' "${MAN}" || true)" = "1" ] || fail "manifest must have exactly one reviewed_sha line"
[ "$(grep -c '^db_image ' "${MAN}" || true)" = "1" ] || fail "manifest must have exactly one db_image line"
[ "$(grep '^db_image ' "${MAN}")" = "${DB_IMAGE_LINE}" ] || fail "db_image is not the exact frozen pinned digest"
[ "$(grep -c '^image ' "${MAN}" || true)" = "2" ] || fail "manifest must have exactly two image records"
[ "$(grep -c '^file ' "${MAN}" || true)" = "17" ] || fail "manifest must declare exactly seventeen file records"
for svc in gateapi workbench; do
  c="$(grep -cE "^image ${svc} " "${MAN}" || true)"
  [ "${c}" = "1" ] || fail "manifest must have exactly one ${svc} image record (got ${c})"
done
SHA="$(grep '^reviewed_sha ' "${MAN}" | sed 's/^reviewed_sha //')"
printf '%s' "${SHA}" | grep -Eq '^[0-9a-f]{40}$' || fail "reviewed_sha is not a 40-char lowercase hex id"

GW_TAR_REL="./images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar"
WB_TAR_REL="./images/tanaghom-v2-dev-workbench-${SHA}.oci.tar"

# ---- (4) exact filesystem structure: only root + ./images + ./openbao dirs + declared files; nothing else
[ -n "$(find "${HERE}" -type l 2>/dev/null)" ] && fail "symlink present in candidate layout"
[ -L "${HERE}/images" ] && fail "images/ is a symlink"
[ -L "${HERE}/openbao" ] && fail "openbao/ is a symlink"
dirs="$(cd "${HERE}" && find . -mindepth 1 -type d | LC_ALL=C sort)"
[ "${dirs}" = "$(printf './images\n./openbao')" ] || fail "unexpected directory entries (only ./images and ./openbao allowed): ${dirs}"
others="$(cd "${HERE}" && find . -mindepth 1 ! -type f ! -type d)"
[ -z "${others}" ] || fail "unexpected non-file/non-directory entries: ${others}"
allfiles="$(cd "${HERE}" && find . -type f | LC_ALL=C sort)"
expfiles="$(printf '%s\n' "./MANIFEST.txt" "./.env.example" "./README.md" "./docker-compose.yml" "./load-images.sh" "${GW_TAR_REL}" "${WB_TAR_REL}" "./openbao/README.md" "./openbao/groq-policy.hcl" "./openbao/iam-session-policy.hcl" "./openbao/materialize-provider-secret.sh" "./openbao/materialize-reviewer-proxy.sh" "./openbao/openrouter-policy.hcl" "./openbao/reviewer-proxy-policy.hcl" "./openbao/tanaghom-provider-secret@.service" "./openbao/tanaghom-provider-secret@.timer" "./openbao/tanaghom-reviewer-proxy.service" "./openbao/tanaghom-reviewer-proxy.timer" | LC_ALL=C sort)"
[ "${allfiles}" = "${expfiles}" ] || fail "candidate layout differs from the exact allowed file set (stale/undeclared content)"
IMG_CANON="$(cd "${HERE}/images" && pwd -P)"

# ---- strict per-record field + canonical path validation --------------------------------------------
REC="$(mktemp)"
INTRODUCED=""; armed=0; cleaned=0
do_rollback() {
  [ "${armed}" = "1" ] || return 0
  for t in ${INTRODUCED}; do docker rmi "${t}" >/dev/null 2>&1 || true; done
}
# Idempotent candidate-only cleanup used by EXIT/ERR (and by the signal handlers before they terminate).
cleanup_once() {
  [ "${cleaned}" = "1" ] && return 0
  cleaned=1
  do_rollback
  rm -f "${REC}" 2>/dev/null || true
}
# (2) Dedicated signal handlers: roll back candidate-only, then TERMINATE with the signal status so
# execution cannot resume and perform further Docker mutation. EXIT/ERR cleanup stays idempotent.
on_int()  { cleanup_once; exit 130; }
on_term() { cleanup_once; exit 143; }
trap cleanup_once EXIT
trap cleanup_once ERR
trap on_int  INT
trap on_term TERM

validate_record() {
  svc="$1"
  line="$(grep -E "^image ${svc} " "${MAN}")"
  set -f; set -- ${line}; set +f
  [ "$#" -eq 9 ] || fail "${svc} image record malformed ($# fields, expected 9)"
  [ "$1" = "image" ] && [ "$2" = "${svc}" ] || fail "${svc} image record header malformed"
  case "$3" in tag=*)            TAG="${3#tag=}";;            *) fail "${svc} record missing tag=";; esac
  case "$4" in archive=*)        ARCH="${4#archive=}";;       *) fail "${svc} record missing archive=";; esac
  case "$5" in archive_sha256=*) ASH="${5#archive_sha256=}";; *) fail "${svc} record missing archive_sha256=";; esac
  case "$6" in image_id=*)       IID="${6#image_id=}";;       *) fail "${svc} record missing image_id=";; esac
  case "$7" in oci_manifest_digest=*) OMD="${7#oci_manifest_digest=}";; *) fail "${svc} record missing oci_manifest_digest=";; esac
  case "$8" in revision=*)       REV="${8#revision=}";;       *) fail "${svc} record missing revision=";; esac
  case "$9" in user=*)           USR="${9#user=}";;           *) fail "${svc} record missing user=";; esac
  [ "${TAG}" = "tanaghom-v2-dev-${svc}:${SHA}" ] || fail "${svc} tag != tanaghom-v2-dev-${svc}:<reviewed_sha>"
  [ "${ARCH}" = "images/tanaghom-v2-dev-${svc}-${SHA}.oci.tar" ] || fail "${svc} archive != exact expected name"
  printf '%s' "${ASH}" | grep -Eq '^[0-9a-f]{64}$' || fail "${svc} archive_sha256 malformed"
  printf '%s' "${IID}" | grep -Eq '^sha256:[0-9a-f]{64}$' || fail "${svc} image_id malformed"
  printf '%s' "${OMD}" | grep -Eq '^sha256:[0-9a-f]{64}$' || fail "${svc} oci_manifest_digest malformed"
  [ "${REV}" = "${SHA}" ] || fail "${svc} revision != reviewed_sha"
  printf '%s' "${USR}" | grep -Eq '^10001(:10001)?$' || fail "${svc} user is not numeric non-root 10001"
  tar="${HERE}/${ARCH}"
  [ -e "${tar}" ] || fail "${svc} archive missing: ${ARCH}"
  [ -L "${tar}" ] && fail "${svc} archive is a symlink: ${ARCH}"
  [ -f "${tar}" ] || fail "${svc} archive is not a regular file: ${ARCH}"
  pcanon="$(cd "$(dirname "${tar}")" && pwd -P)"
  [ "${pcanon}" = "${IMG_CANON}" ] || fail "${svc} archive escapes ./images (traversal): ${ARCH}"
  got_ash="$(sha256sum "${tar}" | cut -d' ' -f1)"
  [ "${got_ash}" = "${ASH}" ] || fail "${svc} archive sha256 mismatch (transfer/substitution): ${ARCH}"
  archive_omd="$(tar -xOf "${tar}" index.json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["manifests"]) == 1; print(d["manifests"][0]["digest"])')"
  [ "${archive_omd}" = "${OMD}" ] || fail "${svc} OCI manifest digest does not match archive index"
  printf '%s|%s|%s|%s|%s\n' "${svc}" "${TAG}" "${tar}" "${IID}" "${OMD}" >> "${REC}"
}
validate_record gateapi
validate_record workbench

# ---- every declared runtime file hash verified; declared set == the allowed files --------------------
ALLOWED="./.env.example
./README.md
./docker-compose.yml
./load-images.sh
${GW_TAR_REL}
${WB_TAR_REL}
./openbao/README.md
./openbao/groq-policy.hcl
./openbao/iam-session-policy.hcl
./openbao/materialize-provider-secret.sh
./openbao/materialize-reviewer-proxy.sh
./openbao/openrouter-policy.hcl
./openbao/reviewer-proxy-policy.hcl
./openbao/tanaghom-provider-secret@.service
./openbao/tanaghom-provider-secret@.timer
./openbao/tanaghom-reviewer-proxy.service
./openbao/tanaghom-reviewer-proxy.timer"
FL="$(mktemp)"; grep '^file ' "${MAN}" > "${FL}" || true
declared=""
while read -r _kw rel kv extra; do
  [ -z "${extra:-}" ] || fail "malformed file line: ${rel}"
  case "${kv}" in sha256=*) want="${kv#sha256=}";; *) fail "file line missing sha256= for ${rel}";; esac
  printf '%s' "${want}" | grep -Eq '^[0-9a-f]{64}$' || fail "file hash malformed for ${rel}"
  printf '%s\n' "${ALLOWED}" | grep -qxF "${rel}" || fail "manifest declares an unknown file: ${rel}"
  case "${declared}" in *"|${rel}|"*) fail "duplicate file declaration: ${rel}";; esac
  declared="${declared}|${rel}|"
  [ -f "${HERE}/${rel}" ] && [ ! -L "${HERE}/${rel}" ] || fail "declared file missing or symlink: ${rel}"
  got="$(cd "${HERE}" && sha256sum "${rel}" | cut -d' ' -f1)"
  [ "${got}" = "${want}" ] || fail "runtime file hash mismatch (tampered): ${rel}"
done < "${FL}"
rm -f "${FL}"
for rel in "./.env.example" "./README.md" "./docker-compose.yml" "./load-images.sh" "${GW_TAR_REL}" "${WB_TAR_REL}" \
           "./openbao/README.md" "./openbao/groq-policy.hcl" "./openbao/iam-session-policy.hcl" "./openbao/materialize-provider-secret.sh" \
           "./openbao/materialize-reviewer-proxy.sh" "./openbao/openrouter-policy.hcl" \
           "./openbao/reviewer-proxy-policy.hcl" "./openbao/tanaghom-provider-secret@.service" \
           "./openbao/tanaghom-provider-secret@.timer" \
           "./openbao/tanaghom-reviewer-proxy.service" "./openbao/tanaghom-reviewer-proxy.timer"; do
  case "${declared}" in *"|${rel}|"*) : ;; *) fail "manifest does not declare required file: ${rel}";; esac
done

# ---- ambiguity pre-check for BOTH tags BEFORE any load (no mutation on refusal) ----------------------
while IFS='|' read -r svc TAG tar IID OMD; do
  if docker image inspect "${TAG}" >/dev/null 2>&1; then
    pid="$(docker image inspect --format '{{.Id}}' "${TAG}")"
    [ "${pid}" = "${IID}" ] || [ "${pid}" = "${OMD}" ] || fail "ambiguous pre-existing tag ${TAG} points to a different image (${pid}); refusing to replace"
  fi
done < "${REC}"

# ---- (2) load + verify with rollback armed; disarm only after BOTH images verified -------------------
armed=1
while IFS='|' read -r svc TAG tar IID OMD; do
  pre="no"; docker image inspect "${TAG}" >/dev/null 2>&1 && pre="yes"
  # Track the ref as introduced BEFORE the load so a signal caught during the load still rolls it back
  # completely (rollback is idempotent / candidate-only).
  [ "${pre}" = "no" ] && INTRODUCED="${INTRODUCED} ${TAG}"
  echo "[load] loading ${svc}…"
  docker load -i "${tar}" >/dev/null
  got_id="$(docker inspect --format '{{.Id}}' "${TAG}" 2>/dev/null || echo MISSING)"
  got_rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${TAG}" 2>/dev/null || echo MISSING)"
  if { [ "${got_id}" != "${IID}" ] && [ "${got_id}" != "${OMD}" ]; } || [ "${got_rev}" != "${SHA}" ]; then
    fail "${TAG} post-load provenance mismatch (id=${got_id} rev=${got_rev}); rolling back only newly-introduced references"
  fi
  echo "[load] ${svc}: ${TAG} loaded; archive sha256 + daemon/config identity + revision label verified against MANIFEST"
done < "${REC}"
armed=0   # both images fully verified — disarm rollback

echo "[load] all transferred images loaded and provenance-verified (exactly gateapi + workbench); external manifest digest matched"
