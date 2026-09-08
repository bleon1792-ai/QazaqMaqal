import logging
import random
import os
import httpx
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"QazaqMaqal Bot is running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TELEGRAM_BOT_TOKEN = "8884376648:AAE8azDpH27Y2VoGuNkdRg-gwZrRTRZul6I"
GEMINI_API_KEY = "AQ.Ab8RN6IDzc0biq-8J_eK-P0ePYE8I5ER01Vm7cAddg_BTZdWrA"

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

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
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(GEMINI_URL, json=payload)
            if response.status_code == 200:
                data = response.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            else:
                return f"❌ Ошибка ИИ ({response.status_code}): {response.text}"
    except Exception as e:
        return f"❌ Ошибка подключения к ИИ: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Сәлем! 👋 Добро пожаловать в **Qazaq Maqal** 🇰🇿!\n\n"
        "Выбирай пункт из меню ниже, отправляй пословицы для разбора, "
        "а понравившиеся ответы сохраняй в **Избранное** кнопкой «💾 Сохранить текущее»!"
    )
    await update.message.reply_text(welcome_text, reply_markup=MENU_KEYBOARD, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "❤️ Избранное":
        favs = user_favorites.get(chat_id, [])
        if not favs:
            await update.message.reply_text(
                "📭 Твой список избранного пока пуст.\n\n"
                "Получи ответ от бота и нажми **«💾 Сохранить текущее»**, чтобы добавить его!",
                reply_markup=MENU_KEYBOARD,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❤️ **Твои сохранённые материалы ({len(favs)}):**", parse_mode="Markdown", reply_markup=MENU_KEYBOARD)
            for i, fav in enumerate(favs, 1):
                await update.message.reply_text(f"📌 **Сохранение #{i}**\n\n{fav}", parse_mode="Markdown")
        return

    elif text == "💾 Сохранить текущее":
        last_msg = last_bot_message.get(chat_id)
        if not last_msg:
            await update.message.reply_text("⚠️ Сначала отправь запрос боту, чтобы было что сохранять!", reply_markup=MENU_KEYBOARD)
        else:
            if chat_id not in user_favorites:
                user_favorites[chat_id] = []
            if last_msg not in user_favorites[chat_id]:
                user_favorites[chat_id].append(last_msg)
                await update.message.reply_text("✅ Успешно сохранено в **Избранное**! ❤️", reply_markup=MENU_KEYBOARD, parse_mode="Markdown")
            else:
                await update.message.reply_text("📌 Этот ответ уже есть в твоем избранном!", reply_markup=MENU_KEYBOARD)
        return

    elif text == "🗑 Очистить избранное":
        user_favorites[chat_id] = []
        await update.message.reply_text("🗑 Твой список избранного полностью очищен.", reply_markup=MENU_KEYBOARD)
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if text == "📚 Учить пословицы":
        prompt = (
            "Напиши 3 мудрые казахские пословицы. "
            "Для каждой приведи точный перевод на русский язык и краткое объяснение морали в 1 предложении. "
            "Оформи красиво с эмодзи."
        )
        reply = await ask_gemini(prompt)

    elif text == "🎯 Проверь себя":
        prompt = (
            "Сгенерируй тестовый вопрос по казахским пословицам. "
            "Например: 'Заверши пословицу: Отан — ...' или 'Что означает пословица...'. "
            "Дай 3 варианта ответа (A, B, C) и в самом конце под спойлером напиши правильный ответ."
        )
        reply = await ask_gemini(prompt)

    elif text == "🎲 Случайная пословица":
        proverb = random.choice(POPULAR_PROVERBS)
        prompt = f"Возьми пословицу '{proverb}' и подробно объясни её смысл, перевод и в каких жизненных ситуациях её применяют."
        reply = await ask_gemini(prompt)

    elif text == "🔍 Найти по теме":
        reply = (
            "💡 Напиши тему, которая тебя интересует (например: *дружба*, *труд*, *родина*, *знания*, *семья*), "
            "и я подберу подходящие пословицы!"
        )

    elif text == "🏆 Мой результат":
        fav_count = len(user_favorites.get(chat_id, []))
        reply = f"📊 Твой уровень: **Мудрец-начинающий** ⭐️\nСохранено в избранное: {fav_count} пословиц(ы)"

    else:
        prompt = (
            f"Ты эксперт по казахскому языку и мақал-мәтелдер. "
            f"Пользователь прислал текст или пословицу: '{text}'.\n\n"
            f"Сделай подробный разбор:\n"
            f"1. 🇰🇿 Пословица и точный перевод на русский\n"
            f"2. 💡 Глубокое значение и смысл простыми словами\n"
            f"3. 🎯 В каких ситуациях применяется\n"
            f"4. 📌 Мораль (чему учит)\n\n"
            f"Отвечай красиво, вежливо и с эмодзи."
        )
        reply = await ask_gemini(prompt)

    last_bot_message[chat_id] = reply
    await update.message.reply_text(reply, reply_markup=MENU_KEYBOARD)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот QazaqMaqal успешно запущен!")
    app.run_polling()
