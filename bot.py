import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

from sheets import SheetsClient
from vision import extract_text_from_image

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

WAITING_MEDIA = 1
WAITING_DESCRIPTION = 2
WAITING_SOURCE = 3

SKIP_BUTTON = [[InlineKeyboardButton("⏭ Пропустить", callback_data="skip")]]
SKIP_MARKUP = InlineKeyboardMarkup(SKIP_BUTTON)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Привет! Я помогу тебе собирать промпты в одном месте.\n\n"
        "📤 *Как использовать:*\n"
        "• Отправь мне текст промпта\n"
        "• Или скриншот с промптом\n"
        "• Или перешли сообщение из другого канала\n\n"
        "Я сам занесу всё в Google Таблицу 🗂",
        parse_mode="Markdown"
    )


async def handle_prompt_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data.clear()
    context.user_data["prompt"] = text
    context.user_data["photos"] = []
    context.user_data["current_state"] = WAITING_MEDIA

    await update.message.reply_text(
        f"✅ Промпт сохранён:\n\n_{text[:200]}{'...' if len(text) > 200 else ''}_\n\n"
        "📸 Пришли фото или видео для этого промпта.\n"
        "Можно несколько. Или нажми «Пропустить».",
        parse_mode="Markdown",
        reply_markup=SKIP_MARKUP
    )
    return WAITING_MEDIA


