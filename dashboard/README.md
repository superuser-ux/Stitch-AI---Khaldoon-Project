# Dashboard (M4) — RTL review queue

Next.js (App Router, RTL/Arabic) review surface for the approval gate. It talks to the
gate **API** (`gates/api.py`, FastAPI over `engine.py`) — same logic as the CLI + Telegram
bot. `/gw/*` is proxied by a Next route handler to the API (`API_BASE`) and carries the
selected reviewer identity through the internal proxy seam.

## Run (two terminals)
1. Gate API (port 8000):
   ```bash
   docker run --rm --network tanaghom_default --env-file ../.env -e DB_HOST=db -e DB_PORT=5432 \
     -p 8000:8000 -v "$PWD/..":/work -w /work python:3.12-slim \
     bash -lc "pip install -q -r gates/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000"
   ```
2. Dashboard (port 3000):
   ```bash
   cd dashboard && pnpm install && pnpm dev
   ```
Open http://localhost:3000 — pick the reviewer, open a gate for R1, approve/reject/request-change
per row or in bulk, preview scripts, then “احسم البوابة” (resolve) to push approved → APPROVED_ASSIGNED.
