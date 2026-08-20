# Change Request 01 — Internal Assessment And Implementation Checklist

Date: 2026-07-02
Status: internal working document
Scope source: client change request "Dynamic Content Methodology, Format, Workflow, and Auditability System" plus addendum "Human-in-the-Loop Approval Assignment"
Companion backlog:
[docs/11_Change_Request_01_Phased_Backlog.md](/Users/Kay/Dev/tanaghom/docs/11_Change_Request_01_Phased_Backlog.md)

## Purpose

This document is for internal implementation guidance only. It translates the client request into:

- current-state check
- risks and dependencies
- architectural implications
- phased implementation guidance
- readiness checklist before build starts

It is not a client-facing commitment and should not be treated as final scope or estimate.

## Executive summary

This change request is not a single feature. It is a platform-level expansion across:

- methodology management
- content format management
- workflow configurability
- approval modeling
- admin UX
- operational UX
- auditability
- permissions and future IAM compatibility

The repo already has useful foundations:

- gate engine and audit log
- principal model started
- DB-backed methodology reference data used by the planner
- operational review dashboard

The main gap is that workflow design and approval assignment are still primarily config-driven and partially hardcoded. The request shifts the system toward a database-backed workflow and approval platform.

## Current-state check

### Already present

- Gate engine with audited transitions:
  [gates/engine.py](/Users/Kay/Dev/tanaghom/gates/engine.py)
- Gate API and review surface:
  [gates/api.py](/Users/Kay/Dev/tanaghom/gates/api.py)
  [dashboard/lib/review-context.tsx](/Users/Kay/Dev/tanaghom/dashboard/lib/review-context.tsx)
- Core schema with gates, decisions, audit log, principals:
  [db/init/schema.sql](/Users/Kay/Dev/tanaghom/db/init/schema.sql)
- DB-backed methodology records used by planning:
  [planner/plan_round.py](/Users/Kay/Dev/tanaghom/planner/plan_round.py)
- Architectural direction already points toward stages, directives, IAM, and graph-like workflow evolution:
  [ARCHITECTURE.md](/Users/Kay/Dev/tanaghom/ARCHITECTURE.md)
  [ROADMAP.md](/Users/Kay/Dev/tanaghom/ROADMAP.md)

### Partially present but not sufficient for the request

- Principals exist, but roles/groups/memberships are not normalized enough for approval assignment.
- Multi-approver support exists, but approvers come from config and are not a full user/role assignment system.
- Workflow stages exist, but stage definitions are still driven by `system_config.yaml`.
- The operational UI exists, but there is no separate workflow-admin/builder surface.
- Approval audit exists, but authorization is not yet strong enough for "no approving on behalf of others."

### Not present yet

- Database-backed workflow designer/builder
- Versioned workflow definitions
- Versioned content-format registry by platform
- Methodology editing/version/revert UI
- Approval assignments to named users plus roles/groups in a normalized model
- Pending approvals per authenticated user view
- Proper auth-backed approval identity enforcement
- Dynamic branch/state model beyond the current status-heavy lifecycle

## Key implementation implications

### 1. This is a schema change, not just a UI change

The current engine can be extended, but the request requires new persistent entities for:

- workflow definitions and versions
- stage definitions and transitions
- approval step configuration
- approval assignment snapshots
- content platform and format definitions
- methodology versions and diffs
- role/group membership

### 2. Auth becomes a core dependency

The addendum requires preventing unauthorized approvals. That means:

- server-side identity from auth/session
- authorization against assigned principal or membership
- no trust in client-supplied `approver_id` as the source of truth

Without this, the approval requirement is not actually met.

### 3. The current status model will become a constraint

The current lifecycle is strongly driven by `slot.status` enum values. The request asks for visible operational branches such as:

- Topic Review
- Approved Topics - Waiting for Commit
- Rejected Topics
- Committed Topics

This likely needs either:

- a richer workflow-item/stage-instance state model, or
- a controlled extension layer above `slot.status`

Trying to force all future workflow states into the existing enum will raise maintenance cost.

### 4. Workflow config should not remain split across YAML and DB

If workflow behavior becomes partly DB-backed and partly `system_config.yaml`, the system will drift and become hard to reason about. The request should converge toward DB-backed workflow definitions with YAML or repo files kept only as:

