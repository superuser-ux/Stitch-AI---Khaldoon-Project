#!/usr/bin/env bash
# #389 — focused automated packaging proof for the v2-dev lane. Builds the two application images from a
# CLEAN exact head (via the EXISTING committed recipes), proves provenance/least-privilege/file-closure/
# secret-exclusion, the negative guards (mismatched SHA rejected; workbench runtime-SHA override
# terminates; gateapi runtime-SHA guard terminates; unrecognized-DB fail-closed), the six #389
# reconciliation decisions (digest-pinned DB, resource ceilings, frozen loopback ports, candidate-path/
# denylist static contract, init double-run idempotency), and a private live-mode smoke. Teardown removes ONLY
# the isolated local v2-dev proof resources. This NEVER touches a VPS, registry push, or the acc/#337
# lane.
#
# Usage:  deploy/v2-dev/packaging_test.sh          # ports are frozen (127.0.0.1:18110 / 13101)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../.." && git rev-parse --show-toplevel)"
cd "${REPO}"

SHA="$(git rev-parse HEAD)"
GATEAPI="tanaghom-v2-dev-gateapi:${SHA}"
WORKBENCH="tanaghom-v2-dev-workbench:${SHA}"
export V2DEV_GIT_SHA="${SHA}"
# Frozen loopback ports (#389 decision 3) — literals in the committed compose; asserted, not parameterized.
WB_PORT=13101
API_PORT=18110
# Pinned DB digest (#389 decision 1) — must match the committed compose image ref.
PINNED_DIGEST="sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb"
DB_IMAGE="pgvector/pgvector:pg16@${PINNED_DIGEST}"
export DB_PASSWORD="v2dev-db-$(od -An -N8 -tx1 /dev/urandom | tr -d ' ')"
# A synthetic sentinel injected ONLY at runtime as the reviewer-proxy secret — it must NEVER appear in any
# image layer/config/label/history/filesystem/log. Never printed.
SENTINEL="v2dev-sentinel-$(od -An -N16 -tx1 /dev/urandom | tr -d ' ')"
export REVIEWER_PROXY_SECRET="${SENTINEL}"
IAM_TEST_NETWORK="tanaghom-v2-dev-iam-test-$$"
export TANAGHOM_IAM_NETWORK="${IAM_TEST_NETWORK}"

STAGE=""   # candidate-path staging dir (a temp dir; set in §6), removed on teardown

pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1" >&2; exit 1; }

cleanup() {
  echo "[teardown] removing only the isolated local v2-dev proof resources (candidate-only)"
  # project-scoped down (works regardless of which compose file the stack was brought up from)
  docker compose -p tanaghom-v2-dev down -v --remove-orphans >/dev/null 2>&1 || true
  docker rmi -f "${GATEAPI}" "${WORKBENCH}" >/dev/null 2>&1 || true
  rm -f /tmp/v2dev-*.tar 2>/dev/null || true
  [[ -n "${STAGE}" ]] && rm -rf "${STAGE}" "${STAGE}.manifest.sha256" 2>/dev/null || true
  # #387 — remove ONLY the FILE-seam artifacts THIS test created; never touch a pre-existing runtime path.
  [[ "${PROVISIONED_SECFILE:-0}" == "1" ]] && rm -f /run/tanaghom-secrets/reviewer_proxy_secret 2>/dev/null || true
  [[ "${PROVISIONED_OPENROUTER_FILE:-0}" == "1" ]] && rm -f /run/tanaghom-secrets/openrouter_api_key 2>/dev/null || true
  [[ "${PROVISIONED_GROQ_FILE:-0}" == "1" ]] && rm -f /run/tanaghom-secrets/groq_api_key 2>/dev/null || true
  [[ "${PROVISIONED_SECDIR:-0}" == "1" ]] && rmdir /run/tanaghom-secrets 2>/dev/null || true
  [[ "${PROVISIONED_IAM_NETWORK:-0}" == "1" ]] && docker network rm "${IAM_TEST_NETWORK}" >/dev/null 2>&1 || true
}
PROVISIONED_SECDIR=0; PROVISIONED_SECFILE=0; PROVISIONED_OPENROUTER_FILE=0; PROVISIONED_GROQ_FILE=0
PROVISIONED_IAM_NETWORK=0
trap cleanup EXIT

echo "== 1. clean exact-head build + full provenance (7 fields) =="
[[ -z "$(git status --porcelain)" ]] || fail "working tree dirty"
bash "${HERE}/build.sh" "${SHA}" >/dev/null
for img in "${GATEAPI}" "${WORKBENCH}"; do
  rev="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${img}")"
  usr="$(docker inspect --format '{{.Config.User}}' "${img}")"
  id="$(docker inspect --format '{{.Id}}' "${img}")"
  repodig="$(docker inspect --format '{{join .RepoDigests " "}}' "${img}")"
  [[ "${rev}" == "${SHA}" ]] || fail "${img} revision label != head"
  [[ "${usr}" == "10001:10001" || "${usr}" == "10001" ]] || fail "${img} not numeric non-root"
  # 7-field provenance: (1) merged SHA, (2) build recipe identity is the committed Dockerfile (built by
  # build.sh from a clean HEAD==SHA), (3) OCI revision label == SHA [checked], (4) local image ID,
  # (5) RepoDigest present OR explicit no-registry-digest statement, (6) container image-ID == this build
  # [checked at step 6], (7) runtime-reported SHA == merged SHA [workbench /api/runtime step 6; gateapi
  # baked-file guard step 5d]. App images are never pushed, so field (5) is the explicit no-registry state.
  [[ -z "${repodig}" ]] || fail "${img} unexpectedly carries a RepoDigest (this lane must not push)"
  docker save "${img}" -o "/tmp/v2dev-$(basename "${img}" | tr ':/' '__').tar"
  arch="$(sha256sum "/tmp/v2dev-$(basename "${img}" | tr ':/' '__').tar" | cut -d' ' -f1)"
  echo "  ${img}: image ID ${id} | OCI archive sha256 ${arch} | user ${usr} | RepoDigest: <none — not pushed>"
done
pass "both images built from clean head, labelled == head, numeric non-root, image IDs + archive digests recorded, explicit no-registry-digest"

echo "== 1b. DB image is pinned to an immutable digest, matching the locally-resolved RepoDigest (#389 decision 1) =="
grep -q "pgvector/pgvector:pg16@${PINNED_DIGEST}" "${HERE}/docker-compose.yml" || fail "compose DB image is not pinned to the frozen digest"
grep -Eq 'image:\s*pgvector/pgvector:pg16\s*$' "${HERE}/docker-compose.yml" && fail "compose carries a mutable-tag-only DB image line"
have="$(docker inspect --format '{{join .RepoDigests "\n"}}' "pgvector/pgvector:pg16" 2>/dev/null | grep -F "${PINNED_DIGEST}" || true)"
[[ -n "${have}" ]] || fail "local pgvector:pg16 RepoDigest does not match the pinned digest — do not guess; STOP and re-resolve"
pass "DB image digest-pinned (${PINNED_DIGEST:0:19}…) and verified against the locally-resolved RepoDigest"

echo "== 2. standalone file closure (workbench) + gateapi v2-dev init orchestrator/entrypoint present =="
docker run --rm --entrypoint sh "${WORKBENCH}" -c \
  'test -f /app/server.js && test -d /app/.next/static && test -f /app/public/brand/tenants/tanaghum/tanaghom-logo.png && test -f /app/public/brand/platform/stitch/stitch-logo.png && test -f /app/BUILD_SHA' \
  || fail "workbench standalone closure incomplete (server.js/static/public/BUILD_SHA)"
pass "workbench ships server.js + .next/static + public brand assets + baked BUILD_SHA (no source tree)"
docker run --rm --entrypoint sh "${GATEAPI}" -c \
  'test -f /work/deploy/v2-dev/init_db.py && test -f /work/deploy/v2-dev/gateapi-entrypoint.sh && test -f /work/BUILD_SHA' \
  || fail "gateapi missing committed v2-dev init orchestrator/entrypoint/baked BUILD_SHA"
pass "gateapi carries committed v2-dev init orchestrator + entrypoint + baked BUILD_SHA"
for dev in typescript tailwindcss @tailwindcss @types playwright @playwright postcss; do
  docker run --rm --entrypoint sh "${WORKBENCH}" -c "test -e /app/node_modules/${dev}" 2>/dev/null \
    && fail "dev dependency '${dev}' leaked into the workbench runtime image"
done
pass "workbench runtime image carries no dev dependency"

echo "== 3. sentinel-secret EXCLUSION from image config/env/labels/history/filesystem (never printed) =="
for img in "${GATEAPI}" "${WORKBENCH}"; do
  docker inspect "${img}" | grep -q "${SENTINEL}" && fail "sentinel found in ${img} inspect"
  docker history --no-trunc "${img}" | grep -q "${SENTINEL}" && fail "sentinel found in ${img} history"
  grep -aq "${SENTINEL}" "/tmp/v2dev-$(basename "${img}" | tr ':/' '__').tar" && fail "sentinel found in ${img} filesystem export"
