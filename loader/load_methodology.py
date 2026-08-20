#!/usr/bin/env python3
"""
Tanaghom methodology loader (M1).

Parses the canon (CANON-010..015) and the 42 HCS seed records straight from the
markdown source-of-truth files and loads them into the methodology tables:
    pillar, lens, hook_type, format, hcs

- Source files are the single source of truth; this script only transcribes them.
- Insertion preserves canon order; hcs also stores an explicit seq_in_pillar so the
  no-repeat cursor (M2) has a deterministic walk order independent of row storage.
- Idempotent: every insert is an UPSERT, so re-running re-syncs without duplicates.

Run it against the compose Postgres (see loader/README.md). Counts are asserted at
the end so a partial/garbled parse fails loudly instead of silently under-seeding.
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "methodology" / "canon"
RECORDS = REPO / "methodology" / "records" / "HCS_Records_All42_Seed_v1.md"
SOURCE_FILES = [
    CANON / "CANON-010_Pillars.md",
    CANON / "CANON-011_Human_Core_Struggles.md",
    CANON / "CANON-012_Content_Lenses.md",
    CANON / "CANON-013_Hook_Types.md",
    CANON / "CANON-014_Content_Formats.md",
    CANON / "CANON-015_28_Day_Calendar_Model.md",
    RECORDS,
]
PLATFORM_SEEDS = [
    {
        "platform_key": "instagram",
        "name": "Instagram",
        "channel_role": "publish_target",
        "description": "Primary publish target for the Tanaghom content pipeline.",
        "config": {"status": "active", "origin": "seed"},
        "active": True,
    },
    {
        "platform_key": "telegram",
        "name": "Telegram",
        "channel_role": "control_channel",
        "description": "Reviewer-control and approval channel, not a publish target.",
        "config": {"status": "active", "origin": "seed"},
        "active": True,
    },
]
CONTENT_TYPE_BOOTSTRAP = [
    {
        "format_key": "hero_reel",
        "name": "Hero Reel",
        "description": "Primary transformational reel content type. Legacy reel execution modes collapse into one managed type.",
        "use_case": "Deep transformational short-form reel built around one painful idea, a cognitive flip, and an immediate action step.",
        "lens_fit": ["L1", "L2", "L3", "L4", "L5"],
        "production_notes": "Treat studio, iPhone, podcast, and event-cut as production treatments inside the type rather than separate content types.",
        "platform_targets": ["instagram"],
        "production_rules": {
            "seed_source": "client_framework_bootstrap",
            "framework_id": "60.viral.01",
            "framework_name": "Hero Reel",
            "framework_summary": "Deep transformational short-form reel built around one painful idea, a cognitive flip, and an immediate action step.",
            "script_guidance": "Keep one painful idea only. Open in the first 0-3 seconds. Preserve the micro-story, cognitive flip, and actual step.",
            "production_guidance": "Choose the shoot treatment per slot while preserving the same narrative backbone and final line.",
            "distribution_guidance": "Primary short-form reel for Instagram and future short-video publish targets.",
            "planning": {"weekly_count": 9, "sort_order": 10},
            "shoot_treatments": ["studio", "iphone", "podcast", "event_cut"],
            "platform_profiles": {
                "instagram": {
                    "surface": "reel",
                    "aspect_ratio": "9:16",
                    "duration_seconds": 60,
                    "caption_mode": "supporting_caption",
                },
            },
        },
    },
    {
        "format_key": "carousel",
        "name": "Carousel",
        "description": "Belief-shift carousel content type with a locked seven-slide progression.",
        "use_case": "Seven-slide belief-shift carousel that moves from disruption to ownership and a concrete behavioural shift.",
        "lens_fit": ["L1", "L2", "L3", "L4", "L5"],
        "production_notes": "The slide story is the product. Captions carry the positive-side and science closures when used.",
        "platform_targets": ["instagram"],
        "production_rules": {
            "seed_source": "client_framework_bootstrap",
            "framework_id": "carousel.deep.01",
            "framework_name": "Deep Transformation Carousel",
            "framework_summary": "Seven-slide belief-shift carousel that moves from disruption to ownership and a concrete behavioural shift.",
            "script_guidance": "Write one idea only. Each slide earns the next. Preserve the reflective CTA and do not soften the core truth too early.",
            "production_guidance": "Treat slide one as its own hook asset. Preserve readability and slide pacing over decorative density.",
            "distribution_guidance": "Primary carousel for Instagram feeds and other swipe-based surfaces.",
            "planning": {"weekly_count": 3, "sort_order": 20},
            "platform_profiles": {
                "instagram": {
                    "surface": "carousel",
                    "slide_count": 7,
                    "closing_sections": ["positive_side", "science"],
                },
            },
        },
    },
    {
        "format_key": "pic_caption",
        "name": "Pic + Caption",
        "description": "Static visual with the full argument delivered in the caption.",
        "use_case": "Visual stop + full spoken script in caption.",
        "lens_fit": ["L1", "L2", "L3", "L4", "L5"],
        "production_notes": "Legacy carry-forward until the client provides a replacement framework.",
        "platform_targets": ["instagram"],
        "production_rules": {
            "seed_source": "legacy_carry_forward",
            "framework_name": "Pic + Caption",
            "framework_summary": "Static visual stop with the full argument carried by the caption.",
            "script_guidance": "The image stops the scroll; the caption does the heavy lifting.",
            "production_guidance": "Prioritise readable cover text and a caption structure that can carry the full script cleanly.",
            "distribution_guidance": "Feed-first format for static posts where the caption is the primary delivery vehicle.",
            "planning": {"weekly_count": 1, "sort_order": 30},
            "platform_profiles": {
                "instagram": {
                    "surface": "feed_post",
                    "caption_mode": "full_script",
                },
            },
        },
    },
    {
        "format_key": "3sec_reel_caption",
        "name": "3sec Reel + Caption",
        "description": "Ultra-short reel stop with the depth carried in the long caption.",
        "use_case": "Ultra-short viral reel that delivers a fast emotional stop while the deeper teaching lives in the long caption.",
        "lens_fit": ["L1", "L2", "L3", "L4", "L5"],
        "production_notes": "Use the reel for the hit and the caption for the real argument.",
        "platform_targets": ["instagram"],
        "production_rules": {
            "seed_source": "client_framework_bootstrap",
            "framework_id": "15.viral.01",
            "framework_name": "3sec + Caption",
            "framework_summary": "Ultra-short viral reel that delivers a fast emotional stop while the deeper teaching lives in the long caption.",
            "script_guidance": "Keep one idea only. Use one sentence per beat. Do not teach inside the reel itself.",
            "production_guidance": "Optimise the first seconds for interruption, then let the caption carry the deeper delivery.",
            "distribution_guidance": "Use as a high-frequency reel entry point with a deliberately deep caption.",
            "planning": {"weekly_count": 1, "sort_order": 40},
            "platform_profiles": {
                "instagram": {
                    "surface": "reel",
                    "aspect_ratio": "9:16",
                    "duration_seconds": 15,
                    "caption_mode": "long_deep_caption_required",
                },
            },
        },
    },
]
CONTENT_FRAMEWORK_RULES = {
    "carousel": {
        "framework_id": "carousel.deep.01",
        "framework_name": "Deep Transformation Carousel",
        "framework_status": "managed",
        "framework_summary": "Seven-slide belief-shift carousel that moves from disruption to ownership and a concrete behavioural shift.",
        "mapping_note": "Direct client framework mapping for the canonical Carousel format.",
        "reference_docs": [
            "docs/design/lunaris/06-carousel-framework.docx",
            "docs/design/lunaris/06-carousel-framework.md",
        ],
        "principles": [
            "One core belief to challenge per carousel.",
            "Pain -> awareness -> reframe -> ownership -> action.",
            "Every slide earns the next; no filler.",
            "Truth is more powerful than comfort.",
            "Specificity over generality.",
            "Closure must feel earned, not falsely positive.",
        ],
        "structure": [
            {"step": "slide_1", "label": "Hook", "guidance": "One provocative statement that creates immediate recognition or discomfort.", "constraint": "1 sentence, max 15 words."},
            {"step": "slide_2", "label": "Concept Anchor", "guidance": "Name the hidden mechanism with a memorable label or analogy.", "constraint": "2-3 sentences."},
            {"step": "slide_3", "label": "Human Proof", "guidance": "Show 2-3 recognisable micro-portraits of people living the problem.", "constraint": "1-2 sentences per portrait."},
            {"step": "slide_4", "label": "Distillation", "guidance": "State the cold truth through psychological, behavioural, and practical lenses.", "constraint": "3 sentences, one per lens."},
            {"step": "slide_5", "label": "Practical Bridge", "guidance": "Reframe the wrong question into the right one and name the behavioural shift.", "constraint": "3-4 sentences."},
            {"step": "slide_6", "label": "Meaningful Closure", "guidance": "Land the transformation of the opening belief with one memorable line.", "constraint": "1-2 sentences."},
            {"step": "slide_7", "label": "Reflective CTA", "guidance": "Ask a personal, uncomfortable question instead of a generic engagement CTA.", "constraint": "1 question."},
        ],
        "closing_sections": [
            {"label": "The Positive Side", "guidance": "Acknowledge the healthy version of the pattern so the post does not read as purely critical."},
            {"label": "Science", "guidance": "Add one accessible psychology or neuroscience fact only if it sharpens the emotional logic."},
        ],
        "dos": [
            "Use Palestinian dialect in spoken/caption text.",
            "Make slide 1 feel accusatory enough to stop the scroll.",
            "Use a named analogy or concept label on slide 2.",
            "Ground human proof in real-life archetypes.",
            "Keep each slide focused on one idea.",
        ],
        "donts": [
            "Do not mix multiple beliefs or problems.",
            "Do not comfort the reader before the truth lands.",
            "Do not use generic engagement CTAs.",
            "Do not over-explain the point.",
            "Do not end with a motivational quote.",
        ],
        "constraints": {
            "slide_count": 7,
            "cta_mode": "reflective_question",
            "hook_max_words": 15,
            "language": "Palestinian Arabic",
        },
    },
    # #177 — keyed by the OPERATIONAL format_key so the rules actually merge in _content_type_seed_rows().
    # This entry was previously keyed "reel_studio" (the CANON-014 source name); the consolidation
    # renamed the operational format to "hero_reel" (docs/design/lunaris/09-content-framework-alignment.md),
    # so the full 10-beat structure never reached the live registry and the UI fell back to the
    # generic 4-beat labels.
    "hero_reel": {
        "framework_id": "60.viral.01",
        "framework_name": "Hero Reel",
        "framework_status": "managed",
        "framework_summary": "Deep transformational short-form reel built around one painful idea, a cognitive flip, and an immediate action step.",
        "mapping_note": "Direct client framework mapping for the operational Hero Reel format (the four CANON-014 reel variants are consolidated into it).",
        "reference_docs": [
            "docs/design/lunaris/07-hero-reel-framework.docx",
            "docs/design/lunaris/07-hero-reel-framework.md",
        ],
        "principles": [
            "One idea only.",
            "Pain -> awareness -> ownership -> action.",
            "No motivation without mechanism.",
            "No comfort without truth.",
            "Avoid negative wording while keeping the pain specific.",
        ],
        "structure": [
            {"step": "beat_1", "label": "Hook", "guidance": "Open with the problem inside the first 3 seconds."},
            {"step": "beat_2", "label": "Micro-Story", "guidance": "Localise the pain in one recognisable moment."},
            {"step": "beat_3", "label": "Deep Value", "guidance": "Deliver the core value statement behind the pain."},
            {"step": "beat_4", "label": "Cognitive Flip", "guidance": "Reframe the idea so the listener sees themselves differently."},
            {"step": "beat_5", "label": "Killer Quote", "guidance": "Land the episode's locked quote cleanly."},
            {"step": "beat_6", "label": "Metaphor", "guidance": "Use one metaphor that helps the truth stick."},
            {"step": "beat_7", "label": "Reality Snap", "guidance": "Return to the pain with a sharper real-life snap on the same idea."},
            {"step": "beat_8", "label": "Ownership Line", "guidance": "Push the burden of change back to the listener."},
            {"step": "beat_9", "label": "Actual Step", "guidance": "Name one real action, not a motivational slogan."},
            {"step": "beat_10", "label": "Viral Ending", "guidance": "End with a line worth repeating or sharing."},
        ],
        "dos": [
            "Speak directly to the listener.",
            "Use Palestinian dialect for the spoken script.",
            "Make pain specific.",
            "Make action concrete.",
        ],
        "donts": [
            "Do not stack multiple ideas.",
            "Do not preach.",
            "Do not over-explain.",
            "Do not add science unless it sharpens the pain.",
        ],
        "constraints": {
            "duration_seconds": 60,
            "spoken_word_limit": 130,
            "hook_window_seconds": "0-3",
            "language": "Palestinian Arabic",
        },
    },
    "3sec_reel_caption": {
        "framework_id": "15.viral.01",
        "framework_name": "3sec + Caption",
        "framework_status": "managed",
        "framework_summary": "Ultra-short viral reel that delivers a fast emotional stop while the deeper teaching lives in the long caption.",
        "mapping_note": "Direct client framework mapping for the canonical 3sec Reel + Caption format.",
        "reference_docs": [
            "docs/design/lunaris/08-3sec-caption-framework.docx",
            "docs/design/lunaris/08-3sec-caption-framework.md",
        ],
        "principles": [
            "One idea only.",
            "One sentence per beat.",
            "No teaching inside the reel; only insight.",
            "End with a line people want to send.",
            "Use the caption for the deeper argument.",
        ],
        "structure": [
            {"step": "beat_1", "label": "Hook", "guidance": "Open with a shock or mirror line."},
            {"step": "beat_2", "label": "Value Line", "guidance": "Deliver the reframe in one clean line."},
            {"step": "beat_3", "label": "Action Nudge", "guidance": "Hint at the action without teaching it in detail."},
            {"step": "beat_4", "label": "Viral Ending", "guidance": "Close with a shareable truth."},
        ],
        "dos": [
            "Be sharp.",
            "Be human.",
            "Be uncomfortable.",
        ],
        "donts": [
            "Do not explain.",
            "Do not teach inside the reel.",
            "Do not stack ideas.",
        ],
        "constraints": {
            "duration_seconds": 15,
            "caption_depth": "long_deep_caption_required",
            "language": "Palestinian Arabic",
        },
    },
    # #177 — Pic + Caption has NO client framework yet: mark it explicitly legacy so every surface
    # (writer read model, review cards, methodology admin) can say so instead of silently rendering
    # the generic fallback as if it were client framework truth. No structure is fabricated here.
    "pic_caption": {
        "framework_status": "legacy_carry_forward",
        "mapping_note": "Legacy carry-forward — the client has not provided a framework for Pic + Caption; the writer uses the generic fallback structure until a real framework source is added.",
    },
}


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------
def _clean(cell: str) -> str:
    """Strip a markdown table cell: surrounding whitespace and backticks."""
    return cell.strip().strip("`").strip()


def parse_table_after(text: str, heading_substring: str):
    """Return the first markdown table that appears after a heading containing
    `heading_substring`, as a list of dicts keyed by the (cleaned) header cells.
    Order is preserved.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") and heading_substring.lower() in line.lower():
            start = i
            break
    if start is None:
        raise ValueError(f"heading not found: {heading_substring!r}")

    # find the first table row (a line starting with '|') after the heading
    rows = []
    in_table = False
    for line in lines[start + 1:]:
        stripped = line.strip()
        is_row = stripped.startswith("|")
        if is_row:
            in_table = True
            rows.append(stripped)
        elif in_table:
            break  # table ended
    if not rows:
        raise ValueError(f"no table found after heading: {heading_substring!r}")

    def split_row(row: str):
        # drop the leading/trailing empty cells produced by the outer pipes
        parts = row.split("|")[1:-1]
        return [_clean(p) for p in parts]

    header = split_row(rows[0])
    # rows[1] is the |---|---| separator; data starts at rows[2]
    data = []
    for row in rows[2:]:
        cells = split_row(row)
        if len(cells) != len(header):
            continue
        data.append(dict(zip(header, cells)))
    return header, data


