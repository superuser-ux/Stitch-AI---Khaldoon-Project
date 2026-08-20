# Stage 4 final-review backend read projection

Owning issue: **#427** · corrected by **#429** (roadmap ledger **#294**). A read-only **backend data
contract**, not a UI. It
resolves exactly one canonical **admitted final-review `(gate_id, slot_id)` target** and returns, in one
server-authoritative payload, the evidence a later reviewer surface would need — joined **entirely from
persisted records**. It composes existing frozen truths and invents none.

- **Module:** `gates/final_review_projection.py` → `read(cur, gate_id, slot_id)`
- **Endpoint:** `GET /gates/{gate_id}/slots/{slot_id}/final-review-projection` (read-only)
- **Proofs:** `gates/final_review_projection_test.py` (runtime-free unit matrix) +
  `gates/final_review_target_package_harness.py` (isolated ephemeral-Postgres, real FKs)
- **Additivity:** the #423 `GET …/target-package` route and its response shape are **unchanged**. This
  is a NEW route; no existing V1 route or shape is modified.

## Evidence sources & field authority (each field has exactly one source of truth)

| Group | Field authority | Persisted source |
|---|---|---|
| **1 Target identity** | `gate.stage`, `gate.status`, admission = row in `gate_target` | `gate`, `gate_target` |
| **2 Exact attached package** | immutable snapshot **only** — never current Topic/Script/workflow/selection | `final_review_target_package` (#423/#425/#426), via `final_review_target_package.read` |
| **3 Governing assignment** | gate-wide frozen snapshot **only** — never a target-level snapshot, never re-resolved membership | `gate_snapshot` / `gate_snapshot_token` / `gate_snapshot_eligible` (#282/#422), via `engine._load_gate_snapshot` |
| **4a Decision / coverage** | head-correct **persisted** coverage + `gate_decision` rows keyed to this exact `(gate_id, slot_id)` | `gate_token_coverage` (#321, via `engine._authoritative_target_projection`), `gate_decision` |
| **4b Audit** | **gate-scoped history only** — never slot-attributable (no canonical slot linkage exists) | `audit_log` (`entity='gate'`, `entity_id=gate_id`) |
| **5 Historical uncertainty** | typed status + machine-readable reason codes | derived from absence/consistency of 1–4 |

## Canonical attribution rule (#429)

A fact is attributed to `(gate, slot, snapshot)` **only** through an enforced persisted key/relation —
never through inference. Each evidence group is attributed **independently** by its own keys and carries
its **own** status; there is **no combined decision/audit status**, so an unavailable group can never be
hidden behind another group's success, and a group reports `recorded`/`available` only when the evidence
required for *that* group is canonically complete and unambiguous.

- The package row FK-links the frozen sources: `final_review_target_package (gate_id, slot_id)` →
  `gate_target`, and `(gate_id, snapshot_id)` → `gate_snapshot`. `gate_snapshot.gate_id` is `UNIQUE`,
  so a gate has **exactly one** governing gate-wide snapshot.
- **Decision/coverage** is admitted only when attributable to the same gate, slot, and governing
  snapshot: `gate_token_coverage` carries the `(gate_id, slot_id, snapshot_id)` triple directly;
  `gate_decision (gate_id, slot_id)` is attributable to the gate's single snapshot transitively.
- **Audit is gate-scoped history only.** `audit_log` has **no** canonical column tying a row to a slot
  or snapshot, so audit rows are exposed as gate-scoped history in a **separate** `audit_evidence` group
  and are **never** promoted to slot-attributable decision evidence. Gate association, actor identity,
  revision similarity, event kind, outcome, or timestamp proximity is **not** slot linkage. The
  `audit_evidence` group never reports `recorded`/`available` — it reports `gate_scoped_history` (events
  present) or `unavailable` (none), always carrying `audit_gate_scoped_not_slot_attributable`.
- **Consistency is fail-closed:** if the package's `snapshot_id` and the governing snapshot's id ever
  diverge, the read returns `inconsistent_snapshot_reference` and does **not** report `recorded`.
- **Ambiguity is fail-closed:** if decision attribution were ever ambiguous, `decision_evidence` reports
  a non-`recorded` status with `ambiguous_decision_attribution` and top-level success is withheld.

## Schema-impossible ambiguity boundaries (#429)

Two ambiguity cases contemplated by the directive cannot be represented by repository-realistic
persisted rows; they are documented rather than simulated, and the nearest feasible fail-closed case is
tested instead:

1. **Slot-attributable audit** — impossible. `audit_log (id, entity, entity_id, action, actor, detail
   jsonb, at)` has no FK or column relating a row to a `(gate, slot, snapshot)` triple. Audit therefore
   stays gate-scoped by construction. Nearest tested case: a gate-scoped audit row (and an unrelated
   `entity='slot'` row) is exposed only as gate-scoped history and never enters slot decision evidence.
2. **Whole-batch / NULL-slot decision ambiguity** — impossible. `gate_decision` PK
   `(gate_id, approver_id, slot_id)` forces `slot_id` NOT NULL, so a slot-unattributable decision cannot
   be persisted. The code keeps a defensive fail-closed check; the harness proves the write is rejected
   (`NotNullViolation`) rather than fabricating an impossible row.

## Typed historical limits

Top-level `status`: `recorded` (full, consistent evidence) · `unknown_history` (admitted final-review
target with missing/legacy/inconsistent authoritative evidence) · `unavailable` (malformed id, unknown
gate, non-`final_review` gate, or non-admitted pair — a typed status, never an endpoint error).

Top-level `uncertainty[]` describes the canonical **slot** evidence only (`missing_target_package_snapshot`,
`missing_governing_gate_snapshot`, `inconsistent_snapshot_reference`,
`legacy_record_predating_authoritative_snapshots`, `ambiguous_decision_attribution`,
`not_a_final_review_target`). The gate-scoped audit group is **self-describing** via its own
`audit_evidence.status` + `audit_evidence.reasons` (`audit_gate_scoped_not_slot_attributable`,
`incomplete_canonical_audit_evidence`) so its unavailability is neither hidden behind slot success nor
able to downgrade genuinely recorded decision/coverage. Successful reads may carry **partial** evidence
with explicit per-group status. Missing history is **never** backfilled, replayed, re-attested, or
reconstructed from current state — later changes to current Topic/Script/workflow/selection/membership/
role/group/label cannot alter a recorded projection (proved by the harness invariance check).

## Frozen eligibility ≠ present authorization

`assignment.tokens[].eligible_principals` is the **frozen historical eligibility** recorded at gate-open
— disclosed as history, under a name that is not an authorization field. This directive adds **no**
present-authority calculation, capability evaluation, or action-authorization inference. Present
authorization is a separate concern and is not computed or implied here.

## Payload shape

```jsonc
{
  "gate_id": "…", "slot_id": "…",
  "available": true,                         // true iff status == "recorded"
  "status": "recorded",                       // recorded | unknown_history | unavailable
  "target_identity": { "gate_id", "slot_id", "gate_stage", "gate_status", "admitted" },
  "package":    { /* final_review_target_package.read() verbatim: status + evidence */ },
  "assignment": {
    "recorded", "status", "snapshot_id", "snapshot_version", "opened_at", "rule_key",
    "tokens": [ { "token_kind", "token_key", "normalized_token", "eligible_principals": [ /* frozen */ ] } ]
  },
  "decision_evidence": {                       // canonical slot+snapshot attribution; NO audit here
    "recorded", "status", "reasons",            // fail-closed: not recorded if ambiguous
    "governing_snapshot_id",
    "outcome",                                // persisted decision state; EXISTING taxonomy (no new states)
    "approval_count", "distinct_principal_coverage",
    "coverage":  [ { "token_kind", "token_key", "normalized_token", "covered_by" } ],
    "decisions": [ { "approver_id", "decision", "revision", "decided_at" } ]
  },
  "audit_evidence": {                          // SEPARATE, gate-scoped history — never slot-attributable
    "scope": "gate", "slot_attributable": false,
    "status": "gate_scoped_history",            // gate_scoped_history | unavailable — never "recorded"
    "reasons": [ /* audit_gate_scoped_not_slot_attributable [, incomplete_canonical_audit_evidence] */ ],
    "events": [ { "id", "action", "actor", "at" } ]
  },
  "uncertainty": [ /* slot-evidence reason codes */ ]
}
```

`assignment` / `decision_evidence` are `null` when the governing gate-wide snapshot is absent (legacy
gate); `outcome` reuses the existing decision taxonomy verbatim — this projection introduces **no** new
decision-state classification and reinterprets no persisted decision semantics.

---

## Stage 4 in V2 — the operator vertical over this contract

Added by `ee36769` (`feat(stage4-v2): complete final-review vertical flow`). This section records what
the V2 surface actually does, so no reader has to infer authority from the UI. It adds a **path**, not
authority: no new decision or resolve service, no new lifecycle transition, no backend or schema change.

### The four gestures, and what each one is

Stage 4 is **four separate, explicit operator gestures**. None triggers another, and none is implied by
the result of the one before it.

The canonical order is **inspect → decision → sign-off → resolve**.

| Order | Gesture | Kind | What it actually does |
|---|---|---|---|
| 1 | **Inspect** | read-only | Renders the projections above. Approves nothing, advances nothing. |
| 2 | **Decision** | **canonical approval authority** | The canonical governed decision, taken **through the gate**. This — and only this — is approval authority. |
| 3 | **Sign-off** | **immutable evidence only** | An immutable, attributable, exact-target-bound receipt. **Approves nothing and advances nothing**, and never substitutes for the decision. |
| 4 | **Resolve** | **lifecycle authority** | The canonical lifecycle transition — the **only** mover. |

Reading these as a single "approve" button is the misreading this table exists to prevent: a recorded
sign-off is *evidence that a human looked*, never consent, authority, or advancement.

### Advancement is MANUAL

Advancement is manual, and that is **this workflow's current governed behaviour — not a platform
invariant**. An automatic-advance option is **not implemented**; it is not disabled, hidden, or pending
rollout, and nothing in this vertical should be read as promising it. Introducing one would be a
governed policy generation, not a UI change.

### Read models are NOT authoritative

Every projection in this document is a **read model**. It reports persisted truth for a reviewer to
look at; it is never the source of authority for a decision or a transition, and a surface must never
act on a projection's summary in place of the canonical command. Authority lives in the gate; the
lifecycle lives in resolve.

### Reachability is derived, not asserted

Stage-4 reachability is **derived from the governed workflow artifact**. `IMPLEMENTED_GATES` only ever
**narrows** what the artifact authorises, so a generation that omits, disables, remaps, or ambiguously
maps `final_review` yields exactly what it did before. `final_review` is **not** asserted as a universal
workflow assumption.

### Exact provenance, and the /gw boundary

The vertical binds to **exact** targets and pinned sources — the immutable attached package, never
current Topic/Script/workflow/selection. The `/gw` boundary was widened by **exact-match entries only**:
reads for the final-review stage state (`state` alone — deliberately *not* `advanced`/`action`, which
widening `SERVED_GATES` would have opened) and the canonical gate detail; writes for
`gates/{id}/decide` and `gates/{id}/resolve`. No actor, principal, role, assignment, quorum, authority
or eligibility value is composed or sent by the surface.

### Protected scope

**#442 is protected** and is explicitly out of scope for this vertical and its closeout. **Stage 5 is
gated**: it begins only after Stage 4 is accepted and merged.

## Stage-4 closeout — responsive shell evidence (`fix/r1-stage4-closeout`)

The closeout reproduced and corrected a **pre-existing 375px Workbench shell-header overflow** — a
shared-shell defect, not a Final Review defect. Prior independent review classified the
"~586px header-control cluster at a 375px viewport" as STAGE_CLOSE_BLOCKING.

### Two distinct SHAs — do not conflate them

| Role | SHA |
|---|---|
| **Parent / base exact main SHA** — the state the defect was **reproduced on, before any edit** | `ee3676975b30db7808a69dc84f50288b72790c3b` (== `origin/main` at the time) |
| **Final closeout exact HEAD** — **this commit**, on `fix/r1-stage4-closeout`, whose parent is the base SHA above; it carries the source fix, the added test, and these docs | recorded in the closeout report (a commit cannot contain its own hash) |

Pre-edit reproduction was measured on the **base** SHA. Post-fix validation, runtime identity and
browser evidence were captured against the **final closeout HEAD** tree.

- **Dedicated exact-head runtime:** every measurement in this section was taken against a workbench
  **built from this worktree** and served on a dedicated port, with its identity read from
  `/api/runtime` rather than assumed. It was **never** taken from the pre-existing reviewer-lane server
  on `:3001`, which serves a **different worktree** at a **divergent** SHA; that lane is named here only
  as the trap that was avoided, and **no evidence in this repository is sourced from it**.
- **Reproduced before any edit:** document overflow **+223 px** at 375×812; the control cluster measured
  **585.8 px** — *identically at 375, 768 and 1280*, the signature of a box that cannot shrink;
  `agent-trigger`, `process-studio-link` and `secrets-admin-link` sat off-screen. The repo's existing red
  control (`workbench/e2e/shell-containment.spec.ts:68`) was **already failing at the base SHA** with the
  same `223`, so two independent measurements agree.
- **Cause:** the cluster carried `flex-wrap` *and* `shrink-0`. `flex-shrink: 0` pins a flex item at its
  max-content width, and a wrapping flex container's max-content contribution is the sum of all children
  on one line — so the wrap could never engage. The adjacent comment asserted the opposite.
- **Correction:** presentation-only — `shrink-0` → `min-w-0` (+ `justify-end`) on that one element.
- **After:** 375px overflow **0**, cluster **351 × 64.3** (genuinely wrapped to two rows), zero off-screen
  header controls, zero focus escaping the viewport; tablet and desktop **unchanged** at 585.8 × 31.6.
- **Coverage added:** a per-control containment red control on the untouched default view, proven
  **fail-before (223) / pass-after** — the pre-existing assertion only ran *after* the rail overlay was
  opened, so it could not distinguish "contained" from "already overflowing before anyone touched it".
