"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { navigationSurfaces } from "@/lib/product-surface";
import { RuntimeStrip } from "./runtime-strip";
import { DirToggle } from "./dir-toggle";
import { AppearanceToggle } from "./appearance-toggle";
import { ScheduleStyleToggle } from "./schedule-style-toggle";
import { SyntheticLaneBanner } from "./synthetic-lane-banner";
import { ShellAgentPanel } from "./agent-panel";
import { useShellNav } from "./shell-nav";
import { IamAccount, IamBoundary } from "./iam-boundary";

// #293 §3 brand continuity — the canonical marks are rendered in the ALWAYS-PRESENT header and footer,
// never inside a collapsible region. §3 forbids omitting, substituting, or conditionally hiding either
// mark, so placing them outside any responsive branch keeps that structurally true at 375px, tablet and
// desktop. Accessible names mirror V1 exactly: alt="Tanaghom" and alt="Stitch".
//
// #382 — this is now the SOLE owner of global navigation chrome (ruling 3): the persistent side rail
// (governed lifecycle stages, derived from active-enabled), the top lens menu (the single 3-class
// matrix), and the first-class Agent panel region. It is mounted once in app/layout.tsx inside
// <ShellNavProvider>, so both `/` and `/runs/{id}` share one containment, and the run workspace no
// longer renders any rail/lens chrome of its own — there is never a duplicate lifecycle authority. The
// single <main> invariant (#330/#331) is preserved: exactly one <main>, with the route's children
// inside it; the rail is an <aside>, the Agent panel a <dialog>, neither is a second <main>.

/** Rail item — full labels in `full`, an initial glyph in `icons`; the accessible name is always the
 *  full governed label so screen readers and keyboard users never lose it. */
function stageInitials(label: string): string {
  const parts = label.trim().split(/\s+/);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : label.slice(0, 2)).toUpperCase();
}

