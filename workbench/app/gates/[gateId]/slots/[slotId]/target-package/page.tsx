// #423 — the read-only final-review target-package evidence route. Server component inside the
// existing #331 shell (app/layout.tsx); it renders into the single global <main>, adds no second
// shell/nav, creates no state, and offers no action. `gateId`/`slotId` are canonical server identity,
// carried verbatim — never parsed, derived, or reinterpreted — and the endpoint decides everything.

import type { Metadata } from "next";
import { TargetPackagePanel } from "@/components/target-package-panel";

export const metadata: Metadata = {
  title: "Final-review target package — Tanaghom Workbench (V2)",
  description:
    "Read-only immutable Stage-4 target-package evidence for one gate/slot; typed recorded / " +
    "unknown_history disclosure. Renders the server verdict verbatim; it mutates nothing.",
};

export default async function TargetPackagePage({
  params,
}: {
  params: Promise<{ gateId: string; slotId: string }>;
}) {
  const { gateId, slotId } = await params;
  return <TargetPackagePanel gateId={gateId} slotId={slotId} />;
}
