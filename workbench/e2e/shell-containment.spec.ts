import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #382 — the V2 containment shell: one persistent, responsive shell that OWNS all global navigation
// chrome (side rail + top lens menu + Agent region), across `/` and `/runs/{id}`.
//
// These assertions are the shell's structural contract AND several of the mandated induced-failure red
// controls (amendment §H): a duplicate lifecycle rail, a rail that overflows or obscures controls at
// 375px, and a malformed persisted rail state that does not fail safe would each fail a test here.
// Presentation-only — no governed value is read or written by the shell chrome itself.

const CHROME_KEY = "wb-shell-chrome-v1";

test("one containment shell wraps the root: single main, side rail, lens menu, agent trigger", async ({ page }) => {
  await page.goto(WB_URL);
  await expect(page.getByTestId("wb-main")).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);                 // still exactly one <main>
  await expect(page.getByTestId("shell-rail")).toBeVisible();        // the rail is an <aside>, not a 2nd main
  await expect(page.getByTestId("stage-rail")).toBeVisible();
  await expect(page.getByTestId("lens-menu")).toBeVisible();
  await expect(page.getByTestId("agent-trigger")).toBeVisible();
});

test("exactly one lifecycle rail exists — no duplicate navigation authority (red control)", async ({ page }) => {
  // The regression this guards: moving the rail into the shell while the workspace still renders its own
  // would create two competing lifecycle authorities. There must be exactly one, on every route.
  await page.goto(WB_URL);
  await expect(page.getByTestId("stage-rail")).toHaveCount(1);
});

test("the side rail cycles full → icons → hidden → full via the toggle and the keyboard (#382)", async ({ page }) => {
  await page.goto(WB_URL);
  const rail = page.getByTestId("stage-rail");
  const toggle = page.getByTestId("nav-toggle");

  // Default is `full`: governed labels and provenance are visible without interaction.
  await expect(rail).toHaveAttribute("data-rail-mode", "full");
  await expect(page.getByTestId("stage-rail-provenance")).toBeVisible();

  await toggle.click();                                              // full → icons
  await expect(rail).toHaveAttribute("data-rail-mode", "icons");

  await toggle.click();                                              // icons → hidden
  await expect(page.getByTestId("shell-rail")).toHaveCount(0);

  await toggle.click();                                              // hidden → full
  await expect(rail).toHaveAttribute("data-rail-mode", "full");

  // ⌘/Ctrl-B cycles it too (keyboard parity). Focus is on <body>, not a field, so the shortcut fires.
  await page.locator("body").click();
  await page.keyboard.press("Control+b");                           // full → icons
  await expect(rail).toHaveAttribute("data-rail-mode", "icons");
});

test("rail mode persists across reload; a malformed persisted value fails safe (red control)", async ({ page }) => {
  await page.goto(WB_URL);
  await page.getByTestId("nav-toggle").click();                     // full → icons
  await expect(page.getByTestId("stage-rail")).toHaveAttribute("data-rail-mode", "icons");
  await page.reload();
  await expect(page.getByTestId("stage-rail")).toHaveAttribute("data-rail-mode", "icons"); // restored

  // A malformed / legacy value must not throw or wedge the shell — it falls back to the default.
  await page.evaluate((k) => localStorage.setItem(k, "}{ not json"), CHROME_KEY);
  await page.reload();
  await expect(page.getByTestId("stage-rail")).toHaveAttribute("data-rail-mode", "full");  // safe default
});

test("at 375px the rail is a modal overlay + scrim and the page never overflows (red control)", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(WB_URL);
  // Collapsed by default on mobile — neither the desktop column nor an open overlay is present.
  await expect(page.getByTestId("shell-rail")).toHaveCount(0);
  await expect(page.getByTestId("nav-toggle")).toBeVisible();

  await page.getByTestId("nav-toggle").click();                    // open the overlay
  const rail = page.getByTestId("shell-rail");
  await expect(rail).toBeVisible();
  await expect(rail).toHaveAttribute("data-variant", "mobile");
  await expect(page.getByTestId("shell-rail-scrim")).toBeVisible();

  // The overlay must not push the page into horizontal scroll, and header controls stay reachable.
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(0);
  await expect(page.getByTestId("wb-dir-toggle")).toBeVisible();

  // Tap the scrim in its UNCOVERED region (right of the 256px drawer, below the header) — the real
  // "tap outside to close" gesture; the drawer sits on top of the scrim's centre.
  await page.getByTestId("shell-rail-scrim").click({ position: { x: 340, y: 500 } });
  await expect(page.getByTestId("shell-rail")).toHaveCount(0);
});

