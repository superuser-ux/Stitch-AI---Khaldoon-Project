#!/usr/bin/env node
// #293 §6 — port-conflict preflight for the V2 workbench.
//
// CONTRACT: DETECT AND REFUSE. This script NEVER kills, signals, or otherwise stops any process.
// §6 is explicit ("never stop unrelated processes"), and this repo has a scar to match: `next
// start` re-execs into `next-server`, so a broad `pkill -f "next start"` both misses the real
// server AND can hit something unrelated. Reclaiming a port is always the operator's deliberate
// act, so this tells them exactly what holds it and exits non-zero.
//
// It also refuses to run V2 on V1's port: V2 must never reuse the V1 production port (§4).
//
// SINGLE SOURCE OF TRUTH FOR THE PORT (corrected after Codex's exact-head review of 11db665):
// this script previously honoured PORT while package.json hard-coded `-p 3001`, so a successful
// preflight on an alternate port was disconnected from the process that actually started — the
// documented `PORT=<free-port> pnpm dev` override silently did nothing. The port is now resolved
// HERE and only here; package.json asks this script for it:
//
//   "dev":   "node scripts/preflight-port.mjs && next dev   -p $(node scripts/preflight-port.mjs --print)"
//   "start": "node scripts/preflight-port.mjs && next start -p $(node scripts/preflight-port.mjs --print)"
//
// The first call gates (a non-zero exit stops the `&&` chain); `--print` emits ONLY the resolved
// port on stdout so the server binds exactly what was validated.

import { execFileSync } from "node:child_process";

const V1_PORT = 3000; // V1 dashboard — reserved, never V2's.
const DEFAULT_V2_PORT = 3001;

const printOnly = process.argv.includes("--print");
const positional = process.argv.slice(2).find((a) => !a.startsWith("-"));
const requested = Number(process.env.PORT || positional || DEFAULT_V2_PORT);

if (!Number.isInteger(requested) || requested < 1 || requested > 65535) {
  console.error(`preflight: "${process.env.PORT || positional}" is not a valid port.`);
  process.exit(2);
}

if (requested === V1_PORT) {
  console.error(
    `preflight: refusing port ${V1_PORT} — that is V1's production port (#293 §4: V2 must not ` +
      `reuse V1's production port, take its default root route, or replace its GFWS service).\n` +
      `  V2's port is ${DEFAULT_V2_PORT}.`,
  );
  process.exit(1);
}

// --print resolves the port for package.json's `-p` flag. It still enforces the V1-port refusal
// above, so the printing path can never hand `next` a port the gate rejected.
if (printOnly) {
  process.stdout.write(String(requested));
  process.exit(0);
}

/** Who is listening on `port`, or null. Read-only: lsof only reports. */
function holder(port) {
  try {
    const out = execFileSync("lsof", ["-tnP", `-iTCP:${port}`, "-sTCP:LISTEN"], {
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
    if (!out) return null;
    const pid = out.split(/\s+/)[0];
    let cmd = "unknown";
    try {
      cmd = execFileSync("ps", ["-o", "comm=", "-p", pid], { stdio: ["ignore", "pipe", "ignore"] })
        .toString()
        .trim();
    } catch {
      /* pid vanished between calls — report what we have */
    }
    return { pid, cmd };
  } catch {
    return null; // lsof exits non-zero when nothing is listening
  }
}

const held = holder(requested);
if (held) {
  console.error(
    `preflight: port ${requested} is already in use by pid ${held.pid} (${held.cmd}).\n` +
      `  V2 will NOT stop it — that is your call. To reclaim it deliberately:\n` +
      `    kill $(lsof -tnP -iTCP:${requested} -sTCP:LISTEN)\n` +
      `  Or run V2 elsewhere:  PORT=<free-port> pnpm dev`,
  );
  process.exit(1);
}

console.log(`preflight: port ${requested} is free (V1's ${V1_PORT} is untouched).`);
