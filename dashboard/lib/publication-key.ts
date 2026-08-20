// #212 — publication idempotency-key minting, HTTP-surface-safe.
// crypto.randomUUID() exists only in SECURE contexts (HTTPS/localhost); the accepted plain-HTTP
// public-IP internal-review surface has crypto.getRandomValues() but not randomUUID (#211).
// Both paths emit a standards-valid RFC 4122 UUIDv4 from a CRYPTOGRAPHIC source — never
// Math.random, timestamps, or predictable values. With no usable cryptographic source this
// throws and the dialog fails safely and visibly (no request, no partial state).
// Deliberately dependency-free and single-purpose: the ONLY consumers are the publication
// dialog and its focused bit-level regression proof (which needs an alias-free import).
export function mintOperationKey(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID();
  if (!c?.getRandomValues) throw new Error("no cryptographic random source available");
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;                       // version 4
  b[8] = (b[8] & 0x3f) | 0x80;                       // variant 10xx (RFC 4122)
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