- seed data
- defaults
- export/import references

### 5. Approval history must snapshot assignment context

For auditability, each opened approval instance should snapshot:

- assigned user ids
- assigned roles/groups
- resolution rule
- required count if quorum is ever added
- stage/workflow version

This prevents later user-role changes from rewriting historical meaning.

## Internal risks to be ready for

### Scope and delivery

- Scope expansion: this can easily be underestimated as "approval enhancements."
- Estimate risk: backend, schema, auth, admin UI, and migration work all move together.
- Acceptance risk: too many moving parts if delivered as one batch.

### Architecture

- Workflow design is still config-centric today.
- Dynamic branching may not fit cleanly in the current status enum model.
- Hardcoded stage assumptions in the dashboard will need to be reduced.

### Security and permissions

- Approval impersonation risk until auth-backed identity enforcement exists.
- Role/group rules can become ambiguous without explicit semantics.
- Future IAM compatibility can be undermined by shortcuts now.

### Data and audit

- Migration risk from markdown/config sources into DB-managed versions.
- Audit ambiguity if assignee resolution is not snapshotted.
- Revert/version-diff behavior needs product definition, not just storage.

### Product semantics

The following points must be defined before implementation starts:

- Does `AND` mean one shared approval step requiring all assignees, or separate sequential approvals?
- Does `OR` mean the first valid approval closes the step?
- If a role/group is assigned, does one member satisfy it or all members?
- If membership changes while an approval is pending, does the pending assignment stay frozen?
- Can one person satisfy multiple role-based assignments in the same step?
- Are reject and request-change separate paths in all approval stages?

## Recommended architecture direction

### Approval model

Model approval as a workflow step with:

- approval instance
- assignment snapshot rows
- resolution rule: `ANY` or `ALL`
- per-assignee action log

For now, keep `ANY` and `ALL`. Do not expand to custom quorum unless it becomes a real requirement.

### Sequential vs parallel semantics

- Use separate sequential approval steps for business flows like Legal -> Brand -> Final.
- Use one approval step with multiple assignments plus rule `ANY` or `ALL` for assignee logic.

This is simpler than literally representing every OR case as parallel engine branches unless the visual builder truly needs that representation.

### Workflow model

Introduce versioned workflow definitions with:

- one active workflow now
- support for future multiple workflows later
- workflow activation history
- workflow-item linkage to the workflow version used at the time of execution

### Identity model

Expand principals into a normalized permission model with at least:

- users
- roles
- groups
- memberships
- optional principal-to-principal relationships if agent reps remain part of the design

## Recommended phased delivery

### Phase 0 - definition and readiness

- freeze approval semantics
- define auth assumptions
- define workflow/versioning model
- define migration strategy

Exit criteria:

- product rules written down
- no unresolved approval-rule ambiguity
- no hidden auth dependency

### Phase 1 - identity and authorization foundation

- implement or harden authenticated user identity
- normalize roles/groups/memberships
- enforce server-side authorization for approval actions

Exit criteria:

- users can approve only when actually assigned or authorized
- approval actor comes from session identity, not request body

### Phase 2 - approval model refactor

- add approval instances and assignment snapshots
- support named users and roles/groups
- support `ANY` and `ALL`
- expose pending approvals per user

Exit criteria:

- audit log can show assigned-to, acted-by, rule, status, timestamp, notes

### Phase 3 - workflow configuration backend

- add workflow definition/version tables
- stage and transition definitions
- activation/deactivation
- one active workflow rule

Exit criteria:

- operational engine reads workflow definition from DB
- no critical stage-routing logic depends on hardcoded dashboard stage lists

### Phase 4 - separate admin workflow surface

- workflow builder/editor
- stage ordering and transitions
- assignment-rule configuration
- version history and activation controls

Exit criteria:

- workflow editing happens only in admin/design surface

### Phase 5 - operational state improvements

- make approval outcomes visible as real stage-based operational states
- cleanly expose pending, approved-waiting, rejected, committed

Exit criteria:

- operational UI reflects stage movement instead of only status toggles within one queue

### Phase 6 - methodology and content format management

- methodology versioning and editing
- platform/content-format registry
- format versioning and revert
- script generation consumes selected format definition

Exit criteria:

- methodology and formats are DB-backed and versioned
- scripts include production direction from format config

