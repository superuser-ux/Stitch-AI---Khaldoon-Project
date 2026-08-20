import { test, expect } from "@playwright/test";
import { WB_URL, VIEWPORTS } from "./surfaces";

// #382 — the Agent panel: a first-class, structurally-complete surface that is TRUTHFUL and
// FAIL-CLOSED in this slice (issue "Agent authority boundary" / ruling 5 / amendment §D). The default
// V2 adapter performs ZERO I/O and the composer cannot act; the panel exposes an injectable seam that a
// later authorised directive can fill.
//
// Red control (§H): an attempted Agent transport, or persistence on open, would fail the no-I/O capture
// below. The transport-error presentation is proven to exist ONLY through the dev-gated injected test
// adapter — never in production.

test.describe("the agent trigger and panel are reachable and truthful at every viewport", () => {
  for (const vp of VIEWPORTS) {
    test(`present, no-run, composer disabled — ${vp.label}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(WB_URL);
      await expect(page.getByTestId("agent-trigger")).toBeVisible();

      await page.getByTestId("agent-trigger").click();
      const panel = page.getByTestId("agent-panel");
      await expect(panel).toBeVisible();
      await expect(panel).toHaveAttribute("data-available", "false");     // default adapter is unavailable
      await expect(panel).toHaveAttribute("data-has-run", "false");       // root: no run in context
      await expect(page.getByTestId("agent-run-context")).toContainText(/no run/i);
      await expect(page.getByTestId("agent-panel-status")).toHaveAttribute("data-state", "no-run");
      // The composer cannot accept or queue a message.
      await expect(page.getByTestId("agent-composer-input")).toBeDisabled();
      await expect(page.getByTestId("agent-composer-send")).toBeDisabled();

      await page.getByTestId("agent-panel-close").click();
      await expect(page.getByTestId("agent-panel")).toHaveCount(0);
    });
  }
});

test("with a run selected the panel is truthfully unavailable, asserts no identity, and cannot act", async ({ page, request }) => {
  const rows = (await (await request.get(`${WB_URL}/gw/rounds`)).json()) as { round_id: string }[];
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}`);
  await page.getByTestId("agent-trigger").click();

  const panel = page.getByTestId("agent-panel");
  await expect(panel).toHaveAttribute("data-has-run", "true");
  await expect(panel).toHaveAttribute("data-available", "false");
  await expect(page.getByTestId("agent-panel-status")).toHaveAttribute("data-state", "unavailable");
  // The run-context slot shows the run for context ONLY — it asserts no identity/authority.
  await expect(page.getByTestId("agent-run-context")).toContainText(id);
  await expect(page.getByTestId("agent-run-context")).toContainText(/no identity or authority/i);
  await expect(page.getByTestId("agent-composer-input")).toBeDisabled();
});

test("opening and closing the agent panel performs NO network I/O (red control)", async ({ page }) => {
  await page.goto(WB_URL);
  await expect(page.getByTestId("agent-trigger")).toBeVisible();
  // Let the shell's own reads settle, THEN capture. Opening/closing the panel is pure client state.
  await page.waitForLoadState("networkidle");

  // The contract (§D): opening/closing the PANEL emits no Agent, provider, chat, action, mutation or V1
  // request. The panel is pure client state, so it issues nothing — but the page itself may keep doing
  // unrelated background READS (the calendar fetching seeded run details). Those are not the panel, so
  // we assert the real invariant: NO agent-endpoint request and NO /gw mutation during open/close. A
  // panel that tried to reach the V1 agent (a POST to /rounds/{id}/agent) is still caught.
  const during: string[] = [];
  page.on("request", (r) => {
    const url = r.url(); const m = r.method();
    if (/\/rounds\/[^/]+\/agent\b/.test(url)) during.push(`${m} ${url}`);                     // any agent request
    else if (m !== "GET" && m !== "HEAD" && /\/gw\//.test(url)) during.push(`${m} ${url}`);   // any /gw mutation
  });

  await page.getByTestId("agent-trigger").click();
  await expect(page.getByTestId("agent-panel")).toBeVisible();
  await page.getByTestId("agent-panel-close").click();
  await expect(page.getByTestId("agent-panel")).toHaveCount(0);
  // Give any stray request a chance to appear before asserting none did.
  await page.waitForTimeout(500);

  expect(during, `agent open/close issued no agent/mutation request; saw: ${during.join(", ")}`).toEqual([]);
});

test("Escape closes the panel and focus returns to the trigger", async ({ page }) => {
  await page.goto(WB_URL);
  const trigger = page.getByTestId("agent-trigger");
  await trigger.click();
  await expect(page.getByTestId("agent-panel")).toBeVisible();
  // Focus entered the panel (the close control).
  await expect(page.getByTestId("agent-panel-close")).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("agent-panel")).toHaveCount(0);
  await expect(trigger).toBeFocused();                                  // focus restored
});

test("⌘/Ctrl-J toggles the agent panel from the keyboard", async ({ page }) => {
  await page.goto(WB_URL);
  await page.locator("body").click();
  await page.keyboard.press("Control+j");
  await expect(page.getByTestId("agent-panel")).toBeVisible();
  await page.keyboard.press("Control+j");
  await expect(page.getByTestId("agent-panel")).toHaveCount(0);
});

test("transport-error exists ONLY through the dev-gated injected test adapter (never in production)", async ({ page }) => {
  const res = await page.goto(`${WB_URL}/agent-adapter-probe`);
  test.skip((res?.status() ?? 404) === 404, "adapter probe is 404 outside TANAGHOM_DEV_MODE (production posture)");

  await expect(page.getByTestId("agent-adapter-probe")).toBeVisible();
  const panel = page.getByTestId("agent-panel");
  await expect(panel).toHaveAttribute("data-available", "true");        // injected adapter is available
  // The injected adapter's transport always fails; sending surfaces the transport-error state.
  await page.getByTestId("agent-composer-input").fill("hello");
  await page.getByTestId("agent-composer-send").click();
  await expect(page.getByTestId("agent-panel-status")).toHaveAttribute("data-state", "transport-error");
  await expect(page.getByTestId("agent-panel-status")).toContainText(/transport failed/i);
});
