# Stage 4 approval-package preflight (#447)

`GET /gates/{gate_id}/slots/{slot_id}/approval-preflight` — read-only, server-authoritative.

The read-only GET counterpart of the #439 sign-off command. For one canonical admitted
`(gate_id, slot_id)` final-review target it answers, from already-persisted records only:

> is this exact **immutable** pinned package still fully pinned, still governed by the current
> generation, and still in a presently-eligible state for a human final-review sign-off — and if so,
> what are the exact six values that identify it?

It **does not** execute production, grant capability, advance lifecycle, create or validate a sign-off
receipt, or authorize anything.

## Boundary

| Property | Guarantee |
| --- | --- |
| Method | GET only. Every statement is a pure `SELECT`; no `FOR UPDATE` (the #439 command locks — this read must not). |
| Writes | None. No builder / emission / record / provider / model / secret path is imported or invoked. |
| Identity | `(gate_id, slot_id)`. There is **no** slot-only gate-resolution heuristic — choosing "the latest" or "the open" gate for a slot would mint selection policy in a read model. |
| Authority | **Structural only.** No caller is evaluated, no actor is selected, no principal is loaded, and no eligible-principal or coverage-principal id is disclosed. `authorization_evaluated` is always `false`. Principal authorization remains the sign-off command's server-side responsibility. |
| Schema | None. No migration, no new column, no persisted state. |
| Additivity | New module + new route. #419 `/slots/{slot_id}/stage4_preflight`, #423 `/target-package`, #427 `/final-review-projection` and #439 `/sign-off` are untouched. |

## The six-member tuple is unconditional

`gate_id, slot_id, snapshot_id, topic_revision, script_revision, workflow_version_id` — read verbatim
from the immutable `final_review_target_package` snapshot (#423, migration 036), which is the same
tuple #439's `sign_off` binds.

`target_package_tuple` is **all six members or `null`**. A recorded row with a NULL member, a legacy
target attached before migration 036, and a non-admitted pair all fail closed and emit **no** tuple —
a partially pinned package is never returned as coherent, and it is never synthesized, backfilled, or
inferred from live selections. The client mirror (`lib/approval-preflight-presentation.ts`) enforces
the same refusal so a partial pin cannot be assembled or displayed downstream.

## Pinned is evidence; live is a coherence check

| Fact | Source | On disagreement |
| --- | --- | --- |
| Package snapshot id | pinned package row | must equal the governing gate snapshot (#282/#422), else `inconsistent_snapshot_reference` (inherited from #427) |
| Workflow version | pinned package row + `workflow_version_source` | divergence from the currently-active version fails closed (`consumed_active_workflow_divergence`, inherited from #419) — never a silent rebinding |
| Topic / script revision | pinned package row | governed head must still equal the pin, else `signoff_stale` |
| Production direction | pinned package columns | any disagreement with observed canonical state fails closed (`production_direction_mismatch`) |

A live read never replaces, refreshes, or promotes itself over a pinned value.

**Deliberately conservative branch:** a production direction present in canonical state that the
immutable package does **not** pin is treated as a disagreement and fails closed. A direction
legitimately emitted *after* attachment also lands here. This is the fail-closed reading of the #447
reconciliation and is isolated to one branch so a future directive can change it without touching the
rest of the contract. Absence on **both** sides is not a disagreement — it is the non-denial
`not_yet_recorded` evidence status (#419 precedent).

## Present-state eligibility

The **actor-independent prefix** of `engine._signoff_revalidate_present_authority`, evaluated in the
identical order and reusing the identical helpers (`_load_gate_snapshot`, `_head_revision`,
`_gate_review_head`, `_effective_decisions_for_head`, `_authoritative_target_projection`):

gate is `final_review` and admitted → gate is `open` → a governing snapshot exists → no
slot-unattributable decisions → governed head equals the pinned revisions → present outcome is
`approved`.

The actor-dependent tail (frozen-eligibility membership, the per-principal hard-floor verdict) is
**not** evaluated here. `_signoff_revalidate_present_authority` is neither called nor refactored, so
#439's merged behaviour is untouched; the duplicated order is locked by the focused test.

Only `current_outcome` is taken from the projection — per-token coverage carries covering principal
ids and is deliberately neither read into the response nor counted.

## Reason vocabulary and deterministic precedence

No new policy vocabulary is introduced. Every code is **imported** from an existing canonical
classification (`final_review_projection`, `stage4_preflight`, `engine.SIGNOFF_ERROR_STATUS`) and is
never re-typed as a string literal, so the vocabularies cannot drift. Present-state codes are reported
as **read-model evidence**, never as command error semantics and never as an authorization result;
the two actor-dependent sign-off codes (`signoff_not_authorized`, `signoff_hard_floor`) can never be
emitted.

`denials` are returned **pre-sorted** and `reason_code` is the head — the client never re-ranks:

| Tier | Codes | Source |
| --- | --- | --- |
| 1 — historical / immutable proof | `not_a_final_review_target`, `missing_target_package_snapshot`, `legacy_record_predating_authoritative_snapshots`, `missing_governing_gate_snapshot`, `inconsistent_snapshot_reference` | #427/#429 |
| 2 — governed generation coherence | `active_workflow_unavailable`, `consumed_active_workflow_divergence` | #419 |
| 3 — structural human-authority floor | `final_review_unknown` | #419 |
| 4 — present-state eligibility | `signoff_target_unavailable`, `signoff_blocked`, `signoff_stale` | #439 |
| 5 — downstream direction coherence | `production_direction_mismatch` | #419 |

**Missing/unknown historical proof outranks present-state eligibility whenever both fail**, so a
client is told that history was never established rather than a present-state symptom derived from
evidence that never existed.

## Two orthogonal top-level facts

- `status` — the **historical evidence** status: `recorded` / `unknown_history` / `unavailable`.
- `available` — the **eligibility verdict**: `true` only when nothing failed.

They are never collapsed. A `recorded` history with a present-state denial is *not eligible*; an
`unknown_history` result is *not* a rejection.

## Client

- Allowlisted read path: one GET entry in `workbench/lib/api-contract.ts` (`resolveAllowedWritePath`
  untouched).
- Route: `/gates/[gateId]/slots/[slotId]/approval-preflight`, inside the existing #331 shell.
- The surface offers **no action** — it cannot sign off, approve, decide, advance, or execute
  anything. The only interactive control is a retry for a transport failure.
