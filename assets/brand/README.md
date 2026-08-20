# Brand & design assets

Canonical source of truth for identity. Two layers (mirrors the platform/multi-tenant model):

```
assets/brand/
  platform/stitch/      # the PLATFORM/builder brand (STITCH) — app shell, login, footer
  tenants/<tenant>/      # per-tenant CONTENT brand (e.g. tanaghum = Moataz/Tanaghum)
  tokens/                # design tokens (colors, type) as DATA for theming (per brand)
```

## Conventions
- Put the STITCH logo in `platform/stitch/` (e.g. `logo.svg`, `logo-dark.svg`, `favicon.png`).
- Each content brand lives under `tenants/<tenant_id>/` so theming maps to `tenant_id` (multi-tenant ready).
- Prefer **SVG** for logos; keep a PNG/favicon set. Name by role, not by tool (`logo-horizontal.svg`, not `final_v3.ai`).
- **Design tokens** (brand colors, fonts) go in `tokens/<brand>.json` (or CSS variables) — config-driven theming, no hardcoded colors (per the no-hardcode principle). Lets each tenant theme without code.
- Large editable source files (.ai/.psd/.fig) — consider Git LFS if they get big; keep web-ready exports here.

## Serving in the app
The Next.js dashboard serves static files from `dashboard/public/`. Keep canonical assets here in `assets/brand/`; copy (or build-step) the web-ready ones the dashboard needs into `dashboard/public/brand/`, and reference them from there. Canonical source stays in `assets/brand/`.
