// #410 — the /studio landing route. Server component inside the existing #331 shell (app/layout.tsx),
// so it renders into the single global <main>; it adds no second shell, <main>, or mobile nav. It is
// OUTSIDE run/stage/lens context: /studio is not a run route, so ShellNavProvider resolves no run and
// entering Studio cannot create or reinterpret one. The originating Workbench URL arrives as `from` and
// is validated to a safe internal path here before it reaches the client view.

import type { Metadata } from "next";
import { StudioView } from "@/components/studio/studio-view";
import { safeInternalPath } from "@/lib/safe-return";

export const metadata: Metadata = {
  title: "Process Studio — Tanaghom Workbench (V2)",
  description:
    "Read-only demonstration of the generic workflow graph direction. Not loaded from active runtime configuration.",
};

export default async function StudioPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string | string[] }>;
}) {
  const sp = await searchParams;
  const raw = Array.isArray(sp.from) ? sp.from[0] : sp.from;
  const returnTo = safeInternalPath(raw);
  return <StudioView returnTo={returnTo} />;
}
