#!/usr/bin/env python3
"""
Tanaghom Writers (M3) — Topic/Brief agent (Agent 1) + Script agent (Agent 2).

Implements Phase1_Build_Spec §4, driven by system_config.yaml:

  Agent 1 (Topic/Brief)
    - In : a RESERVED slot (pillar, HCS record, lens, format).
    - Out: {topic_angle, hook_text, hook_type, rationale}  OR
           NEEDS_STRATEGIC_CLARIFICATION.
    - Hard self-check: the spoken hook obeys CANON-013 (3–7 words, no greeting,
      no Moataz name, addresses one person, true-not-clever). Regenerates on
      violation.
    - Dedup: embeds the topic (local model) and compares it against the topic
      ledger within the configured scope; regenerates on a near-duplicate
      (critical for the same HCS recurring within / across rounds).

  Agent 2 (Script)
    - In : the approved topic + HCS record + lens + format.
    - Out: {script_ar, structure, final_line, delivery_notes, flags[]}.
    - Hard self-check: CANON-013 Hard Fail conditions + the CANON-012 Mandatory
      Delivery Check. Sets needs_scholar_review when an islamic_anchor is used and
      needs_native_review for Palestinian dialect.

  On success the slot moves RESERVED -> DRAFT_ASSIGNED (script_ref -> script row).

Voice context is injected straight from the canon (CANON-012/013) and the HCS
record, so the source of truth stays the markdown, not this code.

Modes:
  write   process RESERVED slots (use --slot-ids / --distinct-pillars / --limit)
"""

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import yaml
from psycopg2.extras import Json

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))  # for directives (M9·B1)
from providers import ChatClient, EmbeddingClient, ProviderError  # noqa: E402
from runtime_secret import status as runtime_secret_status  # noqa: E402
import directives  # noqa: E402  — the inter-stage directive contract (one canonical module)

REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "methodology" / "canon"
DEFAULT_CONFIG = REPO / "system_config.yaml"

# ---------------------------------------------------------------------------
# Voice / hook validation (CANON-013 hard checks)
# ---------------------------------------------------------------------------
GREETINGS = ["السلام", "سلام", "مرحبا", "مرحبًا", "أهلا", "أهلًا", "اهلا",
             "صباح الخير", "مساء الخير", "هلا", "هاي", "hello", "hi "]
AUDIENCE_MARKERS = ["يا جماعة", "يا شباب", "يا متابعين", "متابعيني", "حضراتكم",
                    "يا أصحاب", "يا اصحاب", "يا ناس", "أصدقائي", "اصدقائي",
                    "يا رفاق", "يا متابعيني"]
NAME_MARKERS = ["معتز", "مشعل", "moataz", "mishal", "mashal"]


def word_count(s: str) -> int:
    return len([w for w in re.split(r"\s+", s.strip()) if w])


def dialect_violations(text: str, guard) -> list[str]:
    """Flag Gulf/Egyptian markers (the dialect guard). Markers come from config so the
    list is tunable; each is matched on a word boundary to avoid false positives
    (e.g. 'مو' must not fire inside 'موجود'). Returns ['gulf:مو', 'egyptian:عايز', ...]."""
    if not guard or not guard.get("enabled", True):
        return []
    found = []
    for dialect, markers in (guard.get("markers") or {}).items():
        for m in markers:
            m = m.strip()
            if m and re.search(r"\b" + re.escape(m) + r"\b", text):
                found.append(f"{dialect}:{m}")
    return found


def dialect_soft_warnings(text: str, guard) -> list[str]:
    """Like dialect_violations but for `soft_markers` — words that are *suspect* but also
    occur legitimately (e.g. حاجة 'a need/thing'). These WARN and get flagged but never
    force a regeneration; a human reviewer decides. Returns ['egyptian:حاجة', ...]."""
    if not guard or not guard.get("enabled", True):
        return []
    found = []
    for dialect, markers in (guard.get("soft_markers") or {}).items():
        for m in markers:
            m = m.strip()
            if m and re.search(r"\b" + re.escape(m) + r"\b", text):
                found.append(f"{dialect}:{m}")
    return found


def validate_hook(hook: str, cfg_writers) -> list[str]:
    """Return CANON-013 + dialect-guard violations of the spoken hook ([] = passes)."""
    v = []
    h = (hook or "").strip()
    low = h.lower()
    wc = word_count(h)
    lo, hi = cfg_writers.get("hook_word_min", 3), cfg_writers.get("hook_word_max", 7)
    if not (lo <= wc <= hi):
        v.append(f"word_count={wc} (must be {lo}-{hi})")
    if any(low.startswith(g.lower()) for g in GREETINGS):
        v.append("starts_with_greeting")
    if any(n in low for n in NAME_MARKERS):
        v.append("contains_moataz_name")
    if any(m in h for m in AUDIENCE_MARKERS):
        v.append("addresses_audience_not_one_person")
    if _hook_has_dangling_ending(h):
        v.append("ends_with_dangling_word")
    v += dialect_violations(h, cfg_writers.get("dialect_guard"))
    return v


def arabic_content_violations(fields: dict[str, str]) -> list[str]:
    """Reject obvious model language leakage from fields that must be Arabic.

    Latin words and CJK/Kana/Hangul characters are never valid in the source-language
    Topic fields. Keep punctuation and digits unrestricted so normal Arabic copy is not
    rejected, while malformed multilingual fragments re-enter the existing retry loop.
    """
    violations = []
    foreign_script = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
    latin_word = re.compile(r"[A-Za-z]{2,}")
    for name, value in fields.items():
        text = str(value or "")
        if foreign_script.search(text):
            violations.append(f"{name}:foreign_script")
        if latin_word.search(text):
            violations.append(f"{name}:latin_word")
    return violations


def script_hard_fails(script_ar: str, cfg_writers=None) -> list[str]:
    """CANON-013 Hard Fails + dialect guard on the script (greeting/name at the open;
    Gulf/Egyptian markers anywhere force a regenerate)."""
    v = []
    s = (script_ar or "").strip()
    first_line = s.splitlines()[0] if s else ""
    low = first_line.lower()
    if any(low.startswith(g.lower()) for g in GREETINGS):
        v.append("opens_with_greeting")
    if any(n in s.lower() for n in NAME_MARKERS):
        v.append("uses_moataz_name")
    v += dialect_violations(s, (cfg_writers or {}).get("dialect_guard"))
    return v


# ---------------------------------------------------------------------------
# Canon injection
# ---------------------------------------------------------------------------
def canon_text(name: str) -> str:
    return (CANON / name).read_text(encoding="utf-8")


def lens_questions(lens_id: str) -> str:
    """Pull the '### L{n} — ...' question block for a lens from CANON-012."""
    text = canon_text("CANON-012_Content_Lenses.md")
    # sections look like: "### L1 — The Mirror\n- q\n- q\n\n### L2 ..."
    blocks = re.split(r"\n### ", text)
    for b in blocks:
        if b.startswith(f"{lens_id} ") or b.startswith(f"{lens_id} —") or b.startswith(f"{lens_id}—"):
            return "### " + b.split("\n\n")[0].strip()
    return ""


