"""i18n / glossary loader (shared canonical catalog at repo `i18n/`).

Surfaces render business-lexicon labels from the glossary and copy from ui.json — never
inline strings or raw enum/code terms. The dashboard (TS) loads the SAME JSON files.
"""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "i18n"
_GLOSSARY = json.loads((_ROOT / "glossary.json").read_text(encoding="utf-8"))
_UI = json.loads((_ROOT / "ui.json").read_text(encoding="utf-8"))


def term(category: str, key: str, lang: str = "en") -> str:
    """A glossary label (status/decision/stage/flag/term/role). Falls back to the raw key."""
    entry = (_GLOSSARY.get(category) or {}).get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key


def gloss(category: str, key: str) -> str:
    """Bilingual 'العربية · English' rendering (Arabic-primary brand, bilingual surfaces)."""
    entry = (_GLOSSARY.get(category) or {}).get(key)
    if not entry:
        return key
    ar, en = entry.get("ar"), entry.get("en")
    return f"{ar} · {en}" if ar and en else (ar or en or key)


def t(key: str, lang: str = "en") -> str:
    """A UI/Telegram copy string by key. Falls back to the key."""
    entry = _UI.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key


def catalog() -> dict:
    """The whole catalog (glossary + ui) — served to the dashboard so every surface
    renders from ONE source."""
    return {"glossary": _GLOSSARY, "ui": _UI}
