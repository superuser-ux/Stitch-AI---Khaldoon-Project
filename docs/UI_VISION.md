# UI/UX Vision (directional — reference only, NOT a committed decision)

The architecture (graph of stages, agents, directives, gates, telemetry, accumulating memory) makes a distinctive, system-honest UI both possible and warranted — the UI becomes the *expression* of the system, not a generic admin skin. This is a deliberate differentiator (InfraNodus-style network insight extended into a command-and-control center).

## Composition (the destination UI)
A combination of:
- **Standard admin & settings** panels (config, IAM/principals, registries/matrices).
- **AI-agent interaction**: conversational panels + channels (the copilot/twin; per-agent threads).
- **Command-and-control center**: act on the system — approve / escalate / reroute / inspect / pause.
- **2D / 3D visual map of the organization & flows**: the "brain firing" / "nervous system" metaphor — stages, agents, directives, handoffs, branches, rework loops as a live graph.
- **Live telemetry overlays + control**: status, throughput, bottlenecks, where humans are needed — overlaid on the map, actionable.

## Guiding principle
Rich viz must remain a **usable command-and-control surface** — every node/pulse/overlay maps to a real entity, event, or action. Operability + comprehension first; spectacle second. Act *through* the map, don't just watch it.

## Candidate tech (evaluate later)
- React + WebGL + **Three.js / react-three-fiber** for the 3D org-map; a graph lib (Cytoscape / sigma.js / react-flow) for 2D/control graphs.
- **cables.gl** (node-based WebGL) — noted by Kay; good for prototyping the visual language. Production control UI likely React + r3f + graph lib; cables.gl as a design/prototype aid. TBD.
- Kay has built similar UIs before (not via code) and will provide a specific prior build as a **reference** (record when shared).

## Staging (do NOT divert v1)
This is the eventual UI (Phase B/D), the full realization of M7 (living-operation) + graph-as-view + copilot panels. The current interim UI (shadcn + CopilotKit) is the functional bridge. The cheap-now data seams (first-class event log, attribution, graph-derivable state, telemetry) are exactly what this viz renders — so it becomes a render layer over existing data, not a rewrite. Build the substrate now; build the viz when we reach it.

## Concept reference — "AI Ops Nervous System" (Pencil mockup, 2D)
2D concept (Pencil, ~5 min from a reference image) materializing the M7 living-operation view. Maps directly onto the architecture — a RENDER over data we already build, no changes required:
- Node graph = stages; edges carry payloads = directives; actor annotations = actor model; color/intensity = live event stream; VISIBLE-SIGNALS toggles = operability via filtering.
- Selected-stage drawer (Human Review Gate: State/Input/Output/Policy/Open-trace/Escalate/Replay) = gate + directive + reviewer-disposition + hard-floor + time-travel.
- Two dashboards (Operational + System Health). Autonomy/rollback meters = autonomy guardrails. Error -> ASSIGNED TO REVIEW/RETRY DISABLED = recovery routing.
- "Replay 12s / Replay buffer" = event-sourced memory made visible -> validates keeping the event log first-class & complete.
Build later: manage cognitive load (filters + focus/zoom); animation serves legibility (2D control-graph first via react-flow/Cytoscape; 3D org-map optional); keep it a CONTROL surface. Status: directional reference (M7 destination); does NOT divert current M9 work.

## Multi-surface model — one system, many surfaces over a single spine
Surfaces are pluggable views/controls over the same spine (engine + directives + event log + IAM), gated by role/permissions:
1. Ops/Command center (M7) — full control + telemetry (operators/admins).
2. COP (view-only) — lobby display + filtered public website. = M7 render minus controls + redaction. Transparency + marketing. Needs config-driven redaction/filtering + tenant-scoping (curate the public slice; no sensitive content/PII).
3. Role-specific apps (e.g. the editor/AVP video app) — specialized co-creation surfaces. The AVP shows the SAME pattern on media: agent PROPOSES edits (trim/split) + Before/After + "valid — applies cleanly" (acceptance) + Accept/Reject (gate) + Directive log (event/memory).
Integration boundary = the directive contract (M9 seam): AVP consumes media_directive (approved script + production directions + raw assets), emits the finished edit -> org edit_review gate. Two consistent review levels: in-app co-creation + org edit_review. Each app/role = its own adapter to the SAME contract ("treated differently" = different adapters, same contract), decided when that stage is reached.
Why it's cheap: single engine + event log + directive contract + IAM/roles are exactly what make any surface (incl. unimagined ones) a projection, not a rebuild. Post-v1; does NOT divert current M9 work.
