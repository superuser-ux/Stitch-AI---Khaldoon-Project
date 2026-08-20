# Content Schedule Reference

This package preserves the current content-operations scheduling reference shared by the content team so the product UI and the system model can align to an agreed baseline before we redesign or normalize it further.

## Source artifacts

- Original working document: `docs/design/lunaris/05-content-schedule-current-reference.docx`
- Diff-friendly extract: `docs/design/lunaris/05-content-schedule-current-reference.csv`
- Source received from: `/Users/Kay/Downloads/28_Day_Schedule_Current_Refernece.docx`
- Imported on: `2026-07-02`

## What the current team reference encodes

- Planning horizon: `28` days
- Cadence: `2` posts per day
- Daily slots: `09:00` and `20:00`
- Weekly grouping: `4` weeks of `7` days
- Slot fields shown to operators:
  - day number
  - post code for the `09:00` slot
  - format for the `09:00` slot
  - post code for the `20:00` slot
  - format for the `20:00` slot
- The schedule also carries manual format overrides inline using `was: ...` notes.

## Pillar legend in the reference

- `P1`: Self-awareness (`22` posts)
- `P2`: Relationships (`17` posts)
- `P3`: Kids (`9` posts)
- `P4`: Work (`4` posts)
- `P5`: Religion (`4` posts)

This matches the current blueprint assumption for the 28-day run and should remain consistent across the planner, review UI, and reporting surfaces.

## Alignment implications for UI and system design

- The calendar view should treat the schedule as a week-grouped planning board, not just a flat stream of cards.
- Each day should expose two stable lanes or slots: `09:00` and `20:00`.
- Each slot should visibly carry both the post code and the format because operators appear to reason with both together.
- The system should preserve format override history instead of flattening it away, because the current working document records schedule adjustments explicitly.
- Week separators matter operationally and should be represented in the planning UI.
- Pillar distribution should be inspectable at a glance so operators can confirm the run still respects the target mix.

## Recommended canonical review model

The `.docx` file is useful as a human-origin reference, but it should not remain the primary operational artifact.

Recommended forward model:

1. Keep the original `.docx` in the repo as a frozen source reference.
2. Keep a normalized machine-readable extract such as the CSV in this folder for diffs and QA.
3. Make the database-backed plan template the operational source of truth once the admin planning surface exists.
4. Export a visual schedule snapshot from the app for business review instead of relying on ad hoc document edits.

## Recommended next UI refinement

The current dashboard calendar should evolve toward a week-based board with explicit AM/PM slots, visible format labels, and clearer template-vs-generated status indicators. That will mirror how the content team already reviews scheduling while still moving us toward a controlled system-managed workflow.
