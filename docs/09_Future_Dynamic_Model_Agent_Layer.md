# Future: Dynamic Model & Agent Capability Layer (roadmap note)

**Status:** direction, not yet built. Recorded so current choices stay forward-compatible.
**Why here:** today's static `system_config.yaml` (provider registry + per-stage `primary`/`fallback`) is the seed of this layer. This note defines what it grows into.

## The two matrices
1. **Model Capability Matrix** — one row per available model/provider, scored on:
   `quality` (per task type), `dialect_fidelity` (ar-PS specifically), `latency`, `throughput`,
   `cost_per_1k`, `context_window`, `json_reliability`, `privacy` (local vs remote), `availability/quota`.
   Refreshed periodically by automated probes (e.g. the 3-hook dialect bake-off as a recurring eval)
   + manual native-reviewer scoring.
2. **Agent Capability Matrix** — one row per agent/role (Planner, Topic/Hook, Script, Edit, etc.),
   declaring required capabilities, min quality bar, max cost, privacy constraints, and preferred modalities.

## Selection logic (the "dynamic layer")
A selection skill reads both matrices + the task context and picks the model per call by a weighted
objective (quality × dialect_fidelity for hooks; cost/throughput for bulk; privacy where required),
with automatic fallback when a node is rate-limited or down. This replaces static `primary/fallback`
with matrix-driven routing — without changing the agents.

## Extends to tools / MCP servers / services
The same registry+matrix pattern covers more than models:
- **Tool / MCP Capability Matrix** — one row per tool/MCP server/API service (e.g. POSTIZ, transcription,
  image/video gen, analytics connectors), scored on: capability/coverage, cost, latency, rate limits,
  reliability/uptime, auth & privacy, region/residency.
- The selector then routes *any* capability call — model, agent, or tool — by the same weighted objective
  with fallback. A "generate image" or "publish post" request picks the best available service the same way
  a "write hook" request picks the best model.
- Keep tool/service access behind a uniform interface (like the OpenAI-compatible provider pattern) so new
  MCP servers/APIs are config/data rows, not code.

## Multi-node providers
Providers are nodes, not just APIs:
- **RTX 3090 workstation** — local Ollama (gemma4, embeddings, Whisper).
- **RTX 6000 box** — Qwen + other/own models (higher capacity workhorse).
- **Cloud APIs** — Gemini / Claude / others for top-tier or burst.
The registry already abstracts these behind the OpenAI-compatible interface; new nodes = config rows.

## Integration with skills
Skills carry task-specific know-how (e.g. "Palestinian hook writing", "carousel tooling"); the matrices
decide *which model* executes a skill. Skills + matrices together = capability-aware orchestration.

## Forward-compatibility checklist (keep true as we build)
- [ ] Model selection stays 100% in config/data — never hardcoded.
- [ ] Provider interface stays uniform (OpenAI-compatible) so any node is swappable.
- [ ] Per-stage params (temperature, reasoning_effort, max_tokens) are passthrough, not baked in.
- [ ] Every generation logs which model/node served it (for the matrix's quality/cost feedback).
- [ ] The recurring dialect eval (3-hook bake-off) can run headless to refresh scores.

## When to build it
After Phase 1 (proof) and once 2+ model nodes are in regular use (3090 + RTX 6000). Until then,
static config + manual bake-offs are sufficient and faster.