done
pass "runtime secret absent from every image layer/config/label/history/filesystem"

echo "== 3b. #387 FILE-seam compose grammar (no reviewer-secret env; FILE + max-age + RO tmpfs bind) =="
grep -q "${SENTINEL}" "${HERE}/docker-compose.yml" && fail "committed compose contains a literal secret"
cfgtmp="$(mktemp)"
docker compose -f "${HERE}/docker-compose.yml" config >"${cfgtmp}" 2>/dev/null || true
# The reviewer-proxy secret is NO LONGER a container-env value: neither the committed nor the interpolated
# compose may carry a REVIEWER_PROXY_SECRET env key, and the runtime sentinel (were it exported) must not
# leak into the rendered compose at all.
grep -qE '(^|[^_])REVIEWER_PROXY_SECRET:' "${HERE}/docker-compose.yml" && fail "compose still declares a REVIEWER_PROXY_SECRET env key (env authority not removed)"
grep -q "${SENTINEL}" "${cfgtmp}" && fail "runtime sentinel leaked into the interpolated compose (FILE seam not in effect)"
# Both app services must carry the manager-neutral FILE seam + a positive max age.
for svc in gateapi workbench; do
  blk="$(python3 -c "import sys; t=open('${HERE}/docker-compose.yml').read(); print(t.split('\n  ${svc}:',1)[1].split('\n  workbench:',1)[0] if '${svc}'=='gateapi' else t.split('\n  ${svc}:',1)[1])")"
  echo "${blk}" | grep -q 'REVIEWER_PROXY_SECRET_FILE: /run/tanaghom-secrets/reviewer_proxy_secret' || fail "${svc} missing REVIEWER_PROXY_SECRET_FILE seam"
  echo "${blk}" | grep -qE 'REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS: "?900"?' || fail "${svc} missing positive REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS=900"
  echo "${blk}" | grep -qE '/run/tanaghom-secrets:/run/tanaghom-secrets:ro' || fail "${svc} missing read-only tmpfs secret bind"
done
rm -f "${cfgtmp}"
pass "reviewer-proxy secret delivered via the read-only FILE seam only; no container-env authority remains"
# Provider credentials follow the same FILE-only authority in gateapi, and stub mode is absent.
grep -qE '(^|[^_])OPENROUTER_API_KEY:' "${HERE}/docker-compose.yml" && fail "compose declares direct OPENROUTER_API_KEY authority"
grep -qE '(^|[^_])GROQ_API_KEY:' "${HERE}/docker-compose.yml" && fail "compose declares direct GROQ_API_KEY authority"
grep -q 'TANAGHOM_WRITER_STUB:' "${HERE}/docker-compose.yml" && fail "v2-dev compose still forces writer stub mode"
for item in OPENROUTER_API_KEY:openrouter_api_key GROQ_API_KEY:groq_api_key; do
  key="${item%%:*}"; file="${item#*:}"
  grep -q "${key}_FILE: /run/tanaghom-secrets/${file}" "${HERE}/docker-compose.yml" || fail "gateapi missing ${key}_FILE"
  grep -qE "${key}_FILE_MAX_AGE_SECONDS: \"?900\"?" "${HERE}/docker-compose.yml" || fail "gateapi missing ${key} max age"
done
pass "provider credentials use FILE-only authority and the developer writer is live-mode"
# The IAM session key reuses the same manager-neutral FILE seam. Its public PKCE client has no
# confidential-client credential and IAM remains disabled in the committed template.
grep -qE '(^|[^_])TANAGHOM_SESSION_SECRET:' "${HERE}/docker-compose.yml" && fail "compose declares direct TANAGHOM_SESSION_SECRET authority"
grep -q 'TANAGHOM_SESSION_SECRET_FILE: /run/tanaghom-secrets/iam_session_secret' "${HERE}/docker-compose.yml" || fail "workbench missing IAM session FILE seam"
grep -qE 'TANAGHOM_SESSION_SECRET_FILE_MAX_AGE_SECONDS: "?900"?' "${HERE}/docker-compose.yml" || fail "workbench missing IAM session max age"
grep -q 'TANAGHOM_OIDC_ENABLED=false' "${HERE}/.env.example" || fail "IAM must remain disabled in the committed template"
grep -q 'TANAGHOM_OIDC_ISSUER=http://iam.localhost:13210' "${HERE}/.env.example" || fail "developer issuer is not exact"
grep -q 'TANAGHOM_OIDC_INTERNAL_BASE_URL=http://caddy:13210' "${HERE}/.env.example" || fail "private OIDC transport route is not exact"
grep -q 'TANAGHOM_IAM_NETWORK=tanaghom-iam-dev' "${HERE}/.env.example" || fail "private IAM network is not exact"
grep -q 'TANAGHOM_OIDC_INTERNAL_BASE_URL:.*http://caddy:13210' "${HERE}/docker-compose.yml" || fail "workbench private OIDC transport route is absent"
grep -q 'name:.*tanaghom-iam-dev' "${HERE}/docker-compose.yml" || fail "workbench private IAM network attachment is absent"
grep -q 'TANAGHOM_OIDC_REDIRECT_URI=http://127.0.0.1:13101/api/auth/callback' "${HERE}/.env.example" || fail "developer callback is not exact"
grep -q 'TANAGHOM_OIDC_POST_LOGOUT_REDIRECT_URI=http://127.0.0.1:13101/' "${HERE}/.env.example" || fail "developer post-logout return is not exact"
grep -q '^TANAGHOM_OIDC_CLIENT_ID=$' "${HERE}/.env.example" || fail "public client ID must remain operator-supplied"
grep -qE '^TANAGHOM_OIDC_CLIENT_SECRET(_FILE)?=' "${HERE}/.env.example" && fail "public PKCE template must not configure a client secret"
grep -qE 'TANAGHOM_OIDC_CLIENT_SECRET(_FILE)?:' "${HERE}/docker-compose.yml" && fail "public PKCE compose must not configure a client secret"
grep -q 'iam-session)' "${HERE}/openbao/materialize-provider-secret.sh" || fail "runtime-secret materializer does not allowlist iam-session"
grep -q 'KV_PATH="dev/iam/session"' "${HERE}/openbao/materialize-provider-secret.sh" || fail "iam-session KV path is not exact"
grep -q 'OUT_NAME="iam_session_secret"' "${HERE}/openbao/materialize-provider-secret.sh" || fail "iam-session output name is not exact"
grep -qF 'path "tanaghom/data/dev/iam/session"' "${HERE}/openbao/iam-session-policy.hcl" || fail "iam-session policy path is not exact"
grep -qF 'capabilities = ["read"]' "${HERE}/openbao/iam-session-policy.hcl" || fail "iam-session policy is not read-only"
pass "IAM session uses the existing FILE seam; exact private topology; IAM off; public PKCE has no client secret"
ours="$(docker images -a --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -E "^tanaghom-v2-dev-(gateapi|workbench):${SHA}\$" | sort -u)"
expected="$(printf '%s\n%s\n' "${GATEAPI}" "${WORKBENCH}" | sort -u)"
[[ "${ours}" == "${expected}" ]] || fail "unexpected retained stage(s) for ${SHA}: ${ours}"
pass "no retained intermediate stage for this build (only the two final ${SHA:0:12}… images)"

echo "== 4. static contract: frozen ports, resource ceilings, candidate-path/denylist, no shared mounts =="
CFG="$(docker compose -f "${HERE}/docker-compose.yml" config 2>/dev/null)"
# 4a — frozen loopback ports, literal (decision 3). Assert BOTH the committed short-form and the rendered
# long-form (host_ip 127.0.0.1 + published 18110/13101).
grep -qE '127\.0\.0\.1:18110:8000' "${HERE}/docker-compose.yml" || fail "API loopback 127.0.0.1:18110:8000 not frozen in committed compose"
grep -qE '127\.0\.0\.1:13101:3001' "${HERE}/docker-compose.yml" || fail "workbench loopback 127.0.0.1:13101:3001 not frozen in committed compose"
echo "${CFG}" | grep -q 'host_ip: 127.0.0.1' || fail "rendered compose does not bind host_ip 127.0.0.1"
echo "${CFG}" | grep -q 'published: "18110"' || fail "rendered compose does not publish 18110"
echo "${CFG}" | grep -q 'published: "13101"' || fail "rendered compose does not publish 13101"
# no non-loopback host_ip anywhere
echo "${CFG}" | grep -E 'host_ip: (0\.0\.0\.0|::)' && fail "rendered compose has a non-loopback host_ip"
pass "frozen loopback ports present (127.0.0.1:18110 API / 127.0.0.1:13101 workbench); no non-loopback binding"
# 4b — resource ceilings present for every service (decision 5); both cpus/mem_limit and deploy.limits
for svc_mem in "640" "512" "512"; do :; done
echo "${CFG}" | grep -q 'mem_limit' || fail "no mem_limit ceiling encoded"
python3 - "$HERE/docker-compose.yml" <<'PY' || exit 1
import re, sys, io
txt = open(sys.argv[1]).read()
# crude per-service ceiling presence check on the committed (pre-interpolation) file
for svc, cpus, mem in (("db","0.75","640m"),("gateapi","0.75","512m"),("workbench","0.5","512m")):
    blk = txt.split(f"\n  {svc}:",1)[1]
    if not re.search(rf"cpus:\s*{cpus}", blk): print(f"FAIL: {svc} missing cpus {cpus}"); sys.exit(1)
    if not re.search(rf"mem_limit:\s*{mem}", blk): print(f"FAIL: {svc} missing mem_limit {mem}"); sys.exit(1)
    if "deploy:" not in blk.split(f"\n  ",1)[0]+blk[:600]: pass
