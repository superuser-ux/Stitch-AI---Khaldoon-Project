"use client";

import { useEffect, useState } from "react";
import {
  MessagesSquare, X, PanelLeftClose, LayoutDashboard, Workflow, Inbox, LayoutGrid, CalendarDays,
  Lightbulb, FileText, BadgeCheck, Clapperboard, Scissors, Share2, Plus, TimerReset, TriangleAlert, Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useReview, STAGES, STAGE_GROUPS, APPROVERS, roundActiveCount, type View } from "@/lib/review-context";
import { coerceViewForStage } from "@/lib/views";
import { AssistantPanel } from "@/components/assistant/assistant-panel";
import { NewRunDialog } from "./new-run-dialog";
import { useClientTrialMode, useRuntimeInfo, resetLocalViewState } from "@/lib/client-trial";
import { PersonaEntry } from "./persona-entry";
import { IamEntry } from "./iam-entry";
import { ThemeSwitcher } from "./theme-switcher";
import { OverviewLens } from "./overview-lens";
import { WorkflowLens } from "./workflow-lens";
import { ReviewSurface } from "./review-surface";

// The lunaris shell. Design principle: no navigation surface permanently owns the working estate —
// the stage rail collapses full → icons → hidden, the Agent panel opens/closes, both remembered
// per-user and reachable by keyboard (⌘/Ctrl+B rail, ⌘/Ctrl+J agent). Default is a roomy canvas
// (icon rail, agent closed). One data model renders through five lenses.
const LENSES: { key: View; label: string; icon: typeof Inbox }[] = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "workflow", label: "Workflow", icon: Workflow },
  { key: "inbox", label: "Inbox", icon: Inbox },
  { key: "grid", label: "Grid", icon: LayoutGrid },
  { key: "calendar", label: "Calendar", icon: CalendarDays },
];
const STAGE_ICON: Record<string, typeof Inbox> = {
  schedule: CalendarDays, topic: Lightbulb, script: FileText, final: BadgeCheck, production: Clapperboard, edit: Scissors, distribution: Share2,
};
type Nav = "full" | "icons" | "hidden";
const NEXT_NAV: Record<Nav, Nav> = { full: "icons", icons: "hidden", hidden: "full" };

function fallbackRoundLabel(roundId: string, days: number, postsPerDay: number) {
  return `${days}-day run ${roundId} (${postsPerDay}/day)`;
}

function visibleRoundLabel(roundId: string, label: string | null, days: number, postsPerDay: number) {
  if (!label) return null;
  return label === fallbackRoundLabel(roundId, days, postsPerDay) ? null : label;
}

