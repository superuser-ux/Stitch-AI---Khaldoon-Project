# Client Dry-Run Feedback — GitHub Assimilation & BUG-001 Root Cause

Author: CC · Date: 2026-07-06 · Status: **uncommitted handoff**
Source: client/operator dry run on the live client-trial stack (operator account).

> **Consolidated report for three directives** (per owner request):
> 1. *Assimilate dry-run feedback + start BUG-001* → §1–§9
> 2. *Client reference-card UX addendum* → folded into §10
> 3. *Content-library reference UI assimilation* → §10
> All GitHub mutations across the three are summarised in §10.4. No implementation occurred in any of
> the three; BUG-001 (#47) remains the first implementation target.

---

## 1. Dry-run item → GitHub mapping

| # | Dry-run item | Category | Decision | GitHub home |
|---|--------------|----------|----------|-------------|
| RC-001 | Universal Inline Editing | Requirement | Comment (expand scope) | **#14** (existing) |
| BUG-001 | Content Count / Telemetry Inconsistency Across Pipeline | Bug | **New** | **#47** |
| BUG-002 | Content Regeneration Not Reflected in UI | Bug | **New** | **#48** |
| BUG-003 | User Topic ID Not Mapped to System ID | Bug | **New** | **#49** |
| RC-002 | Framework Elements Must Be Properly Represented | Requirement | **New child of #7** | **#50** |
| RC-003 | Framework Changes Should Cascade Correctly | Requirement | **New**, linked to #14 | **#51** |
| UX-001 | Top Telemetry Panel Consumes Excessive Screen Space | UX | Comment (already scoped) | **#20** |

No existing issue was a correct home for the three bugs, the topic-ID mapping, or the cascade
requirement (confirmed by keyword search: `count`, `telemetry`, `regeneration`, `version`,
`topic id`, `framework`, `cascade`, `collapsible`, `reconcile`). #14/#16/#20/#9 are related but not
duplicates. No issues were closed. No closed issues were reopened.

## 2. New issues created

| Issue | Title | Labels |
|-------|-------|--------|
| **#47** | BUG: Content counts and telemetry inconsistent across pipeline stages | `bug`, `area:review-ui`, `priority:p1` |
| **#48** | BUG: Regenerated content is not reflected as active in the UI | `bug`, `area:review-ui`, `priority:p1` |
| **#49** | BUG: User-facing topic IDs are not mapped to internal system IDs | `bug`, `area:review-ui`, `priority:p1` |
| **#50** | Requirement: Surface actual framework elements on topic cards | `enhancement`, `area:review-ui`, `area:content-types`, `priority:p1` |
| **#51** | Requirement: Structural content edits should cascade coherently | `enhancement`, `area:review-ui`, `area:content-types`, `priority:p2` |

## 3. Existing issues updated (comments only)

- **#14** — dry-run comment: RC-001 scope **expanded** to *universal* editing incl. generated
  metadata (pillar/format/framework/hook), with the cascade concern explicitly split into #51.
  `issuecomment` posted.
- **#20** — dry-run comment: UX-001 is direct client evidence for the existing P1 header-consolidation
  + P2 collapsible/exception-lane scope. No duplicate created.
- **#7** — dry-run comment: RC-002 card-level framework surfacing split into focused child **#50**;
  #7 stays the operational-alignment umbrella.

## 4. Missing labels (reported, not created)

The repo has no equivalent for these suggested labels; closest existing labels were applied instead,
and each issue body is grounded in "client dry-run" so provenance survives without a label:

| Suggested | Status | Applied instead |
|-----------|--------|-----------------|
| `priority:p0` | **missing** | `priority:p1` (highest existing) |
| `type:bug` | missing | `bug` |
| `type:requirement` | **missing** | `enhancement` |
| `type:ux` | **missing** | (none; body-tagged) |
| `area:pipeline` | **missing** | `area:review-ui` |
| `area:content-model` | **missing** | `area:content-types` |
| `client-feedback` / `trial-feedback` | **missing** | (body "Source: client dry-run") |

> Recommendation (owner decision): create `priority:p0`, `type:requirement`, `type:ux`,
> `client-feedback`, `area:pipeline` so backlog triage reflects client-trial risk. Not created here
> (label creation was not in the authorized mutation set).

## 5. Recommended priority order (client-trial risk)

1. **BUG-001** #47 — content count / telemetry inconsistency *(root-caused below)*
2. **BUG-002** #48 — regeneration UI synchronization
3. **BUG-003** #49 — user-facing topic ID mapping
4. **RC-001** #14 — universal inline editing expansion
5. **RC-002** #50 — framework elements on topic cards
6. **RC-003** #51 — cascading structural edits
7. **UX-001** #20 — top telemetry panel / collapsible control surface

Correctness bugs (#47/#48/#49) outrank docs/help/expansion (#44/#45/#46) and layout work (#20).

## 6. What is client-trial blocking vs deferrable

- **Trial-confidence blocking:** #47 (can't trust any number), #48 (can't confirm a requested change
  landed), #49 (can't reliably reference an item). These undermine the core review loop.
- **Important, not blocking:** #50 (framework visibility), #20/UX-001 (screen space).
- **Deferred for product/design decision:** #14/RC-001 (edit + audit model), #51/RC-003 (dependency
  cascade model). Do not implement in stabilization.