def parse_json_blocks(text: str):
    """Return every ```json ... ``` fenced block in `text`, parsed, in order."""
    blocks = re.findall(r"```json\s*(.*?)```", text, flags=re.DOTALL)
    out = []
    for b in blocks:
        out.append(json.loads(b))
    return out


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    return re.sub(r"(^_+|_+$)", "", re.sub(r"[^a-z0-9]+", "_", text.lower()))


def source_manifest():
    files = []
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        files.append({
            "path": str(path.relative_to(REPO)),
            "sha256": _sha256_text(text),
        })
    digest = _sha256_text(json.dumps(files, ensure_ascii=False, sort_keys=True))
    return {"files": files, "digest": digest}


# ---------------------------------------------------------------------------
# Parsers (one per table) — return lists of tuples in canon order
# ---------------------------------------------------------------------------
def parse_pillars():
    """CANON-010: join the descriptive pillar table (code_short, name_en, name_ar,
    scope) with the Pillar Enum table (full pillar_code) by canon order."""
    text = (CANON / "CANON-010_Pillars.md").read_text(encoding="utf-8")
    _, main = parse_table_after(text, "Canonical Pillar Model")   # Code | Pillar | Arabic | Canonical Scope
    _, enum = parse_table_after(text, "Pillar Enum")              # Enum | Canonical Label

    if len(main) != len(enum):
        raise ValueError(f"pillar tables disagree: {len(main)} vs {len(enum)} rows")

    pillars = []
    for m, e in zip(main, enum):
        code_short = m["Code"]                # P1
        pillar_code = e["Enum"]               # P1_SELF
        name_en = m["Pillar"]                 # Self
        name_ar = m["Arabic"]                 # النفس
        scope = m["Canonical Scope"]
        pillars.append((pillar_code, code_short, name_en, name_ar, scope))
    return pillars


