#!/usr/bin/env node
// #380 — deterministic WCAG contrast check for the Tanaghom Daylight token layer. TEST-HARNESS ONLY.
//
// Self-contained by design: it introduces NO dependency (a hard stop forbids new packages/CDNs). It
// PARSES the committed token values straight out of app/globals.css — base :root (Light) and
// :root[data-theme="dark"] — resolves `color-mix(in oklab, …)` soft tokens exactly the way the browser
// does (linear-oklab interpolation), converts OKLCH→sRGB (Björn Ottosson's matrices), and asserts the
// WCAG 2.1 contrast ratio of each meaningful foreground/background pair against its AA threshold
// (4.5:1 body text, 3.0:1 large text / UI affordances / focus rings). A single failing pair exits
// nonzero — the check is discriminating, never decorative.
//
// It is intentionally value-level, not a render scan: it proves the SOURCE tokens are AA-correct in
// both themes at their definition, so no surface consuming them can be non-compliant by palette.

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS = readFileSync(resolve(HERE, "..", "app", "globals.css"), "utf8");

// ---- token extraction -----------------------------------------------------------------------------
/** Pull `--name: value;` decls out of a single CSS rule block identified by its selector. */
function block(selector) {
  const i = CSS.indexOf(selector);
  if (i < 0) throw new Error(`selector not found: ${selector}`);
  const open = CSS.indexOf("{", i);
  const close = CSS.indexOf("}", open);
  const body = CSS.slice(open + 1, close);
  const out = {};
  for (const m of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) out[m[1].trim()] = m[2].trim();
  return out;
}

// The Dark block overrides only some tokens; Light is the base. Resolve dark as base+overrides.
const LIGHT = block(":root {");
const DARK = { ...LIGHT, ...block(':root[data-theme="dark"] {') };

// ---- colour math (OKLCH → linear sRGB → sRGB → relative luminance) ---------------------------------
function parseOklch(v) {
  const m = v.match(/oklch\(\s*([\d.]+)%?\s+([\d.]+)\s+([\d.]+)/i);
  if (!m) return null;
  let L = parseFloat(m[1]);
  if (v.includes("%")) L /= 100;                 // "97.8%" → 0.978
  return { L, C: parseFloat(m[2]), H: parseFloat(m[3]) };
}
function oklchToOklab({ L, C, H }) {
  const h = (H * Math.PI) / 180;
  return { L, a: C * Math.cos(h), b: C * Math.sin(h) };
}
function oklabToLinearSrgb({ L, a, b }) {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
  return [
    +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
}
const clamp01 = (x) => Math.min(1, Math.max(0, x));
/** WCAG relative luminance from LINEAR sRGB (clamped into gamut). */
function luminance(linear) {
  const [r, g, b] = linear.map(clamp01);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
/** color-mix(in oklab, A pct%, B) — linear interpolation in OKLab, exactly the browser's model. */
function mixOklab(A, B, pct) {
  const t = pct / 100;
  return { L: A.L * t + B.L * (1 - t), a: A.a * t + B.a * (1 - t), b: A.b * t + B.b * (1 - t) };
}

/** Resolve a token value (oklch, var(), or color-mix) in a given theme to an OKLab colour. */
function resolve_(theme, value, seen = new Set()) {
  value = value.trim();
  let m = value.match(/^var\((--[a-z0-9-]+)\)$/i);
  if (m) {
    if (seen.has(m[1])) throw new Error(`var cycle at ${m[1]}`);
    seen.add(m[1]);
    return resolve_(theme, theme[m[1]], seen);
  }
  m = value.match(/^color-mix\(in oklab,\s*(.+?)\s+([\d.]+)%\s*,\s*(.+?)\)$/i);
  if (m) return mixOklab(resolve_(theme, m[1], new Set(seen)), resolve_(theme, m[3], new Set(seen)), parseFloat(m[2]));
  const ok = parseOklch(value);
  if (ok) return oklchToOklab(ok);
  throw new Error(`unresolvable colour: ${value}`);
}
function lumOf(theme, token) {
  return luminance(oklabToLinearSrgb(resolve_(theme, theme[token])));
}
function contrast(theme, fg, bg) {
  const a = lumOf(theme, fg) + 0.05, b = lumOf(theme, bg) + 0.05;
  return a > b ? a / b : b / a;
}

// ---- the pairs that must pass ----------------------------------------------------------------------
// [foreground token, background token, min ratio, note]
const PAIRS = [
  ["--color-fg", "--color-bg", 4.5, "body text on canvas"],
  ["--color-fg", "--color-card", 4.5, "body text on card"],
  ["--color-fg", "--color-nav", 4.5, "text on nav chrome"],
  ["--color-fg", "--color-elevated", 4.5, "text on elevated"],
  ["--color-fg", "--color-sunken", 4.5, "text in sunken well"],
  ["--color-muted", "--color-bg", 4.5, "secondary text on canvas"],
  ["--color-muted", "--color-card", 4.5, "secondary text on card"],
  ["--color-subtle", "--color-card", 3.0, "tertiary/diagnostic text (large/non-essential)"],
  ["--color-on-accent", "--color-accent", 4.5, "text on the accent fill (buttons)"],
  ["--color-on-accent-soft", "--color-accent-soft", 4.5, "text on the soft accent surface"],
  ["--color-fg", "--color-danger-soft", 4.5, "text on a blocked/danger chip"],
  ["--color-fg", "--color-warn-soft", 4.5, "text on a stale/warn chip"],
  ["--color-fg", "--color-ok-soft", 4.5, "text on an ok chip"],
  ["--color-fg", "--color-info-soft", 4.5, "text on an info chip"],
  ["--color-danger", "--color-card", 3.0, "danger tone (icon/border/label) on card"],
  ["--color-warn", "--color-card", 3.0, "warn tone on card"],
  ["--color-ok", "--color-card", 3.0, "ok tone on card"],
  ["--color-info", "--color-card", 3.0, "info tone on card"],
  ["--color-focus", "--color-card", 3.0, "focus ring against card"],
  ["--color-border-strong", "--color-card", 3.0, "strong border/divider on card"],
];

let fails = 0;
for (const themeName of ["light", "dark"]) {
  const theme = themeName === "light" ? LIGHT : DARK;
  console.log(`\n## ${themeName}`);
  for (const [fg, bg, min, note] of PAIRS) {
    const r = contrast(theme, fg, bg);
    const ok = r >= min;
    if (!ok) fails++;
    console.log(`  ${ok ? "PASS" : "FAIL"}  ${r.toFixed(2)}:1 (>=${min})  ${fg} on ${bg} — ${note}`);
  }
}
console.log(`\n${fails ? `CONTRAST FAILED: ${fails} pair(s) below threshold` : "ALL DAYLIGHT CONTRAST PAIRS PASS AA"}`);
process.exit(fails ? 1 : 0);
