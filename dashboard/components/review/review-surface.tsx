"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Activity, ArrowUpDown, CalendarDays, Check, CheckCircle2, ChevronDown, ChevronUp, CircleHelp, Clock3, ListChecks, ListFilter, Pencil, RefreshCcw, Search, ShieldAlert, ShieldCheck, Target as TargetIcon, Undo2, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScheduleRevisionControl } from "@/components/review/schedule-revision-control";
import { RunMixControl } from "@/components/review/run-mix-control";
import { Textarea } from "@/components/ui/textarea";
import { approvalAssignmentLabel, approvalRuleLabel, contentIdLabel, resolveContentId, stagedOutcome, useReview, type ContentIdMode, type Target } from "@/lib/review-context";
import { sortFeed, SORT_OPTIONS, type SortMode } from "@/lib/review-sort";
import { searchFeed, normalizeQuery } from "@/lib/review-search";
import { filterFeed, pillarOptions, formatOptions, type AttrFilters } from "@/lib/review-filter";
import { stageLabel } from "@/lib/stages";
import { DispositionBar } from "./disposition-bar";
import { ReviewItem, type Density } from "./review-item";
import { PublicationRecord } from "./publication-record";
import { SdamReadiness } from "./sdam-readiness";
import { TrailInspect } from "./trail-inspect";
import { StageAction } from "./stage-action";
import { EmptyState } from "./empty-state";
import { Bilingual } from "./bilingual";

const DENSITIES: { key: Density; label: string }[] = [
  { key: "chip", label: "Chip" },
  { key: "compact", label: "Compact" },
  { key: "full", label: "Full" },
];
const ID_MODES: { key: ContentIdMode; label: string }[] = [
  { key: "compact", label: "Compact ID" },
  { key: "expanded", label: "Expanded ID" },
  { key: "detailed", label: "Detailed ID" },
];

export type Layout = "list" | "grid" | "calendar";

function primaryCodeLabel(stageKey: string) {
  if (stageKey === "schedule") return "Schedule Code";
  if (stageKey === "topic") return "Topic Code";
  if (stageKey === "script") return "Script Code";
  if (stageKey === "final") return "Approval Code";
  if (stageKey === "production") return "Production Code";
  if (stageKey === "edit") return "Edit Code";
  if (stageKey === "distribution") return "Distribution Code";
  return "Content Code";
}

function slotWindowLabel(time: string) {
  const hour = Number.parseInt((time || "00:00").split(":")[0] || "0", 10);
  if (hour < 12) return "Morning";
  if (hour < 17) return "Midday";
  return "Evening";
}

function byDay(targets: Target[]): Array<{ day: number; items: Target[] }> {
  const map = new Map<number, Target[]>();
  targets.forEach((target) => {
    const items = map.get(target.day) || [];
    items.push(target);
    map.set(target.day, items);
  });
  return Array.from(map.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([day, items]) => ({
      day,
      items: items.sort((a, b) => a.time_uae.localeCompare(b.time_uae) || a.slot_id.localeCompare(b.slot_id)),
    }));
}

function slotTimes(targets: Array<{ time_uae: string }>) {
  return Array.from(new Set(targets.map((target) => target.time_uae)))
    .sort((a, b) => a.localeCompare(b));
}

function weekBoard<T extends { day: number; time_uae: string; slot_id: string }>(targets: T[], totalDays: number) {
  const slots = new Map<string, T>();
  targets.forEach((target) => slots.set(`${target.day}:${target.time_uae}`, target));
  const weeks: Array<{ week: number; days: Array<{ day: number; slots: Array<T | null> }> }> = [];
  const times = slotTimes(targets);
  for (let start = 1; start <= totalDays; start += 7) {
    const days: Array<{ day: number; slots: Array<T | null> }> = [];
    for (let day = start; day < Math.min(start + 7, totalDays + 1); day += 1) {
      days.push({
        day,
        slots: times.map((time) => slots.get(`${day}:${time}`) || null),
      });
    }
    weeks.push({ week: Math.floor((start - 1) / 7) + 1, days });
  }
  return { weeks, times };
}

function calendarCellTone(density: Density) {
  if (density === "chip") return "space-y-1.5";
  if (density === "full") return "space-y-3";
  return "space-y-2";
}

function outcomeLabel(outcome: Target["current_outcome"]) {
  if (outcome === "changes_requested") return "Awaiting rework";
  if (outcome === "rejected") return "Dropped";
  if (outcome === "approved") return "Approved";
  return "Pending";
}

function metricTone(kind: "neutral" | "success" | "warning" | "destructive" | "active") {
  if (kind === "success") return "border-success/25 bg-success/10";
  if (kind === "warning") return "border-warning/25 bg-warning/10";
  if (kind === "destructive") return "border-destructive/25 bg-destructive/10";
  if (kind === "active") return "border-primary/25 bg-primary/10";
  return "border-border/70 bg-background/70";
}

function metricChipTone(kind: "neutral" | "success" | "warning" | "destructive" | "active") {
  if (kind === "success") return "border-success/20 bg-success/10 text-success";
  if (kind === "warning") return "border-warning/20 bg-warning/10 text-warning";
  if (kind === "destructive") return "border-destructive/20 bg-destructive/10 text-destructive";
  if (kind === "active") return "border-primary/20 bg-primary/10 text-primary";
  return "border-border/70 bg-background/80 text-foreground";
}

