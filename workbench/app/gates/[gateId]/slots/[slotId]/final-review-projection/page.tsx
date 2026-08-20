// #431 — the read-only Stage 4 final-review projection route. Server component inside the existing
// #331 shell (app/layout.tsx); it renders into the single global <main>, adds no second shell/nav,
// creates no state, and offers no action. `gateId`/`slotId` are canonical server identity, carried
// verbatim — never parsed, derived, or reinterpreted here — and the endpoint decides everything.

import type { Metadata } from "next";
import { FinalReviewProjectionPanel } from "@/components/final-review-projection-panel";

export const metadata: Metadata = {
  title: "Final-review projection — Tanaghom Workbench (V2)",
  description:
    "Read-only Stage-4 final-review evidence projection for one gate/slot: independent typed evidence " +
    "groups with fail-closed uncertainty and gate-scoped audit. Renders the server projection verbatim; " +
    "it mutates nothing and infers nothing.",
};

export default async function FinalReviewProjectionPage({
  params,
}: {
  params: Promise<{ gateId: string; slotId: string }>;
}) {
  const { gateId, slotId } = await params;
  return <FinalReviewProjectionPanel gateId={gateId} slotId={slotId} />;
}
