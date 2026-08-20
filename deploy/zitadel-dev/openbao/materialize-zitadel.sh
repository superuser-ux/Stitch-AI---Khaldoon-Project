#!/usr/bin/env bash
set -euo pipefail
umask 077

BAO_ADDR="${TANAGHOM_OPENBAO_ADDR:-http://127.0.0.1:18200}"
CUSTODY="${TANAGHOM_ZITADEL_CUSTODY:-/srv/tanaghom-zitadel/openbao/custody}"
ROLE_ID_FILE="${CUSTODY}/role_id"
SECRET_ID_FILE="${CUSTODY}/secret_id"
OUT_DIR="${TANAGHOM_ZITADEL_SECRET_DIR:-/run/tanaghom-zitadel}"
CURL=(curl -sS -m 10 --fail-with-body)
token=""
stage=""
generation=""

log() { printf '[zitadel-materialize] %s\n' "$*" >&2; }
die() { log "FATAL: $*"; exit 1; }

revoke() {
  if [[ -n "${token}" ]]; then
    "${CURL[@]}" -o /dev/null -X POST -H @<(printf 'X-Vault-Token: %s' "${token}") \
      "${BAO_ADDR}/v1/auth/token/revoke-self" >/dev/null 2>&1 || true
    token=""
  fi
}
cleanup() {
  revoke
  [[ -z "${stage}" ]] || rm -rf "${stage}"
  rm -f "${OUT_DIR}/.current.new"
  if [[ -n "${generation}" ]]; then
    active=""
    [[ ! -L "${OUT_DIR}/current" ]] || active="$(readlink "${OUT_DIR}/current")"
    [[ "${active}" == "$(basename "${generation}")" ]] || rm -rf "${generation}"
  fi
}
trap cleanup EXIT

[[ "${EUID}" -eq 0 ]] || die "must run as root"
for command in curl python3 stat; do command -v "${command}" >/dev/null || die "${command} is required"; done
for file in "${ROLE_ID_FILE}" "${SECRET_ID_FILE}"; do
  [[ -f "${file}" && ! -L "${file}" && -r "${file}" ]] || die "custody file missing or unsafe"
  [[ "$(stat -c '%a %u %g' "${file}")" == "600 0 0" ]] || die "custody files must be root:root 0600"
done

token="$(
  python3 - "${ROLE_ID_FILE}" "${SECRET_ID_FILE}" <<'PY' \
    | "${CURL[@]}" -X POST --data @- "${BAO_ADDR}/v1/auth/approle/login" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth"]["client_token"])'
import json, sys
with open(sys.argv[1], encoding="utf-8") as role, open(sys.argv[2], encoding="utf-8") as secret:
    print(json.dumps({"role_id": role.read().strip(), "secret_id": secret.read().strip()}))
PY
)" || die "AppRole login failed"
[[ -n "${token}" ]] || die "OpenBao returned an empty token"

fetch() {
  local path="$1"
  "${CURL[@]}" -H @<(printf 'X-Vault-Token: %s' "${token}") \
    "${BAO_ADDR}/v1/tanaghom/data/dev/zitadel/${path}" \
    | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin)["data"]["data"]["value"])'
}

masterkey="$(fetch masterkey)" || die "masterkey fetch failed"
postgres_password="$(fetch postgres)" || die "PostgreSQL password fetch failed"
admin_password="$(fetch bootstrap-admin)" || die "bootstrap-admin password fetch failed"

[[ "${#masterkey}" -eq 32 ]] || die "masterkey must be exactly 32 characters"
[[ "${#postgres_password}" -ge 24 ]] || die "PostgreSQL password is too short"
[[ "${#admin_password}" -ge 12 ]] || die "bootstrap-admin password is too short"
[[ "${admin_password}" =~ [A-Z] && "${admin_password}" =~ [a-z] && "${admin_password}" =~ [0-9] && "${admin_password}" =~ [^a-zA-Z0-9] ]] \
  || die "bootstrap-admin password does not meet complexity requirements"

"${CURL[@]}" -o /dev/null -X POST -H @<(printf 'X-Vault-Token: %s' "${token}") \
  "${BAO_ADDR}/v1/auth/token/revoke-self" || die "token revocation failed"
reuse_code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' \
  -H @<(printf 'X-Vault-Token: %s' "${token}") "${BAO_ADDR}/v1/auth/token/lookup-self" || true)"
