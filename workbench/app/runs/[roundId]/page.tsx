import { RunWorkspace } from "@/components/run-workspace";

// #331 — the run-scoped workspace route. A real route boundary: opening a run from the schedule-first
// root NAVIGATES here, so the selected run has a stable, linkable, reload-safe URL and browser back
// returns to the schedule. `roundId` is canonical server identity, carried verbatim — never parsed,
// derived or reinterpreted.
//
// The workspace realises `selected run → stage → lens` and renders into the ONE shell <main>
// (app/layout.tsx). It no longer composes a fixed pile of surfaces below a schedule, and it mounts no
// shell chrome or DirToggle of its own — the shell (with the direction toggle) wraps every route.
export default async function RunPage({ params }: { params: Promise<{ roundId: string }> }) {
  const { roundId } = await params;
  return <RunWorkspace roundId={roundId} />;
}
