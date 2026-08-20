# Tanaghom — Architecture & Governing Principles (explicit)

> ## NORTH STAR — this is a SYSTEM, not an application.
> A living, integrated whole that is *operated and steered*, not merely *used*: humans, AI agents, and external services interoperating via contracts, over an orchestration + approval + memory spine — with state, history, and behavior that evolves over time. Every decision serves 'system' over 'app': **seams over screens, interoperability over features, evolution over fixed spec, observability/memory over static CRUD, participants over users, a simple core + pluggable enablers.** The UI is therefore a command-and-control + living-map surface, not generic forms.

The single, explicit statement of how this system is modeled. Detailed milestones, fixes, and notes live in `BUILD_STATE.md`; this is the durable frame they all serve.

## The overarching frame — one system, three views (+ memory)
The platform (and later the organization) is modeled as an **event-sourced temporal graph governed by a state machine**:
- **State machine** — the dynamics: valid transitions / approvals (the gate engine).
- **Graph** — the structure: a snapshot of nodes (items, agents, stages, decisions, principals) and edges (transitions, with weights) at any instant.
- **Event log** — the history: an append-only stream of every transition, from which any past graph snapshot is **derivable by replay**. This history **is the organization's memory** (episodic via attribution; semantic via embeddings over decisions/content/outcomes).

**Dual representation (the key discipline):** relational tables = current-state read model (fast, transactional, correct); append-only event log = history/memory/graph-projection. Current-state for correctness; event log for memory & time-travel. Derive snapshots by replay; don't hoard them. Do NOT rewrite the transactional core into a graph DB or full CQRS — adopt the model + the cheap seams, defer the heavy machinery until queries/scale demand it.

## Git for content — reversible decisions + batch-commit checkpoints
Direct consequence of the event-sourced frame: **nothing is ever destroyed; every state is recoverable.** Versions, decisions, and transitions are immutable append-only events (memory); the *current state* is a movable pointer over them — like git.
- **Reject is reversible, not terminal.** A reject moves the item to a dedicated, recoverable `REJECTED` ("dropped") state — excluded from the active batch / review / regeneration, but **revocable** (`reopen` / un-reject → back to the review status for re-review). It is **distinct from request-change** (which iterates via regeneration) and they never overlap: request-change → `CHANGES_REQUESTED` → regenerate; reject → `REJECTED` → restore. Both are "parked" (excluded + not approvable); both recover, by different means.
- **Decisions are reversible.** Pre-commit: `undecide` (clear a recorded decision → pending). Post-commit: `reopen` reverses a committed reject (un-reject) or approval (un-approve), moving the item back to the review of its *latest decision*. The pointer moves; the prior decision events remain — every reversal is itself a new audited event (actor + timestamp).
- **Batch commit = explicit, human-confirmed checkpoint (not a cliff).** Per-item decisions are recorded but DON'T advance anything; a deliberate **"Commit batch → advance to next stage"** (the engine's `resolve`) is the checkpoint: it advances APPROVED items (their output directive emits — the handoff), parks sent-back/dropped items (recoverable), and is itself an audited event. **Post-commit everything REMAINS and is RECOVERABLE** (`reopen`). Versions (`restore`/`rework-from vN`) follow the same append-only, linear rule.
- **AI advisory, human commit (autonomy hard-floor).** A read model (`stage_state`) computes the stage's lifecycle state (ready_to_start / reviewing / ready_to_commit / awaiting_regeneration / complete / empty) + an **advisory**: a proactive *recommendation* when ready (with tallies) and *warnings* on edge cases (items still pending → excluded; coverage gaps from drops; nothing-advances). The agent/assistant **recommends and warns but never auto-commits** — committing is a hard-floor human gate (per the Unified Actor Model); the assistant can surface the suggestion and execute only on explicit human confirmation. The surface therefore never errors on a normal condition (nothing pending) — it shows the contextual state + the commit affordance.
- **Discipline:** reversals mutate the current-state *pointer* (relational tables) for correctness, while the audit_log keeps the full event history (`looped_back`, `reopened`/`un_rejected`/`un_approved`, `decision_cleared`, `gate_decision`, `gate_resolved`, `approved_revision`, `revision_restored`) — so traceability and time-travel are intact. Config-driven (`gates.<stage>.reject_to` / `changes_to`); no hardcoded terminal states.

