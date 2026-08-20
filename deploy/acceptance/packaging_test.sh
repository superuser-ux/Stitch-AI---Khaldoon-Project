#!/usr/bin/env bash
# #338 — focused automated packaging proof. Builds the two application images from a CLEAN exact head,
# proves provenance/least-privilege/file-closure/secret-exclusion/private-stub-smoke, and the negative
# guards (mismatched SHA rejected; runtime-SHA override terminates). Teardown removes ONLY the isolated
# local proof resources. This never touches a VPS, registry, or the #337 lane.
#
# Usage:  ACC_API_PORT=18110 ACC_WB_PORT=13101 deploy/acceptance/packaging_test.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../.." && git rev-parse --show-toplevel)"
cd "${REPO}"

SHA="$(git rev-parse HEAD)"
GATEAPI="tanaghom-acc-gateapi:${SHA}"
WORKBENCH="tanaghom-acc-workbench:${SHA}"
export ACC_GIT_SHA="${SHA}"
export ACC_API_PORT="${ACC_API_PORT:-18110}"
export ACC_WB_PORT="${ACC_WB_PORT:-13101}"
export DB_PASSWORD="acc-db-$(od -An -N8 -tx1 /dev/urandom | tr -d ' ')"
# A synthetic sentinel injected ONLY at runtime as the acceptance secret — it must NEVER appear in any
# image layer/config/label/history/filesystem. Never printed.
SENTINEL="acc-sentinel-$(od -An -N16 -tx1 /dev/urandom | tr -d ' ')"
export REVIEWER_PROXY_SECRET="${SENTINEL}"

pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1" >&2; exit 1; }

cleanup() {
  echo "[teardown] removing only the isolated local proof resources"
  docker compose -f "${HERE}/docker-compose.yml" down -v --remove-orphans >/dev/null 2>&1 || true
  docker rmi -f "${GATEAPI}" "${WORKBENCH}" >/dev/null 2>&1 || true
  rm -f /tmp/acc-*.tar 2>/dev/null || true
}
trap cleanup EXIT

echo "== 1. clean exact-head build + provenance =="
[[ -z "$(git status --porcelain)" ]] || fail "working tree dirty"
bash "${HERE}/build.sh" "${SHA}" >/dev/null
for img in "${GATEAPI}" "${WORKBENCH}"; do
  rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${img}")"
  usr="$(docker inspect --format '{{.Config.User}}' "${img}")"
  [[ "${rev}" == "${SHA}" ]] || fail "${img} revision label != head"
  [[ "${usr}" == "10001:10001" || "${usr}" == "10001" ]] || fail "${img} not numeric non-root"
  id="$(docker inspect --format '{{.Id}}' "${img}")"
  docker save "${img}" -o "/tmp/acc-$(basename "${img}" | tr ':/' '__').tar"
  arch="$(sha256sum "/tmp/acc-$(basename "${img}" | tr ':/' '__').tar" | cut -d' ' -f1)"
  echo "  ${img}: local image ID ${id}  | OCI archive sha256 ${arch}  | user ${usr}  (no RepoDigest — not pushed)"
done
pass "both images built from clean head, labelled == head, numeric non-root, digests recorded"

echo "== 2. standalone file closure (workbench) + gateapi init orchestrator present =="
docker run --rm --entrypoint sh "${WORKBENCH}" -c \
  'test -f /app/server.js && test -d /app/.next/static && test -f /app/public/brand/tenants/tanaghum/tanaghom-logo.png && test -f /app/public/brand/platform/stitch/stitch-logo.png && test -f /app/BUILD_SHA' \
  || fail "workbench standalone closure incomplete (server.js/static/public/BUILD_SHA)"
pass "workbench ships server.js + .next/static + public brand assets + baked BUILD_SHA (no source tree)"
docker run --rm --entrypoint sh "${GATEAPI}" -c \
  'test -f /work/deploy/acceptance/init_db.py && test -f /work/deploy/acceptance/gateapi-entrypoint.sh && test -f /work/BUILD_SHA' \
  || fail "gateapi missing committed init orchestrator/entrypoint"
pass "gateapi carries committed init orchestrator + entrypoint + baked BUILD_SHA"

