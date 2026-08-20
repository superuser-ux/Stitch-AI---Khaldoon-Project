# Release Gate And Delivery Control

Date: 2026-07-03
Status: active internal operating rule
Primary tracking issue: GitHub issue `#1` "Stabilization release gate and regression-control workflow"

## Purpose

This document defines how Tanaghom work is delivered from now on so implementation stays progressive, controlled, and auditable.

The goal is to prevent:

- mixed-scope branches
- demo-time surprises
- regressions caused by incremental fixes landing without full verification
- client feedback getting lost between chat, code, and GitHub

## Core Rule

One issue = one acceptance target = one branch or worktree.

If a new request changes scope, semantics, or release risk, it must become:

- a new GitHub issue, or
- an explicit scope expansion comment on the existing issue before more code is written

Do not continue landing unrelated fixes into the same stream just because the files overlap.

## Delivery States

Each active issue should move through these states in order:

1. `Defined`
2. `In implementation`
3. `Ready for sacrificial validation`
4. `Demo-safe`
5. `Merge-ready`
6. `Closed`

Definitions:

- `Defined`: scope, acceptance, and exclusions are written.
- `In implementation`: code changes are active and issue scope is still stable.
- `Ready for sacrificial validation`: implementation is done enough for a throwaway end-to-end proof on non-client-critical data.
- `Demo-safe`: the feature was validated on the real user surface and the current demo environment is green.
- `Merge-ready`: required evidence is attached and remaining risks are explicitly documented.

## Mandatory Evidence Per Issue

Every issue that changes behavior must record:

- what changed
- what was intentionally not changed
- automated checks run
- manual checks run
- known residual risk

Minimum evidence types:

- backend behavior change: selftests or equivalent
- dashboard behavior change: browser validation on the real UI
- review-flow change: real per-item and batch-path validation if both paths exist
- operational change: localhost, public URL, and mobile smoke if the user-facing surface is affected
- Telegram change: Telegram-specific validation on the control channel

## Green Status Definition

The system is only considered fully green when all applicable checks pass:

1. Gate API healthy
2. Dashboard healthy on local host
3. Public Tailscale URL healthy and aligned to the active dashboard port
4. Mobile-responsive smoke passes on both local and public URLs
5. Telegram control channel is reachable and the bot process is healthy
6. Relevant automated suites for the changed scope are green
7. No known stale asset or stale port mismatch remains

Current operational checker:

- `tools/dashboard-health-check.sh`

Use:

- `tools/dashboard-health-check.sh`
- `tools/dashboard-health-check.sh --fix-tailscale`

This operational preflight is mandatory before telling the user a demo is ready.

## Required Validation Sequence

Validation should happen in this order:

1. targeted unit or selftest checks
2. affected API checks
3. sacrificial end-to-end run on throwaway data
4. real browser validation on localhost
5. public URL validation
6. mobile smoke
7. Telegram validation if in scope

Do not skip directly from "build passes" to "client ready".

## Review And UX Rule

For operational review flows:

- per-item actioning is the default path
- selective multi-select batch actioning is optional acceleration
- full-batch actioning is secondary, not primary

Any change in this area must verify:

- card state
- disposition bar state
- committed result
- calendar presentation if the same items are shown there

No release is demo-safe if those states can drift.

## Feedback Intake Rule

All feedback must be captured in one of three forms:

### Bug

- what was done
- expected behavior
- actual behavior
- where it happened

### Change

- desired behavior
- business reason
- urgency

### New request

- outcome wanted
- constraints
- whether it changes workflow semantics, permissions, UI, or integrations

## How Feedback Is Routed

- Small clarification inside accepted scope: comment on the active issue
- Behavior change inside accepted scope: comment on the active issue and update acceptance text if needed
- New semantic or architectural requirement: open a new issue
- Client change request with multiple streams: create an assessment doc, then split into issues by acceptance target

Do not keep actionable scope only in chat.

## GitHub Usage Rules

GitHub is the canonical work tracker for implementation status.

Use it to record:

- issue scope
- acceptance criteria
- implementation notes
- validation evidence
- residual risks
- close-out notes

Current active issue map:

- `#1` release gate and regression-control workflow
- `#2` sacrificial end-to-end rework validation
- `#3` review surface hardening
- `#4` run planning and generation hardening
- `#5` operational health and demo-safe preflight
- `#6` workflow governance and admin-surface hardening
- `#7` calendar, numbering, and content-type alignment
- `#8` Telegram control-channel hardening
- `#9` approval identity hardening
- `#10` approval semantics completion
- `#11` agent-first cowork surface

## Continuity File Update Rule

Update `BUILD_STATE.md` or `HANDOFF.md` only when at least one of these is true:

- an issue changed delivery state
- a new runbook or control rule was adopted
- an important environment constraint changed
- a user-visible verification result materially changed readiness

Do not use continuity files as a substitute for issue tracking.

## Merge Gate

Before merge, confirm:

- issue acceptance is met or explicitly narrowed
- tests relevant to the changed scope are green
- manual validation was performed on the real surface
- demo/runtime health is green if the user-facing surface changed
- residual risks are written down
- any follow-up work is split into separate tracked issues

## Future Change Requests

When a new client change request arrives:

1. create or update an internal assessment doc
2. identify schema, engine, UI, auth, ops, and integration impacts
3. create GitHub issues by acceptance target, not by file area
4. sequence the work so semantics and authorization land before UI flexibility
5. do not present the request as "implemented" until sacrificial and real-surface validation are both complete

## Current Adoption

This process is now the working delivery rule for this repository.

Any future agent or contributor should read:

- `README.md`
- `BUILD_STATE.md`
- `HANDOFF.md`
- this file

before resuming implementation on active workstreams.