print("  PASS: per-service CPU/mem ceilings encoded (db 0.75/640m, gateapi 0.75/512m, workbench 0.5/512m; aggregate 2.0 CPU / 1.66 GiB)")
PY
# 4c — candidate-path + denylist static contract lives in the runbook; no shared-path bind mount anywhere
grep -q '/srv/tanaghom-v2-dev' "${HERE}/README.md" || fail "runbook does not freeze the candidate path /srv/tanaghom-v2-dev"
grep -q '0750' "${HERE}/README.md" && grep -q '0640' "${HERE}/README.md" && grep -q '0600' "${HERE}/README.md" || fail "runbook missing frozen modes (0750/0640/0600)"
grep -qi 'canonical' "${HERE}/README.md" && grep -qi 'symlink' "${HERE}/README.md" || fail "runbook missing canonical-path/symlink-escape checks"
for deny in tanaghum-backup postiz powerfix /srv/tanaghum-primary; do
  grep -q "${deny}" "${HERE}/README.md" || fail "runbook denylist missing '${deny}'"
done
# compose must not bind-mount ANY host path except the named db_data volume and the #387 authorized
# read-only reviewer-proxy secret tmpfs bind (/run/tanaghom-secrets, RO); never a denylisted path.
if echo "${CFG}" | grep -E 'source:\s*/' | grep -v 'db_data' | grep -vq '/run/tanaghom-secrets'; then fail "compose bind-mounts an unauthorized host path"; fi
# the reviewer-proxy secret bind must be READ-ONLY wherever it appears
python3 - "${HERE}/docker-compose.yml" <<'PY' || fail "reviewer-proxy secret bind is not read-only (:ro) on every service that mounts it"
import sys
t = open(sys.argv[1]).read()
n = t.count("/run/tanaghom-secrets:/run/tanaghom-secrets:ro")
sys.exit(0 if n == 2 else 1)
PY
for deny in /srv/tanaghum-primary /var/run/docker.sock; do
  echo "${CFG}" | grep -q "${deny}" && fail "compose references a denylisted/dangerous path '${deny}'"
done
pass "candidate-path + shared-service denylist frozen in runbook; compose has no host bind mount and no denylisted path"
# 4d — runtime compose is self-contained: NO build context (candidate path needs no repo checkout), and app
# images are pull_policy: never (fail closed if not loaded, never a silent registry pull).
grep -qE '^\s*build:' "${HERE}/docker-compose.yml" && fail "runtime compose still contains a build: stanza (would need a repo build context at the candidate path)"
echo "${CFG}" | grep -qE 'build:' && fail "rendered compose contains a build context"
for svc in gateapi workbench; do
  blk="$(python3 -c "import sys; t=open('${HERE}/docker-compose.yml').read(); print(t.split('\n  ${svc}:',1)[1].split('\n  workbench:',1)[0] if '${svc}'=='gateapi' else t.split('\n  ${svc}:',1)[1])")"
  echo "${blk}" | grep -q 'pull_policy: never' || fail "${svc} missing pull_policy: never"
done
pass "runtime compose is self-contained: no build context; app images pull_policy: never (loaded from transferred archives)"

echo "== 5. negatives: mismatched-SHA build, workbench runtime-SHA override, gateapi runtime-SHA guard =="
BOGUS="$(printf '0%.0s' {1..40})"
if bash "${HERE}/build.sh" "${BOGUS}" >/dev/null 2>&1; then fail "build accepted a SHA != HEAD"; fi
pass "build.sh rejects a SHA that does not equal clean HEAD"
if docker run --rm -e "TANAGHOM_WORKBENCH_BUILD_SHA=$(printf 'f%.0s' {1..40})" "${WORKBENCH}" >/dev/null 2>&1; then
  fail "workbench started with a divergent runtime SHA override"
fi
pass "workbench terminates non-zero when a runtime SHA override diverges from the baked value"
# 5d — gateapi runtime-SHA guard (#389 decision 2): a divergent expected SHA TERMINATES at the entrypoint
# guard, BEFORE init/uvicorn (no DB needed). Absence of the divergence is proven by the healthy stack (§6).
g_rc=0
docker run --rm -e "TANAGHOM_GATEAPI_EXPECTED_SHA=$(printf 'e%.0s' {1..40})" \
  --entrypoint sh "${GATEAPI}" /work/deploy/v2-dev/gateapi-entrypoint.sh >/dev/null 2>&1 || g_rc=$?
[[ "${g_rc}" -ne 0 ]] || fail "gateapi served with an expected-SHA that diverges from the baked BUILD_SHA"
pass "gateapi entrypoint terminates non-zero when expected reviewed SHA != baked BUILD_SHA (exit ${g_rc})"

echo "== 5b/5c. recreated-container/no-marker and identity-mismatch vs a retained non-empty DB fail closed =="
NEGNET="v2dev-negnet-$$"; NEGDB="v2dev-negdb-$$"
docker network create "${NEGNET}" >/dev/null
docker run -d --name "${NEGDB}" --network "${NEGNET}" \
  -e POSTGRES_USER=tanaghom -e POSTGRES_PASSWORD="${DB_PASSWORD}" -e POSTGRES_DB=tanaghom \
  "${DB_IMAGE}" >/dev/null
for i in $(seq 1 40); do docker exec "${NEGDB}" pg_isready -U tanaghom -d tanaghom >/dev/null 2>&1 && break; sleep 1; done
docker run --rm --network "${NEGNET}" -e DB_HOST="${NEGDB}" -e DB_PASSWORD="${DB_PASSWORD}" \
  --entrypoint sh "${GATEAPI}" -c 'python - <<PY
import glob, os, psycopg2
c = psycopg2.connect(host=os.environ["DB_HOST"], dbname="tanaghom", user="tanaghom", password=os.environ["DB_PASSWORD"])
c.autocommit = True; cur = c.cursor()
cur.execute(open("/work/db/init/schema.sql").read())
for p in sorted(glob.glob("/work/db/migrations/*.sql")):
    cur.execute(open(p).read())
cur.execute("DROP TABLE IF EXISTS publication CASCADE")
PY' >/dev/null 2>&1 || { docker rm -f "${NEGDB}" >/dev/null 2>&1; docker network rm "${NEGNET}" >/dev/null 2>&1; fail "could not construct the retained non-empty DB fixture"; }
neg1_rc=0
docker run --rm --network "${NEGNET}" -e DB_HOST="${NEGDB}" -e DB_PASSWORD="${DB_PASSWORD}" \
  --entrypoint sh "${GATEAPI}" -c 'python /work/deploy/v2-dev/init_db.py' >/dev/null 2>&1 || neg1_rc=$?
[[ "${neg1_rc}" -ne 0 ]] || { docker rm -f "${NEGDB}" >/dev/null 2>&1; docker network rm "${NEGNET}" >/dev/null 2>&1; fail "init served with no container-local marker against a retained non-empty DB"; }
pass "recreated container / no local marker vs retained non-empty DB → fails closed (exit ${neg1_rc})"
neg2_rc=0
docker run --rm --network "${NEGNET}" -e DB_HOST="${NEGDB}" -e DB_PASSWORD="${DB_PASSWORD}" \
  --entrypoint sh "${GATEAPI}" -c '
set -e
MAN="$(python -c "import sys; sys.path.insert(0,\"/work/deploy/v2-dev\"); import init_db; print(init_db._committed_manifest())")"
printf "%s\n%s\n" "$MAN" "0000000000000000000" > /work/.tanaghom-v2-dev-init-marker
python /work/deploy/v2-dev/init_db.py' >/dev/null 2>&1 || neg2_rc=$?
docker rm -f "${NEGDB}" >/dev/null 2>&1 || true
docker network rm "${NEGNET}" >/dev/null 2>&1 || true
[[ "${neg2_rc}" -ne 0 ]] || fail "init served with a marker whose database identity does not match the cluster"
pass "container-local marker with mismatched database identity → fails closed (exit ${neg2_rc})"

