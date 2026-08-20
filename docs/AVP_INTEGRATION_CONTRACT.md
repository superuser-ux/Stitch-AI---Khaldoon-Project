# AVP (Agentic Video Producer) — Integration Contract (reference; post-v1)

Source: read-only review of the AVP repo (`Agentic-Video-Producer`). AVP fills Tanaghom's **media-edit stage** (declared `generator: external` seam in M9/B2). This documents the boundary so the eventual wiring is a thin adapter, not a retrofit.

## Why it's a thin adapter — shared first principles
AVP is built on the SAME core ideas as Tanaghom:
- **Single mutation/directive path** — every edit (human-UI or agent) is one `Directive` via `applyDirective()`; no separate human-vs-agent path. = Tanaghom single engine + event log.
- **`EditProposal` distinct from an applied `Directive`** — never applied until accepted; acceptance produces a Directive; carries `rationale`, `suggestedDirective`, `informedBy`, `status`, staleness baseline. = Tanaghom propose→review→accept + provenance + reviewer-disposition.
- **Directive log = undo/redo + audit + replay.** = Tanaghom event-sourced memory.
- **MCP server is the external interface** (`get_timeline`, `import_media`, `register_asset`, `add/insert/split/trim/move/set_clip…`, `propose_edit`, `get_proposals`, `accept_proposal`, `reject_proposal`). = Tanaghom integration seam.
- **Async generation** (GenerationMetadata: pending→generating→completed→failed; backends comfyui/hosted-api/manual). Fits Tanaghom's long-running gate model.

## The contract: Tanaghom media-edit StageExecutor = an MCP CLIENT to AVP's MCP server
```
Tanaghom edit stage (generator: external)
  -> media_directive (approved script + production directions) + raw assets
  -> AVP MCP: import_media / register_asset   (seed the AVP project)
  -> AVP creative-director agent: propose_edit (in-app co-creation: editor accept/reject_proposal)
  -> finished edit: get_timeline + rendered output (DAM asset ref)
  -> back to Tanaghom edit_review gate
```
Two consistent review levels: in-app (AVP proposals) + org (Tanaghom edit_review).

## Concept mapping (Tanaghom <-> AVP)
| Tanaghom | AVP |
|---|---|
| directive (stage handoff) | media_directive seeds the AVP project |
| agent proposes + gate | EditProposal + accept/reject_proposal |
| event log / memory | directive log |
| single engine (applyDirective) | applyDirective() |
| integration seam (StageExecutor) | MCP server |
| reviewer disposition | "semantic staleness = human judgment" |

## What `media_directive` must carry / what comes back
- IN: raw assets (refs), the approved script + production directions, slot/provenance ids, acceptance criteria.
- OUT: rendered output (DAM asset ref) + optionally the EDL / directive-log (provenance).

## Reconcile when wiring (decisions for later)
1. **Terminology collision** — both use "directive"/"proposal" at DIFFERENT scopes (Tanaghom = stage brief; AVP = edit op). They NEST. Name the boundary clearly so layers never blur.
2. **Handoff artifact** — confirm the exact object edit_review reviews (rendered asset + optional EDL).
3. **Async** — the StageExecutor polls AVP generation/job status (long-running gate).
4. **Cross-system provenance** — link Tanaghom `slot` <-> AVP `project` so memory stays whole across the boundary.

## Scope
Post-v1. AVP is in its own repo (independent product). Tanaghom's side = a documented MCP-client adapter at the media-edit StageExecutor; no core change. Confirms M9's edit seam is correctly shaped.
