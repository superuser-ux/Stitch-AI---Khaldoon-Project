# M7 living-operation view — run-scoped provenance graph read model

Owning issue: **#71** · delivered by directive **#72**. This is the **first safe slice**: a read-only
**data contract**, not the graph UI. It derives a graph-shaped payload for one `round_id` **entirely from
persisted records**, so a later UI (React Flow / Cytoscape) can render an honest activity map.

- **Module:** `gates/provenance.py` → `provenance_graph(conn, round_id, generated_at=None)`
- **Endpoint:** `GET /rounds/{round_id}/provenance` (read-only; `404` for an unknown round)
- **Proof:** `gates/provenance_selftest.py`

## Honesty contract (the point of this slice)

1. **Cite or don't draw.** Every node, edge, and timeline entry carries `cite = {table, field}` and the
   backing record's `source_id`. If a thing cannot cite a real row, it is not emitted.
2. **No dangling graph.** Every edge's `source`/`target` resolves to a real node `id`.
3. **Fence off the future.** Concepts with no persisted backing are **never faked as graph entities** —
   they are listed in `unsupported[]` so the UI can show a "what this map does NOT claim" legend.

## Payload shape

```jsonc
{
  "round_id":     "RSCR",
  "generated_at": "2026-07-07T...Z",
  "nodes":    [ { "id", "type", "label", "cite": {"table","field"}, "source_id", "deep_link", "meta" } ],
  "edges":    [ { "id", "type", "source", "target", "cite": {"table","field"}, "source_id", "meta" } ],
  "timeline": [ { "id", "at", "entity", "entity_id", "action", "actor", "actor_kind", "cite" } ],
  "unsupported": [ { "concept", "reason", "would_require" } ]
}
```

`deep_link` is `null` today (no stable review-UI URL scheme yet); it is reserved for a later slice rather
than fabricated. `generated_at` may be injected by the caller (else server `now`, UTC).

## Derivation rules (node/edge → backing data)

### Nodes
| type | source | id scheme | cite |
|---|---|---|---|
| `round` | `round` (scoped by id) | `round:{round_id}` | `round.round_id` |
| `stage` | `workflow_stage` of the **active** `workflow_version` | `stage:{stage_key}` | `workflow_stage.stage_key` |
| `slot` | `slot WHERE round_id=?` | `slot:{slot_id}` | `slot.slot_id` |
| `topic` | `topic` per revision | `topic:{slot_id}:v{rev}` | `topic.slot_id,revision` |
| `script` | `script` per revision | `script:{slot_id}:v{rev}` | `script.slot_id,revision` |
| `asset` | `asset` | `asset:{asset_id}` | `asset.asset_id` |
| `actor` | deduped from every actor id seen on real rows; kind from `principal` where known, else `audit_log.actor_kind` | `actor:{principal_id}` | `principal.principal_id` / `audit_log.actor_kind` |

### Edges
| type | meaning | source→target | cite |
|---|---|---|---|
| `scopes` | run contains slot | round→slot | `slot.round_id` |
| `transition` | stage topology | stage→stage | `workflow_transition.from_stage_key->to_stage_key` |
| `handoff` | inter-stage directive | stage→stage | `directive.from_stage->to_stage` |
| `produced` | slot yielded artifact | slot→topic/script/asset | `topic|script|asset.slot_id` |
| `revised-from` | revision lineage | rev→base rev | `topic|script.base_revision` |
| `approved-by` | approval | actor→slot / actor→artifact rev | `gate_decision.decision` / `slot_approval.approver` |
| `request-change` | change requested | actor→slot | `gate_decision.decision` |
| `reviewed-by` | review / disposition | actor→slot | `gate_decision.decision` / `slot_review.disposition` |

### Timeline
Every entry is one `audit_log` row for a run entity (`entity_id ∈ slot_ids ∪ gate_ids ∪ {round_id}`),
ordered by `at`. Cites `audit_log.action`.

## `unsupported[]` — future-only, not faked

These have **no persisted rows today** and are declared unsupported (see `provenance.UNSUPPORTED`):

`live_agents` · `used_model_provider` · `tool_call_telemetry` · `delegated_to` · `communicated_with` ·
`blocked_by` · `task_entity` · `agent_rep_or_orchestrator_nodes`

Each entry records a `reason` and `would_require` (e.g. live agents → #19 multi-agent runtime; agent-rep
nodes → seeded principals via #19/#21/#10). A future slice moves an item out of `unsupported[]` **only**
when a real backing table/field exists to cite.

## Boundaries

Read-only; no writes, no schema migrations, no UI, no runtime orchestration. The map must never imply a
capability that #21 bindings do not grant. Adding new node/edge types is allowed **only** when they can
cite a persisted table/field — otherwise they stay in `unsupported[]`.
