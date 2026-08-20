"use client";
// #280 — the ONE shared empty-state contract for the operational workbench. Every lens (Overview,
// Workflow, Grid, Calendar, and the stage review surface) renders its blank/no-data areas through
// this component so the copy, structure, and accessibility are identical everywhere.
//
// It distinguishes the four states the workbench can be in with nothing to show:
//   • no-run   — no plan is selected yet (the operator must pick or start a run)
//   • no-items — a run IS selected, but this particular view/stage has no items for it
//   • loading  — a fetch that decides the above is still in flight (truthful, not "empty")
//   • error    — the data could not be loaded / a surface is unavailable
//
// TRUTHFULNESS RULE (load-bearing): copy here must never imply that generation, approval, or
// publication happened. An absence is described as an absence, and the only actions offered are ones
// the operator can actually take now. Callers pass their own governed `action` (or none).
import type { ReactNode } from "react";
import { Loader2, TriangleAlert, Inbox, LayoutDashboard, type LucideIcon } from "lucide-react";

export type EmptyStateVariant = "no-run" | "no-items" | "loading" | "error";

const PRESET: Record<EmptyStateVariant, { Icon: LucideIcon; heading: string; description: string }> = {
  "no-run": {
    Icon: LayoutDashboard,
    heading: "No run selected",
    description: "Pick a plan from the Plan menu above, or start a new run, to see it here.",
  },
  "no-items": {
    Icon: Inbox,
    heading: "Nothing to show for this view",
    description: "This run has no items at this stage yet. Nothing has been generated, approved, or published.",
  },
  loading: {
    Icon: Loader2,
    heading: "Loading…",
    description: "Fetching the latest state for this view.",
  },
  error: {
    Icon: TriangleAlert,
    heading: "This view is unavailable",
    description: "The data for this view could not be loaded. It has not changed anything — try again in a moment.",
  },
};

export function EmptyState({
  variant,
  heading,
  description,
  scope,
  icon,
  action,
  className,
  testId = "empty-state",
}: {
  variant: EmptyStateVariant;
  heading?: string;                 // override the preset heading
  description?: ReactNode;          // override the preset explanation
  scope?: ReactNode;               // the current scope (e.g. "Run R205 · Calendar") — truthful context
  icon?: LucideIcon;               // override the preset icon
  action?: ReactNode;              // a governed next action the operator can take now (optional)
  className?: string;
  testId?: string;
}) {
  const preset = PRESET[variant];
  const Icon = icon ?? preset.Icon;
  const loading = variant === "loading";
  return (
    <div
      data-testid={testId}
      data-variant={variant}
      role="status"
      aria-live={loading ? "polite" : "off"}
      aria-busy={loading || undefined}
      className={`mx-auto flex max-w-md flex-col items-center px-6 py-16 text-center ${className ?? ""}`}
    >
      <div className="mb-4 flex size-12 items-center justify-center rounded-full border border-border/70 bg-card/60 text-muted-foreground">
        <Icon className={`size-5 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`} aria-hidden />
      </div>
      <p className="text-base font-semibold text-foreground">{heading ?? preset.heading}</p>
      <p className="mt-1 text-sm text-muted-foreground">{description ?? preset.description}</p>
      {scope && (
        <p data-testid={`${testId}-scope`} className="mt-3 rounded-full border border-border/70 bg-background/70 px-3 py-1 text-xs font-medium text-muted-foreground">
          {scope}
        </p>
      )}
      {action && <div className="mt-5 flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  );
}
