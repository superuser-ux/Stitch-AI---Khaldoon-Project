# Content Framework Alignment

This note preserves the client-provided content-framework references inside the repo and maps them to the current Tanaghom content-format model so backend and UI work can use the same guardrails.

## Source set

- `docs/design/lunaris/06-carousel-framework.docx`
- `docs/design/lunaris/06-carousel-framework.md`
- `docs/design/lunaris/07-hero-reel-framework.docx`
- `docs/design/lunaris/07-hero-reel-framework.md`
- `docs/design/lunaris/08-3sec-caption-framework.docx`
- `docs/design/lunaris/08-3sec-caption-framework.md`

Imported on: `2026-07-02`

## Canonical mapping into the current system

| Client framework | Framework id | Current system format | Mapping status | Notes |
|---|---|---|---|---|
| Deep Transformation Carousel | `carousel.deep.01` | `carousel` | direct | Locked 7-slide structure with closing caption sections. |
| Hero Reel | `60.viral.01` | `reel_studio` | mapped variant | Best current fit is the scripted high-weight reel; split to a dedicated format later only if operations need a separate quota or workflow. |
| 3sec + Caption | `15.viral.01` | `3sec_reel_caption` | direct | Reel is the stop; caption carries the deeper logic. |

### CANON-014 source formats — full accounting (#87)

Every CANON-014 source format is explicitly accounted for below, so no future operator infers dropped data
or a silent parse failure. The client CANON files stay **frozen references**; the four `Reel — *` variants
are **intentionally consolidated** into the single operational `Hero Reel` format (split into dedicated
formats later only if operations need a separate quota or workflow).

| CANON-014 source format | Operational format | Status | Rationale |
|---|---|---|---|
| `Reel — Studio` | `Hero Reel` | consolidated | The scripted high-weight reel is the current single reel format. |
| `Reel — iPhone` | `Hero Reel` | consolidated | Raw/intimate reel variant folded into `Hero Reel`. |
| `Reel — Podcast` | `Hero Reel` | consolidated | Conversational reel variant folded into `Hero Reel`. |
| `Reel — Event Cut` | `Hero Reel` | consolidated | Social-proof reel variant folded into `Hero Reel`. |
| `Carousel` | `Carousel` | direct | Deep Transformation Carousel. |
| `Pic + Caption` | `Pic + Caption` | direct | Visual stop + full spoken script in caption. |
| `3sec Reel + Caption` | `3sec Reel + Caption` | direct | Ultra-short visual stop; caption carries the content. |

**No CANON-014 data is dropped** — the 7 source formats map onto the 4 operational formats (four reel
variants → one `Hero Reel`). `system_config.yaml`'s fallback `format_distribution_weekly` now uses only
these operational names; the managed `content_format` weights remain the authoritative planning source.

## Implementation implications

- Content-format versions should expose framework rules as structured metadata, not just free-text notes.
- Admin users should be able to see the purpose, structure, constraints, and reference documents for each framework while reviewing format definitions.
- Planning and review surfaces should treat these frameworks as production guardrails so a selected format implies a known creative structure.
- The current schedule and methodology references remain valid, but the content team now has sharper per-format execution rules than the original canon alone provided.

## Current decision

- Preserve the original client files in the repo as frozen references.
- Seed the framework rules into `content_format_version.production_rules`.
- Surface the framework details in the admin UI as read-only operational guidance.
- Keep the current format taxonomy stable for now; do not split a dedicated `hero_reel` content format until there is a scheduling or approval reason to do so.
