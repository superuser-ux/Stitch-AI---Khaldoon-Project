#!/usr/bin/env node
// #263 — affected-spec guard shared by `test:spec` (inner loop) and `test:pr` (PR checkpoint).
// It REQUIRES at least one positional spec path (a `*.spec.ts` file) and rejects an empty or
// option-only invocation, so neither command can silently fall through to an unfiltered full
// Chromium run (which would break the affected-spec/PR-checkpoint contract and produce misleading
// tier evidence). Supplied spec paths + flags pass through UNCHANGED. Serial, single-worker,
// zero-retry and shared-DB non-overlap are enforced by playwright.config (workers:1,
// fullyParallel:false, retries:0) — this wrapper never overrides them. Full suite: `npm run test:full`.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
// A spec path is a positional (non-option) token naming a Playwright spec file. Requiring the
// documented `*.spec.ts` form rejects both bare flags (`--headed`) and option VALUES (`--grep foo`),
// neither of which scopes the run to a spec.
const specPaths = args.filter((a) => !a.startsWith("-") && /\.spec\.[cm]?[tj]s$/.test(a));

if (specPaths.length === 0) {
  process.stderr.write(
    "error: at least one spec path (e2e/<file>.spec.ts) is required.\n" +
    "  usage: npm run test:spec -- e2e/<file>.spec.ts [more specs] [--grep <pattern>]\n" +
    "         npm run test:pr   -- e2e/<relevant>.spec.ts [more specs]\n" +
    "An empty or option-only invocation is rejected so it never runs the full suite.\n" +
    "For the full immutable-head suite use: npm run test:full\n"
  );
  process.exit(2);
}

const bin = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "..", "node_modules", ".bin",
  process.platform === "win32" ? "playwright.cmd" : "playwright",
);
// caller's args pass through UNCHANGED after the fixed project selector
const res = spawnSync(bin, ["test", "--project=chromium", ...args], { stdio: "inherit" });
process.exit(res.status ?? 1);