def parse_lenses():
    """CANON-012: the 5 lenses."""
    text = (CANON / "CANON-012_Content_Lenses.md").read_text(encoding="utf-8")
    _, rows = parse_table_after(text, "The 5 Lenses")
    lenses = []
    for r in rows:
        lenses.append((
            r["Lens"],              # L1
            r["Arabic"],            # name_ar
            r["English"],           # name_en
            r["Viewer State"],
            r["Primary Action"],
            r["Default Hook Type"],
        ))
    return lenses


def parse_hook_types():
    """CANON-013: the 5 hook types."""
    text = (CANON / "CANON-013_Hook_Types.md").read_text(encoding="utf-8")
    _, rows = parse_table_after(text, "The 5 Hook Types")
    return [(r["Hook Type"], r["Function"]) for r in rows]


def parse_formats(lens_name_to_id: dict):
    """CANON-014: the 7 formats. lens_fit names are mapped to lens ids; 'Flexible'
    expands to all lenses."""
    text = (CANON / "CANON-014_Content_Formats.md").read_text(encoding="utf-8")
    _, rows = parse_table_after(text, "Canonical Formats")
    all_ids = sorted(lens_name_to_id.values())

    # CANON-012 lenses are "The Mirror"/"The Earthquake"; CANON-014 lens-fit uses the
    # short form "Mirror"/"Earthquake". Match on the normalised (no leading "The ") name.
    def _norm(name: str) -> str:
        return re.sub(r"^the\s+", "", name.strip().lower())

    norm_lookup = {_norm(name): lid for name, lid in lens_name_to_id.items()}

    formats = []
    for r in rows:
        fit_raw = [x.strip() for x in r["Lens Fit"].split(",") if x.strip()]
        fit_ids = []
        for name in fit_raw:
            if name.lower() == "flexible":
                fit_ids = list(all_ids)
                break
            key = _norm(name)
            if key not in norm_lookup:
                raise ValueError(f"format {r['Format']!r}: unknown lens fit {name!r}")
            fit_ids.append(norm_lookup[key])
        formats.append((r["Format"], r["Use Case"], fit_ids, r["Production Notes"]))
    return formats


