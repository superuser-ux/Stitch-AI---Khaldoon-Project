import { RunsCalendarSeam } from "@/components/runs-calendar-seam";

// #331 — the schedule-first ROOT. The schedule IS the run index: the runs calendar lists every run
// (placed on the grid, unplaced stated explicitly) and opening one NAVIGATES to /runs/{id} — the
// persistent run workspace. Creating a run is a governed action reached from here, never implied by
// clicking a date. This renders into the ONE shell <main> (app/layout.tsx); it mounts no shell of its
// own and no second <main>. The old standalone "Runs / Canonical slots" panel and the calendar-after-
// footer composition (the #330 client-journey defect) are gone.
//
// V2 still runs on its own port (3001), process and service. It never becomes the V1 root route,
// reuses V1's production port, or touches client DNS/Tailscale (§4).
export default function Page() {
  return (
    <div data-testid="schedule-first-root" className="mx-auto flex max-w-5xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-sm font-semibold">Runs schedule</h1>
        <p className="text-xs text-(--color-muted)">
          The schedule is your run index. Open a run to work its lifecycle stages; start a new run by
          picking dates on the calendar — creating it stays an explicit governed action.
        </p>
      </div>
      {/* #376 — the detached Create-run form is gone. It carried its own `Days` and start date, so the
          calendar and the form described the same intent in two ways that could disagree, and it
          opened on an all-zero mix with nothing governed behind it. Both are corrected by the ONE
          composer the seam now owns. */}
      <RunsCalendarSeam />
    </div>
  );
}
