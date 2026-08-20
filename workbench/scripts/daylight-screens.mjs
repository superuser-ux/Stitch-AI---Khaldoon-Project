#!/usr/bin/env node
// #380 — deterministic before/after screenshot capture for the Daylight visual system. HARNESS ONLY.
//
// FAIL-CLOSED BY CONSTRUCTION (Codex review of 85d34ac). Every required state is captured for real and
// ASSERTED; a missing state, a wrong page, a mis-enabled control, or an unwritten file exits NONZERO.
// No swallowed waits, no conditional omissions — the prior revision skipped the `blocked` state and
// `.catch(()=>{})`-ed required waits, so it could pass while recording the wrong thing.
//
// It captures the five required deterministic states across TWO lane MODES so each is GENUINE (never
// faked) using ONLY the unmodified base lane:
//   MODE=no-policy   (lane started WITHOUT a run-mix policy)  → zero-run, blocked, rtl
//   MODE=with-policy (lane started with RUN_MIX_POLICY=1)      → recommendation, populated
// Each run APPENDS to `<LABEL>-manifest.json`; the run invoked with FINALIZE=1 asserts all five states
// are present. The manifest binds every shot to label, exact source head, fixture, viewport, direction,
// emulated OS scheme, the rendered theme, and a file hash.
//
// Usage: WB_URL=… HEAD=<40hex> LABEL=before|after MODE=no-policy|with-policy [FINALIZE=1] OUT=/abs/dir \
//        node scripts/daylight-screens.mjs

