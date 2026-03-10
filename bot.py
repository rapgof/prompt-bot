import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

from sheets import SheetsClient

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States
WAITING_MEDIA = 1
WAITING_DESCRIPTION = 2
WAITING_SOURCE = 3

def skip_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Пропустить", callback_data="skip")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Привет! Отправь мне текст промпта или перешли сообщение из канала.\n\n"
        "Я сохраню всё в Google Таблицу 🗂"
    )

# ── ENTRY: plain text ──────────────────────────────────────────────────────────
async def entry_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["prompt"] = update.message.text
    context.user_data["photos"] = []
    await update.message.reply_text(
        f"✅ Промпт принят!\n\n"
        "📸 Пришли фото или видео (можно несколько).\nИли нажми «Пропустить».",
        reply_markup=skip_markup()
    )
    return WAITING_MEDIA

# ── ENTRY: forwarded message ───────────────────────────────────────────────────
async def entry_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text or msg.caption or ""
    context.user_data.clear()
    context.user_data["photos"] = []

    if msg.photo:
        context.user_data["photos"].append(msg.photo[-1].file_id)

    if not text and not msg.photo:
        await msg.reply_text("🤔 Не нашёл текст. Отправь промпт текстом.")
        return ConversationHandler.END

    context.user_data["prompt"] = text if text else "—"
    photos_note = "\n📎 Фото: 1 шт." if context.user_data["photos"] else ""
    preview = text[:200] + ("..." if len(text) > 200 else "") if text else "(без текста)"

    await msg.reply_text(
        f"✅ Промпт из пересланного:{photos_note}\n\n_{preview}_\n\n"
        "📸 Добавить ещё фото/видео? Или нажми «Пропустить».",
        parse_mode="Markdown",
        reply_markup=skip_markup()
    )
    return WAITING_MEDIA

# ── STATE: WAITING_MEDIA ───────────────────────────────────────────────────────
async def got_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo:
        context.user_data["photos"].append(msg.photo[-1].file_id)
        await msg.reply_text(
            f"📸 Фото добавлено ({len(context.user_data['photos'])} шт.). Ещё или «Пропустить».",
            reply_markup=skip_markup()
        )
    elif msg.video:
        context.user_data["video"] = msg.video.file_id
        await msg.reply_text("🎬 Видео добавлено! Ещё или «Пропустить».", reply_markup=skip_markup())
    else:
        await msg.reply_text("Отправь фото/видео или нажми «Пропустить».", reply_markup=skip_markup())
    return WAITING_MEDIA

# ── STATE: WAITING_DESCRIPTION ─────────────────────────────────────────────────
async def got_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text
    await update.message.reply_text(
        "🔗 Пришли ссылку на источник.\nИли нажми «Пропустить».",
        reply_markup=skip_markup()
    )
    return WAITING_SOURCE

# ── STATE: WAITING_SOURCE ──────────────────────────────────────────────────────
async def got_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["source"] = update.message.text
    await do_save(update, context)
    return ConversationHandler.END

# ── SKIP button ────────────────────────────────────────────────────────────────
async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # current state is tracked by ConversationHandler automatically —
    # we just check which question to ask next based on what's missing
    state = context.user_data.get("_next_after_skip")

    # Figure out where we are by checking conv state via a small trick:
    # We store the last sent state explicitly
    last = context.user_data.get("last_state", WAITING_MEDIA)

    if last == WAITING_MEDIA:
        context.user_data["last_state"] = WAITING_DESCRIPTION
        await query.edit_message_text(
            "✏️ Напиши краткое описание промпта.\nИли нажми «Пропустить».",
            reply_markup=skip_markup()
        )
        return WAITING_DESCRIPTION

    elif last == WAITING_DESCRIPTION:
        context.user_data["last_state"] = WAITING_SOURCE
        await query.edit_message_text(
            "🔗 Пришли ссылку на источник.\nИли нажми «Пропустить».",
            reply_markup=skip_markup()
        )
        return WAITING_SOURCE

    elif last == WAITING_SOURCE:
        await query.edit_message_text("⏳ Сохраняю...")
        await do_save(update, context, via_callback=True)
        return ConversationHandler.END

    # fallback — shouldn't happen
    await do_save(update, context, via_callback=True)
    return ConversationHandler.END

# ── SAVE ───────────────────────────────────────────────────────────────────────
async def do_save(update, context, via_callback=False):
    d = context.user_data
    prompt      = d.get("prompt", "—")
    description = d.get("description", "—")
    source      = d.get("source", "—")
    photos      = d.get("photos", [])
    video       = d.get("video", "")

    media_ids = photos + ([video] if video else [])
    media_str = "\n".join(media_ids) if media_ids else "—"

    words = prompt.split()
    title = " ".join(words[:6]) if words and prompt != "—" else "Без названия"
    if len(title) > 50:
        title = title[:50] + "..."

    try:
        SheetsClient().append_row([title, description, prompt, media_str, source])
        text = (
            "✅ *Сохранено в таблицу!*\n\n"
            f"📌 *Название:* {title}\n"
            f"📝 *Описание:* {description}\n"
            f"📸 *Медиа:* {'Да (' + str(len(media_ids)) + ' шт.)' if media_ids else 'Нет'}\n"
            f"🔗 *Источник:* {source}\n\n"
            "Отправь следующий промпт! 🚀"
        )
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        text = f"❌ Ошибка сохранения: {e}"

    context.user_data.clear()

    if via_callback:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(
                chat_id=update.callback_query.message.chat_id,
                text=text, parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

# ── Helpers to set last_state when entering each state ─────────────────────────
async def entry_text_wrapped(update, context):
    context.user_data["last_state"] = WAITING_MEDIA
    return await entry_text(update, context)

async def entry_forwarded_wrapped(update, context):
    context.user_data["last_state"] = WAITING_MEDIA
    return await entry_forwarded(update, context)

async def got_media_wrapped(update, context):
    context.user_data["last_state"] = WAITING_MEDIA
    return await got_media(update, context)

async def got_description_wrapped(update, context):
    context.user_data["last_state"] = WAITING_DESCRIPTION
    return await got_description(update, context)

async def got_source_wrapped(update, context):
    context.user_data["last_state"] = WAITING_SOURCE
    return await got_source(update, context)

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set!")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.FORWARDED, entry_text_wrapped),
            MessageHandler(filters.FORWARDED, entry_forwarded_wrapped),
        ],
        states={
            WAITING_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO, got_media_wrapped),
                CallbackQueryHandler(skip, pattern="^skip$"),
            ],
            WAITING_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_description_wrapped),
                CallbackQueryHandler(skip, pattern="^skip$"),
            ],
            WAITING_SOURCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_source_wrapped),
                CallbackQueryHandler(skip, pattern="^skip$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv)
    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