### Phase 7 - optional storyboard preparation

- add data model and UI toggle support only
- generation implementation can come later

Exit criteria:

- no later schema refactor needed to add storyboard generation

## Readiness checklist

Use this before implementation starts.

### Product readiness

- [ ] Approval semantics written and agreed internally
- [ ] Role/group behavior clarified
- [ ] Rejection vs request-change behavior clarified
- [ ] Single-workflow-now, multi-workflow-later boundary agreed

### Technical readiness

- [ ] Auth/session source identified
- [ ] Migration strategy for YAML/markdown-config sources identified
- [ ] Target schema draft prepared
- [ ] Backward compatibility plan for current gate flows prepared

### Delivery readiness

- [ ] Scope split into phases, not one merged ticket
- [ ] Regression test plan identified for gate engine and dashboard
- [ ] Internal owner assigned for data model decisions
- [ ] Internal owner assigned for UX/admin-builder decisions

## Suggested implementation stance

Recommended stance:

- do not promise this as one sprint feature
- treat it as a phased platform enhancement
- make auth and approval identity a first-class dependency
- avoid mixing YAML workflow truth with DB workflow truth
- snapshot approval assignment context for audit

## Immediate next step

Before writing code, produce:

- target schema proposal
- approval semantics spec
- phased backlog with dependencies

That will reduce rework far more than starting directly on the UI.

## Efficiency and quality control approach

The goal should be to implement this in a way that keeps delivery moving without destabilizing the working core.

### Recommended execution strategy

- Keep the current gate engine operational while introducing the new workflow model behind explicit seams.
- Change one layer at a time: identity, then approval model, then workflow config, then admin UI.
- Avoid big-bang replacement of the current review flow.
- Prefer additive schema changes first, then controlled cutover.
- Keep one source of truth per concern. Do not leave approval logic split across request payloads, YAML, and DB.

### Recommended work split

#### Track A - core backend

Owns:

- schema
- auth and authorization rules
- approval model
- workflow version model
- migration paths

Constraint:

- this track defines the contracts other tracks consume

#### Track B - operational UI adaptation

Owns:

- pending approvals by user
- new approval visibility
- operational branch/state presentation

Constraint:

- should consume stable backend contracts from Track A
- should not invent workflow semantics in the frontend

#### Track C - admin/configuration UI

Owns:

- workflow builder/editor
- methodology version UI
- content-format management UI

Constraint:

- should start after backend entities and API shape are stable enough

### Quality controls to enforce

#### 1. Freeze semantics before coding

Do not start implementation until approval behavior is written down for:

- `ANY`
- `ALL`
- user assignment
- role/group assignment
- reassignment
- membership change while pending
- reject vs request-change

If these rules stay ambiguous, quality will degrade through rework and edge-case patches.

#### 2. Preserve a stable compatibility path

Until the new workflow system is proven:

- preserve the existing topic/script lifecycle
- keep existing engine behavior covered by tests
- add adapters rather than rewriting all consumers at once

#### 3. Add regression tests before cutover

At minimum, cover:

- approval authorization
- approval snapshot/audit behavior
- `ANY` approval resolution
- `ALL` approval resolution
- role/group membership resolution
- stage transition correctness
- pending approvals visibility per user
- legacy topic/script review flow still functioning

#### 4. Use migration checkpoints

Suggested checkpoints:

- schema added, not yet active
- new APIs available behind controlled path
- operational UI switched
- admin UI switched
- old config path deprecated only after validation

#### 5. Keep branch complexity contained

Do not implement:

- multiple active workflows
- custom quorum logic
- generalized no-code workflow features

unless they are truly required now. They add cost quickly and weaken quality if introduced too early.

### Definition of done per phase

Each phase should only be considered complete when:

- business rules for that phase are documented
- tests for that phase exist
- audit behavior is verified
- existing lifecycle regressions are checked
- there is a rollback or fallback path

### Internal implementation discipline

Recommended discipline:

- backend-first for semantics
- operational UI second
- admin/builder UI third
- cut scope aggressively where design-for-later is sufficient
- stop after each phase for review before widening scope

### Practical rule

If a change improves flexibility but weakens auditability, authorization clarity, or transition correctness, do not merge it yet.

This request must be implemented as a controlled platform evolution, not as fast-moving UI-led scope.
