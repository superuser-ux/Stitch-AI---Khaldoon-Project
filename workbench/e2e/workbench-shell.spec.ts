import { test, expect } from "@playwright/test";
import { WB_URL, VIEWPORTS } from "./surfaces";

// #293 A7 / #331 — the ONE coherent shell and the schedule-first root.
//
// The shell (brand header + single <main> + brand footer) is mounted once in app/layout.tsx and wraps
// EVERY route. This spec proves it is truthful and coherent: brand marks at every viewport, RTL-safe,
// a single <main> with no second stacked region, and the same chrome present on the run route. It also
// proves the root's real read path and its truthful error/empty states — retargeted from the removed
// Stage-0 "Runs / Canonical slots" panel to the schedule-first run index.

test.describe("responsive shell (real read path)", () => {
  for (const vp of VIEWPORTS) {
    test(`no horizontal overflow at ${vp.label}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(WB_URL);
      await expect(page.getByTestId("schedule-first-root")).toBeVisible();

      await expect
        .poll(
          () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
          { message: `page must not scroll horizontally at ${vp.label}` },
        )
        .toBeLessThanOrEqual(0);

      // The marks stay visible at every viewport — never behind a responsive branch (§3).
      await expect(page.getByTestId("wb-brand-tanaghom")).toBeVisible();
      await expect(page.getByTestId("wb-brand-stitch")).toBeVisible();
    });
  }
});

test("ONE coherent shell: exactly one <main>, no second stacked region, footer after main (#331 A1/A10)", async ({ page }) => {
  await page.goto(WB_URL);
  // The single shell <main> — the old double-main / calendar-after-footer composition is gone.
  await expect(page.getByTestId("wb-main")).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);
  await expect(page.getByTestId("wb-footer")).toHaveCount(1);
  // The schedule-first root lives INSIDE the shell main, not after the footer.
  const rootInMain = await page.evaluate(() => {
    const main = document.querySelector('[data-testid="wb-main"]');
    const root = document.querySelector('[data-testid="schedule-first-root"]');
    return !!(main && root && main.contains(root));
  });
  expect(rootInMain, "the schedule-first root must be inside the single shell main").toBe(true);
});

test("the shell is coherent on the run route too — same chrome, single main (#331)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  test.skip(!rows?.length, "no runs in this fixture");
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(rows[0].round_id)}`);
  await expect(page.getByTestId("wb-header")).toBeVisible();
  await expect(page.getByTestId("wb-footer")).toBeVisible();
  await expect(page.getByTestId("wb-brand-tanaghom")).toBeVisible();
  await expect(page.getByTestId("wb-brand-stitch")).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);
  // The direction toggle lives in the shell header, reachable on the run route without its own copy.
  await expect(page.getByTestId("wb-dir-toggle")).toBeVisible();
});

test("RTL safety — direction flips on <html> and the layout survives at 375px", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(WB_URL);
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");

  await page.getByTestId("wb-dir-toggle").click();

  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  // #315 ruling 3 — the toggle flips ONLY `dir`; the chrome stays lang="en".
  await expect(page.locator("html")).toHaveAttribute("lang", "en");

  await expect(page.getByTestId("wb-brand-tanaghom")).toBeVisible();
  await expect(page.getByTestId("wb-brand-stitch")).toBeVisible();
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();

  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
    )
    .toBeLessThanOrEqual(0);
});

test("real read path: the runs schedule comes from the live API", async ({ page }) => {
  await page.goto(WB_URL);

  // Runtime identity is server truth, not a placeholder.
  await expect(page.getByTestId("wb-runtime-surface")).toHaveText("workbench");
  await expect(page.getByTestId("wb-api-writer")).not.toHaveText("…");

  // The seam resolves to exactly one truthful terminal state — never a static shell.
  await expect
    .poll(async () => {
      for (const id of ["runs-calendar", "runs-calendar-empty", "runs-calendar-read-error"]) {
        if (await page.getByTestId(id).isVisible().catch(() => false)) return id;
      }
      return "loading";
    })
    .not.toBe("loading");
});

test("truthful ERROR state (induced): a failed run read says so and offers retry — never a fake empty", async ({ page }) => {
  let fail = true;
  await page.route("**/gw/rounds", async (route) => {
    if (fail) {
      fail = false;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "tanaghom api unreachable" }) });
      return;
    }
    await route.fallback();
  });

  await page.goto(WB_URL);

  const err = page.getByTestId("runs-calendar-read-error");
  await expect(err).toBeVisible();
  await expect(err).toContainText("tanaghom api unreachable");
  // A failed read must NOT render as "no runs".
  await expect(page.getByTestId("runs-calendar-empty")).toHaveCount(0);

  await page.getByTestId("runs-calendar-retry").click();
  await expect(page.getByTestId("runs-calendar-read-error")).toHaveCount(0);
});

test("V2's own runtime identity survives an api outage (regression: real-path defect found at 11db665)", async ({ page }) => {
  await page.route("**/gw/health", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "tanaghom api unreachable" }) }),
  );
  await page.goto(WB_URL);

  await expect(page.getByTestId("wb-runtime-surface")).toHaveText("workbench");
  await expect(page.getByTestId("wb-runtime-build")).not.toHaveText("…");
  await expect(page.getByTestId("wb-runtime-build")).not.toHaveText("unknown");
  await expect(page.getByTestId("wb-api-writer")).toHaveText("unavailable");
  await expect(page.getByTestId("wb-runtime-error")).toBeVisible();
});

test("truthful EMPTY state (induced): a genuinely empty result reads as empty, not as an error", async ({ page }) => {
  await page.route("**/gw/rounds", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.goto(WB_URL);

  await expect(page.getByTestId("runs-calendar-empty")).toBeVisible();
  await expect(page.getByTestId("runs-calendar-empty")).toContainText("No runs yet");
  await expect(page.getByTestId("runs-calendar-read-error")).toHaveCount(0);
});