// ONE canonical review surface over the open gate's records. The SAME fluid cards + decide actions
// render as a list (Inbox), a gallery (Grid), or a day grid (Calendar) — only the arrangement
// differs. The disposition bar, awaiting/dropped lanes, and every testid are shared across layouts.
export function ReviewSurface({ layout = "list" }: { layout?: Layout }) {
  const r = useReview();
  const { gate, changes, dropped, justApproved, roundInfo, stage, round, stageState, toast } = r;
  // #134 (count contract #131 Slice B) — run-level lifecycle funnel: READ-ONLY explanatory strip.
  // Refetched on the same cadence as the stage snapshot (round/stageState) so the two families of
  // numbers move together (I6); its values must NEVER feed the stage-level disposition below.
  type FunnelStage = { stage: string; entered: number; in_stage: number; awaiting: number; dropped: number; advanced: number };
  const [funnel, setFunnel] = useState<{ total: number; completed: number; stages: FunnelStage[] } | null>(null);
  useEffect(() => {
    let alive = true;
    if (!round) { setFunnel(null); return; }
    fetch(`/gw/rounds/${round}/funnel`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((f) => { if (alive) setFunnel(f); })
      .catch(() => { /* explanatory-only: a missing funnel never degrades the review surface */ });
    return () => { alive = false; };
  }, [round, stageState]);
  const [density, setDensity] = useState<Density>("compact");   // section-level card density
  const [idMode, setIdMode] = useState<ContentIdMode>("expanded");
  const [expandedDropped, setExpandedDropped] = useState<Set<string>>(new Set());   // #24 item 3: per-item detail
  const toggleDroppedDetail = (slotId: string) =>
    setExpandedDropped((cur) => {
      const next = new Set(cur);
      next.has(slotId) ? next.delete(slotId) : next.add(slotId);
      return next;
    });
  const wide = layout !== "list";
  // #261 — publish the sticky control region's LIVE height (it wraps taller at narrow widths) as
  // --review-sticky-h, so the scroll container can reserve exactly that much scroll-padding-top.
  // Then a scrolled-into-view control always lands BELOW the sticky band and ordinary pointer
  // click() hits it — no sticky/stacking interception, without disabling sticky or masking overflow.
  const stickyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = stickyRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const publish = () => document.documentElement.style.setProperty("--review-sticky-h", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    publish();
    const ro = new ResizeObserver(publish);
    ro.observe(el);
    return () => { ro.disconnect(); document.documentElement.style.removeProperty("--review-sticky-h"); };
  }, [layout, wide]);
  const targets = gate?.targets || [];
  // #55 — clickable telemetry filter: narrow the visible review feed to a single review outcome. Sourced
  // from the #47 disposition partition; lookup (#49) and filter are mutually exclusive (see below).
  const [feedFilter, setFeedFilter] = useState<Target["current_outcome"] | null>(null);
  const [attrFilters, setAttrFilters] = useState<AttrFilters>({ pillar: null, format: null });   // #16/#104 — pillar + content-format narrowing
  const [sortMode, setSortMode] = useState<SortMode>("default");   // #16/#96 — review-feed sort order
  const [searchQuery, setSearchQuery] = useState("");              // #16/#98 — review-feed text search
  // #49 — content-ID lookup consumer: resolve a typed slot_id / displayed code (any form) against the
  // current round+stage target set, then scroll to + ring the matching card. Never guesses.
  const [lookupQuery, setLookupQuery] = useState("");
  const [lookup, setLookup] = useState<
    { kind: "idle" } | { kind: "match"; slot_id: string; query: string }
    | { kind: "not_found"; query: string } | { kind: "ambiguous"; query: string; matches: string[] }
  >({ kind: "idle" });
  const clearLookup = () => { setLookupQuery(""); setLookup({ kind: "idle" }); };
  const runLookup = () => {
    const res = resolveContentId(targets, lookupQuery);
    if (res.ok) {
      setFeedFilter(null);   // a lookup always reveals its match — never leave it hidden behind a filter
      setAttrFilters({ pillar: null, format: null });   // keep the existing lookup-vs-filter mutual exclusion deterministic
      setLookup({ kind: "match", slot_id: res.slot_id, query: lookupQuery.trim() });
      if (typeof document !== "undefined") {
        document.querySelector(`[data-testid="card-${res.slot_id}"]`)
          ?.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    } else if (res.reason === "empty") {
      setLookup({ kind: "idle" });
    } else if (res.reason === "ambiguous") {
      setLookup({ kind: "ambiguous", query: lookupQuery.trim(), matches: res.matches });
    } else {
      setLookup({ kind: "not_found", query: lookupQuery.trim() });
    }
  };
  const highlightSlot = lookup.kind === "match" ? lookup.slot_id : null;
  // list/grid feeds surface still-actionable cards first; calendar stays positional (day/time board)
  const feedTargets = r.orderedTargets;
  // #55 — the visible feed after applying the outcome filter. The filter partitions gate.targets by the
  // SAME stagedOutcome that produces the disposition counts, so filtered-visible-count == the chip count.
  const feedOutcomeOf = (t: Target) => stagedOutcome(t, r.approver);
  const visibleFeed = feedFilter ? feedTargets.filter((t) => feedOutcomeOf(t) === feedFilter) : feedTargets;
  const pillarChoices = pillarOptions(feedTargets);
  const formatChoices = formatOptions(feedTargets);
  const attrFilterActive = !!attrFilters.pillar || !!attrFilters.format;
  // #16/#104 — frontend-only attribute filters. Outcome picks the candidate set first; pillar +
  // content-format narrow WITHIN that set using already-loaded Target fields only.
  const attrFilteredFeed = filterFeed(visibleFeed, attrFilters);
  // #16/#98 — text search narrows the already-outcome-filtered, already-attribute-filtered candidate set to cards whose already-loaded text
  // matches the query. Empty query is a no-op. It does NOT touch the #55 chip counts (those stay the
  // round-level disposition partition) or the #49 lookup (a distinct jump-to-one-ID control).
  const searchActive = normalizeQuery(searchQuery) !== "";
  const searchedFeed = searchFeed(attrFilteredFeed, searchQuery);
  // #16/#96 — sorting is the LAST step: it orders the already-filtered, already-searched visible feed.
  // Pipeline: orderedTargets → #55 outcome filter → #104 attribute filters → #98 search → #96 sort → render.
  // Filters/search pick WHICH cards; sort picks their ORDER; none changes the #55 counts. Lookup stays
  // orthogonal (highlight/scroll) by clearing active filters before jumping to a card.
  const sortedFeed = sortFeed(searchedFeed, sortMode, feedOutcomeOf);
  const applyFeedFilter = (outcome: Target["current_outcome"]) => {
    setFeedFilter((current) => (current === outcome ? null : outcome));   // toggle
    clearLookup();   // filter + lookup are mutually exclusive (a filtered view could hide the match)
  };
  const updateAttrFilter = (key: keyof AttrFilters, value: string) => {
    setAttrFilters((current) => ({ ...current, [key]: value || null }));
    clearLookup();   // same mutual-exclusion rule as the outcome chips
  };
  const feedFilters: { key: Target["current_outcome"]; label: string; count: number }[] = [
    { key: "pending", label: "Pending", count: r.disposition.stagedPending },
    { key: "approved", label: "Approved", count: r.disposition.stagedApproved },
    { key: "changes_requested", label: "Changes requested", count: r.disposition.stagedSentBack },
    { key: "rejected", label: "Dropped", count: r.disposition.stagedRejected },
  ];
  const codeLabel = primaryCodeLabel(stage.key);
  const pendingSet = new Set(r.pending.map((target) => target.slot_id));
  const actionBusy = r.busy || r.reviewerSyncing || !r.canDecideGate; // #175 — view-only when not assigned
  const totalDays = roundInfo?.period_len_days
    || Math.max(...targets.map((target) => target.day), ...r.roundSlots.map((s) => s.day), 0);
  // #271 — calendar CONTINUITY: the board is sourced from the run's COMPLETE planned slot set (so an
  // approved cell never disappears), with the active gate's targets overlaid for full interactivity.
  // A planning-only cell (not in the active gate) renders read-only with its format + lifecycle status.
  type CalCell = Target & { _lifecycle?: string; _planningOnly?: boolean };
  const calendarCells: CalCell[] = (() => {
    const byId = new Map<string, CalCell>();
    r.roundSlots.forEach((s) => {
      byId.set(s.slot_id, {
        slot_id: s.slot_id, day: s.day, time_uae: s.time_uae, pillar_code: s.pillar_code,
        pillar_short_code: s.pillar_short_code || "", seq_in_pillar: s.seq_in_pillar || 0,
        format: s.format, hcs_id: s.hcs_id, lens: s.lens, hook_type: s.hook_type,
        topic_angle: s.topic_angle, slot_status: s.status, current_outcome: "pending",
        _lifecycle: s.status, _planningOnly: true,
      } as CalCell);
    });
    targets.forEach((t) => byId.set(t.slot_id, { ...t, _lifecycle: t.slot_status, _planningOnly: false }));
    return Array.from(byId.values());
  })();
  const scheduleBoard = layout === "calendar" && totalDays > 0
    ? weekBoard(calendarCells, totalDays) : null;
  // #47 — the "Pending" chip shows STILL-PENDING visible cards (disposition.pending), not the
  // round-wide in-review population, so the chip reconciles with the actual pending cards on screen.
  const pendingCount = r.disposition.pending;
  const approvedCount = r.disposition.approved;
  const awaitingCount = r.disposition.awaiting;
  const droppedCount = r.disposition.dropped;
  const awaitingLaneCount = changes.length;
  // #24 item 1 — disposition summary completeness: a single at-a-glance progress anchor
  // (committed resolutions / total in this stage) so review progress is legible without
  // mentally summing the individual state chips. Sourced from the same `disposition` object.
  const totalCount = r.disposition.total;
  const resolvedCount = Math.max(0, totalCount - pendingCount);
  const stickyInset = wide ? "-mx-6 px-6" : "-mx-5 px-5 xl:-mx-6 xl:px-6";
  const myStageApproval = gate
    ? r.pendingApprovals.find((p) => p.gate_id === gate.gate_id)
      || r.pendingApprovals.find((p) => p.round_id === round && p.stage === stage.gate)
    : null;
  const awaitingPreview = changes.slice(0, 2);
  const stageSummary = stage.key === "schedule"
    ? "Schedule first; topics generate only after approval."
    : stage.key === "topic"
      ? "Approve topics before scripts."
      : stage.group === "Production"
        ? "Confirm this production stage."
        : "Review this stage.";
  const hasStageGuidance = stage.key === "schedule" || stage.key === "topic" || stage.group === "Production";
  // #280 — truthful scope label for the shared empty-state contract (no-run / loading / no-items).
  const viewScope = layout === "calendar" ? "Calendar" : layout === "grid" ? "Grid" : "Inbox";
  const scopeLabel = round ? `Run ${round} · ${viewScope}` : viewScope;

  return (
    <div className={`space-y-3 pt-3 pb-24 ${wide ? "px-6" : "mx-auto max-w-3xl px-5 xl:mx-0 xl:max-w-none xl:px-6"}`}>
      <div ref={stickyRef} className={`pointer-events-none sticky top-0 z-20 ${stickyInset} border-b bg-background/92 py-1.5 backdrop-blur supports-[backdrop-filter]:bg-background/80`}>
        {/* #261 — display chrome (metrics, funnel, run lifecycle) stays pointer-transparent so a
            control scrolled beneath the sticky band still receives ordinary clicks (hit-testing
            passes through); only the ACTUAL interactive leaves re-enable pointer events, so the
            header's own switchers/filters keep working. No sticky is disabled, no overflow masked. */}
        <div className="pointer-events-none space-y-1 [&_a]:pointer-events-auto [&_button]:pointer-events-auto [&_input]:pointer-events-auto [&_select]:pointer-events-auto [&_textarea]:pointer-events-auto [&_[role=group]]:pointer-events-auto">
          {/* #20 — one dense, count-first telemetry row. Run config + outcome counts + view controls in a
              single wrapping line; the old bordered Scope/Code-display/Card-detail boxes (duplicating the
              nav's stage, gate-assignments' rule, and the pending count) are folded in here. */}
          {roundInfo && (
            <div data-testid="round-status" className="flex flex-wrap items-center gap-1.5">
              <span title="Run length (days)" className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("neutral")}`}>
                <CalendarDays className="size-3.5" /> <span className="tabular-nums">{roundInfo.period_len_days}</span><span className="text-muted-foreground">d</span>
              </span>
              <span title="Cadence — posts per day" className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("neutral")}`}>
                <Clock3 className="size-3.5" /> <span className="tabular-nums">{roundInfo.posts_per_day}</span><span className="text-muted-foreground">/day</span>
              </span>
              {targets.length > 0 && (
                <span data-testid="metric-cards" title={`${targets.length} ${layout === "calendar" ? "scheduled slots" : "review cards"} in scope`}
                  className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("neutral")}`}>
                  <TargetIcon className="size-3.5" /> <span className="tabular-nums">{targets.length}</span> {layout === "calendar" ? "slots" : "cards"}
                </span>
              )}
              <span data-testid="disposition-progress" data-resolved={resolvedCount} data-total={totalCount}
                title="Committed resolutions in this stage (approved, sent for regeneration, or dropped) out of the total."
                className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("neutral")}`}>
                <ListChecks className="size-3.5" /> <span className="tabular-nums">{resolvedCount}<span className="text-muted-foreground">/{totalCount}</span></span> reviewed
              </span>
              <span title="Pending review" className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("active")}`}>
                <Activity className="size-3.5" /> <span data-testid="metric-pending" className="tabular-nums">{pendingCount}</span> pending
              </span>
              <span title="Approved" className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("success")}`}>
                <CheckCircle2 className="size-3.5" /> <span data-testid="metric-approved" className="tabular-nums">{approvedCount}</span> approved
              </span>
              <span title="Awaiting regeneration" className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("warning")}`}>
                <RefreshCcw className="size-3.5" /> <span data-testid="metric-regen" className="tabular-nums">{awaitingCount}</span> regen
              </span>
              <span title="Dropped (recoverable)" className={`inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-xs font-medium ${metricChipTone("destructive")}`}>
                <XCircle className="size-3.5" /> <span data-testid="metric-dropped" className="tabular-nums">{droppedCount}</span> dropped
              </span>
              {/* #219 — inspection controls stay available for the COMPLETED trail too: show when
                  active targets OR durable approved-and-moved-forward items exist, so a finished
                  stage (targets.length === 0, advancedTrail.length > 0) keeps density + ID-mode
                  inspection. The controls are effective on read-only trail rows below (no mutation). */}
              {(targets.length > 0 || r.advancedTrail.length > 0) && (
                <div className="ml-auto flex items-center gap-1.5">
                  <div className="flex items-center gap-0.5 rounded-lg border bg-card/60 p-0.5" data-testid="idmode-switcher" role="group" aria-label="Code display">
                    {ID_MODES.map((mode) => (
                      <button key={mode.key} data-testid={`idmode-${mode.key}`} aria-pressed={idMode === mode.key} title={`Code display: ${mode.label}`} onClick={() => setIdMode(mode.key)}
                        className={`rounded-md px-2 py-0.5 text-xs font-medium transition-colors ${
                          idMode === mode.key ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}>
                        {mode.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-0.5 rounded-lg border bg-card/60 p-0.5" data-testid="density-switcher" role="group" aria-label={layout === "calendar" ? "Board detail" : "Card detail"}>
                    {DENSITIES.map((d) => (
                      <button key={d.key} data-testid={`density-${d.key}`} aria-pressed={density === d.key} title={`Card detail: ${d.label}`} onClick={() => setDensity(d.key)}
                        className={`rounded-md px-2 py-0.5 text-xs font-medium transition-colors ${
                          density === d.key ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}>
                        {d.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          {/* #278 P1 — run-level format-mix revision on the planning (Schedule) surface: re-allocate the
              per-run framework counts across the FULL pinned eligibility set before Schedule approval.
              The server reconciles only uncommitted slots and fails closed once any slot is committed. */}
          {stage.key === "schedule" && r.roundSlots.length > 0 && (
            <div data-testid="run-mix-planning" className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>Planning:</span>
              <RunMixControl
                pinned={r.roundPinned}
                currentMix={r.roundMix}
                plannedTotal={r.roundSlots.length}
                committed={r.roundSlots.some((s) => s.status !== "RESERVED")}
                onRevise={r.reviseRunMix}
              />
            </div>
          )}
          {gate && !myStageApproval && (
            <div data-testid="gate-assignments" className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border/70 bg-card/35 px-2.5 py-1 text-xs text-muted-foreground">
              <Badge variant="secondary">{approvalRuleLabel(gate.rule_key)}</Badge>
              <span>Required:</span>
              {(gate.assignments || []).map((a) => (
                <Badge key={`${a.assignment_kind}:${a.assignment_key}`} variant="outline">
                  {approvalAssignmentLabel(a)}
                </Badge>
              ))}
            </div>
          )}
          {/* #175 — the active persona is not assigned to this open gate: state it plainly BEFORE any
              action is attempted (decision controls below are disabled). Client-safe wording, no raw
              engine text; the server would (and still does) reject regardless of this banner. */}
          {gate?.status === "open" && !r.canDecideGate && (
            <div
              data-testid="not-assigned-banner"
              role="status"
              className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/45 bg-warning/10 px-3 py-2 text-xs"
            >
              <ShieldAlert className="size-4 shrink-0 text-warning" />
              <span>
                <strong>View only — you&apos;re acting as {r.approvers.find((p) => p.principal_id === r.approver)?.display_name_en || r.approver}</strong>, who isn&apos;t assigned
                to decide at this stage.
                {r.gateRequirements.length > 0 && <> Deciding here requires {r.gateRequirements.join(" or ")}.</>}
                {" "}Switch to an assigned persona (Reviewer menu) or update the workflow assignments.
              </span>
            </div>
          )}
          {(myStageApproval || gate || targets.length > 0 || Boolean(stageState)) && (
            <div className="rounded-xl border border-border/70 bg-gradient-to-br from-card via-card/95 to-secondary/[0.08] shadow-sm shadow-primary/5">
              {/* #282 — a legacy (pre-migration) gate is surfaced truthfully: it resolves by the old
                  count rule and no authoritative per-token coverage is claimed for it. */}
              {gate?.legacy && (
                <div data-testid="legacy-gate-marker" className="flex flex-wrap items-center gap-1.5 border-b border-warning/40 bg-warning/10 px-3 py-1 text-[11px] text-foreground">
                  <ShieldAlert className="size-3.5 shrink-0 text-warning" />
                  <span><strong>Legacy approval</strong> — resolved by the pre-migration count rule; per-token coverage is not claimed for this gate.</span>
                </div>
              )}
              {myStageApproval && (
            <div data-testid="my-approval-context" className="flex flex-wrap items-center gap-1 border-b border-border/70 px-3 py-1 text-[11px]">
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/8 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-primary/90">
                <ShieldCheck className="size-3.5" /> Approval context
              </span>
              <Badge variant="secondary">{approvalRuleLabel(myStageApproval.rule_key)}</Badge>
              <Badge variant="outline">{myStageApproval.remaining_targets} remaining</Badge>
              <span className="text-muted-foreground">Act via</span>
              {myStageApproval.matched_assignments.map((a) => (
                <Badge key={`mine-${a.assignment_kind}:${a.assignment_key}`} variant="outline">
                  {approvalAssignmentLabel(a)}
                </Badge>
              ))}
              <span className="text-muted-foreground">Need</span>
              {myStageApproval.all_assignments.map((a) => (
                <Badge key={`all-${a.assignment_kind}:${a.assignment_key}`} variant="outline">
                  {approvalAssignmentLabel(a)}
                </Badge>
              ))}
            </div>
              )}

              <DispositionBar compact embedded />

              {awaitingLaneCount > 0 && (
                <div data-testid="awaiting-count-context" className="flex flex-wrap items-center gap-2 border-t border-border/70 px-3 py-1 text-[11px]">
                  <Badge variant="warning">⟳ {awaitingLaneCount} awaiting regeneration</Badge>
                  <span className="text-muted-foreground">Counted in the stage total; not yet in the active cards.</span>
                </div>
              )}

              {/* #134 — run-level funnel: read-only, explains stage-to-stage differences; no
                  drill-in, no filters, and never a source for the stage chips above. */}
              {funnel && funnel.total > 0 && (
                <div data-testid="run-funnel-strip" data-funnel-total={funnel.total}
                     className="flex flex-wrap items-center gap-1.5 border-t border-border/70 px-3 py-1 text-[11px] text-muted-foreground">
                  <span className="font-semibold uppercase tracking-[0.16em]">Run funnel</span>
                  <span>{funnel.total} planned</span>
                  {funnel.stages.filter((s) => s.entered > 0).map((s) => (
                    <span key={s.stage} data-testid={`funnel-${s.stage}`} data-entered={s.entered}
                          className="inline-flex items-center gap-1">
                      <span aria-hidden>→</span>
                      <span className="text-foreground/80">{stageLabel(s.stage)}</span>
                      <span>{s.entered}</span>
                      {(s.awaiting > 0 || s.dropped > 0) && (
                        <span className="text-muted-foreground/70">
                          ({[s.awaiting > 0 ? `⟳${s.awaiting}` : "", s.dropped > 0 ? `✕${s.dropped}` : ""].filter(Boolean).join(" ")})
                        </span>
                      )}
                    </span>
                  ))}
                  {/* #218 — partial progress is truthful but NOT run-completion: 0 < completed <
                      total shows just the count (no terminal "done", no post-completion loop). */}
                  {funnel.completed > 0 && funnel.completed !== funnel.total && (
                    <span data-testid="run-partial-complete">
                      → <span className="tabular-nums">{funnel.completed}</span> completed
                    </span>
                  )}
                  {/* the run is FULLY complete only when every planned slot reached the terminal
                      status (funnel truth). Only then is publication no longer the end: show the
                      distinct run-completion truth + the planned next loop. */}
                  {funnel.total > 0 && funnel.completed === funnel.total && (
                    <span data-testid="run-lifecycle-tail" className="inline-flex flex-wrap items-center gap-1.5">
                      <span aria-hidden>→</span>
                      {/* run truth stays distinct + truthful (count preserved exactly) */}
                      <span data-testid="run-complete" className="text-foreground/80">
                        Run complete <span className="tabular-nums">{funnel.completed}</span>
                      </span>
                      {/* #218 — the product lifecycle continues past publication. Analytics →
                          Learning → Optimize is the PLANNED next loop, not a connected capability
                          and not a workflow stage/gate. Non-interactive display text ONLY — never
                          links/buttons/controls; the → arrows are aria-hidden so the sequence reads
                          as labels, and one shared disclosure states the not-connected truth. */}
                      <span data-testid="lifecycle-continuation" role="group"
                            aria-label="Planned next loop, not connected: Analytics then Learning then Optimize"
                            className="inline-flex flex-wrap items-center gap-1 rounded-full border border-border/60 bg-card/50 px-2 py-0.5">
                        <span data-testid="lifecycle-analytics">Analytics</span>
                        <span aria-hidden>→</span>
                        <span data-testid="lifecycle-learning">Learning</span>
                        <span aria-hidden>→</span>
                        <span data-testid="lifecycle-optimize">Optimize</span>
                        <span data-testid="lifecycle-disclosure" className="italic opacity-70">· planned next loop, not connected</span>
                      </span>
                    </span>
                  )}
                </div>
              )}

              {targets.length > 0 && (
                <details className="border-t border-border/70 px-3 py-1">
                  <summary className="flex cursor-pointer list-none items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                    <CircleHelp className="size-3" /> Legend
                  </summary>
                  <div className="mt-2 grid gap-2 text-xs text-muted-foreground md:grid-cols-3">
                    <div>
                      <div className="font-medium text-foreground">Code display</div>
                      <div>Compact trims labels; expanded shows the full code; detailed adds context.</div>
                    </div>
                    <div>
                      <div className="font-medium text-foreground">Card detail</div>
                      <div>Chip scans first; compact is default; full shows the deeper payload.</div>
                    </div>
                    <div>
                      <div className="font-medium text-foreground">Exception lanes</div>
                      <div>Use the header chips for counts; use the lanes below for recovery work.</div>
                    </div>
                    {hasStageGuidance && (
                      <div className="md:col-span-3">
                        <div className="font-medium text-foreground">Current stage guidance</div>
                        <div>{stageSummary}</div>
                      </div>
                    )}
                  </div>
                </details>
              )}
            </div>
          )}
        </div>
      </div>

      {/* #49 — content-ID lookup consumer. Kept OUT of the sticky header (which is height-budgeted by the
          cards' scroll-mt) so it never overlaps/intercepts card interactions; resolves against the current
          round+stage target set and scrolls to + rings the match. */}
      {targets.length > 0 && (
        <div className="rounded-2xl border border-border/60 bg-background/70 px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <Search className="size-3" /> Find item
            </span>
            <input
              data-testid="content-id-lookup"
              value={lookupQuery}
              onChange={(event) => setLookupQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") runLookup();
                if (event.key === "Escape") clearLookup();
              }}
              placeholder="Find by content ID or internal ID"
              className="h-8 min-w-[15rem] flex-1 rounded-md border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-primary/40"
            />
            <Button data-testid="content-id-lookup-go" size="sm" variant="outline" disabled={!lookupQuery.trim()} onClick={runLookup}>Find</Button>
            {lookup.kind !== "idle" && (
              <Button data-testid="content-id-lookup-clear" size="sm" variant="ghost" onClick={clearLookup}>Clear</Button>
            )}
          </div>
          {lookup.kind === "match" && (
            <div data-testid="lookup-match" className="mt-1.5 text-xs text-success">
              Jumped to “{lookup.query}” → <span className="font-mono">{lookup.slot_id}</span>
            </div>
          )}
          {lookup.kind === "not_found" && (
            <div data-testid="lookup-not-found" className="mt-1.5 text-xs text-destructive">
              No item in this stage matches “{lookup.query}”.
            </div>
          )}
          {lookup.kind === "ambiguous" && (
            <div data-testid="lookup-ambiguous" className="mt-1.5 text-xs text-warning">
              “{lookup.query}” is ambiguous — matches {lookup.matches.length}: {lookup.matches.join(", ")}. Refine the ID.
            </div>
          )}
        </div>
      )}

      {/* #55 — clickable review-outcome filters. Non-sticky (same reason as the #49 lookup). Each chip
          filters the visible feed by the item's review outcome; the chip count is the #47 disposition
          partition, so filtered-visible-count == chip count by construction. */}
      {layout !== "calendar" && targets.length > 0 && (
        <div data-testid="feed-filter-bar" className="flex flex-wrap items-center gap-2 rounded-2xl border border-border/60 bg-background/70 px-3 py-2">
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
            <ListFilter className="size-3" /> Filter
          </span>
          <button
            data-testid="feed-filter-all"
            aria-pressed={!feedFilter}
            onClick={() => setFeedFilter(null)}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${!feedFilter ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}
          >
            All <span className="tabular-nums">{targets.length}</span>
          </button>
          {feedFilters.filter((f) => f.count > 0 || feedFilter === f.key).map((f) => (
            <button
              key={f.key}
              data-testid={`feed-filter-${f.key}`}
              aria-pressed={feedFilter === f.key}
              onClick={() => applyFeedFilter(f.key)}
              className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${feedFilter === f.key ? "bg-primary/15 text-foreground ring-1 ring-primary/40" : "text-muted-foreground hover:bg-secondary/50"}`}
            >
              {f.label} <span data-testid={`feed-filter-count-${f.key}`} className="tabular-nums">{f.count}</span>
            </button>
          ))}
          {feedFilter && (
            <Button data-testid="feed-filter-clear" size="sm" variant="ghost" onClick={() => setFeedFilter(null)}>Clear filter</Button>
          )}
          {/* #16/#98 — text search. Narrows the outcome-filtered feed by already-loaded card text/codes.
              Distinct from the #49 "Find item" lookup (which jumps to ONE exact ID); this filters to ALL
              matches. Lives in this non-sticky bar (no #20 sticky-header/checkbox risk). */}
          <div className="flex items-center gap-1.5" data-testid="feed-search">
            <label htmlFor="feed-search-input" className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <Search className="size-3" /> Search
            </label>
            <input
              id="feed-search-input"
              data-testid="feed-search-input"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Escape") setSearchQuery(""); }}
              placeholder="Filter cards by text or code"
              className="h-8 min-w-[12rem] rounded-md border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-primary/40"
            />
            {searchActive && (
              <Button data-testid="feed-search-clear" size="sm" variant="ghost" onClick={() => setSearchQuery("")}>Clear</Button>
            )}
          </div>
          {/* #16/#104 — compact single-select attribute filters. Purely presentation-side: each select
              reads existing pillar/format fields already on the loaded Target payload and can be reset
              to "all" without touching the backend or the #55 chip counts. */}
          <div className="flex items-center gap-1.5" data-testid="feed-attr-pillar">
            <label htmlFor="feed-attr-pillar-select" className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <ListFilter className="size-3" /> Pillar
            </label>
            <select
              id="feed-attr-pillar-select"
              data-testid="feed-attr-pillar-select"
              value={attrFilters.pillar || ""}
              onChange={(event) => updateAttrFilter("pillar", event.target.value)}
              className="h-8 min-w-[10rem] rounded-md border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-primary/40"
            >
              <option value="">All pillars</option>
              {pillarChoices.map((option) => (
                <option key={option.code} value={option.code}>{option.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-1.5" data-testid="feed-attr-format">
            <label htmlFor="feed-attr-format-select" className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <ListFilter className="size-3" /> Format
            </label>
            <select
              id="feed-attr-format-select"
              data-testid="feed-attr-format-select"
              value={attrFilters.format || ""}
              onChange={(event) => updateAttrFilter("format", event.target.value)}
              className="h-8 min-w-[10rem] rounded-md border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-primary/40"
            >
              <option value="">All formats</option>
              {formatChoices.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </div>
          {attrFilterActive && (
            <Button data-testid="feed-attr-clear" size="sm" variant="ghost" onClick={() => setAttrFilters({ pillar: null, format: null })}>Clear attrs</Button>
          )}
          {/* #16/#96 — sort control. Shares this non-sticky bar with the #55 filter (kept out of the
              height-budgeted sticky header, so no #20 checkbox-interception risk). Reorders the visible
              feed only; the filter above still decides WHICH cards are visible. */}
          <div className="ml-auto flex items-center gap-1.5" data-testid="feed-sort">
            <label htmlFor="feed-sort-select" className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <ArrowUpDown className="size-3" /> Sort
            </label>
            <select
              id="feed-sort-select"
              data-testid="feed-sort-select"
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value as SortMode)}
              className="h-8 rounded-md border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-primary/40"
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>{option.label}</option>
              ))}
            </select>
          </div>
        </div>
      )}
      {layout !== "calendar" && feedFilter && visibleFeed.length === 0 && (
        <div data-testid="feed-filter-empty" className="rounded-2xl border border-dashed border-border/60 px-4 py-6 text-center text-sm text-muted-foreground">
          No “{feedFilters.find((f) => f.key === feedFilter)?.label}” items in this review.{" "}
          <button className="underline hover:text-foreground" onClick={() => setFeedFilter(null)}>Clear filter</button>
        </div>
      )}
      {layout !== "calendar" && attrFilterActive && visibleFeed.length > 0 && attrFilteredFeed.length === 0 && (
        <div data-testid="feed-attr-empty" className="rounded-2xl border border-dashed border-border/60 px-4 py-6 text-center text-sm text-muted-foreground">
          No cards match the selected pillar / format filters.{" "}
          <button className="underline hover:text-foreground" onClick={() => setAttrFilters({ pillar: null, format: null })}>Clear attribute filters</button>
        </div>
      )}
      {/* #16/#98 — search no-match: distinct from the filter-empty state above. Only shows when the
          outcome+attribute-filtered candidate set had cards but the search narrowed them all out. */}
      {layout !== "calendar" && searchActive && attrFilteredFeed.length > 0 && searchedFeed.length === 0 && (
        <div data-testid="feed-search-empty" className="rounded-2xl border border-dashed border-border/60 px-4 py-6 text-center text-sm text-muted-foreground">
          No cards match “{searchQuery.trim()}”.{" "}
          <button className="underline hover:text-foreground" onClick={() => setSearchQuery("")}>Clear search</button>
        </div>
      )}

      {toast && (
        <div data-testid="toast" data-kind={toast.kind}
          className={`rounded-md border px-3 py-2 text-sm ${toast.kind === "ok" ? "border-success/40 bg-success/10 text-foreground" : "border-destructive/40 bg-destructive/10 text-foreground"}`}>
          {toast.msg}
        </div>
      )}

      {/* awaiting regeneration — items sent back, parked until rework produces v2 */}
      {r.supportsRework && changes.length > 0 && (
        <div data-testid="awaiting-panel" className="rounded-2xl border border-warning/35 bg-gradient-to-r from-warning/[0.09] to-background px-3 py-2 shadow-sm shadow-warning/5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="warning">⟳ {changes.length} awaiting regeneration</Badge>
            <span className="text-xs text-muted-foreground">Parked outside the review queue until regenerated.</span>
            <div className="flex flex-1 flex-wrap gap-2">
              {awaitingPreview.map((c) => (
                <div key={c.slot_id} data-testid={`awaiting-${c.slot_id}`} className="flex items-center gap-1.5 rounded-full border border-warning/20 bg-background/80 px-2 py-1 text-xs text-muted-foreground">
                  <span className="font-mono">{c.slot_id}</span>
                  {c.comment && <span dir="auto">“{c.comment}”</span>}
                  <button
                    type="button"
                    data-testid={`edit-note-${c.slot_id}`}
                    disabled={actionBusy || !!r.genJob}
                    onClick={() => r.setNoteDraft((current) => ({ ...current, [c.slot_id]: c.comment || "" }))}
                    className="ml-0.5 inline-flex items-center rounded-full p-0.5 text-warning/80 hover:text-warning disabled:opacity-40"
                    title="Edit the change note (no undo needed)"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                </div>
              ))}
              {changes.length > awaitingPreview.length && (
                <Badge variant="outline">+{changes.length - awaitingPreview.length} more</Badge>
              )}
            </div>
            {r.genJob ? (
              // #24 item 4 — regenerate runs while the awaiting-panel is shown (StageAction, which hosts
              // the job-progress bar, is unmounted here), so the existing genJob telemetry was invisible.
              // Surface it inline next to the action: immediate, durable "working X/Y" acknowledgment.
              <div data-testid="regen-progress" className="ml-auto flex min-w-[12rem] flex-col gap-1 text-xs text-muted-foreground">
                <span>⟳ {r.genJob.label}… {r.genJob.done}/{r.genJob.total}</span>
                <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
                  <div className="h-full bg-warning transition-all" style={{ width: `${r.genJob.total ? Math.round((r.genJob.done / r.genJob.total) * 100) : 0}%` }} />
                </div>
              </div>
            ) : (
              <Button data-testid="regenerate" size="sm" className="ml-auto" disabled={actionBusy} onClick={r.regenerate}>Regenerate (apply my comments)</Button>
            )}
          </div>
          {/* refine an awaiting item's change note in place — no Undo round-trip (issue #3) */}
          {awaitingPreview.filter((c) => c.slot_id in r.noteDraft).map((c) => (
            <div key={`edit-${c.slot_id}`} className="mt-2 space-y-1.5 rounded-xl border border-warning/25 bg-background/60 p-2">
              <span className="text-[11px] font-medium text-muted-foreground">
                Refine the change note for <span className="font-mono">{c.slot_id}</span> — applied on the next regenerate.
              </span>
              <Textarea
                data-testid={`edit-note-text-${c.slot_id}`}
                dir="auto"
                value={r.noteDraft[c.slot_id]}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => r.setNoteDraft((current) => ({ ...current, [c.slot_id]: event.target.value }))}
                className="min-h-[64px] text-xs"
              />
              <div className="flex flex-wrap gap-2">
                <Button data-testid={`save-note-${c.slot_id}`} size="sm" variant="warning" disabled={actionBusy} onClick={() => r.editChangeNote(c.slot_id, r.noteDraft[c.slot_id])}>Save note</Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => r.setNoteDraft((current) => { const next = { ...current }; delete next[c.slot_id]; return next; })}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* #179 — durable "approved & moved forward" trail: what THIS stage committed and where each
          item is now. Server-derived (resolved gates + live slot state), so it survives reloads and
          keeps a completed stage from reading as empty/lost. Read-only by design. */}
      {r.advancedTrail.length > 0 && (
        <div data-testid="advanced-trail" className="rounded-2xl border border-success/25 bg-gradient-to-r from-success/[0.07] to-background px-3 py-2 shadow-sm shadow-success/5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="success">{r.advancedTrail.length} approved &amp; moved forward</Badge>
            <span className="text-xs text-muted-foreground">Committed at this stage — shown here durably so nothing reads as lost.</span>
            <div className="flex w-full flex-col gap-1.5">
              {r.advancedTrail.map((a) => {
                // #219 — the content-ID uses the SAME formatter as active cards, but ONLY when the
                // canonical fields are present; otherwise fall back to the raw slot_id (canonical,
                // never a fabricated/degraded code). Detailed mode adds the same descriptor the
                // active review cards show. Read-only: no mutation control is ever rendered here.
                const hasCanonicalId = a.pillar_short_code != null && a.seq_in_pillar != null;
                const idLabel = hasCanonicalId
                  ? contentIdLabel({ day: a.day, slot_id: a.slot_id,
                                     pillar_short_code: a.pillar_short_code as string,
                                     seq_in_pillar: a.seq_in_pillar as number }, idMode)
                  : a.slot_id;
                const descriptor = a.pillar_name_en && a.hcs_name_en
                  ? `${a.pillar_name_en} · ${a.hcs_name_en}` : null;
                const locationNode = (
                  <span data-testid={`advanced-location-${a.slot_id}`} className="ml-auto inline-flex items-center gap-1 text-muted-foreground">
                    <CheckCircle2 className="size-3.5 text-success" />
                    {a.location_kind === "in_review" && a.location_stage_label && <>Now in {a.location_stage_label} review</>}
                    {a.location_kind === "advanced" && a.location_stage_label && <>Approved at {a.location_stage_label} — awaiting the next step</>}
                    {a.location_kind === "changes" && <>Sent back for changes</>}
                    {a.location_kind === "dropped" && <>Dropped (recoverable)</>}
                    {(a.location_kind === "other" || !a.location_stage_label) && a.location_kind !== "changes" && a.location_kind !== "dropped" && <>{a.status}</>}
                  </span>
                );
                return (
                <div key={a.slot_id} data-testid={`advanced-item-${a.slot_id}`}
                  data-density={density} data-idmode={idMode}
                  className="flex flex-wrap items-center gap-2 rounded-xl border border-success/20 bg-background/70 px-2.5 py-1.5 text-xs">
                  <span data-testid={`advanced-code-${a.slot_id}`} className="font-mono">{idLabel}</span>
                  {idMode === "detailed" && descriptor && (
                    <span data-testid={`advanced-descriptor-${a.slot_id}`} className="text-[11px] text-muted-foreground">{descriptor}</span>
                  )}
                  {/* density: chip = code + location only; compact adds format + hook; full adds topic + attribution */}
                  {density !== "chip" && a.format && <Badge variant="secondary">{a.format}</Badge>}
                  {density !== "chip" && a.hook_text && <span dir="auto" className="min-w-0 max-w-[24rem] truncate text-foreground">«{a.hook_text}»</span>}
                  {locationNode}
                  {density === "full" && (
                    <div data-testid={`advanced-full-${a.slot_id}`} className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 border-t border-success/15 pt-1 text-[11px] text-muted-foreground">
                      {a.topic_text && <span dir="auto" className="min-w-0 max-w-full truncate">Topic: {a.topic_text}</span>}
                      <span>Approved by <span className="font-medium text-foreground/80">{a.approved_by}</span></span>
                      <span>{new Date(a.approved_at).toLocaleString()}</span>
                      <span className="font-mono opacity-70">{a.slot_id}</span>
                    </div>
                  )}
                  {/* #237 Slice A — read-only inspection parity: every completed-trail row stays
                      openable to the same content definition the active card showed, at every
                      density. Lazy fetch on expansion; strictly non-mutating. */}
                  <TrailInspect slotId={a.slot_id} />
                  {/* #250 — Production/Edit stages: truthful read-only SDAM readiness for items
                      already committed here (persisted evidence only; never a workflow control).
                      #259 P1 — a normal single-item Edit approval closes/advances the gate and moves
                      the item into THIS durable trail, so the governed S2 register affordance must
                      remain reachable here for an authorized session (server re-checks the S1 pin +
                      trusted principal as the real authority; canDecideGate is true once the gate
                      has closed). */}
                  {(r.stage.key === "production" || r.stage.key === "edit") && (
                    <SdamReadiness slotId={a.slot_id} canRegister={r.stage.key === "edit" && r.canDecideGate} />
                  )}
                  {/* #200 (pub.v1) — distribution only: record/see where this approved item was
                      actually published. Manual recording is governed server-side. Unchanged. */}
                  {r.stage.key === "distribution" && <PublicationRecord slotId={a.slot_id} />}
                </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* dropped — reversible; removed from the batch but kept, restorable anytime */}
      {dropped.length > 0 && (
        <div data-testid="dropped-panel" className="rounded-2xl border border-destructive/25 bg-gradient-to-r from-destructive/[0.07] to-background px-3 py-2 shadow-sm shadow-destructive/5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="destructive">{dropped.length} dropped</Badge>
            <span className="text-xs text-muted-foreground">Recoverable lane. Removed from this batch, not deleted.</span>
            <div className="flex flex-1 flex-wrap gap-2">
              {dropped.map((d) => {
                const open = expandedDropped.has(d.slot_id);
                return (
                <div key={d.slot_id} data-testid={`dropped-${d.slot_id}`} className="flex flex-col gap-1 rounded-2xl border border-destructive/20 bg-background/70 px-2 py-1 text-xs text-muted-foreground">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono">{d.slot_id}</span>
                    <Badge variant="secondary">{d.pillar_code}</Badge>
                    {d.hook_text && <span dir="auto" className="max-w-[16rem] truncate">«{d.hook_text}»</span>}
                    <button
                      data-testid={`dropped-detail-toggle-${d.slot_id}`}
                      className="inline-flex items-center gap-0.5 rounded-md px-1 py-0.5 hover:text-foreground"
                      aria-expanded={open}
                      onClick={() => toggleDroppedDetail(d.slot_id)}
                    >
                      {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />} Details
                    </button>
                    <Button data-testid={`restore-${d.slot_id}`} size="sm" variant="outline" disabled={actionBusy} onClick={() => r.restore(d.slot_id)}>Restore</Button>
                  </div>
                  {open && (
                    <div data-testid={`dropped-detail-${d.slot_id}`} className="rounded-lg border border-border/60 bg-muted/25 px-2 py-1.5 text-[11px] leading-relaxed">
                      <div><span className="font-semibold text-foreground/80">Why dropped:</span> {d.reason ? <span dir="auto">{d.reason}</span> : <span className="italic opacity-70">no reason recorded</span>}</div>
                      {d.hook_text && <div className="mt-0.5"><span className="font-semibold text-foreground/80">Hook:</span> <span dir="auto">{d.hook_text}</span></div>}
                      <div className="mt-0.5"><span className="font-semibold text-foreground/80">Status:</span> <span className="font-mono">{d.status}</span></div>
                    </div>
                  )}
                </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* just approved — short-lived confirmation that an immediate approval committed (#24 item 2);
          the card leaves the feed, so this lane reassures "it saved" and keeps Restore one click away */}
      {justApproved.length > 0 && (
        <div data-testid="justapproved-panel" className="rounded-2xl border border-success/30 bg-gradient-to-r from-success/[0.08] to-background px-3 py-2 shadow-sm shadow-success/5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="success">{justApproved.length} just approved</Badge>
            <span className="text-xs text-muted-foreground">Saved and advanced. Undo with Restore while shown.</span>
            <div className="flex flex-1 flex-wrap gap-2">
              {justApproved.map((slotId) => (
                <div key={slotId} data-testid={`justapproved-${slotId}`} className="flex items-center gap-1.5 rounded-full border border-success/25 bg-background/70 px-2 py-1 text-xs text-muted-foreground">
                  <CheckCircle2 className="size-3.5 text-success" />
                  <span className="font-mono">{slotId}</span>
                  <Button data-testid={`restore-approved-${slotId}`} size="sm" variant="outline" disabled={actionBusy} onClick={() => r.restore(slotId)}>Restore</Button>
                  <button data-testid={`dismiss-approved-${slotId}`} className="text-muted-foreground/70 hover:text-foreground" aria-label="Dismiss" onClick={() => r.dismissJustApproved(slotId)}><X className="size-3.5" /></button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* the review feed — arranged by layout */}
      {layout === "grid" && targets.length > 0 && (
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(28rem,1fr))]">
          {sortedFeed.map((t) => <ReviewItem key={t.slot_id} t={t} density={density} idMode={idMode} layout="grid" highlight={t.slot_id === highlightSlot} />)}
        </div>
      )}

      {layout === "calendar" && targets.length > 0 && (
        <div>
          <p className="mb-3 text-xs text-muted-foreground">Schedule board aligned to the client reference: week-grouped, one row per day, with each slot showing its code and format.</p>
          <div className="space-y-4">
            {scheduleBoard?.weeks.map((week) => (
              <section key={week.week} className="overflow-hidden rounded-xl border bg-card/60">
                <div className="border-b bg-secondary/40 px-4 py-2 text-sm font-medium text-foreground">Week {week.week}</div>
                <div className="overflow-x-auto">
                  <table className="min-w-full border-collapse text-sm">
                    <thead>
                      <tr className="bg-secondary/20 text-left text-xs uppercase tracking-[0.18em] text-muted-foreground">
                        <th className="w-20 border-b px-3 py-2 font-medium">Day</th>
                        {scheduleBoard.times.map((time) => (
                          <th key={time} className="min-w-[220px] border-b px-3 py-2 font-medium">
                            {slotWindowLabel(time)} - {time}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {week.days.map((row) => (
                        <tr key={row.day} className="align-top">
                          <td className="border-b px-3 py-3 text-sm font-semibold text-foreground">Day {row.day}</td>
                          {row.slots.map((slot, index) => (
                            <td key={`${row.day}:${scheduleBoard.times[index]}`} className="border-b px-3 py-3">
                              {slot ? (
                                <div className={`rounded-lg border border-border/70 bg-background/70 p-3 ${calendarCellTone(density)}`}>
                                  <div className="space-y-1.5">
                                    <div className="flex items-center gap-2">
                                      {pendingSet.has(slot.slot_id) && (
                                        <input
                                          type="checkbox"
                                          checked={r.selectedSlotIds.has(slot.slot_id)}
                                          data-testid={`select-${slot.slot_id}`}
                                          aria-label={`Select ${codeLabel} ${contentIdLabel(slot, idMode)}`}
                                          className="size-4 shrink-0 accent-primary"
                                          onChange={() => r.toggleSelected(slot.slot_id)}
                                        />
                                      )}
                                      <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-primary/90">
                                        {codeLabel}
                                      </div>
                                    </div>
                                    <div>
                                      <Badge className="border border-primary/30 bg-primary/10 px-2.5 py-1 font-mono text-[12px] font-semibold tracking-[0.14em] text-foreground hover:bg-primary/10">
                                        {contentIdLabel(slot, idMode)}
                                      </Badge>
                                    </div>
                                  </div>
                                  <Badge variant="outline" className="text-[10px]" data-testid={`cal-format-${slot.slot_id}`}>{slot.format}</Badge>
                                  {density !== "chip" && (slot.pillar_name_en || slot.hcs_name_en) && (
                                    <div className="text-xs text-muted-foreground">{slot.pillar_name_en} · {slot.hcs_name_en}</div>
                                  )}
                                  {density === "full" && stage.key === "schedule" && (slot.hcs_name_ar || slot.hcs_name_en) && (
                                    <Bilingual
                                      ar={slot.hcs_name_ar}
                                      en={slot.hcs_name_en}
                                      primary="ar"
                                      title
                                      className="line-clamp-3 text-sm text-foreground"
                                    />
                                  )}
                                  {density === "full" && stage.key !== "schedule" && (
                                    <div dir="auto" className="line-clamp-3 text-sm text-foreground">«{slot.hook_text || "Pending title generation"}»</div>
                                  )}
                                  <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                                    {slot._planningOnly ? (
                                      // #271 — continuity cell: show the slot's lifecycle location, not a review outcome
                                      <Badge variant="outline" data-testid={`cal-lifecycle-${slot.slot_id}`}>{slot._lifecycle}</Badge>
                                    ) : (
                                      <>
                                        <Badge variant="outline">{outcomeLabel(slot.current_outcome)}</Badge>
                                        {slot.current_outcome === "pending" && (
                                          <Badge variant="outline">
                                            {slot.remaining_approvals} more approval{slot.remaining_approvals === 1 ? "" : "s"} required
                                          </Badge>
                                        )}
                                      </>
                                    )}
                                    {stage.key === "schedule" && (
                                      // available across the schedule calendar (incl. after approval, the
                                      // point of a governed revision); the SERVER enforces reviewer
                                      // authority (unauthorized proposals fail closed).
                                      <ScheduleRevisionControl slot={slot} eligibleFormats={r.roundPinned.map((f) => f.name)} maxDay={roundInfo?.period_len_days} onRevise={r.reviseSchedule} />
                                    )}
                                  </div>
                                  {r.supportsRework && slot.slot_id in r.changing && (
                                    <div className="space-y-2 rounded-md border bg-secondary/30 p-2">
                                      <Textarea
                                        data-testid={`change-text-${slot.slot_id}`}
                                        dir="auto"
                                        placeholder="What should change? (used in regeneration)"
                                        value={r.changing[slot.slot_id]}
                                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => r.setChanging((current) => ({ ...current, [slot.slot_id]: event.target.value }))}
                                        className="min-h-[88px] text-xs"
                                      />
                                      <div className="flex flex-wrap gap-2">
                                        <Button
                                          data-testid={`submit-change-${slot.slot_id}`}
                                          size="sm"
                                          variant="warning"
                                          disabled={actionBusy}
                                          onClick={() => r.submitChange(slot.slot_id)}
                                        >
                                          Send back for changes
                                        </Button>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          onClick={() => r.setChanging((current) => {
                                            const next = { ...current };
                                            delete next[slot.slot_id];
                                            return next;
                                          })}
                                        >
                                          Cancel
                                        </Button>
                                      </div>
                                    </div>
                                  )}
                                  {/* interactive decisions belong only to ACTIVE-gate cells; a
                                      planning-only continuity cell (#271) carries no decisions and is
                                      read-only, so it never renders approve/request/undo controls. */}
                                  {!slot._planningOnly && (() => {
                                    const myDecision = (slot.decisions || []).filter((decision) => decision.approver_id === r.approver).slice(-1)[0];
                                    const canAct = slot.current_outcome === "pending";
                                    if (canAct && !(slot.slot_id in r.changing)) {
                                      return (
                                        <div className="flex flex-wrap gap-2 border-t pt-2">
                                          <Button data-testid={`approve-${slot.slot_id}`} size="sm" variant="success" disabled={actionBusy} onClick={() => r.decide("approve", [slot.slot_id])}>
                                            <Check /> Approve
                                          </Button>
                                          {r.supportsRework && (
                                            <Button data-testid={`request-${slot.slot_id}`} size="sm" variant="warning" disabled={actionBusy} onClick={() => r.setChanging((current) => ({ ...current, [slot.slot_id]: "" }))}>
                                              <Pencil /> Request change
                                            </Button>
                                          )}
                                          <Button
                                            data-testid={`reject-${slot.slot_id}`}
                                            size="sm"
                                            variant="destructive"
                                            disabled={actionBusy}
                                            onClick={() => r.decide("reject", [slot.slot_id])}
                                          >
                                            <X /> Drop
                                          </Button>
                                        </div>
                                      );
                                    }
                                    if (myDecision) {
                                      return (
                                        <div className="flex flex-wrap items-center gap-2 border-t pt-2 text-xs text-muted-foreground">
                                          <span>
                                            Your decision: <span className="font-medium text-foreground">{r.g("decision", myDecision.decision)}</span>
                                            {slot.current_outcome === "pending" ? " — waiting for the remaining approver(s)" : ""}
                                          </span>
                                          <Button
                                            data-testid={`undo-${slot.slot_id}`}
                                            size="sm"
                                            variant="ghost"
                                            disabled={actionBusy}
                                            onClick={() => r.undecide(slot.slot_id)}
                                          >
                                            <Undo2 /> Undo
                                          </Button>
                                        </div>
                                      );
                                    }
                                    if (slot.current_outcome !== "pending") {
                                      return (
                                        <div className="border-t pt-2 text-xs text-muted-foreground">
                                          Resolved: <span className="font-medium text-foreground">{outcomeLabel(slot.current_outcome)}</span>
                                        </div>
                                      );
                                    }
                                    return null;
                                  })()}
                                </div>
                              ) : (
                                <div className="text-xs text-muted-foreground">-</div>
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        </div>
      )}

      {layout === "list" && (
        <div className="space-y-3">
          {sortedFeed.map((t) => <ReviewItem key={t.slot_id} t={t} density={density} idMode={idMode} layout="list" highlight={t.slot_id === highlightSlot} />)}
        </div>
      )}

      {/* #280 — the shared empty-state contract. Additive over the original two states: the no-run /
          loading case is new (these areas previously rendered blank with no run selected), and the bare
          "Nothing in this review." line is replaced by the shared no-items state. The StageAction path
          is preserved unchanged for every layout — it is NOT an empty state but the "there is a run,
          this stage needs an action (generate / start review / commit / open review)" surface. */}
      <div className={wide ? "" : "space-y-3"}>
        {!round && (
          <EmptyState
            variant={r.roundsError ? "error" : r.roundsLoading ? "loading" : "no-run"}
            scope={viewScope}
            action={r.roundsError
              ? <Button size="sm" variant="outline" data-testid="rounds-retry" onClick={() => r.reloadRounds()}>Try again</Button>
              : undefined}
          />
        )}
        {round && gate && !targets.length && (
          <EmptyState
            variant="no-items"
            scope={scopeLabel}
            description="This review has no items right now. Nothing has been generated, approved, or published."
          />
        )}
        {round && !gate && (!r.supportsRework || changes.length === 0) && <StageAction />}
      </div>
    </div>
  );
}
