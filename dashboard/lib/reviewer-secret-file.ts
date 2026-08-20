// #387 — manager-neutral reviewer-proxy secret resolver (server-side TypeScript).
//
// A byte-for-byte behavioural mirror of gates/reviewer_secret.py. Knows nothing about OpenBao or any
// secret manager: it reads a plain FILE path (populated out-of-band by a host materializer) or the
// direct env var. Precedence is NOT "file wins" — if BOTH REVIEWER_PROXY_SECRET_FILE and
// REVIEWER_PROXY_SECRET are non-empty the source is AMBIGUOUS and we FAIL CLOSED. The known public dev
// fixture is used ONLY under an explicit TANAGHOM_DEV_MODE opt-in AND ONLY when neither FILE nor env is
// configured — never on accidental omission, never as a fallback for an invalid FILE.
//
// FILE security (validated on EVERY resolve, so an atomic same-directory replacement is observed without
// a restart): absolute; not a symlink (lstat + O_NOFOLLOW); the OPENED descriptor is validated with
// fstat before any byte is read (defeats TOCTOU / symlink swap); regular file; zero group/world
// permission bits; owned by root or the process EUID; size <= 64 KiB; non-empty after trim; mtime not
// more than 30 s in the future; age within a positive REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS. A
// single bounded retry is permitted ONLY for the transient atomic-replacement race (leaf briefly absent
// mid-rename); every persistent invalid/missing/stale/insecure condition fails closed with NO fallback.
// Never logs/returns/throws with secret content — only non-secret reason strings and boolean/source-kind.
import { openSync, fstatSync, lstatSync, readSync, closeSync, constants as FS } from "fs";
import { isAbsolute } from "path";

export const DEV_REVIEWER_SECRET = "dev-internal-reviewer-proxy-secret"; // local/dev/test ONLY
export const MAX_FILE_BYTES = 64 * 1024;
const FUTURE_MTIME_SKEW_MS = 30_000;
const RENAME_RACE_RETRY_DELAY_MS = 50;

export type SecretSource = "file" | "env" | "dev";

// Non-secret fail-closed error. Message never contains the value.
export class SecretError extends Error {}

export function devMode(): boolean {
  return ["1", "true", "yes", "on"].includes((process.env.TANAGHOM_DEV_MODE || "").trim().toLowerCase());
}

function envSecret(): string {
  return (process.env.REVIEWER_PROXY_SECRET || "").trim();
}

function filePath(): string {
  return (process.env.REVIEWER_PROXY_SECRET_FILE || "").trim();
}

function maxAgeSeconds(): number {
  const raw = (process.env.REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS || "").trim();
  const v = Number(raw);
  if (!raw || !Number.isInteger(v) || v <= 0) {
    throw new SecretError(
      "REVIEWER_PROXY_SECRET_FILE requires a positive REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS",
    );
  }
  return v;
}

function isENOENT(e: unknown): boolean {
  return !!e && typeof e === "object" && (e as { code?: string }).code === "ENOENT";
}

