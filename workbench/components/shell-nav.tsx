"use client";

// #382 — the ONE shared navigation authority for the V2 containment shell.
//
// Ruling 2 (Codex reconciliation 5071383590): ONE shared pure resolver governs render, click,
// keyboard, reload and popstate canonicalization; stages stay derived from `active-enabled`, lenses
// from the single 3-class matrix (lib/shell-lens.ts). This context is where those pure resolvers are
// bound to the live URL exactly once for the whole app, so the shell (rail + top lens menu + Agent
// region) and the run workspace (panels) consume the SAME resolved stage/gate/lens — there is never a
// second rail or a second lens authority (ruling 3).
//
// It also owns the presentation-only shell chrome state: the responsive rail mode, the mobile overlay,
// the Agent panel open state, and their keyboard toggles. Persistence is bounded to ONE versioned
// presentation-only key holding NO run/stage/lens/identity/authority/server data (ruling 6); a
// malformed/legacy value fails safe to defaults; the mobile overlay is transient and NEVER overwrites
// the remembered desktop rail mode.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { deriveStageRail, resolveRailStage, type RailStage, type StageRail } from "@/lib/stage-rail";
import {
  defaultLensFor, lensEntries, lensNeedsCanonicalization, lensUrlKey, resolveLens,
  type LensEntry, type LensKey,
} from "@/lib/shell-lens";
import { readJson, ReadError, type WorkflowVersion } from "@/lib/read-model";

/** Rail display mode. Three states cycle full → icons → hidden (adapted from the proven V1 AppShell,
 *  NOT its styling or data model). `icons` is the roomy-canvas default. */
export type NavMode = "full" | "icons" | "hidden";
const NAV_CYCLE: Record<NavMode, NavMode> = { full: "icons", icons: "hidden", hidden: "full" };
// Default `full`: the governed stage labels and provenance are visible without interaction, which the
// stage-rail behavioral contract (#355) and the operator reference composition both expect. The three
// states still cycle full → icons → hidden on demand.
const DEFAULT_NAV: NavMode = "full";

/** The single versioned presentation-only persistence key (ruling 6). Namespaced away from V1's
 *  `tanaghom-nav`/`tanaghom-agent` so a shared origin cannot cross-contaminate. Holds only chrome
 *  presentation state — no run, stage, lens, identity, authority or server-derived data. */
export const SHELL_CHROME_KEY = "wb-shell-chrome-v1";

type ChromeState = { readonly nav: NavMode; readonly agent: boolean };
const DEFAULT_CHROME: ChromeState = { nav: DEFAULT_NAV, agent: false };

function parseChrome(raw: string | null): ChromeState {
  if (!raw) return DEFAULT_CHROME;
  try {
    const v = JSON.parse(raw) as Partial<ChromeState>;
    const nav: NavMode = v.nav === "full" || v.nav === "icons" || v.nav === "hidden" ? v.nav : DEFAULT_NAV;
    const agent = v.agent === true;
    return { nav, agent };
  } catch {
    return DEFAULT_CHROME; // malformed/legacy fails safe
  }
}

export type ShellNav = {
  /** Canonical run identity from the route, or null on the schedule-first root. Carried verbatim. */
  readonly roundId: string | null;
  readonly onRoot: boolean;
  // governed stage authority (derived from active-enabled; never invented)
  readonly rail: StageRail | null;
  readonly railError: string | null;
  readonly resolvedStage: RailStage | null;
  readonly gate: string | null;
  readonly stageIsNavigable: boolean; // false on root — stages are context-only until a run is selected
  onStage(key: string): void;
  // lens authority (the single 3-class matrix)
  readonly lens: LensKey | null;
  readonly lensItems: readonly LensEntry[];
  onLens(key: LensKey): void;
  /** Accessible truthful notice when a stale/invalid stage or lens URL was canonicalized (amendment §B). */
  readonly notice: string | null;
  // presentation-only chrome
  readonly navMode: NavMode;
  cycleNav(): void;
  readonly isMobile: boolean;
  readonly mobileRailOpen: boolean;
  setMobileRail(open: boolean): void;
  readonly agentOpen: boolean;
  setAgent(open: boolean): void;
};

