# Penpot MCP Local Setup Runbook

Last verified: 2026-07-04

This runbook captures the Tanaghom-local Penpot MCP setup so future Codex or Claude sessions do not need to rediscover it.

## Scope

This project uses:

- A self-hosted Penpot stack running in Docker on this Mac.
- A separate local Penpot MCP runtime running as a Node process on the host.
- A Penpot plugin loaded from the local MCP plugin server into an open Penpot design file.

This is the official Penpot **local MCP** flow, not the hosted/remote MCP flow.

## Authoritative References

- Penpot Help Center: `https://help.penpot.app/mcp/`
- Penpot MCP README: `https://github.com/penpot/penpot/blob/main/mcp/README.md`

Important documentation notes from the official sources:

- Local MCP uses `http://localhost:4401/mcp` and no MCP key.
- The local plugin is loaded from `http://localhost:4400/manifest.json`.
- The plugin must be opened inside a real Penpot design file and kept open while MCP is in use.
- MCP acts on the currently focused page in the active Penpot tab.
- Chromium-based browsers may require explicit permission to allow localhost/private-network access from Penpot.

## Local Environment Baseline

### Penpot containers

Observed live on 2026-07-03:

- `penpot_compose-penpot-frontend-1` -> `penpotapp/frontend:latest`
- `penpot_compose-penpot-backend-1` -> `penpotapp/backend:latest`
- `penpot_compose-penpot-exporter-1` -> `penpotapp/exporter:latest`
- `penpot_compose-penpot-postgres-1` -> `postgres:15`
- `penpot_compose-penpot-redis-1` -> `redis:7.2`

Frontend entry point:

- `http://localhost:9001`

Compose source on this Mac:

- `/Users/Kay/penpot_compose/docker-compose.yaml`

### Host Node runtime

Observed live on 2026-07-03:

- `node`: `v22.22.3`
- `npm`: `10.9.8`
- active binaries from: `/Users/Kay/.local/bin`
- actual Node install backing that path: `/Users/Kay/.hermes/node/bin/node`

### Penpot MCP package

Observed live on 2026-07-03:

- `npm view @penpot/mcp dist-tags --json`
- `stable = 2.15.4`
- `latest = 2.15.4`
- Penpot source tag in use locally: `2.16.2`
- MCP package version after running `mcp/scripts/set-version` in the `2.16.2` source tree: `2.16.2`

Note:

- Penpot's README says to use the released MCP version appropriate for the Penpot version.
- Penpot's Help Center currently documents `npx -y @penpot/mcp@stable` for local production use.
- On this Mac, `@penpot/mcp@stable` was version `2.15.4`, which was incompatible with the running Penpot UI `2.16.2` and produced a version-mismatch warning in the plugin.
- The correct working setup for this machine is therefore the MCP package built from the official Penpot source tag `2.16.2`, not the published npm `stable` package.
- Because the local Penpot containers currently use `:latest`, version drift is possible. If MCP stops working after a Penpot update, re-check both official references, re-check `npm view @penpot/mcp dist-tags --json`, and compare against the running Penpot version shown in the Penpot UI.

## What Broke On This Mac

Initial local launch failed with:

```bash
/bin/sh: corepack: command not found
```

Root cause:

- The active Node/npm came from the Hermes-managed install in `~/.local/bin`.
- `corepack` existed only under older `~/.nvm/...` installs and was not on the active `PATH`.

Second blocker after restoring `corepack`:

- `pnpm` refused dependency build scripts for `esbuild` and `sharp`.
- This was resolved by approving builds once in the installed package workspace.

Restart-specific Penpot blocker after a system reboot:

- Penpot frontend could return `502 Bad Gateway` even while all containers were nominally `Up`.
- Root cause on this Mac was twofold:
  - backend and exporter both need the same explicit `PENPOT_SECRET_KEY` in `/Users/Kay/penpot_compose/docker-compose.yaml`
  - after backend recreation, the frontend nginx process can keep proxying to the old backend container IP until the frontend container itself is restarted

## Stable Setup Procedure

### 1. Confirm Penpot is up

```bash
curl -I http://localhost:9001
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' | rg penpot
```

Expected:

- `http://localhost:9001` returns `200 OK`
- frontend container is running

If `http://localhost:9001` loads the branded Penpot page shell but API calls fail with `502 Bad Gateway`, do not stop here. Continue to the recovery section below.

### 2. Restore `corepack` if missing

```bash
which corepack || npm install -g corepack
corepack enable
which corepack
corepack --version
```

Expected:

- `corepack` resolves under `/Users/Kay/.local/bin/corepack`

### 3. Prepare the aligned Penpot MCP source tree

