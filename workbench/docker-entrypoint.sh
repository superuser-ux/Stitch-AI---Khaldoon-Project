#!/bin/sh
# #338 — workbench runtime entrypoint. The image bakes the exact build SHA into /app/BUILD_SHA (from
# the validated GIT_SHA build arg) and into TANAGHOM_WORKBENCH_BUILD_SHA. The baked value is the sole
# authority for runtime build identity: a runtime attempt to claim a DIFFERENT SHA (an override in the
# environment) is a fatal misidentification and TERMINATES startup non-zero — the container never comes
# up reporting an identity that diverges from the artifact it was built from. An absent or matching
# override is fine; the baked value is then used.
set -eu

BAKED="$(cat /app/BUILD_SHA)"

if [ -n "${TANAGHOM_WORKBENCH_BUILD_SHA:-}" ] && [ "${TANAGHOM_WORKBENCH_BUILD_SHA}" != "${BAKED}" ]; then
  echo "FATAL: runtime TANAGHOM_WORKBENCH_BUILD_SHA override diverges from the baked image SHA; refusing to misreport build identity." >&2
  exit 1
fi

export TANAGHOM_WORKBENCH_BUILD_SHA="${BAKED}"
exec node server.js
