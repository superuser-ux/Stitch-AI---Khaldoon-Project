import { notFound } from "next/navigation";
import { devMode } from "@/lib/principal-proxy";
import { AgentAdapterProbe } from "@/components/agent-adapter-probe";

// #382 — dev/test-only route that exercises the Agent panel's injected-adapter transport-error path
// (amendment §D). It 404s outside TANAGHOM_DEV_MODE, so the injected/failing adapter — and any
// transport-error presentation — is UNREACHABLE in production. Rendered dynamically so the dev gate is
// evaluated per request, never baked into a static prerender.
export const dynamic = "force-dynamic";

export default function AgentAdapterProbePage() {
  if (!devMode()) notFound();
  return <AgentAdapterProbe />;
}
