# Gates (M4) — approval engine + surfaces

The approval layer (Phase1_Build_Spec §5–6). A round's slots reach `DRAFT_ASSIGNED`
(from the writers, M3); a **batch gate** opens over them; approvers approve / reject /
request-change per slot or in bulk; `resolve` moves the approved slots to
`APPROVED_ASSIGNED` and loops the rest back — every transition written to `audit_log`.

## One source of truth
All transition logic lives in **`engine.py`**. Three surfaces call it, so the rules
(who may approve, quorum, partial-batch) are defined once and come entirely from
`system_config.yaml` (`gates.<stage>`):

- **`cli.py`** — ops + verification (`open` / `list` / `show` / `decide` / `resolve`).
- **`api.py`** — FastAPI the Next.js dashboard talks to (read queue, post decisions).
- **`bot.py`** — Telegram bridge (inline approve/reject/change buttons).

n8n is intentionally **not** in the approval path (reserved for the later distribution phase).

## Config (`gates.<stage>`)
```yaml
gates:
  script_review:
    scope: "batch"            # batch | item
    policy: "fixed"           # fixed | adhoc
    approvers: ["khal"]       # legacy shorthand; equivalent to approval.users
    quorum: "any"             # legacy shorthand; equivalent to approval.rule
    approval:                 # CR01-ready explicit model (preferred)
      rule: "or"              # or | and | any | all | N
      users: ["khal"]
      roles: ["language_reviewer"]
      groups: ["brand_team"]
      assignments: ["user:khal", "role:brand", "group:legal"]  # optional flat form
    allow_partial_batch: true
```

`approval` is additive and backward-compatible with the legacy `approvers` + `quorum` shape.
When a gate opens, the engine snapshots the normalized assignments into `gate_assignment` so
mid-flight config changes do not silently rewrite who is authorized to approve.

## Decision model
Per slot, precedence **reject > request_change > approve**; a slot is `approved` once it
has ≥ quorum distinct `approve` decisions and no reject/change. `approved` → `APPROVED_ASSIGNED`;
`reject` / `request_change` keep the slot `DRAFT_ASSIGNED` and audit a `looped_back` event
for the writer/editor to pick up.

## Run (CLI, DB up)
```bash
docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
  -v "$PWD":/work -w /work python:3.12-slim \
  bash -lc "pip install -q -r gates/requirements.txt && python gates/cli.py open --stage script_review --round R1"
```
