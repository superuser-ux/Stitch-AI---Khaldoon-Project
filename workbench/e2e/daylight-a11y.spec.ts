import { test, expect, type Page } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #380 — Tanaghom Daylight accessibility contract: every interactive element shows a VISIBLE focus
// indicator, keyboard-only traversal reaches the primary controls, and the deterministic light theme
// holds under both host-OS preferences and RTL. Presentation-only assertions — no canonical value is
// read or written. Contrast is proven separately and deterministically by scripts/daylight-contrast.mjs.

/** Does the focused element paint a visible focus ring? The Daylight base rule gives every
 *  :focus-visible affordance a 2px outline in the focus token; keyboard focus triggers :focus-visible. */
async function hasVisibleFocusRing(page: Page): Promise<boolean> {
  return await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return false;
    const s = getComputedStyle(el);
    const width = parseFloat(s.outlineWidth || "0");
    const ring = width > 0 && s.outlineStyle !== "none";
    const boxShadow = !!s.boxShadow && s.boxShadow !== "none";
    return ring || boxShadow;
  });
}

test("every header control shows a visible focus ring under keyboard focus", async ({ page }) => {
  await page.goto(WB_URL);
  for (const id of ["wb-appearance-light", "wb-appearance-dark", "wb-schedule-style-editorial", "wb-dir-toggle"]) {
    const el = page.getByTestId(id).first();
    await el.focus();
    await expect(el, `${id} is focused`).toBeFocused();
    expect(await hasVisibleFocusRing(page), `${id} shows a visible focus indicator`).toBe(true);
  }
});

test("keyboard-only traversal reaches New run and opens the composer, whose actions are all reachable", async ({ page }) => {
  await page.goto(WB_URL);
  // Tab from the top of the document until the New run control receives focus — proving it is in the
  // natural tab order (not merely click-reachable). Bounded so a regression that drops it out of the
  // order fails instead of hanging.
  const newRun = page.getByTestId("new-run");
  let reached = false;
  for (let i = 0; i < 40 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached = await newRun.evaluate((n) => n === document.activeElement).catch(() => false);
  }
  expect(reached, "New run is reachable by keyboard alone").toBe(true);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("run-composer")).toBeVisible();

  // Each composer affordance shows a visible focus ring when tabbed to.
  for (const id of ["composer-starts-on", "composer-ends-on", "composer-posts", "composer-recommend", "composer-cancel"]) {
    const el = page.getByTestId(id);
    await el.focus();
    await expect(el).toBeFocused();
    expect(await hasVisibleFocusRing(page), `${id} shows a visible focus indicator`).toBe(true);
  }
});

test("the deterministic light theme holds under RTL and both OS preferences (visible focus preserved)", async ({ page }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(WB_URL);
    // Toggle direction via KEYBOARD (focus the control, press Enter) so the interaction modality stays
    // keyboard — a preceding POINTER click would suppress :focus-visible on the subsequent focus and
    // make this assert nothing. This is the same reason the ring is real for keyboard users.
    const toggle = page.getByTestId("wb-dir-toggle");
    await toggle.focus();
    await page.keyboard.press("Enter");                             // → RTL
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    // Still light (no explicit theme) regardless of the OS scheme, and focus stays visible in RTL.
    expect(await page.locator("html").getAttribute("data-theme")).toBeNull();
    const bgL = await page.evaluate(() => {
      const m = getComputedStyle(document.body).backgroundColor.match(/oklch\(\s*([\d.]+)/i);
      return m ? parseFloat(m[1]) : 1;
    });
    expect(bgL, `light canvas under OS ${scheme} + RTL`).toBeGreaterThan(0.5);
    await page.getByTestId("new-run").focus();
    expect(await hasVisibleFocusRing(page), "focus visible in RTL").toBe(true);
  }
});
