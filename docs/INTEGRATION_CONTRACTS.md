# Integration Contracts (M9 · B2) — external executors against the directive schema

**Status: DEFINED + STUBBED, not integrated.** This document + `integrations/` declare the seams so
AVP, POSTIZ, and the analytics system can drop into the pipeline in Phase C without touching the
engine. Every provider is `enabled: false` in `system_config.yaml` (`integrations.*`) until wired.

## The one contract
A stage is `{ input directive, executor, output directive }` (ARCHITECTURE.md). The executor is
pluggable: **ai** (topic/script — built), **manual** (production/media_edit/distribution — B2), or
**external** (these providers). All three are interchangeable because they speak the same language:

```
executor.execute(directive, assets) -> ExecutorResult{ artifacts[], next_directive, notes }
```

- `directive` — the stage's INPUT directive (the B1 six-field package: intent / inputs /
  parameters / constraints / acceptance_criteria / context). The executor must satisfy
  `acceptance_criteria`.
- `assets` — the DAM rows the directive references (raw cuts, edits, variants).
- `artifacts` — new DAM asset specs the executor produced (passed to `dam.add_asset`).
- `next_directive` — the directive the next stage consumes (or `None` for a terminal stage).

The gate that follows the stage then checks output-vs-directive **exactly as for AI/manual stages**
— integration shape (API / MCP / file) is the provider's private business. Code: `StageExecutor`
in `integrations/contracts.py`; stubs in `integrations/stubs.py`; registry from config via
`load_registry(cfg)` (empty by default — nothing integrated).

## The three providers

### 1. AVP — Agentic Video Producer → `media_edit` generator
| | |
|---|---|
| Fills stage | `media_edit` (today: manual human editor) |
| Consumes | `media_directive` (emitted at `production_review` approval) |
| Reads | DAM `raw_cut` assets + the approved `script` (final_line, delivery_notes, format) |
| Emits | edit options as DAM `edit` assets + `distribution_directive` |
| Gate after | `edit_review` — **AVP proposes, human disposes** (the edit options still pass review) |

### 2. POSTIZ — distribution executor behind the publish gate
| | |
|---|---|
| Fills stage | `distribution` (today: manual format/schedule) |
| Consumes | `distribution_directive` (emitted at `edit_review` approval) |
| Reads | DAM `edit` assets + platform variants |
| Emits | `None` (terminal — the published/scheduled post) |
| Hard floor | **Nothing publishes without passing `distribution_review` first.** POSTIZ acts ONLY on already-approved state, triggered by the core's events, and records its actions back as audited events (memory stays whole). It never owns approval state. |

#### pub.v1 — publication persistence every executor lands on (#199 frozen, #200 implemented)
Publication outcomes persist in their own first-class records (`publication` +
`publication_event`, migration 022) — never as media asset versions. The contract, in brief:
- **Two identities:** `publication_intent_id` (the governed attempt-to-publish) vs
  `publication_occurrence_id` (≤1 per intent, set once when attested/confirmed).
- **Idempotency:** callers reserve a stable `idempotency_key` BEFORE the first mutation;
  UNIQUE `(provider_key, destination_account_scope, idempotency_key)` is DB-enforced. Exact
  replay returns existing truth; key reuse with different bound data is a hard conflict.
  Provider-local ids are scoped-unique `(provider, account scope, object type, external_ref)`.
- **Lineage frozen at create:** exact slot / script / approved Edit-output asset+version /
  distribution+production+edit gate ids / raw asset ids / destination — DB triggers keep them
  immutable, the event history append-only, and rows undeletable. The raw readiness set is
  normalized into `publication_raw_asset` junction rows (operator-authorized amendment on #200)
  with NATIVE non-cascading `NO ACTION` FKs — an unknown asset can never be referenced and a
  referenced asset can never be deleted/id-retargeted, correct under MVCC by PostgreSQL's own FK
  machinery; a freeze trigger pins set membership once the intent has history, and a
  DEFERRABLE INITIALLY DEFERRED constraint trigger makes creation atomic — a publication can
  only COMMIT together with its initial raw readiness set and the canonical first event
  (`event_seq=1`, `event_type='intent_created'`), so an eventless or wrongly-seeded parent can
  never exist for a later transaction to append lineage to. Occurrence
  evidence (url/refs/times/attestor) freezes the moment the
  occurrence is recorded — reconciliation/retraction will append typed events, never overwrite.
  A corrected repost is a NEW linked intent.
- **Two predicates, re-evaluated at create AND at success:** content eligibility (committed
  RESOLVED-gate truth only — an approve decision on an unresolved gate never counts) ≠ actor
  attest authority (DIRECT user assignment on the distribution gate's snapshot; role/group
  membership deliberately grants nothing in this slice — #9-safe). Before success the COMPLETE
  frozen lineage (all three gate ids, script id, edit asset+version+rendition, raw readiness set)
  is compared against current committed evidence — any drift fails closed with the drifted
  fields named in an attributable denial audit.
- **Manual is a first-class execution source** (`execution_source='manual'`,
  `destination_account_scope='-'` = accountless), not simulated provider data. Provider
  executors (POSTIZ et al.) will write the SAME records with their own scope/refs.
- Reserved lifecycle events (scheduled/cancelled/reconciled/corrected_by/retracted/
  externally_confirmed) are typed in the schema; commands/endpoints for them are NOT in #200.

### 3. Analytics — the user's system → Strategy feedback (interface, don't rebuild)
| | |
|---|---|
| Fills stage | `strategy` (origin of the pipeline) |
| Consumes | platform KPIs (read from the user's analytics system) |
| Emits | `strategy_directive` proposals |
| Hard floor | Analytics-driven outputs (new strategies / methodology amendments) are **PROPOSALS** — they pass a hard-floor human review gate before applying (propose → review → approve). Never a silent methodology rewrite. |

## Governance (applies to all)
- **Capability nodes:** each provider is a registered tool/capability (config `integrations.*`),
  swappable and contract-bound — same discipline as the future capability matrix.
- **Decoupled but governed:** providers act only on approved state, pass the same gates, and write
  their actions back as attributed events. n8n MAY implement some as connector-glue (POSTIZ push,
  analytics ingest, notifications) per ARCHITECTURE.md — glue, not logic; never the state machine.
- **Versions/compat:** verify the provider/library version (context7) before wiring any of these.

## Not in scope here (Phase C)
Actual API/MCP calls, auth/keys, retry/idempotency, payload mapping, and the n8n workflows. B2
only fixes the **contract** so those are drop-ins, not refactors.