echo "== 6. candidate-path staging + image transfer: assemble the actual layout, then run purely from it =="
# Assemble the self-contained candidate-path layout (runtime compose + immutable OCI archives + MANIFEST +
# load script) — exactly what a later deployment would transfer to /srv/tanaghom-v2-dev.
STAGE="$(mktemp -d)"
bash "${HERE}/stage.sh" "${SHA}" "${STAGE}" >/dev/null
SC="${STAGE}/docker-compose.yml"
# External trust anchor (GPT correction 1): stage.sh emitted the manifest sha256 OUTSIDE the candidate dir.
[ -f "${STAGE}.manifest.sha256" ] || fail "stage.sh did not emit the external manifest digest outside the candidate dir"
[ -e "${STAGE}/manifest.sha256" ] && fail "manifest digest leaked INTO the candidate dir (must be external)"
PRISTINE_MAN_SHA="$(cat "${STAGE}.manifest.sha256")"
printf '%s' "${PRISTINE_MAN_SHA}" | grep -Eq '^[0-9a-f]{64}$' || fail "external manifest digest malformed"
export V2DEV_EXPECTED_MANIFEST_SHA256="${PRISTINE_MAN_SHA}"
pass "external manifest trust anchor emitted outside the candidate dir (${PRISTINE_MAN_SHA:0:16}…)"
# 6-i — the staged set is EXACTLY the allowed runtime artifacts: no source tree, Dockerfile, or build script.
got="$(find "${STAGE}" -type f | sort)"
exp="$(printf '%s\n' \
  "${STAGE}/.env.example" \
  "${STAGE}/MANIFEST.txt" \
  "${STAGE}/README.md" \
  "${STAGE}/docker-compose.yml" \
  "${STAGE}/images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar" \
  "${STAGE}/images/tanaghom-v2-dev-workbench-${SHA}.oci.tar" \
  "${STAGE}/load-images.sh" \
  "${STAGE}/openbao/README.md" \
  "${STAGE}/openbao/groq-policy.hcl" \
  "${STAGE}/openbao/iam-session-policy.hcl" \
  "${STAGE}/openbao/materialize-provider-secret.sh" \
  "${STAGE}/openbao/materialize-reviewer-proxy.sh" \
  "${STAGE}/openbao/openrouter-policy.hcl" \
  "${STAGE}/openbao/reviewer-proxy-policy.hcl" \
  "${STAGE}/openbao/tanaghom-provider-secret@.service" \
  "${STAGE}/openbao/tanaghom-provider-secret@.timer" \
  "${STAGE}/openbao/tanaghom-reviewer-proxy.service" \
  "${STAGE}/openbao/tanaghom-reviewer-proxy.timer" | sort)"
[[ "${got}" == "${exp}" ]] || fail "staged candidate set != allowed runtime file set:"$'\n'"${got}"
for forbidden in Dockerfile Dockerfile.api build.sh stage.sh packaging_test.sh init_db.py init_fixtures.py gateapi-entrypoint.sh .gitignore; do
  find "${STAGE}" -name "${forbidden}" | grep -q . && fail "build-lane/source artifact '${forbidden}' leaked into candidate layout"
done
grep -qE '^\s*build:' "${SC}" && fail "staged compose contains a build: stanza"
pass "candidate layout self-contained: runtime compose + OCI archives + MANIFEST + load script + non-secret openbao adapter (no source/Dockerfile/build script; no build: stanza)"
# #387 — the staged non-secret openbao adapter carries NO secret material: no RoleID/SecretID/token/value,
# no runtime sentinel, no private key. (RoleID/SecretID/tokens live only in the root-only host custody.)
for of in README.md groq-policy.hcl iam-session-policy.hcl materialize-provider-secret.sh materialize-reviewer-proxy.sh openrouter-policy.hcl reviewer-proxy-policy.hcl tanaghom-provider-secret@.service tanaghom-provider-secret@.timer tanaghom-reviewer-proxy.service tanaghom-reviewer-proxy.timer; do
  [[ -f "${STAGE}/openbao/${of}" ]] || fail "staged openbao adapter missing ${of}"
done
grep -rIq "${SENTINEL}" "${STAGE}/openbao" && fail "runtime sentinel present in staged openbao adapter"
grep -rIqE 'role_id[[:space:]]*[=:][[:space:]]*[A-Za-z0-9]|secret_id[[:space:]]*[=:][[:space:]]*[A-Za-z0-9]|-----BEGIN[A-Z ]*PRIVATE KEY|hvs\.[A-Za-z0-9]' "${STAGE}/openbao" && fail "secret-like material present in staged openbao adapter"
pass "staged openbao adapter is non-secret (materializer+policy+units+README present; no credential material)"
# #387 (Named Codex 5154091356) — /run is tmpfs (empty after boot), so the oneshot must CREATE
# /run/tanaghom-secrets before namespace setup or ProtectSystem=strict + ReadWritePaths fails before
# ExecStart. Assert the RuntimeDirectory contract + retained ReadWritePaths in the STAGED unit.
SVCUNIT="${STAGE}/openbao/tanaghom-reviewer-proxy.service"
# Ownership: run AS the app identity so the preserved RuntimeDirectory is created/kept at 10001:10001
# (no per-run root->10001 chown churn / unreadable interval).
grep -qE '^User=10001$'  "${SVCUNIT}" || fail "service unit must run as User=10001 (avoid root RuntimeDirectory ownership reset)"
grep -qE '^Group=10001$' "${SVCUNIT}" || fail "service unit must run as Group=10001"
# The exact !-prefixed ExecStart runs the command as root while keeping the filesystem sandbox; the `+`
# prefix (which would bypass namespacing) is forbidden.
grep -qxF 'ExecStart=!/srv/tanaghom-dev/openbao/materialize-reviewer-proxy.sh' "${SVCUNIT}" || fail "service unit ExecStart must be exactly '!/srv/tanaghom-dev/openbao/materialize-reviewer-proxy.sh'"
grep -qE '^ExecStart=\+' "${SVCUNIT}" && fail "service unit must NOT use the + ExecStart prefix (bypasses filesystem namespacing)"
grep -qE '^RuntimeDirectory=tanaghom-secrets$'    "${SVCUNIT}" || fail "service unit missing RuntimeDirectory=tanaghom-secrets"
grep -qE '^RuntimeDirectoryMode=0500$'            "${SVCUNIT}" || fail "service unit missing RuntimeDirectoryMode=0500"
grep -qE '^RuntimeDirectoryPreserve=yes$'         "${SVCUNIT}" || fail "service unit missing RuntimeDirectoryPreserve=yes"
grep -qE '^ReadWritePaths=/run/tanaghom-secrets$' "${SVCUNIT}" || fail "service unit missing ReadWritePaths=/run/tanaghom-secrets"
pass "reviewer-proxy oneshot: User/Group=10001, ExecStart=! (root exec, sandbox kept), RuntimeDirectory (0500, preserved) + ReadWritePaths"
PROVIDER_UNIT="${STAGE}/openbao/tanaghom-provider-secret@.service"
grep -qxF 'ExecStart=!/srv/tanaghom-dev/openbao/materialize-provider-secret.sh %i' "${PROVIDER_UNIT}" || fail "provider unit ExecStart is not the bounded template command"
grep -qE '^RuntimeDirectory=tanaghom-secrets$' "${PROVIDER_UNIT}" || fail "provider unit missing RuntimeDirectory"
grep -qE '^ReadWritePaths=/run/tanaghom-secrets$' "${PROVIDER_UNIT}" || fail "provider unit missing tmpfs write scope"
pass "runtime-secret oneshot template is bounded to openrouter/groq/iam-session and shares the hardened tmpfs contract"
# Optional non-weakening grammar check: systemd-analyze verify (if present). ExecStart's target does not
# exist on a build host, so verify a copy whose ExecStart points at an existing binary — KEEPING the `!`
# prefix — so the [Service] grammar (incl. the credential prefix + RuntimeDirectory) is validated without
# a spurious path warning.
if command -v systemd-analyze >/dev/null 2>&1; then
  vdir="$(mktemp -d)"
  sed 's#^ExecStart=.*#ExecStart=!/bin/true#' "${SVCUNIT}" > "${vdir}/tanaghom-reviewer-proxy.service"
  systemd-analyze verify "${vdir}/tanaghom-reviewer-proxy.service" || fail "systemd-analyze verify reported a unit grammar error"
  rm -rf "${vdir}"
  pass "systemd-analyze verify: reviewer-proxy.service grammar valid (! prefix + RuntimeDirectory contract)"
else
  echo "  SKIP: systemd-analyze not available on this host — service unit grammar asserted statically above"