def parse_hcs(code_short_to_pillar_code: dict):
    """The 42 records. pillar_code 'P1' is mapped to the full pillar enum
    (e.g. P1_SELF); seq_in_pillar is assigned from file order within each pillar."""
    text = RECORDS.read_text(encoding="utf-8")
    blocks = parse_json_blocks(text)
    seq = {}
    hcs = []
    for b in blocks:
        short = b["pillar_code"]                       # P1..P5
        if short not in code_short_to_pillar_code:
            raise ValueError(f"hcs {b['hcs_id']}: unknown pillar {short!r}")
        pillar_code = code_short_to_pillar_code[short]
        seq[pillar_code] = seq.get(pillar_code, 0) + 1
        hcs.append((
            b["hcs_id"],
            pillar_code,
            seq[pillar_code],
            b.get("name_en"),
            b.get("name_ar"),
            b.get("core_wound"),
            b.get("how_it_shows_up"),
            b.get("false_belief"),
            b.get("earthquake_sentence"),
            b.get("islamic_anchor"),
            b.get("recommended_lenses", []),
            b.get("recommended_formats", []),
            # records use the canon field name `value_ladder_relevance`
            b.get("value_ladder_relevance", b.get("value_ladder", [])),
        ))
    return hcs


def build_payload():
    pillars = parse_pillars()
    lenses = parse_lenses()
    hook_types = parse_hook_types()
    code_short_to_pillar_code = {short: code for (code, short, *_r) in pillars}
    hcs = parse_hcs(code_short_to_pillar_code)
    return {
        "pillars": pillars,
        "lenses": lenses,
        "hook_types": hook_types,
        "hcs": hcs,
        "manifest": source_manifest(),
    }


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def upsert_runtime_tables(cur, payload):
    cur.executemany(
        """INSERT INTO pillar (pillar_code, code_short, name_en, name_ar, scope)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (pillar_code) DO UPDATE SET
             code_short=EXCLUDED.code_short, name_en=EXCLUDED.name_en,
             name_ar=EXCLUDED.name_ar, scope=EXCLUDED.scope""",
        payload["pillars"],
    )
    cur.executemany(
        """INSERT INTO lens (lens_id, name_ar, name_en, viewer_state, primary_action, default_hook_type)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (lens_id) DO UPDATE SET
             name_ar=EXCLUDED.name_ar, name_en=EXCLUDED.name_en,
             viewer_state=EXCLUDED.viewer_state, primary_action=EXCLUDED.primary_action,
             default_hook_type=EXCLUDED.default_hook_type""",
        payload["lenses"],
    )
    cur.executemany(
        """INSERT INTO hook_type (name, function)
           VALUES (%s,%s)
           ON CONFLICT (name) DO UPDATE SET function=EXCLUDED.function""",
        payload["hook_types"],
    )
    cur.executemany(
        """INSERT INTO hcs (hcs_id, pillar_code, seq_in_pillar, name_en, name_ar,
                            core_wound, how_it_shows_up, false_belief, earthquake_sentence,
                            islamic_anchor, recommended_lenses, recommended_formats, value_ladder)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (hcs_id) DO UPDATE SET
             pillar_code=EXCLUDED.pillar_code, seq_in_pillar=EXCLUDED.seq_in_pillar,
             name_en=EXCLUDED.name_en, name_ar=EXCLUDED.name_ar,
             core_wound=EXCLUDED.core_wound, how_it_shows_up=EXCLUDED.how_it_shows_up,
             false_belief=EXCLUDED.false_belief, earthquake_sentence=EXCLUDED.earthquake_sentence,
             islamic_anchor=EXCLUDED.islamic_anchor, recommended_lenses=EXCLUDED.recommended_lenses,
             recommended_formats=EXCLUDED.recommended_formats, value_ladder=EXCLUDED.value_ladder""",
        [
            (hid, pc, seq, ne, na, cw, hi, fb, es, ia, Json(rl), Json(rf), Json(vl))
            for (hid, pc, seq, ne, na, cw, hi, fb, es, ia, rl, rf, vl) in payload["hcs"]
        ],
    )


