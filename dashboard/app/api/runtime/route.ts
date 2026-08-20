import { NextResponse } from "next/server";
import { iamEnabled } from "@/lib/iam-session";

// #180 — server-declared runtime identity: which SURFACE this process intentionally serves and
// which BUILD it runs. `surface` reads the SAME runtime env the middleware enforces its route
// blocking with, so the UI's privilege gating follows server truth — stale browser cookies /
// local state are presentation-advisory only and can never suppress operator controls here.
// Writer/runtime mode deliberately stays with the existing gate-API /health read model (reused
// by the dashboard already) rather than being duplicated into this endpoint.
export async function GET() {
  // #202 — build identity is SERVER-RUNTIME truth ONLY: TANAGHOM_BUILD_SHA is stamped onto the
  // process/container at start (deployments recreate containers without rebuilding images, and
  // the deploy build context has no .git to bake a revision from). The bake-time
  // NEXT_PUBLIC_BUILD_SHA is a client-oriented value and deliberately NEVER consulted here — a
  // stale baked revision must not masquerade as deployed runtime truth. Unset/blank means an
  // explicit "unknown", never a guess.
  const runtimeSha = (process.env.TANAGHOM_BUILD_SHA || "").trim();
  return NextResponse.json({
    surface: process.env.CLIENT_TRIAL_MODE === "true" ? "client-trial" : "operator",
    build: runtimeSha || "unknown",
    // #190 — how identity is established on THIS server: "oidc" (authenticated sessions; persona
    // surfaces disabled) or "demo" (#170 persona flow, internal/dev only). Server-declared so
    // stale client state can never re-enable demo identity paths under IAM.
    identity: iamEnabled() ? "oidc" : "demo",
    // #194/#195 — the canonical issuer this server's sign-ins use (non-secret URL). The identity
    // admin surface derives the issuer from THIS server truth instead of free-text input.
    ...(iamEnabled() ? { issuer: (process.env.TANAGHOM_OIDC_ISSUER || "").trim().replace(/\/$/, "") } : {}),
  });
}
