import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #382 — the top lens menu and the SINGLE 3-class lens matrix (amendment §A / ruling 2). One typed
// matrix classifies every entry as implemented-enabled, implemented-context-invalid, or
// unimplemented-disabled and is the SOLE source for rendering, navigation, accessibility state and URL
// validation. One shared pure resolver canonicalizes invalid/stale lens URLs.
//
// Red controls proven here (§H): a disabled lens that navigates, and an invalid/stale lens value that
// renders stale content instead of canonicalizing, would each fail a test below.

test("on the root the lens menu shows Calendar as the active root lens, context-only — no fake nav", async ({ page }) => {
  await page.goto(WB_URL);
  const menu = page.getByTestId("lens-menu");
  await expect(menu).toBeVisible();
  // The root is a calendar: Calendar is the current root lens...
  await expect(page.getByTestId("lens-calendar")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("lens-calendar")).toHaveAttribute("data-class", "implemented-enabled");
  // ...but with no selected run the menu is context-only, so nothing navigates to a placeholder.
  await expect(menu).toHaveAttribute("data-context-only", "true");
  await expect(page.getByTestId("lens-grid")).toBeDisabled();
  // The URL is untouched — clicking a context-only menu cannot fabricate a run-scoped view.
  await expect(page).toHaveURL(new RegExp(`${WB_URL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/?$`));
});

test("the 3-class matrix on the Topics stage: enabled navigate; context-invalid + unimplemented are disabled, truthful and never navigate (red control)", async ({ page, request }) => {
  const rows = (await (await request.get(`${WB_URL}/gw/rounds`)).json()) as { round_id: string }[];
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("lens-menu")).toBeVisible();

  // implemented-enabled → navigable; a click changes the projection and the URL.
  for (const k of ["list", "grid", "overview"]) {
    await expect(page.getByTestId(`lens-${k}`)).toHaveAttribute("data-class", "implemented-enabled");
    await expect(page.getByTestId(`lens-${k}`)).toBeEnabled();
  }
  await page.getByTestId("lens-grid").click();
  await expect(page.getByTestId("topics-workspace")).toHaveAttribute("data-lens", "grid");
  await expect(page).toHaveURL(/[?&]lens=grid/);

  // implemented-context-invalid (Calendar belongs to Coverage/Planning) — disabled, truthful, no nav.
  const calendar = page.getByTestId("lens-calendar");
  await expect(calendar).toHaveAttribute("data-class", "implemented-context-invalid");
  await expect(calendar).toBeDisabled();
  await expect(calendar).toHaveAttribute("title", /Coverage \/ Planning/i);

  // unimplemented-disabled (never built) — disabled, truthful.
  const board = page.getByTestId("lens-board");
  await expect(board).toHaveAttribute("data-class", "unimplemented-disabled");
  await expect(board).toBeDisabled();
  await expect(board).toHaveAttribute("title", /not built/i);

  // Analytics is visible as product-roadmap information, but Stage 8 remains unavailable until
  // publication-backed performance evidence exists. It is not promoted to a lifecycle stage or view.
  const analytics = page.getByTestId("lens-analytics");
  await expect(analytics).toHaveAttribute("data-class", "unimplemented-disabled");
  await expect(analytics).toBeDisabled();
  await expect(analytics).toHaveAttribute("title", /Stage 8.*publication-backed performance evidence/i);

  // A disabled lens cannot navigate even if forced: the URL and projection stay put.
  await calendar.dispatchEvent("click");
  await expect(page.getByTestId("topics-workspace")).toHaveAttribute("data-lens", "grid");
  await expect(page).toHaveURL(/[?&]lens=grid/);

  await analytics.dispatchEvent("click");
  await expect(page.getByTestId("topics-workspace")).toHaveAttribute("data-lens", "grid");
  await expect(page).toHaveURL(/[?&]lens=grid/);
});

test("an invalid/stale lens URL is canonicalized (replace) to the gate default with a truthful notice (red control)", async ({ page, request }) => {
  const rows = (await (await request.get(`${WB_URL}/gw/rounds`)).json()) as { round_id: string }[];
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id;
  // `calendar` is not a valid Topics lens — the shell must not render a stale/invalid view.
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review&lens=calendar`);

  // Canonicalized to the gate default (`list`), and the accessible notice states what happened.
  await expect(page.getByTestId("topics-workspace")).toHaveAttribute("data-lens", "list");
  await expect(page).toHaveURL(/[?&]lens=list/);
  await expect(page).not.toHaveURL(/[?&]lens=calendar/);
  await expect(page.getByTestId("shell-nav-notice")).toContainText(/not available here/i);
});

test("the lens menu is keyboard reachable and Enter navigates an enabled lens", async ({ page, request }) => {
  const rows = (await (await request.get(`${WB_URL}/gw/rounds`)).json()) as { round_id: string }[];
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review&lens=list`);
  const grid = page.getByTestId("lens-grid");
  await grid.focus();
  await expect(grid).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("topics-workspace")).toHaveAttribute("data-lens", "grid");
});