def delivery_check_text() -> str:
    text = canon_text("CANON-012_Content_Lenses.md")
    m = re.search(r"## Mandatory Delivery Check\s*(.+?)(?:\n##|\Z)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


HOOK_RULES = None  # full CANON-013, loaded lazily


def hook_rules_text() -> str:
    global HOOK_RULES
    if HOOK_RULES is None:
        HOOK_RULES = canon_text("CANON-013_Hook_Types.md").strip()
    return HOOK_RULES


def format_guidance_block(format_spec) -> str:
    if not format_spec:
        return ""
    rules = format_spec.get("production_rules") if isinstance(format_spec.get("production_rules"), dict) else {}
    planning = rules.get("planning") if isinstance(rules.get("planning"), dict) else {}
    platform_profiles = rules.get("platform_profiles") if isinstance(rules.get("platform_profiles"), dict) else {}
    lines = [
        f"FORMAT DEFINITION: {format_spec.get('name')}",
        f"  format_key         : {format_spec.get('format_key') or ''}",
        f"  description        : {format_spec.get('description') or ''}",
        f"  use_case           : {format_spec.get('use_case') or ''}",
        f"  production_notes   : {format_spec.get('production_notes') or ''}",
        f"  platform_targets   : {', '.join(format_spec.get('platform_targets') or []) or '(none)'}",
        f"  planning_weekly    : {planning.get('weekly_count', '(unspecified)')}",
    ]
    if rules.get("framework_name"):
        lines.append(f"  framework          : {rules.get('framework_name')} ({rules.get('framework_id') or 'no-id'})")
    if rules.get("script_guidance"):
        lines.append(f"  script_guidance    : {rules.get('script_guidance')}")
    if rules.get("production_guidance"):
        lines.append(f"  production_guidance: {rules.get('production_guidance')}")
    if rules.get("distribution_guidance"):
        lines.append(f"  distribution_notes : {rules.get('distribution_guidance')}")
    if platform_profiles:
        lines.append(f"  platform_profiles  : {json.dumps(platform_profiles, ensure_ascii=False)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# #149 (#146 S2) — script structure keys are format-specific and REGISTRY-DRIVEN.
# The selected content format's canonical registry entry (production_rules.structure) defines
# the beats (e.g. carousel = 7 named slides); the writer emits and validates exactly those keys.
# The canonical 4-beat is used ONLY as a fallback when the format has no registry structure —
# no per-format hardcoding, no invented keys.
# ---------------------------------------------------------------------------
CANONICAL_SCRIPT_STRUCTURE = ["hook", "body", "turn", "close"]   # fallback ONLY (no registry structure)
_STRUCTURE_KEYS_MARKER = "STRUCTURE KEYS (required, in order):"    # machine-parseable line for the stubs


def structure_spec(format_spec):
    """The (step, label) pairs for a format's script structure, from its registry entry — or []."""
    rules = (format_spec or {}).get("production_rules")
    rules = rules if isinstance(rules, dict) else {}
    structure = rules.get("structure")
    if not isinstance(structure, list):
        return []
    out = []
    for s in structure:
        if isinstance(s, dict):
            step = str(s.get("step") or "").strip()
            if step:
                out.append((step, str(s.get("label") or step).strip()))
    return out


def structure_steps(format_spec):
    """The ordered structure KEYS for a format — registry steps where present, else the 4-beat canon."""
    steps = [k for k, _ in structure_spec(format_spec)]
    return steps if steps else list(CANONICAL_SCRIPT_STRUCTURE)


def _structure_keys_from_prompt(text):
    """Parse the expected structure keys the prompt advertises — used by the deterministic stub
    writers so their offline output is format-aware without any per-format hardcoding."""
    m = re.search(re.escape(_STRUCTURE_KEYS_MARKER) + r"\s*(.+)", text or "")
    if not m:
        return list(CANONICAL_SCRIPT_STRUCTURE)
    keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
    return keys or list(CANONICAL_SCRIPT_STRUCTURE)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SYSTEM_VOICE = (
    "You are the content engine for Tanaghom — the brand of Moataz Mashal. "
    "You write in spoken Palestinian Arabic (ar-PS), in Moataz's voice: intimate, "
    "second-person, speaking to ONE person (never an audience), emotionally honest, "
    "concrete, never preachy or motivational-generic. Use natural Palestinian register "
    "(هاد، هاي، اللي، عشان، إنه، مش، بدك، بتحس، مرّات) and avoid stiff MSA. "
    "The proven voice is the belief-collision / painful-truth register. "
    "Return ONLY a single valid JSON object — no markdown fences, no commentary."
)

SYSTEM_REWORK_VERIFIER = (
    "You are a strict review-compliance verifier for a content workflow. "
    "Your job is not to improve the content. Your job is to judge whether the revised content "
    "actually applied the reviewer's requested changes compared with the previous version. "
    "Be skeptical. If a requested opening, audience shift, ending change, or scripture removal "
    "did not materially happen in the revised content itself, return FAIL. "
    "Return ONLY one valid JSON object."
)


# --- Few-shot dialect exemplars (real high-engagement captions, pillar-matched) ---
_EXEMPLAR_BANK = None


def load_exemplar_bank(cfg):
    global _EXEMPLAR_BANK
    if _EXEMPLAR_BANK is None:
        rel = cfg.get("writers", {}).get("exemplars_file",
                                         "methodology/voice/dialect_exemplars.json")
        try:
            _EXEMPLAR_BANK = json.loads((REPO / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _EXEMPLAR_BANK = {}
    return _EXEMPLAR_BANK


def exemplars_block(cfg, pillar_code):
    """Render 3–5 pillar-matched exemplars as a few-shot voice anchor (empty if none)."""
    bank = load_exemplar_bank(cfg)
    n = cfg.get("writers", {}).get("exemplars_per_slot", 4)
    items = (bank.get(pillar_code) or bank.get("_general") or [])[:n]
    if not items:
        return ""
    lines = "\n".join(f'- "{it["text"]}"' for it in items)
    return ("\n=== Real high-performing captions in THIS voice (imitate the Palestinian "
            "register & rhythm; do NOT copy them or reuse their CTAs) ===\n" + lines + "\n")


REWORK_PREAMBLE = (
    "\n\n=== REWORK DIRECTIVE — the reviewer's comment is your PRIMARY instruction ===\n"
    "REVIEWER COMMENT: «{fb}»\n"
    "Use the CURRENT HEAD content below as the base document. Preserve every unaffected idea, "
    "beat, and phrasing choice unless the comment explicitly requires changing it.\n"
    "For TOPICS specifically: if the comment mentions the title, headline, or hook, that means "
    "`hook_text` (the visible spoken title on the card). `topic_angle` is the supporting topic body.\n"
    "First extract the reviewer's requested changes as BINDING acceptance points. Do not just "
    "mention them in the summary — the revised content itself must satisfy them.\n"
    "Revise to DIRECTLY address this comment. First decide the scope:\n"
    "- MINOR / SURGICAL (a word, a name, a gender, a phrase): change ONLY what was asked and "
    "PRESERVE everything else — keep the same angle & hook unless the comment is about them.\n"
    "- SUBSTANTIVE (the angle/direction is what's wrong): rethink it to satisfy the comment.\n"
    "If the comment points to a specific word or phrase, replace only that span instead of "
    "rewriting the whole piece.\n"
    "If the comment asks for a different opening, audience, tone, scene, or ending, you MUST "
    "materially change that part. Do not keep the same sentence skeleton and claim it changed.\n"
    "If the comment asks to change only the last word in a topic title/hook, keep the rest of "
    "the hook intact and replace that last word with a NATURAL, meaningful word. Do NOT satisfy "
    "the request by appending or swapping in a dangling filler like `يا`, `و`, `بس`, or another "
    "connector that leaves the hook incomplete.\n"
    "Do NOT blindly re-roll: the new version must visibly reflect the comment. Then ALSO return "
    "change_summary_ar + change_summary_en — one short sentence each on HOW this version addresses "
    "the comment.\n")

# extra JSON fields required only on rework (the visible "how this addresses your comment")
_CS_FIELDS = (',\n  "change_summary_ar": "كيف عالجت هذه النسخة ملاحظة المراجِع (جملة قصيرة)",'
              '\n  "change_summary_en": "how this version addresses your comment (one short sentence)",'
              '\n  "comment_scope": "minor" or "substantive",'
              '\n  "requested_changes_ar": ["list the reviewer requests you actually applied"]')


def _topic_head_block(current_head):
    if not current_head:
        return ""
    return (
        "\nCURRENT HEAD TOPIC — revise THIS version, do not replace it unless the comment requires it\n"
        f"  topic_angle : {current_head.get('topic_angle') or ''}\n"
        f"  hook_text   : {current_head.get('hook_text') or ''}\n"
        f"  hook_type   : {current_head.get('hook_type') or ''}\n"
        f"  rationale_ar: {current_head.get('rationale_ar') or ''}\n"
        f"  rationale_en: {current_head.get('rationale_en') or ''}\n"
    )


def _script_head_block(current_script):
    if not current_script:
        return ""
    return (
        "\nCURRENT HEAD SCRIPT — revise THIS version, do not replace it unless the comment requires it\n"
        f"  final_line     : {current_script.get('final_line') or ''}\n"
        f"  delivery_notes : {current_script.get('delivery_notes') or ''}\n"
        f"  script_ar:\n{current_script.get('script_ar') or ''}\n"
    )


def _normalize_rework_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _prefix_words(text: str, words: int) -> str:
    parts = [w for w in re.split(r"\s+", _normalize_rework_text(text)) if w]
    return " ".join(parts[:words])


def _last_word(text: str) -> str:
    parts = [w for w in re.split(r"\s+", _normalize_rework_text(text)) if w]
    return parts[-1] if parts else ""


def _all_but_last_words(text: str) -> str:
    parts = [w for w in re.split(r"\s+", _normalize_rework_text(text)) if w]
    return " ".join(parts[:-1]) if len(parts) > 1 else ""


_DANGLING_HOOK_LAST_WORDS = {
    "يا", "و", "او", "أو", "بل", "بس", "ثم", "في", "من", "عن", "على", "مع", "ل", "ال",
}


def _hook_has_dangling_ending(text: str) -> bool:
    last = _last_word(text)
    return bool(last) and last in _DANGLING_HOOK_LAST_WORDS


def _feedback_requests(feedback: str | None) -> dict[str, bool]:
    fb = _normalize_rework_text(feedback)
    change_hook = bool(re.search(r"(العنوان|عنوان|title|headline|hook|الهوك)", fb, re.IGNORECASE))
    change_last_word = bool(re.search(r"(آخر كلمة|اخر كلمة|last word|final word)", fb, re.IGNORECASE))
    return {
        "change_opening": bool(re.search(r"(ابد[اأ]|افتتح|افتح|opening|المشهد|بداية)", fb)),
        "change_ending": bool(re.search(r"(اختم|النهاية|الخاتمة|final line|closing)", fb)),
        "no_anchor": bool(re.search(r"(لا تستخدم آية|بدون آية|بدون قرآن|لا تستخدم قرآن|بدون حديث|لا تستخدم حديث)", fb)),
        "family_redirect": bool(re.search(r"(الأهل|الوالدين|الأب|الأم)", fb)),
        "home_scene": bool(re.search(r"(داخل البيت|في البيت|بالبيت|home|inside the house)", fb)),
        "softer_tone": bool(re.search(r"(خفف النبرة|أهدى|ألطف|gentler|softer|softer tone|less harsh|less intense|less preach|preach|وعظ)", fb)),
        "question_ending": bool(re.search(r"(سؤال|question|reflective question|ينتهي بسؤال|ending question)", fb, re.IGNORECASE)),
        "practical_step_short": bool(re.search(r"(خطوة عملية|عملية واحدة|short practical step|one short practical step)", fb)),
        "change_hook": change_hook,
        "change_hook_last_word": change_hook and change_last_word,
    }


def _contains_family_terms(text: str) -> bool:
    return bool(re.search(r"(الأهل|أهلك|أهلَك|الوالدين|الوالد|الوالدة|الأب|الأم)", text or ""))


def _contains_home_scene_terms(text: str) -> bool:
    return bool(re.search(r"(البيت|بالبيت|داخل البيت|غرفة|غرفتك|مطبخ|المطبخ|صالون|باب البيت|السفرة|الكنباية|على الطاولة)", text or ""))


def _looks_like_short_practical_step(text: str) -> bool:
    norm = _normalize_rework_text(text)
    if not norm:
        return False
    words = [w for w in re.split(r"\s+", norm) if w]
    if len(words) > 12:
        return False
    if bool(re.match(r"^(جرّب|جرب|اسأل|اسألي|سأل|سألي|احكي|احكي مع|دوّن|دون|خذ|خدي|اعمل|اعملي|ابدأ|ابدئي|وقف|وقفي)\b", norm)):
        return True
    if len(words) <= 8 and not norm.endswith("?") and re.match(r"^[\u0621-\u064A]+ي\b", words[0]):
        return True
    return False


def _looks_like_question(text: str) -> bool:
    norm = _normalize_rework_text(text)
    if not norm:
        return False
    if norm.endswith(("؟", "?")):
        return True
    return bool(re.match(r"^(هل|شو|ليش|كيف|وين|متى|مين)\b", norm))


def _has_gentler_delivery_notes(text: str) -> bool:
    norm = _normalize_rework_text(text)
    return bool(re.search(r"(هاد[يئة]|أهدى|ألطف|أحن|حنون|دافئ|متفهم|رفيق|هادئ|gentle|softer|warmer|calm)", norm, re.IGNORECASE))


def rework_acceptance_points(feedback: str | None, artifact: str) -> list[str]:
    req = _feedback_requests(feedback)
    points = []
    if artifact == "topic" and req["change_hook_last_word"]:
        points.append("Change the last word in hook_text while preserving the same meaning and overall hook shape.")
    elif artifact == "topic" and req["change_hook"]:
        points.append("Change hook_text materially; the visible title/headline cannot stay the same.")
    if req["change_opening"]:
        points.append("Change the opening materially; do not reuse the same opening sentence skeleton.")
    if artifact == "script" and req["softer_tone"]:
        points.append("Make the delivery gentler and explicitly reflect that in delivery_notes; do not keep the same harsh/intense delivery framing.")
    if artifact == "script" and req["home_scene"]:
        points.append("The beat immediately after hook_text must place the listener in one concrete home scene inside the house.")
    if req["no_anchor"]:
        points.append("Do not use any Quran/Hadith verse or scripture reference.")
    if req["family_redirect"]:
        points.append("Make the wording explicitly about family / parents, not a generic audience.")
    if artifact == "script" and req["change_ending"]:
        points.append("Change final_line materially; it cannot stay the same as the current head.")
    if artifact == "script" and req["question_ending"]:
        points.append("Make final_line a direct reflective question.")
    if artifact == "script" and req["practical_step_short"]:
        points.append("Make final_line one short practical step, ideally a single imperative sentence of at most 12 words.")
    return points


def verify_rework_compliance(chat, artifact: str, feedback: str | None,
                             current_head: dict | None, candidate: dict) -> list[str]:
    if not feedback or not current_head or chat is None:
        return []
    if artifact == "topic":
        before = (
            f"topic_angle: {current_head.get('topic_angle') or ''}\n"
            f"hook_text: {current_head.get('hook_text') or ''}\n"
            f"rationale_ar: {current_head.get('rationale_ar') or ''}\n"
        )
        after = (
            f"topic_angle: {candidate.get('topic_angle') or ''}\n"
            f"hook_text: {candidate.get('hook_text') or ''}\n"
            f"change_summary_ar: {candidate.get('change_summary_ar') or ''}\n"
        )
    else:
        before = (
            f"final_line: {current_head.get('final_line') or ''}\n"
            f"script_ar:\n{current_head.get('script_ar') or ''}\n"
        )
        after = (
            f"final_line: {candidate.get('final_line') or ''}\n"
            f"used_islamic_anchor: {candidate.get('used_islamic_anchor')}\n"
            f"change_summary_ar: {candidate.get('change_summary_ar') or ''}\n"
            f"script_ar:\n{candidate.get('script_ar') or ''}\n"
        )
    acceptance = rework_acceptance_points(feedback, artifact)
    prompt = (
        f"ARTIFACT: {artifact}\n"
        f"REVIEWER COMMENT: {feedback}\n\n"
        + (("ACCEPTANCE CHECKLIST:\n- " + "\n- ".join(acceptance) + "\n\n") if acceptance else "")
        + f"PREVIOUS VERSION:\n{before}\n"
        + f"REVISED VERSION:\n{after}\n\n"
        + "Judge whether the revised version materially applied the reviewer's requested changes. "
        + "Do not trust the change summary by itself. Focus on the content itself.\n\n"
        + 'Return JSON exactly: {"verdict":"PASS" or "FAIL","missing":["short missing-change bullets"],"reason":"one short sentence"}'
    )
    print(f"  [rework-verify] {artifact}: checking whether the revision materially applied the review comment")
    try:
        data = parse_json(chat.complete(SYSTEM_REWORK_VERIFIER, prompt))
    except (ProviderError, ValueError) as e:
        print(f"  [rework-verify] verifier unavailable ({str(e)[:90]}) — falling back to heuristic only")
        return []
    verdict = str(data.get("verdict", "")).strip().upper()
    if verdict == "PASS":
        print(f"  [rework-verify] {artifact}: PASS")
        return []
    missing = [str(x).strip() for x in (data.get("missing") or []) if str(x).strip()]
    print(f"  [rework-verify] {artifact}: FAIL {missing or data.get('reason') or ''}")
    if missing:
        return [f"verifier: {m}" for m in missing]
    reason = str(data.get("reason", "")).strip()
    return [f"verifier: {reason or 'review comment not materially applied'}"]


def rework_acceptance_failures(feedback: str | None, artifact: str,
                               current_head: dict | None, candidate: dict) -> list[str]:
    if not feedback or not current_head:
        return []
    req = _feedback_requests(feedback)
    failures = []
    if artifact == "topic":
        old_body = current_head.get("topic_angle", "")
        new_body = candidate.get("topic_angle", "")
        old_hook = current_head.get("hook_text", "")
        new_hook = candidate.get("hook_text", "")
        if req["change_hook"] and _normalize_rework_text(old_hook) == _normalize_rework_text(new_hook):
            failures.append("title/hook request not applied — hook_text did not change")
        if req["change_hook_last_word"] and _last_word(old_hook) == _last_word(new_hook):
            failures.append("title/hook request not applied — the last word in hook_text did not change")
        if req["change_hook_last_word"] and _all_but_last_words(old_hook) != _all_but_last_words(new_hook):
            failures.append("title/hook request not applied — more than the last word in hook_text changed")
        if req["change_hook_last_word"] and _hook_has_dangling_ending(new_hook):
            failures.append("title/hook request not applied — the new last word leaves the hook incomplete")
        if req["change_opening"] and _prefix_words(old_body, 6) == _prefix_words(new_body, 6):
            failures.append("opening request not applied — the topic opening stayed too close to the current head")
        if req["family_redirect"] and not _contains_family_terms(f"{new_hook} {new_body}"):
            failures.append("audience redirect not applied — expected family-oriented wording")
    elif artifact == "script":
        old_script = current_head.get("script_ar", "")
        new_script = candidate.get("script_ar", "")
        old_final = current_head.get("final_line", "")
        new_final = candidate.get("final_line", "")
        old_delivery = current_head.get("delivery_notes", "")
        new_delivery = candidate.get("delivery_notes", "")
        if req["change_opening"] and _prefix_words(old_script, 14) == _prefix_words(new_script, 14):
            failures.append("opening request not applied — the script opening stayed too close to the current head")
        if req["softer_tone"]:
            if _normalize_rework_text(old_delivery) == _normalize_rework_text(new_delivery):
                failures.append("tone request not applied — delivery_notes did not change")
            elif not _has_gentler_delivery_notes(new_delivery):
                failures.append("tone request not applied — delivery_notes do not signal a gentler delivery")
        if req["home_scene"] and not _contains_home_scene_terms(_prefix_words(new_script, 24)):
            failures.append("home-scene request not applied — expected a concrete inside-the-house opening beat")
        if req["change_ending"] and _normalize_rework_text(old_final) == _normalize_rework_text(new_final):
            failures.append("ending request not applied — the final line did not change")
        if req["question_ending"] and not _looks_like_question(new_final):
            failures.append("question-ending request not applied — expected a direct reflective question in final_line")
        if req["practical_step_short"] and not _looks_like_short_practical_step(new_final):
            failures.append("practical-step ending not applied — expected one short actionable final line")
        if req["no_anchor"] and (
            candidate.get("used_islamic_anchor")
            or bool(re.search(r"\[[^\]]+\:\s*\d+\]", new_script))
        ):
            failures.append("anchor removal request not applied — scripture is still present")
        if req["family_redirect"] and not _contains_family_terms(new_script):
            failures.append("audience redirect not applied — expected family-oriented wording")
    return failures


def topic_prompt(slot, hcs, lens, format_spec, exemplars="", feedback=None, current_head=None):
    anchor = hcs["islamic_anchor"] or ""
    fb = REWORK_PREAMBLE.format(fb=feedback) if feedback else ""
    cs = _CS_FIELDS if feedback else ""
    head = _topic_head_block(current_head) if feedback else ""
    acceptance = ""
    points = rework_acceptance_points(feedback, "topic")
    if points:
        acceptance = "\nREWORK ACCEPTANCE CHECKLIST\n- " + "\n- ".join(points) + "\n"
    return f"""Generate the Topic/Brief for one content slot.{fb}
{head}
{acceptance}

PILLAR: {slot['pillar_code']}
HCS {hcs['hcs_id']} — {hcs['name_en']} / {hcs['name_ar'] or ''}
  core_wound        : {hcs['core_wound']}
  how_it_shows_up   : {hcs['how_it_shows_up']}
  false_belief      : {hcs['false_belief']}
  earthquake (voice): {hcs['earthquake_sentence']}
  islamic_anchor    : {anchor or '(none)'}

LENS {lens['lens_id']} — {lens['name_en']} (viewer state: {lens['viewer_state']})
Answer the angle THROUGH this lens. Lens questions:
{lens_questions(lens['lens_id'])}

FORMAT: {slot['format']}
{format_guidance_block(format_spec)}
DEFAULT HOOK TYPE (from the lens): {slot['hook_type']}
{exemplars}
=== CANON-013 (the hook is non-negotiable) ===
{hook_rules_text()}

TASK:
1. Produce a sharp topic_angle (1–2 sentences, ar-PS) that maps THIS HCS through THIS lens.
2. Produce hook_text = the SPOKEN hook (first ~2 seconds): 3–7 words, ar-PS, obeying
   every CANON-013 rule above. True, not clever. One person. No greeting. No "معتز".
3. Pick the hook_type (one of: Painful Truth, The Collision, The Drop, The Promise, The Command).

4. Write a CONCISE reviewer-facing justification — "why this topic now" — for a busy
   content owner (NOT the script): relevance to the audience, the angle's value, how it
   fits the methodology/coverage, and that it is fresh (non-repeat). One or two sentences.
   Provide it BILINGUAL: rationale_ar (Palestinian Arabic) + rationale_en (English).
   On rework, preserve the existing rationale unless the comment requires changing it.
5. On rework, explicitly classify the comment as minor or substantive, and list the requested
   changes you actually applied. If the reviewer asked for a different opening or audience,
   the revised topic itself must show that change clearly.

If the slot genuinely cannot map to this HCS, return NEEDS_STRATEGIC_CLARIFICATION instead.

Return JSON exactly:
{{"maps_to_hcs": true,
  "topic_angle": "...", "hook_text": "...", "hook_type": "...",
  "rationale_ar": "ليش هاد الموضوع الآن (مختصر للمراجِع)",
  "rationale_en": "why this topic now (concise, for the reviewer)"{cs}}}
OR
{{"maps_to_hcs": false, "status": "NEEDS_STRATEGIC_CLARIFICATION", "reason": "..."}}"""


def script_prompt(slot, hcs, lens, topic, format_spec, exemplars="", feedback=None, current_script=None):
    anchor = hcs["islamic_anchor"] or ""
    fb = REWORK_PREAMBLE.format(fb=feedback) if feedback else ""
    cs = _CS_FIELDS if feedback else ""
    head = _script_head_block(current_script) if feedback else ""
    acceptance = ""
    req = _feedback_requests(feedback)
    points = rework_acceptance_points(feedback, "script")
    if points:
        acceptance = "\nREWORK ACCEPTANCE CHECKLIST\n- " + "\n- ".join(points) + "\n"
    rework_overrides = ""
    if req["softer_tone"]:
        rework_overrides += (
            "\nSOFTER-TONE OVERRIDE\n"
            "- `delivery_notes` MUST explicitly include one of these cues in Arabic or English: "
            "`نبرة هادئة`, `أهدى`, `ألطف`, `دافئة`, `gentle`, `softer`, `warmer`, or `calm`.\n"
            "- Do NOT keep the same intense/pain-heavy delivery framing from the current head.\n"
        )
    if req["question_ending"]:
        rework_overrides += (
            "\nQUESTION-ENDING OVERRIDE\n"
            "- `final_line` MUST be a direct reflective question.\n"
            "- It MUST end with `؟`.\n"
        )
    # #149 — structure keys from the format's registry (fallback: 4-beat canon). The prompt names
    # the exact keys + their framework labels so the model fills the format-specific beats; the
    # machine-parseable KEYS line lets the deterministic stub writers stay format-aware.
    _spec = structure_spec(format_spec)
    _steps = [k for k, _ in _spec] if _spec else list(CANONICAL_SCRIPT_STRUCTURE)
    if _spec:
        _label_lines = "\n".join(f"  - {k}: {label}" for k, label in _spec)
        structure_block = (f"STRUCTURE (this format's canonical framework beats — fill EACH):\n"
                           f"{_label_lines}\n{_STRUCTURE_KEYS_MARKER} {', '.join(_steps)}")
    else:
        structure_block = (f"STRUCTURE (this format has no managed framework — use the 4-beat canon):\n"
                           f"{_STRUCTURE_KEYS_MARKER} {', '.join(_steps)}")
    structure_json = "{" + ", ".join(f'"{k}": "..."' for k in _steps) + "}"
    return f"""Write the full SCRIPT for an approved content slot, in spoken Palestinian Arabic.
{fb}
{head}
{acceptance}
{rework_overrides}
APPROVED TOPIC
  topic_angle: {topic['topic_angle']}
  hook_text  : {topic['hook_text']}   (this is the spoken opening — keep it intact)
  hook_type  : {topic['hook_type']}

HCS {hcs['hcs_id']} — {hcs['name_en']}
  core_wound     : {hcs['core_wound']}
  false_belief   : {hcs['false_belief']}
  earthquake     : {hcs['earthquake_sentence']}
  islamic_anchor : {anchor or '(none)'}

ANCHOR POLICY — OMIT BY DEFAULT. Most scripts must NOT use a Quran/Hadith anchor. Include one
ONLY if it is the single most natural way to land THIS exact wound and the script would feel
incomplete without it. Never quote a verse/hadith that is decorative, loosely related, or
force-fit to hit a quota. If — and only if — you use it, weave it in organically (never tacked
on) and you MUST fill anchor_justification explaining why it lands here. When in doubt, leave it
out and set used_islamic_anchor=false.

LENS {lens['lens_id']} — {lens['name_en']}.  FORMAT: {slot['format']}.
{format_guidance_block(format_spec)}

DIALECT: strictly Palestinian (ar-PS). Do NOT use Gulf words (مو، وايد، شلون) or Egyptian
words (دلوقتي، عايز، إزاي، كده، مفيش، بتاع، ده، دي، دول). Use مش/هلق/بدي/إشي.
{exemplars}
=== CANON-013 Hard Fails (auto-reject) ===
{hook_rules_text()}

=== CANON-012 Mandatory Delivery Check (every script MUST contain) ===
{delivery_check_text()}

Write a tight script (suited to {slot['format']}, short-form ≤ ~30s of speech unless the
format demands otherwise). Open on the hook_text verbatim. Carry a full emotional journey,
use a metaphor, a grounded scientific/psychological truth, a light human moment, and an
unforgettable final line. Quran/Hadith ONLY if it lands organically (see ANCHOR POLICY) —
otherwise omit it entirely. On rework, treat the CURRENT HEAD SCRIPT as the baseline and change
only the parts needed to satisfy the reviewer comment. If the comment asks for a different
opening, the beat immediately after hook_text must materially change. If the comment asks for
a different ending, final_line must materially change. If the comment forbids scripture, do
not include any verse/hadith and set used_islamic_anchor=false. If the comment asks for a home
scene, the line immediately after hook_text must anchor the listener in one concrete moment
inside the house. If the comment asks for one short practical step, final_line must be only
that short step, not a long explanation. If the comment asks for a gentler/softer delivery,
delivery_notes must explicitly signal a calmer, softer, warmer performance approach than the
current head. If the comment asks for a question ending, final_line must be phrased as a direct
reflective question. Keep the final_line in Palestinian wording too: use هلق rather than Egyptian دلوقتي.

{structure_block}
Return JSON exactly:
{{"script_ar": "the full script, ready to read aloud",
  "structure": {structure_json},
  "final_line": "the last line",
  "delivery_notes": "tone / pacing / delivery cues",
  "used_islamic_anchor": true/false,
  "anchor_justification": "REQUIRED non-empty ONLY if used_islamic_anchor=true: why this exact verse/hadith lands organically on THIS wound; else \"\"",
  "uses_dialect": true,
  "delivery_check": {{"scroll_stop_hook": true, "emotional_journey": true, "metaphor": true,
                      "scientific_truth": true, "quran_or_hadith_organic": true/false,
                      "light_human_moment": true, "unforgettable_final_line": true}}{cs}}}"""


# ---------------------------------------------------------------------------
# JSON parsing from model output
# ---------------------------------------------------------------------------
def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL).strip()  # thinking models
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    start = t.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]}")
    # Scan for the FIRST balanced object (string-literal aware) so trailing prose or a
    # second object after it — e.g. some models emit "{...}\n{...}" — doesn't break json.loads
    # with "Extra data". Falls back to the last brace if no balance is found.
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                # strict=False tolerates literal control chars (raw newlines/tabs) inside
                # string values — some models emit a multi-line script_ar without escaping \n
                return json.loads(t[start:i + 1], strict=False)
    return json.loads(t[start:t.rfind("}") + 1], strict=False)


# ---------------------------------------------------------------------------
# Stage runner — primary -> fallback fall-through with logging
# ---------------------------------------------------------------------------
def _resolved_execution_identity(chat):
    """#321 R8 — the ACTUAL served execution identity from the runner, as (provider, model), or
    (None, None) for genuine absence. The runner's `.model` is the served ``"provider:model"`` label
    set by `.complete()` (fallback-aware — it reflects the provider/model that actually served, not the
    configured route preference), mirroring the script path which already persists `script_chat.model`.
    The caller records absence as SQL NULL — never a coerced config dict or the string "unknown"."""
    label = getattr(chat, "model", None)
    if not isinstance(label, str) or not label.strip():
        return None, None
    provider, sep, model = label.partition(":")
    if not sep:
        return None, (label.strip() or None)      # bare label, no provider prefix -> model only
    return (provider.strip() or None), (model.strip() or None)


class StageRunner:
    """Presents a single .complete()/.model interface over an ordered list of
    (label, ChatClient). On a ProviderError (incl. quota / HTTP 402 / missing key)
    it logs and falls through to the next client; raises only if all fail."""

    def __init__(self, name, clients):
        self.name = name
        self.clients = clients          # [(label, ChatClient), ...]
        self.last_used = None

    @property
    def model(self):
        return self.last_used or (self.clients[0][0] if self.clients else "?")

    def complete(self, system, user):
        errors = []
        for i, (label, client) in enumerate(self.clients):
            try:
                out = client.complete(system, user)
                self.last_used = label
                if i > 0:
                    print(f"  [fallback] {self.name}: now using {label} "
                          f"(after {len(errors)} failure(s))")
                return out
            except ProviderError as e:
                errors.append(f"{label}: {e}")
                nxt = self.clients[i + 1][0] if i + 1 < len(self.clients) else "—"
                print(f"  [fallback] {self.name}: {label} failed ({str(e)[:110]}) -> {nxt}")
        raise ProviderError(f"{self.name}: all providers failed :: {' | '.join(errors)}")


# --- deterministic stub writer (TANAGHOM_WRITER_STUB=1) — for tests / offline rework proof ---
# Comment-RESPONSIVE: it extracts the reviewer comment from the rework prompt and reflects it in
# v2 + a change-summary, so a test can assert the comment flowed in (plumbing), without a network.
class _StubRunner:
    model = "stub:test"

    def complete(self, system, user):
        m = re.search(r"REVIEWER COMMENT: «(.+?)»", user, re.DOTALL)
        comment = m.group(1).strip() if m else None
        # A deterministic but comment-RESPONSIVE rework: reflect EACH requested change (as classified by
        # _feedback_requests) so the heuristic rework-acceptance check passes for every common reviewer
        # instruction — otherwise a hook/tone/ending request the stub ignored would be rejected and the
        # item would stay stuck in "awaiting regeneration". The real writer applies the comment
        # intelligently; the stub just produces a valid, minimal edit that satisfies the same check.
        req = _feedback_requests(comment) if comment else {}
        if "Write the full SCRIPT" in user:
            # #149 — emit exactly the structure keys the prompt advertises (registry-driven), so the
            # deterministic stub is format-aware without any hardcoded per-format mapping.
            _keys = _structure_keys_from_prompt(user)
            d = {"script_ar": "هاد النص تجريبي بالعامية الفلسطينية بحكي عن الموضوع بوضوح ومختصر.",
                 "structure": {k: ".." for k in _keys},
                 "final_line": "السطر الأخير", "delivery_notes": "نبرة هادئة",
                 "used_islamic_anchor": False, "anchor_justification": "", "uses_dialect": True,
                 "delivery_check": {"scroll_stop_hook": True, "emotional_journey": True, "metaphor": True,
                                    "scientific_truth": True, "quran_or_hadith_organic": False,
                                    "light_human_moment": True, "unforgettable_final_line": True}}
            if comment:
                opening = f"نسخة معدّلة بناءً على ملاحظتك «{comment}». "
                if req.get("home_scene"):
                    opening += "تخيّل حالك بالبيت جوّا غرفتك قدّام الباب. "   # concrete inside-the-house beat
                if req.get("family_redirect"):
                    opening += "الكلام هون موجّه للأب والأم مع بعض. "
                d["script_ar"] = opening + d["script_ar"]
                if req.get("softer_tone"):
                    d["delivery_notes"] = "نبرة أهدى وألطف وأحنّ، دافئة ومتفهّمة"
                if req.get("question_ending"):
                    d["final_line"] = "شو أول خطوة رح تعملها اليوم عشان تتغيّر؟"
                elif req.get("practical_step_short"):
                    d["final_line"] = "دوّن هدف واحد اليوم"
                elif req.get("change_ending"):
                    d["final_line"] = "هاي نهاية جديدة واضحة ومقصودة"
                d["change_summary_ar"] = f"عدّلت النص ليعالج: {comment}"
                d["change_summary_en"] = f"revised the script to address: {comment}"
            return json.dumps(d, ensure_ascii=False)
        d = {"maps_to_hcs": True, "topic_angle": "زاوية تجريبية واضحة",
             "hook_text": "الخوف بياكل قرارك اليوم", "hook_type": "Painful Truth",
             "rationale_ar": "سبب مختصر", "rationale_en": "concise reason"}
        if comment:
            d["topic_angle"] = f"نسخة معدّلة بناءً على ملاحظتك «{comment}»"
            if req.get("family_redirect"):
                d["topic_angle"] += " بشكل يخاطب الأب والأم معاً"
            if req.get("change_hook") or req.get("change_hook_last_word"):
                # Change ONLY the last word of the CURRENT hook (preserve the rest): satisfies both
                # "change the title/hook" and "replace the last word" requests. Rotate the replacement so
                # consecutive reworks always differ from the current head.
                hooks = re.findall(r"hook_text\s*[:：]\s*(.+)", user)
                cur_hook = next((h.strip().splitlines()[0].strip() for h in reversed(hooks)
                                 if re.search(r"[ء-ي]", h)), d["hook_text"])
                words = cur_hook.split()
                if len(words) >= 2:
                    words[-1] = next((w for w in ("هلق", "لسا", "بكرة") if w != words[-1]), "هلق")
                    d["hook_text"] = " ".join(words)
            d["change_summary_ar"] = f"عدّلت الموضوع ليعالج: {comment}"
            d["change_summary_en"] = f"revised the topic to address: {comment}"
        return json.dumps(d, ensure_ascii=False)


class _StubEmbed:
    def embed(self, text):                       # text-varied (hash) -> near-orthogonal, low dedup sim
        out = []
        i = 0
        while len(out) < 1024:
            out.extend(b / 127.5 - 1.0 for b in hashlib.sha256(f"{text}|{i}".encode()).digest())
            i += 1
        v = out[:1024]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


def build_stage_runner(providers, stage_cfg, name):
    """Build a StageRunner from a stage's
    {temperature, max_tokens, params, primary, fallback[]}.
    Each ref may override temperature/max_tokens/params/prompt_suffix; ref params merge
    over stage params, and a null value unsets a key (so a fallback can drop a knob the
    primary needs — e.g. reasoning_effort for a non-thinking local model)."""
    s_temp = stage_cfg.get("temperature", 0.8)
    s_maxt = stage_cfg.get("max_tokens", 1200)
    s_timeout = stage_cfg.get("timeout", 300)
    s_params = stage_cfg.get("params", {}) or {}
    refs = [stage_cfg["primary"]] + stage_cfg.get("fallback", [])
    clients = []
    for r in refs:
        merged = {**s_params, **(r.get("params") or {})}
        merged = {k: v for k, v in merged.items() if v is not None}   # null = unset
        clients.append((
            f"{r['provider']}:{r['model']}",
            ChatClient(providers[r["provider"]], r["model"],
                       r.get("temperature", s_temp), r.get("max_tokens", s_maxt),
                       merged, r.get("prompt_suffix", ""), r.get("timeout", s_timeout))))
    return StageRunner(name, clients)


def build_rework_verifier_runner(cfg, default_stage_cfg, name):
    rv = (cfg.get("writers", {}) or {}).get("rework_verifier") or {}
    if rv.get("enabled", True) is False:
        return None
    stage_cfg = rv.get("model") or {
        "temperature": rv.get("temperature", 0.1),
        "max_tokens": rv.get("max_tokens", 500),
        "timeout": rv.get("timeout", 90),
        "primary": default_stage_cfg["primary"],
        "fallback": default_stage_cfg.get("fallback", []),
    }
    return build_stage_runner(cfg["providers"], stage_cfg, name)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
HOOK_TYPES = {"Painful Truth", "The Collision", "The Drop", "The Promise", "The Command"}


def generate_topic(chat, verifier_chat, slot, hcs, lens, format_spec, cfg_writers, avoid_texts, exemplars="", feedback=None, current_head=None):
    """Generate a topic whose spoken hook passes CANON-013 + the dialect guard, retrying
    on violation. `feedback` (a reviewer's request-change note) is injected for rework.
    Returns (topic_dict, status): 'ok' | 'clarify' | 'hook_failed'."""
    tries = cfg_writers.get("hook_max_regenerations", 3) + (1 if feedback else 0)
    base = topic_prompt(slot, hcs, lens, format_spec, exemplars, feedback=feedback, current_head=current_head)
    last = None
    for attempt in range(tries + 1):
        prompt = base
        notes = []
        if avoid_texts:
            notes.append("AVOID near-duplicates of these existing angles/hooks "
                         "(make this materially different):\n- " + "\n- ".join(avoid_texts))
        if last:
            notes.append(f"Your previous topic output failed validation: {last}. Fix every issue.")
        if notes:
            prompt = base + "\n\n" + "\n\n".join(notes)
        raw = chat.complete(SYSTEM_VOICE, prompt)
        try:
            data = parse_json(raw)
        except ValueError as e:
            if attempt < tries:
                last = f"invalid JSON ({str(e)[:160]}). Return exactly one valid JSON object with every required field."
                continue
            raise
        if data.get("maps_to_hcs") is False or data.get("status") == "NEEDS_STRATEGIC_CLARIFICATION":
            return data, "clarify"
        if data.get("hook_type") not in HOOK_TYPES:
            data["hook_type"] = slot["hook_type"]
        violations = validate_hook(data.get("hook_text", ""), cfg_writers)
        violations += arabic_content_violations({
            "topic_angle": data.get("topic_angle", ""),
            "hook_text": data.get("hook_text", ""),
            "rationale_ar": data.get("rationale_ar", ""),
        })
        rework_failures = rework_acceptance_failures(feedback, "topic", current_head, data)
        verifier_failures = verify_rework_compliance(verifier_chat, "topic", feedback, current_head, data)
        blocking_verifier_failures = verifier_failures if attempt < tries else []
        data["_hook_violations"] = violations
        data["_rework_failures"] = rework_failures + blocking_verifier_failures
        if not violations and not rework_failures and not blocking_verifier_failures:
            return data, "ok"
        last = ", ".join(violations + rework_failures + verifier_failures)
    return data, "hook_failed"


def verify_anchor_organic(chat, hcs, script_ar, anchor):
    """Adversarial second opinion on a used Quran/Hadith anchor. The script-writer
    self-certifies every anchor as 'organic', so we don't trust it: a separate skeptical
    pass decides KEEP vs REMOVE, defaulting to REMOVE unless the scripture clearly belongs
    and is applied correctly. Fail-open (KEEP) if the verifier itself errors, so a flaky
    provider never blocks the round. Returns (keep: bool, reason: str)."""
    q = (f"You are a strict Islamic-content editor reviewing a short Palestinian-Arabic "
         f"script. It used the Quran/Hadith anchor below. Decide if the scripture is "
         f"GENUINELY ORGANIC and CORRECTLY applied to THIS specific emotional wound — or "
         f"decorative, loosely related, force-fit, or theologically misapplied. Default to "
         f"REMOVE unless it clearly belongs and is applied correctly.\n\n"
         f"WOUND (HCS {hcs['hcs_id']} — {hcs['name_en']}): {hcs['core_wound']}\n"
         f"ANCHOR (theme/source): {anchor or '(none)'}\n"
         f"SCRIPT:\n{script_ar}\n\n"
         f'Return ONLY JSON: {{"verdict": "KEEP" or "REMOVE", "reason": "one sentence"}}')
    try:
        data = parse_json(chat.complete("You are a precise JSON-only Islamic-content editor.", q))
    except (ProviderError, ValueError) as e:
        print(f"  [anchor] verifier unavailable ({str(e)[:60]}) — keeping (fail-open)")
        return True, "verifier unavailable"
    keep = str(data.get("verdict", "")).strip().upper() != "REMOVE"
    return keep, str(data.get("reason", ""))[:160]


def generate_script(chat, verifier_chat, slot, hcs, lens, topic, format_spec, cfg_writers, exemplars="", feedback=None, current_script=None):
    tries = cfg_writers.get("script_max_regenerations", 2) + (2 if feedback else 0)
    anchor_cfg = cfg_writers.get("islamic_anchor", {})
    expected_structure = structure_steps(format_spec)   # #149 — the registry-driven keys to validate
    base = script_prompt(slot, hcs, lens, topic, format_spec, exemplars, feedback=feedback,
                         current_script=current_script)
    last, pruned = None, False
    for attempt in range(tries + 1):
        prompt = base if not last else base + f"\n\nREVISE per this instruction: {last}"
        raw = chat.complete(SYSTEM_VOICE, prompt)
        try:
            data = parse_json(raw)
        except ValueError as e:
            if attempt < tries:
                last = f"invalid JSON ({str(e)[:160]}). Return exactly one valid JSON object with every required field."
                continue
            raise
        fails = script_hard_fails(data.get("script_ar", ""), cfg_writers)
        rework_failures = rework_acceptance_failures(feedback, "script", current_script, data)
        verifier_failures = verify_rework_compliance(verifier_chat, "script", feedback, current_script, data)
        blocking_verifier_failures = verifier_failures if attempt < tries else []
        dc = data.get("delivery_check", {})
        missing = [k for k in ("scroll_stop_hook", "emotional_journey", "metaphor",
                               "scientific_truth", "light_human_moment",
                               "unforgettable_final_line") if not dc.get(k)]
        data["_hard_fails"] = fails
        data["_delivery_missing"] = missing
        # #149 — validate the emitted structure carries the format's registry-driven keys (soft flag,
        # mirroring delivery_check: surfaced for review, does not hard-fail generation).
        _struct = data.get("structure") if isinstance(data.get("structure"), dict) else {}
        data["_structure_missing"] = [k for k in expected_structure if not str(_struct.get(k) or "").strip()]
        data["_rework_failures"] = rework_failures + blocking_verifier_failures
        # Anchor policy: a used anchor that the model can't even self-justify is force-fit.
        anchor_forced = []
        if anchor_cfg.get("require_justification", True) and data.get("used_islamic_anchor"):
            organic = bool(dc.get("quran_or_hadith_organic"))
            justified = bool(str(data.get("anchor_justification", "")).strip())
            if not (organic and justified):
                anchor_forced = ["islamic_anchor used without an organic justification — "
                                 "REMOVE the Quran/Hadith entirely and rewrite without it"]
        data["_anchor_forced"] = bool(anchor_forced)
        data["_anchor_pruned"] = pruned
        if not fails and not missing and not anchor_forced and not rework_failures and not blocking_verifier_failures:
            # Adversarial organic check on a used anchor (model self-cert isn't trusted).
            if (anchor_cfg.get("verify", True) and data.get("used_islamic_anchor")
                    and not pruned and attempt < tries):
                keep, reason = verify_anchor_organic(chat, hcs, data.get("script_ar", ""),
                                                     hcs["islamic_anchor"])
                if not keep:
                    pruned = True
                    print(f"  [anchor] verifier: REMOVE — {reason[:90]}; regenerating w/o anchor")
                    last = (f"REMOVE the Quran/Hadith entirely — it is NOT organic here "
                            f"({reason}). Rewrite the script without any scripture and set "
                            f"used_islamic_anchor=false.")
                    continue
            return data, "ok"
        last = "; ".join(fails + [f"missing:{m}" for m in missing] + anchor_forced + rework_failures + verifier_failures)
    return data, "soft_fail"


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------
def vec_literal(vec):
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _load_engine():
    """#184 — lazy gate-engine import (the engine never imports this module, so no cycle; the
    sys.path fallback covers standalone `python agents/run_writers.py` CLI runs)."""
    try:
        import engine as e  # gates/ already on sys.path in every gates-side caller
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gates"))
        import engine as e
    return e


def _nearest_topic(cur, vec, where, params):
    q = (f"SELECT t.text_ar, t.slot_id, 1 - (t.embedding <=> %s::vector) AS sim "
         f"FROM topic t JOIN slot s ON s.slot_id = t.slot_id "
         f"WHERE {where} ORDER BY t.embedding <=> %s::vector LIMIT 1")
    cur.execute(q, [vec, *params, vec])
    row = cur.fetchone()
    return (row["sim"], row["text_ar"]) if row else (None, None)


def repetition_check(cur, embedding, slot, hcs, policy):
    """#184 — evaluate a candidate topic against the ACTIVE managed repetition policy
    (engine.effective_repetition_policy — the single central derivation, never scattered config).

    Returns (sim, near_text, allowed_by):
      sim/near_text — the nearest match INSIDE the policy's violation set (a candidate's own
      slot never counts: a rework revision is not a "repeat" of itself);
      allowed_by    — the repeat mode that excused an otherwise above-threshold match OUTSIDE
                      the violation set (e.g. same topic on a different format under
                      cross_format), so the acceptance can be flagged + audited truthfully.
    """
    scope = policy.get("scope", "all")
    where, params = "t.embedding IS NOT NULL AND t.slot_id <> %s", [slot["slot_id"]]
    if scope in ("hcs", "current_cycle"):
        where += " AND t.hcs_id = %s"
        params.append(hcs["hcs_id"])
    elif scope == "round":
        where += " AND t.round_id = %s"
        params.append(slot["round_id"])
    # scope == "all" -> the whole prior topic history is in play (the production default)
    vec = vec_literal(embedding)
    modes = policy.get("repeat_modes") or {}
    threshold = policy.get("similarity_threshold", 0.86)
    allowed_by = None
    if modes.get("cross_format"):
        # cross-format reuse is permitted: only SAME-format topics count as violations…
        sim, near_text = _nearest_topic(cur, vec, where + " AND s.format = %s",
                                        params + [slot["format"]])
        # …but if a different-format near-duplicate exists, record WHICH mode allowed it.
        if sim is None or sim < threshold:
            other_sim, _ = _nearest_topic(cur, vec, where + " AND s.format <> %s",
                                          params + [slot["format"]])
            if other_sim is not None and other_sim >= threshold:
                allowed_by = "cross_format"
        return sim, near_text, allowed_by
    sim, near_text = _nearest_topic(cur, vec, where, params)
    return sim, near_text, allowed_by


# ---------------------------------------------------------------------------
# Per-slot processing
# ---------------------------------------------------------------------------
def _slot_meta(cur, slot):
    cur.execute("SELECT * FROM hcs WHERE hcs_id=%s", (slot["hcs_id"],)); hcs = cur.fetchone()
    cur.execute("SELECT * FROM lens WHERE lens_id=%s", (slot["lens"],)); lens = cur.fetchone()
    cur.execute("SELECT * FROM format WHERE name=%s", (slot["format"],)); fmt = cur.fetchone()
    return hcs, lens, fmt


def process_topic(conn, topic_chat, verifier_chat, embed, cfg, slot, dry_run, feedback=None, revision=1, novelty=None, on_persist=None, repetition_policy=None):
    """Agent 1 ONLY: topic_angle + hook + bilingual reviewer rationale, with the dedup
    safety-net. Persists a topic row and moves the slot -> TOPIC_PROPOSED. `feedback` (a
    reviewer request-change note) is injected for rework; revision is the new version no.

    #292 — this is the FIRST advancement out of the schedule stage (the single shared stub+live
    path), so it is the only writer that can race a governed reorder. It captures the round's
    combined schedule token here, BEFORE generating, and revalidates it under the round lock
    immediately before the first artifact insert. No DB lock is ever held across the model call."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    hcs, lens, format_spec = _slot_meta(cur, slot)
    _sched_token_at_read = _load_engine().schedule_token(cur, slot["round_id"])
    cfg_writers = cfg.get("writers", {})
    ex = exemplars_block(cfg, slot["pillar_code"])
    # #184 — the effective repetition policy is centrally derived (managed DB row over the strict
    # production default), never read from scattered config here.
    _eng = _load_engine()
    # #310 §E — a Stage 2A job passes its IMMUTABLE repetition snapshot (frozen at enqueue); use it
    # verbatim and NEVER do a live lookup, so a same-scope in-place policy update after enqueue cannot
    # change this job's dedup behaviour. V1/rework callers pass none and keep the live derivation.
    policy = repetition_policy if repetition_policy is not None else _eng.effective_repetition_policy(conn, cfg)
    threshold = policy["similarity_threshold"]
    dedup_tries = policy["max_regenerations"]
    current_head = None
    if feedback:
        cur.execute("""SELECT text_ar, hook_text, hook_type, rationale_ar, rationale_en
                       FROM topic WHERE slot_id=%s
                       ORDER BY revision DESC, created_at DESC LIMIT 1""", (slot["slot_id"],))
        head = cur.fetchone()
        current_head = {
            "topic_angle": (head["text_ar"] if head else slot.get("topic_angle")) or "",
            "hook_text": (head["hook_text"] if head else slot.get("hook_text")) or "",
            "hook_type": (head["hook_type"] if head else slot.get("hook_type")) or "",
            "rationale_ar": (head["rationale_ar"] if head else None) or "",
            "rationale_en": (head["rationale_en"] if head else None) or "",
        }
    print(f"\n{'#'*92}\n# TOPIC {slot['slot_id']} | {slot['pillar_code']} | HCS {hcs['hcs_id']} "
          f"{hcs['name_en']} | lens {lens['lens_id']} {lens['name_en']} | {slot['format']}"
          + (f"  [rework v{revision}]" if feedback else "") + f"\n{'#'*92}")
    # #310 §B / #268 — pre-seed the reactive dedup list with the bounded novelty brief so the FIRST
    # generation already steers away from recently-used territory. `repetition_check` below stays the
    # authoritative semantic net; this only reduces the odds we spend a regeneration on an obvious repeat.
    avoid = list(novelty["exclusion_texts"]) if novelty and novelty.get("exclusion_texts") else []
    topic, status = None, None
    sim, near_text, flagged_dup = None, None, False
    for d in range(dedup_tries + 1):
        topic, status = generate_topic(topic_chat, verifier_chat, slot, hcs, lens, format_spec, cfg_writers, avoid, ex,
                                       feedback=feedback, current_head=current_head)
        if status == "clarify":
            print(f"  [Agent 1] NEEDS_STRATEGIC_CLARIFICATION: {topic.get('reason','')}")
            cur.close()
            return {"slot_id": slot["slot_id"], "result": "NEEDS_STRATEGIC_CLARIFICATION"}
        emb = embed.embed(f"{topic['topic_angle']} — {topic['hook_text']}")
        sim, near_text, repeat_allowed_by = (None, None, None)
        if policy.get("enabled", True):
            sim, near_text, repeat_allowed_by = repetition_check(cur, emb, slot, hcs, policy)
        if sim is not None and sim >= threshold and d < dedup_tries:
            print(f"  [dedup] near-duplicate (sim={sim:.3f} ≥ {threshold}) vs «{near_text[:60]}» "
                  f"— regenerating ({d+1}/{dedup_tries})")
            avoid.append(f"{topic['topic_angle']} / {topic['hook_text']}"); continue
        if sim is not None and sim >= threshold:
            flagged_dup = True
        break
    hv = topic.get("_hook_violations", [])
    rework_failures = topic.get("_rework_failures", [])
    soft = sorted(set(dialect_soft_warnings(topic.get("hook_text", ""), cfg_writers.get("dialect_guard"))))
    flags = []
    if flagged_dup: flags.append("near_duplicate")
    # #184 — a near-duplicate outside the violation set was ACCEPTED under an explicit policy
    # repeat mode: flag it truthfully (never silent) — the audit row lands with the persist below.
    if repeat_allowed_by: flags.append(f"repeat_allowed_{repeat_allowed_by}")
    if hv: flags.append("hook_check_failed")
    if rework_failures: flags.append("rework_under_applied")
    if soft: flags.append("dialect_soft_warn")
    print(f"  [Agent 1] hook: «{topic['hook_text']}» ({word_count(topic['hook_text'])} words) "
          f"type={topic['hook_type']}  hook_check={'PASS' if not hv else 'FAIL '+str(hv)}")
    print(f"            angle: {topic['topic_angle']}")
    print(f"            why-now (en): {topic.get('rationale_en','')}")
    if rework_failures: print(f"  [rework-check] {rework_failures}")
    if soft: print(f"  [dialect-soft] {soft}")
    if feedback and (status != "ok" or rework_failures):
        cur.close()
        raise ValueError(f"{slot['slot_id']}: rework not accepted: {', '.join(rework_failures or [status])}")
    if dry_run:
        cur.close(); return {"slot_id": slot["slot_id"], "result": "DRY_RUN", "flags": flags}
    from_status, new_status = slot["status"], "TOPIC_PROPOSED"
    wcur = conn.cursor()
    # ---- #292 race closure — the model call is DONE; the lock starts HERE ----
    # The guard uses its OWN RealDict cursor: cursors on this connection share one transaction, so
    # the lock/revalidation is still atomic with the inserts below, while `wcur` stays a plain
    # cursor — it is handed to _clear_open_gate_decisions_after_rework() and directives.record(),
    # which read positional rows.
    _gcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Take the round row first (the same serialization point reorder and revise_schedule_slot use),
    # then revalidate the token captured before generation. If a governed reorder committed while we
    # were generating, this content was produced against a superseded schedule mapping: abort BEFORE
    # the first insert so the transaction rolls back with no topic row, no status change, and no
    # mutation audit. Symmetrically, if we commit first, a later reorder sees this slot advanced and
    # fails closed. No DB lock is held across the model call — generation finished above.
    _eng2 = _load_engine()
    _eng2._lock_round(_gcur, slot["round_id"])
    _sched_token_now = _eng2.schedule_token(_gcur, slot["round_id"])
    _gcur.close()
    if _sched_token_now != _sched_token_at_read:
        wcur.close(); cur.close()
        raise _eng2.ScheduleConflict(
            f"{slot['slot_id']}: the schedule mapping changed while this topic was generating "
            f"(token {_sched_token_at_read} -> {_sched_token_now}) — nothing was persisted; "
            "regenerate against the current schedule",
            {"round_id": slot["round_id"], "current_token": _sched_token_now})
    wcur.execute(
        """INSERT INTO topic (slot_id, hcs_id, lens, round_id, cycle_no, text_ar, text_en,
                              rationale_ar, rationale_en, hook_text, hook_type, revision,
                              feedback, change_summary_ar, change_summary_en, base_revision, embedding)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
           RETURNING topic_id""",
        (slot["slot_id"], hcs["hcs_id"], lens["lens_id"], slot["round_id"], slot["cycle_no"],
         topic["topic_angle"], None, topic.get("rationale_ar"), topic.get("rationale_en"),
         topic["hook_text"], topic["hook_type"], revision, feedback,
         topic.get("change_summary_ar"), topic.get("change_summary_en"),
         (revision - 1) if (feedback and revision > 1) else None, vec_literal(emb)))
    _new_topic_id = wcur.fetchone()[0]
    wcur.execute("UPDATE slot SET topic_angle=%s, hook_text=%s, hook_type=%s, status=%s, "
                 "updated_at=now() WHERE slot_id=%s",
                 (topic["topic_angle"], topic["hook_text"], topic["hook_type"], new_status,
                  slot["slot_id"]))
    if feedback:
        gate_stage, _ = _gate_for_rework(cfg, "topic")
        _clear_open_gate_decisions_after_rework(wcur, slot["slot_id"], gate_stage)
    if repeat_allowed_by:
        # #184 — policy-governed exception evidence: WHICH mode allowed the reuse, under WHICH
        # effective policy. Committed with the topic persist in the same transaction.
        wcur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
                     "VALUES ('slot',%s,'repetition_policy_exception_used','writers','agent',%s)",
                     (slot["slot_id"], Json({"mode": repeat_allowed_by, "revision": revision,
                                             "policy_source": policy["source"],
                                             "policy_scope": policy["scope"],
                                             "similarity_threshold": threshold})))
    action = "topic_reworked" if feedback else "topic_proposed"
    for act, detail in ((action, {"hook": topic["hook_text"], "revision": revision,
                                  "feedback": feedback, "near_dup_sim": sim, "flags": flags}),
                        ("status_change", {"from": from_status, "to": new_status})):
        wcur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
                     "VALUES ('slot',%s,%s,'writers','agent',%s)", (slot["slot_id"], act, Json(detail)))
    # M9·B1: record the directive the TOPIC stage consumed (strategy -> topic) as origin
    # provenance — the methodology selection this topic fulfilled. Same transaction.
    if directives.is_enabled(cfg):
        try:
            directives.record(wcur, slot["slot_id"],
                              directives.strategy_to_topic(slot, hcs, lens, cfg),
                              revision=revision, actor="writers", actor_kind="agent",
                              tenant_id=slot.get("tenant_id", "default"),
                              module=slot.get("module", "content"))
        except Exception as e:                   # noqa: BLE001 — provenance, never block the write
            print(f"  [directive] strategy->topic skipped: {e}")
    # #310 §E (P1-3) — the caller's persistence hook runs in THIS SAME transaction, on the SAME
    # cursor, BEFORE the single commit below. So the Topic row + slot advance + #310 provenance
    # commit atomically, leaving NO generated Topic without exact provenance. V1/rework callers pass
    # no hook and are byte-unaffected.
    # #319 — a raising hook skips the commit but does NOT itself roll back: a hook that raises a plain
    # Python error (not a SQL error) leaves this transaction open and still committable. Discarding it
    # is the CALLER's obligation, because the caller owns `conn` — see run_rework_operation, which
    # rolls back before it records any failure state. A caller that commits this connection after a
    # hook raised will durably persist the rejected generation.
    if on_persist is not None:
        on_persist(wcur, _new_topic_id, revision)
    conn.commit(); wcur.close(); cur.close()
    print(f"  [persist] slot -> {new_status}  (topic v{revision})")
    return {"slot_id": slot["slot_id"], "result": new_status, "flags": flags, "topic_id": str(_new_topic_id)}


def process_script(conn, script_chat, verifier_chat, cfg, slot, dry_run, feedback=None, revision=1,
                   on_persist=None):
    """Agent 2 ONLY: full script (+ production directions) for an ALREADY-APPROVED topic.
    Moves the slot TOPIC_APPROVED -> DRAFT_ASSIGNED (or re-enters script_review on rework)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    hcs, lens, format_spec = _slot_meta(cur, slot)
    cfg_writers = cfg.get("writers", {})
    ex = exemplars_block(cfg, slot["pillar_code"])
    # script from the APPROVED topic revision (you may have approved v2 even if v3 exists), else head
    # #357 — a governed attempt pins the EXACT approved revision on the slot; consume it verbatim.
    # Without a pin this falls back to the historical resolution (approved revision, else head).
    _pin = slot.get("_pinned_topic_revision") if hasattr(slot, "get") else None
    if _pin is not None:
        cur.execute("SELECT * FROM topic WHERE slot_id=%s AND revision=%s LIMIT 1",
                    (slot["slot_id"], _pin))
    else:
        cur.execute("""SELECT * FROM topic WHERE slot_id=%s AND revision = COALESCE(
                     (SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='topic'),
                     (SELECT max(revision) FROM topic WHERE slot_id=%s)) LIMIT 1""",
                (slot["slot_id"], slot["slot_id"], slot["slot_id"]))
    trow = cur.fetchone()
    if not trow:
        cur.close(); raise ValueError(f"{slot['slot_id']}: no approved topic to script")
    topic = {"topic_angle": trow["text_ar"] or slot["topic_angle"],
             "hook_text": trow["hook_text"] or slot["hook_text"],
             "hook_type": trow["hook_type"] or slot["hook_type"]}
    current_script = None
    if feedback:
        cur.execute("""SELECT script_ar, final_line, delivery_notes
                       FROM script WHERE slot_id=%s
                       ORDER BY revision DESC, script_id DESC LIMIT 1""", (slot["slot_id"],))
        srow = cur.fetchone()
        if srow:
            current_script = {
                "script_ar": srow["script_ar"] or "",
                "final_line": srow["final_line"] or "",
                "delivery_notes": srow["delivery_notes"] or "",
            }
    # M9·B1: CONSUME the incoming directive (approved topic = directive into the script stage).
    # The engine emitted it at topic_review approval; we read its acceptance_criteria here.
    if directives.is_enabled(cfg):
        incoming = directives.latest(cur, slot["slot_id"], "script")
        if incoming:
            ac = (incoming["payload"] or {}).get("acceptance_criteria", [])
            print(f"  [directive] consuming topic_directive v{incoming['revision']} — "
                  f"must satisfy: {', '.join(ac)}")
    print(f"\n{'#'*92}\n# SCRIPT {slot['slot_id']} | {slot['pillar_code']} | HCS {hcs['hcs_id']} "
          f"{hcs['name_en']} | {slot['format']}"
          + (f"  [rework v{revision}]" if feedback else "") + f"\n{'#'*92}")
    script, s_status = generate_script(script_chat, verifier_chat, slot, hcs, lens, topic, format_spec, cfg_writers, ex,
                                       feedback=feedback, current_script=current_script)
    used_anchor = bool(script.get("used_islamic_anchor"))
    reviews = cfg.get("reviews", {})
    needs_scholar = used_anchor and reviews.get("require_scholar_review_for_islamic_anchor", True)
    needs_native = bool(script.get("uses_dialect", True)) and reviews.get("require_native_dialect_review", True)
    soft = sorted(set(dialect_soft_warnings(script.get("script_ar", ""), cfg_writers.get("dialect_guard"))))
    rework_failures = script.get("_rework_failures", [])
    flags = []
    if needs_scholar: flags.append("needs_scholar_review")
    if needs_native: flags.append("needs_native_review")
    if script.get("_hard_fails"): flags.append("script_hard_fail")
    if script.get("_delivery_missing"): flags.append("delivery_check_incomplete")
    if script.get("_structure_missing"): flags.append("structure_incomplete")   # #149
    if script.get("_anchor_forced"): flags.append("anchor_not_organic")
    if script.get("_anchor_pruned"): flags.append("anchor_pruned")
    if rework_failures: flags.append("rework_under_applied")
    if soft: flags.append("dialect_soft_warn")
    print(f"  [Agent 2] script {len(script.get('script_ar',''))} chars  "
          f"hard_fail={script.get('_hard_fails') or 'none'}  "
          f"delivery_missing={script.get('_delivery_missing') or 'none'}")
    print(f"            final_line: {script.get('final_line','')}")
    if rework_failures: print(f"  [rework-check] {rework_failures}")
    print(f"  [flags]   anchor_used={used_anchor} -> {flags or ['(none)']}")
    if feedback and (s_status != "ok" or rework_failures):
        cur.close()
        raise ValueError(f"{slot['slot_id']}: rework not accepted: {', '.join(rework_failures or [s_status])}")
    if dry_run:
        cur.close(); return {"slot_id": slot["slot_id"], "result": "DRY_RUN", "flags": flags}
    from_status, new_status = slot["status"], "DRAFT_ASSIGNED"
    wcur = conn.cursor()
    wcur.execute(
        """INSERT INTO script (slot_id, hcs_id, lens, script_ar, structure, final_line,
                               delivery_notes, delivery_check, used_islamic_anchor,
                               needs_scholar_review, needs_native_review, flags, model,
                               revision, feedback, change_summary_ar, change_summary_en, base_revision)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING script_id""",
        (slot["slot_id"], hcs["hcs_id"], lens["lens_id"], script.get("script_ar"),
         Json(script.get("structure")), script.get("final_line"), script.get("delivery_notes"),
         Json(script.get("delivery_check")), used_anchor, needs_scholar, needs_native,
         Json(flags), script_chat.model, revision, feedback,
         script.get("change_summary_ar"), script.get("change_summary_en"),
         (revision - 1) if (feedback and revision > 1) else None))
    script_id = wcur.fetchone()[0]
    wcur.execute("UPDATE slot SET script_ref=%s, status=%s, updated_at=now() WHERE slot_id=%s",
                 (str(script_id), new_status, slot["slot_id"]))

    # #357 — bind THIS produced revision to the governed attempt IN THE SAME TRANSACTION.
    #
    # Provenance must be a fact recorded at the moment of production, never an inference made
    # afterwards. An earlier revision of this slice reconstructed the link post-hoc by selecting each
    # pinned slot's LATEST script — which, for a slot whose writer had just failed but which already
    # held a script from a prior attempt or rework, linked that OLD revision to the NEW job and
    # claimed this attempt produced it. Fabricated provenance is worse than absent provenance: it
    # cannot be distinguished from the real thing.
    #
    # Writing it here means the link exists if and only if the row it describes was written by this
    # attempt, and a rollback discards both together.
    _job = (slot.get("_attempt_job_id") if hasattr(slot, "get") else None)
    _tok = (slot.get("_attempt_claim_token") if hasattr(slot, "get") else None)
    _wrk = (slot.get("_attempt_worker") if hasattr(slot, "get") else None)

    # #362 — FENCE THE OUTPUT WRITE ITSELF, inside this transaction.
    #
    # The terminal transition is fenced elsewhere, but Amendment L requires the RESULT and PROVENANCE
    # writes to be fenced too — and they happen HERE, in the writer's own transaction. Without this a
    # worker whose tenure had already been reclaimed would still persist a script row and its
    # provenance; only its final status update would be refused. The artifact would exist, attributed
    # to an attempt someone else now owns.
    #
    # The check shares this transaction and takes FOR UPDATE on the job row, so a reclaim cannot land
    # between verifying ownership and committing the rows — a separate pre-write check would leave
    # exactly that window, which L rules out.
    if _job and _tok and _wrk:
        wcur.execute("""SELECT 1 FROM generation_job
                         WHERE job_id=%s AND stage='script' AND status='running'
                           AND claimed_by=%s AND claim_token=%s::uuid
                         FOR UPDATE""", (_job, _wrk, _tok))
        if wcur.fetchone() is None:
            conn.rollback()
            print(f"  [fenced] {slot['slot_id']}: ownership lost — script and provenance NOT written")
            wcur.close(); cur.close()
            return {"slot_id": slot["slot_id"], "result": "FENCED_OUT"}

    if _job:
        _stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
        _m = slot.get("_attempt_manifest") or {}
        wcur.execute("""INSERT INTO script_provenance
                          (script_id, revision, job_id, slot_id, topic_id, topic_revision,
                           workflow_version_id, methodology_version, framework_version,
                           writer_contract_version, prompt_template_version,
                           requested_route, requested_provider, requested_model,
                           effective_route, effective_provider, effective_model,
                           writer_mode, initiating_actor, effective_actor,
                           capability_binding, runtime_build)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (script_id, revision) DO NOTHING""",
                     (str(script_id), revision, _job, slot["slot_id"],
                      slot.get("_pinned_topic_id"), slot.get("_pinned_topic_revision"),
                      _m.get("workflow_version_id"), _m.get("methodology_version"),
                      _m.get("framework_version"), _m.get("writer_contract_version"),
                      _m.get("prompt_template_version"),
                      _m.get("requested_route"), _m.get("requested_provider"), _m.get("requested_model"),
                      "not_applicable" if _stub else _m.get("canonical_route"),
                      "not_applicable" if _stub else None,
                      script_chat.model,
                      _m.get("writer_mode"), _m.get("initiating_actor"), _m.get("effective_actor"),
                      "not_applicable", os.environ.get("TANAGHOM_BUILD_SHA") or "not_applicable"))
    if feedback:
        gate_stage, _ = _gate_for_rework(cfg, "script")
        _clear_open_gate_decisions_after_rework(wcur, slot["slot_id"], gate_stage)
    action = "script_reworked" if feedback else "script_assigned"
    for act, detail in ((action, {"revision": revision, "feedback": feedback, "flags": flags,
                                  "script_id": str(script_id)}),
                        ("status_change", {"from": from_status, "to": new_status,
                                           "script_id": str(script_id)})):
        wcur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
                     "VALUES ('slot',%s,%s,'writers','agent',%s)", (slot["slot_id"], act, Json(detail)))
    # #367 R3.3 — an in-transaction persistence hook, mirroring process_topic's `on_persist`. The
    # durable Script rework worker uses it to record Script rework provenance and complete the
    # claim-token-fenced rework operation in the SAME transaction as the script revision, so a stale
    # tenure's completion matches zero rows and rolls the whole generation back (Amendment 6).
    if on_persist is not None:
        on_persist(wcur, str(script_id), revision)
    conn.commit(); wcur.close(); cur.close()
    print(f"  [persist] slot -> {new_status}  script_id={script_id} (v{revision})")
    return {"slot_id": slot["slot_id"], "result": new_status, "flags": flags}


