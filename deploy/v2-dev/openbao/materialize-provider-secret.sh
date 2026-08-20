#!/usr/bin/env bash
# Materialize one approved runtime secret from OpenBao into the shared tmpfs.
# The identifier is non-secret; values and tokens never enter argv, logs, or shell history.
set -euo pipefail
umask 077

PROVIDER="${1:-}"
case "${PROVIDER}" in
  openrouter)
    KV_PATH="dev/providers/openrouter"
    OUT_NAME="openrouter_api_key"
    ;;
  groq)
    KV_PATH="dev/providers/groq"
    OUT_NAME="groq_api_key"
    ;;
  iam-session)
    KV_PATH="dev/iam/session"
    OUT_NAME="iam_session_secret"
    ;;
  *)
    printf '[runtime-secret-materialize] FATAL: identifier must be openrouter, groq, or iam-session\n' >&2
    exit 2
    ;;
esac

BAO_ADDR="${TANAGHOM_OPENBAO_ADDR:-http://127.0.0.1:18200}"
CUSTODY="${TANAGHOM_OPENBAO_CUSTODY:-/srv/tanaghom-dev/openbao/custody}"
ROLE_ID_FILE="${CUSTODY}/${PROVIDER}.role_id"
SECRET_ID_FILE="${CUSTODY}/${PROVIDER}.secret_id"
KV_MOUNT="${TANAGHOM_PROVIDER_KV_MOUNT:-tanaghom}"
KV_FIELD="${TANAGHOM_PROVIDER_KV_FIELD:-value}"
OUT_DIR="${TANAGHOM_SECRET_DIR:-/run/tanaghom-secrets}"
OUT_FILE="${OUT_DIR}/${OUT_NAME}"
OWNER_UID="${TANAGHOM_SECRET_UID:-10001}"
OWNER_GID="${TANAGHOM_SECRET_GID:-10001}"
MAX_BYTES=65536
CURL=(curl -sS -m 10 --fail-with-body)

log() { printf '[runtime-secret-materialize:%s] %s\n' "${PROVIDER}" "$*" >&2; }
die() { log "FATAL: $*"; exit 1; }

[[ "${EUID}" -eq 0 ]] || die "must run as root"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
[[ -r "${ROLE_ID_FILE}" && -r "${SECRET_ID_FILE}" ]] || die "AppRole custody files missing/unreadable"

for file in "${ROLE_ID_FILE}" "${SECRET_ID_FILE}"; do
  permissions="$(stat -c '%a %u %g' "${file}")" || die "cannot stat custody file"
  [[ "${permissions}" == "600 0 0" ]] || die "custody files must be root-owned 0600"
done

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

token_header() { printf 'X-Vault-Token: %s' "${token}"; }

value="$(
  "${CURL[@]}" -H @<(token_header) "${BAO_ADDR}/v1/${KV_MOUNT}/data/${KV_PATH}" \
    | python3 -c 'import json,sys; data=json.load(sys.stdin)["data"]["data"]; sys.stdout.write(data[sys.argv[1]])' "${KV_FIELD}"
)" || die "KV read failed"

[[ -n "${value}" ]] || die "fetched value is empty"
bytes="$(printf '%s' "${value}" | wc -c)"
[[ "${bytes}" -le "${MAX_BYTES}" ]] || die "fetched value exceeds ${MAX_BYTES} bytes"

"${CURL[@]}" -o /dev/null -X POST -H @<(token_header) "${BAO_ADDR}/v1/auth/token/revoke-self" \
  || die "token revoke-self failed; refusing to publish"
reuse_code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' -H @<(token_header) \
  "${BAO_ADDR}/v1/auth/token/lookup-self" || true)"
case "${reuse_code}" in
  401 | 403) : ;;
  *) die "revoked token was not denied on reuse (HTTP ${reuse_code}); refusing to publish" ;;
esac
token=""

install -d -m 0500 -o "${OWNER_UID}" -g "${OWNER_GID}" "${OUT_DIR}"
tmp="$(mktemp "${OUT_DIR}/.${OUT_NAME}.XXXXXX")" || die "mktemp failed"
cleanup() { rm -f "${tmp}" 2>/dev/null || true; }
trap cleanup EXIT
printf '%s' "${value}" > "${tmp}"
value=""
chown "${OWNER_UID}:${OWNER_GID}" "${tmp}"
chmod 0400 "${tmp}"
mv -f "${tmp}" "${OUT_FILE}"
trap - EXIT
log "published ${OUT_FILE}; token revoked and reuse denied"