```bash
mkdir -p /Users/Kay/.local/share/penpot-mcp
git clone --depth 1 --branch 2.16.2 https://github.com/penpot/penpot.git /Users/Kay/.local/share/penpot-mcp/penpot-2.16.2
cd /Users/Kay/.local/share/penpot-mcp/penpot-2.16.2/mcp
bash scripts/set-version
```

Expected working location on this Mac:

```bash
/Users/Kay/.local/share/penpot-mcp/penpot-2.16.2/mcp
```

Notes:

- `scripts/set-version` is required because the compatibility check in the plugin compares the exact `major.minor.patch` prefix of the MCP package version against the running Penpot version.
- In the official `2.16.2` source tag, this step updates the MCP package version to `2.16.2`, which removes the mismatch warning.

### 4. Bootstrap the source-aligned package once

Run from the package root:

```bash
cd /Users/Kay/.local/share/penpot-mcp/penpot-2.16.2/mcp
corepack pnpm install
npm pkg set 'pnpm.onlyBuiltDependencies[0]=esbuild' 'pnpm.onlyBuiltDependencies[1]=sharp'
corepack pnpm rebuild
corepack pnpm run build
```

Notes:

- In `pnpm@10.31.0`, `approve-builds --all` is not available. The working fix on this Mac was to set `pnpm.onlyBuiltDependencies` for `esbuild` and `sharp`, then run `corepack pnpm rebuild`.
- After approval, the build should complete successfully for both `packages/plugin` and `packages/server`.

### 5. Start the local plugin server and MCP server

Preferred repo-owned launcher:

```bash
/Users/Kay/Dev/tanaghom/tools/start-penpot-mcp.sh
```

This launcher:

- ensures `corepack` is available
- ensures the Penpot `2.16.2` source tree exists locally
- runs `mcp/scripts/set-version`
- applies the `pnpm.onlyBuiltDependencies` fix for `esbuild` and `sharp`
- installs/builds if required
- starts the aligned MCP runtime from the correct path

Optional bootstrap-only mode:

```bash
/Users/Kay/Dev/tanaghom/tools/start-penpot-mcp.sh --bootstrap-only
```

Direct manual start remains valid if needed.

Run from the package root:

```bash
cd /Users/Kay/.local/share/penpot-mcp/penpot-2.16.2/mcp
corepack pnpm run start
```

Expected runtime endpoints:

- plugin preview server: `http://localhost:4400/`
- plugin manifest: `http://localhost:4400/manifest.json`
- MCP HTTP endpoint: `http://localhost:4401/mcp`
- legacy SSE endpoint: `http://localhost:4401/sse`
- Penpot plugin WebSocket bridge: `ws://localhost:4402`
- REPL helper: `http://localhost:4403`

Expected server log lines include:

- `Local: http://localhost:4400/`
- `Modern Streamable HTTP endpoint: http://localhost:4401/mcp`
- `Legacy SSE endpoint: http://localhost:4401/sse`
- `WebSocket server URL: ws://localhost:4402`

## Verified Host-Side Checks

These were verified live on 2026-07-03.

### Manifest check

```bash
curl -sS -D - http://localhost:4400/manifest.json
```

Expected:

- HTTP `200 OK`
- JSON manifest for `Penpot MCP Plugin`

### MCP endpoint check

```bash
curl -sS -D - http://localhost:4401/mcp
```

Expected:

- HTTP `406 Not Acceptable`
- error message requiring `text/event-stream`

This is a healthy sign that the server is listening and enforcing protocol expectations.

### SSE transport check

```bash
curl -sS -N -H 'Accept: text/event-stream' --max-time 3 http://localhost:4401/sse
```

Expected:

- an SSE `event: endpoint`
- a `sessionId`-scoped message URL in the response body

### Port listener check

```bash
lsof -nP -iTCP:4400 -iTCP:4401 -iTCP:4402 -iTCP:4403 -sTCP:LISTEN
```

Expected listeners:

- `4400`
- `4401`
- `4402`
- `4403`

## Penpot-Side Prerequisites

Do not skip these. Host-side servers being up is not sufficient.

### Required Penpot state

- Penpot must be open at `http://localhost:9001`
- the user must be logged in
- a real design file must be open
- the target page must be focused
- only one Penpot tab should be treated as the active MCP tab

### Required browser behavior

- if using a Chromium-based browser, approve localhost/private-network access when prompted
- if the browser blocks the plugin from reaching localhost, try Firefox or relax the relevant local-network restriction

## Penpot Plugin Setup

For this local flow, use the local plugin manifest. Do not confuse this with the hosted/remote MCP setup.

### Inside Penpot

