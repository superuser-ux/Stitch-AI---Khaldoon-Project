import { test, expect } from "@playwright/test";
import { GET as runtimeGET } from "../app/api/runtime/route";

// #202 — STITCH-VPS deployment-baseline truths:
//  * /api/runtime build identity: the server-RUNTIME stamp (TANAGHOM_BUILD_SHA) ONLY — exact
//    when supplied, an explicit "unknown" when unset/blank. The bake-time client-oriented
//    NEXT_PUBLIC_BUILD_SHA is never consulted: a stale baked revision must not masquerade as
//    deployed runtime truth.
//  * the new-run dialog carries no vendor-perspective wording (#186).
// The handler tests run the REAL route module in-process (playwright's node worker) so both
// build-value paths are provable without rebuilding.

test.describe("#202 /api/runtime build identity (real handler, in-process)", () => {
  const KEYS = ["TANAGHOM_BUILD_SHA", "NEXT_PUBLIC_BUILD_SHA", "CLIENT_TRIAL_MODE",
                "TANAGHOM_OIDC_ENABLED"] as const;
  const saved: Partial<Record<(typeof KEYS)[number], string | undefined>> = {};
  test.beforeEach(() => {
    for (const k of KEYS) { saved[k] = process.env[k]; delete process.env[k]; }
  });
  test.afterEach(() => {
    for (const k of KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });

  test("the container-runtime stamp is authoritative and exact", async () => {
    process.env.TANAGHOM_BUILD_SHA = "222fab2";
    const body = await (await runtimeGET()).json();
    expect(body.build).toBe("222fab2");
    // the deployment identity this endpoint declares for the internal-review surface
    expect(body.surface).toBe("operator");
    expect(body.identity).toBe("demo");
  });

  test("unset/blank runtime stamp => explicit 'unknown'; a stale bake never masquerades", async () => {
    let body = await (await runtimeGET()).json();
    expect(body.build).toBe("unknown");              // unset -> explicit unknown

    process.env.TANAGHOM_BUILD_SHA = "   ";
    body = await (await runtimeGET()).json();
    expect(body.build).toBe("unknown");              // blank/whitespace is not a stamp

    delete process.env.TANAGHOM_BUILD_SHA;
    process.env.NEXT_PUBLIC_BUILD_SHA = "stale-baked-sha";
    body = await (await runtimeGET()).json();
    expect(body.build).toBe("unknown");              // baked value is NEVER runtime truth
  });
});

test("the new-run dialog says 'Optional run name' — no client-friendly wording (#186/#202)", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("new-run").click();
  const input = page.getByTestId("label-input");
  await expect(input).toBeVisible({ timeout: 20_000 });
  await expect(input).toHaveAttribute("placeholder", "Optional run name");
  await expect(page.locator("body")).not.toContainText(/client-friendly/i);
});
