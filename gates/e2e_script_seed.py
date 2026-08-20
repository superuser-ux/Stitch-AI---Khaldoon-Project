"""Seed/reset an isolated script-review round for Playwright browser validation.

Creates a small round already at DRAFT_ASSIGNED with topic + script rows present, then
opens the script_review gate so the dashboard can validate the real script-review surface
without depending on upstream generation.
"""
import os
import sys
import json

import psycopg2

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402

RID = "RSCR"
SLOTS = [
    {
        "slot_id": "RSCR-1",
        "pillar_code": "P1_SELF",
        "hcs_id": "1.1",
        "topic_angle": "Stress",
        "format": "Hero Reel",
        "model": None,   # #154 — no persisted attribution: the card must say "model not recorded"
        "needs_native_review": True,   # #157 — review-state signal, rendered SEPARATELY from the target context
        "hook_text": "الخوف بياكل قرارك اليوم",
        "script_ar": "نص السكربت الأول\n\n— سطر أخير",
        "structure": {
            "hook": "مش كل الضغط هو اللي بيكسرك من جوّا.",
            "body": "سمّي الإشارة اللي جسمك عم يكررها قبل ما ينهارك يومك بالكامل.",
            "turn": "أحياناً المشكلة مش في الشغل نفسه، بل في الطريقة اللي مخك صار يترجم فيها كل ضغط كأنه خطر.",
            "close": "إذا ما فهمت الإشارة بدري، الضغط بيصير هو اللي ياخد القرار عنك.",
        },
        "delivery_notes": "ابدأ بهدوء ثم شدد على الكلمات المفتاحية. اترك وقفة قصيرة بعد الهوك واستخدم نظرة مباشرة في سطر الإغلاق.",
        "delivery_check": {
            "metaphor": True,
            "scientific_truth": True,
            "scroll_stop_hook": True,
            "emotional_journey": True,
            "light_human_moment": True,
            "quran_or_hadith_organic": False,
            "unforgettable_final_line": True,
        },
        "final_line": "إذا ما فهمت الإشارة بدري، الضغط بيصير هو اللي ياخد القرار عنك.",
    },
    {
        "slot_id": "RSCR-2",
        "pillar_code": "P2_RELATIONSHIPS",
        "hcs_id": "2.1",
        "topic_angle": "A marriage that has lost its connection",
        "format": "Carousel",
        "model": "groq:llama-e2e",   # #154 — persisted provider:model label, surfaced verbatim
        "needs_native_review": False,  # #157 — no review-state signal; the target context still shows
        "hook_text": "الخوف بيوقفك عن المواجهة",
        "script_ar": "نص السكربت الثاني\n\n— سطر أخير",
        # #149 — a Carousel script emitted with the format's REGISTRY-DRIVEN structure keys
        # (production_rules.structure: slide_1…slide_7), the shape the writer now produces. The card
        # labels these from the registry (Hook / Concept Anchor / …), NOT the fixed 4-beat dict.
        "structure": {
            "slide_1": "العلاقة مش بتموت مرة وحدة، بتخفّ شوي شوي.",
            "slide_2": "سمّي المفهوم: الانفصال الصامت — الحضور الجسدي مع الغياب العاطفي.",
            "slide_3": "أمثلة من الواقع: وجبة عشا بصمت، رسائل بترد متأخر، ضحكة صارت نادرة.",
            "slide_4": "الخلاصة: كل علامة صغيرة هي إشارة لسه قابلة للإصلاح إذا انتبهتوا بدري.",
            "slide_5": "الجسر العملي: افتحوا محادثة وحدة بدون اتهام، بس سؤال صادق.",
            "slide_6": "الإغلاق ذو المعنى: المواجهة الصح مش فضيحة، هي محاولة ترجعوا تسمعوا بعض.",
            "slide_7": "دعوة للتأمل: إذا لسه في صدق، في باب ينفتح قبل ما ينغلق كل شيء.",
        },
        "delivery_notes": "ابدأ بنبرة حزينة ثابتة. خلي كل لوحة تحمل فكرة واحدة قصيرة مع انتقال نظيف، وانتهِ بجملة أمل واضحة.",
        "delivery_check": {
            "metaphor": True,
            "scientific_truth": False,
            "scroll_stop_hook": True,
            "emotional_journey": True,
            "light_human_moment": True,
            "quran_or_hadith_organic": False,
            "unforgettable_final_line": True,
        },
        "final_line": "إذا لسه في صدق، في باب ينفتح قبل ما ينغلق كل شيء.",
    },
    {
        # #177 — Hero Reel emitted WITH the managed 10-beat registry structure (60.viral.01), the
        # shape the writer produces now that the registry carries the client framework. The card
        # must label these from the registry with NO fallback/stale disclosure. (RSCR-1 stays the
        # OLD 4-beat hero script and must show the "older structure" disclosure instead.)
        "slot_id": "RSCR-3",
        "pillar_code": "P3_PARENTING",
        "hcs_id": "3.1",
        "topic_angle": "Raising without yelling",
        "format": "Hero Reel",
        "model": "groq:llama-e2e",
        "needs_native_review": False,
        "hook_text": "صوتك العالي بيربّي خوف مش احترام",
        "script_ar": "نص السكربت الثالث\n\n— سطر أخير",
        "structure": {
            "beat_1": "صوتك العالي ما بيربّي احترام، بيربّي خوف.",
            "beat_2": "لحظة وحدة: ولدك سكت مش لأنه اقتنع، لأنه خاف.",
            "beat_3": "القيمة: الطاعة اللي أساسها خوف بتختفي أول ما تغيب.",
            "beat_4": "القلب المعرفي: مش هو اللي ما بيسمع، إنت اللي صوتك صار الرسالة الوحيدة.",
            "beat_5": "الاقتباس: اللي بيتربّى على الصوت، بيتعلم يسمع الصوت مش الكلام.",
            "beat_6": "الاستعارة: الصراخ متل المنبّه، أول يوم بيصحّيك وبعدين بتتعود تكتمه.",
            "beat_7": "لقطة الواقع: بتناديه بهدوء ما بيرد، بتصرخ بيرد — هاي مش تربية، هاي تدريب.",
            "beat_8": "سطر الملكية: التغيير بيبدأ من نبرة صوتك إنت، مش من أذنه هو.",
            "beat_9": "الخطوة: جرب يوم كامل تحكي فيه بنفس النبرة اللي بتحب حدا يحكيك فيها.",
            "beat_10": "الختام: خفّض صوتك، بيعلا سمعك عنده.",
        },
        "delivery_notes": "نبرة هادئة حازمة من أول ثانية. وقفة قبل الاقتباس وبعده، والختام بصوت أخفض من البداية.",
        "delivery_check": {
            "metaphor": True,
            "scientific_truth": False,
            "scroll_stop_hook": True,
            "emotional_journey": True,
            "light_human_moment": True,
            "quran_or_hadith_organic": False,
            "unforgettable_final_line": True,
        },
        "final_line": "خفّض صوتك، بيعلا سمعك عنده.",
    },
    {
        # #177 — Pic + Caption is explicitly LEGACY in the registry (no client framework); its
        # generic 4-beat structure must be disclosed as legacy, never presented as a client framework.
        "slot_id": "RSCR-4",
        "pillar_code": "P1_SELF",
        "hcs_id": "1.1",
        "topic_angle": "Comparison fatigue",
        "format": "Pic + Caption",
        "model": None,
        "needs_native_review": False,
        "hook_text": "المقارنة سباق ما إله خط نهاية",
        "script_ar": "نص السكربت الرابع\n\n— سطر أخير",
        "structure": {
            "hook": "المقارنة سباق ما إله خط نهاية.",
            "body": "كل ما وصلت لحد ما، بيطلع حد أبعد — مش لأنك ناقص، لأن السباق نفسه وهم.",
            "turn": "المشكلة مش إنك بطيء، المشكلة إنك عم تركض بمضمار مش إلك.",
            "close": "اركض بمضمارك، وبطّل تقيس عمرك بساعة غيرك.",
        },
        "delivery_notes": "صورة ثابتة قوية والكابشن يحمل النص كامل بهدوء.",
        "delivery_check": {
            "metaphor": True,
            "scientific_truth": False,
            "scroll_stop_hook": True,
            "emotional_journey": True,
            "light_human_moment": False,
            "quran_or_hadith_organic": False,
            "unforgettable_final_line": True,
        },
        "final_line": "اركض بمضمارك، وبطّل تقيس عمرك بساعة غيرك.",
    },
]