function humanRoundPhase(phase: string) {
  if (phase === "titles-pending") return "Ready for topic titles";
  if (phase === "in-review") return "In review";
  if (phase === "awaiting-regeneration") return "Awaiting regeneration";
  return phase
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function phaseTone(phase: string) {
  if (phase === "approved" || phase === "scheduled") return "border-success/25 bg-success/10 text-success";
  if (phase === "in-review" || phase === "awaiting-regeneration") return "border-warning/25 bg-warning/10 text-warning";
  return "border-border/70 bg-background/75 text-foreground";
}

export function AppShell() {
  const r = useReview();
  const clientTrial = useClientTrialMode();
  const runtime = useRuntimeInfo();   // #180 — server-declared surface + build for the badge
  const [nav, setNav] = useState<Nav>("icons");        // stage-rail chrome state (default: roomy)
  const [assistant, setAssistant] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  // #15 — a plain stage switch (nav rail) keeps the current view when it is valid for the destination
  // stage, else falls back to inbox; a lens drill-down passes an explicit view (inbox) to open the
  // review surface. coerceViewForStage guarantees content review stages never land on a non-card view.
  const gotoStage = (key: string, roundId?: string | null, opts?: { view?: View }) => {
    if (roundId && roundId !== r.round) r.setRound(roundId);
    r.setStageKey(key);
    r.setView(coerceViewForStage(opts?.view ?? r.view, key));
    if (isMobile) setNav("hidden");
  };
  const pendingApprovalCount = r.pendingApprovals.reduce((sum, x) => sum + x.remaining_targets, 0);
  const reviewerLabel = (id: string) => r.approvers.find((p) => p.principal_id === id)?.display_name_en || id;
  const selectedRound = r.rounds.find((item) => item.round_id === r.round) || null;
  const selectedRoundLabel = selectedRound
    ? visibleRoundLabel(
      selectedRound.round_id,
      selectedRound.label,
      selectedRound.period_len_days,
      selectedRound.posts_per_day,
    )
    : null;

  // restore per-user chrome prefs (client-only to avoid hydration mismatch)
  useEffect(() => {
    const n = localStorage.getItem("tanaghom-nav") as Nav | null;
    if (n === "full" || n === "icons" || n === "hidden") setNav(n);
    setAssistant(localStorage.getItem("tanaghom-agent") === "1");
  }, []);
  useEffect(() => { localStorage.setItem("tanaghom-nav", nav); }, [nav]);
  useEffect(() => { localStorage.setItem("tanaghom-agent", assistant ? "1" : "0"); }, [assistant]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 639px)");
    const sync = () => {
      const mobile = media.matches;
      setIsMobile(mobile);
      if (mobile) {
        setNav("hidden");
        setAssistant(false);
      }
    };
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  // keyboard: ⌘/Ctrl+B cycles the rail, ⌘/Ctrl+J toggles the agent (ignored while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      const el = document.activeElement;
      if (el && /^(INPUT|TEXTAREA)$/.test(el.tagName)) return;
      const k = e.key.toLowerCase();
      if (k === "b") { e.preventDefault(); setNav((v) => NEXT_NAV[v]); }
      else if (k === "j") { e.preventDefault(); setAssistant((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const icons = !isMobile && nav === "icons";
  const toggleNav = () => setNav((v) => isMobile ? (v === "hidden" ? "full" : "hidden") : NEXT_NAV[v]);
  const closeNav = () => setNav("hidden");

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* #170 — demo persona entry for a window with no persona yet (never in client-trial mode
          and never in IAM mode; the provider decides). Overlay above the shell. */}
      {r.personaEntry === true && <PersonaEntry />}
      {/* #190 — IAM mode: sign-in / truthful no-operating-identity surfaces (renders null when
          authenticated + bound, or when not in IAM mode). */}
      <IamEntry />
      {isMobile && nav !== "hidden" && (
        <button
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px]"
          onClick={closeNav}
        />
      )}
      {/* stage rail — full | icons | hidden. Available at every width (default icon rail is narrow),
          so navigation never vanishes on a small window; collapse to hidden for max canvas. */}
      {nav !== "hidden" && (
        <aside className={`flex shrink-0 flex-col border-r bg-card/40 ${
          isMobile
            ? "fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-card shadow-2xl"
            : icons ? "w-14" : "w-56"
        }`}>
          <div className={`flex h-14 items-center border-b ${icons ? "justify-center px-0" : "gap-2 px-4"}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/tenants/tanaghum/tanaghom-logo.png" alt="Tanaghom" className="size-7 rounded-md object-cover" />
            {!icons && <span className="font-semibold">Tanaghom</span>}
            {isMobile && (
              <Button variant="ghost" size="icon" className="ml-auto size-8" onClick={closeNav}>
                <X />
              </Button>
            )}
          </div>
          <nav className="flex-1 overflow-y-auto p-2">
            {STAGE_GROUPS.map((grp) => (
              <div key={grp} className="mb-3">
                {!icons && <div className="px-2 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{grp}</div>}
                {STAGES.filter((s) => s.group === grp).map((s) => {
                  const Icon = STAGE_ICON[s.key] || Inbox;
                  const active = r.stageKey === s.key;
                  return (
                    <button key={s.key} data-testid={`nav-${s.key}`} title={s.label} onClick={() => gotoStage(s.key)}
                      className={`flex w-full items-center rounded-md text-left text-sm ${icons ? "justify-center px-0 py-2" : "gap-2 px-2 py-1.5"} ${
                        active ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}>
                      <Icon className="size-4 shrink-0" />{!icons && s.label}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>
          <div className={`border-t py-3 ${icons ? "px-0 text-center" : "px-4"}`}>
            <span className={`flex items-center gap-1.5 text-xs text-muted-foreground ${icons ? "justify-center" : ""}`}>
              {!icons && "Powered by"}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/brand/platform/stitch/stitch-logo.png" alt="Stitch" className="size-4 rounded-[4px]" />
              {!icons && <span className="font-medium text-foreground/70">Stitch</span>}
            </span>
          </div>
        </aside>
      )}

      {/* main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {clientTrial && (
          <div data-testid="client-trial-banner" role="status" className="flex flex-wrap items-center justify-center gap-2 border-b border-primary/40 bg-primary/10 px-3 py-1.5 text-xs">
            <span className="font-medium text-foreground">Live client trial · Data is temporary and may be purged</span>
            <span className="rounded-full border border-success/40 bg-success/10 px-2 py-0.5 font-medium text-success">Generation: Live</span>
          </div>
        )}
        <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-2 border-b px-3 py-2 sm:h-14 sm:min-h-0 sm:flex-nowrap sm:py-0">
          {/* rail toggle — cycles full → icons → hidden */}
          <Button data-testid="nav-toggle" variant="ghost" size="icon" className="size-8 shrink-0" title="Toggle nav (⌘/Ctrl+B)" onClick={toggleNav}>
            <PanelLeftClose />
          </Button>
          {/* middle group — may scroll horizontally on small screens; never pushes the right controls off */}
          <div className="order-3 flex min-w-0 basis-full flex-wrap items-center gap-2 pb-1 sm:order-2 sm:basis-auto sm:flex-1 sm:flex-nowrap sm:overflow-x-auto sm:pb-0">
            {/* lens switcher — one data model, many lenses */}
            <div className="flex w-full shrink-0 items-center gap-0.5 overflow-x-auto rounded-lg border bg-card/60 p-0.5 sm:w-auto" data-testid="lens-switcher">
              {LENSES.map((l) => {
                const Icon = l.icon;
                return (
                  <button
                    key={l.key}
                    data-testid={`lens-${l.key}`}
                    onClick={() => r.setView(l.key)}
                    title={l.label}
                    aria-label={l.label}
                    className={`flex size-9 items-center justify-center rounded-full text-sm font-medium transition-colors ${
                      r.view === l.key ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-secondary/60"
                    }`}
                  >
                    <Icon className="size-4" />
                    <span className="sr-only">{l.label}</span>
                  </button>
                );
              })}
            </div>
            <div className="mx-0.5 hidden h-6 w-px shrink-0 bg-border sm:block" />
            <div className="flex w-full min-w-0 flex-wrap items-center gap-2 rounded-[1.35rem] border border-border/80 bg-card/65 px-2 py-1 shadow-[inset_0_1px_0_hsl(var(--foreground)/0.03)] sm:w-auto sm:flex-nowrap">
              <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl px-1 sm:flex-none">
                <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">Plan</span>
                <Select value={r.round} onValueChange={r.setRound}>
                  <SelectTrigger
                    data-testid="round-trigger"
                    className="h-10 w-[160px] border-0 bg-transparent px-3 shadow-none sm:w-[190px]"
                  >
                    <SelectValue placeholder="plan" />
                  </SelectTrigger>
                  <SelectContent>
                    {r.rounds.map((x) => (
                      <SelectItem key={x.round_id} value={x.round_id} data-testid={`round-opt-${x.round_id}`}>
                        {x.round_id}
                        {x.label ? ` · ${x.label}` : ""}
                        {` · ${x.period_len_days}d × ${x.posts_per_day}/day · ${roundActiveCount(x)}/${x.slots} active`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {selectedRound && (
                <div className="hidden min-w-0 flex-1 items-center gap-2 xl:flex">
                  {selectedRoundLabel && (
                    <div className="min-w-0 truncate text-sm font-medium text-foreground/90">
                      {selectedRoundLabel}
                    </div>
                  )}
                  <div className="flex shrink-0 items-center gap-1.5">
                    <span
                      className="rounded-full border border-border/70 bg-background/75 px-2.5 py-1 text-[11px] font-semibold text-foreground/90"
                      title={`${selectedRound.period_len_days} day period · ${selectedRound.posts_per_day} post${selectedRound.posts_per_day === 1 ? "" : "s"} per day`}
                      aria-label={`${selectedRound.period_len_days} day period · ${selectedRound.posts_per_day} post${selectedRound.posts_per_day === 1 ? "" : "s"} per day`}
                    >
                      {selectedRound.period_len_days}:{selectedRound.posts_per_day}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${phaseTone(selectedRound.phase)}`}>
                      {humanRoundPhase(selectedRound.phase)}
                    </span>
                  </div>
                </div>
              )}

              <div className="hidden h-7 w-px shrink-0 bg-border/80 sm:block" />

              {!clientTrial && (
                <div className="w-full sm:w-auto sm:shrink-0">
                  <NewRunDialog
                    triggerLabel="New run"
                    triggerContent={<Plus className="size-4" />}
                    triggerTitle="Start a new run"
                    triggerVariant="warning"
                    triggerSize="icon"
                    triggerClassName="size-10 rounded-full shadow-none"
                  />
                </div>
              )}

              <div className="hidden h-7 w-px shrink-0 bg-border/80 lg:block" />

              {/* #190 — the inline reviewer/persona switcher is a DEMO-mode mechanism; under IAM
                  identity comes only from the authenticated session (switching = re-login). */}
              {!clientTrial && !r.iam?.mode && (
                <div className="hidden items-center gap-2 rounded-xl px-1 lg:flex">
                  <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">Reviewer</span>
                  <Select value={r.approver} onValueChange={r.setApprover}>
                    <SelectTrigger className="h-10 w-[140px] border-0 bg-transparent px-3 shadow-none">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(r.approvers.length
                        ? r.approvers.map((p) => p.principal_id)
                        : APPROVERS).map((a) => <SelectItem key={a} value={a}>{reviewerLabel(a)}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {pendingApprovalCount > 0 && (
                <div
                  className="flex size-10 shrink-0 items-center justify-center rounded-full border border-warning/30 bg-warning/10 text-xs font-semibold text-warning"
                  title={`${pendingApprovalCount} pending approval${pendingApprovalCount === 1 ? "" : "s"}`}
                  aria-label={`${pendingApprovalCount} pending approval${pendingApprovalCount === 1 ? "" : "s"}`}
                >
                  <div className="relative flex items-center justify-center">
                    <TimerReset className="size-4" />
                    <span className="absolute -right-2 -top-2 min-w-[1.1rem] rounded-full bg-warning px-1 text-[10px] leading-4 text-black">
                      {pendingApprovalCount}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
          {/* right controls — always pinned + visible, never overflow off-screen */}
          <div className="order-2 flex shrink-0 items-center gap-2 pl-1 sm:order-3">
            {/* #180 — visible self-identification: which surface this SERVER declares itself to be,
                the runtime writer mode (from the existing /health read model), and the build. Plus a
                scoped recovery action clearing ONLY Tanaghom-owned browser state — no browser
                forensics needed after stale-state incidents. */}
            {/* #205 — the tested build stays identifiable at EVERY viewport: below md the full
                surface/writer/build badge would crowd the header, so this compact always-visible
                `build <sha>` indicator (the SAME /api/runtime-fed state — TANAGHOM_BUILD_SHA-only
                truth, "unknown" when unstamped) carries the reference AND the scoped reset action
                on narrow panels, tablets, and phones. */}
            <span
              data-testid="runtime-badge-compact"
              title="Runtime build — the exact build this server is running. The reset icon clears only Tanaghom-owned local view state and reloads."
              className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-background/60 px-2 py-1 text-[10px] font-medium tracking-wide text-muted-foreground md:hidden"
            >
              <span>build</span>
              <span data-testid="runtime-build-compact" className="font-mono">{runtime?.build || "…"}</span>
              <button
                type="button"
                data-testid="reset-local-state-compact"
                aria-label="Reset local view state"
                title="Reset local view state — clears only Tanaghom-owned browser state (view prefs, window persona, Tanaghom cookies) and reloads."
                className="ml-0.5 rounded-full p-0.5 hover:bg-secondary hover:text-foreground"
                onClick={() => { void resetLocalViewState(); }}
              >
                <TimerReset className="size-3" />
              </button>
            </span>
            <span
              data-testid="runtime-badge"
              title="Runtime identity — surface (server-declared) · writer mode · build. The reset icon clears only Tanaghom-owned local view state and reloads."
              className="hidden items-center gap-1.5 rounded-full border border-border/70 bg-background/60 px-2.5 py-1 text-[10px] font-medium tracking-wide text-muted-foreground md:inline-flex"
            >
              <span data-testid="runtime-surface">{runtime ? (runtime.surface === "client-trial" ? "client trial" : "operator/internal") : "…"}</span>
              <span aria-hidden>·</span>
              <span data-testid="runtime-writer">{r.genMode === "live" ? "live writer" : r.genMode === "stub" ? "stub writer" : "writer n/a"}</span>
              <span aria-hidden>·</span>
              <span data-testid="runtime-build" className="font-mono">{runtime?.build || "…"}</span>
              <button
                type="button"
                data-testid="reset-local-state"
                aria-label="Reset local view state"
                title="Reset local view state — clears only Tanaghom-owned browser state (view prefs, window persona, Tanaghom cookies) and reloads."
                className="ml-0.5 rounded-full p-0.5 hover:bg-secondary hover:text-foreground"
                onClick={() => { void resetLocalViewState(); }}
              >
                <TimerReset className="size-3" />
              </button>
            </span>
            {/* #170 — the active persona is always visible in the shell (every viewport, unlike the
                lg-only inline switcher) so parallel demo windows are never ambiguous about who is
                acting. Operational identity, not auth — hidden in client-trial (fixed reviewer).
                #190 — in IAM mode the badge renders ONLY for an authenticated + bound session:
                the client-side default approver must never be displayed as an acting identity
                the server would refuse to sign. */}
            {!clientTrial && (!r.iam?.mode || (r.iam.authenticated && !r.iam.unbound)) && (
              <span
                data-testid="persona-active-badge"
                title="Internal demo persona — operational identity, not authentication. Approvals are authorized server-side against workflow assignments."
                className="inline-flex max-w-[10rem] items-center gap-1.5 truncate rounded-full border border-border/80 bg-background/75 px-3 py-1.5 text-xs font-medium"
              >
                <span className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">acting as</span>
                <span className="truncate">{reviewerLabel(r.approver)}</span>
              </span>
            )}
            <ThemeSwitcher />
            <Button
              data-testid="assistant-toggle"
              variant={assistant ? "default" : "outline"}
              size="icon"
              className="size-10 rounded-full"
              title="Toggle agent (⌘/Ctrl+J)"
              aria-label="Toggle agent"
              onClick={() => setAssistant((v) => !v)}
            >
              <MessagesSquare />
              <span className="sr-only">Agent</span>
            </Button>
          </div>
        </header>

        {/* #23 generation-mode visibility — an unmissable strip whenever generation is not live, so
            synthetic (stub/dev) output can never be silently read as real content. Sourced from the
            authoritative /health writer_mode; hidden when live. */}
        {r.genMode && r.genMode !== "live" && (
          <div
            data-testid="gen-mode-banner"
            data-mode={r.genMode}
            role="status"
            className={`flex shrink-0 items-center gap-2 border-b px-3 py-1.5 text-xs ${
              r.genMode === "stub"
                ? "border-warning/45 bg-warning/15 text-foreground"
                : "border-border bg-muted/40 text-muted-foreground"
            }`}
          >
            {r.genMode === "stub" ? (
              <>
                <TriangleAlert className="size-3.5 shrink-0 text-warning" />
                <span><strong>Generation: Stub</strong> — output is synthetic (dev/test writer). Not real content; do not treat as client-ready.</span>
              </>
            ) : (
              <>
                <Info className="size-3.5 shrink-0" />
                <span>Generation mode unavailable — could not read the runtime writer mode from <code>/health</code>.</span>
              </>
            )}
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          {/* #261 — reserve scroll-padding-top equal to the review surface's live sticky-control
              height (published as --review-sticky-h), so every scroll-into-view lands controls
              BELOW the sticky band and ordinary pointer click() hits them. Fallback covers first
              paint before the surface measures. */}
          <main data-testid="review-main" data-view={r.view} className="min-w-0 flex-1 overflow-y-auto"
                style={{ scrollPaddingTop: "min(calc(var(--review-sticky-h, 6rem) + 0.75rem), 40vh)" }}>
            {r.view === "overview" ? <OverviewLens onStage={(k, rid) => gotoStage(k, rid, { view: "inbox" })} />
              : r.view === "workflow" ? <WorkflowLens onStage={(k) => gotoStage(k, undefined, { view: "inbox" })} />
              : r.view === "grid" ? <ReviewSurface layout="grid" />
              : r.view === "calendar" ? <ReviewSurface layout="calendar" />
              : <ReviewSurface layout="list" />}
          </main>
          {assistant && (
            <aside className={`flex flex-col border-l bg-card/40 ${
              isMobile
                ? "fixed inset-y-0 right-0 z-50 w-full max-w-[100vw] bg-card shadow-2xl"
                : "w-[360px] max-w-[80vw] shrink-0"
            }`} data-testid="assistant-panel">
              <div className="flex h-12 items-center justify-between border-b px-3">
                <span className="text-sm font-medium">Agent</span>
                <Button variant="ghost" size="sm" onClick={() => setAssistant(false)}><X /></Button>
              </div>
              <AssistantPanel />
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
