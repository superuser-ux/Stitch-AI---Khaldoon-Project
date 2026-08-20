// #335/#380 — V2-owned PRESENTATION preferences: appearance mode and schedule style.
//
// These are PRESENTATION-ONLY state. They live on <html> as attributes and in best-effort browser-local
// storage. They never reach a canonical command, payload, order, identifier, filter/grouping INPUT, or
// domain status/state value — they change how V2 looks, never what it means. Direction (`dir`) is a
// third, independent attribute owned by the DirToggle; appearance/style/direction stay orthogonal.
//
// APPEARANCE POLICY (#380 — DETERMINISTIC for UAT): the workbench is LIGHT-FIRST and its rendering is
// deterministic regardless of the host OS light/dark preference — there is no `prefers-color-scheme`
// rule in globals.css, so the OS never drives the theme. Dark is an EXPLICIT app selection only. The
// two selections are therefore `light` (default) and `dark`; the prior OS-following "system" mode is
// removed, and a stale stored "system" value degrades to the light default. `data-theme` is set to the
// explicit selection; the base :root (no attribute) is Light, so the SSR/first-paint state is Light too.
//
// STORAGE is best-effort: every access is guarded, and an unavailable / denied / malformed / stale
// value degrades silently to the current effective default. Storage never affects application behavior.

export type Appearance = "light" | "dark";
export type ScheduleStyle = "editorial" | "operational";

// Versioned local-storage KEY NAMES (not secrets) — a future contract change bumps the suffix rather
// than reinterpreting an old value. gitleaks:allow — these are presentation-preference key literals.
export const APPEARANCE_KEY = "tanaghom.v2.appearance.v1"; // gitleaks:allow
export const SCHEDULE_STYLE_KEY = "tanaghom.v2.scheduleStyle.v1"; // gitleaks:allow

// The COMPLETE allowlist of accepted stored values. Anything else (incl. a stale "system") → default.
export const APPEARANCES: readonly Appearance[] = ["light", "dark"] as const;
export const SCHEDULE_STYLES: readonly ScheduleStyle[] = ["editorial", "operational"] as const;

export const DEFAULT_APPEARANCE: Appearance = "light";
export const DEFAULT_SCHEDULE_STYLE: ScheduleStyle = "operational";

/** Attribute set on <html> for the explicit theme. Absent = the Light base (deterministic; the OS
 *  preference never governs — #380). */
export const THEME_ATTR = "data-theme";
export const SCHEDULE_STYLE_ATTR = "data-schedule-style";

function isAppearance(v: unknown): v is Appearance {
  return typeof v === "string" && (APPEARANCES as readonly string[]).includes(v);
}
function isScheduleStyle(v: unknown): v is ScheduleStyle {
  return typeof v === "string" && (SCHEDULE_STYLES as readonly string[]).includes(v);
}

/** Read a raw string from localStorage, tolerating unavailability/denial. Returns null on any failure. */
function safeRead(key: string): string | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage.getItem(key);
  } catch {
    return null; // SecurityError (private mode / blocked), etc. — never throws to the caller.
  }
}

/** Best-effort write. A quota/denial failure is swallowed — persistence is a convenience, not a contract. */
function safeWrite(key: string, value: string): void {
  try {
    if (typeof window === "undefined" || !window.localStorage) return;
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable/denied/full — the in-session selection still applies via the DOM attribute. */
  }
}

/** The stored appearance SELECTION, or the default when absent/malformed/unavailable. Never throws. */
export function readAppearance(): Appearance {
  const raw = safeRead(APPEARANCE_KEY);
  return isAppearance(raw) ? raw : DEFAULT_APPEARANCE;
}

export function readScheduleStyle(): ScheduleStyle {
  const raw = safeRead(SCHEDULE_STYLE_KEY);
  return isScheduleStyle(raw) ? raw : DEFAULT_SCHEDULE_STYLE;
}

export function writeAppearance(v: Appearance): void {
  if (isAppearance(v)) safeWrite(APPEARANCE_KEY, v);
}

export function writeScheduleStyle(v: ScheduleStyle): void {
  if (isScheduleStyle(v)) safeWrite(SCHEDULE_STYLE_KEY, v);
}

/** Reflect the appearance SELECTION onto <html>: `light` removes the attribute (the deterministic
 *  Light base renders), `dark` sets the explicit dark attribute. The OS preference never participates.
 *  Presentation-only DOM mutation — no network, no domain action. */
export function applyAppearance(v: Appearance): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (v === "dark") root.setAttribute(THEME_ATTR, "dark");
  else root.removeAttribute(THEME_ATTR); // light = the base :root
}

export function applyScheduleStyle(v: ScheduleStyle): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(SCHEDULE_STYLE_ATTR, v);
}

/** The appearance SELECTION currently reflected on <html> — the source of truth for the live control
 *  after hydration (mirrors the DirToggle "adopt the authoritative document state" pattern). Absent
 *  attribute = the deterministic Light default. */
export function currentAppearanceFromDom(): Appearance {
  if (typeof document === "undefined") return DEFAULT_APPEARANCE;
  return document.documentElement.getAttribute(THEME_ATTR) === "dark" ? "dark" : "light";
}

export function currentScheduleStyleFromDom(): ScheduleStyle {
  if (typeof document === "undefined") return DEFAULT_SCHEDULE_STYLE;
  const attr = document.documentElement.getAttribute(SCHEDULE_STYLE_ATTR);
  return isScheduleStyle(attr) ? attr : DEFAULT_SCHEDULE_STYLE;
}
