#!/usr/bin/env node
// #372 — evidence bundler. TEST-HARNESS ONLY.
//
// Joins the committed machine-readable matrix to the Playwright JSON report produced by the #370
// fail-closed lane, emitting: (1) a bundle mapping every matrix row id -> result + evidence artifact,
// (2) the gap register with each uncovered/unrepresentable row classified, and (3) a truthful
// ACCEPT / REJECT / CONDITIONAL recommendation.
//
// Truthfulness rules (never softened):
//  - A row is `passed` ONLY if its bound test ran and passed. A row with no matching executed test is
//    `not_executed` — never inferred, never counted as passed.
//  - Rows classified unrepresentable-by-design (PRE-02 restore_revision) or out-of-browser-scope
//    (PRE-01 the commit floor) are reported separately and NEVER counted as passed functionality.
//  - The recommendation is ACCEPT only when every mandatory row passed and all other Playwright
//    categories are zero.
//
// Usage: node workbench/scripts/v372-evidence.mjs <playwright-report.json> [<out.json>]

import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORKBENCH = resolve(HERE, "..");
// #376 — the bundler is matrix-PARAMETERIZED. Defaults are byte-identical to #372's behaviour; the
// #376 run points MATRIX_PATH/DIRECTIVE at its own committed matrix so ONE audited executor (and one
// discriminating red proof) serves both, rather than a forked copy that could drift into leniency.
const MATRIX = process.env.MATRIX_PATH
  ? resolve(process.env.MATRIX_PATH)
  : resolve(WORKBENCH, "e2e/acceptance/v372-matrix.json");
const DIRECTIVE = Number(process.env.DIRECTIVE || 372);

const reportPath = process.argv[2];
const outPath = process.argv[3] || resolve(WORKBENCH, `e2e/acceptance/v${DIRECTIVE}-evidence-bundle.json`);
if (!reportPath) { console.error("usage: v372-evidence.mjs <playwright-report.json> [out.json]"); process.exit(2); }

const matrix = JSON.parse(readFileSync(MATRIX, "utf8"));
const report = JSON.parse(readFileSync(reportPath, "utf8"));

// ---- flatten every executed spec from the Playwright report -----------------------------------
const specs = [];
const walk = (s) => { (s.specs || []).forEach((sp) => specs.push({ ...sp, file: s.file || sp.file })); (s.suites || []).forEach(walk); };
(report.suites || []).forEach(walk);

/** terminal status of one spec, using the same six mutually-exclusive categories as the lane ledger */
function categoryOf(sp) {
  const statuses = (sp.tests || []).flatMap((t) => (t.results || []).map((r) => r.status));
  if (sp.ok && statuses.length > 1 && statuses.some((s) => s !== "passed")) return "flaky";
  const terminal = statuses[statuses.length - 1];
  if (["passed", "failed", "timedOut", "interrupted", "skipped"].includes(terminal)) return terminal;
  return "failed";                       // unknown terminal is NOT a pass
}

const executed = specs.map((sp) => ({ title: sp.title || "", file: sp.file || "", category: categoryOf(sp) }));

// ---- join matrix rows -> executed tests by ID prefix -------------------------------------------
const rows = (matrix.rows || []).map((row) => {
  // Binding precedence: an explicit title (a row satisfied by an already-committed spec whose titles do
  // not carry #372 ids) > an explicit prefix (a row satisfied by SEVERAL tests — ALL must pass) > the
  // default "<ID> " title prefix. Nothing is ever inferred.
  let hit = null;
  if (row.bound_test_title) {
    hit = executed.find((e) => e.title === row.bound_test_title) || null;
  } else if (row.bound_test_prefix) {
    const group = executed.filter((e) => e.title.startsWith(row.bound_test_prefix));
    hit = group.length
      ? { title: `${group.length} tests: ${row.bound_test_prefix}…`, file: group[0].file,
          category: group.every((g) => g.category === "passed") ? "passed" : (group.find((g) => g.category !== "passed").category) }
      : null;
  } else {
    hit = executed.find((e) => e.title.startsWith(row.id + " ")) || null;
  }
  return {
    id: row.id,
    mandatory: row.mandatory === true,
    journey: row.journey ?? null,
    stage: row.stage,
    classification: row.classification,
    bound_spec: row.spec,
    executed_test: hit ? hit.title : null,
    executed_file: hit ? hit.file : null,
    result: hit ? hit.category : "not_executed",
    evidence_artifact: reportPath,
  };
});

const counts = rows.reduce((a, r) => { a[r.result] = (a[r.result] || 0) + 1; return a; }, {});
const mandatory = rows.filter((r) => r.mandatory);
const mandatoryPassed = mandatory.filter((r) => r.result === "passed");
const mandatoryNotPassed = mandatory.filter((r) => r.result !== "passed");

// Playwright-level category totals (independent of the matrix join)
const categories = executed.reduce((a, e) => { a[e.category] = (a[e.category] || 0) + 1; return a; }, {});
const nonPassed = ["failed", "timedOut", "interrupted", "skipped", "flaky"]
  .reduce((n, k) => n + (categories[k] || 0), 0);

const allMandatoryPassed = mandatoryNotPassed.length === 0 && mandatory.length > 0;
const recommendation = allMandatoryPassed && nonPassed === 0
  ? "ACCEPT"
  : (mandatoryPassed.length > 0 ? "CONDITIONAL" : "REJECT");

const bundle = {
  directive: DIRECTIVE,
  source: matrix.source,
  generated_from: reportPath,
  declared_universe: matrix.declared_universe,
  reduction_method: matrix.reduction_method,
  excluded_combinations: matrix.excluded_combinations,
  binding_predeclarations: matrix.binding_predeclarations,
  playwright_categories: {
    passed: categories.passed || 0, failed: categories.failed || 0, timedOut: categories.timedOut || 0,
    interrupted: categories.interrupted || 0, skipped: categories.skipped || 0, flaky: categories.flaky || 0,
  },
  matrix_result_counts: counts,
  mandatory_total: mandatory.length,
  mandatory_passed: mandatoryPassed.length,
  mandatory_not_passed: mandatoryNotPassed.map((r) => ({ id: r.id, result: r.result, bound_spec: r.bound_spec })),
  rows,
  gap_register: matrix.gap_register,
  recommendation,
  recommendation_basis: allMandatoryPassed && nonPassed === 0
    ? "every mandatory row passed and all other Playwright categories are zero"
    : `mandatory_not_passed=${mandatoryNotPassed.length}; non-passed playwright categories=${nonPassed}`,
  production_media_authorization: "NOT AUTHORIZED by this bundle. Passing #372 authorizes drafting/starting the Production/media vertical-slice directive; it claims no production readiness, no external integration readiness, and no complete SDR delivery.",
};

writeFileSync(outPath, JSON.stringify(bundle, null, 2) + "\n");
console.log(`[v${DIRECTIVE}-evidence] ${outPath}`);
console.log(`[v${DIRECTIVE}-evidence] mandatory ${mandatoryPassed.length}/${mandatory.length} passed | playwright ${JSON.stringify(bundle.playwright_categories)} | recommendation=${recommendation}`);
if (mandatoryNotPassed.length) console.log(`[v${DIRECTIVE}-evidence] NOT passed: ${mandatoryNotPassed.map((r) => r.id + "=" + r.result).join(", ")}`);
process.exitCode = recommendation === "ACCEPT" ? 0 : 1;