// #385 scope 5 — the visible, focusable, touch-accessible "why is this disabled" disclosure that
// replaces title-only discoverability for context-invalid + unimplemented lenses/stages. The disabled
// buttons keep their native `title` (supplemental only, per acceptance 7) and their sr-only reason;
// this adds a real, non-hover surface: a focusable toggle (keyboard + touch) that reveals the reasons
// as VISIBLE text. It never enables anything — it only explains what is already truthfully disabled.
type DisabledItem = { key: string; label: string; reason: string };
function DisabledHelp({ idBase, heading, items }: { idBase: string; heading: string; items: DisabledItem[] }) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  const panelId = `${idBase}-help-panel`;
  return (
    <div className="w-full">
      <button
        type="button"
        data-testid={`${idBase}-help-toggle`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="rounded-full border border-(--color-border) px-2 py-0.5 text-[11px] text-(--color-muted) hover:bg-(--color-bg)"
      >
        {open ? "Hide why some are unavailable" : `Why ${items.length} unavailable?`}
      </button>
      {open && (
        <ul
          id={panelId}
          data-testid={`${idBase}-help-panel`}
          role="region"
          aria-label={heading}
          className="mt-1 flex flex-col gap-1 rounded-md border border-(--color-border-subtle) bg-(--color-bg) p-2 text-[11px] text-(--color-muted)"
        >
          {items.map((it) => (
            <li key={it.key} data-testid={`${idBase}-reason-${it.key}`}>
              <span className="font-medium text-(--color-fg)">{it.label}</span> — {it.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SideRail({ mode, overlay }: { mode: "full" | "icons"; overlay: boolean }) {
  const { rail, railError, resolvedStage, stageIsNavigable, onStage } = useShellNav();
  const showLabels = mode === "full";
  return (
    <div className={`flex h-full flex-col gap-2 ${showLabels ? "w-56" : "w-14"} ${overlay ? "" : "shrink-0"}`}>
      {rail ? (
        <>
          <nav
            aria-label="Lifecycle stages"
            data-testid="stage-rail"
            data-workflow-version={rail.versionId}
            data-rail-mode={mode}
            className="flex flex-col gap-1"
          >
            {rail.stages.map((s) => {
              const isCurrent = s.navigable && s.key === resolvedStage?.key;
              const interactive = s.navigable && stageIsNavigable;
              return (
                <button
                  key={s.key}
                  type="button"
                  data-testid={`stage-${s.key}`}
                  data-active={s.navigable ? "true" : "false"}
                  aria-current={isCurrent ? "page" : undefined}
                  aria-label={showLabels ? undefined : s.label}
                  disabled={!interactive}
                  title={!s.navigable ? s.reason : !stageIsNavigable ? "Open a run to work this stage." : undefined}
                  onClick={() => interactive && onStage(s.key)}
                  className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-start text-xs ${
                    isCurrent ? "border-(--color-fg) font-semibold" : "border-(--color-border)"
                  } ${interactive ? "hover:bg-(--color-bg)" : "opacity-60"}`}
                >
                  <span aria-hidden className="inline-flex size-5 shrink-0 items-center justify-center rounded bg-(--color-sunken) text-[10px] font-semibold">
                    {stageInitials(s.label)}
                  </span>
                  {showLabels && <span className="truncate">{s.label}</span>}
                  {!s.navigable && <span className="sr-only"> ({s.reason})</span>}
                </button>
              );
            })}
          </nav>
          {showLabels && (
            <DisabledHelp
              idBase="stage"
              heading="Why some stages are unavailable"
              items={rail.stages
                .filter((s) => !s.navigable && s.reason)
                .map((s) => ({ key: s.key, label: s.label, reason: s.reason as string }))}
            />
          )}
          {showLabels && (
            <p data-testid="stage-rail-provenance" className="mt-auto text-[11px] text-(--color-muted)">
              Stages from governed workflow version {rail.versionNo} ({rail.status}).
            </p>
          )}
        </>
      ) : (
        <p data-testid="stage-rail-unavailable" className="text-xs text-(--color-muted)">
          Lifecycle stages unavailable — {railError ?? "the governed workflow version could not be read"}.
          No stages are shown rather than guessing which exist.
        </p>
      )}
    </div>
  );
}

function LensMenu() {
  const { lensItems, lens, onLens, stageIsNavigable } = useShellNav();
  if (lensItems.length === 0) return null; // gate has no lens menu (e.g. Scripts)
  // #385 scope 5 — the structurally-disabled lenses (context-invalid + unimplemented) carry a truthful
  // `reason`; implemented-enabled ones do not. That reason set is what the visible disclosure explains.
  const explained = lensItems
    .filter((l) => !l.navigable && l.reason)
    .map((l) => ({ key: l.key, label: l.label, reason: l.reason as string }));
  return (
    <nav
      aria-label="Workspace view"
      data-testid="lens-menu"
      data-context-only={stageIsNavigable ? undefined : "true"}
      className="flex flex-wrap items-center gap-1 overflow-x-auto border-b border-(--color-border-subtle) px-3 py-1.5 text-xs sm:px-4"
    >
      {/* #385 scope 3 — a visible hierarchy caption. This top menu is the "Workspace view" (which
          artifact surface the whole workspace shows), distinct from the calendar lens's internal
          "Calendar display" toolbar. The two no longer share the ambiguous bare word "List". */}
      <span
        data-testid="lens-menu-label"
        className="me-1 shrink-0 text-[11px] font-medium uppercase tracking-wide text-(--color-muted)"
      >
        Workspace view
      </span>
      {lensItems.map((l) => {
        // On root (no selected run) the menu is context only: Calendar is shown current but no lens
        // navigates — nothing fake-navigates to a placeholder (Scope §6).
        const interactive = l.navigable && stageIsNavigable;
        return (
        <button
          key={l.key}
          type="button"
          data-testid={`lens-${l.key}`}
          data-class={l.cls}
          data-active={l.navigable ? "true" : "false"}
          aria-current={l.key === lens ? "page" : undefined}
          disabled={!interactive}
          title={l.reason ?? (!stageIsNavigable ? "Open a run to change the view." : undefined)}
          onClick={() => interactive && onLens(l.key)}
          className={`rounded-full border px-2.5 py-0.5 ${
            l.key === lens ? "border-(--color-fg) font-semibold" : "border-(--color-border)"
          } ${l.navigable ? "hover:bg-(--color-bg)" : "opacity-50"}`}
        >
          {l.label}
          {!l.navigable && <span className="sr-only"> ({l.reason})</span>}
        </button>
        );
      })}
      <DisabledHelp idBase="lens" heading="Why some views are unavailable" items={explained} />
    </nav>
  );
}

// #410 — global product destinations, rendered from the SINGLE canonical registry (the sole metadata
// source) via the `showInNavigation` filter. This is not a second navigation authority and does not
// touch #331 run/stage/lens context. The header is the one nav surface for these destinations on both
// desktop and mobile (it wraps at 375px), so there is exactly one mobile implementation. Existing
// Identity/Secrets hrefs, test IDs, order, and behavior are preserved verbatim by the registry data;
// only Process Studio is newly navigable, and only it carries the safe-return `from` context.
function GlobalDestinations() {
  const pathname = usePathname() ?? "/";
  const params = useSearchParams();
  const qs = params?.toString();
  // The URL hash is client-only (never in useSearchParams / SSR). Capture it safely AFTER mount so the
  // safe-return `from` preserves path + query + HASH, and keep it current across in-page hash changes.
  const [hash, setHash] = useState("");
  useEffect(() => {
    const read = () => setHash(window.location.hash || "");
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  // Preserve the originating internal Workbench URL so Return lands where the user came from. Never
  // seed `from` with a Studio URL (a Return must go back to the Workbench, not to itself).
  const from = pathname.startsWith("/studio") ? "/" : `${pathname}${qs ? `?${qs}` : ""}${hash}`;
  return (
    <>
      {navigationSurfaces().map((s) => {
        const href =
          s.id === "process-studio"
            ? `${s.route}?from=${encodeURIComponent(from)}`
            : (s.route as string);
        return (
          <Link
            key={s.id}
            href={href}
            data-testid={s.testId}
            title={s.label}
            className="shrink-0 rounded-md border border-(--color-border) px-2 py-1 text-xs hover:bg-(--color-bg)"
          >
            {s.label}
          </Link>
        );
      })}
    </>
  );
}

function NavToggle() {
  const { navMode, cycleNav, isMobile, mobileRailOpen } = useShellNav();
  const label = isMobile
    ? (mobileRailOpen ? "Close navigation" : "Open navigation")
    : `Navigation: ${navMode} (press to cycle)`;
  return (
    <button
      type="button"
      data-testid="nav-toggle"
      onClick={cycleNav}
      aria-label={label}
      aria-expanded={isMobile ? mobileRailOpen : navMode !== "hidden"}
      title={label}
      className="shrink-0 rounded-md border border-(--color-border) px-2 py-1 text-xs hover:bg-(--color-bg)"
    >
      ☰
    </button>
  );
}

function AgentTrigger() {
  const { agentOpen, setAgent } = useShellNav();
  return (
    <button
      type="button"
      data-testid="agent-trigger"
      onClick={() => setAgent(!agentOpen)}
      aria-pressed={agentOpen}
      aria-label="Toggle agent panel"
      title="Agent (⌘/Ctrl-J)"
      className="shrink-0 rounded-md border border-(--color-border) px-2 py-1 text-xs hover:bg-(--color-bg)"
    >
      Agent
    </button>
  );
}

export function WorkbenchShell({ children }: { children: React.ReactNode }) {
  const { navMode, isMobile, mobileRailOpen, setMobileRail, notice } = useShellNav();
  // Desktop rail visibility follows the persisted three-state mode; mobile ignores it (overlay only).
  const desktopRailMode = navMode === "hidden" ? null : navMode; // null → not shown

  return (
    <div className="flex min-h-dvh flex-col">
      {/* #342 — above the header, outside every collapsible region: an acceptance reviewer must not be
          able to scroll past, collapse, or miss the synthetic-data statement. */}
      <SyntheticLaneBanner />

      <header
        data-testid="wb-header"
        // Header sits BELOW the mobile overlays (scrim z-40, rail drawer z-50, agent drawer z-50) so a
        // modal overlay genuinely blocks background interaction (§F) AND each overlay's own close
        // control stays on top and reachable (the rail scrim, the agent close button). Switching one
        // overlay for the other is enforced at the state level and driven by the keyboard (⌘/Ctrl-B/J),
        // which is never occluded — so rail⇄agent mutual exclusion needs no reachable covered trigger.
        className="sticky top-0 z-20 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-(--color-border-subtle) bg-(--color-nav) px-3 py-2 shadow-(--shadow-sm) sm:px-4"
      >
        <NavToggle />
        <img
          data-testid="wb-brand-tanaghom"
          src="/brand/tenants/tanaghum/tanaghom-logo.png"
          alt="Tanaghom"
          className="size-7 shrink-0 rounded-md object-cover"
        />
        <span className="truncate text-sm font-semibold">Tanaghom Workbench</span>
        <span
          data-testid="wb-lane-badge"
          className="shrink-0 rounded-full border border-(--color-border) px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-(--color-muted)"
          title="V2 is a transition lane, not a second product (#293)"
        >
          V2 transition lane
        </span>

        {/* ms-auto is a logical property: it flips correctly under dir=rtl with no RTL stylesheet.
            #335 — appearance, schedule style and direction are orthogonal presentation controls; they
            wrap together (flex-wrap) so 375px never overflows the page. The Agent trigger joins them.

            `min-w-0` (NOT `shrink-0`) is load-bearing, and the distinction is the whole defect this
            cluster once had. `flex-wrap` can only wrap when the box is NARROWER than its contents, but
            `flex-shrink: 0` pins a flex item at its max-content width — and a wrapping flex container's
            max-content contribution is the sum of ALL its children on ONE line. So `shrink-0` here
            measured this cluster at a constant ~586px at every viewport, the inner wrap could never
            engage, and 375px overflowed the document by 223px with the Agent trigger, Process Studio
            and Secrets pushed off-screen. The comment above claimed the wrap protected 375px; the
            utility class silently prevented it. Allowing the box to shrink (default flex-shrink, plus
            `min-w-0` to defeat the automatic min-content floor) is what makes the wrap real, so the
            claim and the CSS now agree. Do not reintroduce `shrink-0` on this element. */}
        <div className="ms-auto flex min-w-0 flex-wrap items-center justify-end gap-2">
          <AppearanceToggle />
          <ScheduleStyleToggle />
          <DirToggle />
          <GlobalDestinations />
          <IamAccount />
          <AgentTrigger />
        </div>

        <div className="w-full sm:w-auto">
          <RuntimeStrip />
        </div>
      </header>

      {/* top lens menu (the single 3-class matrix) — spans full width under the header */}
      <LensMenu />

      {/* accessible canonicalization notice (amendment §B) */}
      <div aria-live="polite" role="status" className="sr-only" data-testid="shell-nav-notice">
        {notice ?? ""}
      </div>

      <div className="relative flex flex-1">
        {/* Desktop rail: an in-flow column reflecting the 3-state mode. */}
        {!isMobile && desktopRailMode && (
          <aside data-testid="shell-rail" data-variant="desktop" className="shrink-0 border-e border-(--color-border-subtle) bg-(--color-nav) p-2">
            <SideRail mode={desktopRailMode} overlay={false} />
          </aside>
        )}

        {/* Mobile rail: a modal overlay drawer + scrim. It blocks background interaction and never
            overwrites the desktop mode (ruling 6 / §F). */}
        {isMobile && mobileRailOpen && (
          <>
            <button
              type="button"
              data-testid="shell-rail-scrim"
              aria-label="Close navigation"
              onClick={() => setMobileRail(false)}
              className="fixed inset-0 z-40 bg-black/40"
            />
            <aside
              data-testid="shell-rail"
              data-variant="mobile"
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
              className="fixed inset-y-0 start-0 z-50 w-64 overflow-y-auto border-e border-(--color-border-strong) bg-(--color-nav) p-3 shadow-(--shadow-lg)"
            >
              <SideRail mode="full" overlay />
            </aside>
          </>
        )}

        <main data-testid="wb-main" className="min-w-0 flex-1 px-3 py-4 sm:px-4">
          <IamBoundary>{children}</IamBoundary>
        </main>

        {/* Agent panel region — desktop dock (right column) or mobile full-height drawer. Renders null
            when closed. Its default adapter performs no I/O. */}
        <ShellAgentPanel />
      </div>

      <footer
        data-testid="wb-footer"
        className="border-t border-(--color-border-subtle) bg-(--color-nav) px-3 py-3 sm:px-4"
      >
        <span data-testid="wb-poweredby" className="flex items-center gap-1.5 text-xs text-(--color-muted)">
          Powered by
          <img
            data-testid="wb-brand-stitch"
            src="/brand/platform/stitch/stitch-logo.png"
            alt="Stitch"
            className="size-4 shrink-0 rounded-[4px]"
          />
          <span className="font-medium">Stitch</span>
        </span>
      </footer>
    </div>
  );
}
