#!/usr/bin/env node
// #293 §3 — brand continuity gate.
//
// V2 must render the EXACT canonical Tanaghom and "Powered by Stitch" marks — never redrawn,
// substituted, renamed, or text-only. V2 holds its own copy (Next serves each package's own
// public/ dir; a symlink would not survive a container build context), so the risk is DRIFT: V1's
// mark changes and V2 silently keeps serving a stale one.
//
// This script makes that failure loud and mechanical. dashboard/public/brand/** is the CANONICAL
// SOURCE; workbench/public/brand/** must match it byte for byte. It is read-only: it never
// rewrites V1, and it never auto-heals V2 (silently re-copying would hide the very drift this
// exists to surface). On drift it prints the exact fix and exits non-zero.

import { createHash } from "node:crypto";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const workbench = path.resolve(here, "..");
const repo = path.resolve(workbench, "..");
const canonicalRoot = path.join(repo, "dashboard", "public", "brand");
const copyRoot = path.join(workbench, "public", "brand");

// The exact marks #293 §3 requires both surfaces to render.
const MARKS = [
  { rel: "tenants/tanaghum/tanaghom-logo.png", accessibleName: "Tanaghom" },
  { rel: "platform/stitch/stitch-logo.png", accessibleName: "Stitch" },
];

const sha256 = (p) => createHash("sha256").update(readFileSync(p)).digest("hex");

let failed = false;
for (const mark of MARKS) {
  const canonical = path.join(canonicalRoot, mark.rel);
  const copy = path.join(copyRoot, mark.rel);

  if (!existsSync(canonical)) {
    console.error(`FAIL  canonical mark missing from V1: dashboard/public/brand/${mark.rel}`);
    failed = true;
    continue;
  }
  if (!existsSync(copy)) {
    console.error(
      `FAIL  V2 is missing the mark: workbench/public/brand/${mark.rel}\n` +
        `      fix: cp dashboard/public/brand/${mark.rel} workbench/public/brand/${mark.rel}`,
    );
    failed = true;
    continue;
  }

  const a = sha256(canonical);
  const b = sha256(copy);
  if (a !== b) {
    console.error(
      `FAIL  BRAND DRIFT on ${mark.rel}\n` +
        `      canonical (V1): ${a}\n` +
        `      copy      (V2): ${b}\n` +
        `      The canonical mark changed and V2 is stale. Re-copy it deliberately:\n` +
        `      cp dashboard/public/brand/${mark.rel} workbench/public/brand/${mark.rel}`,
    );
    failed = true;
    continue;
  }
  console.log(`ok    ${mark.rel}  sha256=${a}  alt="${mark.accessibleName}"`);
}

if (failed) {
  console.error("\nbrand verification FAILED — V2 must render the exact canonical marks (#293 §3).");
  process.exit(1);
}
console.log("\nbrand verification passed: V2 serves the exact canonical bytes.");
