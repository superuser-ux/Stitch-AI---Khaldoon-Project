"""Telegram approval bridge (M4.1) — SUMMARY-FIRST.

Telegram is a lightweight, on-the-go surface: it sends ONE digest per stage/batch
(counts + breakdown by pillar + flags) with batch buttons — it does NOT push one message
per slot. Detailed per-item review lives in the dashboard. "Step through" reveals a few
items on demand. Verbosity is config-driven (surfaces.telegram_ux). All decisions go
through the same engine.py as the dashboard + CLI. n8n is NOT in this path.

Run (long-lived poller):
  docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
    -v "$PWD":/work -w /work python:3.12-slim \
    bash -lc "pip install -q -r gates/requirements.txt && python gates/bot.py"

Commands: /start (chat id), /review [topic|script] (digest), /resolve.
"""
import asyncio
import os
import sys

from telegram import (ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402
import i18n  # noqa: E402  (shared glossary + copy catalog)

CODE = {"a": "approve", "c": "request_change", "r": "reject"}
MARK = {"approve": "✅", "request_change": "✏️", "reject": "❌"}


def slabel(stage):           # business-lexicon stage label from the shared glossary
    return i18n.gloss("stage", stage)


_pending_change = {}   # chat_id -> (gate_id, slot_id) awaiting a "what to change" reply


# --- config / auth ---------------------------------------------------------- #
def _cfg():
    return engine.load_config()


def _tux(cfg):
    return (cfg.get("surfaces") or {}).get("telegram_ux") or {}


def approver_for(chat_id, cfg, stage):
    # Authorization is EXPLICIT: only the configured approver chat may act. No implicit-allow
    # when telegram_approver_chat_id is unset (run /start to capture it). The chat maps to the
    # stage's first configured approver (BLOCK 3's principal model makes this mapping first-class).
    want = str((cfg.get("surfaces") or {}).get("telegram_approver_chat_id") or "").strip()
    if not want or str(chat_id) != want:
        return None
    approvers = engine.stage_cfg(cfg, stage).get("approvers") or []
    return approvers[0] if approvers else None


# --- DB helpers (engine is sync; run off the loop) -------------------------- #
def _pick_stage(cfg, explicit=None):
    """Default to the topic stage when topics await, else the script stage."""
    if explicit:
        return f"{explicit}_review"
    conn = engine.db_connect()
    try:
        cur = conn.cursor()
        order = ["topic_review", "script_review"]
        for st in order:
            rs = engine.stage_cfg(cfg, st).get("reviews_status")
            cur.execute("SELECT count(*) FROM slot WHERE status=%s", (rs,))
            if cur.fetchone()[0] > 0:
                return st
        return "topic_review"
    finally:
        conn.close()


def _open_or_load(stage, actor="system"):
    conn = engine.db_connect()
    try:
        gates = [g for g in engine.list_gates(conn, status="open") if g["stage"] == stage]
        gid = gates[0]["gate_id"] if gates else engine.open_gate(conn, stage, actor=actor)
        return engine.get_gate(conn, gid)
    finally:
        conn.close()


def _pending(gate):
    rs = None
    return [t for t in gate["targets"]
            if not any(d["decision"] in engine.DECISIONS for d in t["decisions"])]


def _record(gate_id, approver, decision, slot_ids, note=None):
    conn = engine.db_connect()
    try:
        engine.decide(conn, gate_id, approver, decision, slot_ids=slot_ids, notes=note)
    finally:
        conn.close()


def _resolve(stage, actor="system"):
    conn = engine.db_connect()
    try:
        gates = [g for g in engine.list_gates(conn, status="open") if g["stage"] == stage]
        if not gates:
            return None
        gid = gates[0]["gate_id"]
        return gid, engine.resolve(conn, gid, actor=actor)
    finally:
        conn.close()


# --- rendering -------------------------------------------------------------- #
def _digest(gate, todo):
    by_pillar, scholar, native = {}, 0, 0
    for t in todo:
        by_pillar[t["pillar_code"]] = by_pillar.get(t["pillar_code"], 0) + 1
        scholar += 1 if t.get("needs_scholar_review") else 0
        native += 1 if t.get("needs_native_review") else 0
    lines = [f"📋 {slabel(gate['stage'])}",
             f"{len(todo)} · {i18n.t('tg.awaiting', 'ar')}  (/ {len(gate['targets'])})",
             i18n.t("tg.by_pillar", "ar") + ": "
             + (", ".join(f"{k.split('_')[0]} {v}" for k, v in sorted(by_pillar.items())) or "—")]
    flags = []
    if scholar:
        flags.append(f"🕌 {i18n.term('flag', 'needs_scholar_review', 'ar')} {scholar}")
    if native:
        flags.append(f"🗣 {i18n.term('flag', 'needs_native_review', 'ar')} {native}")
    if flags:
        lines.append(i18n.t("tg.flags", "ar") + ": " + " · ".join(flags))
    return "\n".join(lines)


def _digest_kb(cfg, gate):
    url = (cfg.get("surfaces") or {}).get("dashboard_url") or ""
    row = [InlineKeyboardButton("✅ " + i18n.t("action.approve_all", "ar"), callback_data=f"appall|{gate['gate_id']}"),
           InlineKeyboardButton("👀 " + i18n.t("action.step_through", "ar"), callback_data=f"step|{gate['gate_id']}|0")]
    row2 = []
    if url:
        row2.append(InlineKeyboardButton("🖥 " + i18n.t("action.open_dashboard", "ar"), url=url))
    return InlineKeyboardMarkup([row, row2] if row2 else [row])


def _slot_card(t):
    # topic stage shows topic + hook + why-now; script stage adds the script. Plain text.
    head = f"{t['slot_id']} · {t['pillar_code']} · HCS {t['hcs_id']}"
    body = [head, f"hook: «{t['hook_text']}»"]
    if t.get("rationale_en"):
        body.append(f"why now: {t['rationale_en']}")
    if t.get("script_ar"):
        s = " ".join(t["script_ar"].split())
        body.append("\n" + (s[:500] + "…" if len(s) > 500 else s))
    return "\n".join(body)


def _slot_kb(gate_id, slot_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅", callback_data=f"a|{gate_id}|{slot_id}"),
        InlineKeyboardButton("✏️ change", callback_data=f"c|{gate_id}|{slot_id}"),
        InlineKeyboardButton("❌", callback_data=f"r|{gate_id}|{slot_id}"),
    ]])


