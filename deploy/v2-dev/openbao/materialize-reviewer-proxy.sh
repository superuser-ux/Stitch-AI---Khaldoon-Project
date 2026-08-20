#!/usr/bin/env bash
# #387 — v2-dev host OpenBao materializer for REVIEWER_PROXY_SECRET (NON-SECRET adapter).
#
# This is the ONLY component that knows OpenBao/AppRole; the applications stay manager-neutral (they read
# a plain file via gates/reviewer_secret.py and the TS mirror). It:
#   1. reads a least-privilege AppRole RoleID/SecretID from a root-owned 0600 custody tree;
#   2. logs in over LOOPBACK OpenBao and fetches EXACTLY ONE KV-v2 value;
#   3. validates the value (non-empty, size-bounded);
#   4. REVOKES the fetched token (revoke-self) and PROVES token-reuse denial;
#   5. ONLY THEN atomically publishes the value to a tmpfs runtime path — a same-directory temp created
#      at the FINAL restrictive owner/mode BEFORE the rename, with an EXIT-trap cleanup.
# Publishes NOTHING unless revocation AND reuse-denial both succeed (revoke failure ⇒ no publish). Never
# prints the value or the token; no secret material ever enters argv, stdout, or shell history (tokens
# travel via stdin/process-substitution header files, never `-H "…: $token"` or `--data "$payload"`).
#
# It performs no product-authority, IAM, DB, or topology change. It is idempotent: each run re-materializes
# and advances mtime; a failed run leaves the previous published file untouched (apps fail closed after
# REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS if refreshes stop).
set -euo pipefail
umask 077

BAO_ADDR="${TANAGHOM_OPENBAO_ADDR:-http://127.0.0.1:18200}"
CUSTODY="${TANAGHOM_OPENBAO_CUSTODY:-/srv/tanaghom-dev/openbao/custody}"
ROLE_ID_FILE="${TANAGHOM_REVIEWER_ROLE_ID_FILE:-${CUSTODY}/reviewer-proxy.role_id}"
SECRET_ID_FILE="${TANAGHOM_REVIEWER_SECRET_ID_FILE:-${CUSTODY}/reviewer-proxy.secret_id}"
KV_MOUNT="${TANAGHOM_REVIEWER_KV_MOUNT:-tanaghom}"
KV_PATH="${TANAGHOM_REVIEWER_KV_PATH:-dev/reviewer-proxy}"
KV_FIELD="${TANAGHOM_REVIEWER_KV_FIELD:-value}"
OUT_DIR="${TANAGHOM_SECRET_DIR:-/run/tanaghom-secrets}"
OUT_FILE="${OUT_DIR}/reviewer_proxy_secret"
OWNER_UID="${TANAGHOM_SECRET_UID:-10001}"
OWNER_GID="${TANAGHOM_SECRET_GID:-10001}"
MAX_BYTES=65536
CURL=(curl -sS -m 10 --fail-with-body)

log() { printf '[materialize] %s\n' "$*" >&2; }   # non-secret status only
die() { log "FATAL: $*"; exit 1; }

[[ "${EUID}" -eq 0 ]] || die "must run as root"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
[[ -r "${ROLE_ID_FILE}" && -r "${SECRET_ID_FILE}" ]] || die "AppRole custody files missing/unreadable under ${CUSTODY}"

# custody must be root-owned 0600 (never group/world readable)
for f in "${ROLE_ID_FILE}" "${SECRET_ID_FILE}"; do
  perm="$(stat -c '%a %u %g' "${f}")" || die "cannot stat ${f}"
  [[ "${perm}" == "600 0 0" ]] || die "custody ${f} must be root-owned 0600 (got: ${perm})"
done

# --- AppRole login: payload built by python reading the FILES directly (paths are non-secret); the
#     secret_id is piped to curl via stdin (--data @-), never argv. The token is captured in memory. ---
token="$(
  python3 - "${ROLE_ID_FILE}" "${SECRET_ID_FILE}" <<'PY' \
    | "${CURL[@]}" -X POST --data @- "${BAO_ADDR}/v1/auth/approle/login" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth"]["client_token"])'
import json, sys
role = open(sys.argv[1]).read().strip()
sid = open(sys.argv[2]).read().strip()
sys.stdout.write(json.dumps({"role_id": role, "secret_id": sid}))
PY
)" || die "AppRole login failed"
[[ -n "${token}" ]] || die "empty client token from AppRole login"

# header file via process substitution so the token never appears in argv (visible in `ps`)
tokhdr() { printf 'X-Vault-Token: %s' "${token}"; }

# --- fetch EXACTLY one KV-v2 value ---
value="$(
  "${CURL[@]}" -H @<(tokhdr) "${BAO_ADDR}/v1/${KV_MOUNT}/data/${KV_PATH}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]["data"]; sys.stdout.write(d[sys.argv[1]])' "${KV_FIELD}"
)" || die "KV read failed for ${KV_MOUNT}/data/${KV_PATH}"

# --- validate (non-secret checks only) ---
[[ -n "${value}" ]] || die "fetched value is empty"
bytes="$(printf '%s' "${value}" | wc -c)"
[[ "${bytes}" -le "${MAX_BYTES}" ]] || die "fetched value exceeds ${MAX_BYTES} bytes"

# --- MANDATORY revoke-self, then PROVE reuse denial, BEFORE any publish ---
"${CURL[@]}" -o /dev/null -X POST -H @<(tokhdr) "${BAO_ADDR}/v1/auth/token/revoke-self" \
  || die "token revoke-self failed — refusing to publish"
reuse_code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' -H @<(tokhdr) \
  "${BAO_ADDR}/v1/auth/token/lookup-self" || true)"
case "${reuse_code}" in
  401 | 403) : ;;   # denied as required
  *) die "revoked token was NOT denied on reuse (HTTP ${reuse_code}) — refusing to publish" ;;
esac
token=""   # drop the (now-revoked) reference

# --- atomic publish to tmpfs: temp at FINAL owner/mode BEFORE same-dir rename; EXIT cleanup ---
install -d -m 0500 -o "${OWNER_UID}" -g "${OWNER_GID}" "${OUT_DIR}"
tmp="$(mktemp "${OUT_DIR}/.reviewer_proxy_secret.XXXXXX")" || die "mktemp failed in ${OUT_DIR}"
cleanup() { rm -f "${tmp}" 2>/dev/null || true; }
trap cleanup EXIT
printf '%s' "${value}" > "${tmp}"
value=""
chown "${OWNER_UID}:${OWNER_GID}" "${tmp}"
chmod 0400 "${tmp}"
mv -f "${tmp}" "${OUT_FILE}"   # atomic same-directory rename; final owner/mode already in place
trap - EXIT
log "published ${OUT_FILE} (owner ${OWNER_UID}:${OWNER_GID}, mode 0400); token revoked + reuse-denied"
