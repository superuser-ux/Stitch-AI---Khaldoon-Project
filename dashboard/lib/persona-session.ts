// #170 (#13 S1) — per-window internal/demo persona.
//
// The acting reviewer has two carriers with different scopes:
//   - the httpOnly `tanaghom_reviewer` cookie: browser-profile-wide default (all windows share it);
//   - this sessionStorage value, forwarded as a request header on every /gw call: window-scoped,
//     so parallel browser windows can each act as a different persona during internal demos.
// The /gw proxy prefers a syntactically valid header persona over the cookie, then signs the
// principal server-side exactly as before. NEITHER carrier is authentication or authority: the gate
// API independently enforces acting-user assignment checks at decide time (#10/#123/#147). This is
// operational identity for internal/demo use until real IAM exists (#13).
export const PERSONA_STORAGE_KEY = "tanaghom-persona";
export const PERSONA_HEADER = "x-tanaghom-persona";
// Same shape rule as /api/reviewer: known principal ids only, never free text.
export const PERSONA_ID_RE = /^[A-Za-z0-9._-]+$/;

export function getSessionPersona(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.sessionStorage.getItem(PERSONA_STORAGE_KEY) || "";
    return PERSONA_ID_RE.test(v) ? v : null;
  } catch {
    return null; // storage blocked → behave as before (cookie/default persona)
  }
}

export function setSessionPersona(id: string) {
  if (typeof window === "undefined" || !PERSONA_ID_RE.test(id)) return;
  try {
    window.sessionStorage.setItem(PERSONA_STORAGE_KEY, id);
  } catch {
    /* storage blocked → cookie path still works */
  }
}