---

## 7. BUG-001 — root-cause investigation (read-only; dev/stub stack only)

**Method.** Deterministic reproduction on the **dev/stub API `:8009`** (never client data). Planned a
`7 days × 2/day = 14` run and snapshotted counts at **every layer** through schedule → topic, including
a request-change + regenerate. Script: `scratchpad/repro_bug001.py`. Repro rounds: `R205` (and `R204`
from a first pass) — disposable dev data, safe to delete.

**Count sources identified (4 independent derivations):**

| Src | Where | Basis | Scope |
|-----|-------|-------|-------|
| A | `engine.list_rounds` (`GET /rounds`) → round-row KPIs, `roundApprovedCount` | `slot.status` FILTER counts (canonical status names) | round-wide |
| B | `engine.stage_state` `review_pending/awaiting/dropped/advanced` | `slot.status` grouped by **stage-config** status lists | round-wide |
| C | `engine.stage_state` `in_review/approved/sent_back/pending` | length of the **open gate's** `targets` | gate-scoped |
| D | frontend `disposition` memo (`review-context.tsx:864`) | **mixes** B (`review_pending`) with client filters over `gate.targets` | mixed |
| E | visible cards | `gate.targets`, client-filtered/ordered | gate-scoped |

**Evidence (actual numbers):**

```
plan 7×2                      -> total = 14                         (planner correct)
schedule open gate            -> review_pending=14, gate targets=14, telemetry=14   (MATCH)
approve all + resolve         -> advanced=14, schedule_approved=14
generate topics (stub)        -> job total=14, done=14; topic review_pending=14, topic_proposed=14
topic open gate               -> review_pending=14, in_review=14, cards=14, telemetry total=14   (MATCH)
request-change 1 + regenerate -> review_pending=13, awaiting=1, in_review=13, cards=13, total=14
```

**Finding — there is NO backend arithmetic bug in the happy path.** Every layer reconciles when read
fresh together. `open_gate` targets *every* slot at the review status, so `len(targets) == review_pending`
at open; after a change-request the awaiting item leaves both the status count and the gate, so
`13 == 13` still holds, with `total=14` correctly accounting for the 1 awaiting item.

**So the client-observed inconsistency is multi-layer, not a formula bug:**

