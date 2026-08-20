# CR01 Parallel Execution Map

Date: 2026-07-02
Status: internal coordination document

## Purpose

This document defines how CR01 can be executed in parallel without creating schema drift, API drift, or merge chaos.

It complements:

- [docs/10_Change_Request_01_Internal_Assessment.md](/Users/Kay/Dev/tanaghom/docs/10_Change_Request_01_Internal_Assessment.md)
- [docs/11_Change_Request_01_Phased_Backlog.md](/Users/Kay/Dev/tanaghom/docs/11_Change_Request_01_Phased_Backlog.md)

## Recommendation

Parallelize by dependency boundary, not by backlog phase label.

Use multiple worktrees, not one shared checkout.

Recommended maximum active parallel tracks at one time:

- 3 active implementation tracks

Beyond that, coordination cost is likely to exceed the gain.

## Recommended worktrees

- `cr01-foundation`
- `cr01-approval-core`
- `cr01-workflow-backend`
- `cr01-ops-ui`
- `cr01-admin-ui`
- optional later: `cr01-methodology-formats`

## Recommended branches

- `codex/cr01-integration`
- `codex/cr01-foundation`
- `codex/cr01-approval-core`
- `codex/cr01-workflow-backend`
- `codex/cr01-ops-ui`
- `codex/cr01-admin-ui`
- `codex/cr01-methodology-formats`

## Track layout

### Track S - Foundation and semantics

Owns:

- CR01-P0
- schema direction
- API contract direction
- compatibility map

Allowed files:

- `docs/10_*`
- `docs/11_*`
- `docs/12_*`
- schema proposal docs

Should not edit:

- live engine behavior unless required for foundation seam work

### Track A - Approval core

Owns:

- CR01-P1
- CR01-P2

Primary files:

- `db/init/schema.sql`
- `db/migrations/*`
- `gates/api.py`
- `gates/engine.py`
- supporting auth/principal modules

Should not edit in parallel with others:

- migration numbering
- approval-resolution core in `gates/engine.py`

### Track B - Workflow backend

Owns:

- CR01-P3

Primary files:

- workflow schema/migrations
- engine mapping layer
- workflow-related API endpoints

Can start when:

- Track S is complete
- Track A identity/assignment assumptions are stable

### Track C - Operational UI

Owns:

- CR01-P4

Primary files:

- `dashboard/lib/*`
- `dashboard/components/review/*`
- operational route handlers

Can start when:

- backend contracts for actor identity and approval visibility are frozen enough

Should not invent:

- approval semantics
- workflow semantics

### Track D - Admin UI

Owns:

- CR01-P5

Primary files:

- new admin routes/components
- builder/editor UI

Can start with:

- shell, route layout, information architecture

Should wait for:

- workflow persistence model and API shape before full builder wiring

### Track E - Methodology and format management

Owns:

- CR01-P6

Primary files:

- methodology/content-format schema
- admin CRUD/versioning UI

Can start when:

- shared versioning/audit conventions are settled

## Safe execution waves

### Wave 1

- Track S
- Track A

### Wave 2

- Track B
- Track C

### Wave 3

- Track D
- Track E

### Wave 4

- storyboard-ready extension points

## Merge order

Recommended merge order into `codex/cr01-integration`:

1. foundation/spec seams
2. identity/auth foundation
3. approval core
4. workflow backend
5. operational UI
6. admin UI
7. methodology/format management

## Coordination rules

- Only one track owns migration numbering at a time.
- Only one track edits approval resolution core at a time.
- UI tracks consume backend contracts; they do not define them.
- Track owners must publish contract notes before dependent tracks start wiring.
- Rebase frequently onto `codex/cr01-integration`.

## Stop-the-line conditions

Pause dependent tracks if any of these change:

- approval semantics
- actor identity source
- assignment snapshot model
- workflow version model
- stage transition contract

## Immediate recommendation

Start with:

- Track S: finalize P0 and coordination docs
- Track A: identity seam + approval actor hardening + role/group groundwork

Delay:

- workflow builder UI
- full methodology management UI

until backend contracts stabilize.
