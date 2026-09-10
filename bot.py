import os
import sys
import logging
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import httpx
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

# 1. Веб-сервер для Health Check на Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# 2. Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 3. Переменные окружения
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

MODELS_TO_TRY = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash"
]

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📚 Учить пословицы"), KeyboardButton("🎯 Проверь себя")],
        [KeyboardButton("🎲 Случайная пословица"), KeyboardButton("🔍 Найти по теме")],
        [KeyboardButton("❤️ Избранное"), KeyboardButton("💾 Сохранить текущее")],
        [KeyboardButton("🏆 Мой результат"), KeyboardButton("🗑 Очистить избранное")]
    ],
    resize_keyboard=True
)

POPULAR_PROVERBS = [
    "Отан — оттан да ыстық.",
    "Ғылым таппай мақтанба, Орын таппай баптанба.",
    "Еңбек етсең ерінбей, Тояды қарның тіленбей.",
    "Білекті бірді жығады, Білімді мыңды жығады.",
    "Өнер алды — қызыл тіл."
]

user_favorites = {}
last_bot_message = {}

async def ask_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        return "❌ Ошибка: В настройках Render не задана переменная GEMINI_API_KEY!"

    full_prompt = (
        "Инструкция: Всегда оформляй ответ строго по этой структуре:\n\n"
        "🇰🇿 **Мақал:** (пословица на казахском языке)\n"
        "🇷🇺 **Перевод:** (точный перевод на русский)\n"
        "💡 **Мағынасы (Смысл):** (понятное объяснение сути в 1-2 предложения)\n"
        "📌 **Қолданылуы (Применение):** (коротко, в какой жизненной ситуации применяется)\n\n"
        "Отвечай сразу по делу, без приветствий и лишних вводных слов.\n\n"
        f"Запрос: {prompt}"
    )

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}]
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    # Быстрый таймаут 10 сек, чтобы бот не «зависал» на минуту
    async with httpx.AsyncClient(timeout=10.0) as client:
        for model in MODELS_TO_TRY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return data['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                logging.warning(f"Пропуск модели {model}: {e}")
                continue

    return "⚠️ ИИ задерживается с ответом. Попробуй нажать на кнопку ещё раз!"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Сәлем! 👋 Добро пожаловать в QazaqMaqal 🇰🇿!\n\n"
        "Выбирай пункт из меню ниже или отправь пословицу/тему для разбора."
    )
    await update.message.reply_text(welcome_text, reply_markup=MENU_KEYBOARD)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "❤️ Избранное":
        favs = user_favorites.get(chat_id, [])
        if not favs:
            await update.message.reply_text("📭 Твой список избранного пока пуст.", reply_markup=MENU_KEYBOARD)
        else:
            await update.message.reply_text(f"❤️ Твои сохранённые материалы ({len(favs)}):", reply_markup=MENU_KEYBOARD)
            for i, fav in enumerate(favs, 1):
                await update.message.reply_text(f"📌 #{i}\n{fav}")
        return

    elif text == "💾 Сохранить текущее":
        last_msg = last_bot_message.get(chat_id)
        if not last_msg:
            await update.message.reply_text("⚠️ Сначала отправь запрос боту!", reply_markup=MENU_KEYBOARD)
        else:
            if chat_id not in user_favorites:
                user_favorites[chat_id] = []
            if last_msg not in user_favorites[chat_id]:
                user_favorites[chat_id].append(last_msg)
                await update.message.reply_text("✅ Сохранено в Избранное!", reply_markup=MENU_KEYBOARD)
            else:
                await update.message.reply_text("📌 Уже есть в избранном!", reply_markup=MENU_KEYBOARD)
        return

    elif text == "🗑 Очистить избранное":
        user_favorites[chat_id] = []
        await update.message.reply_text("🗑 Избранное очищено.", reply_markup=MENU_KEYBOARD)
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if text == "📚 Учить пословицы":
        prompt = "Приведи мудрую казахскую пословицу."
        reply = await ask_gemini(prompt)

    elif text == "🎯 Проверь себя":
        prompt = "Сгенерируй короткий тест по казахской пословице: 1 вопрос, 3 варианта ответа (A, B, C) и правильный ответ."
        reply = await ask_gemini(prompt)

    elif text == "🎲 Случайная пословица":
        proverb = random.choice(POPULAR_PROVERBS)
        prompt = f"Возьми пословицу '{proverb}'."
        reply = await ask_gemini(prompt)

    elif text == "🔍 Найти по теме":
        reply = "💡 Напиши тему (например: дружба, родина, учеба), и я подберу подходящую пословицу!"

    elif text == "🏆 Мой результат":
        fav_count = len(user_favorites.get(chat_id, []))
        reply = f"📊 Твой уровень: Мудрец-начинающий ⭐️\nСохранено в избранное: {fav_count} пословиц"

    else:
        prompt = f"Разбери пословицу или подбери пословицу по теме '{text}'."
        reply = await ask_gemini(prompt)

    last_bot_message[chat_id] = reply
    await update.message.reply_text(reply, reply_markup=MENU_KEYBOARD)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот QazaqMaqal успешно запущен!")
    app.run_polling()
