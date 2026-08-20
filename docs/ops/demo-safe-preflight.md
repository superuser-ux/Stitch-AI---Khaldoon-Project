# Demo-safe preflight (localhost · Tailscale · Telegram)

**Issue #5.** Run one observe-only check before any live walkthrough so a demo never looks broken.
The #1 real-world footgun: the gate API left in **writer-stub mode**, which serves deterministic
offline placeholder content and makes an otherwise-healthy review surface look corrupted.

## TL;DR

```bash
tools/demo-preflight.sh
```

- Exit **0** → safe to demo (any `WARN` items are context-dependent — see below).
- Exit **1** → **not** demo-safe; resolve the `FAIL` line(s) and re-run.
- Use `tools/demo-preflight.sh --json` for automation/CI/operator tooling that needs the same
  observe-only result in machine-readable form.

The script is **observe-only**: it never restarts a service, recreates a container, edits `.env`/
secrets, reconfigures Tailscale, or touches run/client-trial data. Safe to run repeatedly.
For the Tailscale auto-*fix* convenience (mutating), use the sibling `tools/dashboard-health-check.sh
--fix-tailscale` instead — deliberately kept separate from this read-only gate.

## What it checks

| Check | Severity if bad | Meaning |
|---|---|---|
| `dashboard` | **FAIL** | Local dashboard unreachable at `http://127.0.0.1:<port>` (default 3000). |
| `gate-api` | **FAIL** | Gate API `/health` unreachable (default `http://127.0.0.1:8009/health`). |
| `writer-mode` | **FAIL** | Writer **stub** enabled — cross-checked from `/health` (`writer_stub`) **and** the container env `TANAGHOM_WRITER_STUB`. Either signal = block. |
| `reviewer-secret` | **FAIL** / WARN | Reviewer proxy secret config (#147). **FAIL** if `/health` shows `reviewer_secret_configured:false` **and** `dev_mode:false` — review actions fail closed. **WARN** if unset but `dev_mode:true` (signing with the public dev fallback — fine locally, not a client demo). PASS when `REVIEWER_PROXY_SECRET` is set. |
| `api-port` | WARN | Gate API container publishes a different port than expected (port drift). |
| `tailscale` | WARN¹ | No Tailscale Funnel / proxy points at the wrong port → public access is off/misrouted. |
| `public-dash` | WARN¹ | The Funnel public URL isn't reachable yet. |
| `telegram` | WARN² / **FAIL** | Bot container not running (WARN); **two or more** bot containers = FAIL (Telegram allows a single long-poll — duplicates fight and drop updates). |

¹ Escalate to FAIL with `--require-funnel` for a **public-access** demo profile.
² Escalate to FAIL with `--require-telegram` for a **Telegram** demo profile.

### Severity model & exit codes
- **FAIL** = demo-blocking, confidently detected → exit **1**.
- **WARN** = fine for a localhost-only walkthrough; review before a public/Telegram demo.
- **PASS** = checked and healthy. Exit **0** when there are no FAILs.
- **Usage / invocation error** = exit **2** (for example an unknown flag, or `--json` when neither
  `python3` nor `node` is available to serialize the already-collected observe-only result).

## JSON mode

`--json` emits the same preflight outcome as valid JSON without adding or changing checks:

```bash
tools/demo-preflight.sh --json
```

High-level shape:

```json
{
  "overall_status": "pass | warn | fail",
  "demo_safe": true,
  "failure_count": 0,
  "warning_count": 1,
  "pass_count": 6,
  "options": {
    "require_funnel": false,
    "require_telegram": false
  },
  "context": {
    "dashboard_url": "http://127.0.0.1:3000",
    "api_url": "http://127.0.0.1:8009/health",
    "api_container": "tanaghom-gateapi",
    "bot_container": "tanaghom-bot"
  },
  "checks": [
    { "id": "dashboard", "name": "dashboard", "status": "pass", "message": "..." }
  ]
}
```

Notes:
- `overall_status` is `fail` when any demo-blocking failure is present, `warn` when there are no
  failures but at least one warning, else `pass`.
- `demo_safe` mirrors the existing exit-code contract: `true` when the script exits **0**, `false`
  when it exits **1**.
- `options.require_funnel` / `options.require_telegram` capture whether the stricter demo profile
  flags were enabled for that run.
- `checks[*].status` reflects the existing pass/warn/fail severity of the current script; no new
  checks are added in JSON mode.
- The `message` field contains the same safely visible non-secret summary already shown in the
  human-readable output.

### JSON examples

- Local automation / parse-and-decide:

  ```bash
  json="$(tools/demo-preflight.sh --json)"; code=$?
  printf '%s\n' "$json" | python3 -m json.tool
  test "$code" -eq 0
  ```

- Public demo profile:

  ```bash
  tools/demo-preflight.sh --json --require-funnel
  ```

- Telegram demo profile:

  ```bash
  tools/demo-preflight.sh --json --require-telegram
  ```

### Demo profiles
- **Localhost only:** defaults are enough — Funnel/Telegram warnings are expected and OK.
- **Public (Tailscale Funnel):** `tools/demo-preflight.sh --require-funnel`.
- **Telegram walkthrough:** add `--require-telegram`.

### How writer-stub is detected (and its one limitation)
Two independent, observe-only signals: the **running** mode from `GET /health` (`"writer_stub": true`)
and the **configured** env from `docker inspect <gate-api> … TANAGHOM_WRITER_STUB`. Either showing
"on" is a FAIL; a mismatch between them is a WARN (investigate). **Limitation:** if `/health` is
unreachable, the running mode can't be confirmed — the script falls back to the container env and
reports reduced confidence rather than guessing.

## Manual recovery playbook (operator steps — the script does none of this)

> Exact run commands live in `HANDOFF.md` (§ startup). The stack runs on the `tanaghom_default`
> Docker network; `.env` + `system_config.yaml` are gitignored secrets loaded via `--env-file .env`.

- **`dashboard` FAIL** — start the dashboard: `cd dashboard && API_BASE=http://localhost:8009 npx next start -p 3000` (or `pnpm dev`). If the port is taken, either free it or pass `--dashboard-port <n>`.
- **`gate-api` FAIL** — (re)start the gate API container per `HANDOFF.md` (`docker run -d --name tanaghom-gateapi … -p 8009:8000 … uvicorn gates.api:app`). Confirm with `curl -fsS http://127.0.0.1:8009/health`.
- **`writer-mode` FAIL (the important one)** — the gate API is running with `-e TANAGHOM_WRITER_STUB=1`. Re-launch it **without** that flag (drop `-e TANAGHOM_WRITER_STUB=1` from the `HANDOFF.md` run command) so real topic/script generation is used, then re-run this preflight. Keep the stub **only** for deterministic test suites, never for a live walkthrough.
- **`reviewer-secret` FAIL** — the API and dashboard have no `REVIEWER_PROXY_SECRET` and dev-mode is off, so every review action fails closed (500 / thrown). Set a real secret in `.env` — `REVIEWER_PROXY_SECRET=<a long random string>` — so it flows to **both** the API (`--env-file .env`) and the dashboard (`set -a; . ../.env`); recreate the API container and rebuild+restart the dashboard so both pick it up; re-run preflight. **Local/dev/test only:** set `TANAGHOM_DEV_MODE=1` instead to sign with the deterministic dev fallback (never for a client demo). Env changes need a container **recreate**, not `docker restart` (restart does not re-read `--env-file`).
- **`api-port` WARN** — the gate API publishes a port other than 8009. Either re-run it with `-p 8009:8000`, or point the preflight at the real one: `--api-url http://127.0.0.1:<port>/health`.
- **`tailscale` WARN/FAIL** — for public access, point the Funnel at the dashboard port: `tailscale funnel --bg <dashboard-port>` (mutating — do it deliberately, or use `dashboard-health-check.sh --fix-tailscale`). For a localhost-only demo, ignore.
- **`telegram` FAIL (duplicates)** — stop the extra bot container(s) so exactly one `tanaghom-bot` runs; Telegram long-polling is a singleton. **WARN (not running)** — start the bot only if the demo uses Telegram.

### After a crash / reboot / session restart
0. **`git pull --ff-only` first** — the API container and the dashboard build both serve the **local
   tree**, so restarting without pulling serves stale code (bit twice on 2026-07-08: a pre-merge API
   and a pre-#115 dashboard build that made green checks lie). Pull → rebuild → restart, in that order.
1. Bring the Docker network + DB up (`tanaghom-db` on `tanaghom_default`).
2. Start the gate API **without** the stub flag (see above); verify `/health`. Ensure `REVIEWER_PROXY_SECRET` is set in `.env` (or `TANAGHOM_DEV_MODE=1` for a local-only run) — otherwise review actions fail closed (#147).
3. Build/start the dashboard on :3000 (it inherits the same `.env`, so it needs the same `REVIEWER_PROXY_SECRET` / dev-mode).
4. (Public demo) re-point the Tailscale Funnel at :3000.
5. (Telegram demo) ensure a single `tanaghom-bot`.
6. Re-run `tools/demo-preflight.sh` (add `--require-funnel` / `--require-telegram` as needed) until it exits 0.