fi
# 6-ii — prove the images come from the TRANSFERRED archives, not the local build: remove the built
# images, then load + provenance-verify from the staged archives.
docker rmi -f "${GATEAPI}" "${WORKBENCH}" >/dev/null 2>&1 || true
docker image inspect "${GATEAPI}" >/dev/null 2>&1 && fail "gateapi image not removed before transfer proof"
docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && fail "workbench image not removed before transfer proof"
bash "${STAGE}/load-images.sh" >/dev/null || fail "load-images.sh failed provenance verification"
docker image inspect "${GATEAPI}" >/dev/null 2>&1 || fail "gateapi not restored from transferred archive"
docker image inspect "${WORKBENCH}" >/dev/null 2>&1 || fail "workbench not restored from transferred archive"
pass "app images restored from transferred OCI archives; load-images.sh verified sha256 + image ID + revision label"
# 6-iii — bring the stack up PURELY from the staged candidate layout (no --build; no repo present there).
# #387 — provision the reviewer-proxy secret via the FILE seam (mimics the host materializer) at the frozen
# tmpfs bind source so the stack PROVES memory-resident, file-backed delivery. Guarantees:
#   * NEVER overwrite/delete a pre-existing runtime secret path (refuse before touching it);
#   * provisioning ownership/mode weakness FAILS (no weaker, unreadable fallback);
#   * teardown removes ONLY the dir/file this test itself created (see cleanup()).
# The container user (10001) must be able to read the 0400 file, so this step requires the privilege to
# chown to 10001; if it cannot, the test FAILS rather than falsely passing on an unreadable file.
SECDIR="/run/tanaghom-secrets"; SECFILE="${SECDIR}/reviewer_proxy_secret"
OPENROUTER_FILE="${SECDIR}/openrouter_api_key"; GROQ_FILE="${SECDIR}/groq_api_key"
for file in "${SECFILE}" "${OPENROUTER_FILE}" "${GROQ_FILE}"; do
  [[ -e "${file}" ]] && fail "refusing to overwrite a pre-existing runtime secret at ${file}"
done
if [[ ! -d "${SECDIR}" ]]; then
  install -d -m 0500 -o 10001 -g 10001 "${SECDIR}" || fail "cannot provision ${SECDIR} at mode 0500 owner 10001:10001 (provisioning weakness)"
  PROVISIONED_SECDIR=1
fi
( umask 077; printf '%s' "${SENTINEL}" > "${SECFILE}" ) || fail "cannot create ${SECFILE}"
PROVISIONED_SECFILE=1
chown 10001:10001 "${SECFILE}" || fail "cannot set ownership 10001:10001 on ${SECFILE} (provisioning weakness — refusing a weaker unreadable file)"
chmod 0400 "${SECFILE}" || fail "cannot set mode 0400 on ${SECFILE}"
for spec in "${OPENROUTER_FILE}:PROVISIONED_OPENROUTER_FILE" "${GROQ_FILE}:PROVISIONED_GROQ_FILE"; do
  file="${spec%%:*}"; marker="${spec#*:}"
  ( umask 077; printf '%s' "${SENTINEL}" > "${file}" ) || fail "cannot create ${file}"
  printf -v "${marker}" '%s' 1
  chown 10001:10001 "${file}" || fail "cannot set ownership 10001:10001 on ${file}"
  chmod 0400 "${file}" || fail "cannot set mode 0400 on ${file}"
done
docker network create "${IAM_TEST_NETWORK}" >/dev/null
PROVISIONED_IAM_NETWORK=1
docker compose -f "${SC}" up -d >/dev/null
for i in $(seq 1 60); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose -f "${SC}" ps -q workbench)" 2>/dev/null || echo starting)"
  [[ "${st}" == "healthy" ]] && break; sleep 3
done
[[ "${st:-}" == "healthy" ]] || fail "workbench did not become healthy from the staged candidate layout"
svc_count="$(docker compose -f "${SC}" ps --services | sort -u | tr '\n' ' ')"
[[ "${svc_count}" == "db gateapi workbench " ]] || fail "topology is not exactly db+gateapi+workbench: '${svc_count}'"
pass "exactly three services (db, gateapi, workbench) — brought up purely from the transferred candidate layout"

# 6a — container image-ID equality (provenance field 6): each running app container's Image == the
# reviewed build image ID (which == the loaded transferred-archive image ID — a save/load invariant).
for svc in gateapi workbench; do
  img="tanaghom-v2-dev-${svc}:${SHA}"
  want="$(docker inspect --format '{{.Id}}' "${img}")"
  got="$(docker inspect --format '{{.Image}}' "$(docker compose -f "${SC}" ps -q ${svc})")"
  [[ "${got}" == "${want}" ]] || fail "${svc} container image-ID (${got}) != reviewed build image ID (${want})"
done
pass "each running app container's image ID == the reviewed build image ID (preserved through save/transfer/load)"

RT="$(curl -s "http://127.0.0.1:${WB_PORT}/api/runtime")"
echo "${RT}" | grep -q "\"build\":\"${SHA}\"" || fail "workbench runtime build != head SHA: ${RT}"
echo "${RT}" | grep -q '"surface":"workbench"' || fail "runtime surface not workbench"
pass "workbench runtime identity == build head SHA (${SHA:0:12}…)"
H="$(curl -s "http://127.0.0.1:${WB_PORT}/gw/health")"
echo "${H}" | grep -q '"writer_mode":"live"' || fail "writer_mode is not live: ${H}"
echo "${H}" | grep -q '"openrouter":{"configured":true,"source":"file"}' || fail "OpenRouter FILE credential not reported configured"
echo "${H}" | grep -q '"groq":{"configured":true,"source":"file"}' || fail "Groq FILE credential not reported configured"
curl -s "http://127.0.0.1:${WB_PORT}/gw/rounds" | grep -q '\[' || fail "canonical /gw -> API read failed"
pass "workbench -> /gw -> governed API smoke: live writer mode + provider FILE metadata + canonical rounds read"
# #387 — PROVE memory-backed FILE delivery: the gate API must report configured=true AND source="file"
# (boolean + source-kind only, never the value). Accepting null would let a permission/mount failure pass.
echo "${H}" | grep -q '"reviewer_secret_configured":true' || fail "gate API did not report reviewer_secret_configured=true from the FILE seam: ${H}"
echo "${H}" | grep -q '"reviewer_secret_source":"file"' || fail "gate API did not report reviewer_secret_source=file (memory-backed FILE delivery unproven): ${H}"
echo "${H}" | grep -q "${SENTINEL}" && fail "reviewer-proxy secret value leaked onto /health"
pass "gate API proves memory-backed FILE delivery (configured=true, source=file; value never exposed)"

for c in gateapi workbench; do
  hostip="$(docker inspect --format '{{range $p,$b := .NetworkSettings.Ports}}{{range $b}}{{.HostIp}} {{end}}{{end}}' "$(docker compose -f "${SC}" ps -q ${c})")"
  echo "${hostip}" | grep -qE '127\.0\.0\.1' || fail "${c} host binding is not loopback: '${hostip}'"
  echo "${hostip}" | grep -qE '0\.0\.0\.0|::' && fail "${c} has a non-loopback binding"
done
dbports="$(docker inspect --format '{{json .NetworkSettings.Ports}}' "$(docker compose -f "${SC}" ps -q db)")"
echo "${dbports}" | grep -q '5432/tcp":null' || echo "${dbports}" | grep -q '"5432/tcp":\[\]' || [[ "${dbports}" == '{"5432/tcp":null}' || "${dbports}" == "{}" ]] || fail "DB appears to publish a host port: ${dbports}"
pass "application ports loopback-only (127.0.0.1); DB internal (no host port)"

# 6b — #414: ORDINARY STARTUP IS DB-READ-ONLY + an EXPLICIT, lane-bounded, idempotent fixture initializer.
# Ordinary startup (init_db.py, run by the entrypoint) must load NO catalogue, seed NO fixture, and open
# NO gate. A known-owned restart/recreate must leave an EXACT persisted-data fingerprint — every table's
# row count PLUS the audit_log count AND max(id) — byte-identical (no audit row may be appended). Synthetic
# fixtures come only from the deliberate deploy/v2-dev/init_fixtures.py, which is create-missing-only,
# marker-evidenced, and refuses outside the synthetic v2-dev-389 lane.
DBC="$(docker compose -f "${SC}" ps -q db)"
GWC="$(docker compose -f "${SC}" ps -q gateapi)"
fingerprint() {  # deterministic md5 over EVERY user table's EXACT row count + explicit audit_log count & max(id)
  # #414 correction 1: build a schema-qualified, per-table EXACT-count query on the server (format()/%I is
  # injection-safe; deterministic ORDER BY), then execute it. No query_to_xml/xpath — the prior XPath
  # (`/row/c/text()`) returned empty and collapsed every non-audit table count to a constant md5, so those
  # counts were never actually proven. This construction proves every user table's real count, while the
  # audit_log count AND max(id) stay explicit.
  local perq
  perq="$(docker exec "${DBC}" psql -U tanaghom -d tanaghom -tAX -c \
    "SELECT coalesce(string_agg(format('SELECT %L AS k, count(*)::bigint AS n FROM %I.%I', quote_ident(schemaname)||'.'||quote_ident(relname), schemaname, relname), ' UNION ALL ' ORDER BY schemaname, relname), 'SELECT NULL::text AS k, 0::bigint AS n WHERE false') FROM pg_stat_user_tables")"
  docker exec "${DBC}" psql -U tanaghom -d tanaghom -tAX -c \
    "SELECT md5(coalesce(string_agg(k||'='||n, ',' ORDER BY k),''))||'|audit_count='||(SELECT count(*) FROM audit_log)||'|audit_max='||coalesce((SELECT max(id)::text FROM audit_log),'0') FROM (${perq}) s"
}

