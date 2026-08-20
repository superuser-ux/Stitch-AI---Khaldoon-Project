// #419 — the read-only Stage 4 approval-package preflight route. Server component inside the existing
// #331 shell (app/layout.tsx), so it renders into the single global <main> and adds no second shell,
// <main>, or mobile nav. It is a pure READ projection of one canonical slot's package coherence: it
// creates no run/stage/lifecycle state and offers no action. `slotId` is canonical server identity,
// carried verbatim — never parsed, derived, or reinterpreted — and the endpoint decides everything.

import type { Metadata } from "next";
import { Stage4PreflightPanel } from "@/components/stage4-preflight-panel";

export const metadata: Metadata = {
  title: "Stage 4 package preflight — Tanaghom Workbench (V2)",
  description:
    "Read-only, server-authoritative Stage 4 approval-package preflight for one canonical slot. " +
    "Renders the server's typed eligibility/denial verdict verbatim; it mutates nothing.",
};

export default async function Stage4PreflightPage({
  params,
}: {
  params: Promise<{ slotId: string }>;
}) {
  const { slotId } = await params;
  return <Stage4PreflightPanel slotId={slotId} />;
}
