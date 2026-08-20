# Change Request 01 — Phased Internal Backlog

Date: 2026-07-02
Status: internal planning document
Companion assessment:
[docs/10_Change_Request_01_Internal_Assessment.md](/Users/Kay/Dev/tanaghom/docs/10_Change_Request_01_Internal_Assessment.md)

## Purpose

This is the internal execution backlog for Change Request 01. It is designed to help us implement efficiently while keeping quality, auditability, and backward compatibility under control.

This is not a client-facing scope promise.

## Implementation baseline

Current baseline before CR01 work starts:

- working gate engine exists
- working operational review UI exists
- methodology seed/reference data is partly DB-backed for planning
- workflow behavior is still largely config-driven
- approval authorization is not yet strong enough for role/group-driven assignments

Implication:

CR01 should be built as an additive platform extension with controlled cutover, not a direct rewrite.

## Delivery principles

- backend semantics before frontend flexibility
- additive schema before destructive replacement
- one active workflow only for this phase
- preserve current topic/script review flow until replacement is proven
- no auth shortcuts on approval actions
- no mixed long-term source of truth for workflow definition

## Workstreams

### Stream A - semantics and data model

Includes:

- approval semantics
- workflow semantics
- schema design
- migration strategy

### Stream B - auth and authorization

Includes:

- session identity
- approval authorization
- role/group membership enforcement

### Stream C - engine and API

Includes:

- approval instance model
- workflow execution model
- pending approvals queries
- operational branch state support

### Stream D - operational UI

Includes:

- per-user pending approvals
- approval visibility
- new branch/state presentation

### Stream E - admin/configuration UI

Includes:

- workflow builder/editor
- methodology management
- content-format management

## Phase sequence

Recommended sequence:

1. CR01-P0 definition and baseline freeze
2. CR01-P1 identity and authorization foundation
3. CR01-P2 approval model and audit refactor
4. CR01-P3 workflow definition backend
5. CR01-P4 operational UI adaptation
6. CR01-P5 admin workflow surface
7. CR01-P6 methodology and content-format management
8. CR01-P7 storyboard-ready extension points

Do not start P4, P5, or P6 as independent frontend-first efforts.

## Backlog

## CR01-P0 - Definition And Baseline Freeze

Goal:

Remove ambiguity before implementation starts.

### CR01-001 Approval semantics spec

Deliver:

- written rules for `ANY`
- written rules for `ALL`
- behavior for named users
- behavior for roles/groups
- behavior for reject vs request-change
- behavior when membership changes while approval is pending

Dependencies:

- none

Acceptance:

- no unresolved approval-rule ambiguity remains
- documented internal sign-off from product/implementation side

### CR01-002 Workflow semantics spec

Deliver:

- definition of workflow
- definition of stage
- definition of transition
- definition of approval step vs approval assignment
- one-active-workflow rule

Dependencies:

- none

Acceptance:

- workflow builder target model is agreed internally

### CR01-003 Current-system compatibility map

Deliver:

- map from current gate/stage model to future workflow model
- identify fields and APIs that must remain stable during transition
- identify hardcoded stage assumptions in backend and dashboard

Dependencies:

- none

Acceptance:

- compatibility constraints documented
- cutover risks identified up front

## CR01-P1 - Identity And Authorization Foundation

Goal:

Make approval identity trustworthy before adding richer assignment logic.

### CR01-101 Session-backed acting user

Deliver:

- server derives acting principal from authenticated session or trusted identity layer
- approval actions no longer treat request-body `approver_id` as authority

Dependencies:

- CR01-001

Acceptance:

- acting user is server-resolved
- impersonation through request payload is blocked

### CR01-102 User, role, group, membership schema

Deliver:

- normalized user/role/group tables
- membership tables
- migration plan from current principal model

Dependencies:

- CR01-001
- CR01-002

Acceptance:

- assignment logic can target users and groups without ambiguous storage

### CR01-103 Authorization policy for approval actions

Deliver:

- authorization checks for approval action execution
- checks for direct assignment
- checks for role/group-derived assignment
- unauthorized action audit path

Dependencies:

- CR01-101
- CR01-102

Acceptance:

