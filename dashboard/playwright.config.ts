import { defineConfig } from "@playwright/test";

const channel = process.env.PLAYWRIGHT_CHANNEL || undefined;
const dashUrl = new URL(process.env.DASH_URL || "http://localhost:3000");

// #170 — existing specs always acted as the default reviewer implicitly (no cookie). The demo
// persona entry surface now appears for a browser with NO established reviewer, so the shared
// context starts as an established "khal" session (the same identity the suite always ran as).
// persona-entry.spec.ts opts out with an empty storageState to exercise the fresh-browser path.
const establishedReviewer = {
  cookies: [{
    name: "tanaghom_reviewer",
    value: "khal",
    domain: dashUrl.hostname,
    path: "/",
    expires: -1,
    httpOnly: true,
    secure: false,
    sameSite: "Lax" as const,
  }],
  origins: [],
};

// Drives the REAL dashboard (:3000) against the live gate API (:8009). For deterministic
// regeneration the API must run with TANAGHOM_WRITER_STUB=1 (the stub writer). globalSetup
// seeds an isolated round (RE2E) via the engine. Behaviour ground-truth, independent of UI polish.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  // #263 tiered-validation contract — these are load-bearing at EVERY tier and must not change:
  // serial, single worker (shared dev DB — never parallel), and ZERO retries (a failure is reported
  // truthfully, never retried until it passes). See CLAUDE.md "Validation tiers".
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.DASH_URL || "http://localhost:3000",
    storageState: establishedReviewer,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium", ...(channel ? { channel } : {}) } }],
});