def _ensure_methodology_catalog(cur, actor: str) -> str:
    cur.execute("""INSERT INTO methodology
                   (methodology_key, name, description, created_by, tenant_id, module)
                   VALUES ('tanaghom_core', 'Tanaghom Core Methodology',
                           'DB-backed versioned seed of the Tanaghom canon and HCS records.',
                           %s, 'default', 'content')
                   ON CONFLICT (methodology_key, tenant_id, module) DO UPDATE SET
                     name=EXCLUDED.name,
                     description=EXCLUDED.description,
                     updated_at=now()
                   RETURNING methodology_id::text AS methodology_id""", (actor,))
    return cur.fetchone()[0]


def _set_active_methodology_version(cur, methodology_id: str, version_id: str, actor: str):
    cur.execute("""UPDATE methodology_version
                   SET status='inactive', updated_by=%s, updated_at=now()
                   WHERE methodology_id=%s AND status='active' AND version_id<>%s""",
                (actor, methodology_id, version_id))
    cur.execute("""UPDATE methodology_version
                   SET status='active', updated_by=%s, updated_at=now(),
                       activated_by=%s, activated_at=coalesce(activated_at, now())
                   WHERE version_id=%s""", (actor, actor, version_id))


def _sync_methodology_version(cur, payload, actor: str) -> str:
    methodology_id = _ensure_methodology_catalog(cur, actor)
    digest = payload["manifest"]["digest"]
    cur.execute("""SELECT version_id::text AS version_id
                   FROM methodology_version
                   WHERE methodology_id=%s AND source_digest=%s
                   ORDER BY version_no DESC
                   LIMIT 1""", (methodology_id, digest))
    existing = cur.fetchone()
    if existing:
        version_id = existing[0]
        _set_active_methodology_version(cur, methodology_id, version_id, actor)
        return version_id
    cur.execute("SELECT coalesce(max(version_no), 0) + 1 FROM methodology_version WHERE methodology_id=%s",
                (methodology_id,))
    version_no = cur.fetchone()[0]
    cur.execute("""UPDATE methodology_version
                   SET status='inactive', updated_by=%s, updated_at=now()
                   WHERE methodology_id=%s AND status='active'""", (actor, methodology_id))
    cur.execute("""INSERT INTO methodology_version
                   (methodology_id, version_no, status, source, notes, source_digest, source_manifest,
                    created_by, updated_by, activated_by, activated_at, tenant_id, module)
                   VALUES (%s,%s,'active','seed',%s,%s,%s,%s,%s,%s,now(),'default','content')
                   RETURNING version_id::text AS version_id""",
                (methodology_id, version_no, "Imported from repo markdown seed",
                 digest, Json(payload["manifest"]), actor, actor, actor))
    version_id = cur.fetchone()[0]
    cur.executemany(
        """INSERT INTO methodology_pillar
           (version_id, pillar_code, code_short, name_en, name_ar, scope)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        [(version_id, *row) for row in payload["pillars"]],
    )
    cur.executemany(
        """INSERT INTO methodology_lens
           (version_id, lens_id, name_ar, name_en, viewer_state, primary_action, default_hook_type)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        [(version_id, *row) for row in payload["lenses"]],
    )
    cur.executemany(
        """INSERT INTO methodology_hook_type (version_id, name, function)
           VALUES (%s,%s,%s)""",
        [(version_id, *row) for row in payload["hook_types"]],
    )
    cur.executemany(
        """INSERT INTO methodology_hcs
           (version_id, hcs_id, pillar_code, seq_in_pillar, name_en, name_ar, core_wound,
            how_it_shows_up, false_belief, earthquake_sentence, islamic_anchor,
            recommended_lenses, recommended_formats, value_ladder, voice_status, anchor_status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'seed','unverified')""",
        [
            (
                version_id, hid, pc, seq, ne, na, cw, hi, fb, es, ia,
                Json(rl), Json(rf), Json(vl),
            )
            for (hid, pc, seq, ne, na, cw, hi, fb, es, ia, rl, rf, vl) in payload["hcs"]
        ],
    )
    return version_id


