import { NextResponse } from "next/server";
import { iamEnabled } from "@/lib/api-contract";

// #293 Stage 0 — V2's server-declared runtime identity, DISTINCT from V1's.
//
// V1 answers surface:"operator"|"client-trial" from TANAGHOM_BUILD_SHA. V2 answers
// surface:"workbench" from TANAGHOM_WORKBENCH_BUILD_SHA — a separate env contract, so the two
// processes can never be mistaken for one another and neither can borrow the other's identity.
//
// #202 principle, mirrored: build identity is SERVER-RUNTIME truth only. Nothing is baked at build
// time (see next.config.mjs); unset means an explicit "unknown", never a guess.
export const dynamic = "force-dynamic";

// #342 — the acceptance-lane identity, declared at RUNTIME exactly like the build SHA above.
//
// `data_class` answers the only question a human acceptance reviewer must never have to guess:
// is what I am looking at real client data or a synthetic fixture? It is deliberately a THREE-value
// answer. "synthetic" is asserted only when the operator explicitly declared it for this process;
// anything else resolves to "unknown", never to an implied "real". A default of "synthetic" would
// be far worse than useless — it would stamp a reassuring label on a lane that might be pointed at
// a real database, which is precisely the false-evidence failure this directive exists to remove.
//
// This is topology/runtime wiring in env, not product policy: it selects no behaviour, gates no
// feature, and no domain decision reads it. It only lets the surface state what it is.
const LANE_DATA_CLASSES = ["synthetic", "unknown"] as const;
function laneDataClass(): (typeof LANE_DATA_CLASSES)[number] {
  const v = (process.env.TANAGHOM_WORKBENCH_DATA_CLASS || "").trim().toLowerCase();
  return v === "synthetic" ? "synthetic" : "unknown";
}

export async function GET() {
  const runtimeSha = (process.env.TANAGHOM_WORKBENCH_BUILD_SHA || "").trim();
  const laneId = (process.env.TANAGHOM_WORKBENCH_LANE_ID || "").trim();
  const oidcIssuer = (process.env.TANAGHOM_OIDC_ISSUER || "").trim().replace(/\/$/, "");
  return NextResponse.json({
    surface: "workbench",
    build: runtimeSha || "unknown",
    // The NAMED lane instance (e.g. an acceptance lane), distinct from the lane KIND below. Unset
    // means an ordinary process, not an anonymous acceptance lane.
    lane_id: laneId || "unknown",
    data_class: laneDataClass(),
    // The transition lane is stated in the runtime truth itself, so no operator or reviewer can
    // mistake V2 for a second product or for the deployable client surface (#293 §4).
    lane: "v2-transition",
    identity: iamEnabled() ? "oidc" : "dev-fixture",
    // The issuer is non-secret configuration needed to create the governed external-identity
    // binding before IAM is enabled. Authentication mode remains independently fail-closed.
    ...(oidcIssuer ? { issuer: oidcIssuer } : {}),
  });
}
