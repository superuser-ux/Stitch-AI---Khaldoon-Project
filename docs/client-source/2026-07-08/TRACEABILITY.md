# SRD Checkpoint Ledger — SRC-SMA-SRD-2026-07-08

Versioned, many-to-many traceability ledger mapping external client-SRD clauses to where they were
considered and what evidence exists. **This ledger is a derived, non-authoritative reference. It
creates no product behavior, architecture contract, or delivery status, and it does not copy
unrestricted source text.** The authoritative original is the external document in the manifest
([`../README.md`](../README.md)).

- **Assessed source:** `SRC-SMA-SRD-2026-07-08` — SRD v0.4 draft, dated 2026-07-08, SHA-256 `d1d64316…`
  (companion `SRC-SMA-ONEPAGER-2026-07-08`, SHA-256 `b9bc71ea…`).
- **Mapping version:** `mv2` · **Reviewer:** CC · **Date:** 2026-07-13.
- **Supersession note:** `mv1` was the draft ledger in the unmerged, superseded PR #239; it never
  reached `main`. `mv2` replaces it with split authority fields (`source_authority` /
  `interpretation_authority` / `clarification_evidence`), split mixed-authority checkpoints
  (CP-001→CP-031, CP-003→CP-032), per-checkpoint `decision_owner`, and weakest-defensible coverage.
- Unless a row states otherwise, every checkpoint below assesses that source at `mv2`, reviewer CC,
  2026-07-13, and `superseded_by = none`.

## How to read this ledger (frozen rules)

- **Many-to-many:** one checkpoint may partially address several clauses; one clause may need several
  checkpoints across directives, PRs, live proofs, external integrations, and later versions.
- **Non-equivalence:** `considered` ≠ `defined` ≠ `implemented` ≠ `live-proven`. A high status on one
  checkpoint never implies coverage of a clause addressed by other checkpoints.
- **Authority is recorded in separate fields — never collapsed into one value:**
  - `source_authority` — authority of the referenced clause(s). `client-authored` for every row in
    this ledger: all locators cite the client SRD.
  - `interpretation_authority` — authority of this row's interpretation/decision content beyond the
    clause itself: `none` (the row only locates the clause and reports status/evidence),
    `derived-mapping` (Tanaghom-internal interpretation; non-authoritative), or
    `operator-clarification` (an explicit operator amendment is claimed).
  - `clarification_evidence` — required citation **iff** `interpretation_authority =
    operator-clarification`; `—` otherwise. An uncited clarification claim is invalid.
  - Where one checkpoint would contain materially different authority claims, it is **split into
    linked checkpoints** (e.g. CP-001 ↔ CP-031, CP-003 ↔ CP-032) — never encoded as a mixed value.
- **Coverage status vocabulary (frozen):** `unconsidered` · `considered` · `defined` · `implemented` ·
  `live-proven` · `partially-covered` · `deferred` · `blocked-input` · `superseded`. Claims are kept
  at the **weakest defensible** status; a GitHub issue as evidence proves consideration or
  definition, never implementation.
- **`decision_owner`:** the named owner of the open decision on that checkpoint; `unassigned` until
  the operator assigns one. No "one owner decision per checkpoint" claim is made while owners are
  unassigned.
- **Frozen per version:** a checkpoint's meaning is fixed for the source/mapping version it assessed.
  Later SRD/provider/product generations **add or supersede** checkpoints explicitly (new
  `checkpoint_id`, `superseded_by` set on the old) — never silent reinterpretation.
- **Evidence links** cite issues/directives/PRs/heads/merge-SHAs/tests/live-proofs/external contracts;
  a link is evidence of *consideration or work*, not of acceptance.

## Mapping principles (interpretation_authority = derived-mapping — context, not requirements)

The SRD must not be read as one hardcoded global content model. Keep these dimensions separate, each
versioned and selectable per operating context:

1. **Content methodology profile** — pillars, struggles/HCS, lenses, formats, voice, planning
   distribution for a specific org/brand/program.
2. **Workflow family** — the governed lifecycle (social, courses, newsletters, podcast/book
   derivatives, …); a workflow selects a methodology profile without redefining it globally.
