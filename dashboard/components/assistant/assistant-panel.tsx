"use client";

import { ArrowUp } from "lucide-react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  AuiIf,
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { useReview } from "@/lib/review-context";

// A THIN chat over our own gate API (no vendor chrome): a custom ChatModelAdapter posts to
// /api/chat, which runs Groq with tools that drive the SAME engine as the buttons. assistant-ui
// only provides the primitives; the runtime/source-of-truth stays ours.
export function AssistantPanel() {
  const r = useReview();

  // Thin chat over the SINGLE agent endpoint (the same runtime the Telegram bot uses). The agent
  // re-derives state from the engine each call, so we send the latest user message scoped to the
  // current run + reviewer. It RECOMMENDS but never commits from free text (server hard floor).
  const adapter: ChatModelAdapter = {
    async run({ messages, abortSignal }) {
      const lastUser = [...messages].reverse().find((m) => m.role === "user");
      const text = (lastUser?.content as { type: string; text?: string }[] | undefined)
        ?.filter((p) => p.type === "text").map((p) => p.text).join("\n") ?? "";
      if (!r.round) return { content: [{ type: "text", text: "Select a run first, then ask me about it." }] };
      const artifact = r.stage.key === "topic" || r.stage.key === "script" ? r.stage.key : undefined;
      let res: Response;
      try {
        res = await fetch(`/gw/rounds/${r.round}/agent`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, artifact }), signal: abortSignal,
        });
      } catch {
        return { content: [{ type: "text", text: "Agent unavailable — the rest of the dashboard still works." }] };
      }
      if (!res.ok) {
        const msg = res.status === 503
          ? "Agent unavailable (not configured) — the dashboard still works."
          : `Agent error (${res.status}).`;
        return { content: [{ type: "text", text: msg }] };
      }
      const data = await res.json().catch(() => ({ reply: "(no response from the assistant)" }));
      r.refresh().catch(() => {});   // an agent action may have changed engine state
      return { content: [{ type: "text", text: data.reply || data.error || "" }] };
    },
  };
  const runtime = useLocalRuntime(adapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
        <ThreadPrimitive.Viewport className="flex flex-1 flex-col gap-3 overflow-y-auto p-3">
          <AuiIf condition={(s) => s.thread.isEmpty}>
            <p className="text-xs text-muted-foreground">
              Ask about the queue or act — e.g. “what’s awaiting me?”, “approve all parenting topics”,
              “send back R3-D02-AM: not Palestinian dialect”.
            </p>
          </AuiIf>
          <ThreadPrimitive.Messages>
            {({ message }) =>
              message.role === "user" ? <UserMsg /> : <AssistantMsg />
            }
          </ThreadPrimitive.Messages>
          <ThreadPrimitive.ViewportFooter className="sticky bottom-0 pt-2">
            <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border bg-muted p-1.5">
              <ComposerPrimitive.Input data-testid="assistant-input" rows={1}
                placeholder="Message the assistant…"
                className="min-h-8 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm focus:outline-none" />
              <ComposerPrimitive.Send className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground disabled:opacity-30">
                <ArrowUp className="size-4" />
              </ComposerPrimitive.Send>
            </ComposerPrimitive.Root>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

function UserMsg() {
  return (
    <MessagePrimitive.Root className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl bg-primary px-3 py-2 text-sm text-primary-foreground">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}
function AssistantMsg() {
  return (
    <MessagePrimitive.Root className="flex justify-start">
      <div dir="auto" className="max-w-[85%] rounded-2xl bg-secondary px-3 py-2 text-sm">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}
