#!/usr/bin/env node
// #372 — DISCRIMINATING RED PROOF for the matrix executor (the evidence bundler).
//
// A bundler that always says ACCEPT proves nothing. This drives v372-evidence.mjs against SYNTHETIC
// Playwright reports and asserts its verdict FLIPS for each way a run can be untrue. Every case must
// behave as stated or this exits nonzero — the proof is discriminating, never tautological.
//
//   1 all mandatory rows pass                  -> ACCEPT
//   2 a mandatory row's test is ABSENT          -> that row is `not_executed`, verdict is NOT ACCEPT
//   3 a mandatory row's test FAILED             -> verdict is NOT ACCEPT
//   4 a mandatory row's test was SKIPPED        -> verdict is NOT ACCEPT (a skip is never a pass)
//   5 a mandatory row TIMED OUT                 -> verdict is NOT ACCEPT
//   6 an unrepresentable-by-design gap is never counted as passed functionality
//
// Run: node workbench/scripts/v372-redproof.mjs

import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { resolve, dirname } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORKBENCH = resolve(HERE, "..");
const BUNDLER = resolve(HERE, "v372-evidence.mjs");
// #376 — the red proof follows the bundler's parameterization, so the SAME discriminating cases run
// against the #376 matrix too. A bundler that always says ACCEPT proves nothing for either directive.
const MATRIX_PATH = process.env.MATRIX_PATH
  ? resolve(process.env.MATRIX_PATH)
  : resolve(WORKBENCH, "e2e/acceptance/v372-matrix.json");
const matrix = JSON.parse(readFileSync(MATRIX_PATH, "utf8"));
const TMP = mkdtempSync(resolve(tmpdir(), "v372-redproof-"));

const FAILS = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}: got=${JSON.stringify(got)} want=${JSON.stringify(want)}`);
  if (!ok) FAILS.push(label);
};

/** the title the bundler will look for, for a given matrix row */
const titleFor = (row) => row.bound_test_title
  ?? (row.bound_test_prefix ? `${row.bound_test_prefix} 375px` : `${row.id} synthetic`);

/** build a synthetic Playwright report where every mandatory row passes, then apply a mutation */
function report(mutate = () => {}) {
  const specs = matrix.rows.map((row) => ({
    title: titleFor(row), ok: true,
    tests: [{ results: [{ status: "passed" }] }],
  }));
  // XC-03 is bound by prefix and needs ALL its tests present
  const xc = matrix.rows.find((r) => r.bound_test_prefix);
  if (xc) for (const vp of ["768px", "1280px"]) {
    specs.push({ title: `${xc.bound_test_prefix} ${vp}`, ok: true, tests: [{ results: [{ status: "passed" }] }] });
  }
  const r = { suites: [{ file: "e2e/synthetic.spec.ts", specs }] };
  mutate(r.suites[0].specs);
  return r;
}

function verdict(rep, name) {
  const p = resolve(TMP, `${name}.json`);
  writeFileSync(p, JSON.stringify(rep));
  const out = resolve(TMP, `${name}-bundle.json`);
  try { execFileSync("node", [BUNDLER, p, out], { encoding: "utf8", stdio: "pipe",
                     env: { ...process.env, MATRIX_PATH } }); }
  catch { /* nonzero exit is expected for non-ACCEPT verdicts */ }
  return JSON.parse(readFileSync(out, "utf8"));
}

const firstMandatory = matrix.rows.find((r) => r.mandatory && !r.bound_test_prefix);
const target = titleFor(firstMandatory);
console.log(`#372 matrix-executor red proof (mutating mandatory row ${firstMandatory.id})\n`);

// 1 — the honest baseline
check("1 all mandatory pass -> ACCEPT", verdict(report(), "all-pass").recommendation, "ACCEPT");

// 2 — an ABSENT test must be `not_executed` and must NOT be accepted
const absent = verdict(report((s) => { const i = s.findIndex((x) => x.title === target); s.splice(i, 1); }), "absent");
check("2 absent mandatory test -> row not_executed",
      absent.rows.find((r) => r.id === firstMandatory.id).result, "not_executed");
check("2 absent mandatory test -> NOT ACCEPT", absent.recommendation !== "ACCEPT", true);

// 3/4/5 — failed / skipped / timedOut must each block ACCEPT (a skip is never a pass)
for (const [status, label] of [["failed", "3"], ["skipped", "4"], ["timedOut", "5"]]) {
  const rep = report((s) => {
    const t = s.find((x) => x.title === target);
    t.ok = false; t.tests = [{ results: [{ status }] }];
  });
  const v = verdict(rep, `st-${status}`);
  check(`${label} mandatory ${status} -> row reports ${status}`,
        v.rows.find((r) => r.id === firstMandatory.id).result, status);
  check(`${label} mandatory ${status} -> NOT ACCEPT`, v.recommendation !== "ACCEPT", true);
}

// 6 — unrepresentable-by-design gaps and binding predeclarations are carried into the bundle VERBATIM
// and are never counted as passed functionality. Asserted from the COMMITTED matrix rather than from a
// hardcoded #372 id list, so the case stays discriminating for whichever matrix is under proof: a
// bundler that silently dropped a gap or a ruling would fail here regardless of directive.
const base = verdict(report(), "gaps");
const declaredGapIds = (matrix.gap_register || []).map((g) => g.id).sort();
const bundledGapIds = (base.gap_register || []).map((g) => g.id).sort();
check("6 every declared gap is carried into the bundle", bundledGapIds, declaredGapIds);
const declaredRulings = (matrix.binding_predeclarations || []).map((p) => p.id).sort();
const bundledRulings = (base.binding_predeclarations || []).map((p) => p.id).sort();
check("6 every binding predeclaration is carried into the bundle", bundledRulings, declaredRulings);
check("6 a gap id is never reported as a passed matrix row",
      (base.rows || []).some((r) => declaredGapIds.includes(r.id) && r.result === "passed"), false);

console.log(`\n${FAILS.length ? "RED PROOF FAILED: " + FAILS.join(", ") : "ALL RED PROOFS DISCRIMINATE"}`);
process.exit(FAILS.length ? 1 : 0);
