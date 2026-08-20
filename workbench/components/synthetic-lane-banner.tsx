"use client";

import { useEffect, useState } from "react";
import { readJson, type RuntimeIdentity } from "@/lib/read-model";

// #342 — states, in the UI itself, that this process is a SYNTHETIC acceptance lane.
//
// WHY THIS EXISTS. The corrected FullCalendar preview proved geometry but was pointed at a database
// carrying ~102 legacy synthetic runs. Nothing on screen said so. That is not client data, but it
// is also not credible acceptance evidence: a reviewer cannot tell "small coherent schedule" from
// "leftover test rows", and a screenshot of it carries an implied claim it has not earned.
//
// TRUTHFULNESS RULES (the whole point — a banner that can lie is worse than no banner):
//   - It renders ONLY when the server declared `data_class: "synthetic"` for this process. There is
//     no client-side inference from row counts, id prefixes, hostnames, or ports.
//   - It never appears optimistically. Until /api/runtime answers, it renders nothing rather than a
//     placeholder, because a flash of "synthetic" on a real surface is the exact lie to avoid.
//   - It makes no claim about a process that did not declare itself. "unknown" renders nothing;
//     silence is honest, whereas a default of "synthetic" would stamp reassurance on a lane that
//     might be pointed at real data.
//   - It is presentation only. It reads runtime truth and changes no behaviour, no scheduling, no
//     defaults, and no canonical state.
export function SyntheticLaneBanner() {
  const [rt, setRt] = useState<RuntimeIdentity | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    readJson<RuntimeIdentity>("/api/runtime", ac.signal)
      .then(setRt)
      .catch(() => {
        // A failed read must not be interpreted. We cannot prove the lane is synthetic, so we say
        // nothing — never a fallback banner, which would assert exactly what we just failed to read.
        setRt(null);
      });
    return () => ac.abort();
  }, []);

  if (rt?.data_class !== "synthetic") return null;

  const laneId = rt.lane_id && rt.lane_id !== "unknown" ? rt.lane_id : null;

  return (
    <div
      data-testid="synthetic-lane-banner"
      data-lane-id={laneId ?? "unnamed"}
      // `role="note"` + a label: this is standing context, not an alert. An alert role would make
      // assistive tech announce it as urgent on every route change, which it is not.
      role="note"
      aria-label="Synthetic acceptance lane"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-(--color-warn) bg-(--color-warn)/10 px-3 py-1.5 text-[11px] text-(--color-fg)"
    >
      <b data-testid="synthetic-lane-tag" className="uppercase tracking-wide">
        Synthetic acceptance lane
      </b>
      {laneId && (
        <span>
          lane <b data-testid="synthetic-lane-id" className="font-mono">{laneId}</b>
        </span>
      )}
      <span data-testid="synthetic-lane-note" className="text-(--color-muted)">
        Fixture data only — not client data. Safe to reset; nothing here is a real schedule.
      </span>
    </div>
  );
}
