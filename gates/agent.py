"""The conversational AGENT layer (M6 first instance) — natural-language driving of the SAME gate
engine, ADDITIVE over the structured Telegram surface.

The agent's capabilities ARE the contract verbs in `contract.py` (one clean tool boundary): plan /
query status, approve / request-change-with-comment / reject / restore / reopen, iterate (rework),
and RECOMMEND committing — but it NEVER commits without explicit human authorization (the
`allow_commit` gate = the Unified Actor Model hard floor; the agent proposes, the human commits).
Every action goes through the engine and is audited + attributed there.

The LLM is injectable (`run(..., llm=...)`) so the loop is testable offline with a scripted stand-in;
the production client is Groq (OpenAI-compatible), model config-driven (`surfaces.telegram_agent`).
Bilingual (Palestinian Arabic + English). Swappable to the client's own agent later (same contract).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import contract as C  # noqa: E402
from agents import runtime_secret  # noqa: E402

MAX_ITERS = 6

# Tool schema (OpenAI function-calling shape) for the production LLM. The scripted test LLM ignores
# this and returns pre-planned steps. `commit` is advertised but hard-floored in dispatch.
TOOL_SPECS = [
    {"type": "function", "function": {"name": "status", "description":
     "Get the status of a content round: its phase and the topic/script stage states. Read-only.",
     "parameters": {"type": "object", "properties": {"round_id": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "digest", "description":
     "Open/load the current review and return its summary: tallies, by-pillar, flags, and each item.",
     "parameters": {"type": "object", "properties": {"artifact": {"type": "string", "enum": ["topic", "script"]}}}}},
    {"type": "function", "function": {"name": "approve", "description":
     "Approve one or more items (omit slot_ids to approve the whole batch). Recorded, not advanced.",
     "parameters": {"type": "object", "properties": {"slot_ids": {"type": "array", "items": {"type": "string"}}}}}},
    {"type": "function", "function": {"name": "request_change", "description":
     "Send an item back for regeneration WITH a comment (the comment guides the rewrite). Needs a comment.",
     "parameters": {"type": "object", "properties": {"slot_id": {"type": "string"},
                    "comment": {"type": "string"}}, "required": ["slot_id", "comment"]}}},
    {"type": "function", "function": {"name": "reject", "description":
     "Drop an item (reversible/recoverable). Distinct from sending back for changes.",
     "parameters": {"type": "object", "properties": {"slot_id": {"type": "string"},
                    "reason": {"type": "string"}}, "required": ["slot_id"]}}},
    {"type": "function", "function": {"name": "undecide", "description":
     "Undo a recorded decision on an item before committing (back to pending).",
     "parameters": {"type": "object", "properties": {"slot_id": {"type": "string"}}, "required": ["slot_id"]}}},
    {"type": "function", "function": {"name": "rework", "description":
     "Regenerate the round's sent-back items in this stage (applies the reviewer comments).",
     "parameters": {"type": "object", "properties": {"artifact": {"type": "string", "enum": ["topic", "script"]}}}}},
    {"type": "function", "function": {"name": "revisions", "description":
     "List the version history of an item.",
     "parameters": {"type": "object", "properties": {"slot_id": {"type": "string"}}, "required": ["slot_id"]}}},
    {"type": "function", "function": {"name": "restore", "description":
     "Restore an older version of an item as the new head and send it back for re-review.",
     "parameters": {"type": "object", "properties": {"slot_id": {"type": "string"},
                    "revision": {"type": "integer"}}, "required": ["slot_id", "revision"]}}},
    {"type": "function", "function": {"name": "reopen", "description":
     "Restore a dropped item (or reverse an approval) back into review.",
     "parameters": {"type": "object", "properties": {"slot_id": {"type": "string"}}, "required": ["slot_id"]}}},
    {"type": "function", "function": {"name": "dropped", "description": "List the round's dropped (recoverable) items.",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "awaiting", "description":
     "List the round's items awaiting regeneration, with the reviewer comment.",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "commit", "description":
     "Advance the approved items to the next stage. HUMAN-CONFIRMED ONLY — recommend it, never do it unasked.",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "generation_status", "description":
     "Observe the automatic Topic-generation run for this round: overall state (queued/running/done/"
     "failed/partial), how many topics were produced, and per-slot results. Read-only — for reporting "
     "and recommending; you cannot start or retry generation yourself.",
     "parameters": {"type": "object", "properties": {}}}},
]


def _system_prompt(ctx, allow_commit):
    return (
        "You are the Tanaghom content-review assistant on Telegram. You help the reviewer work the "
        "current queue and can act on their behalf through the review engine (the single source of "
        "truth — every action is audited). Use business language, never engineering terms (no "
        "'gate'/'resolve'/'quorum'). Be concise. Reply in the reviewer's language — Palestinian "
        "Arabic or English — matching how they wrote.\n"
        f"Current context: round {ctx.get('round_id')}, stage '{ctx.get('artifact')}', reviewer "
        f"{ctx.get('actor')}.\n"
        "Reject = a reversible DROP (recoverable via restore), distinct from 'send back for changes' "
        "(which regenerates from your comment). A send-back ALWAYS needs a comment.\n"
        "PROACTIVELY recommend committing when the stage advisory says it's ready (cite the tallies) "
        "and WARN about pending items, coverage gaps, or items awaiting regeneration. "
        + ("The reviewer has authorized committing this turn — you may commit if they asked.\n"
           if allow_commit else
           "COMMITTING IS A HARD-FLOOR HUMAN DECISION — you may recommend it, but you must NOT commit "
           "yourself; tell the reviewer to tap Commit / confirm explicitly.\n")
        + "When asked to act, call the tools; then tell the reviewer plainly what you did.\n"
        "If a tool result has unavailable: true, do NOT improvise or retry — relay its next_step "
        "to the reviewer in plain business language."
    )


# #144 (contract #143 / inventory #130) — structured unavailable-action fallback. Blocked or
# unavailable actions return ONE predictable shape instead of improvised error text, so both
# surfaces (dashboard panel, Telegram) can render a consistent, testable message and the LLM
# relays a concrete next step. reason_class ∈ not_exposed | human_confirm_required |
# not_authorized | dependency_unavailable.
def _unavailable(action, reason_class, next_step):
    return {"unavailable": True, "action": action, "reason_class": reason_class,
            "next_step": next_step}


# Actions operators ASK FOR but which are deliberately not agent-exposed (see the #130 binding
# matrix: workspace-scoped or cost-bearing actions stay human-driven until an explicit binding).
_NOT_EXPOSED = {
    "plan_run": "Run creation is a workspace action — plan the run from the dashboard (New run).",
    "create_run": "Run creation is a workspace action — plan the run from the dashboard (New run).",
    "generate": "Starting generation spends provider budget — use the stage's Generate button in the dashboard.",
    "generate_topics": "Starting generation spends provider budget — use the stage's Generate button in the dashboard.",
    "generate_scripts": "Starting generation spends provider budget — use the stage's Generate button in the dashboard.",
    "retry_generation": "Retrying Topic generation spends provider budget — use the round's Retry control "
                        "in the dashboard, which confirms and attributes it to you (the same binding).",
    "retry_topics": "Retrying Topic generation spends provider budget — use the round's Retry control "
                    "in the dashboard, which confirms and attributes it to you (the same binding).",
    "approval_policy": "Approval policies are owner-administered — edit them under Admin in the dashboard.",
    "update_policy": "Approval policies are owner-administered — edit them under Admin in the dashboard.",
    "workflow": "Workflow definitions are owner-administered — edit them under Admin in the dashboard.",
}


def _classify_error(name, msg, ctx):
    """#144 — map a blocked-action error message to the structured fallback, or None if the
    message is ordinary workflow feedback the model should see verbatim (e.g. a missing comment).
    Used for BOTH raised exceptions and the contract layer's caught `{error: ...}` results —
    the contract already swallows engine.GateError, so classification must run on results too."""
    if "not configured" in msg or "hard-floor" in msg or "hard floor" in msg:
        return _unavailable(name, "not_authorized",
                            f"{ctx.get('actor')} is not an assigned approver for this stage — "
                            "an assigned reviewer must act, or the owner can update the "
                            f"approval policy. ({msg})")
    if "unavailable" in msg or "503" in msg:
        return _unavailable(name, "dependency_unavailable",
                            "That capability's backing service is unavailable right now — "
                            f"try again shortly or tell the operator. ({msg})")
    return None


def _dispatch(name, args, ctx, allow_commit):
    res = _dispatch_call(name, args, ctx, allow_commit)
    if isinstance(res, dict) and set(res.keys()) == {"error"}:
        classified = _classify_error(name, str(res["error"]), ctx)
        if classified is not None:
            return classified
    return res


def _dispatch_call(name, args, ctx, allow_commit):
    rid = args.get("round_id") or ctx.get("round_id")
    art = args.get("artifact") or ctx.get("artifact")
    actor = ctx.get("actor")
    try:
        if name == "status":
            return C.plan_round(args.get("round_id") or ctx.get("round_id"))
        if name == "stage_state":
            return C.stage_state(rid, art)
        if name == "digest":
            return C.digest(rid, art, actor=actor)
        if name == "approve":
            return C.approve(rid, art, args.get("slot_ids"), actor=actor)
        if name == "request_change":
            return C.request_change(rid, art, args.get("slot_id"), args.get("comment", ""), actor=actor)
        if name == "reject":
            return C.reject(rid, art, args.get("slot_id"), actor=actor, reason=args.get("reason"))
        if name == "undecide":
            return C.undecide(rid, art, args.get("slot_id"), actor=actor)
        if name == "rework":
            return C.rework(rid, art, dry_run=bool(args.get("dry_run")))
        if name == "revisions":
            return C.revisions(args.get("slot_id"), art)
        if name == "restore":
            return C.restore(args.get("slot_id"), art, args.get("revision"), actor=actor)
        if name == "rework_from":
            return C.rework_from(args.get("slot_id"), art, args.get("revision"), args.get("comment", ""), actor=actor)
        if name == "reopen":
            return C.reopen(args.get("slot_id"), actor=actor)
        if name == "dropped":
            return C.dropped(rid)
        if name == "awaiting":
            return C.awaiting(rid)
        if name == "commit":
            if not allow_commit:           # HARD FLOOR — the agent may never self-commit
                return _unavailable("commit", "human_confirm_required",
                                    "Committing advances the batch and is a human decision — "
                                    "tap Commit in the dashboard (or confirm explicitly).")
            return C.commit(rid, art, actor=actor, confirmed=True)
        if name == "generation_status":    # #310 §F — OBSERVE only (read model); no start/retry here
            return C.topic_generation(rid)
    except Exception as e:                 # noqa: BLE001 — surface, never crash the chat
        # blocked-action classes get the structured shape; anything else is actionable workflow
        # feedback (e.g. "request_change needs a comment") the model should see verbatim.
        classified = _classify_error(name, str(e), ctx)
        return classified if classified is not None else {"error": str(e)}
    if name in _NOT_EXPOSED:
        return _unavailable(name, "not_exposed", _NOT_EXPOSED[name])
    return _unavailable(name, "not_exposed",
                        "I can't do that from here — it isn't one of my review actions. "
                        "Ask me to review, approve, send back, drop, restore, or regenerate items.")


def run(messages, ctx, llm=None, allow_commit=False, max_iters=MAX_ITERS):
    """Drive the conversation: the LLM may call contract tools; results feed back until it replies.
    `messages` = [{role, content}]. Returns {text, tool_results}. `llm` is injectable for tests."""
    llm = llm or build_llm()
    system = _system_prompt(ctx, allow_commit)
    convo = [dict(m) for m in messages]
    tool_results = []
    text = ""
    for _ in range(max_iters):
        step = llm.step(system, convo, TOOL_SPECS) or {}
        calls = step.get("tool_calls")
        if not calls:
            text = step.get("text") or ""
            break
        convo.append({"role": "assistant", "content": step.get("text") or "", "tool_calls": calls})
        for c in calls:
            args = c.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {}
            res = _dispatch(c.get("name"), args, ctx, allow_commit)
            tool_results.append({"name": c.get("name"), "result": res})
            convo.append({"role": "tool", "tool_call_id": c.get("id"), "name": c.get("name"),
                          "content": json.dumps(res, ensure_ascii=False, default=str)})
    return {"text": text, "tool_results": tool_results}


# --------------------------------------------------------------------------- #
# Production LLM — Groq (OpenAI-compatible), model config-driven. Not exercised by the offline test.
# --------------------------------------------------------------------------- #
def agent_cfg(cfg=None):
    cfg = cfg or C._cfg()
    return ((cfg.get("surfaces") or {}).get("telegram_agent") or {})


def build_llm(cfg=None):
    from openai import OpenAI
    ag = agent_cfg(cfg)
    model = (os.environ.get("TELEGRAM_AGENT_MODEL") or ag.get("model")
             or os.environ.get("COPILOT_MODEL") or "llama-3.3-70b-versatile")
    client = OpenAI(api_key=runtime_secret.resolve("GROQ_API_KEY")[0],
                    base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    return _GroqLLM(client, model, float(ag.get("temperature", 0.2)))


class _GroqLLM:
    """Adapts our (system, convo, tools) step protocol to a Groq chat-completions call."""
    def __init__(self, client, model, temperature=0.2):
        self.client, self.model, self.temperature = client, model, temperature

    def step(self, system, convo, tools):
        msgs = [{"role": "system", "content": system}]
        for m in convo:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                msgs.append({"role": "assistant", "content": m.get("content") or "",
                             "tool_calls": [{"id": c.get("id"), "type": "function",
                                             "function": {"name": c.get("name"),
                                                          "arguments": json.dumps(c.get("arguments") or {})}}
                                            for c in m["tool_calls"]]})
            elif m.get("role") == "tool":
                msgs.append({"role": "tool", "tool_call_id": m.get("tool_call_id"), "content": m.get("content")})
            else:
                msgs.append({"role": m["role"], "content": m.get("content") or ""})
        resp = self.client.chat.completions.create(
            model=self.model, messages=msgs, tools=tools, tool_choice="auto", temperature=self.temperature)
        m = resp.choices[0].message
        if not m.tool_calls:
            return {"text": m.content or ""}
        return {"text": m.content or "",
                "tool_calls": [{"id": tc.id, "name": tc.function.name,
                                "arguments": json.loads(tc.function.arguments or "{}")}
                               for tc in m.tool_calls]}