1. Open a design file.
2. Open `Plugins`.
3. Use `Load from URL`.
4. Load `http://localhost:4400/manifest.json`.
5. Open the Penpot MCP plugin UI.
6. Click `Connect to MCP server`.

Expected:

- the plugin changes from not connected to connected
- the plugin stays open while MCP is being used

Important:

- if the plugin window is closed, the MCP bridge is lost
- if the focused page changes, MCP context follows the newly focused page

## MCP Client Setup

For Codex/OpenCode-style HTTP MCP clients, the official docs describe this shape:

```json
{
  "servers": {
    "penpot": {
      "url": "http://localhost:4401/mcp",
      "transport": {
        "type": "http"
      }
    }
  }
}
```

For local MCP:

- URL: `http://localhost:4401/mcp`
- transport: `http`
- auth: none

## First Validation Prompts

Start read-only. The official docs recommend this pattern and it should be followed here.

Suggested first prompts:

- `List pages in this file.`
- `Show all components on this page.`
- `Analyze the structure of this design and summarize it.`
- `List the color styles and explain how they are used.`

Only after read-only validation should write actions be attempted.

## Current Known Good State

Verified on 2026-07-04:

- Penpot frontend reachable at `http://localhost:9001`
- `curl -sS -D - http://localhost:9001/api/main/methods/get-profile` returns `200 OK` with the anonymous-user payload when not logged in
- source-aligned local Penpot MCP runtime builds successfully after:
  - `npm install -g corepack`
  - `bash scripts/set-version`
  - `npm pkg set 'pnpm.onlyBuiltDependencies[0]=esbuild' 'pnpm.onlyBuiltDependencies[1]=sharp'`
  - `corepack pnpm rebuild`
- plugin manifest responds successfully from `http://localhost:4400/manifest.json`
- MCP transport responds successfully from `http://localhost:4401/mcp`
- SSE endpoint responds successfully from `http://localhost:4401/sse`
- ports `4400`, `4401`, `4402`, `4403` are listening
- Penpot plugin on the `2.16.2` source-aligned runtime shows `Connected` without the previous version mismatch warning
- after reboot recovery, the in-app browser returns to `http://localhost:9001/#/auth/login` and renders the Penpot login screen normally

Not yet captured in repository automation:

- a fully automated Penpot UI/plugin-connect flow
- a persisted Codex MCP server registration flow for future threads

## Recovery Checklist

If Penpot MCP stops working, check in this order:

1. Penpot containers still running and `http://localhost:9001` still loads.
2. `corepack` still resolves from the active Node install.
3. `corepack pnpm run start` is still running in `/Users/Kay/.local/share/penpot-mcp/penpot-2.16.2/mcp`.
4. `http://localhost:4400/manifest.json` still returns `200`.
5. `http://localhost:4401/mcp` still responds.
6. The Penpot plugin is still loaded from the local manifest.
7. The plugin UI is still open.
8. The plugin shows connected status.
9. The target design file and page are actually open in the active Penpot tab.
10. Browser localhost/private-network access has not been blocked.

### Penpot reboot recovery

If Penpot itself shows `Bad Gateway` after a reboot or container recreate, use this order:

1. Confirm backend and exporter both share the same `PENPOT_SECRET_KEY` in `/Users/Kay/penpot_compose/docker-compose.yaml`.
2. Recreate the Penpot compose stack from `/Users/Kay/penpot_compose`:

```bash
docker compose up -d
```

3. Probe the Penpot API directly:

```bash
curl -sS -D - http://localhost:9001/api/main/methods/get-profile
```

Expected healthy result when logged out:

- HTTP `200 OK`
- body contains `Anonymous User`

4. If the probe still returns `502`, inspect the frontend log:

```bash
docker logs --tail 120 penpot_compose-penpot-frontend-1
```

5. If nginx is proxying to an old backend IP such as `172.26.0.4:6060` while `docker inspect penpot_compose-penpot-backend-1` shows a different current IP, restart only the frontend:

```bash
cd /Users/Kay/penpot_compose
docker compose restart penpot-frontend
```

6. Re-run the API probe. On this Mac, this frontend restart was the fix that cleared the post-reboot `502`.

## Maintenance Rule

Whenever any of the following changes, update this runbook and the continuity notes in `HANDOFF.md` and `BUILD_STATE.md`:

- Penpot Docker image tags or topology
- Penpot base URL/port
- Node runtime source or version manager
- `@penpot/mcp` version or dist-tags
- local bootstrap steps
- required build approvals
- local ports
- plugin load path
- client connection method

After any such change, re-run the host-side verification commands in this document before declaring the environment stable again.
