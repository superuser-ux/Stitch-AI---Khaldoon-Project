# Methodology loader (M1)

`load_methodology.py` parses the canon (`methodology/canon/CANON-010..015`) and the
42 HCS seed records (`methodology/records/HCS_Records_All42_Seed_v1.md`) directly
from the markdown source-of-truth files and loads them into the methodology tables:
`pillar`, `lens`, `hook_type`, `format`, `hcs`.

- **Source of truth = the markdown.** The loader only transcribes it. To change the
  data, edit the canon/records files and re-run.
- **Idempotent.** Every insert is an UPSERT keyed on the natural primary key, so it is
  safe to re-run; counts are asserted at the end (5 / 42 / 5 / 5 / 7).
- **Order preserved.** Rows insert in canon order; `hcs.seq_in_pillar` records the
  within-pillar walk order for the M2 no-repeat cursor.

## Run it

The stack must be up (`docker compose up -d db`). The loader runs in a throwaway
Python container attached to the compose network, reading `DB_PASSWORD` from `.env`:

```bash
docker run --rm \
  --network tanaghom_default \
  --env-file .env \
  -e DB_HOST=db \
  -v "$PWD":/work -w /work \
  python:3.12-slim \
  bash -lc "pip install -q -r loader/requirements.txt && python loader/load_methodology.py"
```

(Run from the repo root. On Windows use Git Bash, or swap `$PWD` for `%cd%` in cmd /
`${PWD}` in PowerShell.)

Or, if you have Python + psycopg2 on the host with the DB published on `localhost:5432`:

```bash
DB_HOST=localhost DB_PASSWORD=... python loader/load_methodology.py
```
