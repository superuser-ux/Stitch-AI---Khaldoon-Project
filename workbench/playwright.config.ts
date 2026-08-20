import { defineConfig } from "@playwright/test";

// #293 Stage 0 evidence suite (D3-scoped: responsive/RTL/branding/truthful-state/coexistence and
// deterministic non-mutation evidence ONLY — no feature coverage, no lifecycle behaviour).
//
// It deliberately inherits V1's #263 validation discipline verbatim: serial, single worker, ZERO
// retries. This suite drives the SHARED dev DB read path, so parallelism would be unsafe, and a
// retry would let a failure be re-run until it passed — the exact dishonesty #263 forbids.
//
// It drives BOTH surfaces:
//   V1 = http://localhost:3000  (unchanged; this suite only READS it)
//   V2 = http://localhost:3001
// Asserting V1's branding from HERE is what lets #293 evidence acceptance A6 for both UIs while
// keeping the V1 diff provably empty — no spec is added under dashboard/.

const wbUrl = new URL(process.env.WB_URL || "http://localhost:3001");
const channel = process.env.PLAYWRIGHT_CHANNEL || undefined;

// V1's shell is reached as an established reviewer, mirroring dashboard/playwright.config.ts's
// #170 rationale. Cookies are port-agnostic, so this also reaches :3001 — harmless: V2 reads no
// cookie and asserts no identity (its seam is unauthenticated by design, D2).
const establishedReviewer = {
  cookies: [
    {
      name: "tanaghom_reviewer",
      value: "khal",
      domain: wbUrl.hostname,
      path: "/",
      expires: -1,
      httpOnly: true,
      secure: false,
      sameSite: "Lax" as const,
    },
  ],
  origins: [],
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.WB_URL || "http://localhost:3001",
    storageState: establishedReviewer,
    trace: "retain-on-failure",
  },
  // #348 — TWO NAMED GATES over two deliberately incompatible fixture lanes.
  //
  // WHY. The product-regression lane needs ~18 generated/review fixtures; the synthetic acceptance
  // lane must contain EXACTLY four runs, and asserting that is the whole point of #342's evidence
  // ("a reviewer sees the scenario, not a hundred leftovers"). No single dataset satisfies both, so
  // one undifferentiated invocation could only ever be green by weakening one of them. At #342 head
  // that showed up as 166 accounted tests with all seven non-passes being the acceptance spec run
  // against the 18-run lane. Splitting the SELECTION — not the assertions — is the honest fix.
  //
  // THE SELECTION IS DEFINED BY EXCLUSION, ON PURPOSE. `product-regression` is "every spec that is
  // not the acceptance spec", so a spec added tomorrow automatically belongs to a gate and cannot
  // fall into neither. An explicit include-list would satisfy union accounting the day it was
  // written and silently drop the first spec someone adds. Exhaustiveness has to be structural.
  //
  // Consequences that are deliberate, not incidental:
  //   - The projects are DISJOINT by construction (testMatch and testIgnore are exact complements
  //     over the same testDir), so no test can be counted twice.
  //   - Their UNION equals native discovery: `playwright test --list` with no `--project` enumerates
  //     both, so "did we lose a spec?" is one command, not an argument.
  //   - Neither project is named `chromium` any more. That name reads as "all Chromium tests" while
  //     now denoting a PARTIAL selection, and calling a partial selection a full suite is exactly
  //     the false-green this repo has been bitten by. Each gate name states which lane it needs.
  //
  // NEVER add `--pass-with-no-tests` to make an empty selection succeed. An empty gate reporting
  // success is a concealed omission — the precise failure mode this split exists to prevent. An
  // empty selection must keep failing loudly ("No tests found", exit 1).
  //
  // Each gate is still serial / one worker / zero retries; the discipline is unchanged and shared.
  projects: [
    {
      // Runs against the DETERMINISTIC product-regression fixture lane (#345 topology).
      name: "product-regression",
      testIgnore: /acceptance-lane-342\.spec\.ts/,
      use: { browserName: "chromium", ...(channel ? { channel } : {}) },
    },
    {
      // Runs against the SYNTHETIC acceptance lane only (tanaghom_acc342, exactly four runs).
      name: "synthetic-acceptance",
      testMatch: /acceptance-lane-342\.spec\.ts/,
      use: { browserName: "chromium", ...(channel ? { channel } : {}) },
    },
  ],
});