3. **Council of Experts** — a CCO-only advisory capability of expert-domain agents; its ten domains
   are **not** content pillars, HCS records, or executable workflow stages.
4. **Operating organization & actors** — CCO, manager, content subject/brand, reviewers, production
   roles, Agents, AgentReps; identities/permissions are separate from methodology data.

Accordingly the SRD's 4×12 model is a **candidate methodology profile to map/configure**, not evidence
that the existing 5-pillar/42-HCS profile is wrong, and it must not trigger destructive replacement
(recorded as checkpoint CP-031).

## Checkpoint ledger

`source_authority` is `client-authored` (**CA**) on every row. `interpretation_authority` values:
`none` · `derived-mapping` · `operator-clarification` (each written in full — never combined with the
source authority or with each other).

| checkpoint_id | clause locator(s) | source_authority | interpretation_authority | clarification_evidence | coverage_status | interpretation / decision + evidence | unresolved / exclusions | decision_owner | superseded_by |
|---|---|---|---|---|---|---|---|---|---|
| CP-001 | FR-1.1–1.3 (methodology profile) | client-authored | none | — | partially-covered | Clause coverage status only; the derived mapping decision for the 4×12 model is recorded separately in **CP-031**. Evidence: versioned methodology/HCS + cursor planning (test-backed); #21. | Admin profile add/edit/retire acceptance. | unassigned | none |
| CP-002 | primary accountable identity (SRD §owner) | client-authored | derived-mapping | — | considered | Confirm Mai (CCO/Owner) ↔ Moataz/Tanaghum; map CCO/owner/manager/reviewers/demo actors explicitly. Evidence: principal/role model; #197, #238. | Mai's relationship to the product identity. | unassigned | none |
| CP-003 | FR-5.1–5.4 (production routing) | client-authored | none | — | partially-covered | Clause coverage status only; the claimed operator clarification on production routing is recorded separately in **CP-032**. Evidence: manual production live-proven #225; SDAM #233/#234. | Auto routing decision + override UI + assignable tasks/due-dates/overdue. | unassigned | none |
| CP-004 | FR-10.1 (approval channel) | client-authored | derived-mapping | — | implemented | Dashboard is the client acceptance channel; Telegram stays internal/optional pending an explicit amendment. Evidence: reviewer queues + approval actions live-proven. | Whether Telegram is amended in vs kept optional. | unassigned | none |
| CP-005 | FR-2.x (cadence 10–20/week) | client-authored | derived-mapping | — | implemented | Compatible: planner configurable, 14/week default (28d×2/day) explicit. Evidence: parametric planner. | — | unassigned | none |
| CP-006 | FR-1.1–1.3 (pillars/struggles/tagging/rotation) | client-authored | derived-mapping | — | partially-covered | Platform capability substantially present; SRD profile not yet mapped. Evidence: methodology/HCS data + planning test-backed. | Admin profile selection + add/edit/retire client acceptance. | unassigned | none |
| CP-007 | FR-2.1–2.4 (calendar/format mix/trends/schedule approval) | client-authored | none | — | partially-covered | Planner, managed format weights, calendar, schedule gate implemented; #225 live-proved schedule approval. | Trend/competitor input not connected; manual override history open. | unassigned | none |
| CP-008 | FR-3.1–3.4 (topic gen/promotions/review/Levantine) | client-authored | none | — | partially-covered | Topic gen + governed review/rework live-proven; dialect prompts + automated checks exist. Evidence: #225; #227/#229/#151. | Promotion/campaign context unproven; native-dialect acceptance baseline missing; guards don't inspect every generated field. | unassigned | none |
| CP-009 | FR-4.1–4.4 (format scripts/frameworks/review/Levantine) | client-authored | none | — | partially-covered | Format-specific gen, versioned formats, admin mgmt, script review implemented. | Framework authoring/revert UX + native-dialect acceptance unproven. | unassigned | none |
| CP-010 | FR-4.5 (newsletter) | client-authored | derived-mapping | — | deferred | Separate workflow-family/profile decision; do not force into the social workflow. | No confirmed execution surface/agent. | unassigned | none |
| CP-011 | FR-4.6 (podcast/book derivatives) | client-authored | derived-mapping | — | deferred | Likely separate workflow + methodology selections reusing governance primitives. | No confirmed execution surface/agent. | unassigned | none |
| CP-012 | FR-5.1–5.4 (routing/tasks/due-dates/overdue) | client-authored | none | — | partially-covered | Manual production stage + audited advancement live-proven. | Auto routing, override UI, assignable tasks, due dates, overdue notices not delivered. | unassigned | none |
| CP-013 | FR-5.5 (automated short-form edit) | client-authored | derived-mapping | — | defined | AVP is a companion MCP-first project with a Tanaghom contract; SDAM readiness (#233/#234) precedes the adapter. | Not integrated; live end-to-end pending. | unassigned | none |
| CP-014 | FR-5.6 (carousel production from templates) | client-authored | none | — | blocked-input | Format framework exists; no proven automatic carousel asset production. | Missing integration/execution path. | unassigned | none |
| CP-015 | FR-5.7 (AI image/thumbnail) | client-authored | none | — | deferred | Direction exists; no proven Tanaghom execution path. | Missing/deferred. | unassigned | none |
| CP-016 | FR-5.8–5.9 (human-final long-form / motion roles) | client-authored | derived-mapping | — | blocked-input | Human/AgentRep authority can represent roles; no operational task surfaces proven. | Missing product workflow. | unassigned | none |
| CP-017 | FR-6.1–6.3 (placement/per-post platforms/final approval) | client-authored | none | — | partially-covered | Manual distribution + pub.v1 recording live-proven; platform registry/receipt exists. | Six-platform selection + multi-destination not acceptance-proven. | unassigned | none |
| CP-018 | FR-6.4–6.5 (official API publishing/retries/alerts) | client-authored | derived-mapping | — | deferred | Postiz is the preferred replaceable candidate; no live adapter. | Manual publication receipt ≠ automatic publishing. | unassigned | none |
| CP-019 | FR-7.1–7.5 (metrics/aggregates/attribution/monitoring) | client-authored | derived-mapping | — | defined | BrandShield operational externally; #235/#236/#216 define Tanaghom surfaces/joins. | Not integrated; profile analytics ≠ Tanaghom per-post; lead/sales attribution (FR-7.4) remains a required seam even if CRM stays external. | unassigned | none |
| CP-020 | FR-8.1–8.5 (KPI Watcher/reports/escalation/WhatsApp/email) | client-authored | derived-mapping | — | deferred | Event/audit data + planned analytics loop exist; no KPI Watcher capability. **Explicit client requirement — may be phased, not classified absent.** Corrects #128 (reviewed only the STITCH SRD). | WhatsApp/email reporting channels required; KPI Watcher product capability missing. | unassigned | none |
| CP-021 | FR-9.1–9.3 (Council of 10, CCO-only, no execution) | client-authored | derived-mapping | — | blocked-input | Agent + permission architecture can host a strictly advisory-only Council; **not** a methodology/pillar model or executable stage. | Source/licensing decision; advisory-only authority enforcement. | unassigned | none |
| CP-022 | FR-10.1 (dashboard approval inbox) | client-authored | none | — | implemented | Reviewer-specific queues + approval actions implemented/live-proven; dashboard remains the acceptance path. | — | unassigned | none |
| CP-023 | FR-10.2–10.3 (single/dual approval + per-item routing) | client-authored | none | — | partially-covered | ANY/ALL assignment semantics + multi-approver policies exist. | Client-facing global mode + per-item CCO→manager routing UX unproven. | unassigned | none |
| CP-024 | FR-10.4 (visible item status) | client-authored | none | — | partially-covered | Workflow state, funnels, approved trail, publication events exist. Weakest-defensible: held below `implemented` while #237 (loss of full detail after approval) is open against the approved-item view. | Residual: #237 (loss of full detail after approval). | unassigned | none |
| CP-025 | FR-10.5 (permanent attributable audit) | client-authored | none | — | implemented | Gate decisions, versions, actors, timestamps, comments, publication events persisted. | Cross-system audit continuity future (#238). | unassigned | none |
| CP-026 | FR-10.6 (version history + restoration) | client-authored | none | — | partially-covered | Topic/script versions + governed rework + workflow/methodology versions exist. | Schedule version/override restoration + complete client-facing history unproven. | unassigned | none |
| CP-027 | FR-11.1 (compliance before every gate + publish) | client-authored | none | — | partially-covered | Dialect/structure checks in generation + approval hard floors. | No complete brand-safety/tone/claims compliance service proven before every gate/publish. | unassigned | none |
| CP-028 | FR-11.2 (secure credentials / OAuth2) | client-authored | none | — | blocked-input | Env-name indirection exists; #187 and #221/#223 evaluate secret authority. | Secret manager/control plane + provider OAuth lifecycle not deployed. | unassigned | none |
| CP-029 | FR-11.3 (RBAC + named roles + Council restriction) | client-authored | none | — | partially-covered | Principal/role/group model, OIDC binding S1/S2, AgentRep/capability design exist. | Production OIDC disabled; named client roles, Council restriction, companion mappings not operational (#197/#238). | unassigned | none |
| CP-030 | NFRs + success metrics (TLS/OIDC/availability/retention/recovery; export + every-field dialect; KPI baseline) | client-authored | derived-mapping | — | blocked-input | Not yet accepted as a production-release baseline; UI/RTL substantially covered. Permanent retention is stated in the SRD while trial data is treated as ephemeral — production retention is defined separately and does **not** require preserving synthetic trial records. | Availability/retention/recovery objectives; full export + generated-field dialect acceptance; measured KPI baseline. | unassigned | none |
| CP-031 | FR-1.1–1.3 (methodology profile) — linked to CP-001 | client-authored | derived-mapping | — | considered | Derived mapping decision (Tanaghom-internal, non-authoritative): the SRD's 4×12 model is a candidate profile to import as a **separate versioned** methodology; preserve the existing 5×42 profile; never conflate with the Council of Experts. Exclusion: not a ruling that 5×42 is wrong, and no destructive replacement. | Which org/program owns 4×12; owner acceptance of the mapping approach. | unassigned | none |
| CP-032 | FR-5.1–5.4 (production routing) — linked to CP-003 | client-authored | operator-clarification | Operator statement, Tanaghom Codex session 2026-07-12: governed physical production → SDAM upload/readiness → AVP-assisted edit; auto A/V/image generation is future. **Formal SRD amendment record pending — must be recorded before routing automation.** | considered | Clarification claim held at `considered` until the amendment is formally recorded; it amends interpretation of the routing clauses, not their text. Evidence: SDAM #233/#234 as the clarified direction's prerequisites. | Amendment not yet formally recorded; recording it is a prerequisite for any routing automation. | unassigned | none |

## Explicit exclusions and boundary

- The **STITCH platform SRD** governs the broader platform; it does not replace this content-product
  SRD and cannot be used to declare a product requirement absent.
- **CRM** stays outside Tanaghom as a system, but FR-7.4 lead/sales attribution where trackable is a
  required seam (see CP-019) — not a wholesale exclusion.
- Provider portability and external-DAM conclusions remain directionally compatible.

## Existing issue anchors (evidence index)

Approval/provenance #9 #197 · workflow governance #6 · schedule/calendar #7 · agent-capability
governance #21 · content edit cascade #51 · reusable content library #52 · scheduling readiness #53 ·
Arabic/RTL + attribution #54 #151 #229 · external lifecycle/learning #216 #235 #236 · approved-content
detail parity #237 · cross-system authority #238 · secret authority #187 · SDAM contract/readiness
#233 #234 · SDAM readiness adapter #244.

## Next traceability action

Assign a `decision_owner` to each open checkpoint; only then convert this ledger into a reviewed
status view with one owner decision per open checkpoint before starting a broad implementation
stream. (No such claim is made while owners are `unassigned`.) New directives cite the relevant
`FR-*` locator and a `checkpoint_id`, and must distinguish trial deferral from product exclusion.
Later SRD/provider/product generations add or supersede checkpoints explicitly — never silently
reinterpret historical coverage.