1. **Cross-fetch timing skew (primary).** Telemetry `disposition.inReview` reads **B** (`review_pending`,
   round-wide) while cards render from **E** (`gate.targets`). `fetchStageSnapshot` fetches B+C together
   (consistent), **but** Source A (`loadRounds`) and the `reassertStageSnapshot` timers fire on
   **separate cycles** (`review-context.tsx:349-357, 368, 381`). Between a decision and the next full
   snapshot, one number can update while another lags — a transient telemetry≠cards window that widens
   **under load** (the client's exact wording: "do not *always* match").
2. **In-flight items counted but not visible.** An awaiting-regeneration item leaves the visible gate
   (`cards=13`) but stays in totals (`awaiting=1`, `total=14`). Correct data, but nothing on the surface
   reconciles it → reads as "counts don't match the cards." Entangled with **#48 (BUG-002)** and
   **#20/UX-001** (the exception lane is easy to miss).
3. **No run-level funnel.** Per-stage numbers legitimately differ (14 planned → 14 topics → N approved →
   N scripts). Without a run-level invariant/funnel surface, different per-stage counts read as
   inconsistency. **This is partly a product decision** (what the authoritative run-level count contract
   is, and whether/how to show in-flight items).

### 7.1 Decision: STOP before coding (per task rule)

BUG-001 is **multi-layer AND requires a product decision** (authoritative count contract + in-flight
surfacing), and the obvious frontend change is **state-dependent** (see below), so it is **not** the
"clear + bounded + no product decision" case the task authorizes for immediate implementation.
Per the explicit instruction — *"If BUG-001 requires product decision or schema migration, stop and
report"* / *"if root cause is multi-layer, stop and report with a fix plan before coding"* — **no
product code was changed.**

### 7.2 Fix plan (staged)

**Phase 1 — single-snapshot counts (bounded, no schema, no product decision).**
Make the review surface derive **all** its counts from the **one** `stage_state` payload that also
produced the rendered `gate.targets`, instead of mixing round-wide `review_pending` into
`disposition.inReview`:
- when a gate is open: `inReview := stage_state.in_review` (== `gate.targets.length`), and
  `approved/sentBack/rejected/pending` from the same gate-scoped fields;
- keep `awaiting/dropped/advanced` from the same payload;
- stop letting Source A (`loadRounds`) feed any number the review surface displays as "pending/total".
- **Subtlety to handle:** in the pre-open `ready_to_start` state there is no gate, so the summary must
  intentionally fall back to `review_pending` (items ready but review not started, 0 cards). This
  state-dependence is exactly why this needs a small, tested change rather than a blind field swap.
- **Regression test:** assert the invariant on a deterministic run —
  `telemetry.inReview === visibleCards.length === stage_state.in_review`, and
  `total === in_review + advanced + awaiting + dropped`, across open / post-approve / post-change-request.
  Run the full Chromium pack (touches shared review-context/telemetry).

**Phase 2 — in-flight visibility + run funnel (needs product/UX decision — DEFER).**
Surface awaiting-regeneration items and a run-level funnel so cross-stage numbers are explained.
Converges with **#48 (BUG-002)** and **#20/UX-001 (#20)**; should be scoped with those, not bolted on.

### 7.3 BUG-001 outcome

- Root cause: **found and bounded** — no backend arithmetic defect; the defect is
  frontend multi-source/multi-cycle count derivation + unsurfaced in-flight items + missing run-level
  contract.
- Implementation: **not started** (stopped per rule; product decision + full-pack scope).
- PR: **none** (no code changed).
- Validation: reproduction script + captured evidence above; **no assertions weakened, no retries added.**

## 8. Next recommended issue after BUG-001

Once the BUG-001 Phase-1 count-source consolidation is approved and landed with its invariant test,
proceed to **#48 (BUG-002)** — regeneration UI synchronization — which shares the same
refresh/active-version machinery and would be validated by the same review-context test surface.

## 9. Owner decisions needed

1. **BUG-001 authoritative count contract** — approve Phase 1 (single `stage_state` snapshot feeds all
   review-surface counts) so CC can implement + add the invariant test. Confirm the pre-open fallback
   (show `review_pending` when no gate is open) is acceptable.
2. **In-flight surfacing / run funnel** (Phase 2) — product/UX decision; sequence with #48 + #20.
3. **Labels** — approve creating `priority:p0`, `type:requirement`, `type:ux`, `client-feedback`,
   `area:pipeline`, `area:content-library`, `area:content-lifecycle` (§4, §10.5).

---

## 10. Content-library reference UI assimilation
### (a.k.a. "Full content-library reference UI observations")

Covers directives 2 (client reference **card** UX addendum) and 3 (client **Content Library** full-page
reference UI — issued twice; the second, fuller re-issue added only the IA/navigation ask in §10.7-D,
which is now handled). The client provided a full-page reference from another content/campaign system.
**The reference screenshot is held privately by the owner — it was NOT attached to any GitHub issue and
the other product is NOT named**, per the privacy/no-cloning constraint. Patterns are described as
principles, not a UI to copy.

### 10.1 Patterns extracted from the reference

| Pattern | What the reference does | Tanaghom mapping |
|---------|-------------------------|------------------|
| Compact KPI cards | 4 single-number cards (Saved / Approved / Ready-for-scheduling / Drafts), thin accent underline | UX-001 / **#20** (compact vs tall telemetry) |
| Workspace-first layout | Cards dominate; context is slim header + filter bar | UX-001 / **#20** |
| Filter bar | Event · Campaign · Platform · Status | **#16** (round/campaign · stage · status · format · pillar/framework · readiness) |
| Card semantic anatomy | platform+type+status chips · title · context line · body preview · distinct `CTA:` · hashtags · readiness | RC-002 / **#50** |
| Per-card edit affordance | pencil icon on every card | RC-001 / **#14** |
| Approved ≠ Ready-for-scheduling | separate states, actions, and counts | **#53** (new) + **#18** (safeguards) |
| Reusable approved-asset surface | a "Content Library" outside the run/review flow | **#52** (new) |
| Governed destructive action | Delete per card | **#18** |
| Arabic/RTL + mixed EN | RTL titles/body with LTR `CTA:`, `Learn More`, EN/AR hashtags | **#54** (new) |

### 10.2 Existing issues updated (comments only — no duplicates created)

- **#14** (RC-001) — per-card edit affordance; expand text-only → all AI-generated attributes; audit/cascade stay separate.
- **#20** (UX-001) — compact KPI cards + workspace-first; collapsible summary vs tall telemetry block.
- **#16** — validates Event/Campaign/Platform/Status filters; lists Tanaghom analogues.
- **#50** (RC-002) — semantic card anatomy; expose real framework/content metadata, CTA + hashtags separated from body.
- **#18** — Approved ≠ Ready-for-scheduling; delete needs lifecycle safeguards; cross-links #52/#53.

### 10.3 New issues created (only where genuinely uncovered)

| Issue | Title | Labels |
|-------|-------|--------|
| **#52** | Content library for approved and reusable campaign assets | `enhancement`, `area:content-types`, `priority:p2` |
| **#53** | Scheduling readiness state for approved content | `enhancement`, `area:content-types`, `priority:p2` |
| **#54** | Arabic/RTL review-card readability and mixed-language content polish | `enhancement`, `area:review-ui`, `priority:p2` |

Confirmed no existing home (searched `content library`, `reusable`, `scheduling`, `ready for scheduling`,
`asset`, `RTL`, `Arabic`). #52 is distinct from **#18** (run lifecycle) — it is a post-approval *content
asset* surface, not run management.

### 10.4 Intentionally NOT created (avoided duplication)

- Left-nav / module IA → covered by **#20**/**#11**.
- Compact telemetry → **#20**.
- Inline edit icon → **#14**.
- Filtering → **#16**.
- Card framework metadata → **#50** (child of **#7**).

### 10.5 Missing labels (reported, not created)

`area:content-library`, `area:content-lifecycle`, `client-feedback` — closest existing applied
(`area:content-types` / `area:review-ui`), provenance body-grounded. Adds to the §4 label list.

### 10.6 Confirmation

- **No implementation, no code, no UI redesign, no new component work.** GitHub-only assimilation.
- **Reference screenshot not exposed** in any issue; other product not named.
- Critical-fix priority **unchanged** — the reference informs RC/UX/library backlog only.

### 10.7 Explicit surface decisions (required by the re-issued directive)

- **B — Content library vs #18: SEPARATE.** #18 is run lifecycle (edit/archive/restore/delete runs).
  A *post-approval reusable-content-asset* surface is a different concern → filed as **#52**, cross-linked
  to #18/#16/#14/#20/#50. #52 complements #18; it does not duplicate it.
- **C — Scheduling readiness: SEPARATE (#53), not folded into #52.** Rationale: "ready for scheduling"
  is a **lifecycle state** that spans review → library → future scheduling, not just a library
  sub-feature; keeping it a distinct issue lets the state be defined once and referenced by both #52 and
  #18. Cross-linked accordingly. (If the owner prefers it folded, #53 can be closed into #52 — flagged as
  a reversible call, not a duplicate.)
- **D — IA / navigation: COMMENT on #20, no new broad IA issue.** The reference implies clean module
  separation (review workspace · content library · admin/config · help). Recorded as a comment on #20
  noting the new #52/#53 surfaces should be **sibling top-level modules**, not extra review panels.
  No standalone IA issue — #20 (review-surface IA) and #11 (agent-first layout) already cover it, per the
  directive's own guardrail.
- **Three separate surfaces affirmed** (not collapsed into the review screen): **(1) review workspace**,
  **(2) content library #52**, **(3) scheduling readiness #53**.

## 11. Final consolidated priority order

1. **BUG-001** #47 — content count / telemetry consistency *(root-caused; first implementation target)*
2. **BUG-002** #48 — regeneration UI synchronization
3. **BUG-003** #49 — user-facing topic ID mapping
4. **RC-001** #14 — universal inline editing expansion
5. **RC-002** #50 — framework elements on topic cards
6. **RC-003** #51 — cascading structural edits
7. **UX-001** #20 — telemetry panel compactness
8. *(new backlog, p2, below the above)* **#52** content library · **#53** scheduling readiness · **#54** Arabic/RTL card polish

## 12. Complete GitHub mutation ledger (three directives)

**New issues (9):** #47 BUG-001 · #48 BUG-002 · #49 BUG-003 · #50 RC-002 · #51 RC-003 · #52 content library · #53 scheduling readiness · #54 Arabic/RTL · #55 clickable telemetry.
**Comments (14):** #7 · #14 (×2) · #16 (×2) · #18 · #20 (×4, incl. IA + clickable) · #47 (×2, root cause + dep) · #50.
**No issues closed or reopened. No code changed. No labels created. No screenshot exposed; other product not named.**

---

## 13. Clickable telemetry and filter-navigation feedback

Client dry-run asked that telemetry labels/counts be **clickable** — clicking a count should filter the
current surface (or navigate to the corresponding stage/context), with visible, reversible filter state.

**Coverage decision.** Neither #16 (filter *controls/dropdowns*) nor #20 (telemetry *compaction*)
explicitly owns the **chip-as-filter/nav interaction** (confirmed by search: `clickable telemetry`,
`telemetry filter`, `status chip filter`, `count chip`, `KPI card filter`, `context navigation` — only
keyword-coincidence hits on #16/#20/#50). → **Created a focused issue, #55**, linked to #16/#20/#47.

**#55 — Clickable telemetry labels for filtering and context navigation** (`enhancement`,
`area:review-ui`, `priority:p1`). Behavior tracked: Pending/Approved/Dropped/Change-requested chips
filter to their items; stage counts navigate; active filter visible + reversible; empty states explain
the active filter; **filtered cards must match the clicked count**.

**Cross-refs added:** #16 (chips as first-class filter triggers), #20 (make compact counts actionable),
#47 (BUG-001 dependency).

**Critical dependency — flagged, not glossed over.** #55 is **gated on #47 (BUG-001)**: with counts
derived from multiple sources on different refresh cycles, a clickable count could filter to a set that
doesn't match its own number. #55 must be built on the single authoritative snapshot from BUG-001
Phase 1 and validated with a count-to-filter reconciliation test. **BUG-001 remains the first
implementation target; #55 sequences after it.**

**Recommended implementation order:** `#47 (fix counts) → #55 (make the now-trustworthy counts clickable)`
— #55 is the natural, high-value follow-on to BUG-001 on the same review-context surface, and can share
its reconciliation test. No implementation occurred.
