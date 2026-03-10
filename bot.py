import logging
import os
import json
import base64
from io import BytesIO

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

# Conversation states
WAITING_MEDIA = 1
WAITING_DESCRIPTION = 2
WAITING_SOURCE = 3

SKIP_BUTTON = [[InlineKeyboardButton("⏭ Пропустить", callback_data="skip")]]
SKIP_MARKUP = InlineKeyboardMarkup(SKIP_BUTTON)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    """Handle plain text message as prompt"""
    text = update.message.text

    if text.startswith("/"):
        return

    context.user_data.clear()
    context.user_data["prompt"] = text
    context.user_data["photos"] = []

    await update.message.reply_text(
        f"✅ Промпт сохранён:\n\n_{text[:200]}{'...' if len(text) > 200 else ''}_\n\n"
        "📸 Теперь пришли фото или видео для этого промпта (можно несколько).\n"
        "Или нажми кнопку ниже, чтобы пропустить.",
        parse_mode="Markdown",
        reply_markup=SKIP_MARKUP
    )
    return WAITING_MEDIA


async def handle_prompt_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image as prompt (extract text via OCR)"""
    message = update.message

    # Get the largest photo
    photo = message.photo[-1] if message.photo else None
    if not photo:
        return

    await message.reply_text("🔍 Извлекаю текст из скриншота...")

    try:
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()

        extracted_text = await extract_text_from_image(bytes(file_bytes))

        if not extracted_text or len(extracted_text.strip()) < 5:
            await message.reply_text(
                "😕 Не удалось извлечь текст из изображения.\n"
                "Пожалуйста, отправь промпт текстом."
            )
            return ConversationHandler.END

        context.user_data.clear()
        context.user_data["prompt"] = extracted_text.strip()
        context.user_data["photos"] = []

        await message.reply_text(
            f"✅ Извлечённый текст промпта:\n\n_{extracted_text[:300]}{'...' if len(extracted_text) > 300 else ''}_\n\n"
            "📸 Теперь пришли фото или видео для этого промпта (можно несколько).\n"
            "Или нажми кнопку ниже, чтобы пропустить.",
            parse_mode="Markdown",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_MEDIA

    except Exception as e:
        logger.error(f"Error extracting text: {e}")
        await message.reply_text(
            "❌ Ошибка при обработке изображения. Попробуй отправить промпт текстом."
        )
        return ConversationHandler.END


async def handle_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded messages with optional attached media"""
    message = update.message
    text = message.text or message.caption or ""
    
    context.user_data.clear()
    context.user_data["photos"] = []

    # Check for attached photo in forwarded message
    if message.photo:
        photo = message.photo[-1]
        context.user_data["photos"].append(photo.file_id)

    if text:
        context.user_data["prompt"] = text
        preview = text[:200] + ('...' if len(text) > 200 else '')
        photos_note = f"\n📎 Прикреплено фото: 1 шт." if context.user_data["photos"] else ""
        
        await message.reply_text(
            f"✅ Промпт из пересланного сообщения:{photos_note}\n\n_{preview}_\n\n"
            "📸 Добавить ещё фото/видео? Или нажми «Пропустить».",
            parse_mode="Markdown",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_MEDIA
    elif message.photo:
        # Only image, need to OCR
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
        await message.reply_text(
            "🤔 Не нашёл текст в этом сообщении. Отправь промпт текстом или скриншотом."
        )
        return ConversationHandler.END


async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect photo/video files"""
    message = update.message

    if message.photo:
        photo = message.photo[-1]
        context.user_data["photos"].append(photo.file_id)
        await message.reply_text(
            f"📸 Фото добавлено ({len(context.user_data['photos'])} шт.)\n"
            "Отправь ещё или нажми «Пропустить» для продолжения.",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_MEDIA

    elif message.video:
        context.user_data["video"] = message.video.file_id
        await message.reply_text("🎬 Видео добавлено!", reply_markup=SKIP_MARKUP)
        return WAITING_MEDIA

    else:
        await message.reply_text(
            "Это не фото и не видео. Отправь медиафайл или нажми «Пропустить».",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_MEDIA


async def handle_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save description text"""
    context.user_data["description"] = update.message.text
    await update.message.reply_text(
        "🔗 Отлично! Теперь пришли ссылку на источник промпта.\n"
        "Или нажми «Пропустить».",
        reply_markup=SKIP_MARKUP
    )
    return WAITING_SOURCE


async def handle_source_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save source link and finalize entry"""
    context.user_data["source"] = update.message.text
    await finalize_entry(update, context)
    return ConversationHandler.END


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skip button press"""
    query = update.callback_query
    await query.answer()

    state = context.user_data.get("_state_hint")
    
    # Determine current state from conversation
    # We'll use a helper field to track
    current_state = context.user_data.get("current_state", WAITING_MEDIA)

    if current_state == WAITING_MEDIA:
        context.user_data["current_state"] = WAITING_DESCRIPTION
        await query.edit_message_text(
            "✏️ Напиши краткое описание этого промпта.\n"
            "Например: «для аниме-стиля», «реалистичный портрет» и т.д.\n"
            "Или нажми «Пропустить».",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_DESCRIPTION

    elif current_state == WAITING_DESCRIPTION:
        context.user_data["current_state"] = WAITING_SOURCE
        await query.edit_message_text(
            "🔗 Пришли ссылку на источник промпта.\n"
            "Или нажми «Пропустить».",
            reply_markup=SKIP_MARKUP
        )
        return WAITING_SOURCE

    elif current_state == WAITING_SOURCE:
        await query.edit_message_text("⏳ Сохраняю в таблицу...")
        await finalize_entry(update, context, via_callback=True)
        return ConversationHandler.END


async def finalize_entry(update, context, via_callback=False):
    """Save all data to Google Sheets"""
    data = context.user_data
    
    prompt = data.get("prompt", "—")
    description = data.get("description", "—")
    source = data.get("source", "—")
    photos = data.get("photos", [])
    video = data.get("video", "")

    # Build media string
    media_ids = photos.copy()
    if video:
        media_ids.append(video)
    media_str = "\n".join(media_ids) if media_ids else "—"

    # Generate title from prompt (first 50 chars)
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
            f"📸 *Медиа:* {'Да' if media_ids else 'Нет'}\n"
            f"🔗 *Источник:* {source}\n\n"
            "Отправь следующий промпт, когда будет готов! 🚀"
        )
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        success_text = f"❌ Ошибка сохранения в таблицу: {e}\n\nПроверь настройки Google Sheets."

    if via_callback:
        try:
            await update.callback_query.edit_message_text(success_text, parse_mode="Markdown")
        except:
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


# State-tracking middleware for skip button
async def set_state_media(update, context):
    context.user_data["current_state"] = WAITING_MEDIA
    if update.message.photo and not context.user_data.get("prompt"):
        return await handle_prompt_image(update, context)
    elif update.message.forward_origin or update.message.forward_from or update.message.forward_from_chat:
        return await handle_forwarded(update, context)
    elif update.message.text:
        return await handle_prompt_text(update, context)
    return ConversationHandler.END


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()

    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt_text),
            MessageHandler(filters.PHOTO & ~filters.FORWARDED, handle_prompt_image),
            MessageHandler(filters.FORWARDED, handle_forwarded),
            MessageHandler((filters.TEXT | filters.PHOTO) & filters.FORWARDED, handle_forwarded),
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
    )

    # Override skip to track state properly
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