# ---------------------------------------------------------------------------
def select_slots(cur, args, status):
    """Slots in `status` matching the selection (--slot-ids / --round / --distinct-pillars
    / --limit). `status` is the stage's source state (RESERVED for topics, TOPIC_APPROVED
    for scripts) — no hardcoding."""
    if args.slot_ids:
        ids = [s.strip() for s in args.slot_ids.split(",") if s.strip()]
        cur.execute("SELECT * FROM slot WHERE slot_id = ANY(%s) AND status=%s "
                    "ORDER BY array_position(%s, slot_id)", (ids, status, ids))
        return cur.fetchall()
    q = "SELECT * FROM slot WHERE status=%s"
    params = [status]
    if args.round:
        q += " AND round_id=%s"
        params.append(args.round)
    q += " ORDER BY slot_id"
    cur.execute(q, params)
    rows = cur.fetchall()
    if args.distinct_pillars:
        seen, picked = set(), []
        for r in rows:
            if r["pillar_code"] not in seen:
                seen.add(r["pillar_code"])
                picked.append(r)
        rows = picked
    if args.limit:
        rows = rows[:args.limit]
    return rows


def select_rework(cur, gate_stage, review_status, rev_table, round_id=None):
    """Slots whose LATEST decision on a `gate_stage` gate is request_change, still at the
    review status, and not yet reworked (the decision is newer than the latest revision).
    Scoped to `round_id` when given (so `rework --round R2` only reworks R2, and the selftest
    stays isolated to its throwaway round). Returns rows + the reviewer note + next revision."""
    round_clause = " AND sl.round_id=%s" if round_id else ""
    params = [gate_stage, review_status] + ([round_id] if round_id else [])
    cur.execute(
        f"""WITH latest_dec AS (
              SELECT DISTINCT ON (gd.slot_id) gd.slot_id, gd.decision, gd.notes, gd.decided_at
              FROM gate_decision gd JOIN gate g USING (gate_id)
              WHERE g.stage=%s AND gd.slot_id IS NOT NULL
              ORDER BY gd.slot_id, gd.decided_at DESC)
            SELECT sl.*, ld.notes AS rework_note,
                   COALESCE((SELECT max(revision) FROM {rev_table} r WHERE r.slot_id=sl.slot_id),0)+1
                     AS next_revision
            FROM latest_dec ld JOIN slot sl ON sl.slot_id=ld.slot_id
            WHERE ld.decision='request_change' AND sl.status=%s{round_clause}
              AND ld.decided_at > COALESCE(
                    (SELECT max(created_at) FROM {rev_table} r WHERE r.slot_id=sl.slot_id),
                    'epoch'::timestamptz)
            ORDER BY sl.slot_id""", params)
    return cur.fetchall()