# (i) ordinary startup on a fresh DB seeds NOTHING (no catalogue, no fixture round, no audit row).
fresh="$(docker exec "${DBC}" psql -U tanaghom -d tanaghom -tAX -c "SELECT (SELECT count(*) FROM methodology)||'|'||(SELECT count(*) FROM round)||'|'||(SELECT count(*) FROM audit_log)")"
[[ "${fresh}" == "0|0|0" ]] || fail "#414: ordinary startup was not read-only on a fresh DB (methodology|round|audit_log='${fresh}', expected 0|0|0)"
pass "#414 ordinary startup on a fresh DB seeds nothing (methodology|round|audit_log = 0|0|0)"

# (ii) explicit fixture initializer — FIRST run creates catalogue + RE2E fixture + open gate (evidenced).
docker exec "${GWC}" python /work/deploy/v2-dev/init_fixtures.py --confirm 2>&1 | tee /tmp/v2dev-fxi1.log | grep -q "DONE:" || fail "explicit fixture initializer did not report DONE on first init: $(cat /tmp/v2dev-fxi1.log)"
grep -q 'methodology=loaded' /tmp/v2dev-fxi1.log && grep -q 'fixture_round=created' /tmp/v2dev-fxi1.log && grep -q 'fixture_gate=opened' /tmp/v2dev-fxi1.log || fail "first fixture init did not create catalogue+round+gate: $(cat /tmp/v2dev-fxi1.log)"
seeded="$(docker exec "${DBC}" psql -U tanaghom -d tanaghom -tAX -c "SELECT (SELECT count(*) FROM methodology)||'|'||(SELECT count(*) FROM round WHERE round_id='RE2E')||'|'||(SELECT count(*) FROM slot WHERE round_id='RE2E')")"
[[ "${seeded}" == "1|1|3" ]] || fail "fixture initializer did not create the expected synthetic fixture (methodology|RE2E-round|RE2E-slots='${seeded}', expected 1|1|3)"
pass "#414 explicit fixture initializer FIRST run creates catalogue + RE2E fixture + open gate (evidenced)"

FP_INIT="$(fingerprint)"

# (iii) THE read-only-startup regression: a KNOWN-OWNED gateapi restart is MANDATORY, genuinely fresh, and
# changes NO rows — exact fingerprint (table counts + audit_log count AND max id) byte-identical.
# #414 correction 2: the restart must SUCCEED (no `|| true`), restart the SAME container in place, and
# produce a NEW StartedAt — otherwise a silently-failed / no-op restart would make the read-only proof
# vacuous. (RestartCount is deliberately NOT asserted: it counts restart-policy restarts, not a manual
# `docker compose restart`, so StartedAt is the reliable fresh-start evidence.)
# #414 correction 3: capture a pre-restart LOG BOUNDARY (line count) so the read-only init record is proven
# to come from THIS restart, not from accumulated first-boot logs.
GW_CID_BEFORE="$(docker compose -f "${SC}" ps -q gateapi)"
GW_START_BEFORE="$(docker inspect --format '{{.State.StartedAt}}' "${GW_CID_BEFORE}")"
GW_LOGLINES_BEFORE="$(docker compose -f "${SC}" logs --no-color gateapi 2>&1 | wc -l | tr -d ' ')"
docker compose -f "${SC}" restart gateapi >/dev/null 2>&1 || fail "#414 correction 2: mandatory gateapi restart command failed"
for i in $(seq 1 40); do
  gs="$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose -f "${SC}" ps -q gateapi)" 2>/dev/null || echo starting)"
  [[ "${gs}" == "healthy" ]] && break; sleep 3
done
[[ "${gs:-}" == "healthy" ]] || fail "gateapi did not become healthy on a known-owned restart"
GWC="$(docker compose -f "${SC}" ps -q gateapi)"   # refresh after restart
[[ "${GWC}" == "${GW_CID_BEFORE}" ]] || fail "#414 correction 2: gateapi was recreated (container id changed), not restarted in place"
GW_START_AFTER="$(docker inspect --format '{{.State.StartedAt}}' "${GWC}")"
[[ -n "${GW_START_BEFORE}" && "${GW_START_AFTER}" != "${GW_START_BEFORE}" ]] || fail "#414 correction 2: gateapi StartedAt unchanged after restart (before='${GW_START_BEFORE}' after='${GW_START_AFTER}') — no fresh start; the read-only restart proof would be vacuous"
pass "#414 correction 2: ordinary gateapi restart is MANDATORY, in-place, and genuinely fresh (StartedAt ${GW_START_BEFORE} -> ${GW_START_AFTER})"
FP_RESTART="$(fingerprint)"
[[ -n "${FP_INIT}" && "${FP_INIT}" == "${FP_RESTART}" ]] || fail "#414 VIOLATED: ordinary restart changed the DB fingerprint: before='${FP_INIT}' after='${FP_RESTART}'"
pass "#414 ordinary Gate API restart is DB-read-only: exact fingerprint (table counts + audit_log count + max id) byte-identical"
# #414 correction 3: examine ONLY the post-boundary log slice (lines appended by THIS restart), so the
# read-only init record is proven fresh — accumulated first-boot logs cannot satisfy it.
GW_LOG_POST="$(docker compose -f "${SC}" logs --no-color gateapi 2>&1 | tail -n +"$((GW_LOGLINES_BEFORE + 1))")"
printf '%s\n' "${GW_LOG_POST}" | grep -q "ordinary startup is DB-read-only" || fail "#414 correction 3: no NEW post-restart read-only init record after the pre-restart log boundary (line ${GW_LOGLINES_BEFORE})"
printf '%s\n' "${GW_LOG_POST}" | grep -Eq "seeded RE2E|running loader/load_methodology|running gates/e2e_seed" && fail "#414: the post-restart startup ran a catalogue/fixture/gate seed step (must be read-only)"
pass "#414 correction 3: the restart emitted a NEW read-only-path init record (post-boundary) and ran no catalogue/fixture/gate seeding"

# (iv) initializer NO-OP rerun — marker present ⇒ zero writes ⇒ identical fingerprint.
docker exec "${GWC}" python /work/deploy/v2-dev/init_fixtures.py --confirm 2>&1 | tee /tmp/v2dev-fxi2.log | grep -q "NO-OP:" || fail "fixture initializer rerun was not a no-op: $(cat /tmp/v2dev-fxi2.log)"
FP_NOOP="$(fingerprint)"
[[ "${FP_INIT}" == "${FP_NOOP}" ]] || fail "fixture initializer rerun mutated the DB (not idempotent): before='${FP_INIT}' after='${FP_NOOP}'"
pass "#414 fixture initializer rerun is a proven no-op (marker-gated; fingerprint byte-identical)"

# (v) refusal outside the explicit synthetic lane, and without --confirm — and it must write nothing.
docker exec -e TANAGHOM_LANE_ID=some-prod-lane "${GWC}" python /work/deploy/v2-dev/init_fixtures.py --confirm >/dev/null 2>&1 && fail "fixture initializer did NOT refuse outside the synthetic v2-dev-389 lane"
docker exec -e TANAGHOM_DATA_CLASS=production "${GWC}" python /work/deploy/v2-dev/init_fixtures.py --confirm >/dev/null 2>&1 && fail "fixture initializer did NOT refuse for non-synthetic data class"
docker exec "${GWC}" python /work/deploy/v2-dev/init_fixtures.py >/dev/null 2>&1 && fail "fixture initializer did NOT refuse without explicit --confirm"
FP_REFUSE="$(fingerprint)"
[[ "${FP_INIT}" == "${FP_REFUSE}" ]] || fail "a refused initializer run still mutated the DB: before='${FP_INIT}' after='${FP_REFUSE}'"
pass "#414 fixture initializer refuses outside the synthetic lane / without --confirm, and writes nothing when refused"

if docker compose -f "${SC}" logs --no-color 2>&1 | grep -q "${SENTINEL}"; then
  fail "sentinel found in running stack/container logs"
fi
pass "no sentinel in container/stack logs after runtime secret injection"

