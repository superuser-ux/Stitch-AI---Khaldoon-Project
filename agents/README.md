# Writers (M3) — Topic/Brief + Script agents

`run_writers.py` turns RESERVED slots into DRAFT_ASSIGNED ones (Phase1_Build_Spec §4).
All model/provider/threshold behavior is config (`system_config.yaml`), not code; voice
rules are injected straight from the canon (CANON-012/013) and the HCS record.

## Pipeline per slot

Each slot's prompt gets 3–5 **pillar-matched dialect exemplars** (real high-engagement
captions, built by `build_exemplars.py` → `methodology/voice/dialect_exemplars.json`) as
few-shot voice anchors.

1. **Agent 1 (Topic/Brief)** generates `topic_angle` + `hook_text` + `hook_type` (or
   flags `NEEDS_STRATEGIC_CLARIFICATION`). The spoken hook is hard-checked against
   CANON-013 (3–7 words, no greeting, no "معتز", one person) **and the dialect guard**
   (Gulf/Egyptian markers from `writers.dialect_guard`), and regenerated on any violation.
2. **Dedup** embeds the topic (local `mxbai-embed-large`, 1024-dim) and compares it to
   the topic ledger within `engine.dedup_safety_net.scope`; regenerates on a
   near-duplicate (≥ `similarity_threshold`). Scope `hcs` guards the same HCS recurring
   across cycles/rounds.
3. **Agent 2 (Script)** writes `script_ar` enforcing the CANON-013 Hard Fails + the
   CANON-012 Mandatory Delivery Check + the dialect guard. Sets `needs_scholar_review`
   when an `islamic_anchor` is used and `needs_native_review` for Palestinian dialect.
4. On success: insert into `topic` + `script`, set `slot.script_ref`, move the slot to
   **DRAFT_ASSIGNED**, and write `audit_log` entries — in one transaction per slot.

## Backends — provider registry + per-stage primary/fallback

All model selection lives in `system_config.yaml` (`providers` + `models`). Each stage
has a `primary` and an ordered `fallback` list; on any provider error / quota / HTTP 402
the `StageRunner` falls through and logs each hop. The OpenAI-compatible `ChatClient`
serves every chat provider and takes a generic per-stage/ref `params` passthrough
(e.g. `reasoning_effort`, `stop`) plus `prompt_suffix`; it retries 429s with backoff
(honouring the server's retry delay).

- **Writing:** `gemini / gemini-2.5-flash` primary (`GEMINI_API_KEY`, `reasoning_effort:
  low` so "thinking" doesn't truncate scripts) → fallback `ollama / gemma4:26b`
  (capped + concise, local).
- **Embeddings:** local Ollama `ollama_embed / mxbai-embed-large`.

Refresh the exemplar bank from new exports with `python agents/build_exemplars.py`.

## Run it

Stack up (`docker compose up -d db`) and a round planned (M2). The container needs the
DB (compose network), the internet (OpenRouter), and the host's Ollama
(`--add-host=host.docker.internal:host-gateway`):

**Two-stage flow (M4.1): topics are approved BEFORE scripting.**
```bash
RUN='docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
  --add-host=host.docker.internal:host-gateway -v "$PWD":/work -w /work python:3.12-slim \
  bash -lc "pip install -q -r agents/requirements.txt &&'

# 1) topics: RESERVED -> TOPIC_PROPOSED (topic + hook + bilingual "why now"; NO script)
$RUN python agents/run_writers.py topics --round R1"
#    -> review at the topic_review gate (dashboard / Telegram / gates CLI)
# 2) scripts: TOPIC_APPROVED -> DRAFT_ASSIGNED (full script; approved topics ONLY)
$RUN python agents/run_writers.py scripts --round R1"
#    -> review at the script_review gate
# rework (co-creation): re-run an agent for slots a reviewer sent back, with the note injected
$RUN python agents/run_writers.py rework --stage topic"    # or --stage script
# bake-off (read-only model comparison)
$RUN python agents/run_writers.py bakeoff"
```

Provider credentials may be supplied as `GROQ_API_KEY` / `OPENROUTER_API_KEY` or through the hardened
`*_FILE` seam with a positive `*_FILE_MAX_AGE_SECONDS`; configuring both forms for one key fails closed.
Modes: `topics` / `scripts` / `rework` (`--stage topic|script`)
/ `bakeoff`; selection flags `--slot-ids` / `--round` / `--limit` / `--distinct-pillars` / `--dry-run`.

(Git Bash on Windows: prefix `MSYS_NO_PATHCONV=1` and use `"$(pwd -W)"` for the mount.)