# --- handlers --------------------------------------------------------------- #
async def start(update, ctx):
    chat = update.effective_chat
    cfg = _cfg()
    who = approver_for(chat.id, cfg, "topic_review")
    auth = (f"✅ authorized as {who}" if who else
            "⚠️ not the configured approver — set surfaces.telegram_approver_chat_id")
    await update.message.reply_text(
        f"Tanaghom approvals bot.\nYour chat id: {chat.id}\n{auth}\n\n"
        f"Set surfaces.telegram_approver_chat_id: \"{chat.id}\"\nThen /review for the digest.")


async def review(update, ctx):
    cfg = _cfg()
    explicit = (ctx.args[0].lower() if ctx.args and ctx.args[0].lower() in ("topic", "script") else None)
    stage = _pick_stage(cfg, explicit)
    who = approver_for(update.effective_chat.id, cfg, stage)
    if not who:
        return await update.message.reply_text("Not authorized. /start to see your chat id.")
    gate = await asyncio.to_thread(_open_or_load, stage, who)
    todo = _pending(gate)
    if not todo:
        return await update.message.reply_text(f"Nothing pending in {slabel(stage)}.")
    await update.message.reply_text(_digest(gate, todo), reply_markup=_digest_kb(cfg, gate))


async def on_button(update, ctx):
    q = update.callback_query
    await q.answer()
    cfg = _cfg()
    parts = q.data.split("|")
    kind, gate_id = parts[0], parts[1]
    # which stage is this gate? load it
    conn = engine.db_connect()
    try:
        gate = engine.get_gate(conn, gate_id)
    finally:
        conn.close()
    who = approver_for(q.message.chat.id, cfg, gate["stage"])
    if not who:
        return await q.edit_message_text("Not authorized.")

    if kind == "appall":
        todo = _pending(gate)
        await asyncio.to_thread(_record, gate_id, who, "approve", [t["slot_id"] for t in todo])
        return await q.edit_message_text(f"✅ approved {len(todo)} item(s). Send /resolve to apply.")

    if kind == "step":
        off = int(parts[2])
        size = int(_tux(cfg).get("step_batch_size", 5))
        todo = _pending(gate)
        batch = todo[off:off + size]
        for t in batch:
            await ctx.bot.send_message(q.message.chat.id, _slot_card(t),
                                       reply_markup=_slot_kb(gate_id, t["slot_id"]))
        more = off + size
        if more < len(todo):
            await ctx.bot.send_message(
                q.message.chat.id, f"… {len(todo) - more} more",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "👀 Next", callback_data=f"step|{gate_id}|{more}")]]))
        return

    # per-slot decision
    decision, slot_id = CODE.get(kind), parts[2]
    if decision == "request_change":
        _pending_change[q.message.chat.id] = (gate_id, slot_id)
        return await q.edit_message_text(
            f"{slot_id}: " + i18n.t("tg.reply_change", "ar"),
            reply_markup=ForceReply(selective=True))
    try:
        await asyncio.to_thread(_record, gate_id, who, decision, [slot_id])
    except Exception as e:  # noqa: BLE001
        return await q.edit_message_text(f"{slot_id}: error — {str(e)[:120]}")
    await q.edit_message_text(f"{slot_id} — {MARK[decision]} {i18n.term('decision', decision, 'ar')} · {who}")


