"use client";

import Link from "next/link";
import { ArrowRight, Instagram, Bot, Hand, Plug, Settings2, Waypoints } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { approvalAssignmentLabel, approvalRuleLabel, useReview, STAGES } from "@/lib/review-context";
import type { StageState } from "@/lib/review-context";
import { useClientTrialMode } from "@/lib/client-trial";
import { EmptyState } from "./empty-state";

// WORKFLOW lens — the pipeline as a live graph: each stage a node with real counts + its actor
// (AI / manual / external), flowing to the terminal PUBLISH node = Instagram. Click a node to open
// that stage in the Inbox. Everything here is real engine state; Instagram analytics stays honest.

const STATE_TONE: Record<string, string> = {
  complete: "border-success/50 bg-success/5",
  ready_to_commit: "border-success/50 bg-success/5",
  reviewing: "border-warning/50 bg-warning/5",
  start_review: "border-primary/50 bg-primary/5",
  generate: "border-primary/40 bg-primary/5",
  awaiting_regeneration: "border-warning/50 bg-warning/5",
  empty: "border-border bg-card/40",
};
const GEN = {
  ai: { label: "AI", icon: Bot },
  manual: { label: "Manual", icon: Hand },
  external: { label: "External", icon: Plug },
} as const;

function StageNode({ label, ss, onClick }: { label: string; ss?: StageState; onClick: () => void }) {
  const state = ss?.next_action || "empty";
  const gen = ss?.generator ? GEN[ss.generator] : null;
  const GenIcon = gen?.icon;
  const advanced = ss?.advanced ?? 0;
  // items needing work now: those in the open review, else those queued/pending for the stage.
  const active = ss?.in_review || ss?.review_pending || ss?.pending || 0;
  return (
    <button onClick={onClick}
      className={`flex w-[172px] shrink-0 flex-col gap-2 rounded-xl border p-3 text-left transition-colors hover:border-primary/60 ${STATE_TONE[state] || STATE_TONE.empty}`}>
      <div className="flex items-center justify-between gap-1">
        <span className="text-sm font-medium leading-tight">{label}</span>
        {gen && GenIcon && (
          <span className="flex shrink-0 items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            <GenIcon className="size-3" />{gen.label}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-1 text-center">
        {([["advanced", advanced], ["active", active], ["dropped", ss?.dropped ?? 0]] as const).map(([k, n]) => (
          <div key={k} className="rounded-md bg-background/40 py-1">
            <div className="font-mono text-sm font-semibold tabular-nums">{n}</div>
            <div className="text-[9px] uppercase tracking-wide text-muted-foreground">{k}</div>
          </div>
        ))}
      </div>
      <span className="truncate text-[10px] text-muted-foreground">{ss?.recommendation || "no items yet"}</span>
      {ss && (
        <span className="truncate text-[10px] text-muted-foreground">
          {approvalRuleLabel(ss.approval_rule)} · {ss.approval_assignments.length || ss.approval_quorum} approver{(ss.approval_assignments.length || ss.approval_quorum) === 1 ? "" : "s"}
        </span>
      )}
    </button>
  );
}

export function WorkflowLens({ onStage }: { onStage: (key: string) => void }) {
  const r = useReview();
  const clientTrial = useClientTrialMode();
  const ri = r.roundInfo;

  if (r.roundsError && !r.round) {
    return (
      <EmptyState
        variant="error"
        scope="Workflow"
        action={<Button size="sm" variant="outline" data-testid="rounds-retry" onClick={() => r.reloadRounds()}>Try again</Button>}
      />
    );
  }
  if (r.roundsLoading && !r.round) {
    return <EmptyState variant="loading" scope="Workflow" />;
  }
  if (!r.round) {
    return (
      <EmptyState
        variant="no-run"
        scope="Workflow"
        description="Pick a plan from the Plan menu above to see its stage-by-stage workflow."
      />
    );
  }

  return (
    <div className="space-y-5 px-6 py-6 pb-24">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">Workflow</h1>
        {ri && <Badge variant="outline" className="font-mono">{ri.round_id}</Badge>}
        <span className="text-sm text-muted-foreground">stage-by-stage — click a node to open it</span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {STAGES.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            <StageNode label={s.label} ss={r.roundStates[s.gate]} onClick={() => onStage(s.key)} />
            {i < STAGES.length - 1 && <ArrowRight className="size-4 shrink-0 text-muted-foreground" />}
          </div>
        ))}

        {/* terminal publish node — Instagram (the only social target today). Honest: no fake metrics. */}
        <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
        <div className="flex w-[172px] shrink-0 flex-col gap-2 rounded-xl border border-primary/50 bg-primary/5 p-3">
          <div className="flex items-center gap-1.5">
            <Instagram className="size-4 text-primary" />
            <span className="text-sm font-medium">Instagram</span>
          </div>
          <Badge variant="outline" className="w-fit text-[10px]">publish target</Badge>
          <div className="rounded-md bg-background/40 py-1 text-center">
            <div className="font-mono text-sm font-semibold tabular-nums">{ri?.scheduled ?? 0}</div>
            <div className="text-[9px] uppercase tracking-wide text-muted-foreground">queued</div>
          </div>
          <span className="text-[10px] text-muted-foreground">analytics: connect Insights</span>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        <b>advanced</b> = handed to the next stage · <b>active</b> = in review or pending · <b>dropped</b> = recoverable.
        Actors: AI generates, Manual = human production, External = integration (not yet connected).
      </p>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">Approval Policies</h2>
            <p className="text-sm text-muted-foreground">Read-only in operations. Manage versions and assignment rules in the admin workflow surface.</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline">read only</Badge>
            {r.round && !clientTrial && (
              <Button asChild variant="outline" size="sm">
                <Link href={`/runs/${r.round}/provenance`} data-testid="open-provenance"><Waypoints />Provenance</Link>
              </Button>
            )}
            {r.approvalAdmin && !clientTrial && (
              <Button asChild variant="outline" size="sm">
                <Link href="/admin/workflows"><Settings2 />Open admin</Link>
              </Button>
            )}
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          {STAGES.map((stage) => {
            const policy = r.approvalPolicies[stage.gate];
            return (
              <div key={stage.gate} className="space-y-3 rounded-xl border bg-card/50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="font-medium">{stage.label}</div>
                    <div className="text-xs text-muted-foreground">{stage.gate}</div>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{approvalRuleLabel(policy?.rule_key || "any")}</Badge>
                    <span className="text-sm text-muted-foreground">
                      {policy?.assignments.length || 0} required assignment{(policy?.assignments.length || 0) === 1 ? "" : "s"}
                    </span>
                    {policy?.source && <Badge variant="outline">{policy.source}</Badge>}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(policy?.assignments || []).map((assignment) => (
                      <Badge key={`${assignment.assignment_kind}:${assignment.assignment_key}`} variant="outline">
                        {approvalAssignmentLabel(assignment)}
                      </Badge>
                    ))}
                    {!policy?.assignments.length && <span className="text-sm text-muted-foreground">No approval assignments configured.</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
