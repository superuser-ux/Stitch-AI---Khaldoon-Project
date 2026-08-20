import { test, expect, type Page } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #335/#380 — the V2-owned appearance system, now DETERMINISTIC LIGHT-FIRST for UAT. The host OS
// light/dark preference NEVER determines rendering (#380 acceptance 3); Dark is an explicit in-app
// selection only, and Light is the default/base. Every assertion is about PRESENTATION state on <html>
// and the computed surface color — never a canonical value.

const APP_KEY = "tanaghom.v2.appearance.v1"; // gitleaks:allow

async function bodyIsDark(page: Page): Promise<boolean> {
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  // Modern browsers return the surface as `oklch(L C H)`; L (0..1) is lightness — the direct
  // dark/light signal. Fall back to sRGB luminance if a browser ever serializes to rgb().
  const ok = bg.match(/oklch\(\s*([\d.]+)/i);
  if (ok) return parseFloat(ok[1]) < 0.5;
  const rgb = (bg.match(/[\d.]+/g) || []).map(Number);
  if (rgb.length >= 3) return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255 < 0.5;
  return false;
}

test("DETERMINISTIC LIGHT: the default renders light and the OS dark preference does NOT darken it (#380)", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(WB_URL);
  // No explicit selection → no attribute → the Light base renders, regardless of the OS being dark.
  expect(await page.locator("html").getAttribute("data-theme"), "default sets no explicit theme").toBeNull();
  expect(await bodyIsDark(page), "OS dark must NOT drive the theme (deterministic light)").toBe(false);
  // Flipping the OS the other way changes nothing either — the OS never participates.
  await page.emulateMedia({ colorScheme: "light" });
  expect(await bodyIsDark(page)).toBe(false);
});

test("explicit Dark is the only non-light state, persists, and is restored at first paint on reload (no flash)", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto(WB_URL);
  await page.getByTestId("wb-appearance-dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByTestId("wb-appearance-dark")).toHaveAttribute("aria-pressed", "true");
  expect(await bodyIsDark(page)).toBe(true);
  expect(await page.evaluate((k) => localStorage.getItem(k), APP_KEY)).toBe("dark");

  await page.reload();
  // The inline pre-paint initializer restores the attribute BEFORE paint — proven by it already being
  // present on the freshly-loaded document, with no client click.
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await bodyIsDark(page)).toBe(true);
});

test("selecting Light clears the explicit dark attribute and returns to the deterministic light base", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(WB_URL);
  await page.getByTestId("wb-appearance-dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByTestId("wb-appearance-light").click();
  // Light removes the attribute — the base :root Light renders, and the OS dark preference is ignored.
  expect(await page.locator("html").getAttribute("data-theme")).toBeNull();
  expect(await bodyIsDark(page), "Light beats the OS dark preference deterministically").toBe(false);
});

test("host OS light and dark preferences both render the same deterministic light default", async ({ page }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(WB_URL);
    expect(await page.locator("html").getAttribute("data-theme"), `${scheme} OS: no attribute`).toBeNull();
    expect(await bodyIsDark(page), `${scheme} OS still renders light`).toBe(false);
  }
});

test("stored dark preference is applied at first paint from local storage", async ({ page }) => {
  await page.addInitScript(([k, v]) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } }, [APP_KEY, "dark"]);
  await page.goto(WB_URL);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("a stale stored 'system' value degrades to the deterministic light default", async ({ page }) => {
  // A value from before #380 must not resurrect OS-following: it is malformed under the new allowlist.
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(([k, v]) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } }, [APP_KEY, "system"]);
  await page.goto(WB_URL);
  expect(await page.locator("html").getAttribute("data-theme"), "stale 'system' sets no attribute").toBeNull();
  expect(await bodyIsDark(page), "stale 'system' does NOT follow the OS — it is light").toBe(false);
});

test("storage unavailable/denied degrades safely to the light default without breaking the app", async ({ page }) => {
  // Make every localStorage access throw (private-mode / blocked-storage shape).
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() { throw new Error("storage denied"); },
    });
  });
  await page.goto(WB_URL);
  // The app renders and the pre-paint script's try/catch swallowed the failure → safe light default.
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();
  expect(await page.locator("html").getAttribute("data-theme")).toBeNull();
  // The control still operates IN-SESSION (DOM attribute) even though persistence silently fails.
  await page.getByTestId("wb-appearance-dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("appearance, direction, and schedule style are orthogonal presentation state", async ({ page }) => {
  await page.goto(WB_URL);
  await page.getByTestId("wb-dir-toggle").click();                 // → RTL
  await page.getByTestId("wb-appearance-dark").click();            // → dark
  await page.getByTestId("wb-schedule-style-editorial").click();   // → editorial
  const html = page.locator("html");
  await expect(html).toHaveAttribute("dir", "rtl");
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(html).toHaveAttribute("data-schedule-style", "editorial");
  // Changing appearance again must not disturb direction or style.
  await page.getByTestId("wb-appearance-light").click();
  await expect(html).toHaveAttribute("dir", "rtl");
  await expect(html).toHaveAttribute("data-schedule-style", "editorial");
});

test("appearance control is keyboard operable with stable accessible names", async ({ page }) => {
  await page.goto(WB_URL);
  const dark = page.getByTestId("wb-appearance-dark");
  await dark.focus();
  await expect(dark).toBeFocused();
  await expect(dark).toHaveAttribute("aria-label", "Dark appearance"); // stable name, state via aria-pressed
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

for (const scheme of ["light", "dark"] as const) {
  test(`no page-level horizontal overflow at 375px in ${scheme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(WB_URL);
    await expect(page.getByTestId("schedule-first-root")).toBeVisible();
    // brand marks remain present in both modes
    await expect(page.getByTestId("wb-brand-tanaghom")).toBeVisible();
    await expect(page.getByTestId("wb-brand-stitch")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
      .toBeLessThanOrEqual(0);
  });
}