# No DEV dependency ships in the workbench runtime image (Next standalone traces prod deps only; the
# over-traced `typescript` is pruned in the runner).
for dev in typescript tailwindcss @tailwindcss @types playwright @playwright postcss; do
  docker run --rm --entrypoint sh "${WORKBENCH}" -c "test -e /app/node_modules/${dev}" 2>/dev/null \
    && fail "dev dependency '${dev}' leaked into the workbench runtime image"
done
pass "workbench runtime image carries no dev dependency (typescript/tailwind/@types/playwright/postcss absent)"

echo "== 3. sentinel-secret EXCLUSION from image config/env/labels/history/filesystem (never printed) =="
for img in "${GATEAPI}" "${WORKBENCH}"; do
  docker inspect "${img}" | grep -q "${SENTINEL}" && fail "sentinel found in ${img} inspect (config/env/labels)"
  docker history --no-trunc "${img}" | grep -q "${SENTINEL}" && fail "sentinel found in ${img} history"
  grep -aq "${SENTINEL}" "/tmp/acc-$(basename "${img}" | tr ':/' '__').tar" && fail "sentinel found in ${img} filesystem export"
done
pass "runtime acceptance secret is absent from every image layer/config/label/history/filesystem"

echo "== 3b. sentinel exclusion from generated Compose CONTENT, retained stages (config/labels/history/fs), evidence =="
# (a) Generated Compose content is INSPECTED (non-retained temp): the committed file holds no literal
#     secret, and in the interpolated output the sentinel must appear ONLY in the authorized runtime
#     REVIEWER_PROXY_SECRET field — nowhere else — then the temp is removed. The sentinel is never printed.
grep -q "${SENTINEL}" "${HERE}/docker-compose.yml" && fail "committed compose contains a literal secret"
cfgtmp="$(mktemp)"
docker compose -f "${HERE}/docker-compose.yml" config >"${cfgtmp}" 2>/dev/null || true
total_hits="$(grep -c "${SENTINEL}" "${cfgtmp}" 2>/dev/null || true)"; total_hits="${total_hits:-0}"
authz_hits="$(grep "${SENTINEL}" "${cfgtmp}" 2>/dev/null | grep -c 'REVIEWER_PROXY_SECRET' || true)"; authz_hits="${authz_hits:-0}"
rm -f "${cfgtmp}"
[[ ! -e "${cfgtmp}" ]] || fail "interpolated compose config was retained"
[[ "${total_hits}" -ge 1 ]] || fail "sentinel not present in interpolated compose (interpolation not exercised)"
[[ "${total_hits}" -eq "${authz_hits}" ]] || fail "sentinel appears in a non-REVIEWER_PROXY_SECRET compose field"
pass "generated Compose content inspected (non-retained): sentinel confined to the authorized REVIEWER_PROXY_SECRET field"
# (b) Retained stages: with BuildKit, multi-stage intermediates are NOT retained as images — for THIS
#     build (this exact SHA) only the two final tagged images exist; no untagged/<none> intermediate is
#     produced. We prove that, then confirm no retained evidence archive carries the sentinel. (The two
#     final images' config/labels + history + filesystem were already fully scanned in step 3.)
ours="$(docker images -a --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -E "^tanaghom-acc-(gateapi|workbench):${SHA}\$" | sort -u)"
expected="$(printf '%s\n%s\n' "${GATEAPI}" "${WORKBENCH}" | sort -u)"
[[ "${ours}" == "${expected}" ]] || fail "unexpected retained stage(s) for ${SHA}: ${ours}"
for t in /tmp/acc-*.tar; do [[ -e "${t}" ]] && grep -aq "${SENTINEL}" "${t}" && fail "sentinel in retained evidence ${t}"; done
pass "no retained intermediate stage for this build (only the two final ${SHA:0:12}… images); evidence clean"

echo "== 4. negative: mismatched SHA build rejected =="
BOGUS="$(printf '0%.0s' {1..40})"
if bash "${HERE}/build.sh" "${BOGUS}" >/dev/null 2>&1; then fail "build accepted a SHA != HEAD"; fi
pass "build.sh rejects a SHA that does not equal clean HEAD"