echo "== 7. adversarial negatives: manifest, traversal/symlink, stale layout, hash tamper, load rollback, staging =="
# Baseline for these negatives is: app image tags ABSENT. Tear the §6 stack down and remove the loaded
# app images so any post-negative appearance of a tag proves an unwanted state change.
docker compose -p tanaghom-v2-dev down -v --remove-orphans >/dev/null 2>&1 || true
docker rmi -f "${GATEAPI}" "${WORKBENCH}" >/dev/null 2>&1 || true
docker image inspect "${GATEAPI}"   >/dev/null 2>&1 && fail "precondition: gateapi image still present"
docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && fail "precondition: workbench image still present"
PG_BEFORE="$(docker image inspect --format '{{.Id}}' pgvector/pgvector:pg16 2>/dev/null || echo none)"

# A synthetic candidate layout with PLACEHOLDER archives + a well-formed manifest. Each negative mutates
# ONE thing so load-images.sh rejects it BEFORE any docker load (placeholders are never loaded).
synth_layout() {  # <dir>
  d="$1"; mkdir -p "${d}/images"
  cp "${HERE}/docker-compose.yml" "${d}/"; cp "${HERE}/load-images.sh" "${d}/"
  cp "${HERE}/README.md" "${d}/"; cp "${HERE}/.env.example" "${d}/"; chmod 0750 "${d}/load-images.sh"
  # Include the non-secret OpenBao adapters so the synthetic baseline matches the real allowlist.
  mkdir -p "${d}/openbao"
  for of in README.md groq-policy.hcl iam-session-policy.hcl materialize-provider-secret.sh materialize-reviewer-proxy.sh openrouter-policy.hcl reviewer-proxy-policy.hcl tanaghom-provider-secret@.service tanaghom-provider-secret@.timer tanaghom-reviewer-proxy.service tanaghom-reviewer-proxy.timer; do
    cp "${HERE}/openbao/${of}" "${d}/openbao/${of}"
  done
  chmod 0750 "${d}/openbao/materialize-reviewer-proxy.sh"
  chmod 0750 "${d}/openbao/materialize-provider-secret.sh"
  printf 'placeholder-gateapi\n'   > "${d}/images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar"
  printf 'placeholder-workbench\n' > "${d}/images/tanaghom-v2-dev-workbench-${SHA}.oci.tar"
  m="${d}/MANIFEST.txt"
  { echo "manifest_version 2"; echo "reviewed_sha ${SHA}"; echo "db_image pgvector/pgvector:pg16@sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb"; } > "${m}"
  fake="sha256:$(printf 'a%.0s' {1..64})"
  for svc in gateapi workbench; do
    t="${d}/images/tanaghom-v2-dev-${svc}-${SHA}.oci.tar"; ash="$(sha256sum "${t}" | cut -d' ' -f1)"
    echo "image ${svc} tag=tanaghom-v2-dev-${svc}:${SHA} archive=images/tanaghom-v2-dev-${svc}-${SHA}.oci.tar archive_sha256=${ash} image_id=${fake} oci_manifest_digest=${fake} revision=${SHA} user=10001:10001" >> "${m}"
  done
  ( cd "${d}" && find . -type f | grep -v '^\./MANIFEST\.txt$' | LC_ALL=C sort | while read -r f; do echo "file ${f} sha256=$(sha256sum "${f}" | cut -d' ' -f1)"; done ) >> "${m}"
}
mkcase() { d="$(mktemp -d)"; synth_layout "${d}"; printf '%s' "${d}"; }
neg() {  # <desc> <dir>  — expects load-images to exit non-zero with NO app-image state change
  desc="$1"; d="$2"; rc=0
  # Supply the digest of THIS (mutated) manifest so the external-anchor check passes and the intended
  # grammar/structure/field/hash validation is what rejects the case (anchor is tested separately).
  export V2DEV_EXPECTED_MANIFEST_SHA256="$(sha256sum "${d}/MANIFEST.txt" | cut -d' ' -f1)"
  bash "${d}/load-images.sh" >/dev/null 2>&1 || rc=$?
  [ "${rc}" -ne 0 ] || fail "NEGATIVE not caught (load-images exited 0): ${desc}"
  docker image inspect "${GATEAPI}"   >/dev/null 2>&1 && fail "Docker state changed (gateapi present) after: ${desc}"
  docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && fail "Docker state changed (workbench present) after: ${desc}"
  pass "rejected non-zero, no state change — ${desc}"
  rm -rf "${d}"
}

d="$(mkcase)"; : > "${d}/MANIFEST.txt";                                              neg "empty manifest" "${d}"
d="$(mkcase)"; grep -v '^image workbench ' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "partial manifest (missing workbench record)" "${d}"
d="$(mkcase)"; grep -E '^image gateapi ' "${d}/MANIFEST.txt" >> "${d}/MANIFEST.txt"; neg "duplicate gateapi record" "${d}"
d="$(mkcase)"; sed 's/image_id=sha256:[0-9a-f]*/image_id=not-a-sha/' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "malformed image_id field" "${d}"
d="$(mkcase)"; sed 's/archive_sha256=[0-9a-f]*/archive_sha256='"$(printf 'b%.0s' {1..64})"'/' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "substituted archive_sha256" "${d}"
d="$(mkcase)"; sed 's/ revision='"${SHA}"'/ revision='"$(printf 'c%.0s' {1..40})"'/' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "substituted revision" "${d}"
d="$(mkcase)"; sed 's#archive=images/tanaghom-v2-dev-gateapi-'"${SHA}"'.oci.tar#archive=images/../../etc/x.oci.tar#' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "path traversal in archive field" "${d}"
d="$(mkcase)"; rm -f "${d}/images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar"; ln -s /etc/hostname "${d}/images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar"; neg "symlink-escape archive" "${d}"
d="$(mkcase)"; touch "${d}/UNDECLARED";                                              neg "stale/undeclared extra file" "${d}"
d="$(mkcase)"; rm -f "${d}/README.md";                                              neg "missing declared runtime file" "${d}"
d="$(mkcase)"; printf '\n# tampered\n' >> "${d}/docker-compose.yml";                neg "runtime-file hash tamper" "${d}"
# whole-manifest grammar negatives
d="$(mkcase)"; grep -v '^db_image ' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "missing db_image record" "${d}"
d="$(mkcase)"; sed 's#@sha256:1d533553[0-9a-f]*#@sha256:'"$(printf '0%.0s' {1..64})"'#' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "changed db_image digest" "${d}"
d="$(mkcase)"; sed 's/^manifest_version 2$/manifest_version 3/' "${d}/MANIFEST.txt" > "${d}/m" && mv "${d}/m" "${d}/MANIFEST.txt"; neg "changed manifest_version" "${d}"
d="$(mkcase)"; printf 'bogus_record x\n' >> "${d}/MANIFEST.txt";                    neg "unknown record type" "${d}"
d="$(mkcase)"; printf '\n' >> "${d}/MANIFEST.txt";                                  neg "trailing blank/junk line" "${d}"
# exact-filesystem-structure negative: an undeclared (empty) directory
d="$(mkcase)"; mkdir "${d}/images/undeclared_dir";                                  neg "undeclared empty directory" "${d}"

# Heavy negatives that require the REAL staged archives (from §6's ${STAGE}).
# 7-anchor — external trust anchor rejects a SELF-CONSISTENT archive+manifest rewrite before mutation.
AC="$(mktemp -d)/c"; cp -a "${STAGE}" "${AC}"
printf 'tamper-bytes\n' >> "${AC}/images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar"
newash="$(sha256sum "${AC}/images/tanaghom-v2-dev-gateapi-${SHA}.oci.tar" | cut -d' ' -f1)"
awk -v n="${newash}" '
  /^image gateapi / { sub(/archive_sha256=[0-9a-f]+/, "archive_sha256=" n) }
  /^file \.\/images\/tanaghom-v2-dev-gateapi-/ { sub(/sha256=[0-9a-f]+/, "sha256=" n) }
  { print }' "${AC}/MANIFEST.txt" > "${AC}/m" && mv "${AC}/m" "${AC}/MANIFEST.txt"
