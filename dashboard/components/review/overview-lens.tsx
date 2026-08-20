"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Instagram, Send, PlugZap, BarChart3, CircleDot } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { approvalAssignmentLabel, approvalRuleLabel, useReview, STAGES, GW, roundActiveCount, roundApprovedCount } from "@/lib/review-context";
import { EmptyState } from "./empty-state";

// OVERVIEW lens — the "what needs me + where is everything" landing, built ENTIRELY from real
// engine data (roundInfo + per-stage states). Distribution/analytics render as honest connect
// states: no integration yet ⇒ no invented numbers (this screen may be shown to the client).

type Integration = { name: string; stage: string; enabled: boolean; kind: string };

// which stages actually want the reviewer's attention now, in pipeline order
const ACTIONABLE: Record<string, { label: string; tone: "primary" | "warning" | "success" | "muted" }> = {
  generate: { label: "Generate", tone: "primary" },
  start_review: { label: "Review", tone: "primary" },
  reviewing: { label: "In review", tone: "warning" },
  ready_to_commit: { label: "Ready to commit", tone: "success" },
  awaiting_regeneration: { label: "Awaiting regeneration", tone: "warning" },
};

function Kpi({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-3xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

function FunnelStep({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex min-w-[92px] flex-col items-center rounded-lg border bg-card/60 px-3 py-2">
      <span className="font-mono text-xl font-semibold tabular-nums">{n}</span>
      <span className="text-center text-[11px] leading-tight text-muted-foreground">{label}</span>
    </div>
  );
}

export function OverviewLens({ onStage }: { onStage: (key: string, roundId?: string | null) => void }) {
  const r = useReview();
  const ri = r.roundInfo;
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  useEffect(() => { fetch(`${GW}/integrations`).then((x) => x.json()).then(setIntegrations).catch(() => {}); }, []);

  if (r.roundsError && !r.round) {
    return (
      <EmptyState
        variant="error"
        scope="Overview"
        action={<Button size="sm" variant="outline" data-testid="rounds-retry" onClick={() => r.reloadRounds()}>Try again</Button>}
      />
    );
  }
  if (r.roundsLoading && !r.round) {
    return <EmptyState variant="loading" scope="Overview" />;
  }
  if (!r.round || !ri) {
    return (
      <EmptyState
        variant="no-run"
        scope="Overview"
        description="Pick a plan from the Plan menu above, or start a new run, to see its overview."
      />
    );
  }

  const inFlight = roundActiveCount(ri);
  const analyticsOn = integrations.find((i) => i.name === "analytics")?.enabled ?? false;
  const distributionOn = integrations.find((i) => i.stage === "distribution")?.enabled ?? false;

  // the review queue — real per-stage states, only the stages that need action
  const queue = STAGES
    .map((s) => ({ s, ss: r.roundStates[s.gate] }))
    .filter(({ ss }) => ss && ACTIONABLE[ss.next_action]);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-6 pb-24">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">Overview</h1>
        <Badge variant="outline" className="font-mono">{ri.round_id}</Badge>
        <Badge variant="secondary">{ri.phase}</Badge>
        <span className="text-sm text-muted-foreground">{ri.slots} slots planned · {ri.reserved} awaiting schedule review · {ri.schedule_approved} schedule approved</span>
      </div>

      {/* KPIs — all real, from the engine */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="In flight" value={inFlight} hint="items live in this run" />
        <Kpi label="Approved" value={roundApprovedCount(ri)} hint="topics + scripts" />
        <Kpi label="Scheduled" value={ri.scheduled} hint="queued to publish" />
        <Kpi label="Needs attention" value={ri.changes_requested + ri.rejected}
          hint={`${ri.changes_requested} awaiting · ${ri.rejected} dropped`} />
      </div>

      {/* pipeline funnel — real counts across the content stages */}
      <section className="rounded-xl border bg-card/40 p-4">
        <div className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Pipeline</div>
        <div className="flex flex-wrap items-center gap-2">
          <FunnelStep n={ri.reserved} label="Schedule proposed" />
          <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          <FunnelStep n={ri.schedule_approved} label="Schedule approved" />
          <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          <FunnelStep n={ri.topic_proposed} label="Topics proposed" />
          <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          <FunnelStep n={ri.topic_approved} label="Topics approved" />
          <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          <FunnelStep n={ri.draft} label="Scripts drafted" />
          <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          <FunnelStep n={ri.approved} label="Scripts approved" />
          <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          <FunnelStep n={ri.scheduled} label="Scheduled" />
        </div>
      </section>

      {/* review queue — what actually needs the reviewer, deep-links into the Inbox stage */}
      <section className="rounded-xl border bg-card/40 p-4">
        <div className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Needs you now</div>
        {queue.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing is waiting on you in this run.</p>
        ) : (
          <ul className="space-y-2">
            {queue.map(({ s, ss }) => {
              const meta = ACTIONABLE[ss!.next_action];
              return (
                <li key={s.key} className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-3 py-2">
                  <CircleDot className={`size-4 shrink-0 ${meta.tone === "success" ? "text-success" : meta.tone === "warning" ? "text-warning" : "text-primary"}`} />
                  <span className="text-sm font-medium">{s.label}</span>
                  <Badge variant={meta.tone === "success" ? "success" : meta.tone === "warning" ? "warning" : "outline"}>{meta.label}</Badge>
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{ss!.recommendation}</span>
                  <Button size="sm" variant="outline" onClick={() => onStage(s.key)}>Open <ArrowRight /></Button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="rounded-xl border bg-card/40 p-4">
        <div className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">My approvals</div>
        {r.pendingApprovals.length === 0 ? (
          <p className="text-sm text-muted-foreground">No open approvals are currently assigned to {r.approver}.</p>
        ) : (
          <ul className="space-y-2">
            {r.pendingApprovals.map((p) => {
              const stageKey = STAGES.find((s) => s.gate === p.stage)?.key;
              return (
                <li key={p.gate_id} className="rounded-lg border bg-card px-3 py-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant="outline">{p.round_id || "no round"}</Badge>
                    <span className="text-sm font-medium">{p.stage}</span>
                    <Badge variant="secondary">{approvalRuleLabel(p.rule_key)}</Badge>
                    <span className="text-xs text-muted-foreground">{p.remaining_targets} remaining of {p.total_targets}</span>
                    {stageKey && <Button size="sm" variant="outline" className="ml-auto" onClick={() => onStage(stageKey, p.round_id)}>Open <ArrowRight /></Button>}
                  </div>
                  <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                    <div>Matched via: {p.matched_assignments.map((a) => approvalAssignmentLabel(a)).join(", ")}</div>
                    <div>Required approvers: {p.all_assignments.map((a) => approvalAssignmentLabel(a)).join(", ")}</div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* distribution — Instagram = publish target · Telegram = control channel. Honest connect states. */}
      <section className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border bg-card/40 p-4">
          <div className="mb-2 flex items-center gap-2">
            <Instagram className="size-4 text-primary" />
            <span className="text-sm font-medium">Instagram</span>
            <Badge variant="outline" className="text-[10px]">publish target</Badge>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-2xl font-semibold tabular-nums">{ri.scheduled}</span>
            <span className="text-sm text-muted-foreground">queued to publish</span>
          </div>
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <BarChart3 className="size-4 shrink-0" />
            {analyticsOn
              ? "Instagram Insights connected."
              : "Connect Instagram Insights to see reach & engagement — no data yet."}
            {!analyticsOn && <Button size="sm" variant="ghost" className="ml-auto h-7 px-2 text-xs" disabled>Connect</Button>}
          </div>
        </div>

        <div className="rounded-xl border bg-card/40 p-4">
          <div className="mb-2 flex items-center gap-2">
            <Send className="size-4 text-[#38bdf8]" />
            <span className="text-sm font-medium">Telegram</span>
            <Badge variant="outline" className="text-[10px]">control channel</Badge>
          </div>
          <p className="text-sm text-muted-foreground">Approvals, change-requests & the Agent Rep — from your phone.</p>
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <PlugZap className="size-4 shrink-0" />
            {distributionOn ? "Channel connected." : "Connect the Telegram channel to manage approvals here — not linked yet."}
            {!distributionOn && <Button size="sm" variant="ghost" className="ml-auto h-7 px-2 text-xs" disabled>Connect</Button>}
          </div>
        </div>
      </section>
    </div>
  );
}