def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
        cur.execute(f"DELETE FROM {tbl} WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RSCR-%%'")
    cur.execute("DELETE FROM slot WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()


def seed(conn):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
               pillar_distribution,format_distribution,status,tenant_id)
           VALUES (%s,'script-e2e',1,4,'["09:00","13:00","17:00","20:00"]','{}','{}','planning','e2e')""",
        (RID,),
    )
    for index, slot in enumerate(SLOTS, start=1):
        sid = slot["slot_id"]
        time_uae = ["09:00", "13:00", "17:00", "20:00"][index - 1]
        cur.execute(
            """INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,format,
                   hook_type,status,cycle_no,topic_angle,hook_text,tenant_id)
               VALUES (%s,%s,1,%s,%s,%s,'L1',%s,'Painful Truth','DRAFT_ASSIGNED',1,%s,%s,%s)""",
            (sid, RID, time_uae, slot["pillar_code"], slot["hcs_id"], slot["format"], slot["topic_angle"], slot["hook_text"], "e2e"),
        )
        cur.execute(
            """INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,
                   rationale_ar,rationale_en,hook_text,hook_type,revision,tenant_id)
               VALUES (%s,%s,'L1',%s,1,%s,'سبب','because it matters',%s,'Painful Truth',1,%s)""",
            (sid, slot["hcs_id"], RID, slot["topic_angle"], slot["hook_text"], "e2e"),
        )
        cur.execute(
            """INSERT INTO script (slot_id,hcs_id,lens,script_ar,structure,final_line,delivery_notes,
                   delivery_check,used_islamic_anchor,needs_scholar_review,needs_native_review,flags,
                   model,revision,feedback,tenant_id)
               VALUES (%s,%s,'L1',%s,%s::jsonb,%s,%s,%s::jsonb,false,false,%s,'[]',
                   %s,1,NULL,%s)""",
            (
                sid,
                slot["hcs_id"],
                slot["script_ar"],
                json.dumps(slot["structure"], ensure_ascii=False),
                slot["final_line"],
                slot["delivery_notes"],
                json.dumps(slot["delivery_check"]),
                slot["needs_native_review"],
                slot["model"],
                "e2e",
            ),
        )
    conn.commit()


def main():
    conn = engine.db_connect()
    teardown(conn)
    seed(conn)
    gid = engine.open_gate(conn, "script_review", round_id=RID, actor="e2e")
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM slot WHERE round_id=%s GROUP BY status", (RID,))
    print(f"seeded {RID}: {dict(cur.fetchall())}  script gate {str(gid)[:8]} open")
    conn.close()


if __name__ == "__main__":
    main()
