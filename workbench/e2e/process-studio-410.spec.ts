import { test, expect, type Page } from "@playwright/test";
import { WB_URL, VIEWPORTS, dbSnapshot } from "./surfaces";
import { FIXTURE_DISCLOSURE } from "../components/studio/illustrative-social-workflow";

// #410 — Process Studio graph direction + canonical product-surface metadata.
//
// Proves the SLICE truthfully: Process Studio is discoverable (desktop + mobile) as the only newly
// navigable destination; /studio renders ONE read-only React Flow demonstration with the exact fixture
// disclosure and no mutation controls; selected-node inspection changes no data; run → Studio → Return
// preserves the originating internal Workbench URL without altering run/stage/lens; the product-surface
// ledger shows the complete planned map with deferred surfaces dimmed and non-clickable. Read-only
// throughout — the run/gate/audit snapshot must be identical across the whole flow.

test.describe("#410 Process Studio + product-surface registry", () => {
  test("Process Studio is discoverable on desktop and mobile; Identity/Secrets preserved", async ({ page }) => {
    for (const vp of VIEWPORTS) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(WB_URL);
      // The single header nav surface wraps at 375px but the destinations stay present on every viewport.
      await expect(page.getByTestId("process-studio-link"), `Studio visible @ ${vp.label}`).toBeVisible();
      await expect(page.getByTestId("identity-admin-link"), `Identity preserved @ ${vp.label}`).toBeVisible();
      await expect(page.getByTestId("secrets-admin-link"), `Secrets preserved @ ${vp.label}`).toBeVisible();
    }
    // Existing hrefs are untouched; only Process Studio carries the safe-return `from`.
    await expect(page.getByTestId("identity-admin-link")).toHaveAttribute("href", "/admin/identity");
    await expect(page.getByTestId("secrets-admin-link")).toHaveAttribute("href", "/admin/secrets");
    await expect(page.getByTestId("process-studio-link")).toHaveAttribute("href", /^\/studio\?from=/);
  });

  test("/studio renders one read-only demonstration graph with the exact disclosure and no mutation controls", async ({ page }) => {
    await page.goto(`${WB_URL}/studio`);

    // exactly one shell / one <main> (invariant preserved by rendering into the existing layout).
    await expect(page.locator("main[data-testid='wb-main']")).toHaveCount(1);

    await expect(page.getByTestId("studio-view")).toBeVisible();
    await expect(page.getByTestId("studio-fixture-disclosure")).toHaveText(FIXTURE_DISCLOSURE);
    await expect(page.getByTestId("studio-version-status")).toBeVisible();
    await expect(page.getByTestId("studio-editing-unavailable")).toContainText("Editing not available");

    // the read-only graph mounts (lazy chunk resolves)
    await expect(page.getByTestId("studio-graph-canvas")).toBeVisible();
    await expect(page.locator(".react-flow")).toBeVisible();

    // no mutation affordances: React Flow's interactive lock control is suppressed, and there is no
    // node palette / add / delete control anywhere on the surface.
    await expect(page.locator(".react-flow__controls-interactive")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /add node|new node|palette|delete/i })).toHaveCount(0);
  });

  test("selecting a node shows details and mutates no data", async ({ page }, testInfo) => {
    const before = snapshotOrDefer(testInfo);
    await page.goto(`${WB_URL}/studio`);
    await expect(page.getByTestId("studio-node-details")).toContainText("Select a node");

    await page.getByTestId("studio-node-review").click();
    await expect(page.getByTestId("studio-node-details")).toContainText("Review & approve");
    await expect(page.getByTestId("studio-node-details")).toContainText("review"); // illustrated stage id

    assertNoMutation(before); // inspection never writes (or an explicit deferral is recorded)
  });

  test("Planned capabilities and the ledger are truthful, dimmed, and non-clickable", async ({ page }) => {
    await page.goto(`${WB_URL}/studio`);

    // The six planned builder functions render, dimmed, with NO interactive control inside them.
    const caps = page.getByTestId("studio-planned-capabilities");
    await expect(caps).toBeVisible();
    for (const id of ["ps-palette", "ps-validation", "ps-releases", "ps-archive", "ps-methodology", "ps-approvals"]) {
      const li = page.getByTestId(`planned-capability-${id}`);
      await expect(li).toHaveAttribute("data-surface-tone", "dimmed");
      await expect(li.locator("a, button")).toHaveCount(0);
      // Canonical implementation-state text is VISIBLE on every card (color is never the sole signal).
      await expect(page.getByTestId(`planned-capability-state-${id}`)).toHaveText("Deferred");
    }

    // The ledger shows the complete planned map; deferred/scaffolded surfaces are dimmed + aria-disabled.
    const ledger = page.getByTestId("product-surface-ledger");
    await expect(ledger).toBeVisible();
    for (const id of ["workbench", "process-studio", "inbox-tasks", "content", "analytics-learning", "agents", "administration"]) {
      await expect(page.getByTestId(`ledger-surface-${id}`)).toBeVisible();
    }
    // A deferred surface is dimmed, aria-disabled, and never a link.
    const deferred = page.getByTestId("ledger-surface-inbox-tasks");
    await expect(deferred).toHaveAttribute("data-surface-tone", "dimmed");
    await expect(deferred).toHaveAttribute("aria-disabled", "true");
    await expect(deferred.locator("a")).toHaveCount(0);
  });

  test("run → Studio → Return preserves the originating URL (path+query+hash) and does not alter run/stage/lens", async ({ page }, testInfo) => {
    // Includes a hash so the safe-return contract's path + query + hash preservation is all proven.
    const origin = "/runs/RE2E?lens=grid#top";
    const before = snapshotOrDefer(testInfo);

    await page.goto(`${WB_URL}${origin}`);
    // The nav link captures the current hash only AFTER mount (client-side), so wait for the href to
    // carry the encoded hash before clicking — proves the hash is genuinely captured, not dropped.
    const escaped = encodeURIComponent(origin).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    await expect(page.getByTestId("process-studio-link")).toHaveAttribute("href", new RegExp(`/studio\\?from=${escaped}$`));
    await page.getByTestId("process-studio-link").click();

    // We are in Studio, out of run context, carrying the full origin as a validated `from`.
    await expect(page).toHaveURL(new RegExp(`/studio\\?from=${escaped}`));
    await expect(page.getByTestId("studio-view")).toBeVisible();

    // Return lands back on the exact originating Workbench URL — path, query, AND hash intact.
    await expect(page.getByTestId("studio-return-link")).toHaveAttribute("href", origin);
    await page.getByTestId("studio-return-link").click();
    await expect(page).toHaveURL(`${WB_URL}${origin}`);

    assertNoMutation(before); // entering Studio created/reinterpreted no run
  });
});

// dbSnapshot() needs docker + the db container. When the stack is down (e.g. CI without it) the
// non-mutation DB assertion CANNOT run. Rather than silently drop it (a false pass), we record an
// EXPLICIT, visible deferral annotation on the test and log it, then skip only that one assertion.
function snapshotOrDefer(testInfo: import("@playwright/test").TestInfo): string | null {
  try {
    return dbSnapshot();
  } catch (e) {
    const why = (e as Error).message.split("\n")[0];
    testInfo.annotations.push({
      type: "deferred",
      description: `DB non-mutation assertion NOT run: dbSnapshot unavailable (${why}). Run where the dev stack/db container is up to exercise it.`,
    });
    // eslint-disable-next-line no-console
    console.warn(`[DEFERRED] ${testInfo.title}: DB non-mutation assertion skipped — dbSnapshot unavailable (${why}).`);
    return null;
  }
}

/** Assert no DB mutation when a baseline snapshot was captured; when it was deferred (null), the
 *  deferral is already annotated/logged above, so this is intentionally a no-op — never a silent pass. */
function assertNoMutation(before: string | null): void {
  if (before !== null) expect(dbSnapshot()).toBe(before);
}
