import os
import logging
import base64
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN ortam değişkeni ayarlanmamış")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY ortam değişkeni ayarlanmamış")

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-2.5-flash-lite"

SYSTEM_PROMPT = (
    "Sen Telegram'da çalışan yardımsever, samimi ve öz bir yapay zeka asistanısın. "
    "Cevaplarını her zaman Türkçe ver. "
    "Yanıtlarını açık ve anlaşılır tut. "
    "Kod yazman istenirse uygun biçimlendirme kullan. "
    "Konuşma geçmişini bu oturum içinde hatırlarsın."
)

user_sessions: dict[int, list[types.Content]] = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_sessions[user.id] = []
    await update.message.reply_text(
        f"👋 Merhaba {user.first_name}! Ben Google Gemini destekli yapay zeka asistanınım.\n\n"
        "Bana mesaj yaz, sana yardımcı olayım. Komutları görmek için /yardim yazabilirsin."
    )


async def yardim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Mevcut Komutlar*\n\n"
        "/baslat — Yeni bir sohbet başlat\n"
        "/temizle — Sohbet geçmişini temizle\n"
        "/yardim — Bu yardım mesajını göster\n\n"
        "💬 Herhangi bir mesaj yazarak Gemini AI ile sohbet edebilirsin!\n"
        "🖼️ Fotoğraf göndererek resim analizi yaptırabilirsin. Açıklama da ekleyebilirsin.\n"
        "🎙️ Sesli mesaj göndererek sesi metne çevirip yanıt alabilirsin.",
        parse_mode="Markdown"
    )


async def temizle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_sessions[user_id] = []
    await update.message.reply_text("🗑️ Sohbet geçmişi temizlendi. Yeni bir sohbet başlıyor!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_sessions:
        user_sessions[user_id] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    user_sessions[user_id].append(
        types.Content(role="user", parts=[types.Part(text=user_text)])
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=user_sessions[user_id],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=8192,
            ),
        )
        reply_text = response.text

        user_sessions[user_id].append(
            types.Content(role="model", parts=[types.Part(text=reply_text)])
        )

        if len(user_sessions[user_id]) > 40:
            user_sessions[user_id] = user_sessions[user_id][-40:]

        max_length = 4096
        if len(reply_text) <= max_length:
            await update.message.reply_text(reply_text)
        else:
            for i in range(0, len(reply_text), max_length):
                await update.message.reply_text(reply_text[i:i + max_length])

    except Exception as e:
        error_str = str(e)
        logger.error(f"Gemini API hatası: {error_str}")

        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            await update.message.reply_text(
                "⏳ API kotası doldu, birkaç saniye bekleyip tekrar dene."
            )
        elif "401" in error_str or "API_KEY" in error_str:
            await update.message.reply_text(
                "🔑 Geçersiz API anahtarı. Lütfen GEMINI_API_KEY değerini kontrol et."
            )
        else:
            await update.message.reply_text(
                "⚠️ Bir hata oluştu, lütfen tekrar dene."
            )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if user_id not in user_sessions:
        user_sessions[user_id] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    caption = update.message.caption or "Bu resmi Türkçe olarak analiz et ve detaylıca açıkla."

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        photo_b64 = base64.b64encode(photo_bytes).decode("utf-8")

        contents = user_sessions[user_id] + [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        inline_data=types.Blob(mime_type="image/jpeg", data=photo_b64)
                    ),
                    types.Part(text=caption),
                ],
            )
        ]

        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=8192,
            ),
        )
        reply_text = response.text

        user_sessions[user_id].append(
            types.Content(role="user", parts=[types.Part(text=f"[Resim gönderildi] {caption}")])
        )
        user_sessions[user_id].append(
            types.Content(role="model", parts=[types.Part(text=reply_text)])
        )

        if len(user_sessions[user_id]) > 40:
            user_sessions[user_id] = user_sessions[user_id][-40:]

        max_length = 4096
        if len(reply_text) <= max_length:
            await update.message.reply_text(reply_text)
        else:
            for i in range(0, len(reply_text), max_length):
                await update.message.reply_text(reply_text[i:i + max_length])

    except Exception as e:
        error_str = str(e)
        logger.error(f"Fotoğraf işleme hatası: {error_str}")
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            await update.message.reply_text(
                "⏳ API kotası doldu, birkaç saniye bekleyip tekrar dene."
            )
        else:
            await update.message.reply_text(
                "⚠️ Fotoğraf işlenirken bir hata oluştu, lütfen tekrar dene."
            )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if user_id not in user_sessions:
        user_sessions[user_id] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        voice_bytes = await file.download_as_bytearray()
        voice_b64 = base64.b64encode(voice_bytes).decode("utf-8")

        contents = user_sessions[user_id] + [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        inline_data=types.Blob(mime_type="audio/ogg", data=voice_b64)
                    ),
                    types.Part(
                        text=(
                            "Önce bu sesli mesajı kelimesi kelimesine Türkçe olarak yazıya çevir, "
                            "ardından içeriğe uygun Türkçe bir yanıt ver. "
                            "Yanıtını şu formatta yaz:\n"
                            "🎙️ *Transkript:* <metne çevrilmiş ses>\n\n"
                            "💬 *Yanıt:* <AI yanıtı>"
                        )
                    ),
                ],
            )
        ]

        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=8192,
            ),
        )
        reply_text = response.text

        user_sessions[user_id].append(
            types.Content(role="user", parts=[types.Part(text="[Sesli mesaj gönderildi]")])
        )
        user_sessions[user_id].append(
            types.Content(role="model", parts=[types.Part(text=reply_text)])
        )

        if len(user_sessions[user_id]) > 40:
            user_sessions[user_id] = user_sessions[user_id][-40:]

        max_length = 4096
        if len(reply_text) <= max_length:
            await update.message.reply_text(reply_text, parse_mode="Markdown")
        else:
            for i in range(0, len(reply_text), max_length):
                await update.message.reply_text(reply_text[i:i + max_length], parse_mode="Markdown")

    except Exception as e:
        error_str = str(e)
        logger.error(f"Ses mesajı işleme hatası: {error_str}")
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            await update.message.reply_text(
                "⏳ API kotası doldu, birkaç saniye bekleyip tekrar dene."
            )
        else:
            await update.message.reply_text(
                "⚠️ Ses mesajı işlenirken hata oluştu, lütfen tekrar dene."
            )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Güncelleme işlenirken hata: {context.error}")


def main() -> None:
    logger.info("Telegram AI Botu başlatılıyor...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("baslat", start))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yardim", yardim_command))
    app.add_handler(CommandHandler("help", yardim_command))
    app.add_handler(CommandHandler("temizle", temizle_command))
    app.add_handler(CommandHandler("clear", temizle_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_error_handler(error_handler)

    logger.info("Bot çalışıyor. Durdurmak için Ctrl+C bas.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