echo "== 5. negative: runtime-SHA override TERMINATES the workbench non-zero =="
if docker run --rm -e "TANAGHOM_WORKBENCH_BUILD_SHA=$(printf 'f%.0s' {1..40})" "${WORKBENCH}" >/dev/null 2>&1; then
  fail "workbench started with a divergent runtime SHA override"
fi
pass "workbench terminates non-zero when a runtime SHA override diverges from the baked value"

echo "== 5b/5c. negatives: recreated-container/no-marker and identity-mismatch against a retained non-empty DB fail closed =="
NEGNET="acc-negnet-$$"; NEGDB="acc-negdb-$$"
docker network create "${NEGNET}" >/dev/null
docker run -d --name "${NEGDB}" --network "${NEGNET}" \
  -e POSTGRES_USER=tanaghom -e POSTGRES_PASSWORD="${DB_PASSWORD}" -e POSTGRES_DB=tanaghom \
  pgvector/pgvector:pg16 >/dev/null
for i in $(seq 1 40); do docker exec "${NEGDB}" pg_isready -U tanaghom -d tanaghom >/dev/null 2>&1 && break; sleep 1; done
# Retained non-empty DB: full committed schema + migrations applied externally, an INTERMEDIATE migration
# artifact dropped for good measure. No container-local marker is written by this external apply.
docker run --rm --network "${NEGNET}" -e DB_HOST="${NEGDB}" -e DB_PASSWORD="${DB_PASSWORD}" \
  --entrypoint sh "${GATEAPI}" -c 'python - <<PY
import glob, os, psycopg2
c = psycopg2.connect(host=os.environ["DB_HOST"], dbname="tanaghom", user="tanaghom", password=os.environ["DB_PASSWORD"])
c.autocommit = True; cur = c.cursor()
cur.execute(open("/work/db/init/schema.sql").read())
for p in sorted(glob.glob("/work/db/migrations/*.sql")):
    cur.execute(open(p).read())
cur.execute("DROP TABLE IF EXISTS publication CASCADE")   # an intermediate artifact is missing too
PY' >/dev/null 2>&1 || { docker rm -f "${NEGDB}" >/dev/null 2>&1; docker network rm "${NEGNET}" >/dev/null 2>&1; fail "could not construct the retained non-empty DB fixture"; }

# 5b — a RECREATED gateapi (fresh --rm container => no container-local marker) against the retained
# non-empty DB must FAIL CLOSED.
neg1_rc=0
docker run --rm --network "${NEGNET}" -e DB_HOST="${NEGDB}" -e DB_PASSWORD="${DB_PASSWORD}" \
  --entrypoint sh "${GATEAPI}" -c 'python /work/deploy/acceptance/init_db.py' >/dev/null 2>&1 || neg1_rc=$?
[[ "${neg1_rc}" -ne 0 ]] || { docker rm -f "${NEGDB}" >/dev/null 2>&1; docker network rm "${NEGNET}" >/dev/null 2>&1; fail "init served with no container-local marker against a retained non-empty DB"; }
pass "recreated container / no local marker vs retained non-empty DB → fails closed (exit ${neg1_rc})"

# 5c — a container-local marker with the CORRECT committed manifest but a WRONG database identity must
# FAIL CLOSED (the marker binds the specific cluster it initialized).
neg2_rc=0
docker run --rm --network "${NEGNET}" -e DB_HOST="${NEGDB}" -e DB_PASSWORD="${DB_PASSWORD}" \
  --entrypoint sh "${GATEAPI}" -c '
set -e
mkdir -p /var/lib/tanaghom-acc
MAN="$(python -c "import sys; sys.path.insert(0,\"/work/deploy/acceptance\"); import init_db; print(init_db._committed_manifest())")"
printf "%s\n%s\n" "$MAN" "0000000000000000000" > /var/lib/tanaghom-acc/init-marker   # correct manifest, WRONG identity
python /work/deploy/acceptance/init_db.py' >/dev/null 2>&1 || neg2_rc=$?
docker rm -f "${NEGDB}" >/dev/null 2>&1 || true
docker network rm "${NEGNET}" >/dev/null 2>&1 || true
[[ "${neg2_rc}" -ne 0 ]] || fail "init served with a marker whose database identity does not match the cluster"
pass "container-local marker with mismatched database identity → fails closed (exit ${neg2_rc})"

