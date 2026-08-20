# Workflow Stage Naming & Identity — Decision Brief (#39 / #6)

Author: CC (read-only inspection; no code/DB/GitHub mutation)
`origin/main`: `7751614` · Prompt: "Workflow Naming & Stage Identity Decision Brief — CC only (OR)"
Status: **DECISION BRIEF ONLY — nothing implemented.**

---

## TL;DR recommendation

**Do NOT rename internal keys/gate names (Option 3 is high-risk — it migrates 500+ live gate rows and breaks every selftest/seed). Adopt Option 4: freeze the gate name as the documented canonical identity, collapse the three duplicated label catalogs into one admin-editable label source (`workflow_stage.stage_label`), and publish a naming glossary.** Land the **canonical-identity decision as #39 (standalone, first)**; deliver the **admin label-editing mechanism under #6** (it owns the workflow-admin surface). #39 defines what #6 edits, so #39 sequences first.

---

## 1. Current naming model — there are THREE parallel stage catalogs

| # | Catalog | Location | Editable? | Authoritative for |
|---|---------|----------|-----------|-------------------|
| A | **Engine library** `WORKFLOW_STAGE_LIBRARY` | `gates/engine.py:40–48` (hardcoded) | code-only | gate identity + transitions + labels (engine truth) |
| B | **Dashboard STAGES** | `dashboard/lib/review-context.tsx:80–87` (hardcoded) | code-only | dashboard nav/labels/keys + testids + `lib/views.ts` |
| C | **DB workflow_stage** | `db/init/schema.sql:259` table | **admin-editable** (via `/workflows`, `workflow-admin.tsx`) | CR01 governance model (versions, enable/bypass, ordinal) |

These three **must agree but are maintained separately**. Renaming a label in C (admin) does **not** change A or B (both hardcoded). That is the core architectural defect behind #39.

### Divergences beyond labels (important)
- **A has stages B omits**: engine has `native_review` (Language sign-off), `scholar_review` (Religious sign-off), `production_review` (Production) — the dashboard `STAGES` does **not** list these. So B is a curated subset of A, not a mirror.
- **B's keys differ from gate names**: dashboard `key: "final"` vs gate `"final_review"`; `key: "edit"` vs `"edit_review"`; `key: "distribution"` vs `"distribution_review"`. `lib/views.ts` (`CONTENT_REVIEW_STAGES`) and testids depend on the short keys.

## 2. Mismatch inventory — the "final" concept has 5+ names, none neutral

| Layer | Identifier for this one stage |
|-------|-------------------------------|
| Engine **gate name** (canonical, persisted) | `final_review` |
| Engine label (A) | `Publish approval` |
| Dashboard **key** (B) | `final` |
| Dashboard label (B) | `Publish approval` |
| Resulting **slot status** (enum) | `APPROVED_ASSIGNED` |
| Governance `workflow_stage.stage_key` (C) | *(seed location unconfirmed — see Ambiguities)* |
| Actual process meaning | **pre-production sign-off** |
| Owner's desired label | `Pre Production Approval` |

Same problem, milder, on `edit`/`edit_review`/"Media edit" and `distribution`/`distribution_review`/"Distribution". `native_review`/`scholar_review` labels ("Language/Religious sign-off") are descriptive but engine-only.

## 3. Source-of-truth map

| Concept | Canonical home | Persisted in DB rows? | Migration cost if renamed |
|---------|----------------|-----------------------|---------------------------|
| **Stage identity** = gate name (`final_review`) | `gate.stage`, `gate_decision.*`, `open_gate()`, engine transitions | **YES** — live counts: `schedule_review` 239, `topic_review` 223, `script_review` 69, `final_review` 15, `production/edit/distribution_review` 2 each; **500 `gate_decision` rows** | **HIGH** — must migrate all gate + gate_decision rows + selftests + seeds + transitions |
| Slot status (`APPROVED_ASSIGNED`) | `slot_status` enum, `slot.status` | YES | HIGH (enum migration) |
| Engine label | `gates/engine.py` (A) | No | trivial (code) |
| Dashboard key | `review-context.tsx` (B) + `views.ts` + testids | No (but tests couple) | LOW-MEDIUM (code + testids) |
| Dashboard label | `review-context.tsx` (B) | No | trivial (code) |
| **Editable operator label** | `workflow_stage.stage_label` (C) | YES (workflow_stage rows) | n/a — it's meant to change |

**Key takeaway:** the *identity* (gate name) is deeply persisted and expensive to rename; the *label* is cheap and already has an editable DB home (`stage_label`). The fix is to stop treating them as the same thing.

## 4. Options

| Option | What | Scope | Migration risk | Test impact | Operator clarity | Debug clarity | #6 relationship |
|--------|------|-------|----------------|-------------|------------------|---------------|-----------------|
| **1. Display-name override only** | small label map the dashboard reads; keys/gates untouched | XS | none | minimal (testids use keys) | High | Low (internal `final`/`final_review` still confusing) | independent |
| **2. Label model via `workflow_stage.stage_label`** | dashboard + engine read labels from `workflow_stage`; admin edits them | M | Low (needs workflow_stage seeded/authoritative; no gate rename) | Medium (label assertions) | High | Medium (labels configurable; keys/gates still non-neutral) | **squarely #6** (workflow-admin owns it) |
| **3. Canonical rename / migration** | rename gate names + keys to neutral canonical ids | L | **High** — migrate 500+ gate rows, slot enum, selftests, seeds, testids | High | High | **Highest** | needs #6's engine-native-vs-editable decision first |
| **4. Alias layer (recommended)** | gate name = frozen documented canonical id; single editable label source (`stage_label`); naming glossary; de-dup A/B/C | M | **none** (no gate rename) | Low-Medium | High | High (canonical stable + documented; label clearly separate) | complements #6 |