- unauthorized users cannot approve for others
- denial cases are audited and test-covered

## CR01-P2 - Approval Model And Audit Refactor

Goal:

Introduce a durable approval-instance model that supports assignments and auditability.

### CR01-201 Approval instance schema

Deliver:

- approval instance table
- approval assignment snapshot table
- approval action/event table
- status fields for pending/approved/rejected/requested-change if required by product rules

Dependencies:

- CR01-001
- CR01-102

Acceptance:

- assignment context is snapshotted at open time
- audit history does not depend on future membership changes

### CR01-202 Approval resolution engine

Deliver:

- engine logic for `ANY`
- engine logic for `ALL`
- clear behavior for close, supersede, reopen if needed

Dependencies:

- CR01-201

Acceptance:

- `ANY` and `ALL` behavior proven by tests
- no ambiguity in first-approval-wins behavior for `ANY`

### CR01-203 Pending approvals query model

Deliver:

- per-user pending approvals
- per-role/group-derived pending approvals
- queue-friendly read model for operations UI

Dependencies:

- CR01-201
- CR01-202

Acceptance:

- authenticated user can see only relevant pending approvals

### CR01-204 Audit and reporting fields

Deliver:

- assigned user/role/group
- rule `ANY`/`ALL`
- approval status
- timestamp
- acting user
- comments/notes

Dependencies:

- CR01-201

Acceptance:

- required audit fields from client request are present and readable

## CR01-P3 - Workflow Definition Backend

Goal:

Move workflow structure from config-driven behavior toward DB-backed definition and versioning.

### CR01-301 Workflow and workflow-version schema

Deliver:

- workflow table
- workflow version table
- activation state
- one-active-workflow constraint

Dependencies:

- CR01-002

Acceptance:

- one workflow can be active at a time
- workflow versions are auditable

### CR01-302 Stage and transition schema

Deliver:

- stage definitions
- stage ordering
- transitions
- bypassable/mandatory flags
- enabled/disabled flags

Dependencies:

- CR01-301

Acceptance:

- workflow can be represented without relying only on static YAML stage definitions

### CR01-303 Workflow execution mapping layer

Deliver:

- translation layer from DB workflow definition to engine execution behavior
- compatibility layer for existing topic/script flow during migration

Dependencies:

- CR01-301
- CR01-302

Acceptance:

- existing lifecycle still works while new workflow backend is introduced

### CR01-304 Workflow version activation and rollback

Deliver:

- activate a workflow version
- deactivate prior version
- guard against conflicting active workflows on same task space

Dependencies:

- CR01-301

Acceptance:

- cutover is controlled and auditable

## CR01-P4 - Operational UI Adaptation

Goal:

Expose the new approval model in the live operations surface without mixing in design concerns.

### CR01-401 Pending approvals per user view

Deliver:

- operational queue for current user
- visibility into why an item is pending
- visibility into who else is required where applicable

Dependencies:

- CR01-203

Acceptance:

- UI clearly shows who is required to approve

### CR01-402 Approval card/state enhancements

Deliver:

- assigned user/role/group display
- rule display `ANY` or `ALL`
- status display
- comments/history display as needed

Dependencies:

- CR01-204

Acceptance:

- approval requirements are understandable without reading backend labels

### CR01-403 Stage-based operational branch visibility

Deliver:

- approved waiting state
- rejected state
- committed state
- any other approved business states defined in P0

Dependencies:

- CR01-303

Acceptance:

- items visibly move through stage-based operational states

## CR01-P5 - Admin Workflow Surface

Goal:

Create a separate admin/design surface for workflow management.

### CR01-501 Workflow builder shell

Deliver:

- separate admin route/surface
- workflow list
- workflow version history
- active/inactive controls

Dependencies:

- CR01-301

Acceptance:

- workflow editing does not happen in operational UI

### CR01-502 Stage configuration editor

Deliver:

- add/remove/reorder stages
- enable/disable
- bypassable vs mandatory
- transition editing

Dependencies:

- CR01-302

Acceptance:

- stage configuration can be changed visually and persisted

### CR01-503 Approval assignment editor

Deliver:

- assign one user
- assign multiple named users
- assign one or more roles/groups
- choose `ANY` or `ALL`

