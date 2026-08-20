"use client";

import { UserRound } from "lucide-react";
import { useReview, APPROVERS } from "@/lib/review-context";

// #170 (#13 S1) — internal/demo persona entry, shown before the working dashboard when this
// browser window has no persona yet. Selection is from KNOWN principals only (no free text) and is
// deliberately labeled as operational identity: it is not a login and grants nothing — the gate API
// authorizes every sensitive action server-side at decide time (#10). Overlay, not a route: the
// shell keeps mounting behind it, and client-trial mode never renders it (the provider decides).
export function PersonaEntry() {
  const r = useReview();
  const options = r.approvers.length
    ? r.approvers.map((p) => ({ id: p.principal_id, label: p.display_name_en || p.principal_id }))
    : APPROVERS.map((id) => ({ id, label: id }));

  return (
    <div
      data-testid="persona-entry"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-background/95 p-6 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded-2xl border border-border/80 bg-card p-6 shadow-xl">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-warning">
          Internal demo
        </span>
        <h1 className="mt-4 text-lg font-semibold">Who is acting in this window?</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Pick the persona this browser window represents. Each window can hold a different persona
          for multi-reviewer walkthroughs.
        </p>
        <div className="mt-5 grid gap-2">
          {options.map((o) => (
            <button
              key={o.id}
              type="button"
              data-testid={`persona-option-${o.id}`}
              onClick={() => r.enterPersona(o.id)}
              className="flex items-center gap-3 rounded-xl border border-border/80 bg-background/60 px-4 py-3 text-left text-sm font-medium transition-colors hover:border-primary/50 hover:bg-primary/5"
            >
              <UserRound className="size-4 shrink-0 text-muted-foreground" />
              <span>{o.label}</span>
              <span className="ml-auto text-xs text-muted-foreground">{o.id}</span>
            </button>
          ))}
        </div>
        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
          This is persona selection, not a login — no password, SSO, or access control. Approvals
          are still authorized server-side against the workflow&apos;s assignments, and a persona
          without the required assignment will be rejected there.
        </p>
      </div>
    </div>
  );
}