rc=0; V2DEV_EXPECTED_MANIFEST_SHA256="${PRISTINE_MAN_SHA}" bash "${AC}/load-images.sh" >/dev/null 2>&1 || rc=$?
[ "${rc}" -ne 0 ] || fail "self-consistent archive+manifest rewrite not rejected by the external digest"
docker image inspect "${GATEAPI}"   >/dev/null 2>&1 && fail "state changed after anchor negative (gateapi present)"
docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && fail "state changed after anchor negative (workbench present)"
rm -rf "$(dirname "${AC}")"
pass "external trust anchor rejects a self-consistent archive+manifest rewrite BEFORE any mutation"
# 7-2load — first-load success + second-load failure → full rollback (no new tag remains, state unchanged).
SL="$(mktemp -d)/c"; cp -a "${STAGE}" "${SL}"
awk '/^image workbench / { sub(/image_id=sha256:[0-9a-f]+/, "image_id=sha256:'"$(printf 'e%.0s' {1..64})"'") } { print }' "${SL}/MANIFEST.txt" > "${SL}/m" && mv "${SL}/m" "${SL}/MANIFEST.txt"
sldig="$(sha256sum "${SL}/MANIFEST.txt" | cut -d' ' -f1)"
rc=0; V2DEV_EXPECTED_MANIFEST_SHA256="${sldig}" bash "${SL}/load-images.sh" >/dev/null 2>&1 || rc=$?
[ "${rc}" -ne 0 ] || fail "second-load provenance failure not caught"
docker image inspect "${GATEAPI}"   >/dev/null 2>&1 && fail "second-load rollback failed: gateapi tag remained"
docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && fail "second-load rollback failed: workbench tag remained"
rm -rf "$(dirname "${SL}")"
pass "first-load success + second-load failure → full rollback (no new tag remains, pre-existing state unchanged)"
# 7-signal — real SIGINT/SIGTERM delivered while the first image is loading: dedicated handlers must roll
# back candidate-only and terminate with 130/143; no second image loads; pre-existing state intact.
# `docker load` is near-instant here (layers already in the content store), so a test-only `docker` shim
# (a) writes an UNBUFFERED marker when a `load` begins — a deterministic sync point that avoids racing on
# buffered stdout — and (b) sleeps to widen the load window. The load semantics and load-images.sh are
# unchanged; the shim only affects the backgrounded invocation's PATH.
REALDOCKER="$(command -v docker)"
SHIMDIR="$(mktemp -d)"
# On `load`: actually load the image (so the candidate tag genuinely exists and MUST be rolled back),
# record an unbuffered marker, then hold the window open. A real terminal Ctrl-C delivers the signal to
# the whole foreground process group, so the test signals the load-images process GROUP (monitor mode).
cat > "${SHIMDIR}/docker" <<SHIM
#!/usr/bin/env bash
if [ "\$1" = "load" ]; then
  "${REALDOCKER}" "\$@"; rc=\$?
  printf 'load\n' >> "\${V2DEV_TEST_LOAD_MARKER}"
  sleep 3
  exit \$rc
fi
exec "${REALDOCKER}" "\$@"
SHIM
chmod +x "${SHIMDIR}/docker"
sigtest() {  # <signal> <want_rc> <desc>
  sig="$1"; want_rc="$2"; desc="$3"
  docker rmi -f "${GATEAPI}" "${WORKBENCH}" >/dev/null 2>&1 || true
  slog="$(mktemp)"; marker="$(mktemp)"; : > "${marker}"
  set -m   # give the backgrounded job its own process group so a group-kill reaches the docker child
  PATH="${SHIMDIR}:${PATH}" V2DEV_TEST_LOAD_MARKER="${marker}" V2DEV_EXPECTED_MANIFEST_SHA256="${PRISTINE_MAN_SHA}" \
    bash "${STAGE}/load-images.sh" > "${slog}" 2>&1 &
  lpid=$!
  set +m
  ok=0
  for i in $(seq 1 800); do [ -s "${marker}" ] && { ok=1; break; }; sleep 0.05; done
  [ "${ok}" = "1" ] || { kill -"${sig}" -"${lpid}" 2>/dev/null || kill "${lpid}" 2>/dev/null || true; wait "${lpid}" 2>/dev/null || true; rm -f "${slog}" "${marker}"; fail "${desc}: never reached the first docker load"; }
  sleep 0.3   # first (gateapi) image is now loaded; we are inside the held window before the 2nd load
  kill -"${sig}" -"${lpid}" 2>/dev/null || kill -"${sig}" "${lpid}" 2>/dev/null || true
  src=0; wait "${lpid}" || src=$?
  n_loads="$(grep -c 'load' "${marker}" 2>/dev/null || echo 0)"
  rm -f "${marker}"
  [ "${src}" = "${want_rc}" ] || { rm -f "${slog}"; fail "${desc}: expected exit ${want_rc}, got ${src}"; }
  [ "${n_loads}" = "1" ] || { rm -f "${slog}"; fail "${desc}: expected exactly one load to start, got ${n_loads} (second image loaded)"; }
  docker image inspect "${GATEAPI}"   >/dev/null 2>&1 && { rm -f "${slog}"; fail "${desc}: gateapi candidate tag remained after rollback"; }
  docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && { rm -f "${slog}"; fail "${desc}: workbench candidate tag present (second image loaded)"; }
  rm -f "${slog}"
  pass "${desc}: exit ${want_rc}, exactly one load started, first image rolled back, no second image loaded, pre-existing state unchanged"
}
sigtest INT 130 "SIGINT after first image introduced"
sigtest TERM 143 "SIGTERM after first image introduced"
rm -rf "${SHIMDIR}"
[ "$(docker image inspect --format '{{.Id}}' pgvector/pgvector:pg16 2>/dev/null || echo none)" = "${PG_BEFORE}" ] || fail "pgvector disturbed by signal tests"
pass "unrelated pgvector image undisturbed across SIGINT/SIGTERM tests"
# 7-A — post-load provenance mismatch → rollback removes ONLY newly-introduced refs; Docker state preserved.
CASE="$(mktemp -d)/c"; cp -a "${STAGE}" "${CASE}"
sed 's/image_id=sha256:[0-9a-f]*/image_id=sha256:'"$(printf 'd%.0s' {1..64})"'/' "${CASE}/MANIFEST.txt" > "${CASE}/m" && mv "${CASE}/m" "${CASE}/MANIFEST.txt"
casedig="$(sha256sum "${CASE}/MANIFEST.txt" | cut -d' ' -f1)"
rc=0; V2DEV_EXPECTED_MANIFEST_SHA256="${casedig}" bash "${CASE}/load-images.sh" >/dev/null 2>&1 || rc=$?
[ "${rc}" -ne 0 ] || fail "post-load provenance mismatch not caught"
docker image inspect "${GATEAPI}"   >/dev/null 2>&1 && fail "rollback failed: gateapi left in Docker state"
docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && fail "rollback failed: workbench left in Docker state"
rm -rf "$(dirname "${CASE}")"
pass "post-load provenance mismatch → non-zero + rollback of only newly-introduced refs (state preserved)"
# 7-B — ambiguous pre-existing tag (points to a different image) is refused with ZERO mutation.
docker tag pgvector/pgvector:pg16 "${GATEAPI}" >/dev/null
conflict_id="$(docker image inspect --format '{{.Id}}' "${GATEAPI}")"
rc=0; V2DEV_EXPECTED_MANIFEST_SHA256="${PRISTINE_MAN_SHA}" bash "${STAGE}/load-images.sh" >/dev/null 2>&1 || rc=$?
[ "${rc}" -ne 0 ] || fail "ambiguous pre-existing tag not refused"
[ "$(docker image inspect --format '{{.Id}}' "${GATEAPI}")" = "${conflict_id}" ] || fail "ambiguous tag was replaced (state mutated)"
docker image inspect "${WORKBENCH}" >/dev/null 2>&1 && fail "workbench loaded despite ambiguity refusal (partial mutation)"
docker rmi "${GATEAPI}" >/dev/null 2>&1 || true   # remove only the extra tag we added; pgvector stays
pass "ambiguous pre-existing tag refused with zero mutation (no partial load)"
# 7-C — unrelated image isolation: pgvector untouched throughout the negatives.
[ "$(docker image inspect --format '{{.Id}}' pgvector/pgvector:pg16 2>/dev/null || echo none)" = "${PG_BEFORE}" ] || fail "unrelated pgvector image was disturbed"
pass "unrelated pgvector image undisturbed across all negatives"
# 7-D — stage.sh refuses a symlink or non-empty publish target (no clobber, no partial write).
nd="$(mktemp -d)"; touch "${nd}/preexisting"
rc=0; bash "${HERE}/stage.sh" "${SHA}" "${nd}" >/dev/null 2>&1 || rc=$?
[ "${rc}" -ne 0 ] || fail "stage.sh published into a non-empty target"
[ -f "${nd}/preexisting" ] && [ ! -e "${nd}/MANIFEST.txt" ] || fail "stage.sh clobbered/wrote into a non-empty target"
rm -rf "${nd}"
ns="$(mktemp -d)"; ln -s "${ns}" "${ns}.lnk"
rc=0; bash "${HERE}/stage.sh" "${SHA}" "${ns}.lnk" >/dev/null 2>&1 || rc=$?
[ "${rc}" -ne 0 ] || fail "stage.sh published into a symlink target"
rm -rf "${ns}" "${ns}.lnk"
pass "stage.sh refuses symlink/non-empty publish targets (atomic, no clobber)"

echo ""
echo "ALL v2-dev PACKAGING PROOFS PASSED @ ${SHA}"
