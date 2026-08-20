#!/usr/bin/env bash
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOURNAL="${HERE}/.provision-journal"
OPERATOR_ENV=/srv/tanaghom-dev/openbao/custody/operator.env
SNAPSHOT_DIR=/srv/tanaghom-dev/openbao/snapshots
[[ "${EUID}" -eq 0 ]] || { echo "FATAL: run provision with sudo" >&2; exit 2; }
[[ ! -e "${JOURNAL}" ]] || { echo "FATAL: provision journal already exists" >&2; exit 3; }
complete=0
partial_snapshot=""
cleanup_on_failure() {
  status=$?
  trap - EXIT INT TERM
  [[ -z "${partial_snapshot}" ]] || rm -f "${partial_snapshot}"
  if [[ "${complete}" == 0 && -f "${JOURNAL}" ]]; then
    BAO_TOKEN=""
    if ! "${HERE}/rollback.sh" >/dev/null 2>&1; then
      echo "FATAL: exact compensation failed; retain evidence and stop" >&2
      status=70
    fi
  fi
  exit "${status}"
}
trap cleanup_on_failure EXIT
trap 'exit 130' INT TERM

# shellcheck disable=SC1090
source "${OPERATOR_ENV}"
[[ -n "${BAO_ADDR:-}" && -n "${BAO_TOKEN:-}" ]] || { echo "FATAL: OpenBao operator custody unavailable" >&2; exit 3; }
header() { printf 'X-Vault-Token: %s' "${BAO_TOKEN}"; }
api() { curl -sS -m 15 --fail-with-body -H @<(header) "$@"; }
mark() { printf '%s\n' "$1" >> "${JOURNAL}"; }

printf 'started_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${JOURNAL}"
chmod 0600 "${JOURNAL}"
snapshot="${SNAPSHOT_DIR}/zitadel-pilot-$(date -u +%Y%m%dT%H%M%SZ).snap"
partial_snapshot="${snapshot}.partial.$$"
api "${BAO_ADDR}/v1/sys/storage/raft/snapshot" > "${partial_snapshot}"
chmod 0600 "${partial_snapshot}"
mv "${partial_snapshot}" "${snapshot}"
partial_snapshot=""
mark "snapshot=${snapshot}"

readarray -t generated < <(python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(32)))
print("".join(secrets.choice(alphabet) for _ in range(36)))
print("Aa1!" + "".join(secrets.choice(alphabet) for _ in range(32)))
PY
)
masterkey="${generated[0]}"
postgres_password="${generated[1]}"
admin_password="${generated[2]}"
unset generated

write_secret() {
  local path="$1" value="$2"
  mark "kv=${path}"
  printf '%s' "${value}" \
    | python3 -c 'import json,sys; print(json.dumps({"data": {"value": sys.stdin.read()}}))' \
    | api -X POST --data @- "${BAO_ADDR}/v1/tanaghom/data/dev/zitadel/${path}" >/dev/null
}
write_secret masterkey "${masterkey}"
write_secret postgres "${postgres_password}"
write_secret bootstrap-admin "${admin_password}"
masterkey="" postgres_password="" admin_password=""

mark "policy=tanaghom-zitadel-dev"
python3 - "${HERE}/openbao/zitadel-policy.hcl" <<'PY' | api -X PUT --data @- "${BAO_ADDR}/v1/sys/policies/acl/tanaghom-zitadel-dev" >/dev/null
import json, sys
with open(sys.argv[1], encoding="utf-8") as policy:
    print(json.dumps({"policy": policy.read()}))
PY

mark "approle=tanaghom-zitadel-dev"
printf '%s' '{"token_policies":["tanaghom-zitadel-dev"],"token_ttl":"5m","token_max_ttl":"5m","token_num_uses":10,"secret_id_num_uses":0}' \
  | api -X POST --data @- "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev" >/dev/null

mark "custody=created"
install -d -m 0700 -o root -g root "${HERE}/openbao/custody"
api "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev/role-id" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["role_id"])' > "${HERE}/openbao/custody/role_id"
api -X POST "${BAO_ADDR}/v1/auth/approle/role/tanaghom-zitadel-dev/secret-id" \
  | python3 -c 'import json,sys; data=json.load(sys.stdin)["data"]; print(data["secret_id"]); open(sys.argv[1], "w", encoding="utf-8").write(data["secret_id_accessor"])' \
      "${HERE}/.secret-accessor" > "${HERE}/openbao/custody/secret_id"
chmod 0600 "${HERE}/openbao/custody/role_id" "${HERE}/openbao/custody/secret_id" "${HERE}/.secret-accessor"
mark "secret_accessor=$(cat "${HERE}/.secret-accessor")"
rm -f "${HERE}/.secret-accessor"

mark "units=created"
install -m 0644 -o root -g root "${HERE}/openbao/tanaghom-zitadel-secrets.service" /etc/systemd/system/tanaghom-zitadel-secrets.service
install -m 0644 -o root -g root "${HERE}/openbao/tanaghom-zitadel-secrets.timer" /etc/systemd/system/tanaghom-zitadel-secrets.timer
systemctl daemon-reload
mark "runtime=created"
systemctl start tanaghom-zitadel-secrets.service
mark "timer=enabled"
systemctl enable --now tanaghom-zitadel-secrets.timer >/dev/null
BAO_TOKEN=""
complete=1
trap - EXIT INT TERM
echo "PROVISION_VERDICT=PASS snapshot=${snapshot}"
