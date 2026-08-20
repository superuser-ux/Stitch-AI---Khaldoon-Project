# Product help — living user-guide source of truth (#46)

This directory is the **canonical, maintained** home of client-facing help content. It exists so
that #44 (in-app guided tour) and #45 (help copilot) consume ONE stable, anchorable source — never
the dated trial exports.

| Path | What it is |
|---|---|
| `client-guide.md` | The living client reviewer guide, sectioned into stable anchors |
| `operator-guide.md` | The living operator/admin guide — **internal-only, never client-facing, never linked from `client-guide.md`**; same maintenance policy as the client guide |
| `feedback-template.md` | The living feedback template |
| `screenshots/` | Current guide screenshots, stable topic-based filenames; operator-guide assets use an `op-` filename prefix |
| `artifacts/client-trial-guide/` (repo root) | **Immutable dated snapshots** from specific trials — never edited. NOTE: `artifacts/` is gitignored by design ("local QA / integration artifacts — never committed"), so snapshots are a LOCAL operator archive, not versioned content |

## Living vs snapshot

- `artifacts/client-trial-guide/` preserves each trial's guide/PDFs/screenshots **exactly as
  delivered**, dated, as a local operator archive (the directory is deliberately outside git).
  History is never rewritten there.
- This directory is updated continuously. When a client-facing trial or release ships, export a
  dated snapshot into `artifacts/` if a delivered record is needed — the living source stays here.

## Versioning policy

- `client-guide.md` carries a visible **Last reviewed** date and **Release/trial tag** at the top.
- Every client-facing release or trial refresh requires a guide review pass before use.
- Trial-specific facts (URLs, credentials wording, purge notices) stay per-engagement — recorded in
  the dated snapshot, referenced generically in the living guide.

## Screenshot policy

- Filenames are **stable by section/topic** (`03-round-selector.png`, `06-topic-card.png`, …);
  replace image contents when the UI changes materially, keep the name.
- If a screenshot goes stale before a replacement exists, mark the section
  **`screenshot refresh pending`** in the guide — never let it silently drift. (Two such markers
  are currently open: the script-stage capture and the evolved card badges.)

## Maintenance process (owner-review gate)

1. **Feature owner** — when shipping UI/flow changes that touch help-visible behavior, flag the
   drift (issue comment or directive note referencing this directory).
2. **Docs maintainer** — update the guide text and refresh screenshots for changed surfaces.
3. **Owner/release approver** — final gate before any client-facing use, confirming:
   - wording matches the current UI;
   - blocked/deferred features are still described honestly;
   - screenshots match the actual surface.

Nothing becomes the current client-facing version without step 3.

## Refresh checklist (run per release/trial)

- [ ] Walk the real dashboard against every guide section; fix drifted wording/labels.
- [ ] Recapture screenshots for any changed surface (keep filenames stable).
- [ ] Clear or renew every `screenshot refresh pending` marker.
- [ ] Verify known-limitations still match what is actually blocked.
- [ ] Update **Last reviewed** + **Release/trial tag** in `client-guide.md`.
- [ ] Owner review (step 3 above).
- [ ] If delivering to a client: export the dated snapshot into `artifacts/client-trial-guide/`.

## Downstream consumers

- **#44 guided tour**: map tour steps to the guide's section anchors (`{#walkthrough-*}`, etc.).
- **#45 help copilot**: retrieve from these bounded sections and the known-limitations block.
- Neither may fork a parallel user-facing copy — this directory is the single source (#46).
