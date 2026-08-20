# Stabilization Umbrella (#1) — Reassessment

Date: 2026-07-05
Author: CC (reassessment pass, read-only; no GitHub/DB mutation)
Tracking issue: `#1 — Stabilization release gate and regression-control workflow` (P0, `type:process`, currently `status:in-validation`, OPEN)
Prompt: "Stabilization Umbrella Reassessment — CC only (OR)"

---

## 1. TL;DR recommendation

**Recommended #1 state: CLOSE #1 as completed, and split the perpetual-enforcement remainder into a new lower-priority standing process issue (Option 3).**

Rationale in one line: #1's *written* acceptance (checklist exists + adopted; every stream maps to an issue; mixed-bundle discipline demonstrated) is now fully met with hard evidence, and the only residual — perpetual enforcement + a class-level stateful-action audit — is a standing concern that should not sit as an open **P0 `status:in-validation`** umbrella, per the release-gate doc's own "split follow-up into separate tracked issues" rule.

Conservative alternative (Option 2): keep #1 open with a single explicitly-narrowed remaining gap (the cross-cutting stateful-action audit as a written artifact), if the owner considers that comment-added scope part of #1 rather than a separable stream.

**No true release blockers remain.** Everything else is housekeeping.

---

## 2. #1 acceptance matrix

Original written acceptance (from the issue body):

| # | Acceptance criterion | State | Evidence |
|---|----------------------|-------|----------|
| A1 | **Written release gate checklist exists and is adopted** | ✅ MET | `docs/16_Release_Gate_and_Delivery_Control.md` (6.6 KB, "Status: active internal operating rule", dated 2026-07-03) — covers Core Rule, Delivery States, Mandatory Evidence, Green Status, Validation Sequence, Merge Gate, Feedback Intake/Routing, GitHub Usage, Continuity rule. `.github/pull_request_template.md` encodes the Release Gate as literal checkboxes. Adoption declared in #1 comment 2026-07-03T05:39 ("added to the repo and adopted as the active delivery rule"). **Enforced in practice**: PR #26 body followed the template structure. |
| A2 | **Each active implementation stream maps to a GitHub issue** | ✅ MET | Release-gate doc §"Current active issue map" lists #1–#11. Live tracker shows 21 open issues (#5–#24) covering every stream: planner (#4→closed, #7, #18), review-ui (#3→closed, #14–#17, #20, #24), workflow-admin (#6, #9, #10, #21), telegram (#8), ops (#5, #23), agents (#11, #19, #21). Close-path proved routing: #3 split #24; the repeated-script-title finding was classified & routed (#22); the generation-poll bug cross-referenced #4. |
| A3 | **Future work stops landing as mixed-scope bundles without explicit acceptance evidence** | ✅ SUBSTANTIALLY MET (standing) | Demonstrated working twice on the close-path: (a) the Lunaris WIP — 47 files, mixed Lunaris+CR01+#3 — was **not** blindly merged; it was decomposed into 7 auditable per-concern commits and landed via **PR #26** with a full validation table in the body (148/0 api_selftest, 37/37 Playwright, gitleaks clean). (b) **#4** required clean-room extraction rather than merging the mixed bundle (**PR #25**). PR template now forces the "Scope matches one GitHub issue or one explicitly approved issue bundle" checkbox. This criterion is a *perpetual behavioral guarantee* — adopted and proven, but by nature never "finished." |

**Interpretation:** A1 and A2 are concrete deliverables and are done. A3 is a standing rule; its *deliverable* portion (PR template + doc + demonstrated enforcement) is done, its *enforcement* portion is perpetual.

---

## 3. Evidence by issue / PR

| Item | Outcome | Evidence |
|------|---------|----------|
| **#4** run planning & generation hardening | Closed / COMPLETED | Clean-room extraction from mixed WIP → fresh-main-schema validation (90/0 selftest) → **PR #25** merged to `main` (`ff33fba`). Generation poll → open-gate robustness fixed; full Chromium pack **30/30 twice** (#1 comments 2026-07-04T12:09). |
| **#2** sacrificial e2e rework validation | Closed / COMPLETED | Evidence-backed closure; live-run rework validated (`R1-D01-AM` hook change stayed in-scope; revision history + stored feedback aligned — #1 comment 2026-07-03T09:51). |
| **#3** review-surface hardening | Closed / COMPLETED | Lunaris/CR01 integration branch → full validation → **PR #26** merged to `main` (`7524a8f`, squash). Hardened regenerate/rework/approve-older/edit-note/stage-switch seams — the same seams named in the 2026-07-03T10:03 cross-cutting audit scope. |
| **#24** review-surface UX polish | OPEN (P2, non-blocking) | Split from #3 deliberately. Aligns with the release-gate doc's separate "focused quality review pass" (codified in #1 comment 2026-07-03T09:36) which is *after* functional green, not a stabilization-correctness gate. |
| **PR #25** | Merged | #4 planner/generation guards → `main`. |
| **PR #26** | Merged (squash `7524a8f`) | Lunaris + CR01 + #3 → `main`; auto-closed #3 via `Closes #3`. Head branch deleted. |