async def on_change_reply(update, ctx):
    """Capture the reviewer's 'what to change' note (reply) and record request_change."""
    chat_id = update.effective_chat.id
    if chat_id not in _pending_change:
        return
    gate_id, slot_id = _pending_change.pop(chat_id)
    cfg = _cfg()
    conn = engine.db_connect()
    try:
        stage = engine.get_gate(conn, gate_id)["stage"]
    finally:
        conn.close()
    who = approver_for(chat_id, cfg, stage)
    note = (update.message.text or "").strip()
    try:
        await asyncio.to_thread(_record, gate_id, who, "request_change", [slot_id], note)
    except Exception as e:  # noqa: BLE001
        return await update.message.reply_text(f"{slot_id}: error — {str(e)[:120]}")
    await update.message.reply_text(f"{slot_id} — ✏️ {i18n.term('decision','request_change','ar')}: “{note}”")


async def resolve_cmd(update, ctx):
    cfg = _cfg()
    explicit = (ctx.args[0].lower() if ctx.args and ctx.args[0].lower() in ("topic", "script") else None)
    stage = _pick_stage(cfg, explicit)
    who = approver_for(update.effective_chat.id, cfg, stage)
    if not who:
        return await update.message.reply_text("Not authorized.")
    res = await asyncio.to_thread(_resolve, stage, who)
    if not res:
        return await update.message.reply_text(f"No open {slabel(stage)} gate.")
    gid, outcomes = res
    tally = {}
    for o in outcomes.values():
        tally[o] = tally.get(o, 0) + 1
    back = [f"{s}: {o}" for s, o in sorted(outcomes.items()) if o not in ("approved",)]
    await update.message.reply_text(
        f"Resolved {slabel(stage)}\n"
        + "  ".join(f"{k}={v}" for k, v in sorted(tally.items()))
        + ("\n" + "\n".join(back) if back else "\nall approved ✅")
        + ("\n" + i18n.t("tg.regenerates", "ar") if back else ""))


def main():
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("review", review))
    app.add_handler(CommandHandler("pending", review))   # alias
    app.add_handler(CommandHandler("resolve", resolve_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, on_change_reply))
    print("Tanaghom approvals bot (summary-first) polling…", flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