def _sync_platforms(cur, actor: str):
    cur.executemany(
        """INSERT INTO platform
           (platform_key, name, channel_role, description, active, config, created_by, updated_by,
            tenant_id, module)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'default','content')
           ON CONFLICT (platform_key, tenant_id, module) DO UPDATE SET
             name=EXCLUDED.name,
             channel_role=EXCLUDED.channel_role,
             description=EXCLUDED.description,
             active=EXCLUDED.active,
             config=EXCLUDED.config,
             updated_by=EXCLUDED.updated_by,
             updated_at=now()""",
        [
            (
                row["platform_key"], row["name"], row["channel_role"], row["description"],
                row["active"], Json(row["config"]), actor, actor,
            ) for row in PLATFORM_SEEDS
        ],
    )


def _activate_content_format_version(cur, content_format_id: str, version_id: str, actor: str):
    cur.execute("""UPDATE content_format_version
                   SET status='inactive', updated_by=%s, updated_at=now()
                   WHERE content_format_id=%s AND status='active' AND version_id<>%s""",
                (actor, content_format_id, version_id))
    cur.execute("""UPDATE content_format_version
                   SET status='active', updated_by=%s, updated_at=now(),
                       activated_by=%s, activated_at=coalesce(activated_at, now())
                   WHERE version_id=%s""", (actor, actor, version_id))


def materialize_methodology_version(conn, version_id: str):
    """Project a chosen methodology version back into the runtime tables used by the planner and
    writers. This keeps CR01 version activation aligned with the current execution path."""
    cur = conn.cursor()
    try:
        cur.execute("""SELECT pillar_code, code_short, name_en, name_ar, scope
                       FROM methodology_pillar
                       WHERE version_id=%s
                       ORDER BY pillar_code""", (version_id,))
        pillars = cur.fetchall()
        cur.execute("""SELECT lens_id, name_ar, name_en, viewer_state, primary_action, default_hook_type
                       FROM methodology_lens
                       WHERE version_id=%s
                       ORDER BY lens_id""", (version_id,))
        lenses = cur.fetchall()
        cur.execute("""SELECT name, function
                       FROM methodology_hook_type
                       WHERE version_id=%s
                       ORDER BY name""", (version_id,))
        hook_types = cur.fetchall()
        cur.execute("""SELECT hcs_id, pillar_code, seq_in_pillar, name_en, name_ar, core_wound,
                              how_it_shows_up, false_belief, earthquake_sentence, islamic_anchor,
                              recommended_lenses, recommended_formats, value_ladder
                       FROM methodology_hcs
                       WHERE version_id=%s
                       ORDER BY pillar_code, seq_in_pillar, hcs_id""", (version_id,))
        hcs_rows = cur.fetchall()
        upsert_runtime_tables(cur, {
            "pillars": pillars,
            "lenses": lenses,
            "hook_types": hook_types,
            "hcs": hcs_rows,
        })
    finally:
        cur.close()


