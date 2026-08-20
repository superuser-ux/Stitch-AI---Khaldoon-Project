import { type Page } from "@playwright/test";

// #276 — a run cannot be planned without an explicit format_mix over the baseline eligibility set (the
// server rejects a missing one; the dialog keeps submit disabled until the allocation totals days×ppd).
// This helper waits for the eligible-framework inputs, then allocates the whole run to Hero Reel
// (60.viral.01) — a valid deterministic mix for any run size — so existing flows create a run in one call.
export async function allocateFullMix(page: Page): Promise<void> {
  await page.getByTestId("format-mix").waitFor();
  const days = Number(await page.getByTestId("days-input").inputValue()) || 0;
  const ppd = Number(await page.getByTestId("ppd-input").inputValue()) || 0;
  await page.getByTestId("mix-60.viral.01").fill(String(days * ppd));
}
