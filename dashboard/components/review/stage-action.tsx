"use client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { approvalAssignmentLabel, approvalRuleLabel, useReview } from "@/lib/review-context";

// The single, state-aware action for a stage when there's no open review. Driven entirely by
// stage_state.next_action — so every stage shows its real next step (generate / done / empty)
// instead of the old static "Start the review to load…" placeholder.
export function StageAction() {
  const r = useReview();
  const ss = r.stageState;
  if (r.genJob) {
    const pct = r.genJob.total ? Math.round((r.genJob.done / r.genJob.total) * 100) : 0;
    return (
      <div data-testid="job-progress" className="rounded-lg border bg-card px-4 py-3 text-sm">
        ⟳ {r.genJob.label}… {r.genJob.done} / {r.genJob.total}
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-muted">
          <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }

  if (r.gate) return null;                 // an open review is handled by the disposition bar
  if (!ss) return null;

  if (ss.next_action === "generate") {
    const noun = r.stage.key === "topic" ? "Topics" : r.stage.key === "script" ? "Scripts" : r.stage.label;
    return (
      <div className="flex flex-col gap-2 rounded-lg border bg-card px-4 py-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-muted-foreground">{ss.recommendation}</span>
          <span className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            <Badge variant="secondary">{approvalRuleLabel(ss.approval_rule)}</Badge>
            {ss.approval_assignments.map((a) => <Badge key={`${a.assignment_kind}:${a.assignment_key}`} variant="outline">{approvalAssignmentLabel(a)}</Badge>)}
          </span>
          <Button data-testid="generate-action" size="sm" className="ml-auto" disabled={r.busy || r.reviewerSyncing || !!r.genJob} onClick={r.generate}>
            Generate {noun}
          </Button>
        </div>
        {/* #265 — server-side truthful hold (e.g. an open gate held until generation completes) */}
        {ss.warnings.map((w, i) => (
          <span key={i} data-testid="stage-warning" className="text-xs text-warning">⚠ {w}</span>
        ))}
      </div>
    );
  }

  return null;   // start_review / reviewing / ready_to_commit / awaiting_regeneration / complete / empty -> disposition bar
}
