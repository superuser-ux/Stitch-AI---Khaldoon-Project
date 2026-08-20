import { test, expect } from "@playwright/test";
import { composeBilingual, dirForLang, BILINGUAL_SEPARATOR } from "../lib/bilingual";

// #280 — the deterministic, RTL-safe bilingual PRESENTATION contract. Pure logic: no dashboard/API
// needed. It proves display-only fallback + direction/lang selection + truthful absence, and never
// mutates or invents source content.

test.describe("#280 bilingual presentation contract (pure logic)", () => {
  test("prefers the primary language, with the correct direction + lang tag", () => {
    expect(composeBilingual("مرحبا", "Hello", { primary: "ar" }))
      .toEqual({ text: "مرحبا", lang: "ar", dir: "rtl", present: true });
    expect(composeBilingual("مرحبا", "Hello", { primary: "en" }))
      .toEqual({ text: "Hello", lang: "en", dir: "ltr", present: true });
    // default primary is Arabic (the product's content-primary language)
    expect(composeBilingual("مرحبا", "Hello").lang).toBe("ar");
  });

  test("falls back deterministically to the other side when the primary is absent/blank", () => {
    expect(composeBilingual(null, "Hello", { primary: "ar" }))
      .toEqual({ text: "Hello", lang: "en", dir: "ltr", present: true });
    expect(composeBilingual("   ", "Hello", { primary: "ar" }))
      .toEqual({ text: "Hello", lang: "en", dir: "ltr", present: true });
    expect(composeBilingual("مرحبا", null, { primary: "en" }))
      .toEqual({ text: "مرحبا", lang: "ar", dir: "rtl", present: true });
  });

  test("exposes genuine absence truthfully (never invents a value)", () => {
    expect(composeBilingual(null, null)).toEqual({ text: null, lang: null, dir: null, present: false });
    expect(composeBilingual("  ", undefined)).toEqual({ text: null, lang: null, dir: null, present: false });
  });

  test("direction + separator helpers are stable", () => {
    expect(dirForLang("ar")).toBe("rtl");
    expect(dirForLang("en")).toBe("ltr");
    expect(BILINGUAL_SEPARATOR).toBe(" · ");
  });
});
