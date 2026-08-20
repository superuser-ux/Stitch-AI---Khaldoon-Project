# Phase 1 — Build Spec: Strategy → Topic → Script (v1)

**Goal:** A runnable vertical slice that takes a *period request* and produces **approved, scripted, slotted content** ready for production — fully bound by the canon, with a working approval gate. This replaces the most labor-intensive human work and proves the two riskiest ideas (the deterministic engine + the gate model).

**Out of scope (later phases):** media editing, platform formatting, distribution, analytics loop. Stubs/handoff points are defined where they connect.

---

## 1. Stack (lightest that proves the loop)
- **Orchestrator + agents:** one service (TypeScript or Python). Agent reasoning via LangGraph-style chain; no durable engine yet.
- **DB:** Postgres (+ `pgvector` for the dedup safety net).
- **Dashboard:** Next.js, chat-first, RTL/Arabic.
- **Messaging:** Telegram bot (approve/reject/change on the go).
- **LLM:** frontier model with strong Arabic/Palestinian dialect for Topic + Script; cheaper model for orchestration glue.
- **Hosting:** TBD pending residency answer; single small VM/managed Postgres is enough for this volume.

---

## 2. Data model (DDL sketch)
```sql
-- methodology (seeded from CANON-010..014 + HCS records)
pillar(pillar_code PK, name_en, name_ar, scope)
hcs(hcs_id PK, pillar_code FK, name_en, name_ar, core_wound, how_it_shows_up,
    false_belief, earthquake_sentence, islamic_anchor, recommended_lenses jsonb,
    recommended_formats jsonb, value_ladder jsonb,
    voice_status enum('seed','native_reviewed'), anchor_status enum('unverified','scholar_verified'))
lens(lens_id PK, name_ar, name_en, viewer_state, default_hook_type)
hook_type(name PK, function)
format(name PK, use_case, lens_fit jsonb, production_notes)

-- planning + the cursor that guarantees no-repeat
round(round_id PK, label, period_len_days, posts_per_day, post_times jsonb,
      pillar_distribution jsonb, format_distribution jsonb, status)
hcs_cursor(pillar_code PK, last_hcs_id, cycle_no)          -- sequential position
lens_history(hcs_id, cycle_no, lens, PRIMARY KEY(hcs_id,cycle_no)) -- enforce lens≠prev

-- the unit of work = a calendar slot (also the workflow state)
slot(slot_id PK, round_id FK, day, time_uae, pillar_code, format,
     hcs_id, lens, hook_type, topic_angle, hook_text, script_ref,
     status enum('EMPTY','RESERVED','DRAFT_ASSIGNED','APPROVED_ASSIGNED',
                 'SCHEDULED','PUBLISHED','SKIPPED','REPLACED'),
     created_at, updated_at)

-- topics ledger (safety-net dedup + coverage history)
topic(topic_id PK, slot_id FK, hcs_id, lens, text_ar, text_en, embedding vector, created_at)

-- approvals (per-item or per-batch, multi-approver, fixed/adhoc)
gate(gate_id PK, scope enum('item','batch'), stage, policy enum('fixed','adhoc'),
     status enum('open','approved','rejected','changes_requested'), created_at)
gate_target(gate_id FK, slot_id FK)                        -- batch = many slots
gate_decision(gate_id FK, approver_id, decision, notes, decided_at)
```

---

## 3. The deterministic assignment algorithm (Planner)
Implements CANON-015 exactly:
1. Build slots for the round from `pillar_distribution` (P1=22…P5=4) + `format_distribution` (weekly Studio 4, etc.). Each slot gets `pillar` + `format` + `time_uae`.
2. For each pillar, walk HCS **top-to-bottom from `hcs_cursor.last_hcs_id`**; assign `hcs_id` per slot; advance cursor; when a pillar's HCS list is exhausted, wrap and `cycle_no++`.
3. **Lens selection:** pick from `hcs.recommended_lenses`, excluding any lens in `lens_history` for this `(hcs_id, prior cycle)`. Record to `lens_history`.
4. `hook_type` defaults from `lens.default_hook_type` (override allowed by Topic agent).
5. Slots created at status `RESERVED` → handed to Topic agent.
> Result: repetition impossible by construction. Embedding dedup only guards accidental angle/hook echoes.

