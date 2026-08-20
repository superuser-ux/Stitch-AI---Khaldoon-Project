# Stage 2B-3 (#315) — client evidence reconciliation (weakest-defensible)

Bounded evidence record for #315 (bilingual / responsive / accessibility completion of the V2 Topic
review surface over the already-shipped #313 per-item and #314 bulk/presentation-order semantics). It is
reconciled at the **weakest defensible evidence** and makes **no** overclaim. A GitHub issue/PR is
evidence that something was *considered/defined*, never that it is *implemented*.

## What #315 evidences (and only this)
- V2 UX **presentation** of the established governed Topic workflow: deterministic four-state bilingual
  rendering (Arabic-only / English-only / bilingual / missing) of the canonical read-model pairs
  (`change_summary_ar`/`change_summary_en`), with truthful **per-node** `lang`/`dir` + Unicode bidi
  isolation, and explicit single-side fallback disclosure (a missing counterpart is disclosed, never
  fabricated).
- **Source-byte integrity (Codex Option B, comment 5011184074)** — split into the two claims that are
  actually true, with **no** raw-whitespace-persistence claim:
  - **Raw V2 transmission is proven**: the only source write is the deliberate structured edit, which
    transmits the reviewer's value **byte-for-byte** on the wire (`trim()` is only the non-empty submit
    predicate, never a transform). V2 applies **no** client normalization.
  - **Server canonicalization of a newly authored edit remains existing behavior**: the shared server's
    `edit_revision` canonicalizes with `strip()`. That is pre-existing shared/**V1** backend behavior;
    #315 does **not** alter it (removing it would exceed this UX/evidence slice). The e2e asserts **and
    discloses** the server-canonicalized persisted value rather than claiming whitespace preservation.
    This is **not** a #315 defect.
  - **No display/fallback normalization is persisted, proven by EXECUTING the paths NON-VACUOUSLY**: the
    byte e2e discovers a deterministically eligible run and performs a **successful** live bulk
    disposition (outcome `succeeded`) **and** a **successful** live presentation reorder (the governed
    token/version **advances**, not a conflict) through real V2 → `/gw` → canonical commands, then shows
    the affected slots' canonical Topic **source** bytes are byte-for-byte unchanged before/after
    (approve/reorder never rewrite `body`; reorder is presentation-only). The conflict path is proven
    SEPARATELY (it is not a substitute for the success proof). Display transitions (language toggle,
    inspect/history) are exercised too, and the append-only history preserves all prior revision bytes.
- Correct language semantics: the document chrome stays `lang="en"`; direction switching flips only `dir`.
  The shared direction control **synchronizes to the authoritative `<html dir>` after hydration** (it
  cannot drift on client navigation/mount) and exposes an explicit `aria-pressed` state with a **stable**
  accessible name.
- Accessibility: keyboard-only operation with no traps and **focus restoration to an announced
  `role=status`/`alert` region after per-item, bulk AND reorder commands** (success and typed
  conflict/error) — no dialog-dismissal is claimed (there are no dialogs); stable accessible names across
  language/fallback states; reduced-motion usability; and 375/768/1280 × LTR/RTL coverage for
  per-item / bulk / reorder — through the production-shaped V2 → `/gw` → live API/read-model path.
- Truthful operational states as a **closed deterministic matrix**
  (loading/empty/busy/denied/stale/conflict/partial/error) over the per-item/bulk/reorder surfaces, each
  driven by a controlled fixture with its typed reason and accessible announcement asserted — deterministic
  evidence, not observational coverage, and **no conditional skips**. Canonical mutation/CAS/idempotency/
  source-byte claims are proven on the live path; controlled UI interception is used only for deterministic
  display/error-state rendering.

## CP status ceilings (binding — do not exceed)
| CP | Ceiling | Note |
|----|---------|------|
| CP-008 | **partial** | topic gen + governed review live-proven; **no native-Levantine/dialect acceptance baseline; promotion/campaign unproven** |
| CP-022 | implemented | dashboard approval inbox |
| CP-023 | **partial** | ANY/ALL quorum exists; per-item CCO→manager routing UX unproven |
| CP-024 | **below implemented** | held below implemented while **#237** (loss of detail after approval) remains open |
| CP-025 | implemented | permanent attributable audit |
| CP-026 | **partial** | version history/restoration + full client-facing history unproven |
| CP-027 | **partial** | no complete brand-safety/tone/claims compliance service |
| CP-028 | **blocked-input** | secure credential/OAuth2 provisioning |
| CP-029 | **partial** | **production OIDC disabled; named client roles not operational** |
| CP-030 | **blocked-input** | UI/RTL substantially covered; **availability/retention/recovery + measured KPI baseline not accepted** |

## Explicit non-claims (#315 asserts NONE of these)
Native-Levantine/dialect acceptance · comprehensive brand-safety/compliance · production OIDC / named
client roles / Council restriction operational · promotion/campaign coverage · any NFR / availability /
retention / recovery / KPI baseline · production readiness.

## Stage 2C (#316) — RESOLVED as REJECT; Stage 2 still OPEN/HOLD on a different gate
**#316 (Stage 2C) is CLOSED as REJECT/STOP** ([#316 closeout](https://github.com/Kholio/tanaghom/issues/316)).
The bounded Payload / NocoBase / Directus control-plane adapter proof rejected all three candidates
on-merits, and **#294's external-adapter expectation was cancelled** — Tanaghom remains the sole
governed authoring/configuration and active-run authority; **no external-adapter dependency or
external-adapter P0/P1 remains**. #315 performed no #316 work and makes no Stage 2 closeout claim.

**Stage 2 nevertheless remains OPEN / HOLD** — not on any adapter, but per the #327 Stage 2 exit
reconciliation ([#327 report/reconciliation/closeout](https://github.com/Kholio/tanaghom/issues/327)):
- **#294 DoD item 9 (client acceptance evidence) is a P1 pre-close gate — NOT MET.** No immutable
  post-merge **deployment / client-acceptance** evidence exists (per-slice merge-head gates record
  *no deploy*, and this record makes no closeout claim). Closing this P1 requires a **separately
  authorized deployment/client-acceptance directive**; it is not satisfied here.
- **Governed `topic_generation_policy` create/activate authoring is a provisional P2 — non-blocking,
  separately scheduled.** The default governed generation is the retained safe path; a bounded
  governed endpoint is the future path. **Direct DB administration is never a fallback.**
  (`repetition_policy` already has governed administration — not in scope here.)

Stage 2 may be considered closed only after the item-9 P1 gate is satisfied and #294's exit criteria
are reconciled ([#294](https://github.com/Kholio/tanaghom/issues/294)) — **this document asserts no
Stage-2-closed/completed claim.** The CP ceilings and explicit non-claims above are unchanged.

## Boundaries
V2-only; V1 reference-only (no fallback, no V1 per-PR full-suite gate); no schema / backend-authority /
provider / model-route / control-plane / deploy / Stage-3 / #316 change. The dirty canonical checkout was
never touched.
