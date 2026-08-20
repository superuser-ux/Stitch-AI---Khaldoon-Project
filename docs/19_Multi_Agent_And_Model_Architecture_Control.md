# Multi-Agent and Model Architecture Control

## Purpose
Make the intended agent runtime explicit in delivery control.

The repository already describes the product as an orchestrated system of humans, AI agents, and external executors. What is still too implicit is the implementation boundary between:

- the current development simplification
- the target operating architecture
- the concrete backlog slices required to move from one to the other without mixing UI work, runtime work, and governance work

This note makes that boundary explicit.

## Current Reality in This Repo

### Already explicit in the architecture
- `ARCHITECTURE.md` defines a unified actor model, pluggable executors, provider/model registries, capability matrices, and a user-facing Agent Rep.
- `docs/01_Blueprint_v2.md` defines the control plane as:
  - an orchestrator
  - a user-facing Agent Rep
  - specialist agents for planning, topics, scripts, production planning, editing, formatting, distribution, and analytics
- `db/migrations/006_unified_actor_seams.sql` already adds the correct long-term seams on principals:
  - `autonomy_level`
  - `capabilities`
  - `permissions`
  - `scope`
- `integrations/contracts.py` already defines the external executor seam cleanly.
- `system_config.example.yaml` already contains a provider registry and integration-provider structure.

### Still implicit or only partially implemented
- Runtime execution is still mostly a single-path implementation, not a true agent router.
- `gates/agent.py` proves the Agent Rep seam, but it is still one conversational layer backed by one configured model at a time.
- Stage generation is not yet driven by an explicit `task -> eligible agents -> eligible models -> required tools -> approval policy` selection flow.
- Observability shows actions and audit events, but not yet a first-class "why this agent/model/tool was selected" trace.
- UI work has already started to expose agentic concepts, but it can easily outrun the backend truth if the runtime contract stays implicit.

## Explicit Product Position

### Current dev-stage operating mode
For the current stage, it is acceptable that:
- one primary implementation path handles most AI generation
- the same model family may power multiple functions
- some specialist roles exist conceptually before they exist as separate runtime workers

This is a deliberate development simplification, not the target architecture.

### Target operating mode
The target system is a heterogeneous agent runtime where:
- one orchestrator owns workflow state, routing, retries, approval boundaries, and audit
- one user-facing Agent Rep translates human intent into orchestrator actions
- multiple specialist agents handle task-specific work
- each specialist agent can use:
  - the same model as another agent
  - a different remote API model
  - a local model
  - a CLI-driven capability
  - an MCP or external service
  - a non-LLM tool path when that is the right executor

This is a product differentiator, not an optional future embellishment.

## Architecture Rules That Must Stay Explicit

### 1. Agent, model, and tool are different things
- An agent is an operating role with instructions, allowed actions, and audit identity.
- A model is a compute option with strengths, costs, latency, modality, and availability characteristics.
- A tool or skill is an execution capability the agent may use.

Do not collapse these into one concept.

### 2. Routing is policy, not hardcoded branching
Task execution should be selected through data and policy:

`stage/task -> eligible agent roles -> eligible model/provider options -> eligible tools/skills -> approval/autonomy boundary`

This lets the system change provider, move work local, add specialist agents, or enforce different guardrails without rewriting core workflow logic.

### 3. The orchestrator must remain separate from creative specialists
- The orchestrator decides who should do work.
- Specialist agents do the work.
- The Agent Rep explains, requests, recommends, and acts within permission.

The orchestrator should not become a hidden writer, and the Agent Rep should not become an unbounded super-user.

### 4. Capability must be expressed on two planes

#### Agent capability plane
Per agent role, define:
- identity
- role/function
- ownership
- autonomy level
- allowed stages/tasks
- allowed tool/skill families
- approved model classes
- approval limits
- scope

#### Model/provider capability plane
Per model/provider entry, define:
- provider type
- endpoint/runtime shape
- modality support
- language/domain strength
- context limits
- latency/cost profile
- local vs remote location
- availability/failover state
- compliance or governance notes where relevant

Routing combines both planes.

### 5. Every execution decision needs traceability
For any meaningful execution, the system should be able to answer:
- which agent acted
- which model/provider was used
- which tool/skill chain was used
- why that path was selected
- what policy or constraint excluded alternatives
- who approved or overrode it if applicable

Without this, multi-agent language in the product remains decorative.

## Concrete Delivery Slices

### Slice A — Registry normalization
Define and normalize the data contracts for:
- principal/agent registry
- model/provider registry
- tool/skill registry
- routing policy definitions

Output:
- explicit schemas or config contracts
- documented distinction between agent capability and model capability

### Slice B — Task routing policy
Introduce a runtime selection layer that resolves:
- requested task or stage
- candidate agent roles
- candidate model/provider options
- required tools/skills
- guardrails and approval boundary

Output:
- deterministic selection logic
- readable fallback behavior
- test coverage for routing decisions

### Slice C — Execution adapters
Allow one selected agent role to execute through different backends:
- remote API model
- local model runtime
- MCP/tool chain
- CLI executor
- external integration contract

Output:
- one execution contract, many backend implementations

### Slice D — Observability and audit
Extend auditability from "what happened" to also include "why this runtime path happened".

Output:
- execution trace fields for agent/model/tool selection
- human-readable operator surfaces later

### Slice E — UI surfacing
Only after the runtime truth is explicit enough:
- roster/presence surfaces
- agent-first cowork mode
- tool/model visibility per agent
- live status and execution provenance

Output:
- UI reflects actual runtime state, not aspirational mock behavior

## Dependency Map to Existing GitHub Streams
- Issue `#11` agent-first cowork surface depends on this architecture being explicit enough to avoid false signaling.
- Issue `#10` approval identity hardening intersects with the principal and delegation model.
- Issue `#6` workflow governance/admin hardening intersects with who can assign, enable, disable, or constrain agent behavior.
- Future edit/distribution/analytics integrations depend on this architecture far more than current topic/script generation does.

## Recommended Delivery Position

### Priority
High, but not a same-day blocker for current review-surface stabilization.

### Why high
- It protects the product differentiator from becoming diluted into generic assistant behavior.
- It prevents UI work from advertising capabilities the runtime does not yet control.
- It gives future specialized generation, edit tooling, and analytics integrations a stable target.

### Why not the immediate blocker
- Current critical blockers remain review-flow stability, correctness, and clear stage behavior.
- The architecture work should run as a governed parallel stream, not interrupt stabilization unless a runtime decision depends on it.

## Explicit Non-Goal
This note does not say "split everything into many agents now."

The right sequence is:
1. stabilize the current workflow
2. make the target runtime contract explicit
3. introduce specialist runtime slices where specialization, tooling, latency, or governance actually justify them

## Outcome Required
This architecture is only "explicit enough" when all three are true:
- the repo has one clear control note for it
- GitHub has one owning umbrella issue for it
- future agent/UI/runtime issues reference it rather than re-describing the same intent ad hoc
