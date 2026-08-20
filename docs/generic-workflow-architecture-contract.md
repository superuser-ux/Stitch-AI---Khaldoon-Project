# Generic Workflow Architecture Contract & Product-Surface Ledger (#410)

**Status:** Normative. **Scope:** V2 Workbench UI/docs/tests only. **Slice base:** `c51ae684655da27693fc675b80c812d47c407744`.

This document is the normative contract for the generic graph/workflow direction and the canonical
product-surface metadata. It records architecture and the complete planned product map; it does **not**
change execution semantics, schema, runtime, or deployment. The implementation slice adds canonical
product-surface metadata, integrates only **Process Studio** into the existing V2 shell, renders one
truthful **read-only** React Flow demonstration, and publishes this contract.

## 1. Normative workflow contract

- A **stage type / capability** defines reusable executable behavior and compatibility constraints; it
  is **not** a workflow instance.
- A **workflow family** owns durable identity and lifecycle across versions.
- A **workflow version / template** composes configured stage instances and transitions.
- A **domain profile** supplies domain-specific configuration and eligibility but **cannot** introduce a
  separate execution engine.
- A **methodology binding** modifies planning/generation behavior **without** becoming workflow identity.
- An **approval binding** governs review requirements and is intended to become **workflow-version
  scoped**.
- A **run snapshot** immutably pins all applicable versions and bindings.
- **Identifier separation is mandatory:** UI graph node IDs, display labels, canonical stage
  identifiers, and executable capability identifiers are **separate**. React Flow serialization is
  **never** the backend execution contract.
- The architecture **rejects both** a single hardcoded global pipeline **and** bespoke engines per use
  case. Domain cases are configured compositions of reusable capabilities.

## 2. Canonical product-surface semantics

Navigation presence, implementation state, route availability, and product status are **four
independent dimensions**. The single registry (`workbench/lib/product-surface.ts`) is the sole metadata
source; runtime consumers read filtered views and may not redefine labels, state, or ownership.

- **Planned does not imply navigable.** In this slice only **Process Studio** becomes newly navigable;
  Identity and Secrets remain represented and navigable; no other planned top-level destination is
  navigable.
- **Disabled controls never navigate** and never imply operational behavior.
- `owner` means `{ productArea, authority, trackingIssue? }`. It **never** names a person or team.
- Consumers:
  - **V2 global shell** renders only `showInNavigation` entries (desktop + mobile, one implementation).
  - **Process Studio** renders its own children (the Planned capabilities list).
  - **Product-surface ledger** renders the complete planned set, non-navigational.

### Visual implementation-state language

- `operational` / `implemented` → **active** treatment (normal foreground + interaction).
- `scaffolded` / `deferred` / `blocked` / `unavailable` → **dimmed** treatment, theme-aware (light +
  dark) via shared semantic state classes (`.surface-tone[data-surface-tone]` in `app/globals.css`),
  driven by registry state — never per-component opacity guesses.
- Color is **never** the sole signal: dimmed surfaces also carry `aria-disabled` and visible status
  copy, and remain legible, discoverable, and focus-accessible.

## 3. Product-surface ledger (complete planned map)

Top-level order is canonical. `nav` = appears in global navigation this slice.

| Surface | Parent | Product status | Implementation state | Route availability | Nav | Owner (area · authority · issue) |
|---|---|---|---|---|---|---|
| Workbench | — | operational | operational | available (`/`) | — | Workbench · SRD #331 · #331 |
| Process Studio | — | preview | implemented | available (`/studio`) | ✅ | Process Studio · SRD generic-workflow architecture · #410 |
| Inbox & Tasks | — | planned | deferred | planned | — | Inbox & Tasks · SRD roadmap |
| Content | — | planned | deferred | planned | — | Content · SRD roadmap · #294 |
| Analytics & Learning | — | planned | deferred | planned | — | Analytics & Learning · SRD roadmap |
| Agents | — | planned | scaffolded | planned | — | Agents · SRD roadmap |
| Administration | — | planned | scaffolded | planned | — | Administration · SRD roadmap |
| ↳ Identity | Administration | operational | operational | available (`/admin/identity`) | ✅ | Administration · IAM |
| ↳ Secrets | Administration | operational | operational | available (`/admin/secrets`) | ✅ | Administration · Secrets custody |

**Process Studio children — Planned capabilities (non-interactive, deferred):** Node palette (#39),
Graph validation (#39), Releases & version history (#6), Archive / restore (#6), Methodology bindings
(#242), Approval bindings (#9).

## 4. Process Studio containment rules

- One global shell, one `<main>`, one mobile navigation implementation, and the existing #331
  run-stage-lens authority are preserved. The registry is **not** a second navigation authority.
- Process Studio is a **product-authoring context**, never a lifecycle stage or Workbench lens.
- `/studio` is outside selected-run/stage/lens context. Entering it never creates or reinterprets a run.
- **Safe return contract:** the originating internal Workbench URL is passed as a `from` query
  parameter and validated to a safe internal absolute path (`workbench/lib/safe-return.ts`): a single
  leading `/`, preserving path/query/hash; rejecting `//`, schemes, absolute URLs, backslash tricks,
  control/whitespace, and anything not internal; fallback `/`. `from` is return context only and never
  alters run/stage/lens interpretation.
- The Workbench **Workflow** lens stays disabled/read-only (`lib/shell-lens.ts`, outside `IMPLEMENTED`).
  **V1 Workflow Admin is unchanged**; Process Studio does **not** replace it.

## 5. Demonstration fixture rule

- One typed fixture, `illustrativeSocialWorkflow`
  (`workbench/components/studio/illustrative-social-workflow.ts`).
- Visible copy, verbatim: **"Illustrative social workflow template — not loaded from active runtime
  configuration."**
- Fixture ownership is Process Studio demonstration only — not execution truth, activation evidence, or
  a seed. Tests assert the disclosure and the absence of mutation controls.

## 6. Follow-on sequence (recorded, not implemented)

1. Per-workflow-family lifecycle and activation.
2. Family create, clone, archive, and restore.
3. Explicit workflow/methodology selection and immutable run pinning.
4. Governed stage-type/capability registry and graph validation.
5. Workflow-version-scoped approval bindings.
6. Enable Process Studio editing only for drafts.
7. Migrate and prove the existing social workflow on the generalized model.
8. Add course/newsletter/podcast profiles only from approved requirements.

## 7. Non-goals & invariants

- **Non-goals:** no schema, migration, API, engine, planner, gate, approval, methodology, IAM,
  AgentRep, secret, provider, runtime, or deployment change; no new workflow family/activation; no
  functional node palette, edge editing, validation engine, release/archive controls; no V1 Workflow
  Admin change; no UAT/staging/production/public-ingress/source-cleanup/VPS deployment.
- **Invariants:** existing social execution and all run snapshots unchanged; existing direct-run and
  schedule-first journeys unchanged; no duplicate navigation authority, shell, `<main>`, or mobile
  implementation; deferred visibility is roadmap truth, never simulated functionality; no bootstrap/
  seed/reset overwrites operator-owned configuration.

## 8. GitHub reconciliation

Consumes no existing issue. Links: #6 (workflow governance/admin compatibility), #39 (stable stage
identifiers / display labels), #9 (approval semantics), #241 (campaign/course association seam), #242
(SRD sequencing / deferred families), #331 (shell/context authority). #294 is preserved as the
social-content delivery ledger, **not** a universal workflow definition.
