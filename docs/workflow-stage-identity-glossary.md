# Workflow Stage Identity Glossary

Status: active reference (#39 slice 1). Canonical source in code: `dashboard/lib/stages.ts`.

## The rule (read this first)

- **Canonical identity = the gate id** (e.g. `final_review`). It is **stable and persisted** (`gate.stage`, `gate_decision`, engine transitions in `gates/engine.py`). **Never rename it** — that would be a data migration.
- **Operator-facing label = presentation metadata** (e.g. "Pre Production Approval"). It **may change freely** without touching identity.
- **Logs / debug / DB** must reference the **canonical gate id** (and, on the dashboard, the alias key), **never the label**. Use `stageDebugId()` → `canonicalGate(alias)` form, e.g. `final_review(final)`.
- The dashboard uses a **short alias key** (`final`) in `STAGES`, testids, and `lib/views.ts`; that alias resolves to the canonical gate id. The alias is a dashboard convenience, not a second identity.
- Admin-editable labels at runtime (`workflow_stage.stage_label`) are **future #6 scope**; today the labels below are the static dashboard defaults, not a runtime source of truth.

## Glossary

| Canonical gate id (identity) | Dashboard alias key | Preferred operator label | Actual meaning | Slot status | In review nav today | Editable now | Future #6 admin scope |
|---|---|---|---|---|---|---|---|
| `schedule_review` | `schedule` | Schedule | schedule / slot-reservation review | `RESERVED` | yes | no (static default) | yes |
| `topic_review` | `topic` | Topics | topic-title review | `TOPIC_PROPOSED` | yes | no | yes |
| `script_review` | `script` | Scripts | script-draft review | `DRAFT_ASSIGNED` | yes | no | yes |
| `native_review` | `native` | Language sign-off | dialect / language sign-off | — | **no (engine-native)** | no | yes |
| `scholar_review` | `scholar` | Religious sign-off | religious / scholarly sign-off | — | **no (engine-native)** | no | yes |
| **`final_review`** | **`final`** | **Pre Production Approval** | **pre-production sign-off (NOT publishing)** | `APPROVED_ASSIGNED` | yes | no | yes |
| `production_review` | `production` | Production | production-readiness review | `READY_FOR_PRODUCTION` | yes | no | yes |
| `edit_review` | `edit` | Media edit | media-edit review | `PRODUCED` | yes | no | yes |
| `distribution_review` | `distribution` | Distribution | distribution / posting review | `EDITED` | yes | no | yes |

## The `final` case (the reason this glossary exists)

One concept previously carried five disagreeing names:

- gate id `final_review` (canonical) · dashboard key `final` · old label **"Publish approval"** · resulting status `APPROVED_ASSIGNED` · actual meaning **pre-production sign-off**.

"Publish approval" implied publishing; the stage is actually a **pre-production sign-off**. The operator label is now **"Pre Production Approval"**; the canonical id stays `final_review` (unchanged in the DB and engine). If this is later renamed for operators again, only the label changes — identity is untouched.

## Known divergences / follow-ups (for #6, not resolved here)

- **Engine-native stages** `native_review` and `scholar_review` exist in `gates/engine.py` but are **not surfaced in the dashboard review nav** (`STAGES`). This is an intentional curated subset for now; reconciling engine-native vs surfaced stages is #6's "engine-native vs admin-editable" clarification.
- **Runtime-editable labels**: making `workflow_stage.stage_label` the live source (so operators rename stages without a code change) is #6. Before that, the `workflow_stage` seed must be confirmed to agree with `gates/engine.py` (seed location currently unconfirmed — likely a migration `013–019` or `loader/`).
- **Engine label (`gates/engine.py` `WORKFLOW_STAGE_LIBRARY`)** still hardcodes "Publish approval". This slice intentionally does **not** change engine/Python labels (no engine runtime dependency on dashboard labels); aligning the engine label is a separate step under #6/#39-slice-2.

## What slice 1 changed

- Added `dashboard/lib/stages.ts` — the single dashboard-side stage-identity source (identity + alias + label + meaning + debug id).
- `dashboard/lib/review-context.tsx` `STAGES` and `dashboard/components/admin/workflow-admin.tsx` `STAGE_LIBRARY` now derive their labels from `stages.ts` (de-duplicated); the `final` stage label changed "Publish approval" → "Pre Production Approval".
- No persisted gate id, slot-status enum, API contract, or workflow execution changed.
