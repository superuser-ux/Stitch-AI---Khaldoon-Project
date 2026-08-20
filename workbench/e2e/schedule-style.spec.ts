import { test, expect, type Page } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #335 — Editorial/Operational schedule styles are PRESENTATION ONLY. These specs prove the toggle
// changes how the schedule/coverage surfaces look while leaving every canonical fact — row set, order,
// identifiers, generation/status state, and write payloads — byte-identical. Appearance and style are
// also orthogonal.

const STYLE_KEY = "tanaghom.v2.scheduleStyle.v1"; // gitleaks:allow

async function firstRun(page: Page, request: import("@playwright/test").APIRequestContext): Promise<string> {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  expect(rows?.length, "fixture must expose a run").toBeGreaterThan(0);
  for (const r of rows as { round_id: string }[]) {
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}`)).json();
    if ((d.slots?.length ?? 0) > 0) return r.round_id;
  }
  return rows[0].round_id;
}

/** The canonical projection the coverage list exposes — identity, order, and status/state text. */
async function captureAllocations(page: Page) {
  return page.getByTestId("coverage-allocation-list").locator(":scope > li").evaluateAll((els) =>
    els.map((e) => ({
      slot: e.getAttribute("data-slot-id"),
      generated: e.getAttribute("data-generated"),
      genstate: e.querySelector('[data-testid^="alloc-genstate-"]')?.textContent?.trim() ?? null,
      code: e.querySelector('[data-testid^="alloc-code-"]')?.textContent?.trim() ?? null,
      placement: e.querySelector('[data-testid^="alloc-placement-"]')?.textContent?.trim() ?? null,
    })),
  );
}

test("style toggle persists on <html> and is restored at first paint", async ({ page }) => {
  await page.goto(WB_URL);
  await expect(page.locator("html")).toHaveAttribute("data-schedule-style", "operational"); // default
  await page.getByTestId("wb-schedule-style-editorial").click();
  await expect(page.locator("html")).toHaveAttribute("data-schedule-style", "editorial");
  await expect(page.getByTestId("wb-schedule-style-editorial")).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate((k) => localStorage.getItem(k), STYLE_KEY)).toBe("editorial");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-schedule-style", "editorial"); // pre-paint restore
});

test("Editorial vs Operational render identical canonical rows, order, identity, and status — presentation only", async ({ page, request }) => {
  const id = await firstRun(page, request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("topics-workspace")).toBeVisible();

  await page.getByTestId("wb-schedule-style-operational").click();
  const operational = await captureAllocations(page);
  const opCount = await page.getByTestId("coverage-allocation-list").locator(":scope > li").count();

  await page.getByTestId("wb-schedule-style-editorial").click();
  await expect(page.locator("html")).toHaveAttribute("data-schedule-style", "editorial");
  const editorial = await captureAllocations(page);
  const edCount = await page.getByTestId("coverage-allocation-list").locator(":scope > li").count();

  // Same allocation count (editorial grouping lives INSIDE each <li>, never adds a sibling <li>) …
  expect(edCount).toBe(opCount);
  // … and the same identifiers, order, generation state, code, and placement — only the look differs.
  expect(editorial).toEqual(operational);
});

test("Editorial density targets the allocation CARD only — nested chips/text are not re-padded", async ({ page, request }) => {
  const id = await firstRun(page, request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("topics-workspace")).toBeVisible();

  const card = page.getByTestId("coverage-allocation-list").locator(":scope > [data-slot-id]").first();
  const slot = await card.getAttribute("data-slot-id");
  // A representative NESTED element inside the card — a status/state chip.
  const nested = page.getByTestId(`alloc-genstate-${slot}`);
  const padTop = (loc: import("@playwright/test").Locator) => loc.evaluate((el) => getComputedStyle(el).paddingTop);

  await page.getByTestId("wb-schedule-style-operational").click();
  const cardOp = await padTop(card);
  const nestedOp = await padTop(nested);

  await page.getByTestId("wb-schedule-style-editorial").click();
  await expect(page.locator("html")).toHaveAttribute("data-schedule-style", "editorial");
  const cardEd = await padTop(card);
  const nestedEd = await padTop(nested);

  // The card's padding DOES change with the style (the density knob applies here) …
  expect(cardEd).not.toBe(cardOp);
  // … but the nested chip is NOT re-padded by the card-density rule — it keeps its own padding in both.
  expect(nestedEd).toBe(nestedOp);
});

test("appearance/style changes do not alter the canonical generate payload (induced)", async ({ page, request }) => {
  const id = await firstRun(page, request);
  await page.route(`**/gw/rounds/*/generation`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ round_id: "X", stage2a_enabled: true, entry_mode: "manual", phase: "awaiting_trigger", jobs: [], results: [], counts: { accepted: 0, generated: 0 } }) }));

  const bodies: string[] = [];
  const urls: string[] = [];
  await page.route(`**/gw/rounds/*/stages/topic_review/generate`, async (route) => {
    bodies.push(route.request().postData() ?? "");
    urls.push(new URL(route.request().url()).pathname);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job_id: "j", stage2a: true, activated: true }) });
  });

  // Dark + Editorial
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await page.getByTestId("wb-appearance-dark").click();
  await page.getByTestId("wb-schedule-style-editorial").click();
  await page.getByTestId("topic-generate-action").click();

  // Light + Operational
  await page.getByTestId("wb-appearance-light").click();
  await page.getByTestId("wb-schedule-style-operational").click();
  await page.getByTestId("topic-generate-action").click();

  expect(bodies.length).toBe(2);
  expect(bodies[0]).toBe(bodies[1]);           // identical canonical payload regardless of appearance/style
  expect(urls[0]).toBe(urls[1]);               // identical canonical target
});