## 5. Risk analysis

- **Renaming gate names (Option 3) is the dangerous path**: `final_review` etc. are persisted identity in 500+ gate_decision rows + every selftest/seed/engine-transition string. A rename is a data migration + a broad code sweep with real regression surface against the #3/#4-stabilized flows. Not worth it for a *labeling* problem.
- **Three hardcoded catalogs (A + B) are the root cause**: even a perfect label editor in C won't fix confusion while A and B hardcode their own labels/keys. Any option must **collapse to one label source** or the divergence persists.
- **Dashboard-vs-engine stage-set divergence** (B omits native/scholar/production) is a latent correctness/expectations gap independent of labels — worth surfacing under #6.

## 6. Recommended path — Option 4, sequenced

1. **Freeze the gate name as THE canonical internal identity** (it already is, in the DB). Do **not** rename it. Document this in a **naming glossary** (canonical gate name ↔ meaning ↔ current label ↔ slot status), so `final_review` = "pre-production sign-off" is unambiguous in logs/DB/debugging regardless of the display label.
2. **One editable label source**: make `workflow_stage.stage_label` the single operator-facing label, and have the dashboard (B) and engine label lookups (A) read from it instead of hardcoding — removing the triplicated label. This is where "Publish approval → Pre Production Approval" becomes a no-code admin edit.
3. **Optionally align the dashboard short keys** (`final`→`final_review`) to the canonical gate name to kill the last alias — *low-risk code+testid change, no data migration*. Defer if it risks scope; the glossary covers the gap meanwhile.
4. **Do not touch** slot-status enum names (`APPROVED_ASSIGNED`) — out of scope; document their mapping in the glossary.

## 7. #39 vs #6 — split

- **#39 (standalone, sequence FIRST):** the *naming-architecture decision* — declare gate name canonical, author the glossary, and de-duplicate the three catalogs into one label source. This is broader than admin UI and must be decided before #6 builds an editor (it defines what "a stage" canonically is).
- **#6 (delivers the mechanism):** the *admin label-editing surface* on `workflow_stage.stage_label` (workflow-admin already reads `/workflows`), plus the "engine-native vs admin-editable stages" clarification #6 already scopes. The label editor is a #6 slice consuming #39's model.
- Recommendation: **keep #39 open as the decision/architecture umbrella; cross-reference #6 as the delivery vehicle for the editable-label slice.** Correct my earlier #39 note: `workflow_stage` has `stage_label` (single), **not** `display_name_ar/en` (those are on `principal`) — bilingual stage labels would be a separate additive column if wanted.

## 8. Proposed acceptance criteria

**#39 (naming architecture):**
- Gate name is documented as the canonical, immutable internal stage identity; a glossary maps canonical id ↔ meaning ↔ current label ↔ slot status for all engine stages.
- The three catalogs (engine A, dashboard B, DB C) are reconciled to a single label source; no stage label is hardcoded in more than one place.
- Debug/log/DB references use the canonical gate name; troubleshooting is unambiguous regardless of display label.
- No gate-name/slot-status migration required; no review/approval/generation semantics change.

**#6 (delivery slice):**
- A stage's operator label is editable via workflow-admin (`workflow_stage.stage_label`) without code changes; the change reflects in the review surface.
- "Engine-native vs admin-editable" stage boundary is documented; dashboard stage-set is reconciled with the engine catalog (or the divergence is explicitly justified).

## 9. Ambiguities to resolve before implementation (documented, not guessed)

- **Where is `workflow_stage` seeded, and does it currently agree with engine.py A?** Not in base `schema.sql`; likely a migration (`013–019`) or `loader/`. Must confirm C's current contents before making it authoritative.
- **Is the dashboard's omission of `native_review`/`scholar_review`/`production_review` intentional** (curated operator view) or drift? Affects whether B should mirror A.
- **Bilingual stage labels** — desired? `workflow_stage` has only `stage_label` today.

## 10. Exact next directive (if implementation approved)

> "Implement #39 slice 1 — canonical naming glossary + single label source — CC only (OR). Author `docs/…/workflow-stage-glossary.md` (canonical gate name ↔ meaning ↔ label ↔ slot status). Confirm `workflow_stage` seed contents vs `engine.py`. De-duplicate labels: dashboard `STAGES` + engine label reads consume one source. Do NOT rename gate names or slot-status enums. Frontend+read-only-config only; one PR `Refs #39`; stop if a gate/enum migration is required."

## 11. Attestation
- Read-only: `gh issue` reads + code/schema greps + read-only `SELECT count(*)` on gate/gate_decision. **No DB mutation, no migration, no code edit, no GitHub mutation, no PR, no Pi.**
- No internal keys renamed; no tests altered. Housekeeping deferred. This brief is uncommitted.
