#!/bin/sh
# #338 — gateapi acceptance entrypoint. Runs the unchanged governed initialization fail-fast BEFORE
# uvicorn, inside the gateapi container startup (no separate init service — the topology stays exactly
# three services). If initialization fails, the container exits non-zero and never serves. Used only by
# the private acceptance compose (which overrides the image's default serve-only CMD); the public image
# default is unchanged.
set -eu

python /work/deploy/acceptance/init_db.py
exec uvicorn gates.api:app --host 0.0.0.0 --port 8000