case "${reuse_code}" in 401|403) : ;; *) die "revoked token reuse was not denied" ;; esac
token=""

install -d -m 0500 -o root -g root "${OUT_DIR}"
stage="$(mktemp -d "${OUT_DIR}/.generation.XXXXXX")"
chmod 0700 "${stage}"
printf '%s' "${masterkey}" > "${stage}/masterkey"
printf '%s' "${postgres_password}" > "${stage}/postgres_password"

printf '%s' "${postgres_password}" | python3 -c '
import json, sys
password = sys.stdin.read()
with open(sys.argv[1], "w", encoding="utf-8") as out:
    out.write("Database:\n  postgres:\n    User:\n      Username: zitadel\n      Password: ")
    out.write(json.dumps(password))
    out.write("\n    Admin:\n      Username: postgres\n      Password: ")
    out.write(json.dumps(password))
    out.write("\n")
' "${stage}/zitadel-secrets.yaml"

printf '%s' "${admin_password}" | python3 -c '
import json, sys
password = sys.stdin.read()
with open(sys.argv[1], "w", encoding="utf-8") as out:
    out.write("FirstInstance:\n  InstanceName: Tanaghom DEV\n  TrustedDomains:\n    - iam.localhost\n")
    out.write("  LoginClientPatPath: /zitadel/bootstrap/login-client.pat\n")
    out.write("  Org:\n    Name: Tanaghom DEV\n    Human:\n      UserName: zitadel-admin\n")
    out.write("      FirstName: Tanaghom\n      LastName: Administrator\n      Password: ")
    out.write(json.dumps(password))
    out.write("\n      PasswordChangeRequired: true\n")
    out.write("    LoginClient:\n      Machine:\n        Username: login-client\n")
    out.write("        Name: Tanaghom DEV Login Client\n      Pat:\n        ExpirationDate: 2099-01-01T00:00:00Z\n")
' "${stage}/first-instance-steps.yaml"

masterkey="" postgres_password="" admin_password=""
for file in masterkey postgres_password zitadel-secrets.yaml first-instance-steps.yaml; do
  chown root:root "${stage}/${file}"
  chmod 0400 "${stage}/${file}"
done
now="$(date +%s)"
for file in masterkey postgres_password zitadel-secrets.yaml first-instance-steps.yaml; do
  meta="$(stat -c '%a %u %g %Y' "${stage}/${file}")"
  read -r mode uid gid mtime <<<"${meta}"
  [[ "${mode} ${uid} ${gid}" == "400 0 0" ]] || die "staged file metadata is unsafe"
  (( mtime <= now + 30 && now - mtime <= 60 )) || die "staged file timestamp is stale or future-dated"
done

# A single symlink rename activates all four files. Until this point the prior generation remains active;
# interruption cannot expose a mixed generation or advance any active file mtime.
generation="${OUT_DIR}/generation-$(date -u +%Y%m%dT%H%M%SZ)-${stage##*.generation.}"
mv "${stage}" "${generation}"
stage=""
chmod 0500 "${generation}"
previous=""
if [[ -L "${OUT_DIR}/current" ]]; then
  previous="$(readlink "${OUT_DIR}/current")"
  [[ "${previous}" =~ ^generation-[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9]+$ && -d "${OUT_DIR}/${previous}" ]] \
    || die "active generation link is unsafe"
elif [[ -e "${OUT_DIR}/current" ]]; then
  die "active generation path is not a symlink"
fi
rm -f "${OUT_DIR}/.current.new"
ln -s "$(basename "${generation}")" "${OUT_DIR}/.current.new"

for old in "${OUT_DIR}"/generation-*; do
  [[ -d "${old}" ]] || continue
  base="$(basename "${old}")"
  [[ "${base}" == "$(basename "${generation}")" || "${base}" == "${previous}" ]] || rm -rf "${old}"
done
log "activating one validated four-file root-only tmpfs generation; token revoked and reuse denied"

# The exchange is the final fallible operation. No cleanup can convert a successful activation into
# a failed refresh after active mtimes advance.
if mv -Tf "${OUT_DIR}/.current.new" "${OUT_DIR}/current"; then
  generation=""
  trap - EXIT
  exit 0
fi
die "atomic generation activation failed"
