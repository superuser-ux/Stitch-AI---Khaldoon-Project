"use client";

import { useEffect, useState } from "react";
import { Check, AlertTriangle, ArrowRight, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { approvalAssignmentLabel, approvalRuleLabel, STAGES, useReview, type Target } from "@/lib/review-context";
import { coerceViewForStage } from "@/lib/views";

// The review control bar, reusable across all 8 stages. Renders a CONTEXTUAL lifecycle state (never
// a scary "no slots" error) and the explicit, HUMAN-confirmed batch commit with an AI advisory
// (recommendation + warnings). Agents recommend; only the human's click commits (hard-floor gate).
// Gate-present advisory is computed locally (lag-free); the server `stageState` (same logic) drives
// the assistant + the no-gate contextual states.
function stagedOutcome(target: Target, approver: string) {
  if (target.current_outcome !== "pending") return target.current_outcome;
  const mine = target.decisions.filter((decision) => decision.approver_id === approver).slice(-1)[0];
  const staged = mine || target.decisions[target.decisions.length - 1];
  if (!staged) return "pending";
  if (staged.decision === "approve") return "approved";
  if (staged.decision === "request_change") return "changes_requested";
  if (staged.decision === "reject") return "rejected";
  return "pending";
}

function advise(
  targets: Target[],
  awaiting: number,
  approver: string,
  committed?: { approved?: number; sentBack?: number; rejected?: number },
) {
  const undecided = targets.filter((t) => stagedOutcome(t, approver) === "pending");
  const approved = targets.filter((t) => stagedOutcome(t, approver) === "approved").length + (committed?.approved || 0);
  const sentBack = targets.filter((t) => stagedOutcome(t, approver) === "changes_requested").length + (committed?.sentBack || 0);
  const rejected = targets.filter((t) => stagedOutcome(t, approver) === "rejected").length + (committed?.rejected || 0);
  const byPillar: Record<string, string[]> = {};
  targets.forEach((t) => (byPillar[t.pillar_code] ||= []).push(t.slot_id));
  const rejectedTargets = targets.filter((t) => stagedOutcome(t, approver) === "rejected");
  const rej = new Set(rejectedTargets.map((t) => t.slot_id));
  const gaps = Object.entries(byPillar).filter(([, ids]) => ids.length && ids.every((i) => rej.has(i))).map(([p]) => p);
  const confirm: string[] = [];
  if (undecided.length) confirm.push(`${undecided.length} item(s) still pending — they will be EXCLUDED if you commit now.`);
  if (gaps.length) confirm.push(`Coverage gap: ${gaps.join(", ")} fully dropped in this batch.`);
  const warnings = [...confirm];
  if (awaiting) warnings.push(`${awaiting} item(s) awaiting regeneration are excluded from this stage.`);
  if (!approved && !undecided.length && (sentBack || rejected)) warnings.push("Nothing will advance — every item was sent back or dropped.");
  const recommendation = undecided.length
    ? `${undecided.length} item(s) still to decide (${approved} approved so far).`
    : `Ready to commit: ${approved} will advance to the next stage${rejected ? `, ${rejected} dropped (recoverable)` : ""}.`;
  return { undecided: undecided.length, approved, sentBack, rejected, confirm, warnings, recommendation };
}

export function DispositionBar({ compact = false, embedded = false }: { compact?: boolean; embedded?: boolean }) {
  const r = useReview();
  const { gate, stageState: ss, pending, busy, stage, round, changes, selectedPending, disposition } = r;
  const actionBusy = busy || r.reviewerSyncing || !r.canDecideGate; // #175 — view-only when not assigned
  const [confirming, setConfirming] = useState(false);
  const [selectedAction, setSelectedAction] = useState<"approve" | "request_change" | "reject">("approve");
  const [batchComment, setBatchComment] = useState("");
  useEffect(() => {
    if (!r.supportsRework && selectedAction === "request_change") setSelectedAction("approve");
  }, [r.supportsRework, selectedAction]);

  // no open review → a CONTEXTUAL state from the server (never an error)
  if (!gate) {
    const state = ss?.state;
    if (state === "ready_to_start" || (!ss && (r.roundInfo?.topic_proposed ?? 0) > 0))
      return (
        <div data-testid="disposition-bar" data-state="ready_to_start" className={`flex flex-wrap items-center gap-2 ${embedded ? "" : "rounded-xl border bg-card/70"} ${compact ? "px-3 py-2" : "px-4 py-3"}`}>
          <span className="text-sm text-muted-foreground">{ss?.recommendation || "Items ready to review."}</span>
          {ss && (
            <span className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
              <Badge variant="secondary">{approvalRuleLabel(ss.approval_rule)}</Badge>
              {ss.approval_assignments.map((a) => <Badge key={`${a.assignment_kind}:${a.assignment_key}`} variant="outline">{approvalAssignmentLabel(a)}</Badge>)}
            </span>
          )}
          <Button data-testid="open-gate" className="ml-auto" size="sm" disabled={actionBusy || !round} onClick={r.openGate}>Review {stage.label}</Button>
        </div>
      );
    if (state === "awaiting_regeneration")
      return <div data-testid="disposition-bar" data-state={state} className={`${embedded ? "" : "rounded-xl border border-warning/40 bg-warning/10"} text-sm ${compact ? "px-3 py-2" : "px-4 py-3"}`}>⟳ {ss?.recommendation}</div>;
    if (state === "complete") {
      // #24 item 5 — a completed stage otherwise leaves the operator on a now-done surface with no
      // forward cue. OFFER (not force) the next stage: reuses setStageKey (which clears + reloads stage
      // state, so it can't land on a stale summary — cf. #12). No auto-navigation, no semantics change.
      const idx = STAGES.findIndex((s) => s.key === stage.key);
      const nextStage = idx >= 0 ? STAGES[idx + 1] : undefined;
      return (
        <div data-testid="disposition-bar" data-state={state} className={`flex flex-wrap items-center gap-2 ${embedded ? "" : "rounded-xl border border-success/40 bg-success/10"} text-sm ${compact ? "px-3 py-2" : "px-4 py-3"}`}>
          <span>✓ {ss?.recommendation}</span>
          {nextStage && (
            <Button data-testid="advance-next-stage" size="sm" variant="success" className="ml-auto"
              onClick={() => { r.setStageKey(nextStage.key); r.setView(coerceViewForStage(r.view, nextStage.key)); }}>
              Next: {nextStage.label} <ArrowRight />
            </Button>
          )}
        </div>
      );
    }
    return <div data-testid="disposition-bar" data-state={state || "empty"} className={`${embedded ? "" : "rounded-xl border bg-card/70"} text-sm text-muted-foreground ${compact ? "px-3 py-2" : "px-4 py-3"}`}>{ss?.recommendation || "Nothing at this stage yet."}</div>;
  }

  // open review → live disposition + human-confirmed commit + advisory (computed locally)
  const a = advise(gate.targets, changes.length, r.approver, {
    approved: disposition.committedApproved,
    sentBack: disposition.committedAwaiting,
    rejected: disposition.committedDropped,
  });
  const needsConfirm = a.confirm.length > 0;
  const nothingDecided = disposition.approved + disposition.sentBack + disposition.rejected === 0;
  const dataState = disposition.pending ? "reviewing" : "ready_to_commit";
  const doCommit = () => { setConfirming(false); r.resolve(); };
  const selectedCount = selectedPending.length;
  const actionOptions = r.supportsRework
    ? [
      { value: "approve" as const, label: "Approve selected" },
      { value: "request_change" as const, label: "Request change" },
      { value: "reject" as const, label: "Drop selected" },
    ]
    : [
      { value: "approve" as const, label: "Approve selected" },
      { value: "reject" as const, label: "Drop selected" },
    ];
  const chip = (n: number, label: string, v: "success" | "warning" | "destructive" | "outline") =>
    n > 0 ? <Badge variant={v}>{n} {label}</Badge> : null;
  const applySelected = async () => {
    const slotIds = selectedPending.map((target) => target.slot_id);
    if (!slotIds.length) return;
    if (selectedAction === "request_change") {
      const note = batchComment.trim();
      if (!note) {
        r.setToast({ kind: "err", msg: "Add one shared change request before applying it to the selected items." });
        return;
      }
      await r.decide("request_change", slotIds, note, "deferred");
      setBatchComment("");
      return;
    }
    await r.decide(selectedAction, slotIds, undefined, "deferred");
  };
  const batchActionLabel = selectedAction === "approve"
    ? "Approve"
    : selectedAction === "request_change"
      ? "Request change"
      : "Drop";
  const advisoryText = compact
    ? `${a.recommendation}${selectedCount > 0 ? ` ${selectedCount} selected for ${batchActionLabel.toLowerCase()}.` : ""}`
    : `Per-item actions apply immediately. Use checkboxes to build a selective batch, stage ${r.supportsRework ? "approve/request-change/drop" : "approve/drop"} on only those items, then apply the batch advance when the selection is ready. ${a.recommendation}`;
  const shellClass = embedded
    ? compact
      ? "rounded-xl border border-border/60 bg-background/70 px-3 py-1.5 shadow-sm"
      : "rounded-xl border border-border/60 bg-background/70 px-4 py-3 shadow-sm"
    : compact
      ? "rounded-xl border bg-card/70 px-3 py-2"
      : "rounded-xl border bg-card/70 px-4 py-3";

  return (
    <div data-testid="disposition-bar" data-state={dataState} className={`${compact ? "space-y-1.5" : "space-y-2.5"} ${shellClass}`}>
      <div className={`flex flex-wrap items-start gap-3 ${compact ? "xl:flex-nowrap" : ""}`}>
        <div className={`min-w-[15rem] flex-1 ${compact ? "space-y-1" : "space-y-2"}`}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">Review actions</span>
            <Badge variant="secondary">{approvalRuleLabel(gate.rule_key)}</Badge>
            {!compact && <Badge variant="outline">Batch tools optional</Badge>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{disposition.inReview} in review</Badge>
            {chip(disposition.approved, "approved", "success")}
            {chip(disposition.sentBack, "sent back", "warning")}
            {chip(disposition.rejected, "dropped", "destructive")}
            {chip(disposition.pending, "pending", "outline")}
            {selectedCount > 0 && <Badge variant="secondary">{selectedCount} selected</Badge>}
            {disposition.awaiting > 0 && <Badge variant="warning" data-testid="awaiting-count">⟳ {disposition.awaiting} awaiting regeneration</Badge>}
          </div>
        </div>
        <div className={`flex flex-wrap items-center gap-2 ${compact ? "xl:ml-auto xl:justify-end" : "ml-auto"}`}>
          <Button data-testid="select-all-pending" variant="outline" size="sm" disabled={actionBusy || !pending.length}
            onClick={r.selectAllPending}>Select all pending</Button>
          {selectedCount > 0 && (
            <Button data-testid="clear-selection" variant="ghost" size="sm" disabled={actionBusy}
              onClick={r.clearSelected}>Clear</Button>
          )}
          <Select value={selectedAction} onValueChange={(value: "approve" | "request_change" | "reject") => setSelectedAction(value)}>
            <SelectTrigger data-testid="selected-action" className={`h-9 ${compact ? "min-w-[11rem] flex-1 sm:w-[11rem] sm:flex-none" : "w-[160px]"}`}>
              <SelectValue placeholder="Batch action" />
            </SelectTrigger>
            <SelectContent>
              {actionOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {r.supportsRework && selectedAction === "request_change" && (
            <Input
              data-testid="batch-note"
              value={batchComment}
              onChange={(event) => setBatchComment(event.target.value)}
              placeholder="One shared change request for the selected items"
              className={`h-9 ${compact ? "min-w-[16rem] flex-1" : "w-[280px]"}`}
            />
          )}
          <Button
            data-testid="apply-selected-action"
            variant={selectedAction === "approve" ? "success" : selectedAction === "request_change" ? "warning" : "destructive"}
            size="sm"
            disabled={actionBusy || !selectedCount}
            onClick={() => { void applySelected(); }}
          >
            {selectedAction === "approve" ? <Check /> : selectedAction === "request_change" ? <Pencil /> : <X />}
            {batchActionLabel}
          </Button>
          {!confirming && (
            <Button data-testid="resolve-gate" size="sm" disabled={actionBusy || nothingDecided}
              onClick={() => (needsConfirm ? setConfirming(true) : doCommit())}>
              Apply batch <ArrowRight /> advance
            </Button>
          )}
          {confirming && <Button data-testid="confirm-commit" size="sm" variant="destructive" disabled={actionBusy} onClick={doCommit}>Apply anyway</Button>}
          {confirming && <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>}
        </div>
      </div>
      {/* AI advisory — proactive recommendation + warnings; the human has the final say */}
      <div data-testid="advisory" className="flex flex-col gap-1 text-xs">
        <span className={`rounded-lg bg-muted/35 px-2.5 ${compact ? "py-1" : "py-2"} text-muted-foreground`}>{advisoryText}</span>
        {(confirming ? a.confirm : a.warnings).map((w, i) => (
          <span key={i} data-testid="warning" className="flex items-center gap-1 text-warning"><AlertTriangle className="size-3" /> {w}</span>
        ))}
      </div>
    </div>
  );
}