Dependencies:

- CR01-201
- CR01-102

Acceptance:

- admin can visually define approval logic per workflow step

## CR01-P6 - Methodology And Content-Format Management

Goal:

Move methodology and content-format definitions into versioned, DB-backed admin-managed entities.

### CR01-601 Methodology version schema and seed import

Deliver:

- methodology entity
- methodology versions
- import current repo markdown as initial canonical seed

Dependencies:

- CR01-003

Acceptance:

- active source of truth becomes DB-backed
- current markdown remains seed/reference only

### CR01-602 Methodology admin UI

Deliver:

- view versions
- edit
- create new version
- revert
- change history view

Dependencies:

- CR01-601

Acceptance:

- permissions can govern methodology editing

### CR01-603 Platform and content-format schema

Deliver:

- platform registry
- content-format registry
- versioning
- deactivation support
- production rules storage

Dependencies:

- CR01-003

Acceptance:

- multiple future platforms can be modeled without code changes

### CR01-604 Content-format admin UI

Deliver:

- add/edit/deactivate platform
- add/edit/deactivate content format
- revert version
- manage production requirements

Dependencies:

- CR01-603

Acceptance:

- admin can manage production format definitions without repo edits

### CR01-605 Script handoff enrichment

Deliver:

- script generation resolves selected content-format definition
- production direction is attached from DB-backed format rules

Dependencies:

- CR01-603

Acceptance:

- scripts include relevant production guidance by format/platform

## CR01-P7 - Storyboard-Ready Extension Points

Goal:

Prepare for optional storyboard generation without forcing full implementation now.

### CR01-701 Storyboard-capable schema fields

Deliver:

- storyboard option fields on relevant format/workflow/script entities

Dependencies:

- CR01-603

Acceptance:

- no major refactor required to add storyboard generation later

### CR01-702 Storyboard toggle UI placeholder

Deliver:

- optional UI toggle or prompt definition only

Dependencies:

- CR01-701

Acceptance:

- capability is represented without full generation implementation

## Quality gates

These gates apply to every phase.

### QG-1 Semantic clarity

- rules documented before code
- no unresolved approval edge cases

### QG-2 Regression control

- existing topic/script review flow re-tested
- legacy engine behavior not broken silently

### QG-3 Audit integrity

- actor identity verified
- assignment snapshot verified
- timestamps and comments retained

### QG-4 Authorization correctness

- unauthorized approval attempts blocked
- role/group membership paths tested

### QG-5 Cutover safety

- additive rollout preferred
- fallback path exists before old path is removed

## Test plan requirements

Minimum test coverage to require before cutover:

- `ANY` approval resolution
- `ALL` approval resolution
- direct user assignment
- role/group-derived assignment
- membership change while approval is pending
- unauthorized approval attempt
- workflow activation and version selection
- pending approvals by user view
- existing topic/script lifecycle regression

## Non-goals for this change wave

To protect quality and delivery speed, do not include by default:

- multiple active workflows
- arbitrary custom quorum logic
- broad no-code workflow automation beyond requested admin controls
- generalized IAM platform beyond what is needed for approval security and future compatibility
- full storyboard generation implementation

## Recommended first implementation slice

Best first slice:

1. P0 semantics and compatibility map
2. P1 identity and authorization foundation
3. P2 approval instance model
4. minimal operational UI support for pending approvals and visible assignees

Reason:

This gives the highest risk reduction early:

- closes impersonation risk
- establishes auditability
- validates approval semantics
- improves UI usefulness without forcing the full workflow builder immediately

## Exit signal before coding phase 2+

Do not proceed beyond P1 unless:

- approval semantics are signed off internally
- auth identity source is real
- assignment snapshot model is agreed
- regression test strategy is ready

## Related Follow-On Requests

The following request is related to the long-term UI and operating model, but should remain a separate stream from CR01 unless explicitly reprioritized:

- GitHub issue `#11` "Agent-first cowork surface: prioritize agent panels over artifact-first review layout"
  - internal note: `docs/17_Agent_First_Cowork_Surface_Feature_Request.md`
  - reason: this changes the primary operating-surface framing and should not be mixed into current CR01 stabilization or semantics-completion work