// The header control cluster must be CONTAINED at 375px, on the untouched default view.
//
// Why this exists alongside the overflow assertion above: that one runs only AFTER the rail overlay is
// opened, so it proves the overlay adds no overflow — it cannot distinguish "the shell is contained"
// from "the shell already overflowed before anyone touched it". The regression this guards was exactly
// the latter: the cluster carried `shrink-0` next to its own `flex-wrap`, which pins a flex item at its
// max-content width, so the wrap never engaged. The cluster measured a constant ~586px at every
// viewport and 375px overflowed the document by 223px, pushing the Agent trigger, Process Studio and
// Secrets off-screen. Asserting per-control containment (not just a document-level number) names WHICH
// control escaped, so a future regression reports the cause rather than a bare overflow count.
test("at 375px every header control is contained on the default view (red control)", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(WB_URL);
  await expect(page.getByTestId("wb-header")).toBeVisible();

  // No horizontal document overflow BEFORE any interaction.
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(0);

  // Every header control sits inside the viewport horizontally. A control whose right edge is past the
  // viewport is unreachable without a horizontal scroll the page must never have.
  const escaped = await page.evaluate(() => {
    const header = document.querySelector('[data-testid="wb-header"]');
    if (!header) return ["wb-header missing"];
    const limit = document.documentElement.clientWidth;
    return Array.from(header.querySelectorAll("[data-testid]"))
      .map((el) => ({ id: el.getAttribute("data-testid") as string, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.width > 0 && (r.right > limit + 0.5 || r.left < -0.5))
      .map(({ id, r }) => `${id} right=${r.right.toFixed(1)} > ${limit}`);
  });
  expect(escaped, "header controls escaping the 375px viewport").toEqual([]);

  // The cluster genuinely wraps rather than merely being clipped: it fits the content width AND is
  // taller than one control row. `shrink-0` would reproduce the defect by keeping it one tall row.
  const cluster = await page.evaluate(() => {
    const header = document.querySelector('[data-testid="wb-header"]');
    const box = header
      ? Array.from(header.children).find((el) => String(el.className || "").includes("ms-auto"))
      : null;
    if (!box) return null;
    const r = box.getBoundingClientRect();
    return { width: r.width, height: r.height, flexShrink: getComputedStyle(box).flexShrink };
  });
  expect(cluster, "header control cluster not found").not.toBeNull();
  expect(cluster!.width).toBeLessThanOrEqual(375);
  expect(cluster!.flexShrink, "the cluster must be allowed to shrink or its flex-wrap cannot engage").not.toBe("0");

  // The control the defect pushed furthest off-screen (`agent-trigger`, right edge 597.8 at a 375px
  // viewport) is reachable with an ORDINARY click — no force, no coordinate click, no scrolling the
  // document sideways. That single click is the containment proof.
  //
  // It is closed with Escape, NOT a second click on the trigger. On mobile the Agent panel is a modal
  // drawer that deliberately sits ABOVE the header (§F: an overlay must genuinely block background
  // interaction), so the trigger is intentionally covered while the panel is open. Clicking it again
  // would assert the opposite of the shell's stated contract.
  await page.getByTestId("agent-trigger").click();
  await expect(page.getByTestId("agent-panel")).toBeVisible();
  // Wait for focus to actually ENTER the panel before pressing Escape. The panel focuses its close
  // control inside a requestAnimationFrame and its Escape handler is bound to the panel, so a press
  // issued on visibility alone races that frame and is silently dropped. This barrier is the fix for a
  // real intermittent failure observed here — never a retry until it passes.
  await expect(page.getByTestId("agent-panel-close")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("agent-panel")).toHaveCount(0);
});

test("on mobile the rail overlay and the agent panel are mutually exclusive (§F)", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(WB_URL);

  // Each full-screen mobile overlay blocks the background (its own close control stays on top), so the
  // switch is driven by the keyboard — never occluded by whichever overlay is showing.
  await page.getByTestId("nav-toggle").click();                    // rail overlay open
  await expect(page.getByTestId("shell-rail")).toBeVisible();

  await page.keyboard.press("Control+j");                          // opening agent closes the rail
  await expect(page.getByTestId("agent-panel")).toBeVisible();
  await expect(page.getByTestId("shell-rail")).toHaveCount(0);

  await page.keyboard.press("Control+b");                          // opening the rail closes agent
  await expect(page.getByTestId("shell-rail")).toBeVisible();
  await expect(page.getByTestId("agent-panel")).toHaveCount(0);
});
