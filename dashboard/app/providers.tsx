"use client";

// CopilotKit removed (Phase 2). The review surface is wrapped by ReviewProvider in page.tsx; the
// assistant runtime is now self-hosted per-panel (assistant-ui) — see components/assistant.
export function Providers({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