**What changed since the last "keep open" note (2026-07-04T20:07):** that note kept #1 open because the umbrella "still covers broader regression-control and stabilization work beyond the now-validated regenerate loop." Since then: **#2, #3, #4 all closed**, #3's review-surface hardening landed on `main`, and the full Chromium pack is green (30/30 twice). The broader regression-control work that note referenced has since landed. That rationale is now largely discharged.

---

## 4. Blockers vs. non-blocking follow-ups

**True #1 blockers remaining: NONE.**

| Candidate | Classification | Reasoning |
|-----------|----------------|-----------|
| Stale labels on closed #2/#3/#4 (`#2 status:ready-to-close`, `#3 status:in-validation`, `#4 status:in-validation` — all on CLOSED/COMPLETED issues) | Non-blocking hygiene | Release-gate doc tracks *delivery states* as prose, not label state; it imposes no label-consistency merge gate. Per directive constraint, stale labels are hygiene unless the workflow requires label-state consistency — it does not. |
| R54/R55 demo-data cleanup | Non-blocking (demo hygiene) | Release-gate doc requires a *green demo environment*, not an empty round history, for closure. Per directive constraint, demo-data hygiene is not an automatic #1 closure blocker unless the gate docs require it — they don't. |
| R2–R53 broader demo cleanliness | Non-blocking (demo hygiene) | Same as above. Belongs to demo-prep, not the release-gate deliverable. |
| #24 review-surface polish | Non-blocking (P2 follow-up) | Explicitly split; editorial/UX layer, gated *after* functional correctness by design. |
| Branch hygiene after PR #26 | Non-blocking (local hygiene) | Remote `pr/lunaris-cr01-review-integration` already deleted by `--delete-branch`. Local stale branches remain (`feat/ui-driven-runs` a38aa73 and `feat/review-surface` are now ancestors of `main` → prunable; `feat/lunaris-redesign` ahead-17 is the retired foundation). None are release blockers. |
| Generation single-worker-API hardening | Non-blocking (future note) | The generation-poll *bug* is fixed (30/30). The residual "single-worker under load" is a longer-term robustness note, no longer causing failures; track separately if desired (candidate for the new standing issue or #4-adjacent). |
| **Cross-cutting stateful-action audit as a written artifact** (from 2026-07-03T10:03) | Borderline — the one item with a real claim on #1 | The audit's *core seams* were hardened via #3 (regenerate/rework/approve/request-change/stage-switch/duplicate-click). A standalone written class-level audit doc was not produced. This scope was **added by comment**, not in the original written acceptance → per the doc's own rule it is a separable stream. Recommend re-homing into the new standing issue (Option 3) rather than blocking #1. |

---

## 5. Recommended #1 state — decision

**Primary: Option 3 — split standing governance + residual audit into a new lower-priority process issue, then close #1 as completed.**

Why Option 3 over the alternatives:
- **vs. "close outright" (Option 1):** closing with nothing to carry the perpetual-enforcement + un-written cross-cutting audit would drop a real (if low-priority) thread. Split-then-close preserves it.
- **vs. "keep open, narrowed" (Option 2):** #1 is P0 `status:in-validation`. Its concrete acceptance is met; leaving a P0 umbrella open indefinitely for a perpetual rule contradicts the release-gate doc's own Merge Gate ("any follow-up work is split into separate tracked issues"). A standing process rule is better represented by the *adopted doc + PR template* plus a low-priority tracking issue than by a perpetually-open P0.

**If the owner prefers to honor the 2026-07-04T20:07 "keep open" note verbatim → Option 2** with exactly one narrowed acceptance gap: *"Produce (or explicitly waive) the written class-level stateful-action audit from the 2026-07-03 comment; all other original acceptance is met."* Everything else moves to follow-up.

---

## 6. Draft GitHub comment for #1 (DO NOT POST without authorization)

> ## Stabilization umbrella reassessment (2026-07-05)
>
> Re-evaluated #1 against its written acceptance now that the close-path is complete (#2, #3, #4 all closed; PR #25 and PR #26 merged to `main`; full Chromium pack 30/30 twice).
>
> **Acceptance status**
> - ✅ **Written release gate checklist exists and is adopted** — `docs/16_Release_Gate_and_Delivery_Control.md` (active operating rule) + `.github/pull_request_template.md` (Release Gate checkboxes, followed by PR #26).
> - ✅ **Each active stream maps to a GitHub issue** — issue map in the doc; 21 tracked issues (#5–#24) cover every workstream; close-path routing (#3→#24 split, script-title→#22, poll bug→#4 xref) demonstrates it in use.
> - ✅ **Mixed-scope bundles no longer land without acceptance evidence** — demonstrated: the mixed Lunaris WIP was decomposed into 7 auditable commits and landed via PR #26 with a full validation table; #4 required clean-room extraction (PR #25) rather than a bundle merge.
>
> **No release blockers remain.** Non-blocking follow-ups: stale `status:*` labels on closed #2/#3/#4 (hygiene), R54/R55 + R2–R53 demo-data cleanup (demo hygiene), #24 UX polish (P2), local branch pruning, and single-worker-API hardening (future note).
>
> The one comment-added item still worth a home is the **class-level stateful-action audit** (2026-07-03) — its core seams were hardened via #3, but a standalone written audit was not produced.
>
> **Recommendation:** close #1 as completed and open a new lower-priority `type:process` issue to carry (a) standing release-gate enforcement and (b) the residual stateful-action audit / single-worker hardening notes. Alternatively, keep #1 open narrowed to just the audit item.
>
> Awaiting authorization before mutating issue state.

---

## 7. Draft new follow-up issue (DO NOT CREATE without authorization)

**Title:** Standing release-gate enforcement and class-level stateful-action audit
**Labels:** `area:stability`, `type:process`, `priority:p2`
**Body:**

> Carries the perpetual/standing portion of #1 after its written acceptance was met and #1 closed (2026-07-05).
>
> **Scope**
> - Ongoing enforcement of the release-gate rules in `docs/16_Release_Gate_and_Delivery_Control.md` and `.github/pull_request_template.md` (one issue = one branch = one acceptance target; mandatory evidence; merge gate).
> - Produce or explicitly waive the **class-level stateful-action audit** from #1 (2026-07-03): per-item vs batch, generate/regenerate/rework-from-version, approve/request-change/drop/undo/restore, round/stage switching mid-work, duplicate-click / overlapping-job protection, visible progress during background work. (Core seams already hardened via #3; this is the written class-level pass.)
> - Track single-worker-API-under-load hardening as a longer-term robustness note (no longer causing failures post-#4).
>
> **Explicitly not in scope:** feature delivery, #24 UX polish, demo-data cleanup.
>
> **Acceptance:** enforcement remains the active delivery rule; the stateful-action audit is either delivered as a doc or explicitly waived with rationale.

---

## 8. Exact next-owner authorization choices

Pick one path (nothing below has been executed; GitHub/DB untouched):

- **[A] Option 3 (recommended):** authorize — (1) post the §6 comment on #1, (2) create the §7 follow-up issue, (3) close #1 as completed. *Optionally* also fix stale labels on closed #2/#3/#4 as part of the same hygiene pass.
- **[B] Option 2 (conservative):** authorize — post a variant of the §6 comment, keep #1 OPEN narrowed to the single audit gap, do **not** create the new issue.
- **[C] Hold:** keep the reassessment on file, mutate nothing. (Current state.)
- **[D] Docs-tracking:** authorize committing this reassessment doc on a dedicated branch (`docs: reassess stabilization umbrella`) and opening a docs PR — separate from the #1 state decision. (This session did **not** commit it; it is left uncommitted per "do not push / one-issue-one-branch".)

Independent of the above, optional hygiene the owner may separately authorize (all non-blocking):
- Normalize stale `status:*` labels on closed #2/#3/#4.
- Prune merged local branches (`feat/ui-driven-runs`, `feat/review-surface`).

---

## 9. Process attestation

- No GitHub mutation (no comment, no close, no label change).
- No DB mutation. No Pi usage. No R54/R55 or R2–R53 cleanup. No cursor reset.
- No code edits. No PR created. No branch pushed.
- Only action taken: read issues/docs/branches and authored this reassessment file (uncommitted).
- #24 and #1 remain OPEN and unchanged; #2/#3/#4 remain CLOSED/COMPLETED.