def _content_type_seed_rows():
    rows = []
    for item in CONTENT_TYPE_BOOTSTRAP:
        production_rules = dict(item["production_rules"])
        production_rules.update(CONTENT_FRAMEWORK_RULES.get(item["format_key"], {}))
        rows.append({
            "format_key": item["format_key"],
            "name": item["name"],
            "description": item["description"],
            "use_case": item["use_case"],
            "lens_fit": list(item["lens_fit"]),
            "production_notes": item["production_notes"],
            "production_rules": production_rules,
            "platform_targets": list(item["platform_targets"]),
            "source_digest": _sha256_text(json.dumps({
                "format_key": item["format_key"],
                "name": item["name"],
                "description": item["description"],
                "use_case": item["use_case"],
                "lens_fit": item["lens_fit"],
                "production_notes": item["production_notes"],
                "production_rules": production_rules,
                "platform_targets": item["platform_targets"],
            }, ensure_ascii=False, sort_keys=True)),
        })
    return rows


def _runtime_format_upsert(cur, row):
    cur.execute(
        """INSERT INTO format
           (name, format_key, description, use_case, lens_fit, production_notes, production_rules, platform_targets)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (name) DO UPDATE SET
             format_key=EXCLUDED.format_key,
             description=EXCLUDED.description,
             use_case=EXCLUDED.use_case,
             lens_fit=EXCLUDED.lens_fit,
             production_notes=EXCLUDED.production_notes,
             production_rules=EXCLUDED.production_rules,
             platform_targets=EXCLUDED.platform_targets""",
        (
            row["name"], row["format_key"], row.get("description"), row.get("use_case"),
            Json(row.get("lens_fit") or []), row.get("production_notes"),
            Json(row.get("production_rules") or {}), Json(row.get("platform_targets") or []),
        ),
    )


