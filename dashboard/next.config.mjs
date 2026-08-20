import { execFileSync } from "node:child_process";

/** @type {import('next').NextConfig} */
// NEXT_DIST_DIR lets an isolated build (e.g. the locked-down client-trial dashboard) write to a
// separate output dir so it never disturbs the default `.next` used by the dev dashboard.
// #180 — the build identifier is baked in at build time (env override first, then git, then
// "unknown") so every surface can visibly self-identify which build it serves.
let buildSha = (process.env.TANAGHOM_BUILD_SHA || "").trim();
if (!buildSha) {
  try {
    buildSha = execFileSync("git", ["rev-parse", "--short", "HEAD"], { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    buildSha = "unknown";
  }
}

const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  env: { NEXT_PUBLIC_BUILD_SHA: buildSha },
};
export default nextConfig;