**Parametric:** alternate periods or ad-hoc items override `round` params; ad-hoc slots can be flagged off-cycle (don't advance the cursor) or on-cycle (do).

---

## 4. Agent IO contracts

### 4.1 Topic/Brief agent ("Agent 1")
- **In:** slot (pillar, hcs record, lens, format, platform context).
- **Out:** `{topic_angle, hook_text, hook_type, rationale}` OR `NEEDS_STRATEGIC_CLARIFICATION`.
- **Rules:** angle must map to the HCS; hook obeys CANON-013 (first spoken line 3–7 words, no greeting, no Moataz name, one person, true-not-clever); lens drives the angle per CANON-012 questions; format respected.
- **Gate after:** dedup check (embedding vs `topic`); if too similar, regenerate.

### 4.2 Script agent
- **In:** approved topic + hcs record + lens + format.
- **Out:** `{script_ar, structure, final_line, delivery_notes, flags[]}`.
- **Hard self-checks (auto-reject before human):**
  - Hook rules (CANON-013) + Hard Fail conditions.
  - Mandatory Delivery Check (CANON-012): scroll-stop hook, full emotional journey, metaphor, scientific truth, Qur'an/Hadith *only if organic*, light human moment, unforgettable final line.
  - If `islamic_anchor` used → set flag `needs_scholar_review`. Dialect → flag `needs_native_review`.
- Writes `script_ref`; slot → `DRAFT_ASSIGNED`.

*(Prompt skeletons for both agents to be authored from the canon + the calibration voice patterns; the HCS records supply the substance.)*

---

## 5. Approval gate logic
- **Trigger:** batch gate opens when a round's slots reach `DRAFT_ASSIGNED` (default), or per-item for high-stakes.
- **Surfaces:** dashboard (batch table: slot, pillar, HCS, lens, hook, script preview; bulk + per-row actions) and Telegram (one item at a time: Approve / Reject / Request change + note).
- **Partial batch:** approving 8/10 moves those 8 → `APPROVED_ASSIGNED`; the other 2 → `changes_requested` and loop back to the relevant agent with notes (slot stays in DRAFT, optionally `REPLACED` if HCS/lens re-assigned).
- **Multi-approver:** `gate` can require N approvers; `gate_decision` rows tallied; policy (any/all/quorum) configurable.
- **Audit:** every transition logged with actor + timestamp.

---

## 6. Dashboard + Telegram (Phase 1 screens)
- **Chat-first home:** talk to the User-Agent rep — "plan next 28 days", "show what's awaiting me", "approve batch R2 topics", "redo 3.4 with a different lens".
- **Round view:** the 42×5 coverage grid + slot calendar with statuses.
- **Review queue:** batch table with partial actions + script preview (RTL).
- **Telegram:** push when a gate opens; inline buttons; notes via reply.

---

## 7. Acceptance criteria (definition of done)
1. Given "plan a 28-day round", system generates 56 slots with correct pillar (22/17/9/4/4) + weekly format mix (4/1/2/2/3/1/1), correct HCS sequence from the cursor, and lenses respecting the no-repeat-lens rule.
2. Topic + Script agents fill every slot to `DRAFT_ASSIGNED`; scripts pass the hard self-checks; religious/dialect flags set where relevant.
3. A reviewer can **batch-approve with partial actions** from both dashboard and Telegram; partial rejects loop back correctly; all transitions audited.
4. No duplicate topic passes the dedup net within a cycle (test with a deliberate near-duplicate).
5. Re-running a second round continues the cursor and rotates lenses (verify 1.x HCS gets a different lens than round 1).

---

## 8. Milestones
1. **M1 – Data + canon load:** schema live; CANON-010..014 + 42 HCS records seeded; baselines noted.
2. **M2 – Planner:** deterministic slot generation + cursor + lens rotation (acceptance #1, #5).
3. **M3 – Agents:** Topic + Script with hard checks + dedup (acceptance #2, #4).
4. **M4 – Gates + surfaces:** dashboard review + Telegram, partial batch, multi-approver, audit (acceptance #3).
5. **M5 – Hardening:** native-review + scholar-review workflow flags surfaced in the queue; dry-run a full round end-to-end.

---

## 9. Dependencies / open items
- Native Palestinian editor + scholar reviewer in the loop (process, not code).
- Confirm hosting/residency before M1.
- Value-ladder canon (not required for Phase 1; needed for CTAs in Phase 3).
- Reconcile any existing Agent 2/3 definitions with §4 if you have them.

*v1 — consistent with Blueprint v2 §5/§7. Builds on the seeded HCS records and the calibration voice rules.*
