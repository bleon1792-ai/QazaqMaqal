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
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.0-flash"
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

    # Единый чёткий шаблон оформления ответа
    full_prompt = (
        "Инструкция: Всегда оформляй ответ строго по этой структуре:\n\n"
        "🇰🇿 **Мақал:** (пословица на казахском языке)\n"
        "🇷🇺 **Перевод:** (точный перевод на русский)\n"
        "💡 **Мағынасы (Смысл):** (понятное объяснение сути в 1-2 предложения)\n"
        "📌 **Қолданылуы (Применение):** (коротко, в какой жизненной ситуации применяется)\n\n"
        "Отвечай без долгих вступлений и лишних приветствий. Соблюдай умеренную длину.\n\n"
        f"Запрос: {prompt}"
    )

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}]
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        last_error = ""
        for model in MODELS_TO_TRY:
            for api_ver in ["v1beta", "v1"]:
                url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent"
                try:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        return data['candidates'][0]['content']['parts'][0]['text']
                    else:
                        last_error = f"Model {model} ({api_ver}) HTTP {response.status_code}: {response.text}"
                except Exception as e:
                    last_error = str(e)
        
        return f"❌ Ошибка запроса к ИИ: {last_error}"

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
        prompt = "Приведи 2 мудрые казахские пословицы. Для каждой соблюдай структуру: 1) Мақал, 2) Перевод, 3) Мағынасы, 4) Қолданылуы."
        reply = await ask_gemini(prompt)

    elif text == "🎯 Проверь себя":
        prompt = "Сгенерируй тест по казахским пословицам: 1 вопрос, 3 варианта ответа (A, B, C) и в конце напиши правильный ответ с указанием мақал, перевода и смысла."
        reply = await ask_gemini(prompt)

    elif text == "🎲 Случайная пословица":
        proverb = random.choice(POPULAR_PROVERBS)
        prompt = f"Возьми пословицу '{proverb}'. Выдай её строго по формату: Мақал -> Перевод -> Мағынасы -> Қолданылуы."
        reply = await ask_gemini(prompt)

    elif text == "🔍 Найти по теме":
        reply = "💡 Напиши тему (например: дружба, родина, учеба), и я подберу подходящую пословицу с переводом и смыслом!"

    elif text == "🏆 Мой результат":
        fav_count = len(user_favorites.get(chat_id, []))
        reply = f"📊 Твой уровень: Мудрец-начинающий ⭐️\nСохранено в избранное: {fav_count} пословиц"

    else:
        prompt = f"Разбери пословицу или подбери пословицу по теме '{text}'. Оформи строго по структуре: 1) Мақал, 2) Перевод, 3) Мағынасы (Смысл), 4) Қолданылуы (Применение)."
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
