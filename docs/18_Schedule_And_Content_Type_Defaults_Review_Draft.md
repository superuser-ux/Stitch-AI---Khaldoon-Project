# Schedule And Content Type Defaults — Review Draft

This draft is for client confirmation before the related backlog is logged and fully implemented.

## 1. Schedule Stage Comes Before Topic Generation

### Proposed default behavior
- When a new run is created, the system first generates the schedule for that run.
- The schedule stage distributes planned content slots across the selected run period and according to the configured number of posts per day.
- At this stage, the system is visualizing and organizing the run structure as a real review surface.
- Each schedule slot should already show:
  - its schedule/topic code
  - its assigned default content type/framework
  - its date/day and slot position in the calendar
- No topic title is generated yet at this stage.
- The content type is already present at this stage as part of the calendar plan, but the topic title is still not generated.

### Purpose
- This stage gives the team a clear calendar view of the run before topic generation starts.
- It also lets the team confirm the planned code and content type allocation at slot level before titles are written.
- It allows the schedule itself to be reviewed and approved first.
- Only after schedule approval does the workflow move forward to topic generation.

### Flexibility requirement
- This should be the default operating mode now.
- Later, this behavior should remain configurable in case the workflow needs to change.

## 2. One Topic Maps To One Content Type

### Proposed default behavior
- After the schedule stage is approved, the system generates each topic under a default constraint:
- Each topic must map to the single content type already allocated to its approved schedule slot.
- The same topic should not be produced in multiple different framework formats by default.

### Meaning in practice
- The schedule slot is created first.
- That slot already carries one code and one assigned content type/framework.
- A topic is then generated once for that approved slot.
- The script for that topic is then generated according to that assigned content type.
- The system should therefore treat topic generation and script generation as linked through one framework type per topic.

### Purpose
- This matches the client’s current operating model.
- It creates a cleaner one-to-one relationship between:
  - schedule slot
  - schedule code
  - topic
  - content type
  - script
- It reduces duplication and ambiguity in production planning.

### Flexibility requirement
- This one-topic-to-one-content-type rule should be the default setting now.
- Later, the system should remain flexible enough to support different rules if the operating model changes.

## 3. Suggested Confirmation Wording

Please confirm the following:

1. The workflow should begin with a schedule approval stage, where the run calendar is reviewed before any topic titles are generated.
2. During the schedule stage, no topic titles are yet generated, but each schedule slot already shows its code and assigned content type/framework.
3. After schedule approval, each generated topic should map to the single content type already allocated in the approved schedule.
4. Under the current default model, the same topic should not be produced in multiple framework formats.
5. The resulting script should follow the single assigned content type for that topic.
6. Both behaviors should be implemented as default settings now, while remaining configurable later.

## 4. Implementation Note

The first requirement aligns with the new schedule-first workflow direction already being introduced.

The second requirement affects:
- planner and schedule approval flow
- schedule slot code visibility
- schedule-stage content-type visibility and persistence
- topic generation rules
- content type assignment rules
- script generation input rules
- review and calendar UI wording

These should be logged only after the client confirms the default behavior above.

## 5. Implementation Acceptance Criteria

The requirement should be considered correctly implemented only when all of the following are true:

### Schedule stage
- Creating a new run first produces a schedule-stage review surface, not topic titles.
- Each schedule slot is visible in calendar form before topic generation starts.
- Each visible schedule slot shows:
  - the user-facing schedule/topic code
  - the assigned content type/framework
  - the day/date position and post slot
- Topic title fields are still empty or explicitly marked as not yet generated at this stage.
- Schedule approval must complete before the topic generation action becomes available.

### Schedule-to-topic handoff
- After schedule approval, the next stage exposes topic generation.
- Topic generation consumes the approved schedule allocation instead of rebuilding content-type allocation from scratch.
- The system preserves the approved schedule code and assigned content type as the basis for the generated topic.

### One-topic-to-one-content-type default
- Each generated topic is attached to exactly one approved schedule slot.
- Each generated topic inherits exactly one assigned content type/framework from that slot.
- The same topic is not generated into multiple framework types under the default operating mode.
- Script generation uses that same assigned content type as its governing framework.

### UI and auditability
- Schedule-stage calendar, list, and review surfaces all show the same primary user-facing code consistently.
- Content type visibility is consistent across schedule, topic, and script stages.
- Internal system IDs remain secondary metadata only.
- Audit and persisted records keep the approved schedule allocation that topic generation was derived from.

## 6. Implementation Backlog Slices

Recommended delivery order:

### Slice S1 - Planner and data contract
- Ensure run planning allocates:
  - schedule code
  - default content type/framework
  - day/post slot placement
- Treat content-type allocation as part of schedule planning, not topic generation.
- Confirm the slot read model exposes the assigned content type cleanly to the UI.

### Slice S2 - Schedule-stage engine behavior
- Keep schedule as the first review stage.
- Prevent topic generation until schedule approval is complete.
- Preserve approved schedule allocation for downstream topic generation.
- Ensure reopen, drop, restore, and approval behavior do not discard the slot’s assigned content type or visible code.

### Slice S3 - Topic generation contract
- Make topic generation consume the approved schedule slot as input.
- Enforce the default rule:
  - one approved schedule slot
  - one generated topic
  - one inherited content type
- Prevent default generation paths that duplicate the same topic into multiple formats.

### Slice S4 - UI and UX alignment
- Show the user-facing code prominently in schedule, topic, and script review.
- Show the assigned content type prominently in the schedule calendar itself.
- Keep topic-title copy explicit at schedule stage:
  - title not generated yet
  - content type already assigned
- Keep list, grid, and calendar representations semantically aligned.

### Slice S5 - Regression coverage
- Add tests for:
  - new run opens into schedule-first flow
  - schedule stage shows code and content type before titles
  - topic generation is unavailable before schedule approval
  - topic generation becomes available after schedule approval
  - generated topic inherits the schedule-assigned content type
  - one topic does not fan out into multiple content types under the default rule

## 7. Open Product Notes

- The default rule is fixed for now, but the data model should not hard-code it irreversibly.
- Future configurability should likely distinguish between:
  - schedule allocation policy
  - topic-to-format mapping policy
  - script generation policy
- If the client later wants one topic to drive multiple formats, that should be a deliberate configurable mode rather than an accidental side effect of generation.
