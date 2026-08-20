import { test, expect, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { V1_URL, WB_URL, VIEWPORTS } from "./surfaces";

// #293 §3 + acceptance A6 — BOTH V1 and V2 visibly render the canonical Tanaghom and
// "Powered by Stitch" marks at 375px, tablet, and desktop, with correct accessible names.
//
// This asserts V1 from the V2 package on purpose: it evidences A6 for both surfaces while leaving
// dashboard/ byte-identical (A1/A11). It only READS V1.

const CANONICAL = {
  tanaghom: {
    file: "tenants/tanaghum/tanaghom-logo.png",
    sha256: "126f7d1e90ae2707463b9520aefb3270dd17a2aa3e56b5d03e9738d3468be4c4",
    alt: "Tanaghom",
  },
  stitch: {
    file: "platform/stitch/stitch-logo.png",
    sha256: "182625bba04b184620653f839dd133faed7956947d08199995315959f2494d0c",
    alt: "Stitch",
  },
} as const;

/** A mark is only "rendered" if the browser actually decoded pixels — a broken <img> still has an
 *  accessible name and still passes toBeVisible(), so naturalWidth is what separates a real mark
 *  from a 404 box. §3 forbids omitting or substituting either mark; this is how we prove it. */
async function expectMarkRendered(page: Page, testId: string, alt: string) {
  const img = page.getByTestId(testId);
  await expect(img).toBeVisible();
  await expect(img).toHaveAttribute("alt", alt);
  const decoded = await img.evaluate(
    (el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0,
  );
  expect(decoded, `${testId} must decode real pixels, not a broken image`).toBe(true);
}

test.describe("V2 workbench renders the canonical marks at every viewport", () => {
  for (const vp of VIEWPORTS) {
    test(`V2 — Tanaghom + Powered by Stitch at ${vp.label}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(WB_URL);

      await expectMarkRendered(page, "wb-brand-tanaghom", CANONICAL.tanaghom.alt);
      await expectMarkRendered(page, "wb-brand-stitch", CANONICAL.stitch.alt);

      // The attribution is the exact "Powered by … Stitch" wording, never a text-only substitute
      // for the mark (§3) — the mark itself is asserted above.
      await expect(page.getByTestId("wb-poweredby")).toContainText("Powered by");
      await expect(page.getByTestId("wb-poweredby")).toContainText("Stitch");
    });
  }
});

test.describe("V1 dashboard still renders the canonical marks at every viewport", () => {
  for (const vp of VIEWPORTS) {
    test(`V1 — Tanaghom + Powered by Stitch at ${vp.label}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(V1_URL);

      // V1 collapses its sidebar on small viewports, so the marks are addressed by accessible name
      // (V1 has no testids on them) and the nav is opened when it is behind the mobile toggle.
      const tanaghom = page.getByAltText(CANONICAL.tanaghom.alt).first();
      if (!(await tanaghom.isVisible().catch(() => false))) {
        const navToggle = page.getByTestId("nav-toggle");
        if (await navToggle.isVisible().catch(() => false)) await navToggle.click();
      }
      await expect(tanaghom).toBeVisible();
      await expect(page.getByAltText(CANONICAL.stitch.alt).first()).toBeVisible();
    });
  }
});

test("V2 serves the exact canonical bytes (not a redraw or a substitute)", async ({ request }) => {
  for (const mark of [CANONICAL.tanaghom, CANONICAL.stitch]) {
    // Byte identity over the wire — what the browser actually receives from V2.
    const res = await request.get(`${WB_URL}/brand/${mark.file}`);
    expect(res.status()).toBe(200);
    const served = createHash("sha256").update(await res.body()).digest("hex");
    expect(served, `V2 must serve canonical bytes for ${mark.file}`).toBe(mark.sha256);

    // And the tracked copy still matches V1's canonical source on disk.
    const canonicalPath = path.resolve(__dirname, "..", "..", "dashboard", "public", "brand", mark.file);
    const onDisk = createHash("sha256").update(readFileSync(canonicalPath)).digest("hex");
    expect(onDisk, `V1 canonical bytes for ${mark.file} changed — V2 copy is stale`).toBe(mark.sha256);
  }
});
