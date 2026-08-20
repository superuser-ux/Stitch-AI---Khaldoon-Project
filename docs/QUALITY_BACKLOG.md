# Quality backlog — output-quality observations (parallel track; NOT fixed in flow passes)

Mode note: we validate **process + flow** end-to-end; **output quality is a deprioritized, parallel track.** This file logs quality observations seen while driving flow, so nothing is lost. Do NOT fix these in a flow pass.

## R3 — Scout script generation (2026-06-30)
Observed while driving R3 through the lifecycle to SCHEDULED (Scout, QA gates ran). Approved through for flow validation; quality to address in the writer track.
- **R3-D02-PM (Work / imposter syndrome)** — `script_hard_fail`: Egyptian dialect leaked («كده»); `delivery_check_incomplete`: missing metaphor. The dialect guard flagged it correctly; the script was persisted at v1 after max regenerations. → real candidate for request-change/regenerate or a writer-prompt tweak point on this HCS.
- **R3-D01-PM (Relationships)** — `dialect_soft_warn` (a suspect-but-legitimate marker, e.g. حاجة). Advisory only; native-review territory.
- **R3-D01-AM, R3-D01-PM** — used a Qur'an/Hadith anchor (`needs_scholar_review`). Anchors organic-by-policy; scholar sign-off is the gate. (R3-D01-AM scholar review was escalated + signed during the flow run.)
- All scripts carry `needs_native_review` (every ar-PS script). In `reviewer_discretion` mode these don't block publish — a **policy/coverage note**: most reached SCHEDULED without a native pass. For production, either escalate per item, or set `reviews.native.mode: suggested|required`.

## Writer-track follow-ups (from earlier passes, still open)
- Dialect guard on the **topic justification/rationale** field (Egyptian leaked into a couple rationales).
- **Surgical-vs-rethink** rework: minor word-swap comments should preserve unchanged parts (the rework prompt now asks for this, but quality of adherence is unverified at scale).
- Rationale prompt is a bit boilerplate ("many people struggle with X").
- LoRA on Moataz's ~1,400-caption corpus (the real voice win) — Track B.
