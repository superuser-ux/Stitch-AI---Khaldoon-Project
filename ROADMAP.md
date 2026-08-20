# Tanaghom — Consolidated Roadmap

See `ARCHITECTURE.md` for the model; `BUILD_STATE.md` for the working log. This is the aligned plan.
Current shared client/internal status baseline: `docs/14_Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.md`, issue `1.2` dated `July 2, 2026`.

## Essence
A graph of stages; each stage = a transform with a pluggable executor (AI / human / external). Directives flow forward; reviews/rejections flow back/sideways; gates check output vs directive; multi-approval = extra review stages; every transition is an event → the log is memory. Enablers (IAM, registries/matrices, config, DAM, UI, copilot) make this simple core consistent + flexible.

## Status
- **Built:** M1 foundation+methodology · M2 planner (no-repeat) · M3 writers (topic+script, co-creation) · M4 gate engine + surfaces · M5 reviewer-disposition reviews. Content-brain core works end-to-end; interim UI (shadcn + CopilotKit) usable for functional validation.
- **Designed/recorded, not built:** stage/directive contract, manual production/edit/distribution gates, DAM, AVP/POSTIZ/analytics seams, proper copilot (M6), graph/living-op (M7), IAM/actor-model (M8), serious UX, 3090 node + LoRA.

## Plan (phased)

### Now — close the core
- Finish the **M5 functional dry run** end-to-end on :3000 (topic → script → language/religious review → final).

### Phase A — v1 lifecycle completion (the simple structure, end-to-end)  ← next build
- **M9:** formalize the **stage + directive/handoff contract** (forward directives; back/sideways reviews; multi-approval = stages).
- Add **manual gates** for Production, Media-Edit, Distribution (executor = manual now).
- **Minimal DAM/asset model** (for media stages).
- Define **integration seams/contracts** for AVP (edit), POSTIZ (publish), analytics system (feedback) — define now, integrate later.
- Finish seeding **actor-model dims** (autonomy/capabilities/permissions/scope on principals).
- **Outcome = shippable v1:** complete content lifecycle, consistent gates, AI where ready + manual elsewhere, clean seams.

### Phase B — usable & trustworthy (enablers + UX)
- Serious **UX pass** (proper redesign; copilot behind a swappable boundary; expect it to reveal gaps = hardening).
- **M6** proper copilot (your twin) over the gate engine.
- **M8** IAM / user & agent-rep management / roles & permissions.
- **Guest/external approver links** (sheikh/clients) via the gate engine.

### Phase C — intelligence & integrations (differentiators)
- **3090 node** online + Arabic bake-off + **LoRA on Moataz corpus** (the real voice win). *Can start in parallel now.*
- **AVP** integration (media-edit generator) via the contract.
- **POSTIZ** automation (distribution executor).
- **Analytics system** interface + feedback loop (reviewable recommendations → strategy).

### Phase D — the living system (advanced)
- Make the **event log first-class/complete** → **M7 graph/living-operation** view.
- **Semantic memory** (embeddings over decisions/outcomes) → smarter copilot + analytics.
- **Dynamic capability matrices** (model/agent/tool selection) + autonomy policy engine.
- **Multi-tenant / multi-department** activation.

## Immediate next actions
1. Enforce `docs/16_Release_Gate_and_Delivery_Control.md` as the operating rule for active workstreams.
2. Run sacrificial and real-surface validation against the active stabilization issues before further mixed-scope feature delivery.
3. Resume implementation by explicit issue target, not broad branch intent.

## Execution — parallel tracks + risk controls (speed without risk)
- **Track A (critical path, Mac/CC):** M9 core completion. ONLY track that edits schema/engine/surfaces. Sub-blocks with stop-for-review after each.
- **Track B (parallel, Windows/3090):** LoRA dataset prep → Arabic bake-off → fine-tune. Touches NO core code (own folder/branch; reads corpus read-only). Sole future repo touch = a provider-registry entry.
- **External prep (your teams):** AVP/analytics API specs + POSTIZ access, ready for the M9 contracts.
- **Sequential (do NOT parallelize):** UX redesign waits for M9 (moving target + file collisions); real integrations wait for the M9 contracts; only Track A touches schema/engine.
- **Risk controls:** separate folders/branches for B; keep stop-for-review after each M9 sub-block; git + BUILD_STATE coordinate; don't skip reviews for speed.