async def handle_prompt_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    photo = message.photo[-1] if message.photo else None
    if not photo:
        return ConversationHandler.END

    await message.reply_text("🔍 Извлекаю текст из скриншота...")

    try:
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        extracted_text = await extract_text_from_image(bytes(file_bytes))

        if not extracted_text or len(extracted_text.strip()) < 5:
            await message.reply_text("😕 Не удалось извлечь текст. Отправь промпт текстом.")
            return ConversationHandler.END

        context.user_data.clear()
        context.user_data["prompt"] = extracted_text.strip()
        context.user_data["photos"] = []
        context.user_data["current_state"] = WAITING_MEDIA

        await message.reply_text(
            f"✅ Извлечённый промпт:\n\n_{extracted_text[:300]}{'...' if len(extracted_text) > 300 else ''}_\n\n"
            "📸 Пришли фото или видео. Или нажми «Пропустить».",
            parse_mode="Markdown",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_MEDIA

    except Exception as e:
        logger.error(f"Error: {e}")
        await message.reply_text("❌ Ошибка. Попробуй текстом.")
        return ConversationHandler.END


async def handle_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = message.text or message.caption or ""

    context.user_data.clear()
    context.user_data["photos"] = []
    context.user_data["current_state"] = WAITING_MEDIA

    if message.photo:
        context.user_data["photos"].append(message.photo[-1].file_id)

    if text:
        context.user_data["prompt"] = text
        photos_note = "\n📎 Фото прикреплено: 1 шт." if context.user_data["photos"] else ""
        await message.reply_text(
            f"✅ Промпт из пересланного сообщения:{photos_note}\n\n_{text[:200]}_\n\n"
            "📸 Добавить ещё фото/видео? Или нажми «Пропустить».",
            parse_mode="Markdown",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_MEDIA
    elif message.photo:
        await message.reply_text("🔍 Извлекаю текст из изображения...")
        try:
            file = await context.bot.get_file(message.photo[-1].file_id)
            file_bytes = await file.download_as_bytearray()
            extracted_text = await extract_text_from_image(bytes(file_bytes))
            if extracted_text and len(extracted_text.strip()) > 5:
                context.user_data["prompt"] = extracted_text.strip()
                await message.reply_text(
                    f"✅ Извлечённый промпт:\n\n_{extracted_text[:300]}_\n\n"
                    "📸 Добавить фото/видео? Или нажми «Пропустить».",
                    parse_mode="Markdown",
                    reply_markup=SKIP_MARKUP
                )
                return WAITING_MEDIA
            else:
                await message.reply_text("😕 Не удалось извлечь текст. Отправь промпт текстом.")
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error: {e}")
            await message.reply_text("❌ Ошибка. Отправь промпт текстом.")
            return ConversationHandler.END
    else:
        await message.reply_text("🤔 Не нашёл текст. Отправь промпт текстом или скриншотом.")
        return ConversationHandler.END


async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message.photo:
        context.user_data["photos"].append(message.photo[-1].file_id)
        await message.reply_text(
            f"📸 Фото добавлено ({len(context.user_data['photos'])} шт.)\n"
            "Отправь ещё или нажми «Пропустить».",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_MEDIA
    elif message.video:
        context.user_data["video"] = message.video.file_id
        await message.reply_text("🎬 Видео добавлено!", reply_markup=SKIP_MARKUP)
        return WAITING_MEDIA
    else:
        await message.reply_text("Отправь медиафайл или нажми «Пропустить».", reply_markup=SKIP_MARKUP)
        return WAITING_MEDIA


async def handle_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text
    context.user_data["current_state"] = WAITING_SOURCE
    await update.message.reply_text(
        "🔗 Пришли ссылку на источник промпта.\nИли нажми «Пропустить».",
        reply_markup=SKIP_MARKUP
    )
    return WAITING_SOURCE


async def handle_source_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["source"] = update.message.text
    await finalize_entry(update, context)
    return ConversationHandler.END


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current_state = context.user_data.get("current_state", WAITING_MEDIA)

    if current_state == WAITING_MEDIA:
        context.user_data["current_state"] = WAITING_DESCRIPTION
        await query.edit_message_text(
            "✏️ Напиши краткое описание промпта.\n"
            "Например: «для аниме», «реалистичный портрет».\n"
            "Или нажми «Пропустить».",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_DESCRIPTION
    elif current_state == WAITING_DESCRIPTION:
        context.user_data["current_state"] = WAITING_SOURCE
        await query.edit_message_text(
            "🔗 Пришли ссылку на источник. Или нажми «Пропустить».",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_SOURCE
    elif current_state == WAITING_SOURCE:
        await query.edit_message_text("⏳ Сохраняю в таблицу...")
        await finalize_entry(update, context, via_callback=True)
        return ConversationHandler.END


async def finalize_entry(update, context, via_callback=False):
    data = context.user_data
    prompt = data.get("prompt", "—")
    description = data.get("description", "—")
    source = data.get("source", "—")
    photos = data.get("photos", [])
    video = data.get("video", "")

    media_ids = photos.copy()
    if video:
        media_ids.append(video)
    media_str = "\n".join(media_ids) if media_ids else "—"

    words = prompt.split()
    title = " ".join(words[:6]) if words else "Без названия"
    if len(title) > 50:
        title = title[:50] + "..."

    try:
        sheets = SheetsClient()
        sheets.append_row([title, description, prompt, media_str, source])
        success_text = (
            "✅ *Промпт успешно сохранён в таблицу!*\n\n"
            f"📌 *Название:* {title}\n"
            f"📝 *Описание:* {description}\n"
            f"📸 *Медиа:* {'Да (' + str(len(media_ids)) + ' шт.)' if media_ids else 'Нет'}\n"
            f"🔗 *Источник:* {source}\n\n"
            "Отправь следующий промпт! 🚀"
        )
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        success_text = f"❌ Ошибка сохранения: {e}"

    if via_callback:
        try:
            await update.callback_query.edit_message_text(success_text, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(
                chat_id=update.callback_query.message.chat_id,
                text=success_text,
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(success_text, parse_mode="Markdown")

    context.user_data.clear()


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено. Отправь новый промпт когда будешь готов.")
    return ConversationHandler.END


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.FORWARDED, handle_prompt_text),
            MessageHandler(filters.PHOTO & ~filters.FORWARDED, handle_prompt_image),
            MessageHandler(filters.FORWARDED, handle_forwarded),
        ],
        states={
            WAITING_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO, handle_media_input),
                CallbackQueryHandler(handle_skip, pattern="^skip$"),
            ],
            WAITING_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description_input),
                CallbackQueryHandler(handle_skip, pattern="^skip$"),
            ],
            WAITING_SOURCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_source_input),
                CallbackQueryHandler(handle_skip, pattern="^skip$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
