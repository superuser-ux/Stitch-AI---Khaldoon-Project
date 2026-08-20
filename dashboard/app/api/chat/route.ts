import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import OpenAI from "openai";
import { principalProxyHeaders } from "@/lib/reviewer-session";
import { IAM_SESSION_COOKIE, iamEnabled, readSession, revalidateBinding } from "@/lib/iam-session";

// Thin chat backend: Groq (OpenAI-compatible) with tools that drive the SAME gate engine as the
// dashboard buttons. No CopilotKit. The engine stays the single source of truth — every tool call
// goes through the gate API and is audited there. Model/key are env (no-hardcode).
const MODEL = process.env.COPILOT_MODEL || "meta-llama/llama-4-scout-17b-16e-instruct";
const API = process.env.API_BASE || "http://localhost:8009";

type Ctx = { round?: string; stage?: string; stage_label?: string; approver?: string;
  gate_id?: string | null; round_phase?: string | null; round_stats?: unknown; stage_advisory?: unknown;
  items?: unknown[]; awaiting?: unknown[]; dropped?: { slot_id: string }[] };

const TOOLS: OpenAI.Chat.Completions.ChatCompletionTool[] = [
  {
    type: "function",
    function: {
      name: "decide_on_slot",
      description: "Record a decision on one content item in the current review. decision is approve | reject | request_change. A request_change REQUIRES a comment.",
      parameters: {
        type: "object",
        properties: {
          slot_id: { type: "string", description: "e.g. R3-D02-AM" },
          decision: { type: "string", enum: ["approve", "reject", "request_change"] },
          comment: { type: "string", description: "required when decision is request_change" },
        },
        required: ["slot_id", "decision"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "submit_decisions",
      description: "Apply (commit) the recorded decisions for the current review, moving approved items forward and parking sent-back/dropped items.",
      parameters: { type: "object", properties: {} },
    },
  },
  {
    type: "function",
    function: {
      name: "reopen_slot",
      description: "Restore a dropped (rejected) item — or reverse an approval — moving it back into review. Nothing is destroyed.",
      parameters: { type: "object", properties: { slot_id: { type: "string" } }, required: ["slot_id"] },
    },
  },
];

async function execTool(name: string, args: Record<string, unknown>, ctx: Ctx, trustedActor?: string) {
  // #194 — in IAM mode the actor comes ONLY from the validated + revalidated session (passed in);
  // the client-supplied ctx.approver is honored solely under the demo trust model.
  const actor = trustedActor || ctx.approver || "khal";
  const proxyHeaders = { "Content-Type": "application/json", ...principalProxyHeaders(actor) };
  try {
    if (name === "reopen_slot") {            // slot-scoped — works without an open review
      const r = await fetch(`${API}/slots/${args.slot_id}/reopen`, {
        method: "POST", headers: proxyHeaders, body: JSON.stringify({ actor }),
      });
      const j = await r.json().catch(() => ({}));
      return r.ok ? { ok: true, ...j } : { error: j.detail || r.statusText };
    }
    if (!ctx.gate_id) return { error: "No review is in progress on screen — start a review first." };
    if (name === "decide_on_slot") {
      const body = { approver_id: actor, decision: args.decision, slot_ids: [args.slot_id], notes: args.comment };
      const r = await fetch(`${API}/gates/${ctx.gate_id}/decide`, {
        method: "POST", headers: proxyHeaders, body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      return r.ok ? { ok: true, ...j } : { error: j.detail || r.statusText };
    }
    if (name === "submit_decisions") {
      const r = await fetch(`${API}/gates/${ctx.gate_id}/resolve`, {
        method: "POST", headers: proxyHeaders, body: JSON.stringify({ actor }),
      });
      const j = await r.json().catch(() => ({}));
      return r.ok ? { ok: true, ...j } : { error: j.detail || r.statusText };
    }
  } catch (e) {
    return { error: String(e) };
  }
  return { error: `unknown tool ${name}` };
}

export async function POST(req: NextRequest) {
  const { messages, context } = (await req.json()) as { messages: { role: string; content: string }[]; context: Ctx };
  if (!process.env.GROQ_API_KEY) return NextResponse.json({ error: "assistant is not configured (GROQ_API_KEY missing)" });
  // #194 — this route is authority-bearing (its tools decide/commit/reopen through the gate
  // engine). In IAM mode the acting principal is the validated session's bound principal with a
  // per-request current-binding revalidation — never the client-supplied context. Demo mode keeps
  // the existing demo trust model unchanged.
  let trustedActor: string | undefined;
  if (iamEnabled()) {
    const jar = await cookies();
    const session = readSession(jar.get(IAM_SESSION_COOKIE)?.value);
    if (!session) return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
    if (!session.principal_id) return NextResponse.json({ detail: "no operating identity assigned" }, { status: 403 });
    const binding = await revalidateBinding(session);
    if (binding === "unavailable") {
      return NextResponse.json({ detail: "identity check unavailable — try again" }, { status: 503 });
    }
    if (binding !== "ok") {
      const res = NextResponse.json(
        binding === "unbound" ? { detail: "access not configured" } : { detail: "reauthentication required" },
        { status: binding === "unbound" ? 403 : 401 },
      );
      res.cookies.delete(IAM_SESSION_COOKIE);
      return res;
    }
    trustedActor = session.principal_id;
  }
  const groq = new OpenAI({
    apiKey: process.env.GROQ_API_KEY,
    baseURL: process.env.GROQ_BASE_URL || "https://api.groq.com/openai/v1",
  });

  const sys =
    `You are the Tanaghom content-review assistant. You help a reviewer work the current queue and ` +
    `can act on their behalf through the review engine (the single source of truth). Use business ` +
    `language, never engineering terms ("gate", "resolve"). Be concise.\n` +
    `Current review: plan ${context?.round} (status: ${context?.round_phase}), stage "${context?.stage_label}", reviewer ${context?.approver}.\n` +
    `Plan stats: ${JSON.stringify(context?.round_stats || {})}\n` +
    `Items in review: ${JSON.stringify(context?.items || [])}\n` +
    `Awaiting regeneration: ${JSON.stringify(context?.awaiting || [])}\n` +
    `Dropped (recoverable): ${JSON.stringify(context?.dropped || [])}\n` +
    `Stage advisory: ${JSON.stringify(context?.stage_advisory || {})}\n` +
    `Reject = a reversible "drop" (recoverable), distinct from "send back for changes" (which regenerates). ` +
    `To restore a dropped item, call reopen_slot. A "send back"/"request change" ALWAYS needs a comment.\n` +
    `COMMITTING is a hard-floor HUMAN decision. PROACTIVELY recommend committing when the stage advisory ` +
    `says ready (cite the tallies) and WARN about any advisory warnings (pending/awaiting/coverage gaps). ` +
    `But only call submit_decisions when the human EXPLICITLY asks to commit — never auto-commit.\n` +
    `When asked to act, call the tools; then tell the reviewer what you did.`;

  const msgs: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
    { role: "system", content: sys },
    ...messages.map((m) => ({ role: m.role as "user" | "assistant", content: m.content })),
  ];

  try {
    for (let i = 0; i < 4; i++) {
      const completion = await groq.chat.completions.create({
        model: MODEL, messages: msgs, tools: TOOLS, tool_choice: "auto", temperature: 0.2,
      });
      const m = completion.choices[0].message;
      if (!m.tool_calls?.length) return NextResponse.json({ text: m.content || "" });
      msgs.push(m);
      for (const tc of m.tool_calls) {
        const args = JSON.parse(tc.function.arguments || "{}");
        const result = await execTool(tc.function.name, args, context, trustedActor);
        msgs.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify(result) });
      }
    }
    const fin = await groq.chat.completions.create({ model: MODEL, messages: msgs });
    return NextResponse.json({ text: fin.choices[0].message.content || "" });
  } catch (e) {
    return NextResponse.json({ error: `assistant error: ${String(e)}` });
  }
}
