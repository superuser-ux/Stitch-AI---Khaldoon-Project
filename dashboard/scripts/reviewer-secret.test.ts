// #147 (#146 S1) — proves the dashboard reviewer-session secret handling fails closed.
// Pure-function unit test (no browser) — run with: npx tsx scripts/reviewer-secret.test.ts
// Kept out of e2e/ so Playwright never collects it.
import { strict as assert } from "node:assert";
import * as reviewer from "../lib/reviewer-session.ts";

// reviewer-session reads process.env at call time, so a single import is enough — each case
// just resets the env before calling.
function setEnv(secret?: string, dev?: string) {
  if (secret === undefined) delete process.env.REVIEWER_PROXY_SECRET;
  else process.env.REVIEWER_PROXY_SECRET = secret;
  if (dev === undefined) delete process.env.TANAGHOM_DEV_MODE;
  else process.env.TANAGHOM_DEV_MODE = dev;
}

let failures = 0;
async function run(name: string, fn: () => Promise<void>) {
  try {
    await fn();
    console.log(`  [PASS] ${name}`);
  } catch (e) {
    failures += 1;
    console.log(`  [FAIL] ${name}: ${(e as Error).message}`);
  }
}

async function main() {
  await run("configured secret is used and reported configured", async () => {
    setEnv("real-secret-123");
    const m = reviewer;
    assert.equal(m.reviewerSecretConfigured(), true);
    // a signature is produced deterministically from the configured secret (not the dev fallback)
    const sig = m.signPrincipal("khal");
    assert.equal(typeof sig, "string");
    assert.equal(sig.length, 64); // sha256 hex
  });

  await run("dev mode + no secret uses the dev fallback (not reported configured)", async () => {
    setEnv(undefined, "1");
    const m = reviewer;
    assert.equal(m.reviewerSecretConfigured(), false);
    assert.doesNotThrow(() => m.signPrincipal("khal"));
  });

  await run("missing secret + no dev mode FAILS CLOSED (throws, no silent fallback)", async () => {
    setEnv(undefined, undefined);
    const m = reviewer;
    assert.equal(m.reviewerSecretConfigured(), false);
    assert.throws(() => m.signPrincipal("khal"), /REVIEWER_PROXY_SECRET is not configured/);
  });

  await run("empty-string secret is treated as unset (fails closed, not '' key)", async () => {
    setEnv("", undefined);
    const m = reviewer;
    assert.equal(m.reviewerSecretConfigured(), false);
    assert.throws(() => m.signPrincipal("khal"), /not configured/);
  });

  console.log(failures === 0 ? "\nALL FRONTEND SECRET CHECKS PASSED" : `\nFAILURES: ${failures}`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