def materialize_content_format_version(conn, version_id: str):
    """Project a chosen content-format version back into the runtime `format` table."""
    cur = conn.cursor()
    try:
        cur.execute("""SELECT f.name, f.format_key, f.description, v.use_case, v.lens_fit,
                              v.production_notes, v.production_rules, v.platform_targets
                       FROM content_format_version v
                       JOIN content_format f ON f.content_format_id=v.content_format_id
                       WHERE v.version_id=%s""", (version_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"unknown content format version {version_id}")
        _runtime_format_upsert(cur, {
            "name": row[0],
            "format_key": row[1],
            "description": row[2],
            "use_case": row[3],
            "lens_fit": row[4] or [],
            "production_notes": row[5],
            "production_rules": row[6] or {},
            "platform_targets": row[7] or [],
        })
    finally:
        cur.close()


def _bootstrap_content_formats(cur, actor: str):
    for row in _content_type_seed_rows():
        cur.execute("""INSERT INTO content_format
                       (format_key, name, description, active, lifecycle_status, created_by, updated_by, tenant_id, module)
                       VALUES (%s,%s,%s,true,'active',%s,%s,'default','content')
                       ON CONFLICT (format_key, tenant_id, module) DO UPDATE SET
                         name=EXCLUDED.name,
                         description=EXCLUDED.description,
                         active=EXCLUDED.active,
                         lifecycle_status=EXCLUDED.lifecycle_status,
                         updated_by=EXCLUDED.updated_by,
                         updated_at=now()
                       RETURNING content_format_id::text AS content_format_id""",
                    (row["format_key"], row["name"], row["description"], actor, actor))
        content_format_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO content_format_version
                       (content_format_id, version_no, status, source, use_case, lens_fit,
                        production_notes, production_rules, platform_targets, source_digest,
                        created_by, updated_by, activated_by, activated_at, tenant_id, module)
                       VALUES (%s,1,'active','bootstrap',%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'default','content')""",
                    (
                        content_format_id, row["use_case"], Json(row["lens_fit"]),
                        row["production_notes"], Json(row["production_rules"]), Json(row["platform_targets"]),
                        row["source_digest"], actor, actor, actor,
                    ))
        _runtime_format_upsert(cur, row)


def sync_content_format_seed(conn, actor: str = "loader"):
    """#177 — bring bootstrap-lineage content-format versions up to the current seed.

    bootstrap_content_formats() is insert-once, so a corrected seed (e.g. the Hero Reel structure
    that was keyed under the wrong format) never reaches an existing registry. For each seed row:
    - if the format's ACTIVE version came from the seed lineage (source bootstrap/bootstrap-sync)
      and its source_digest differs, insert a NEW active version (version_no = max+1,
      source='bootstrap-sync'), deactivate the old one, and re-materialize the runtime row —
      the same versioned semantics the admin activate flow uses;
    - if the active version is operator-authored (any other source), it is NEVER overridden —
      the row is reported as skipped instead.
    """
    cur = conn.cursor()
    applied, skipped, unchanged = [], [], []
    try:
        for row in _content_type_seed_rows():
            cur.execute("""SELECT cf.content_format_id::text, v.version_id::text, v.source, v.source_digest
                           FROM content_format cf
                           JOIN content_format_version v ON v.content_format_id=cf.content_format_id
                                AND v.status='active'
                           WHERE cf.format_key=%s AND cf.tenant_id='default' AND cf.module='content'""",
                        (row["format_key"],))
            hit = cur.fetchone()
            if not hit:
                continue  # format absent — bootstrap owns first seeding
            content_format_id, active_version_id, source, digest = hit
            if digest == row["source_digest"]:
                unchanged.append(row["format_key"])
                continue
            if source not in ("bootstrap", "bootstrap-sync"):
                skipped.append(row["format_key"])
                continue
            cur.execute("""SELECT coalesce(max(version_no),0)+1 FROM content_format_version
                           WHERE content_format_id=%s""", (content_format_id,))
            next_no = cur.fetchone()[0]
            cur.execute("""UPDATE content_format_version
                           SET status='inactive', updated_by=%s, updated_at=now()
                           WHERE version_id=%s""", (actor, active_version_id))
            cur.execute("""INSERT INTO content_format_version
                           (content_format_id, version_no, status, source, use_case, lens_fit,
                            production_notes, production_rules, platform_targets, source_digest,
                            created_by, updated_by, activated_by, activated_at, tenant_id, module)
                           VALUES (%s,%s,'active','bootstrap-sync',%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'default','content')""",
                        (
                            content_format_id, next_no, row["use_case"], Json(row["lens_fit"]),
                            row["production_notes"], Json(row["production_rules"]), Json(row["platform_targets"]),
                            row["source_digest"], actor, actor, actor,
                        ))
            _runtime_format_upsert(cur, row)
            applied.append(row["format_key"])
        conn.commit()
        return {"applied": applied, "skipped_operator_owned": skipped, "unchanged": unchanged}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def bootstrap_content_formats(conn, actor: str = "loader", reset: bool = False):
    cur = conn.cursor()
    try:
        _sync_platforms(cur, actor)
        if reset:
            cur.execute("DELETE FROM format")
            cur.execute("DELETE FROM content_format WHERE tenant_id='default' AND module='content'")
        else:
            cur.execute("""SELECT count(*) FROM content_format
                           WHERE tenant_id='default' AND module='content'""")
            if cur.fetchone()[0]:
                conn.commit()
                return {"bootstrapped": False, "count": 0}
        _bootstrap_content_formats(cur, actor)
        conn.commit()
        return {"bootstrapped": True, "count": len(CONTENT_TYPE_BOOTSTRAP)}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def sync_versioned_seed(conn, payload=None, actor: str = "loader"):
    payload = payload or build_payload()
    cur = conn.cursor()
    try:
        version_id = _sync_methodology_version(cur, payload, actor)
        _sync_platforms(cur, actor)
        conn.commit()
        return {"methodology_version_id": version_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def main():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "tanaghom"),
        user=os.environ.get("DB_USER", "tanaghom"),
        password=os.environ["DB_PASSWORD"],
    )
    conn.autocommit = False
    cur = conn.cursor()
    payload = build_payload()
    upsert_runtime_tables(cur, payload)
    conn.commit()
    seeded = sync_versioned_seed(conn, payload=payload, actor="loader")
    bootstrap = bootstrap_content_formats(conn, actor="loader")
    format_sync = sync_content_format_seed(conn, actor="loader")

    expected = {"pillar": 5, "hcs": 42, "lens": 5, "hook_type": 5, "format": 4}
    print("Loaded (parsed -> db):")
    ok = True
    for table, want in expected.items():
        cur.execute(f"SELECT count(*) FROM {table}")
        got = cur.fetchone()[0]
        mark = "OK" if got == want else "MISMATCH"
        if got != want:
            ok = False
        print(f"  {table:<10} expected {want:>2}  got {got:>2}  [{mark}]")
    cur.execute("SELECT count(*) FROM methodology_version")
    methodology_versions = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM content_format")
    content_formats = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM platform")
    platforms = cur.fetchone()[0]
    print(f"\nVersioned seed:")
    print(f"  methodology_version active/imported: {seeded['methodology_version_id']}")
    print(f"  methodology_version rows: {methodology_versions}")
    print(f"  content_format rows:      {content_formats}")
    print(f"  platform rows:            {platforms}")
    print(f"  content_type bootstrap:   {'applied' if bootstrap['bootstrapped'] else 'existing registry kept'}")
    print(f"  content_format seed sync: applied={format_sync['applied']} "
          f"skipped_operator_owned={format_sync['skipped_operator_owned']} unchanged={format_sync['unchanged']}")

    cur.close()
    conn.close()
    if not ok:
        print("\nCOUNT VERIFICATION FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nAll counts verified.")


if __name__ == "__main__":
    main()