// Read+validate the FILE. Throws an ENOENT-coded Error ONLY for the transient rename window (caller may
// retry once); every other problem throws SecretError (persistent, fail-closed, no retry).
function readSecureFile(path: string): string {
  if (!isAbsolute(path)) throw new SecretError("REVIEWER_PROXY_SECRET_FILE must be an absolute path");
  const maxAge = maxAgeSeconds();
  const lst = lstatSync(path); // ENOENT -> transient-retry candidate (propagates)
  if (lst.isSymbolicLink()) throw new SecretError("REVIEWER_PROXY_SECRET_FILE must not be a symlink");

  let fd: number;
  try {
    fd = openSync(path, FS.O_RDONLY | (FS.O_NOFOLLOW || 0));
  } catch (e) {
    if (isENOENT(e)) throw e; // transient
    // ELOOP (symlink swapped in under O_NOFOLLOW), EACCES, etc. -> persistent, fail closed.
    throw new SecretError("REVIEWER_PROXY_SECRET_FILE is unreadable or not a plain file");
  }
  try {
    const st = fstatSync(fd);
    if (!st.isFile()) throw new SecretError("REVIEWER_PROXY_SECRET_FILE must be a regular file");
    if (st.mode & 0o077) {
      throw new SecretError("REVIEWER_PROXY_SECRET_FILE must have zero group/world permission bits");
    }
    const euid = typeof process.geteuid === "function" ? process.geteuid() : st.uid;
    if (st.uid !== 0 && st.uid !== euid) {
      throw new SecretError("REVIEWER_PROXY_SECRET_FILE must be owned by root or the process user");
    }
    if (st.size > MAX_FILE_BYTES) {
      throw new SecretError("REVIEWER_PROXY_SECRET_FILE exceeds the 64 KiB size cap");
    }
    const now = Date.now();
    if (st.mtimeMs > now + FUTURE_MTIME_SKEW_MS) {
      throw new SecretError("REVIEWER_PROXY_SECRET_FILE mtime is in the future beyond skew");
    }
    if (now - st.mtimeMs > maxAge * 1000) {
      throw new SecretError("REVIEWER_PROXY_SECRET_FILE is stale beyond the configured max age");
    }
    // read the COMPLETE bounded file — never assume one readSync returns every byte — failing closed the
    // moment total exceeds the cap (defence in depth beyond the fstat size check). Mirrors the Python helper.
    const chunks: Buffer[] = [];
    let total = 0;
    for (;;) {
      const buf = Buffer.allocUnsafe(65536);
      const n = readSync(fd, buf, 0, buf.length, total);
      if (n === 0) break;
      total += n;
      if (total > MAX_FILE_BYTES) throw new SecretError("REVIEWER_PROXY_SECRET_FILE exceeds the 64 KiB size cap");
      chunks.push(Buffer.from(buf.subarray(0, n)));
    }
    // reject invalid UTF-8 consistently with Python's strict decode (never silently substitute U+FFFD).
    let decoded: string;
    try {
      decoded = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks));
    } catch {
      throw new SecretError("REVIEWER_PROXY_SECRET_FILE is not valid UTF-8");
    }
    const value = decoded.trim();
    if (!value) throw new SecretError("REVIEWER_PROXY_SECRET_FILE is empty after trim");
    return value;
  } finally {
    closeSync(fd);
  }
}

function sleepBusy(ms: number): void {
  // synchronous bounded pause for the sub-millisecond rename window (signing paths are sync).
  const end = Date.now() + ms;
  while (Date.now() < end) {
    /* spin briefly */
  }
}

// Resolve to [value, source]. Throws SecretError (fail-closed) on any invalid configuration.
export function resolveReviewerSecret(): [string, SecretSource] {
  const fp = filePath();
  const ev = envSecret();
  if (fp && ev) {
    throw new SecretError(
      "both REVIEWER_PROXY_SECRET_FILE and REVIEWER_PROXY_SECRET are set — ambiguous secret source, refusing",
    );
  }
  if (fp) {
    try {
      return [readSecureFile(fp), "file"];
    } catch (e) {
      if (!isENOENT(e)) throw e;
      // transient atomic-replacement race ONLY: one bounded retry, then fail closed.
      sleepBusy(RENAME_RACE_RETRY_DELAY_MS);
      try {
        return [readSecureFile(fp), "file"];
      } catch (e2) {
        if (isENOENT(e2)) throw new SecretError("REVIEWER_PROXY_SECRET_FILE is missing");
        throw e2;
      }
    }
  }
  if (ev) return [ev, "env"];
  if (devMode()) return [DEV_REVIEWER_SECRET, "dev"];
  throw new SecretError("REVIEWER_PROXY_SECRET is not configured");
}

// Non-secret health/gate signal: [configured, source]. A resolvable FILE or env secret is "configured";
// the dev fixture and any unresolved/invalid state are NOT. Never exposes the value.
export function reviewerSecretStatus(): [boolean, SecretSource | null] {
  try {
    const [, src] = resolveReviewerSecret();
    return [src === "file" || src === "env", src];
  } catch {
    return [false, null];
  }
}
