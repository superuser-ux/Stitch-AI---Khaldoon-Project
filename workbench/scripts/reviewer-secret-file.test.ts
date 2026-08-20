// #387 — focused unit test for the manager-neutral reviewer-proxy FILE resolver (TS mirror of
// gates/reviewer_secret_selftest.py). Pure-function; no browser/network. Run:
//   npx tsx scripts/reviewer-secret-file.test.ts
// Kept out of e2e/ so Playwright never collects it.
import { strict as assert } from "node:assert";
import { mkdtempSync, writeFileSync, chmodSync, utimesSync, symlinkSync, renameSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as rs from "../lib/reviewer-secret-file.ts";

const ENV_KEYS = [
  "REVIEWER_PROXY_SECRET",
  "REVIEWER_PROXY_SECRET_FILE",
  "REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS",
  "TANAGHOM_DEV_MODE",
];
function clearEnv() {
  for (const k of ENV_KEYS) delete process.env[k];
}
function writeSecret(dir: string, opts: { value?: string; mode?: number; ageSec?: number; name?: string } = {}) {
  const p = join(dir, opts.name ?? "reviewer_proxy_secret");
  writeFileSync(p, opts.value ?? "file-backed-secret-XYZ");
  chmodSync(p, opts.mode ?? 0o400);
  if (opts.ageSec) {
    const t = Date.now() / 1000 - opts.ageSec;
    utimesSync(p, t, t);
  }
  return p;
}
function expectSecretError(fn: () => void): { ok: boolean; msg: string } {
  try {
    fn();
    return { ok: false, msg: "no-throw" };
  } catch (e) {
    return { ok: e instanceof rs.SecretError, msg: (e as Error).message };
  }
}

let failures = 0;
function check(name: string, cond: boolean) {
  if (cond) console.log(`  [PASS] ${name}`);
  else {
    failures += 1;
    console.log(`  [FAIL] ${name}`);
  }
}

function main() {
  const d = mkdtempSync(join(tmpdir(), "revsec-ts-"));
  const secretValue = "file-backed-secret-XYZ";

  clearEnv();
  process.env.REVIEWER_PROXY_SECRET = "  env-secret-123  ";
  check("env resolves trimmed as 'env'", JSON.stringify(rs.resolveReviewerSecret()) === JSON.stringify(["env-secret-123", "env"]));
  check("env status configured=true source=env", JSON.stringify(rs.reviewerSecretStatus()) === JSON.stringify([true, "env"]));

  clearEnv();
  process.env.TANAGHOM_DEV_MODE = "1";
  check("dev-mode uses dev fixture", JSON.stringify(rs.resolveReviewerSecret()) === JSON.stringify([rs.DEV_REVIEWER_SECRET, "dev"]));
  check("dev fixture NOT configured", JSON.stringify(rs.reviewerSecretStatus()) === JSON.stringify([false, "dev"]));

  clearEnv();
  check("nothing configured -> status [false,null]", JSON.stringify(rs.reviewerSecretStatus()) === JSON.stringify([false, null]));
  {
    const r = expectSecretError(() => rs.resolveReviewerSecret());
    check("nothing configured -> SecretError not-configured", r.ok && /not configured/.test(r.msg));
  }

  const p = writeSecret(d, { mode: 0o400 });
  clearEnv();
  process.env.REVIEWER_PROXY_SECRET_FILE = p;
  process.env.REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS = "900";
  check("valid FILE resolves as 'file'", JSON.stringify(rs.resolveReviewerSecret()) === JSON.stringify([secretValue, "file"]));
  check("valid FILE configured source=file", JSON.stringify(rs.reviewerSecretStatus()) === JSON.stringify([true, "file"]));

  process.env.TANAGHOM_DEV_MODE = "1";
  check("FILE authoritative even under dev-mode", rs.resolveReviewerSecret()[1] === "file");
  delete process.env.TANAGHOM_DEV_MODE;

  process.env.REVIEWER_PROXY_SECRET = "env-and-file";
  check("both FILE+env -> ambiguous", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("ambiguous"));
  delete process.env.REVIEWER_PROXY_SECRET;

  delete process.env.REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS;
  check("FILE without positive max-age -> error", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("MAX_AGE"));
  process.env.REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS = "900";

  process.env.REVIEWER_PROXY_SECRET_FILE = "relative/secret";
  check("relative path -> error", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("absolute"));
  process.env.REVIEWER_PROXY_SECRET_FILE = p;

  chmodSync(p, 0o444);
  check("world-readable FILE -> error (no fallback)", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("permission"));
  chmodSync(p, 0o400);

  const link = join(d, "link_secret");
  symlinkSync(p, link);
  process.env.REVIEWER_PROXY_SECRET_FILE = link;
  check("symlink FILE -> error", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("symlink"));
  process.env.REVIEWER_PROXY_SECRET_FILE = p;

  const big = writeSecret(d, { value: "x".repeat(rs.MAX_FILE_BYTES + 1), mode: 0o400, name: "big" });
  process.env.REVIEWER_PROXY_SECRET_FILE = big;
  check("oversize FILE -> error", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("size cap"));
  process.env.REVIEWER_PROXY_SECRET_FILE = p;

  const empty = writeSecret(d, { value: "   \n", mode: 0o400, name: "empty" });
  process.env.REVIEWER_PROXY_SECRET_FILE = empty;
  check("empty-after-trim FILE -> error", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("empty"));
  process.env.REVIEWER_PROXY_SECRET_FILE = p;

  const stale = writeSecret(d, { mode: 0o400, ageSec: 1000, name: "stale" });
  process.env.REVIEWER_PROXY_SECRET_FILE = stale;
  check("stale FILE -> error", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("stale"));
  process.env.REVIEWER_PROXY_SECRET_FILE = p;

  const future = writeSecret(d, { mode: 0o400, ageSec: -120, name: "future" });
  process.env.REVIEWER_PROXY_SECRET_FILE = future;
  check("future-mtime FILE -> error", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("future"));
  process.env.REVIEWER_PROXY_SECRET_FILE = p;

  process.env.REVIEWER_PROXY_SECRET_FILE = join(d, "does-not-exist");
  process.env.TANAGHOM_DEV_MODE = "1"; // prove NO dev fallback for an invalid FILE
  check("missing FILE -> error even with dev-mode (no fallback)", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("missing"));
  delete process.env.TANAGHOM_DEV_MODE;
  process.env.REVIEWER_PROXY_SECRET_FILE = p;

  const tmp = join(d, ".reviewer_proxy_secret.tmp");
  writeFileSync(tmp, "rotated-secret-2");
  chmodSync(tmp, 0o400);
  renameSync(tmp, p); // atomic same-dir replacement over the leaf
  check("atomic replacement observed without restart", rs.resolveReviewerSecret()[0] === "rotated-secret-2");

  {
    process.env.REVIEWER_PROXY_SECRET_FILE = stale;
    const r = expectSecretError(() => rs.resolveReviewerSecret());
    check("error messages never contain the secret value", r.ok && !r.msg.includes("rotated-secret-2") && !r.msg.includes("file-backed-secret"));
  }

  // PARITY: the COMPLETE bounded file is read (value at the exact size cap resolves in full)
  const capval = "A".repeat(rs.MAX_FILE_BYTES);
  const capf = join(d, "capfull");
  writeFileSync(capf, capval);
  chmodSync(capf, 0o400);
  process.env.REVIEWER_PROXY_SECRET_FILE = capf;
  {
    const [v, src] = rs.resolveReviewerSecret();
    check("complete bounded read: full-size (64 KiB) file read in its entirety", src === "file" && v === capval && v.length === rs.MAX_FILE_BYTES);
  }

  // PARITY: invalid UTF-8 is rejected (strict), matching Python's strict decode
  const badf = join(d, "badutf8");
  writeFileSync(badf, Buffer.from([0xff, 0xfe, 0x00, 0x6e, 0x6f]));
  chmodSync(badf, 0o400);
  process.env.REVIEWER_PROXY_SECRET_FILE = badf;
  check("invalid UTF-8 FILE -> SecretError (not valid UTF-8)", expectSecretError(() => rs.resolveReviewerSecret()).msg.includes("UTF-8"));

  clearEnv();
  console.log(failures === 0 ? "\nALL FILE-RESOLVER CHECKS PASSED" : `\nFAILURES: ${failures}`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
