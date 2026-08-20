# Lunaris Sync Policy

This repo does not have automatic round-trip sync between Pencil and the implemented UI.

To keep continuity real instead of assumed, the project uses an explicit sync contract.

## Source Of Truth

- Pencil is the source of truth for design intent and reference boards.
- Repo code is the source of truth for shipped implementation.
- Repo PNG exports are the portable snapshot of the Pencil boards that matter for continuity.

## Managed Sync Scope

The managed Lunaris sync scope is defined in [sync-map.json](/Users/Kay/Dev/tanaghom/docs/design/lunaris/sync-map.json).

Today that scope includes:

- Pencil boards:
  - `Tanaghom Overview`
  - `Workflow Graph`
  - `v2 — Agentic Content OS (vision)`
- Portable exports:
  - [01-overview.png](/Users/Kay/Dev/tanaghom/docs/design/lunaris/01-overview.png)
  - [02-workflow.png](/Users/Kay/Dev/tanaghom/docs/design/lunaris/02-workflow.png)
  - [04-vision-agentic-os.png](/Users/Kay/Dev/tanaghom/docs/design/lunaris/04-vision-agentic-os.png)
- Design-sensitive repo surfaces:
  - the Lunaris dashboard shell, lenses, and token files listed in `sync-map.json`

`00-foundation-options.png` and `03-reskin-topics.png` remain useful references, but are not part of the enforced sync set.

## Commit Rule

Any commit that changes a managed export or a tracked design-sensitive repo surface must also update:

- [sync-status.json](/Users/Kay/Dev/tanaghom/docs/design/lunaris/sync-status.json)

The pre-commit hook enforces that rule.

## What “In Sync” Means

For a commit to honestly set `"status": "in_sync"` in `sync-status.json`:

1. The relevant Pencil board has been reviewed.
2. If the Pencil board changed, its managed export has been refreshed in the repo.
3. If the repo UI changed in a way that affects the managed design intent, Pencil has been updated or explicitly reviewed against the implementation.
4. The SHA-256 hashes in `sync-status.json` match the current managed export files.

## Expected Workflow

### Pencil-first change

1. Update the Pencil board.
2. Export the managed PNG(s) into `docs/design/lunaris/`.
3. Update `sync-status.json`.
4. Commit.

### Repo-first UI change

1. Update the repo UI.
2. Review/update the matching Pencil board.
3. Re-export the managed PNG(s) if the visual reference changed.
4. Update `sync-status.json`.
5. Commit.

## What Is Still Local-only

The local Pencil file currently contains additional boards that are not automatically made portable:

- `lunaris: design system components`
- `dashboard-utility`
- `dashboard-revenue`
- `dashboard-football`

If any of those become continuity-critical, add them to `sync-map.json` and export them into the repo.
