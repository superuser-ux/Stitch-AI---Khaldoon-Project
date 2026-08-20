// #387/#292 — proves workbench server-side principal signing fails closed and honours the FILE seam.
// Pure-function (no browser/network). Run:  npx tsx scripts/principal-proxy.test.ts
import { strict as assert } from "node:assert";
import { mkdtempSync, writeFileSync, chmodSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as pp from "../lib/principal-proxy.ts";

const KEYS = ["REVIEWER_PROXY_SECRET", "REVIEWER_PROXY_SECRET_FILE", "REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS", "TANAGHOM_DEV_MODE", "TANAGHOM_WORKBENCH_DEV_PRINCIPAL"];
function clearEnv() {
  for (const k of KEYS) delete process.env[k];
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
  clearEnv();
  process.env.REVIEWER_PROXY_SECRET = "real-secret-123";
  check("env configured -> reviewerSecretConfigured true", pp.reviewerSecretConfigured() === true);
  const h = pp.principalProxyHeaders("khal");
  check("signs x-principal-id/signature (sha256 hex)", h["x-principal-id"] === "khal" && /^[0-9a-f]{64}$/.test(h["x-principal-signature"]));

  clearEnv();
  process.env.TANAGHOM_DEV_MODE = "1";
  process.env.REVIEWER_PROXY_SECRET = "real-secret-123";
  check("no configured dev principal preserves khal default", pp.workbenchPrincipal() === "khal");
  process.env.TANAGHOM_WORKBENCH_DEV_PRINCIPAL = "khal";
  check("explicit permitted dev principal binds khal", pp.workbenchPrincipal() === "khal");
  const khal = pp.principalProxyHeaders(pp.workbenchPrincipal());
  process.env.TANAGHOM_WORKBENCH_DEV_PRINCIPAL = "huda";
  check("explicit permitted dev principal binds huda", pp.workbenchPrincipal() === "huda");
  const huda = pp.principalProxyHeaders(pp.workbenchPrincipal());
  check("khal and huda receive independently generated HMAC signatures",
    khal["x-principal-id"] === "khal" && huda["x-principal-id"] === "huda"
    && khal["x-principal-signature"] !== huda["x-principal-signature"]);
  const routeSource = readFileSync(join(import.meta.dirname, "../app/gw/[...path]/route.ts"), "utf8");
  check("client requests cannot select the configured principal",
    routeSource.includes("workbenchPrincipal()")
    && !/body\.(?:actor|principal|approver|principal_id)/.test(routeSource));
  process.env.TANAGHOM_WORKBENCH_DEV_PRINCIPAL = "nour";
  assert.throws(() => pp.workbenchPrincipal(), /must be one of/);
  check("unknown configured principal fails closed", true);
  delete process.env.TANAGHOM_WORKBENCH_DEV_PRINCIPAL;
  delete process.env.TANAGHOM_DEV_MODE;
  process.env.TANAGHOM_WORKBENCH_DEV_PRINCIPAL = "huda";
  assert.throws(() => pp.workbenchPrincipal(), /only in an explicit local\/dev\/test runtime/);
  check("non-dev configured principal fails closed", true);
  process.env.TANAGHOM_DEV_MODE = "1";
  process.env.TANAGHOM_WORKBENCH_DEV_PRINCIPAL = "huda";

  clearEnv();
  process.env.TANAGHOM_DEV_MODE = "1";
  check("dev-mode -> devMode() true, not configured", pp.devMode() === true && pp.reviewerSecretConfigured() === false);
  assert.doesNotThrow(() => pp.principalProxyHeaders("khal"));

  clearEnv();
  check("missing secret + no dev-mode -> not configured", pp.reviewerSecretConfigured() === false);
  assert.throws(() => pp.principalProxyHeaders("khal"), /REVIEWER_PROXY_SECRET is not configured/);

  // FILE seam wired into the workbench consumer
  const d = mkdtempSync(join(tmpdir(), "pp-"));
  const p = join(d, "reviewer_proxy_secret");
  writeFileSync(p, "file-secret-Z");
  chmodSync(p, 0o400);
  clearEnv();
  process.env.REVIEWER_PROXY_SECRET_FILE = p;
  process.env.REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS = "900";
  check("valid FILE -> configured true and signs", pp.reviewerSecretConfigured() === true && /^[0-9a-f]{64}$/.test(pp.principalProxyHeaders("khal")["x-principal-signature"]));

  clearEnv();
  console.log(failures === 0 ? "\nALL WORKBENCH PRINCIPAL-PROXY CHECKS PASSED" : `\nFAILURES: ${failures}`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
