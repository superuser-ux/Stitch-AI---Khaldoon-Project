import { test, expect, type Page } from "@playwright/test";
import { reseedScriptRound } from "./seed-script";
import { getScriptOpening } from "../lib/script";

// #22 — the Scripts-stage hero uses the script's own opening (structure.hook, fallback first non-empty
// line of script_ar), never final_line; the parent topic hook is demoted to a "Topic through-line".

test.describe("#22 getScriptOpening (pure logic)", () => {
  test("primary = structure.hook; fallback = first non-empty script_ar line; never final_line", async () => {
    // primary: the structured hook beat (case-insensitive key)
    expect(getScriptOpening({ script_structure: { hook: "  A real opening.  " }, script_ar: "X" })).toBe("A real opening.");
    expect(getScriptOpening({ script_structure: { Hook: "Cap key" }, script_ar: null })).toBe("Cap key");
    // fallback: first non-empty line of script_ar when the hook beat is empty/absent
    expect(getScriptOpening({ script_structure: { hook: "   " }, script_ar: "First line\nSecond" })).toBe("First line");
    expect(getScriptOpening({ script_structure: null, script_ar: "\n\n  Real opening\nmore" })).toBe("Real opening");
    // #149 — registry-shaped structure (no `hook` key): the first beat in registry order is the opening
    expect(getScriptOpening({ script_structure: { slide_2: "B", slide_1: "A" }, script_ar: "X" }, ["slide_1", "slide_2"])).toBe("A");
    expect(getScriptOpening({ script_structure: { slide_1: "  " }, script_ar: "First line" }, ["slide_1"])).toBe("First line");
    // final_line / close beats are NOT used as the opening
    expect(getScriptOpening({ script_structure: { close: "the ending" }, script_ar: null })).toBeNull();
    // missing everything -> null (card keeps its graceful fallback)
    expect(getScriptOpening({ script_structure: null, script_ar: null })).toBeNull();
    expect(getScriptOpening({ script_structure: {}, script_ar: "" })).toBeNull();
  });
});

test.beforeEach(() => reseedScriptRound());

async function gotoRSCRScripts(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RSCR").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-script").click();
  await expect(page.getByTestId("card-RSCR-1")).toBeVisible({ timeout: 20000 });
}

test("Scripts-stage hero is the script opening; topic hook is demoted to the through-line (#22)", async ({ page }) => {
  await gotoRSCRScripts(page);
  // seed: RSCR-1 topic hook "الخوف بياكل قرارك اليوم" vs script structure.hook "مش كل الضغط ..."
  const hero1 = page.getByTestId("hero-RSCR-1");
  await expect(hero1).toContainText("مش كل الضغط");          // script's own opening (structure.hook)
  await expect(hero1).not.toContainText("الخوف");            // NOT the parent topic hook
  await expect(hero1).not.toContainText("إذا ما فهمت");      // NOT the final_line
  await expect(page.getByTestId("topic-throughline-RSCR-1")).toContainText("الخوف بياكل قرارك"); // topic hook demoted

  // two scripts under distinct topics now differ at the hero (the core #22 impact)
  await expect(page.getByTestId("hero-RSCR-2")).toContainText("العلاقة مش بتموت");

  // review actions still render
  await expect(page.getByTestId("approve-RSCR-1")).toBeVisible();
  await expect(page.getByTestId("request-RSCR-1")).toBeVisible();
});
