"use client";

// #382 — DEV/TEST-ONLY harness for the Agent panel's injectable adapter seam (amendment §D).
//
// It mounts the PURE <AgentPanel> with a deterministic INJECTED adapter that is "available" and whose
// `run` always fails, plus a fixed run context. This is the ONLY way the transport-error presentation
// can appear — production always uses DEFAULT_V2_ADAPTER (unavailable, no `run`, no I/O). The page that
// renders this component 404s outside TANAGHOM_DEV_MODE, so this seam is unreachable in production.

import { useState } from "react";
import { AgentPanel, type AgentAdapter } from "./agent-panel";

const FAILING_TEST_ADAPTER: AgentAdapter = {
  available: true,
  run: async () => ({ ok: false, error: "Transport failed (deterministic probe adapter)." }),
};

export function AgentAdapterProbe() {
  const [open, setOpen] = useState(true);
  return (
    <div data-testid="agent-adapter-probe" className="flex flex-col gap-2">
      <p className="text-xs text-(--color-muted)">
        Dev/test-only Agent adapter probe — an injected adapter whose transport always fails. Not present
        in production.
      </p>
      <button type="button" data-testid="agent-probe-open" onClick={() => setOpen(true)} className="self-start rounded-md border border-(--color-border) px-2 py-1 text-xs">
        Reopen
      </button>
      <AgentPanel
        open={open}
        onClose={() => setOpen(false)}
        roundId="PROBE-RUN"
        isMobile={false}
        adapter={FAILING_TEST_ADAPTER}
      />
    </div>
  );
}
