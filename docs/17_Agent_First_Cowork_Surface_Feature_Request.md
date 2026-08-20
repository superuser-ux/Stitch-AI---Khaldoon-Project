# Agent-First Cowork Surface — Feature Request

Date: 2026-07-03
Status: defined
Primary tracking issue:
GitHub issue `#11` "Agent-first cowork surface: prioritize agent panels over artifact-first review layout"

## Summary

Introduce an additional operating surface that prioritizes agentic cowork instead of artifact-first review.

The current dashboard is centered on topics, scripts, approvals, and downstream production artifacts. Agent interaction exists, but it is still secondary to the artifact review surface.

This request asks for an explicit alternative mode where:

- agent panels become the primary operating surface
- topics, scripts, calendars, and related outputs remain available, but mainly as output and input panels attached to agent work
- the user experience better supports a future state where human users collaborate with multiple agent representatives and connected tools as active coworkers

## Product Intent

Shift the working model from:

- human reviews artifacts, with agents assisting

to:

- human supervises and collaborates with a visible team of agents, while artifacts are one class of output inside that cowork surface

This is a meaningful product and UI framing change, not just a layout tweak.

## Desired User Outcome

A user should be able to work from an agent-first surface where the main focus is:

- the active Agent Rep
- other Agent Reps
- AI agents currently enabled for the workflow
- the tools, skills, permissions, and connected systems active for each agent
- the current task, output stream, or blocked state for each agent

The current topic, script, workflow, and calendar panels should remain available, but as subordinate work surfaces rather than the primary frame.

## Proposed Scope

### In scope

- define an `agent-first` dashboard mode or a separate workspace surface
- introduce panel architecture for:
  - Agent Rep
  - other agent reps
  - AI agents
  - connected tools and skills per agent
  - current outputs and pending outputs per agent
- make artifact panels dockable or secondary within that surface
- preserve compatibility with existing topic, script, review, and approval flows
- define how the user switches between the current artifact-first mode and the new agent-first mode

### Out of scope for the first slice

- full multi-agent orchestration redesign
- expansion of autonomous authority beyond current approval and audit controls
- removal of the current artifact-first review UI
- deep redesign of external tool execution beyond visibility, state, and connected-context surfacing

## Acceptance Criteria

- a written interaction model exists for `artifact-first` versus `agent-first` operating modes
- the new surface shows a visible agent roster and state, not only a larger assistant sidebar
- each visible agent can expose:
  - role or function
  - active status
  - connected tool or skill context
  - current task, output, or blocked state
- topics and scripts remain reachable without losing current operational control
- switching modes does not break current review, approval, or audit flows
- implementation planning separates what can be delivered as UI framing from what requires backend or runtime support

## UX Constraints

- do not reduce this to a bigger chat drawer
- the surface should feel like a control room or cowork console, not a document review screen with extra widgets
- keep the distinction clear between:
  - human-controlled actions
  - agent-suggested actions
  - agent-executed actions
- preserve auditability and permission boundaries
- preserve the current artifact-first review flow until the new mode is proven

## Architectural Impact

This request likely spans:

- operational UI architecture
- agent and session state modeling
- tool and skill visibility modeling
- approval and permission framing
- future orchestration roadmap

This should therefore remain a distinct feature stream rather than being folded into current stabilization or CR01 completion issues.

## Risks

- UI complexity before the agent-state model is stable
- user confusion between agent visibility and actual agent authority
- regressions if this is layered into the existing review surface without a clear mode boundary
- false impression of multi-agent operational maturity before runtime support is actually ready

## Recommended Delivery Shape

### Slice 1

- define the mode boundary
- define the information architecture
- expose agent roster, status, connected context, and output associations
- preserve all current artifact review operations unchanged underneath

### Slice 2

- add richer per-agent task and tool state
- add workspace composition and panel behavior
- connect more of the existing workflow/admin/tooling state into the surface

### Slice 3

- align future orchestration/runtime support with the now-proven UI model

## Current Routing

This request is tracked as:

- GitHub issue `#11`
- this internal feature-request note

It should be planned after current stabilization and CR01 priority streams are sufficiently controlled, unless the user explicitly reprioritizes it.