def db_connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "tanaghom"),
        user=os.environ.get("DB_USER", "tanaghom"),
        password=os.environ["DB_PASSWORD"])


def make_embed(cfg):
    ref = cfg["models"]["embeddings"]["primary"]
    return EmbeddingClient(cfg["providers"][ref["provider"]], ref["model"])


# ---------------------------------------------------------------------------
# two-stage flow: topics (RESERVED -> TOPIC_PROPOSED) then scripts (TOPIC_APPROVED -> DRAFT_ASSIGNED)
# ---------------------------------------------------------------------------
def _gate_for_rework(cfg, mode):
    """The gate whose rework_mode == mode (topic|script) -> (stage, awaiting-rework status).
    Slots sit at `changes_to` (CHANGES_REQUESTED) while awaiting rework; rework returns them to
    the gate's reviews_status for re-review."""
    for name, gc in (cfg.get("gates") or {}).items():
        if gc.get("rework_mode") == mode:
            return name, (gc.get("changes_to") or gc.get("reviews_status"))
    raise ValueError(f"no gate with rework_mode={mode!r} in config")


def _clear_open_gate_decisions_after_rework(cur, slot_id, gate_stage):
    """Clear active stage decisions once a reworked item re-enters review.

    Without this, the slot can return to its review status while still carrying the old
    `request_change` decision on the open gate, which makes the UI treat it as sent back
    instead of a fresh pending item.
    """
    cur.execute(
        """SELECT DISTINCT gd.gate_id
           FROM gate_decision gd
           JOIN gate g USING (gate_id)
           WHERE gd.slot_id=%s AND g.stage=%s AND g.status='open'""",
        (slot_id, gate_stage),
    )
    gate_ids = [row[0] for row in cur.fetchall()]
    if not gate_ids:
        return
    cur.execute(
        """DELETE FROM gate_decision
           USING gate
           WHERE gate_decision.gate_id=gate.gate_id
             AND gate_decision.slot_id=%s
             AND gate.stage=%s
             AND gate.status='open'""",
        (slot_id, gate_stage),
    )
    for gate_id in gate_ids:
        cur.execute(
            "INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
            "VALUES ('slot',%s,'decision_cleared','writers','agent',%s)",
            (slot_id, Json({"gate_id": str(gate_id), "reason": "rework_reentered_review"})),
        )


