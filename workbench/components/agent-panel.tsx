"use client";

// #382 — the conversational Agent panel: a first-class, structurally-complete surface that is
// TRUTHFUL and FAIL-CLOSED in this slice.
//
// HARD STOP (issue "Agent authority boundary" / ruling 5). The V1 agent endpoint
// (`POST /rounds/{id}/agent`) is a live Groq tool-calling channel that can execute governed writes
// (approve/reject/rework/…). It is in NEITHER `/gw` allowlist and `/gw` returns 403 for it. This panel
// must therefore render the conversation architecture WITHOUT any upstream/model/action request: the
// default V2 adapter performs ZERO I/O and the composer cannot accept or queue a message. It preserves
// the seam (an injectable adapter interface) so a later, separately-authorised integration directive
// can supply a real adapter — this slice supplies none.
//
// Amendment §D — the delivered panel keeps a recognisable conversation layout: accessible title/close,
// message-history region, empty/no-run/unavailable status, disabled composer with explanation, focus
// entry/containment where modal, Escape handling, focus restoration, and a run-context slot that
// ASSERTS NO IDENTITY. Production states are exactly `no run selected` and
// `integration unavailable in this V2 boundary`; a transport-error presentation exists ONLY through a
// deterministic injected test adapter (exercised by the dev-gated adapter probe, never in production).
//
// The panel is split into a PURE presentational component (`AgentPanel`, driven entirely by props so a
// test can mount it with any adapter/run-context) and a thin `ShellAgentPanel` wrapper that binds it to
// the shared shell-nav state. The shell mounts the wrapper, always supplying DEFAULT_V2_ADAPTER.

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useShellNav } from "./shell-nav";

export type AgentSendResult = { readonly ok: true; readonly reply: string } | { readonly ok: false; readonly error: string };

/** The injectable seam. The DEFAULT adapter is unavailable and exposes no `run`, so no code path can
 *  issue a request. A later authorised integration (or a deterministic test) supplies its own. */
export type AgentAdapter = {
  readonly available: boolean;
  readonly unavailableReason?: string;
  run?(input: { readonly message: string; readonly roundId: string }): Promise<AgentSendResult>;
};

/** The production V2 adapter: unavailable, no `run`, performs no I/O. Opening/closing the panel with
 *  this adapter emits no Agent/provider/chat/action/mutation/V1 request (proven by browser capture). */
export const DEFAULT_V2_ADAPTER: AgentAdapter = {
  available: false,
  unavailableReason: "Agent integration is unavailable in this V2 boundary. A separate authorised directive is required before it can act.",
};

type Msg = { readonly role: "user" | "agent"; readonly text: string };

export type AgentPanelProps = {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly roundId: string | null;
  readonly isMobile: boolean;
  readonly adapter?: AgentAdapter;
};

