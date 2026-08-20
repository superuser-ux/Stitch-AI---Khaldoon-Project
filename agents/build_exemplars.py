#!/usr/bin/env python3
"""
Build the dialect exemplar bank from the real analytics exports.

Reads the IG + FB caption exports, ranks posts by engagement
(likes+shares+comments+saves, per the calibration doc), tags each to a pillar via
Arabic keyword heuristics, and writes the top exemplars per pillar to
methodology/voice/dialect_exemplars.json. The writer agents inject 3–5 of these
(matched to the slot's pillar) as few-shot voice anchors.

This is a curation aid: the JSON is committed and meant to be reviewed/edited by a
native editor. Re-run to refresh from new exports. Stdlib only.
"""
import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXPORTS = REPO / "data" / "analytics_exports"
OUT = REPO / "methodology" / "voice" / "dialect_exemplars.json"

SOURCES = [("IG", "Jan-01-2026_May-25-2026_Insta.csv"),
           ("FB", "May-29-2025_May-25-2026_FB.csv")]

PER_PILLAR = 5          # exemplars kept per pillar
MIN_LEN = 20            # ignore trivially short captions
SNIPPET = 240           # chars of the caption opening to keep

PILLAR_KEYWORDS = {
    "P1_SELF": ["توتر", "قلق", "خوف", "تقدير", "ثقة", "خجل", "عار", "تسويف",
                "احتراق", "إرهاق", "ارهاق", "وحدة", "هوية", "غضب", "حزن", "فقد",
                "سيطرة", "نفسك", "مشاعر", "ضغط", "ذاتك", "قيمتك", "طيبتك", "إرضاء",
                "الناس برأسك", "جواتك"],
    "P2_RELATIONSHIPS": ["زواج", "الزوج", "زوجة", "زوجتك", "جوزك", "مرتك", "شريك",
                         "شريكة", "العلاقة", "علاقتك", "الحب", "حبك", "خيانة",
                         "طلاق", "الحدود", "حماتك", "الصمت في العلاقة"],
    "P3_PARENTING": ["طفل", "طفلك", "ابنك", "بنتك", "ولدك", "الأبوة", "الأمومة",
                     "التربية", "تربية", "المراهق", "مراهق", "أولاد", "ولادك",
                     "أطفال", "ابنتك", "أمهات"],
    "P4_WORK": ["العمل", "الشغل", "شغلك", "المهنة", "الوظيفة", "وظيفتك", "المدير",
                "مشروع", "نجاح", "الطموح", "الانضباط", "الإنضباط", "مشغول",
                "وقتك", "فلوس", "رزق"],
    "P5_MEANING_ALLAH": ["الله", "ربنا", "الإيمان", "العبادة", "الصلاة", "الروح",
                         "التوكل", "الذنب", "الآخرة", "الموت", "الدعاء", "سبحان",
                         "الدنيا", "يا رب", "ربي", "وعود رباني", "الفراغ"],
}


def to_int(x):
    try:
        return int(float(str(x).replace(",", "").strip() or 0))
    except ValueError:
        return 0


def tag_pillar(text):
    scores = {p: sum(text.count(k) for k in kws) for p, kws in PILLAR_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def snippet(text):
    t = re.sub(r"\s+", " ", text).strip()
    return t[:SNIPPET]


def main():
    rows = []
    for src, fname in SOURCES:
        path = EXPORTS / fname
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                desc = (row.get("Description") or "").strip()
                if len(desc) < MIN_LEN:
                    continue
                eng = (to_int(row.get("Likes")) + to_int(row.get("Shares"))
                       + to_int(row.get("Comments")) + to_int(row.get("Saves")))
                rows.append({"text": snippet(desc), "engagement": eng,
                             "views": to_int(row.get("Views")), "source": src,
                             "pillar": tag_pillar(desc)})

    # de-duplicate by opening (cross-posted IG/FB winners), keep the higher engagement
    seen = {}
    for r in sorted(rows, key=lambda r: -r["engagement"]):
        key = r["text"][:60]
        if key not in seen:
            seen[key] = r
    uniq = list(seen.values())

    bank = {}
    for pillar in PILLAR_KEYWORDS:
        picks = sorted([r for r in uniq if r["pillar"] == pillar],
                       key=lambda r: -r["engagement"])[:PER_PILLAR]
        bank[pillar] = [{"text": r["text"], "engagement": r["engagement"],
                         "source": r["source"]} for r in picks]
    # general fallback = overall top, used when a pillar is thin
    bank["_general"] = [{"text": r["text"], "engagement": r["engagement"], "source": r["source"]}
                        for r in sorted(uniq, key=lambda r: -r["engagement"])[:PER_PILLAR]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {OUT.relative_to(REPO)}")
    for pillar, items in bank.items():
        print(f"  {pillar:<18} {len(items)} exemplars"
              + (f"  (top eng={items[0]['engagement']})" if items else "  (EMPTY)"))


if __name__ == "__main__":
    main()