import { chromium } from "@playwright/test";
import { mkdirSync, existsSync, statSync, writeFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";

const WB_URL = req("WB_URL");
const HEAD = req("HEAD");
const LABEL = req("LABEL");
const OUT = req("OUT");
const MODE = req("MODE");
const FINALIZE = process.env.FINALIZE === "1";
const FIXTURE = process.env.FIXTURE || (MODE === "with-policy" ? "zero-run+gov376+run-mix-policy" : "zero-run+gov376");
const VIEWPORT = { width: 1280, height: 900 };
const OS_SCHEME = "dark"; // force OS DARK: proves determinism (after=light) vs main (before=dark).
const REQUIRED = ["zero-run", "blocked", "recommendation", "populated", "rtl"];
const ORDER = { "zero-run": 1, blocked: 2, recommendation: 3, populated: 4, rtl: 5 };
if (!["no-policy", "with-policy"].includes(MODE)) { console.error(`bad MODE ${MODE}`); process.exit(2); }

function req(name) { const v = process.env[name]; if (!v) { console.error(`[daylight-screens] missing env ${name}`); process.exit(2); } return v; }
function must(cond, msg) { if (!cond) throw new Error(`ASSERT FAILED: ${msg}`); }
function sha256(path) { return createHash("sha256").update(readFileSync(path)).digest("hex"); }
const manifestPath = resolve(OUT, `${LABEL}-manifest.json`);
function loadManifest() {
  if (!existsSync(manifestPath)) return { label: LABEL, head: HEAD, os_color_scheme: OS_SCHEME, captured: [] };
  const m = JSON.parse(readFileSync(manifestPath, "utf8"));
  must(m.head === HEAD, `manifest head ${m.head} matches this run's HEAD ${HEAD}`);
  return m;
}

mkdirSync(OUT, { recursive: true });
const manifest = loadManifest();

async function capture(page, state, { direction, extra }) {
  const file = resolve(OUT, `${LABEL}-${ORDER[state]}-${state}.png`);
  await page.screenshot({ path: file, fullPage: true });
  must(existsSync(file) && statSync(file).size > 0, `${state} screenshot file exists and is non-empty`);
  const themeAttr = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  const bgL = await page.evaluate(() => {
    const m = getComputedStyle(document.body).backgroundColor.match(/oklch\(\s*([\d.]+)/i);
    return m ? parseFloat(m[1]) : null;
  });
  // one entry per state — a re-capture replaces the prior entry rather than duplicating it
  const row = {
    label: LABEL, state, order: ORDER[state], head: HEAD, fixture: FIXTURE, mode: MODE,
    viewport: `${VIEWPORT.width}x${VIEWPORT.height}`, direction, os_color_scheme: OS_SCHEME,
    rendered_theme_attr: themeAttr, body_bg_lightness: bgL, body_is_dark: bgL != null ? bgL < 0.5 : null,
    file: `${LABEL}-${ORDER[state]}-${state}.png`, sha256: sha256(file), ...extra,
  };
  manifest.captured = manifest.captured.filter((c) => c.state !== state).concat([row]).sort((a, b) => a.order - b.order);
  console.log(`[daylight-screens] ${LABEL}/${MODE} ${state}: theme=${themeAttr ?? "(base/light)"} bgL=${bgL} dir=${direction} → ${file}`);
}
async function gwRounds(page) { return await page.evaluate(async () => (await (await fetch("/gw/rounds")).json())); }

const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ colorScheme: OS_SCHEME, viewport: VIEWPORT });
  const page = await ctx.newPage();

  if (MODE === "no-policy") {
    // 1) ZERO-RUN — the calendar-first root with no runs (assert the calendar renders AND it is empty).
    await page.goto(WB_URL, { waitUntil: "networkidle" });
    await page.waitForSelector('[data-testid="runs-calendar-grid"]', { timeout: 30_000 });
    await page.waitForSelector('[data-testid="runs-calendar-empty"]', { timeout: 30_000 });
    must((await gwRounds(page)).length === 0, "zero-run: /gw/rounds is empty");
    await capture(page, "zero-run", { direction: "ltr" });

    // 2) BLOCKED — a GENUINE no-current-policy governed state: recommend returns the typed blocked
    //    reason and Plan run is DISABLED (the lane was started without a run-mix policy).
    await page.getByTestId("new-run").click();
    await page.waitForSelector('[data-testid="run-composer"]', { timeout: 30_000 });
    await page.getByTestId("composer-posts").fill("2");
    await page.getByTestId("composer-recommend").click();
    const blocked = page.getByTestId("composer-mix-blocked");
    await blocked.waitFor({ state: "visible", timeout: 30_000 });
    must((await blocked.getAttribute("data-reason")) === "no_current_recommendation_policy", "blocked: reason is no_current_recommendation_policy");
    must(await page.getByTestId("composer-submit").isDisabled(), "blocked: Plan run is disabled");
    await capture(page, "blocked", { direction: "ltr", extra: { blocked_reason: "no_current_recommendation_policy" } });

    // 5) RTL — the root under right-to-left (toggle via KEYBOARD so the modality is honest).
    await page.goto(WB_URL, { waitUntil: "networkidle" });
    const toggle = page.getByTestId("wb-dir-toggle");
    await toggle.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.documentElement.getAttribute("dir") === "rtl", null, { timeout: 10_000 });
    await page.waitForSelector('[data-testid="runs-calendar-grid"]', { timeout: 30_000 });
    await capture(page, "rtl", { direction: "rtl" });
  } else {
    // with-policy: the lane minted a current run-mix policy, so recommend returns the governed mix.
    // 3) RECOMMENDATION — inputs render, provenance is shown, and Plan run is ENABLED.
    await page.goto(WB_URL, { waitUntil: "networkidle" });
    await page.getByTestId("new-run").click();
    await page.waitForSelector('[data-testid="run-composer"]', { timeout: 30_000 });
    await page.getByTestId("composer-posts").fill("2");
    await page.getByTestId("composer-recommend").click();
    await page.waitForSelector('[data-testid="composer-mix-inputs"]', { timeout: 30_000 });
    await page.waitForSelector('[data-testid="composer-provenance"]', { timeout: 30_000 });
    must(await page.getByTestId("composer-submit").isEnabled(), "recommendation: Plan run is enabled");
    await capture(page, "recommendation", { direction: "ltr" });

    // 4) POPULATED — plan the run and capture the schedule workspace with slots (List lens).
    await page.getByTestId("composer-submit").click();
    await page.waitForURL(/\/runs\/.+/, { timeout: 60_000 });
    const rid = (page.url().match(/\/runs\/([^?]+)/) || [])[1];
    must(!!rid, "populated: a run id is in the URL after Plan run");
    await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review&lens_${rid}=list`, { waitUntil: "networkidle" });
    await page.waitForSelector('[data-testid="schedule-cells"]', { timeout: 60_000 });
    const detail = await page.evaluate(async (r) => (await (await fetch(`/gw/rounds/${r}`)).json()), rid);
    must((detail.slots || []).length > 0, "populated: the run has slots");
    await capture(page, "populated", { direction: "ltr", extra: { round_id: rid, slots: (detail.slots || []).length } });
  }

  await ctx.close();
  writeFileSync(manifestPath, JSON.stringify({ label: LABEL, head: HEAD, os_color_scheme: OS_SCHEME, captured: manifest.captured }, null, 2) + "\n");

  if (FINALIZE) {
    const got = manifest.captured.map((m) => m.state).sort();
    must(JSON.stringify(got) === JSON.stringify([...REQUIRED].sort()), `all five required states captured (got ${JSON.stringify(got)})`);
    console.log(`[daylight-screens] ${LABEL}: 5/5 required states captured → ${manifestPath}`);
  } else {
    console.log(`[daylight-screens] ${LABEL}/${MODE}: captured ${manifest.captured.filter((c) => c.mode === MODE).map((c) => c.state).join(", ")} → ${manifestPath}`);
  }
} catch (e) {
  console.error(`[daylight-screens] FAILED: ${e.message}`);
  await browser.close();
  process.exit(1);
} finally {
  await browser.close();
}