/** Pure, props-driven panel. Testable in isolation with any adapter + run context. */
export function AgentPanel({ open, onClose, roundId, isMobile, adapter = DEFAULT_V2_ADAPTER }: AgentPanelProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const [messages, setMessages] = useState<readonly Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [transportError, setTransportError] = useState<string | null>(null);

  const noRun = roundId === null;
  // The composer is ENABLED only when a run is selected AND the adapter can actually act. The default
  // adapter is unavailable, so in production it is always disabled — it cannot accept or queue text.
  const canSend = !noRun && adapter.available && typeof adapter.run === "function";

  const status = noRun
    ? "No run selected — open a run to give the agent context."
    : adapter.available
      ? (transportError ?? "Ready.")
      : (adapter.unavailableReason ?? "Agent integration is unavailable in this V2 boundary.");

  // Focus entry + restoration. On open, remember what had focus and move focus into the panel; on
  // close, restore it to the trigger (amendment §D).
  useEffect(() => {
    if (open) {
      returnFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
      requestAnimationFrame(() => closeRef.current?.focus());
    } else if (returnFocusRef.current) {
      returnFocusRef.current.focus?.();
      returnFocusRef.current = null;
    }
  }, [open]);

  // Escape closes; focus containment (a simple Tab trap) applies only when the panel is MODAL — the
  // full-height mobile drawer. On desktop the panel is a non-modal dock, so focus moves freely.
  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
    if (e.key !== "Tab" || !isMobile) return;
    const root = panelRef.current;
    if (!root) return;
    const focusables = root.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])',
    );
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }, [isMobile, onClose]);

  const onSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSend || !adapter.run || !roundId) return; // fail-closed: default adapter never reaches here
    const message = draft.trim();
    if (!message) return;
    setMessages((m) => [...m, { role: "user", text: message }]);
    setDraft("");
    setTransportError(null);
    const res = await adapter.run({ message, roundId });
    if (res.ok) setMessages((m) => [...m, { role: "agent", text: res.reply }]);
    else setTransportError(res.error);
  }, [canSend, adapter, draft, roundId]);

  if (!open) return null;

  return (
    <div
      ref={panelRef}
      data-testid="agent-panel"
      data-available={adapter.available ? "true" : "false"}
      data-has-run={noRun ? "false" : "true"}
      role="dialog"
      aria-modal={isMobile ? "true" : undefined}
      aria-labelledby={titleId}
      onKeyDown={onKeyDown}
      className={
        isMobile
          ? "fixed inset-0 z-50 flex h-dvh w-full flex-col gap-3 border-s border-(--color-border-strong) bg-(--color-elevated) p-3 shadow-(--shadow-lg)"
          : "flex h-full w-full max-w-sm flex-col gap-3 border-s border-(--color-border-subtle) bg-(--color-elevated) p-3 shadow-(--shadow-md)"
      }
    >
      <div className="flex items-center gap-2 border-b border-(--color-border-subtle) pb-2">
        <h2 id={titleId} data-testid="agent-panel-title" className="text-sm font-semibold">Agent</h2>
        <button
          ref={closeRef}
          type="button"
          data-testid="agent-panel-close"
          onClick={onClose}
          aria-label="Close agent panel"
          className="ms-auto rounded-md border border-(--color-border) px-2 py-0.5 text-xs hover:bg-(--color-bg)"
        >
          Close
        </button>
      </div>

      {/* run-context slot — shows the selected run for context ONLY; it asserts no identity, no actor,
          and carries no authority (amendment §D). */}
      <p data-testid="agent-run-context" className="text-[11px] text-(--color-muted)">
        {noRun ? "No run in context." : <>Context: run <span className="font-mono">{roundId}</span> — read-only context, no identity or authority asserted.</>}
      </p>

      <div
        data-testid="agent-panel-history"
        role="log"
        aria-live="polite"
        className="flex-1 overflow-y-auto rounded-md border border-(--color-border-subtle) bg-(--color-bg) p-2 text-xs"
      >
        {messages.length === 0 ? (
          <p data-testid="agent-panel-empty" className="text-(--color-muted)">No messages yet.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {messages.map((m, i) => (
              <li key={i} data-testid={`agent-msg-${m.role}`} className={m.role === "user" ? "text-(--color-fg)" : "text-(--color-muted)"}>
                <span className="font-medium">{m.role === "user" ? "You" : "Agent"}: </span>{m.text}
              </li>
            ))}
          </ul>
        )}
      </div>

      <p
        data-testid="agent-panel-status"
        data-state={noRun ? "no-run" : adapter.available ? (transportError ? "transport-error" : "ready") : "unavailable"}
        role="status"
        className="text-[11px] text-(--color-muted)"
      >
        {status}
      </p>

      {/* composer — DISABLED and non-queuing whenever the agent cannot act (always, with the default
          adapter). It explains why rather than pretending to work. */}
      <form data-testid="agent-composer" onSubmit={onSubmit} className="flex flex-col gap-1.5">
        <label className="sr-only" htmlFor={`${titleId}-input`}>Message the agent</label>
        <textarea
          id={`${titleId}-input`}
          data-testid="agent-composer-input"
          value={draft}
          onChange={(e) => canSend && setDraft(e.target.value)}
          disabled={!canSend}
          rows={2}
          placeholder={canSend ? "Ask the agent…" : "Composer disabled — the agent cannot act in this boundary."}
          className="w-full resize-none rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs disabled:opacity-50"
        />
        <button
          type="submit"
          data-testid="agent-composer-send"
          disabled={!canSend || draft.trim().length === 0}
          className="self-end rounded-md border border-(--color-border) px-2.5 py-1 text-xs disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}

/** Shell binding: wires the pure panel to the shared nav state, always with the no-I/O default adapter. */
export function ShellAgentPanel() {
  const { agentOpen, setAgent, roundId, isMobile } = useShellNav();
  return (
    <AgentPanel
      open={agentOpen}
      onClose={() => setAgent(false)}
      roundId={roundId}
      isMobile={isMobile}
      adapter={DEFAULT_V2_ADAPTER}
    />
  );
}
