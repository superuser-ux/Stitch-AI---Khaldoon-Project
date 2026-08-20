/** @type {import('next').NextConfig} */
// V2 build identity is RUNTIME truth only (#202 principle, mirrored from V1's /api/runtime): the
// exact revision is supplied by TANAGHOM_WORKBENCH_BUILD_SHA at container/process start, never
// baked here. A baked identity goes stale the moment a container is recreated from an older image.
//
// Deliberately NOT mirrored from V1: V1's next.config.mjs bakes NEXT_PUBLIC_BUILD_SHA at build time
// (#180) for its client-visible badge. V2 has no such surface yet, so it bakes nothing — one fewer
// identity to keep truthful. V2's distDir stays the package-local default; V1's NEXT_DIST_DIR
// escape hatch belongs to its own isolated-build contract and is not V2's to reuse.
const nextConfig = {
  distDir: ".next",
  // #338 — emit a self-contained production server (`.next/standalone/server.js` + traced minimal
  // node_modules) so the acceptance container ships no dev dependencies and no source tree. Additive:
  // `next build`/`next start`/dev are unchanged; standalone is an extra output the container copies
  // alongside `.next/static` and `public/`. Runtime build identity stays env-injected (never baked in
  // the bundle), so it cannot go stale when a container is recreated.
  output: "standalone",
};
export default nextConfig;