def _summary(results):
    print(f"\n{'='*92}\nSUMMARY\n{'='*92}")
    for r in results:
        print(f"  {r['slot_id']:<13} {r['result']:<22} {r.get('flags', r.get('error',''))}")


def _source_status_for_writer(cfg, writer_mode, fallback):
    """The configured writer input status for a writer_mode (topics|scripts)."""
    for gc in (cfg.get("gates") or {}).values():
        if gc.get("writer_mode") == writer_mode and gc.get("generates_from"):
            return gc["generates_from"]
    return fallback


def run_topics(cfg, args):
    topic_stage_cfg = cfg["models"]["topic_hook"]
    stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
    topic_chat = _StubRunner() if stub else build_stage_runner(cfg["providers"], topic_stage_cfg, "topic_hook")
    topic_verifier = None if stub else build_rework_verifier_runner(cfg, topic_stage_cfg, "topic_rework_verifier")
    embed = _StubEmbed() if stub else make_embed(cfg)
    conn = db_connect()
    scur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    slots = select_slots(scur, args, _source_status_for_writer(cfg, "topics", "RESERVED"))
    scur.close()
    if not slots:
        print("No topic-writer input slots match the selection."); return
    print(f"TOPICS: {len(slots)} slot(s){'  [STUB]' if stub else ''}{'  [DRY RUN]' if args.dry_run else ''}")
    results = []
    for slot in slots:
        try:
            results.append(process_topic(conn, topic_chat, topic_verifier, embed, cfg, slot, args.dry_run))
        except (ProviderError, ValueError) as e:
            conn.rollback(); print(f"  [error] {slot['slot_id']}: {e}")
            results.append({"slot_id": slot["slot_id"], "result": "ERROR", "error": str(e)})
    _summary(results); conn.close()


