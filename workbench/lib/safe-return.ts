// #410 (reconciliation C) — the safe "Return to Workbench" contract.
//
// Process Studio carries the originating internal Workbench URL in a `from` query parameter so Return
// lands where the user came from. `from` is PRODUCT-SURFACE RETURN CONTEXT ONLY — it never alters
// run/stage/lens interpretation (ShellNavProvider does not read it). Because a raw `from` is
// attacker-controllable, it is treated as untrusted: only a validated internal absolute path is
// accepted, everything else falls back to "/".
//
// Accept: a single leading "/", preserving path + query + hash.
// Reject: absent/empty/non-string, protocol-relative "//", backslash tricks, control/whitespace,
//         schemes and absolute URLs, and anything that does not resolve to an internal absolute path.

const FALLBACK = "/";

export function safeInternalPath(raw: string | null | undefined): string {
  if (typeof raw !== "string" || raw.length === 0) return FALLBACK;
  // Must be a path-absolute reference: exactly one leading slash.
  if (!raw.startsWith("/")) return FALLBACK;
  // Protocol-relative ("//host") and backslash-smuggled ("/\host", "\") forms are not internal.
  if (raw.startsWith("//") || raw.startsWith("/\\")) return FALLBACK;
  // No control chars, spaces, or backslashes anywhere (\x00-\x20 covers CR/LF/TAB and space).
  if (/[\x00-\x20\\]/.test(raw)) return FALLBACK;
  // Resolve against an opaque internal base and keep ONLY path+query+hash. A scheme or authority in
  // `raw` cannot survive this because a valid input has no scheme and begins with a single "/".
  try {
    const u = new URL(raw, "http://internal.invalid");
    const rebuilt = `${u.pathname}${u.search}${u.hash}`;
    if (!rebuilt.startsWith("/") || rebuilt.startsWith("//")) return FALLBACK;
    return rebuilt;
  } catch {
    return FALLBACK;
  }
}