## Governing principles
1. **Nothing hardcoded** — every changeable value in config/env/DB, UI-manageable; no-hardcode audit each milestone.
2. **Platform, not app** — decoupled modules over shared platform services; multi-tenant / multi-department ready (tenant/module scoping now; defer the framework). Maintain seams, defer machinery.
3. **Unified Actor Model + policy-driven autonomy** — humans, AI agents, agent reps, guests = one principal spine with separate axes: capabilities (tools) / permissions (allowed) / autonomy (how independent) / scope. Behavior = f(autonomy × stage-policy × permissions). Guardrails: default-low autonomy, hard floors (publish/spend/religious keep a human gate), no self-escalation, human override, full audit.
4. **Graph as a VIEW** over the relational+state-machine core (not the store) — control graph (M7), methodology coverage/insight, provenance/lineage; define edge-weight semantics per use-case.
5. **Single engine = single source of truth** — dashboard, Telegram, CLI, copilot, guest links all call the same gate engine; n8n stays out of the approval path (it's for distribution/integration).
6. **Bilingual content, business-lexicon UI** — content (topics/hooks/scripts/justifications/comments) bilingual AR(Palestinian)/EN; UI chrome English-only for now via i18n; never expose code/DB terms to users.
7. **Human-in-the-loop, staged** — topics approved before scripting; reviews are reviewer-disposed suggestions (escalate/waive), not hardwired; co-creation loop (comment → regenerate → revision history).
8. **Leverage skills/plugins/MCPs & verify versions** — use the best-fitting existing capability (don't reinvent); check component versions + current docs (context7) before writing code/config.

## How the roadmap layers on this frame
- Gates = the **state machine** (built). Event log + attribution = the **memory seam** (~80%, finish it).
- Graph view = **M7** living-operation. Semantic memory = embeddings over decisions/outcomes (extends the topic ledger) → powers the **M6 copilot** and the analytics loop.
- Each milestone is a layer on the same frame, not a new architecture.

## Consistency with the original diagram (traceability)
The build is consistent with `docs/Tanaghom high level workflow content dept Diagram.drawio.svg`. Mapping:
- Methodology 5P×42HS → CANON-010..015 (built). Main Agent/Orchestrator → gate engine spine (built). LLM Models A–E/1–2 → config-driven provider/model registry + capability matrix (built). Human-in-the-Loop → uniform gate/review (built). User AI Agent/Agent rep → copilot/M6 (CopilotKit interim, swappable via MCP — matches "integrates with user's own agent"). POSTIZ→SM Platforms → gated distribution executor. Tooling (Local/Remote) → multi-node providers (3090/RTX6000/Ollama + Groq/Gemini).
- Content Strategy/Production Plan, Production (physical)+Raw Cuts, AI/Human Co-EDITS, SDA/DAM, Smart Analytics Repo/Own KPIs → designed/roadmapped (M9 + post-v1 integrations: AVP for edits, POSTIZ for publish, user's analytics system interfaced). Intent matches the diagram.
- Beyond the diagram (compatible evolution): event-sourced temporal graph + state machine + memory frame; Unified Actor Model + autonomy; multi-tenant/platform; IAM/principals; staged topic→script + co-creation + reviewer-disposition; capability matrices; LoRA/local nodes; graph/living-operation (formalizes the diagram's agents+humans interacting).
- Nothing in the diagram is contradicted or dropped.

## Inter-stage handoff = directive propagation (the integration contract)
The pipeline is a GRAPH of stage handoffs (branching + loops), not a flat line. Stages interoperate via a structured **directive package**, not just the artifact — this is the stable seam that lets heterogeneous executors (AI agents / humans / external systems: AVP, POSTIZ, analytics) plug in regardless of integration shape (API/MCP/file/manual).

**Directive package (versioned; content fields bilingual):**
- intent — what this stage must achieve
- inputs — refs to upstream artifacts (script, raw assets) in store/DAM
- parameters/controls — knobs (format, platform targets, length, lens, dialect, style)
- constraints/guardrails — must/never (brand, religious, dialect, platform specs, hard floors)
- acceptance_criteria — what "approved/done" means (what the gate checks)
- context/provenance — methodology refs (pillar/HCS/lens), upstream decisions, attribution

**Mechanism:** each stage declares the input directive it accepts + the output directive it emits. Executor reads directive → works with that stage's tooling/skills/agents/services → emits artifact + next-stage directive. Directives accumulate/refine down the chain (methodology → strategy → topic → script + production directions → edit directives → platform/format specs → distribution).

**Consequences:**
- Integration independence: outside systems only implement the directive contract; shape can vary.
- Gate = "does output satisfy the incoming directive's acceptance_criteria?" (review and directives share one language).
- Branching/loops are graph edges; request-change comment IS a directive back to the agent (co-creation = directive propagation in miniature).
- Edges carry directives; event log records every handoff = memory. Autonomy operates within a directive's constraints; actor model decides the executor.

**Scope:** define the schema concretely + minimally for current stages + AVP/POSTIZ/analytics seams; version it; let it grow. Do NOT build a universal directive DSL up front. This is the core of M9 (stage generalization). Seed already exists: approved topic = directive into script stage; script stage emits production directions.

## Nuances — edge direction & multi-approval
- Directives flow FORWARD along edges; **reviews/rejections flow BACKWARD (rework to a prior stage) or SIDEWAYS (parallel reviewer/branch).** Edges are multi-directional.
- **Multi-approval = extra approval stages**, not a special case. N approvers = N review nodes (sequential or parallel) on the graph.
- **Core is simple; the rest are enablers.** Core = graph of stages + pluggable executors + directives + gates + event-log/memory. Enablers (IAM/admin, model/agent/tool registries & matrices, config, DAM, i18n/UI, copilot) make the core deliver consistently (governance/attribution/guardrails) and flexibly (swappable executors, tunable params) — they serve the structure, they are not it.

## n8n's role — decoupled integration & automation plane (peripheral nervous system)
n8n is NOT the spine. The code core (gate engine, directives, event log/memory, graph) is the source of truth. n8n lives at the edges.
**Use for:** implementing integration seams as connector-glue (POSTIZ publish, analytics ingest, notifications) = one valid shape of a pluggable executor; scheduling/triggers/side-effects/fan-out; **event-driven reactions** off the event log (core emits events → n8n subscribes & acts); non-dev-editable automations; rapid integration prototyping.
**Never:** the gate/approval state machine; source of truth for state; the memory/event-log owner; business-critical directive logic; deep branching/long-running stateful flows.
**Decoupled but governed:** n8n acts ONLY on approved state (triggered by core events; never bypasses gates), and records actions back as events with attribution (memory/graph stay whole). Each workflow = a registered tool/capability node, swappable, contract-bound.
**Discipline:** glue, not logic. If a flow needs real branching/state/correctness → codify it. Don't let n8n become a shadow system.
**Placement:** M9 DEFINES the contracts (code); Phase C IMPLEMENTS some via n8n (POSTIZ/analytics/notifications), managed via the n8n MCP. NOT part of the M9 core engine. (Native nodes + version/context7 checks per BUILD_STATE.)