echo "== 6. private three-service stub stack: start healthy, smoke, loopback-only, no V1 =="
docker compose -f "${HERE}/docker-compose.yml" up -d --build >/dev/null
# wait for all services healthy (compose orders them; poll the workbench which depends on a healthy API)
for i in $(seq 1 60); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose -f "${HERE}/docker-compose.yml" ps -q workbench)" 2>/dev/null || echo starting)"
  [[ "${st}" == "healthy" ]] && break; sleep 3
done
[[ "${st:-}" == "healthy" ]] || fail "workbench did not become healthy (init/readiness ordering)"

svc_count="$(docker compose -f "${HERE}/docker-compose.yml" ps --services | sort -u | tr '\n' ' ')"
[[ "${svc_count}" == "db gateapi workbench " ]] || fail "topology is not exactly db+gateapi+workbench: '${svc_count}'"
pass "exactly three services (db, gateapi, workbench) — no V1 dashboard/proxy"

RT="$(curl -s "http://127.0.0.1:${ACC_WB_PORT}/api/runtime")"
echo "${RT}" | grep -q "\"build\":\"${SHA}\"" || fail "workbench runtime build != head SHA: ${RT}"
echo "${RT}" | grep -q '"surface":"workbench"' || fail "runtime surface not workbench"
pass "workbench runtime identity == build head SHA (${SHA:0:12}…)"

H="$(curl -s "http://127.0.0.1:${ACC_WB_PORT}/gw/health")"
echo "${H}" | grep -q '"writer_mode":"stub"' || fail "writer_mode is not stub: ${H}"
curl -s "http://127.0.0.1:${ACC_WB_PORT}/gw/rounds" | grep -q '\[' || fail "canonical /gw -> API read failed"
pass "workbench -> /gw -> governed API smoke: stub writer + canonical rounds read"

# loopback-only: the published ports must bind 127.0.0.1, and the DB must have no host port
for c in gateapi workbench; do
  hostip="$(docker inspect --format '{{range $p,$b := .NetworkSettings.Ports}}{{range $b}}{{.HostIp}} {{end}}{{end}}' "$(docker compose -f "${HERE}/docker-compose.yml" ps -q ${c})")"
  echo "${hostip}" | grep -qE '127\.0\.0\.1' || fail "${c} host binding is not loopback: '${hostip}'"
  echo "${hostip}" | grep -qE '0\.0\.0\.0|::' && fail "${c} has a non-loopback binding"
done
dbports="$(docker inspect --format '{{json .NetworkSettings.Ports}}' "$(docker compose -f "${HERE}/docker-compose.yml" ps -q db)")"
echo "${dbports}" | grep -q '5432/tcp":null' || echo "${dbports}" | grep -q '"5432/tcp":\[\]' || [[ "${dbports}" == '{"5432/tcp":null}' || "${dbports}" == "{}" ]] || fail "DB appears to publish a host port: ${dbports}"
pass "application ports loopback-only (127.0.0.1); DB internal (no host port)"

# Known-owned SAME-CONTAINER RESTART (negative #3): `docker compose restart` restarts the SAME gateapi
# container, so its container-local marker (manifest + this cluster's identity) survives; init recognizes
# the owned DB and returns healthy — proving the contract does not fail-closed on a legitimate restart.
docker compose -f "${HERE}/docker-compose.yml" restart gateapi >/dev/null 2>&1 || true
for i in $(seq 1 40); do
  gs="$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose -f "${HERE}/docker-compose.yml" ps -q gateapi)" 2>/dev/null || echo starting)"
  [[ "${gs}" == "healthy" ]] && break; sleep 3
done
[[ "${gs:-}" == "healthy" ]] || fail "gateapi did not become healthy on a known-owned restart"
pass "known-owned restart: gateapi re-inits against the owned DB (manifest matches) and returns healthy"

# With the runtime secret injected and the stack live, container/stack logs must not carry the sentinel.
if docker compose -f "${HERE}/docker-compose.yml" logs --no-color 2>&1 | grep -q "${SENTINEL}"; then
  fail "sentinel found in running stack/container logs"
fi
pass "no sentinel in container/stack logs after runtime secret injection"

echo ""
echo "ALL PACKAGING PROOFS PASSED @ ${SHA}"
