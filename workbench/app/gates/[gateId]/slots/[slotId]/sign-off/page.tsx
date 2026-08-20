// #449 — the V2 final-review sign-off action route. Server component inside the existing #331 shell
// (app/layout.tsx); it renders into the single global <main>, adds no second shell/nav, and creates no
// state. `gateId`/`slotId` are canonical server identity, carried verbatim — never parsed, derived, or
// reinterpreted here — and the merged #439/#440 command decides everything.

import type { Metadata } from "next";
import { SignOffActionPanel } from "@/components/sign-off-action-panel";

export const metadata: Metadata = {
  title: "Final-review sign-off — Tanaghom Workbench (V2)",
  description:
    "V2 action surface for human final-review sign-off on one gate/slot. It forwards the immutable " +
    "package binding fields authored by the approval-package preflight to the canonical sign-off " +
    "command and renders the server's result verbatim. It determines no authority, derives no " +
    "package, and advances no lifecycle.",
};

export default async function SignOffPage({
  params,
}: {
  params: Promise<{ gateId: string; slotId: string }>;
}) {
  const { gateId, slotId } = await params;
  return <SignOffActionPanel gateId={gateId} slotId={slotId} />;
}
