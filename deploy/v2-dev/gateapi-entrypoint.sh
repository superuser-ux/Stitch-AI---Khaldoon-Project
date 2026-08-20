#!/bin/sh
# #389 decision 2 — gate API v2-dev entrypoint. Runs a FATAL packaging-boundary runtime-SHA guard, THEN
# the unchanged governed initialization fail-fast, THEN uvicorn — all inside the gateapi container
# startup (no separate init service; the topology stays exactly three services). This is packaging /
# provenance behavior, NOT product functionality: it adds no HTTP endpoint or product surface. The
# public image's default serve-only CMD is unchanged; only this private v2-dev compose overrides the
# entrypoint to point here.
#
# Runtime-SHA guard: the image bakes the exact build SHA into /work/BUILD_SHA (from the validated GIT_SHA
# build arg — see deploy/stitch-vps/Dockerfile.api). The gate API exposes NO runtime-SHA HTTP surface, so
# its runtime identity is asserted here: TANAGHOM_GATEAPI_EXPECTED_SHA (the reviewed SHA this artifact is
# expected to be) must equal the baked value. A divergence — e.g. a stale image recreated under a newer
# expected SHA — TERMINATES startup non-zero, so the container never serves a misidentified artifact. An
# absent expected value is permitted (the baked value is authoritative); a present, matching value passes.
set -eu

BAKED="$(cat /work/BUILD_SHA)"
EXPECTED="${TANAGHOM_GATEAPI_EXPECTED_SHA:-}"

if [ -n "${EXPECTED}" ] && [ "${EXPECTED}" != "${BAKED}" ]; then
  echo "FATAL: expected reviewed gateapi SHA (${EXPECTED}) does not equal the baked image BUILD_SHA (${BAKED}); refusing to serve a misidentified artifact." >&2
  exit 1
fi

# Publish the resolved (baked) identity for any in-process consumer; never a caller-supplied override.
export TANAGHOM_GATEAPI_BUILD_SHA="${BAKED}"

# #414 — READ-ONLY startup verification. init_db.py verifies schema + candidate-local ownership marker
# only: a known-owned database is checked read-only (ZERO row writes, ZERO audit rows) and a genuinely
# fresh database gets its committed schema + migrations + ownership marker (structural, one-time). It NO
# LONGER loads the methodology catalogue, seeds fixtures, or opens gates — so an ordinary restart/recreate
# never mutates persisted data or provenance history. Synthetic developer fixtures are a separate,
# explicit, idempotent, v2-dev-389-only step (deploy/v2-dev/init_fixtures.py), never run here. If this
# verification fails, the container exits non-zero and never serves.
python /work/deploy/v2-dev/init_db.py

exec uvicorn gates.api:app --host 0.0.0.0 --port 8000