@contextlib.contextmanager
def _lease_heartbeat(job_id):
    """#310 §A (P0-b) — keep a running job's execution lease alive on an INDEPENDENT DB connection for
    the ENTIRE attempt, not merely at slot boundaries. A background daemon beats every
    TANAGHOM_TOPICGEN_HEARTBEAT_SECONDS (a fraction of the lease), so even an attempt that runs longer
    than one lease interval (verifier/dedup regenerations, a slow provider call) keeps extending its
    lease and is NEVER mistaken for abandoned and reclaimed. Stopped in finally, so heartbeats cease
    the instant the run ends (completion or failure) and the terminal lease clear takes effect."""
    eng = _load_engine()
    interval = float(os.environ.get("TANAGHOM_TOPICGEN_HEARTBEAT_SECONDS",
                                    str(max(1, eng.TOPIC_GENERATION_LEASE_SECONDS // 5))))
    stop = threading.Event()
    hb = {"conn": db_connect()}                  # mutable holder so a broken connection can be REPLACED

    def _beat():
        consecutive_fail = 0
        try:
            while not stop.wait(interval):
                try:
                    eng.heartbeat_topic_generation_job(hb["conn"], job_id)
                    consecutive_fail = 0
                except Exception as e:           # noqa: BLE001 — NEVER kill the run, but NEVER silently
                    # lose the lease either. A statement/transaction error can leave the connection
                    # aborted; if every later beat then failed, the lease would expire and a recovery
                    # worker could reclaim a still-running job. So: recover the transaction, and if the
                    # connection is broken/closed (or rollback fails), REPLACE it before the next beat.
                    consecutive_fail += 1
                    recovered = False
                    try:
                        hb["conn"].rollback()
                        recovered = not bool(getattr(hb["conn"], "closed", 0))
                    except Exception:            # noqa: BLE001
                        recovered = False
                    if not recovered:
                        try: hb["conn"].close()
                        except Exception: pass    # noqa: BLE001
                        try:
                            hb["conn"] = db_connect()
                        except Exception:         # noqa: BLE001 — next beat retries the reconnect
                            pass
                    # bounded, NON-SECRET operational signal (exception class + counter only).
                    print(f"[heartbeat] job {job_id}: beat failed ({type(e).__name__}); "
                          f"{'recovered txn' if recovered else 'reconnected'}; consecutive={consecutive_fail}")
        finally:
            try: hb["conn"].close()
            except Exception: pass                # noqa: BLE001

    t = threading.Thread(target=_beat, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set(); t.join(timeout=5)


def run_stage2a_topic_job(cfg, job_id):
    """#310 Stage 2A — run ONE durable Topic-generation job over its accepted portfolio.

    Reuses the EXISTING process_topic writer (the single shared stub+live path) — no second
    generation mechanism. Idempotent recovery is structural: process_topic advances a slot to
    TOPIC_PROPOSED, so a re-run only picks up slots still at SCHEDULE_APPROVED — already-generated
    Topic identities are never recreated (a genuine retry appends a new revision under the same
    topic_id). Records exact §E provenance per attempt and advances truthful job state.

    STUB by default; the live path needs an operator-gated key and is never exercised here.
    """
    eng = _load_engine()
    stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
    topic_stage_cfg = cfg["models"]["topic_hook"]
    topic_chat = _StubRunner() if stub else build_stage_runner(cfg["providers"], topic_stage_cfg, "topic_hook")
    topic_verifier = None if stub else build_rework_verifier_runner(cfg, topic_stage_cfg, "topic_rework_verifier")
    embed = _StubEmbed() if stub else make_embed(cfg)
    conn = db_connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM generation_job WHERE job_id=%s", (job_id,))
    job = cur.fetchone()
    if not job:
        cur.close(); conn.close(); raise ValueError(f"no such generation_job {job_id}")

    # #360 — FAIL CLOSED ON A WRONG-STAGE JOB, BEFORE THE CLAIM BELOW.
    #
    # This runner fetches then claims, so without this check the claim would already have stamped
    # status/lease/heartbeat/claimed_by onto a Script attempt before anything noticed the mismatch —
    # and the Topic writer would then run against it, producing nothing and writing Topic-shaped
    # terminal state over a Script job the real dispatcher could no longer claim.
    #
    # The SQL predicates on pending/claim make that unreachable via the drain; this assertion closes
    # DIRECT invocation, and it is placed before the claim so refusal costs no mutation at all.
    # Resources are released on this path exactly as on the two branches around it.
    if job.get("stage") != "topic":
        cur.close(); conn.close()
        return {"job_id": str(job_id), "status": "skipped",
                "reason": f"wrong stage: this runner executes stage='topic' only, job is "
                          f"stage={job.get('stage')!r} — refused before claim"}

    # EXACTLY-ONCE claim (P0-1): atomically transition queued->running. If we do not win the claim the
    # job was already claimed/running/completed — a replayed or duplicated dispatch — so we do nothing
    # and never launch a second writer over the same job.
    if not eng.claim_topic_generation_job(conn, job_id, worker="run_stage2a"):
        cur.close(); conn.close()
        return {"job_id": str(job_id), "status": "skipped",
                "reason": "not claimable (already claimed+alive or completed) — no double launch"}

    # Use the policy identity PINNED on the job at enqueue — NEVER re-resolve the currently-active one.
    # A generation-policy change after acceptance must not alter this job's novelty/allocation behaviour.
    policy = eng.get_topic_generation_policy_by_id(cur, job["topic_generation_policy_id"])

    # Accepted population still awaiting generation = SCHEDULE_APPROVED slots. A retry of a partial job
    # re-enters here and picks up ONLY the remaining SCHEDULE_APPROVED slots — already-generated
    # (TOPIC_PROPOSED) slots are never regenerated.
    cur.execute("""SELECT * FROM slot WHERE round_id=%s AND status='SCHEDULE_APPROVED'
                    ORDER BY day, time_uae, slot_id""", (job["round_id"],))
    slots = cur.fetchall()
    # P0-b: the lease is kept alive INDEPENDENTLY for the whole run (a background keeper on its own
    # connection), so a single attempt exceeding one lease interval is never stolen. NOT per-slot.
    with _lease_heartbeat(job_id):
        for slot in slots:
            try:
                # #310 §B / #268 — build a bounded, explainable novelty brief from Tanaghom-owned Topic
                # history for THIS slot, pre-seed the first generation with it, and persist exactly which
                # historical Topics fed it. #184's post-generation semantic dedup remains the final net.
                bcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                novelty = eng.build_novelty_brief(bcur, slot, policy, tenant_id=job.get("tenant_id", "default"))
                bcur.close()
                # #310 §E (P1-3) — provenance is written INSIDE process_topic's transaction via this hook,
                # atomically with the Topic insert + slot advance. The hook opens a RealDict cursor on the
                # SAME connection (shared transaction) and process_topic's single commit commits both;
                # record_topic_provenance is idempotent (ON CONFLICT), so a re-drive never duplicates.
                def _persist(_wcur, _tid, _rev, _novelty=novelty):
                    # Resolve only AFTER generation. StageRunner updates `.model` on each successful
                    # provider call, so this records the route that actually served this Topic rather
                    # than a pre-call configured preference (or the old schema-mismatched `unknown`).
                    resolved_provider, resolved_model = _resolved_execution_identity(topic_chat)
                    pcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    eng.record_topic_provenance(pcur, _tid, _rev, job, policy["policy_id"],
                                                resolved_provider, resolved_model,
                                                actor=job["actor"], novelty=_novelty)
                    pcur.close()
                process_topic(conn, topic_chat, topic_verifier, embed, cfg, slot,
                              dry_run=False, novelty=novelty, on_persist=_persist,
                              repetition_policy=job.get("repetition_policy_snapshot"))
            except Exception as e:                   # noqa: BLE001 — fail CLOSED per slot (P1-3):
                # ANY failure in the attempt (generation, persist, OR the atomic provenance hook) rolls
                # the WHOLE attempt back. Because provenance is written in process_topic's transaction,
                # a provenance failure leaves NO TOPIC_PROPOSED slot behind — the slot stays
                # SCHEDULE_APPROVED and is picked up truthfully by a later run/retry. Never a generated
                # Topic without exact provenance; never a job-crashing exception escaping the loop.
                conn.rollback()
                print(f"  [error] {slot['slot_id']}: {e}")

    # CUMULATIVE, CANONICAL counts (P1-4): done = provenance rows for THIS job (one per generated
    # attempt, guaranteed unique + atomic with the Topic), NOT a per-run local counter. So a partial
    # job (N) plus a retry that completes M more reports N+M, never M. total is the durable accepted
    # population fixed at enqueue; the remainder is what still failed to generate.
    ccur = conn.cursor()
    ccur.execute("SELECT count(*) FROM topic_provenance WHERE job_id=%s", (job_id,))
    done = ccur.fetchone()[0]
    ccur.close()
    total = job["slots_total"] or 0
    remaining = max(0, total - done)
    final = "completed" if total > 0 and done >= total else "partial" if done > 0 else "failed"
    err = None if remaining == 0 else {"remaining_slots": remaining,
                                       "reason": "one or more accepted slots are not yet generated"}
    eng.set_generation_job_state(conn, job_id, status=final, done=done, failed=remaining, error=err)
    cur.close(); conn.close()
    return {"job_id": str(job_id), "status": final, "done": done, "failed": remaining, "total": total}


def run_governed_script_job(cfg, job_id, worker="script-drain"):
    """#362 — recover ONE durable Script attempt, fenced end to end.

    Claim first: the claim mints this tenure's `claim_token`, and NOT winning it means someone else
    owns the attempt — so we return without touching anything. There is no "check then run" window,
    because the claim IS the check and it is a single atomic statement.

    Execution consumes the attempt's own persisted manifest (#357), never a fresh selection, so a
    recovered run reproduces exactly the authorized work. Every authoritative write afterwards
    carries the tenure token, so if this worker is reclaimed mid-run its results cannot land.
    """
    eng = _load_engine()
    conn = eng.db_connect()
    try:
        job = eng.script_job_row(conn, job_id)
        if not job:
            return {"job_id": str(job_id), "status": "skipped", "reason": "no such script job"}
        if job.get("stage") != "script":
            # Mirror of #360's Topic-runner assertion, in the opposite direction: full bidirectional
            # isolation (correction F) means this runner refuses a Topic job just as firmly.
            return {"job_id": str(job_id), "status": "skipped",
                    "reason": f"wrong stage: this runner executes stage='script' only, job is "
                              f"stage={job.get('stage')!r} — refused before claim"}

        # Check and claim under ONE lock: the decision to claim and the claim itself must not be
        # separable by a concurrent shutdown. Held across these two statements only.
        with SCRIPT_CLAIM_GATE:
            if script_drain_is_shutting_down():
                # The last moment at which declining costs nothing: no tenure has been taken, so
                # there is no lease to hold, release, or falsely terminalise.
                return {"job_id": str(job_id), "status": "skipped",
                        "reason": "shutdown in progress — no new Script tenure claimed"}
            token = eng.claim_script_generation_job(conn, job_id, worker=worker)
            if token:
                conn.commit()   # the tenure is durable before the gate is released
        if not token:
            return {"job_id": str(job_id), "status": "skipped",
                    "reason": "not claimable (owned by a live tenure, or terminal) — no double launch"}

        manifest = eng.script_attempt_manifest_of(conn, job_id)
        if not manifest:
            # Correction A/I: immutable truth is missing. Report it as a stable typed outcome; do not
            # rebuild the manifest, re-resolve configuration, or invent identity.
            eng.finish_script_generation_job(conn, job_id, done=0, failed=0,
                                             error_detail={"reason": "manifest_missing"},
                                             worker=worker, claim_token=token)
            return {"job_id": str(job_id), "status": "blocked", "reason": "manifest_missing"}

        # Heartbeat on its OWN connection for the life of the run, so a long writer pass cannot lose
        # a lease it is actively honouring. Ownership loss stops the keeper immediately.
        stop = threading.Event()
        lost = {"flag": False}

        def _keep():
            hb = eng.db_connect()
            try:
                while not stop.wait(eng.SCRIPT_HEARTBEAT_SECONDS):
                    if not eng.heartbeat_script_generation_job(hb, job_id, worker, token):
                        lost["flag"] = True          # reclaimed or terminalised: stand down
                        return
            except Exception:                        # noqa: BLE001 — the fence, not the keeper, is authoritative
                lost["flag"] = True
            finally:
                hb.close()

        keeper = threading.Thread(target=_keep, daemon=True)
        keeper.start()
        try:
            run_scripts(cfg, _GovernedScriptArgs(job["round_id"], manifest, job_id,
                                                claim_token=token, worker=worker))
        finally:
            stop.set()
            keeper.join(timeout=5)

        res = eng.record_script_generation_results(conn, job_id, worker=worker, claim_token=token)
        if res.get("fenced_out"):
            # Correction E: ownership was lost while we ran. We are non-authoritative — say so, and
            # do NOT release the lease or write terminal state, so the current owner is undisturbed.
            return {"job_id": str(job_id), "status": "skipped",
                    "reason": "ownership lost during execution — results not committed"}
        return {"job_id": str(job_id), "status": res.get("status"), "linked": res.get("linked")}
    finally:
        conn.close()


class _GovernedScriptArgs:
    """argparse-compatible shim carrying the attempt's pinned manifest into the writer."""

    def __init__(self, round_id, manifest, job_id, claim_token=None, worker=None):
        self.round = round_id
        self.slot_ids = None
        self.distinct_pillars = False
        self.limit = None
        self.dry_run = False
        self.manifest = manifest
        self.job_id = job_id
        self.claim_token = claim_token
        self.worker = worker


# #362 correction E / J10 — the SHUTDOWN BOUNDARY for Script recovery.
#
# One process-wide event, set by the host when shutdown begins. Its contract is narrow and
# deliberate:
#   * BEFORE EVERY CLAIM the drain checks it and stops. No new Script work is taken once shutdown
#     has started, so a shutting-down process cannot acquire a tenure it may not be able to finish.
#   * WORK ALREADY RUNNING IS NOT INTERRUPTED and is NEVER falsely terminalised. A job in flight
#     keeps its lease; if this process dies before finishing, the lease simply expires and another
#     worker reclaims it through the normal fenced path. Marking it failed on the way out would
#     invent a terminal state for work whose outcome nobody knows.
#   * OWNERSHIP IS NEVER FORCE-RELEASED. Releasing a lease while this process might still commit
#     would hand a live tenure to a second worker — the fence protects the writes, but the correct
#     behaviour is to let the lease expire rather than create the race at all.
#   * The wait is BOUNDED, so shutdown cannot block the Topic and rework passes that share this
#     recovery owner.
SCRIPT_DRAIN_SHUTDOWN = threading.Event()

# #362 correction — the LINEARIZATION BOUNDARY between the shutdown check and the SQL claim.
#
# An `is_set()` test followed by a claim is a check-then-act race: shutdown can be signalled in the
# window between them, and a tenure is taken by a process that has already begun shutting down. The
# flag alone cannot close that window no matter where it is read, because the window is between the
# read and the write.
#
# This lock makes the pair atomic with respect to shutdown. Both sides take it: the claim path holds
# it across check AND claim, and `begin_script_drain_shutdown` holds it while setting the flag. The
# two possible orderings are therefore the only two outcomes, and both are safe:
#   shutdown first -> the claim observes the flag and refuses; no tenure exists.
#   claim first    -> shutdown waits for the claim to COMPLETE, so it acts on a fully-formed tenure
#                     with a live lease rather than on a half-built one; that tenure then finishes
#                     or has its lease expire and is reclaimed through the fenced path.
# It is held only across the claim — never across the writer's execution — so shutdown is never
# blocked behind a long generation run.
SCRIPT_CLAIM_GATE = threading.RLock()


def begin_script_drain_shutdown():
    """Signal that no further Script work may be claimed. Idempotent; safe from any thread.

    Takes SCRIPT_CLAIM_GATE so the signal cannot land in the middle of a check-then-claim sequence:
    it either precedes a claim's check (which then refuses) or follows a claim's completion.
    """
    with SCRIPT_CLAIM_GATE:
        SCRIPT_DRAIN_SHUTDOWN.set()


def reset_script_drain_shutdown():
    """Clear the signal. Exists for deterministic tests and host restart, not for normal operation."""
    SCRIPT_DRAIN_SHUTDOWN.clear()


def script_drain_is_shutting_down():
    return SCRIPT_DRAIN_SHUTDOWN.is_set()


def dispatch_pending_script_generation(cfg, limit=None):
    """#362 — the BOUNDED Script recovery pass for the shared recovery owner.

    Bounded by design (correction D): it mirrors the rework drain's finite batch rather than the
    Topic drain, which selects with no LIMIT and so could let one round's backlog monopolise a
    recovery cycle. Each job is isolated in its own try, so a poisoned row cannot stop the rest of
    the pass — nor the Topic and rework passes that share this owner.
    """
    if script_drain_is_shutting_down():
        return []                                  # shutdown began: take nothing new
    eng = _load_engine()
    conn = eng.db_connect()
    try:
        pending = eng.pending_script_generation_jobs(conn, limit=limit)
    finally:
        conn.close()
    results = []
    for j in pending:
        # Re-checked per job, not once per pass: shutdown can begin midway through a batch, and the
        # guarantee is "no new CLAIM after shutdown", not "no new pass".
        if script_drain_is_shutting_down():
            break
        try:
            results.append(run_governed_script_job(cfg, j["job_id"]))
        except Exception as e:                        # noqa: BLE001 — isolate per job
            print(f"  [script-drain] {j['job_id']}: {type(e).__name__}: {e}")
            results.append({"job_id": j["job_id"], "status": "error", "reason": str(e)[:160]})
    return results


def dispatch_pending_topic_generation(cfg, round_id=None):
    """#310 §A — the durable post-commit DISPATCH: run every QUEUED Topic-generation job exactly once.

    Reads the queued jobs (optionally scoped to one round) and runs each through run_stage2a_topic_job,
    which CLAIMS the job atomically — so a job launched twice (the post-commit handoff plus a later
    recovery drain of an orphaned queued job) runs exactly once. Never launches a completed/running
    job. This is what turns Schedule acceptance's queued job into populated Topics without a second
    trigger and without a provider call inside the acceptance transaction."""
    eng = _load_engine()
    conn = db_connect()
    try:
        pending = eng.pending_topic_generation_jobs(conn, round_id=round_id)
    finally:
        conn.close()
    results = []
    for j in pending:
        results.append(run_stage2a_topic_job(cfg, j["job_id"]))
    return results


def run_scripts(cfg, args):
    script_stage_cfg = cfg["models"]["script"]
    stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
    script_chat = _StubRunner() if stub else build_stage_runner(cfg["providers"], script_stage_cfg, "script")
    script_verifier = None if stub else build_rework_verifier_runner(cfg, script_stage_cfg, "script_rework_verifier")
    conn = db_connect()
    scur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # #357 — GOVERNED PATH: when an attempt manifest is supplied, it is an EXECUTABLE INPUT CONTRACT,
    # not descriptive metadata. The pinned (slot_id, topic_id, topic_revision) tuples ARE the work set.
    #
    # WHY THIS MATTERS. The legacy path below re-derives its own inputs from `select_slots` against the
    # live configured status. That means an attempt authorized against one input set could execute
    # against a different one if configuration or the slot population moved in between — the exact
    # silent reinterpretation this directive forbids. When a manifest is present we neither reselect
    # slots nor re-resolve live configuration: we load precisely the pinned rows, in pinned order, and
    # refuse if any has moved.
    manifest = getattr(args, "manifest", None)
    if manifest:
        pinned = manifest.get("items") or []
        ids = [i["slot_id"] for i in pinned]
        scur.execute("SELECT * FROM slot WHERE slot_id = ANY(%s) ORDER BY array_position(%s, slot_id)",
                     (ids, ids))
        slots = scur.fetchall()
        scur.close()
        if len(slots) != len(pinned):
            print(f"[governed] manifest pins {len(pinned)} slot(s) but {len(slots)} resolved — refusing.")
            return
        # Bind each slot to its pinned Topic revision so process_script cannot silently consume a newer
        # one; the pin is consumed, not merely recorded beside the work.
        by_id = {i["slot_id"]: i for i in pinned}
        for sl in slots:
            sl["_pinned_topic_revision"] = by_id[sl["slot_id"]]["topic_revision"]
            sl["_pinned_topic_id"] = by_id[sl["slot_id"]]["topic_id"]
            # the attempt this work belongs to, carried to the persistence transaction
            sl["_attempt_job_id"] = getattr(args, "job_id", None)
            sl["_attempt_manifest"] = manifest
            sl["_attempt_claim_token"] = getattr(args, "claim_token", None)
            sl["_attempt_worker"] = getattr(args, "worker", None)
    else:
        slots = select_slots(scur, args, _source_status_for_writer(cfg, "scripts", "TOPIC_APPROVED"))
        scur.close()
    if not slots:
        print("No script-writer input slots to process (approve topics first)."); return
    print(f"SCRIPTS: {len(slots)} approved topic(s){'  [STUB]' if stub else ''}{'  [DRY RUN]' if args.dry_run else ''}")
    results = []
    for slot in slots:
        try:
            results.append(process_script(conn, script_chat, script_verifier, cfg, slot, args.dry_run))
        except (ProviderError, ValueError) as e:
            conn.rollback(); print(f"  [error] {slot['slot_id']}: {e}")
            results.append({"slot_id": slot["slot_id"], "result": "ERROR", "error": str(e)})
    _summary(results); conn.close()


def rework_round(cfg, mode, round_id=None, dry_run=False, quiet=False):
    """Co-creation loop (callable from the CLI AND the API trigger): re-run the relevant agent
    for CHANGES_REQUESTED slots (optionally scoped to round_id), injecting the reviewer's saved
    comment as the rework directive -> v2 (prior version kept = history). v2 returns to the
    review status for re-review. Returns the results list. TANAGHOM_WRITER_STUB=1 -> deterministic
    offline writer (tests)."""
    gate_stage, changes_status = _gate_for_rework(cfg, mode)
    conn = db_connect()
    scur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    rev_table = "topic" if mode == "topic" else "script"
    slots = select_rework(scur, gate_stage, changes_status, rev_table, round_id=round_id)
    scur.close()
    if not slots:
        conn.close()
        return []
    stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
    if not quiet:
        print(f"REWORK ({mode}): {len(slots)} slot(s){'  [STUB]' if stub else ''}"
              f"{'  [DRY RUN]' if dry_run else ''}")
    topic_chat = topic_verifier = script_chat = script_verifier = embed = None
    if mode == "topic":
        topic_stage_cfg = cfg["models"]["topic_hook"]
        topic_chat = _StubRunner() if stub else build_stage_runner(
            cfg["providers"], topic_stage_cfg, "topic_hook")
        topic_verifier = None if stub else build_rework_verifier_runner(
            cfg, topic_stage_cfg, "topic_rework_verifier")
        embed = _StubEmbed() if stub else make_embed(cfg)
    else:
        script_stage_cfg = cfg["models"]["script"]
        script_chat = _StubRunner() if stub else build_stage_runner(
            cfg["providers"], script_stage_cfg, "script")
        script_verifier = None if stub else build_rework_verifier_runner(
            cfg, script_stage_cfg, "script_rework_verifier")
    results = []
    for slot in slots:
        note, rev = slot["rework_note"], slot["next_revision"]
        if not quiet:
            print(f"\n>>> rework {slot['slot_id']} v{rev} — feedback: {note}")
        try:
            if mode == "topic":
                r = process_topic(conn, topic_chat, topic_verifier, embed, cfg, slot, dry_run, feedback=note, revision=rev)
            else:
                r = process_script(conn, script_chat, script_verifier, cfg, slot, dry_run, feedback=note, revision=rev)
            results.append(r)
        except (ProviderError, ValueError) as e:
            conn.rollback()
            if not quiet:
                print(f"  [error] {slot['slot_id']}: {e}")
            results.append({"slot_id": slot["slot_id"], "result": "ERROR", "error": str(e)})
    conn.close()
    return results


def rework_one(cfg, mode, slot_id, comment, dry_run=False, quiet=True, actor="system"):
    """Rework a SINGLE slot from its current head with an explicit comment (the 'rework from this
    version' action: restore vN made it the head, this regenerates from it). Returns the result.

    #313 — a topic rework records EXACT, JOB-LESS provenance (record_rework_provenance): job_id NULL,
    the effective actor, and the resolved provider/model/route that ACTUALLY ran. No live provider is
    called in this directive, so a stub rework records the stub truthfully; nothing is fabricated."""
    eng = _load_engine()
    conn = db_connect()
    scur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    scur.execute("SELECT * FROM slot WHERE slot_id=%s", (slot_id,))
    slot = scur.fetchone()
    rev_table = "topic" if mode == "topic" else "script"
    scur.execute(f"SELECT coalesce(max(revision),0)+1 AS r FROM {rev_table} WHERE slot_id=%s", (slot_id,))
    rev = scur.fetchone()["r"]
    scur.close()
    if not slot:
        conn.close(); return None
    stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
    try:
        if mode == "topic":
            topic_stage_cfg = cfg["models"]["topic_hook"]
            chat = _StubRunner() if stub else build_stage_runner(
                cfg["providers"], topic_stage_cfg, "topic_hook")
            verifier = None if stub else build_rework_verifier_runner(
                cfg, topic_stage_cfg, "topic_rework_verifier")
            embed = _StubEmbed() if stub else make_embed(cfg)
            # Exact, job-less rework provenance for the resulting revision — recorded in the SAME
            # transaction as the topic INSERT (atomic).
            def _rework_persist(_wcur, _tid, _rev):
                # #321 R8 — the ACTUAL served provider/model from the runner (fallback-aware), or NULL
                # for genuine absence; never the configured route preference.
                _rw_provider, _rw_model = _resolved_execution_identity(chat)
                eng.record_rework_provenance(_wcur, _tid, _rev, slot_id, actor,
                                             resolved_provider=_rw_provider, resolved_model=_rw_model,
                                             execution_route="manual_rework")
            r = process_topic(conn, chat, verifier, embed, cfg, slot, dry_run, feedback=comment,
                              revision=rev, on_persist=_rework_persist)
        else:
            script_stage_cfg = cfg["models"]["script"]
            chat = _StubRunner() if stub else build_stage_runner(
                cfg["providers"], script_stage_cfg, "script")
            verifier = None if stub else build_rework_verifier_runner(
                cfg, script_stage_cfg, "script_rework_verifier")
            r = process_script(conn, chat, verifier, cfg, slot, dry_run, feedback=comment, revision=rev)
    finally:
        conn.close()
    return r


@contextlib.contextmanager
def _rework_op_heartbeat(op_id, claim_token):
    """#313 P1-1 — renew the operation's lease on an INDEPENDENT connection for the whole generation,
    fenced by claim_token, reusing the Stage 2A rollback/RECONNECT pattern: a transient heartbeat DB
    failure recovers the transaction and, if the connection is broken, REPLACES it before the lease can
    expire — so a slow generation is never wrongly reclaimed. The moment ownership transfers (a new claim
    minted a new token) the beat stops and the fenced completion rejects this stale worker. The beat
    thread OWNS its connection (closes it in its own finally); teardown JOINs the thread before returning,
    so there is no close/use race."""
    eng = _load_engine()
    # #313 review #5 — when the heartbeat interval is unset, derive it from the SAME runtime-resolved
    # lease that claim/renewal use (not the frozen import-time constant), so a short runtime lease keeps
    # the beat well ahead of expiry instead of pinning the interval to the 120s default.
    interval = float(os.environ.get("TANAGHOM_REWORK_HEARTBEAT_SECONDS",
                                    str(max(1, eng._resolve_rework_lease_seconds() / 4))))
    _kill_after = int(os.environ.get("TANAGHOM_REWORK_TEST_HB_KILL", "0"))   # test hook: induce a conn failure
    stop = threading.Event()
    hb = {"conn": db_connect()}                  # mutable holder so a broken connection can be REPLACED

    def _beat():
        beats = 0
        try:
            while not stop.wait(interval):
                try:
                    if not eng.heartbeat_rework_operation(hb["conn"], op_id, claim_token):
                        break                    # ownership lost/completed — stop; fenced complete rejects us
                    beats += 1
                    if _kill_after and beats == _kill_after:
                        hb["conn"].close()       # test hook: simulate a transient heartbeat connection failure
                except Exception as e:           # noqa: BLE001 — recover the txn; REPLACE a broken connection
                    recovered = False
                    try:
                        hb["conn"].rollback()
                        recovered = not bool(getattr(hb["conn"], "closed", 0))
                    except Exception:            # noqa: BLE001
                        recovered = False
                    if not recovered:
                        try:
                            hb["conn"].close()
                        except Exception:        # noqa: BLE001
                            pass
                        try:
                            hb["conn"] = db_connect()   # REPLACE the broken connection before the next beat
                        except Exception:        # noqa: BLE001 — next beat retries the reconnect
                            pass
                    print(f"[rework-heartbeat] op {op_id}: beat failed ({type(e).__name__}); "
                          f"{'recovered txn' if recovered else 'reconnected'}")
        finally:
            try:
                hb["conn"].close()
            except Exception:                    # noqa: BLE001
                pass

    t = threading.Thread(target=_beat, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=5)                        # JOIN before returning (the thread closes its own conn)


def run_rework_operation(cfg, op_id):
    """#313 P1-B/P1-1/P1-2 — the durable rework WORKER. CLAIMS the operation exactly once (minting an
    ownership claim_token), keeps its lease alive via a fenced heartbeat, regenerates from the operation's
    exact RESTORED source revision, and records provenance + the operation's COMPLETION (fenced by the
    token) in ONE transaction with the generated topic revision. A stale worker (lease expired, op
    reassigned) can neither heartbeat nor complete — its completion matches zero rows and RAISES, rolling
    back its generation — so exactly one revision/provenance results. A crash before the commit leaves the
    op resumable; a completed op is never re-driven."""
    eng = _load_engine()
    conn = db_connect()
    try:
        op = eng.claim_rework_operation(conn, op_id)
        if not op:                          # already completed, or running under a live lease elsewhere
            return None
        slot_id, comment, actor = op["slot_id"], op["comment"], op["actor"]
        token, restored = op["claim_token"], op["restored_revision"]
        # #367 R3.3 — dispatch by the op's PERSISTED artifact so a Script rework reads/writes SCRIPT
        # revisions and SCRIPT provenance. The op row (031) stored `artifact` at begin; before this,
        # this worker ignored it and always regenerated a topic, so a governed Script rework silently
        # produced topic content into the slot. The claim-token/lease/atomic-completion machinery is
        # reused UNCHANGED — only the generation body branches.
        artifact = op.get("artifact") or "topic"
        _art_tbl = "topic" if artifact == "topic" else "script"
        scur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        scur.execute("SELECT * FROM slot WHERE slot_id=%s", (slot_id,))
        slot = scur.fetchone()
        scur.execute(f"SELECT coalesce(max(revision),0) AS h FROM {_art_tbl} WHERE slot_id=%s", (slot_id,))
        head = scur.fetchone()["h"]
        scur.close()
        # #313 P1-2 — the current head MUST still be the restored source (the active-op fence guarantees
        # it; verify defensively and fail closed/resumable if a mutation ever slipped through, so a rework
        # never generates from a silently-changed source). Checked against the ARTIFACT's own head.
        if head != restored:
            eng.fail_rework_operation(conn, op_id, token,
                                      f"rework source changed: head {head} != restored {restored}")
            raise RuntimeError(f"rework source changed for {slot_id} (head {head} != restored {restored})")
        rev = restored + 1
        stub = bool(os.environ.get("TANAGHOM_WRITER_STUB"))
        embed = _StubEmbed() if stub else make_embed(cfg)
        if artifact == "topic":
            topic_stage_cfg = cfg["models"]["topic_hook"]
            chat = _StubRunner() if stub else build_stage_runner(cfg["providers"], topic_stage_cfg, "topic_hook")
            verifier = None if stub else build_rework_verifier_runner(cfg, topic_stage_cfg, "topic_rework_verifier")

            def _persist(_wcur, _tid, _rev):
                # provenance + FENCED operation completion, in the SAME transaction as the generated
                # topic revision — a stale token makes complete raise, rolling the generation back.
                # #321 R8 — the ACTUAL served provider/model, resolved AFTER generation, never the pref.
                _prov, _model = _resolved_execution_identity(chat)
                eng.record_rework_provenance(_wcur, _tid, _rev, slot_id, actor,
                                             resolved_provider=_prov, resolved_model=_model,
                                             execution_route="manual_rework")
                eng.complete_rework_operation(_wcur, op_id, token, _rev, controller=actor)
        else:
            # SCRIPT rework — the same claim-token-fenced completion, over the script generation body.
            script_stage_cfg = cfg["models"]["script"]
            chat = _StubRunner() if stub else build_stage_runner(cfg["providers"], script_stage_cfg, "script")
            verifier = None if stub else build_rework_verifier_runner(cfg, script_stage_cfg,
                                                                      "script_rework_verifier")

            def _persist(_wcur, _sid, _rev):
                # `_sid` is the new script_id (process_script passes str(script_id)). Bind SCRIPT rework
                # provenance and complete the fenced op in the SAME transaction as the script revision;
                # a stale token makes complete_rework_operation match zero rows and raise, rolling the
                # whole generation back (amendment 6).
                _prov, _model = _resolved_execution_identity(chat)
                eng.record_script_rework_provenance(_wcur, _sid, _rev, slot_id, actor,
                                                    resolved_provider=_prov, resolved_model=_model,
                                                    execution_route="manual_rework")
                eng.complete_rework_operation(_wcur, op_id, token, _rev, controller=actor)
        try:
            with _rework_op_heartbeat(op_id, token):
                _delay = float(os.environ.get("TANAGHOM_REWORK_TEST_DELAY_SECONDS", "0"))
                if _delay:                  # test hook: make the generation EXCEED the nominal lease
                    time.sleep(_delay)
                if artifact == "topic":
                    return process_topic(conn, chat, verifier, embed, cfg, slot, dry_run=False,
                                         feedback=comment, revision=rev, on_persist=_persist)
                return process_script(conn, chat, verifier, cfg, slot, dry_run=False,
                                      feedback=comment, revision=rev, on_persist=_persist)
        except Exception as e:              # noqa: BLE001
            # #319 P0 — ROLL BACK FIRST, then record failure on a SEPARATE, CLEAN connection.
            # complete_rework_operation() raises a plain GateError on a stale claim_token: that is a
            # Python raise, NOT a SQL error, so the generation transaction is left OPEN and still
            # COMMITTABLE — not aborted. Before #319, the handler called fail_rework_operation() on
            # THIS connection, whose unconditional conn.commit() then committed the whole rejected
            # generation (topic revision, slot advance, gate_decision deletions, audit rows,
            # provenance) even though the fenced completion matched zero rows. The rollback below is
            # what makes the rejection real; the clean connection is what keeps it real, because no
            # failure-state write may ever share a transaction with generation effects it rejected.
            _rollback_quietly(conn)
            _record_rework_failure_cleanly(op_id, token, e)
            raise
    finally:
        conn.close()


def _rollback_quietly(conn):
    """#319 — discard the generation transaction. A rollback failure must never mask the original
    generation error, so it is swallowed: the connection is closed by the caller's finally either
    way, and an unrolled-back transaction dies with it rather than committing."""
    try:
        conn.rollback()
    except Exception:                        # noqa: BLE001
        pass


def _record_rework_failure_cleanly(op_id, token, error):
    """#319 — persist the operation's failure state on a connection that carries NO generation work,
    so recording a failure cannot commit the generation it just rejected. The write stays fenced by
    claim_token: a stale worker matches zero rows and truthfully records NOTHING, which is correct —
    it no longer owns the operation, and the real owner's state must not be overwritten by a loser.
    A failure while recording the failure must not mask the generation error that caused it."""
    fconn = None
    try:
        fconn = db_connect()
        _load_engine().fail_rework_operation(fconn, op_id, token, error)
    except Exception as e:                   # noqa: BLE001
        print(f"[rework_op] {op_id}: failure-state recording failed: {e}")
    finally:
        if fconn is not None:
            try:
                fconn.close()
            except Exception:                # noqa: BLE001
                pass


def run_rework(cfg, args):
    results = rework_round(cfg, args.stage, round_id=args.round, dry_run=args.dry_run)
    if not results:
        print(f"No {args.stage} slots awaiting rework."); return
    _summary(results)


# ---------------------------------------------------------------------------
# bake-off mode — read-only, no DB writes
# ---------------------------------------------------------------------------
def run_bakeoff(cfg, args):
    providers = cfg["providers"]
    bo = cfg["bakeoff"]
    temp, maxt = bo.get("temperature", 0.8), bo.get("max_tokens", 2000)
    slot_ids = ([s.strip() for s in args.slot_ids.split(",")] if args.slot_ids else bo["slots"])

    # one-shot self-checks (no regeneration) so we see each model's raw behavior
    once = dict(cfg.get("writers", {}))
    once["hook_max_regenerations"] = 0
    once["script_max_regenerations"] = 0

    # optional --only filter (substring match on label/provider/model)
    writers = bo["writers"]
    if args.only:
        needle = args.only.lower()
        writers = [w for w in writers
                   if needle in f"{w['label']} {w['provider']} {w['model']}".lower()]

    # skip writers whose API key isn't set, with a clear notice
    active, skipped = [], []
    for w in writers:
        key_env = providers[w["provider"]].get("api_key_env") or ""
        if key_env and not runtime_secret_status(key_env)[0]:
            skipped.append((w["label"], f"{key_env} not configured"))
        else:
            active.append(w)

    conn = db_connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    slots = []
    for sid in slot_ids:
        cur.execute("SELECT * FROM slot WHERE slot_id=%s", (sid,))
        row = cur.fetchone()
        if row:
            cur.execute("SELECT * FROM hcs WHERE hcs_id=%s", (row["hcs_id"],))
            row["_hcs"] = cur.fetchone()
            cur.execute("SELECT * FROM lens WHERE lens_id=%s", (row["lens"],))
            row["_lens"] = cur.fetchone()
            slots.append(row)
    conn.close()

    print(f"\nBAKE-OFF — read-only, NO DB writes. temp={temp} max_tokens={maxt}")
    print(f"writers: {', '.join(w['label'] for w in active)}"
          + (f"   |   SKIPPED: {', '.join(f'{l} ({why})' for l,why in skipped)}" if skipped else ""))

    # execute grouped BY MODEL (keeps each local model loaded), collect by slot
    results = {s["slot_id"]: {} for s in slots}
    for w in active:
        client = ChatClient(providers[w["provider"]], w["model"],
                            w.get("temperature", temp), w.get("max_tokens", maxt),
                            w.get("params"), w.get("prompt_suffix", ""))
        for slot in slots:
            hcs, lens = slot["_hcs"], slot["_lens"]
            ex = exemplars_block(cfg, slot["pillar_code"])
            entry = {"hook": None, "wc": None, "violations": None, "open": None, "error": None}
            try:
                topic, status = generate_topic(client, slot, hcs, lens, once, [], ex)
                if status == "clarify":
                    entry["error"] = "NEEDS_STRATEGIC_CLARIFICATION"
                else:
                    entry["hook"] = topic["hook_text"]
                    entry["wc"] = word_count(topic["hook_text"])
                    entry["violations"] = topic.get("_hook_violations", [])
                    script, _ = generate_script(client, slot, hcs, lens, topic, once, ex)
                    entry["open"] = " ".join(script.get("script_ar", "").split())[:200]
            except (ProviderError, ValueError) as e:
                entry["error"] = str(e)[:160]
            results[slot["slot_id"]][w["label"]] = entry
            tag = (entry["error"] or (f"{entry['wc']}w "
                   + ("PASS" if not entry["violations"] else "FAIL")))
            print(f"  · {w['label']:<20} {slot['slot_id']}: {tag}")

    # ---- side-by-side report -------------------------------------------
    labels = [w["label"] for w in active]
    for slot in slots:
        hcs, lens = slot["_hcs"], slot["_lens"]
        print(f"\n{'='*100}\nSLOT {slot['slot_id']}  |  {slot['pillar_code']}  |  HCS "
              f"{hcs['hcs_id']} {hcs['name_en']}  |  lens {lens['lens_id']} {lens['name_en']}"
              f"  |  {slot['format']}\n{'='*100}")
        print("HOOKS  (CANON-013: 3–7 words · no greeting · no name · one person):")
        for lb in labels:
            e = results[slot["slot_id"]][lb]
            if e["hook"]:
                verdict = "PASS" if not e["violations"] else "FAIL " + ",".join(e["violations"])
                suffix = f"   (script error: {e['error'][:60]})" if e["error"] else ""
                print(f"  {lb:<20} {e['wc']}w  {verdict:<28} «{e['hook']}»{suffix}")
            elif e["error"]:
                print(f"  {lb:<20} [error] {e['error']}")
        print("\nSCRIPT OPENINGS (first ~200 chars):")
        for lb in labels:
            e = results[slot["slot_id"]][lb]
            print(f"  {lb:<20} {e['open'] or '—'}")

    # ---- summary matrix -------------------------------------------------
    print(f"\n{'='*100}\nHOOK-CHECK SUMMARY (passes / slots run)\n{'='*100}")
    for lb in labels:
        run = [results[s["slot_id"]][lb] for s in slots]
        ok = sum(1 for e in run if e["hook"] and not e["violations"])
        errs = sum(1 for e in run if e["error"])
        print(f"  {lb:<20} hooks_pass={ok}/{len(run)}   errors={errs}")
    if skipped:
        print("\nNOT RUN (missing key): " + "; ".join(f"{l} — {why}" for l, why in skipped))
    print("\nNO config committed, NO DB writes. Review and choose models.*.primary.")


def main():
    ap = argparse.ArgumentParser(description="Tanaghom Writers (M3/M4.1 two-stage)")
    ap.add_argument("mode", nargs="?", default="topics",
                    choices=["topics", "scripts", "rework", "bakeoff"])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--slot-ids", default=None, help="comma-separated slot ids")
    ap.add_argument("--round", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--distinct-pillars", action="store_true",
                    help="pick the first slot of each distinct pillar")
    ap.add_argument("--dry-run", action="store_true", help="generate + print, write nothing")
    ap.add_argument("--stage", default="topic", choices=["topic", "script"],
                    help="rework: which agent to re-run for sent-back slots")
    ap.add_argument("--only", default=None, help="bakeoff: run only writers matching this substring")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    {"topics": run_topics, "scripts": run_scripts,
     "rework": run_rework, "bakeoff": run_bakeoff}[args.mode](cfg, args)


if __name__ == "__main__":
    main()
