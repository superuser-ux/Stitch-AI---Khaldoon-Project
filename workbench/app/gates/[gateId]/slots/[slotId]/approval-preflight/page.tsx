// #447 — the read-only Stage 4 approval-package preflight route. Server component inside the existing
// #331 shell (app/layout.tsx); it renders into the single global <main>, adds no second shell/nav,
// creates no state, and offers no action. `gateId`/`slotId` are canonical server identity, carried
// verbatim — never parsed, derived, or reinterpreted here — and the endpoint decides everything.

import type { Metadata } from "next";
import { ApprovalPreflightPanel } from "@/components/approval-preflight-panel";

export const metadata: Metadata = {
  title: "Approval-package preflight — Tanaghom Workbench (V2)",
  description:
    "Read-only Stage-4 approval-package preflight for one gate/slot: the immutable six-member package " +
    "tuple, the current governed workflow version, present final-review eligibility, and the structural " +
    "human hard floor. Renders the server read model verbatim; it mutates nothing, evaluates no " +
    "principal, and authorizes nothing.",
};

export default async function ApprovalPreflightPage({
  params,
}: {
  params: Promise<{ gateId: string; slotId: string }>;
}) {
  const { gateId, slotId } = await params;
  return <ApprovalPreflightPanel gateId={gateId} slotId={slotId} />;
}
