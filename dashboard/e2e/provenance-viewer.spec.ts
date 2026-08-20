import { test, expect, type Page } from "@playwright/test";
import { reseedScriptRound } from "./seed-script";

// #74 — M7 provenance viewer SHELL. Read-only list view over GET /rounds/{id}/provenance (PR #73):
// summary counts, grouped nodes/edges, timeline, visible data-source citations, and the unsupported[]
// honesty legend. Drives the real dashboard (:3000) + API (:8009) against the RSCR seeded run.

test.beforeEach(() => reseedScriptRound());

test("viewer loads a seeded run: summary, groups, citations, honesty legend", async ({ page }: { page: Page }) => {
  test.setTimeout(120_000);
  await page.goto("/runs/RSCR/provenance");
  await expect(page.getByTestId("provenance-viewer")).toBeVisible({ timeout: 20_000 });

  // honesty banner is first-class and states what the page is NOT
  await expect(page.getByTestId("provenance-honesty")).toContainText(/read-only/i);
  await expect(page.getByTestId("provenance-honesty")).toContainText(/not.*execution|control surface/i);

  // summary counts render, node count > 0
  await expect(page.getByTestId("provenance-summary")).toBeVisible();
  expect(parseInt(await page.getByTestId("prov-count-nodes").innerText(), 10)).toBeGreaterThan(0);
  await expect(page.getByTestId("prov-count-edges")).toBeVisible();
  await expect(page.getByTestId("prov-count-timeline")).toBeVisible();
  await expect(page.getByTestId("prov-count-unsupported")).toBeVisible();

  // grouped node/edge sections
  await expect(page.getByTestId("provenance-nodes")).toBeVisible();
  await expect(page.getByTestId("provenance-edges")).toBeVisible();

  // data-source citations are visible, and NO row is missing one
  await expect(page.getByTestId("cite").first()).toBeVisible();
  await expect(page.getByTestId("cite-missing")).toHaveCount(0);

  // unsupported honesty legend renders each fenced-off concept
  await expect(page.getByTestId("provenance-unsupported")).toBeVisible();
  for (const c of ["live_agents", "used_model_provider", "tool_call_telemetry", "task_entity", "blocked_by"]) {
    await expect(page.getByTestId(`prov-unsupported-${c}`)).toBeVisible();
  }
});

test("viewer calls the provenance endpoint for the round", async ({ page }: { page: Page }) => {
  const hits: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/provenance")) hits.push(r.url()); });
  await page.goto("/runs/RSCR/provenance");
  await expect(page.getByTestId("provenance-summary")).toBeVisible({ timeout: 20_000 });
  expect(hits.some((u) => u.includes("/rounds/RSCR/provenance"))).toBe(true);
});

test("unknown round renders a clean 404 state, not a fabricated graph", async ({ page }: { page: Page }) => {
  await page.goto("/runs/RNOPE/provenance");
  await expect(page.getByTestId("provenance-notfound")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("provenance-summary")).toHaveCount(0);
});

test("viewer is reachable from the Workflow lens", async ({ page }: { page: Page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RSCR").click();
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Workflow" }).click();
  const link = page.getByTestId("open-provenance");
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByTestId("provenance-viewer")).toHaveAttribute("data-round", "RSCR", { timeout: 20_000 });
});