const Ctx = createContext<ShellNav | null>(null);

/** Consume the one shell nav authority. Throws if used outside the provider (a wiring bug, not a
 *  runtime state). */
export function useShellNav(): ShellNav {
  const v = useContext(Ctx);
  if (!v) throw new Error("useShellNav must be used within <ShellNavProvider>");
  return v;
}

const RUN_ROUTE = /^\/runs\/([^/?#]+)/;

export function ShellNavProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const params = useSearchParams();
  const router = useRouter();

  const roundId = useMemo(() => {
    const m = RUN_ROUTE.exec(pathname);
    return m ? decodeURIComponent(m[1]) : null;
  }, [pathname]);
  const onRoot = roundId === null;

  // Governed stage rail — fetched ONCE for the app's lifetime (the provider lives in the persistent
  // layout). If it cannot be read, the shell says so; it never invents a rail (preserves #355).
  const [rail, setRail] = useState<StageRail | null>(null);
  const [railError, setRailError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    readJson<WorkflowVersion>("/gw/workflow-stages/active-enabled", ac.signal)
      .then((v) => { setRail(deriveStageRail(v)); setRailError(null); })
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setRail(null);
        setRailError(e instanceof ReadError ? e.message : "the governed workflow version could not be read");
      });
    return () => ac.abort();
  }, []);

  const stageRaw = params?.get("stage") ?? null;
  const resolvedStage = resolveRailStage(rail, stageRaw);
  // On root the rail is CONTEXT ONLY: Schedule is current, but no stage navigates and no run is ever
  // fabricated (ruling 1). We still surface the schedule gate so the lens menu shows Calendar as the
  // active root lens (Scope §6), while `stageIsNavigable` stays false.
  const gate = onRoot ? "schedule_review" : resolvedStage?.gateStage ?? null;
  const stageIsNavigable = !onRoot;

  const lensKey = lensUrlKey(gate, roundId);
  const lensRaw = lensKey ? params?.get(lensKey) ?? null : null;
  const lens = resolveLens(gate, lensRaw);
  const lensItems = useMemo(() => lensEntries(gate), [gate]);

  // Accessible truthful notice when a stale/invalid stage or lens URL was canonicalized (amendment §B).
  // A deliberate stage/lens choice clears it; the canonicalization effect sets it (and does NOT clear
  // it on the follow-up render, so it persists to be announced rather than flashing).
  const [notice, setNotice] = useState<string | null>(null);

  const setParam = useCallback((key: string, value: string) => {
    const next = new URLSearchParams(params?.toString() ?? "");
    next.set(key, value);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }, [params, router, pathname]);

  const onStage = useCallback((key: string) => {
    // Never navigate a stage without a selected run — the root rail is context only (ruling 1).
    if (onRoot) return;
    setNotice(null);
    setParam("stage", key);
  }, [onRoot, setParam]);

  const onLens = useCallback((key: LensKey) => {
    // On root the lens menu is context only — Calendar is shown current but no lens navigates without a
    // selected run, so nothing fake-navigates to a placeholder (Scope §6 / ruling 1).
    if (onRoot) return;
    const k = lensUrlKey(gate, roundId);
    if (k) { setNotice(null); setParam(k, key); }
  }, [onRoot, gate, roundId, setParam]);

  // Canonicalization (amendment §B): when a run is selected and the rail is known, an unknown / disabled
  // / context-invalid stage or lens value in the URL is rewritten with REPLACE (never push) to the
  // first valid governed value, and an accessible truthful notice is surfaced. Absent values imply the
  // default and are NOT rewritten (no history churn). Never runs on root.
  useEffect(() => {
    if (onRoot || !rail) return;
    // stage: a present-but-unresolvable raw value (resolver fell back to a different navigable stage)
    if (stageRaw != null && stageRaw !== "" && resolvedStage && resolvedStage.key !== stageRaw) {
      setNotice(`“${stageRaw}” is not an available stage — showing ${resolvedStage.label}.`);
      const next = new URLSearchParams(params?.toString() ?? "");
      next.set("stage", resolvedStage.key);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
      return;
    }
    // lens: stale/cross-gate value → canonicalize to the gate default
    if (lensKey && lensNeedsCanonicalization(gate, lensRaw) && lens) {
      setNotice(`That view is not available here — showing ${lens}.`);
      const next = new URLSearchParams(params?.toString() ?? "");
      next.set(lensKey, lens);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    }
  }, [onRoot, rail, stageRaw, resolvedStage, lensKey, lensRaw, gate, lens, params, router, pathname]);

  // ---- presentation-only chrome state ----
  const [chrome, setChrome] = useState<ChromeState>(DEFAULT_CHROME);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileRailOpen, setMobileRailOpen] = useState(false);
  const hydrated = useRef(false);

  // Client-only restore (dodges hydration mismatch, like the #380 pre-paint init). Reads the ONE
  // versioned key; storage denied/malformed → safe defaults.
  useEffect(() => {
    let raw: string | null = null;
    try { raw = localStorage.getItem(SHELL_CHROME_KEY); } catch { /* denied → defaults */ }
    setChrome(parseChrome(raw));
    hydrated.current = true;
  }, []);
  // Persist ONLY after the first restore, so the initial default never clobbers a stored value.
  useEffect(() => {
    if (!hydrated.current) return;
    try { localStorage.setItem(SHELL_CHROME_KEY, JSON.stringify(chrome)); } catch { /* denied → skip */ }
  }, [chrome]);

  // Mobile detection. On entering mobile, close the Agent panel; the desktop rail MODE is preserved
  // (never written) — the mobile overlay is a separate transient state (ruling 6 / §F).
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(max-width: 639px)");
    const apply = () => {
      setIsMobile(mq.matches);
      if (mq.matches) { setMobileRailOpen(false); setChrome((c) => (c.agent ? { ...c, agent: false } : c)); }
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const setAgent = useCallback((open: boolean) => {
    // Rail overlay and Agent are mutually exclusive on mobile: opening one closes the other (§F).
    if (open) setMobileRailOpen(false);
    setChrome((c) => (c.agent === open ? c : { ...c, agent: open }));
  }, []);

  const setMobileRail = useCallback((open: boolean) => {
    if (open) setChrome((c) => (c.agent ? { ...c, agent: false } : c));
    setMobileRailOpen(open);
  }, []);

  const cycleNav = useCallback(() => {
    if (isMobile) { setMobileRail(!mobileRailOpen); return; }
    setChrome((c) => ({ ...c, nav: NAV_CYCLE[c.nav] }));
  }, [isMobile, mobileRailOpen, setMobileRail]);

  // Keyboard: ⌘/Ctrl-B cycles the rail (or toggles the mobile overlay); ⌘/Ctrl-J toggles the Agent
  // panel. Ignored while typing in a field so composing text never eats the shortcut.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      const el = document.activeElement as HTMLElement | null;
      if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
      const k = e.key.toLowerCase();
      if (k === "b") { e.preventDefault(); cycleNav(); }
      else if (k === "j") { e.preventDefault(); setAgent(!chrome.agent); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cycleNav, setAgent, chrome.agent]);

  const value: ShellNav = {
    roundId, onRoot,
    rail, railError, resolvedStage, gate, stageIsNavigable, onStage,
    lens, lensItems, onLens,
    notice,
    navMode: chrome.nav, cycleNav,
    isMobile, mobileRailOpen, setMobileRail,
    agentOpen: chrome.agent, setAgent,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
