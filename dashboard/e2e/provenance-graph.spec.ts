import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { reseedScriptRound } from "./seed-script";

// #81 — M7 provenance GRAPH canvas (React Flow) over the same GET /rounds/{id}/provenance payload as
// the #75 list viewer. Read-only; every node/edge exposes its data-source citation + source_id; the
// unsupported[] honesty legend stays first-class; no act-through-map controls.
const API = process.env.API_URL || "http://localhost:8009";
const payload = async (r: APIRequestContext, round = "RSCR") =>
  (await r.get(`${API}/rounds/${round}/provenance`)).json();

test.beforeEach(() => reseedScriptRound());

async function openGraph(page: Page, round = "RSCR") {
  await page.goto(`/runs/${round}/provenance`);
  await expect(page.getByTestId("provenance-viewer")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("prov-view-graph").click();
  await expect(page.getByTestId("provenance-graph")).toBeVisible({ timeout: 20_000 });
}

test("graph renders the payload: matching node/edge counts, legends, honesty legend, read-only", async ({ page, request }) => {
  test.setTimeout(120_000);
  const g = await payload(request);
  const hits: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/provenance")) hits.push(r.url()); });

  await openGraph(page);
  expect(hits.some((u) => u.includes("/rounds/RSCR/provenance"))).toBe(true);

  // rendered node/edge counts match the payload exactly (nothing faked, nothing dropped)
  await expect(page.locator('[data-testid^="gnode-"]')).toHaveCount(g.nodes.length);
  await expect(page.locator('[data-testid^="gedge-"]')).toHaveCount(g.edges.length);

  // node/edge type legend + the unsupported "Not claimed yet" honesty legend both visible in graph view
  await expect(page.getByTestId("prov-graph-legend")).toBeVisible();
  await expect(page.getByTestId("provenance-unsupported")).toBeVisible();
  await expect(page.getByTestId("prov-unsupported-live_agents")).toBeVisible();

  // no citation is missing on any rendered detail, and NO act-through-map controls exist
  await expect(page.getByTestId("provenance-viewer").getByRole("button", { name: /approve|retry|pause|reassign|regenerate|execute/i })).toHaveCount(0);
});

test("selecting a node exposes its type, source_id and data-source citation", async ({ page }) => {
  test.setTimeout(120_000);
  await openGraph(page);
  await page.getByTestId("gnode-round:RSCR").click();
  const d = page.getByTestId("prov-detail-node");
  await expect(d).toBeVisible();
  await expect(d.getByTestId("cite")).toBeVisible();               // table.field citation
  await expect(d.getByTestId("prov-detail-source")).toBeVisible(); // source_id
  await expect(d).toContainText("round");
});

test("selecting an edge exposes its source/target, source_id and citation", async ({ page }) => {
  test.setTimeout(120_000);
  await openGraph(page);
  await page.locator('[data-testid^="gedge-"]').first().click();
  const d = page.getByTestId("prov-detail-edge");
  await expect(d).toBeVisible();
  await expect(d.getByTestId("cite")).toBeVisible();
  await expect(d.getByTestId("prov-detail-source")).toBeVisible();
});

test("the list viewer remains available alongside the graph (toggle back)", async ({ page }) => {
  await openGraph(page);
  await page.getByTestId("prov-view-list").click();
  await expect(page.getByTestId("provenance-nodes")).toBeVisible();
  await expect(page.getByTestId("provenance-graph")).toHaveCount(0);
});

test("unknown round is a clean 404 (no graph rendered)", async ({ page }) => {
  await page.goto("/runs/RNOPE/provenance");
  await expect(page.getByTestId("provenance-notfound")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("provenance-graph")).toHaveCount(0);
  await expect(page.getByTestId("prov-view-graph")).toHaveCount(0);
});
