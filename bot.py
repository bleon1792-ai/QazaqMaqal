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

# 2. Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 3. Переменные окружения
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 4. Локальная база данных пословиц (Мгновенный отклик 0ms)
PROVERBS_DB = [
    {
        "maqal": "Отан — оттан да ыстық.",
        "translation": "Родина горячее огня.",
        "meaning": "Любовь к своей родине — самое сильное и священное чувство.",
        "usage": "Применяется, когда говорят о патриотизме и любви к родному краю."
    },
    {
        "maqal": "Ғылым таппай мақтанба, Орын таппай баптанба.",
        "translation": "Не хвастайся, не найдя знания, не гордись, не найдя своего места.",
        "meaning": "Настоящее уважение приносят только знания и реальный труд, а не пустая гордость.",
        "usage": "Применяется как наставление к учебе и скромности."
    },
    {
        "maqal": "Еңбек етсең ерінбей, Тояды қарның тіленбей.",
        "translation": "Если будешь трудиться без лени, будешь сыт без попрошайничества.",
        "meaning": "Честный труд гарантирует достаток и независимость.",
        "usage": "Используется для мотивирования к работе и борьбе с ленью."
    },
    {
        "maqal": "Білекті бірді жығады, Білімді мыңды жығады.",
        "translation": "Сильный победит одного, знающий — победит тысячу.",
        "meaning": "Ум и знания намного сильнее физической силы.",
        "usage": "Подчеркивает важность образования и интеллекта."
    },
    {
        "maqal": "Өнер алды — қызыл тіл.",
        "translation": "Первое из искусств — красноречие.",
        "meaning": "Умение правильно и красиво говорить открывает любые двери.",
        "usage": "Говорится о значении ораторского искусства и грамотной речи."
    },
    {
        "maqal": "Досы көпті жау алмайды, Ақылы көпті дау алмайды.",
        "translation": "У кого много друзей — того враг не одолеет, у кого много ума — тот в споре не проиграет.",
        "meaning": "Дружба и разум — главные защитники человека в сложных ситуациях.",
        "usage": "Применяется для ценности дружбы и здравомыслия."
    },
    {
        "maqal": "Жақсы байқап сөйлер, Жаман шайқап сөйлер.",
        "translation": "Мудрый говорит обдуманно, глупый — наобум.",
        "meaning": "Умный человек всегда взвешивает свои слова перед тем как сказать.",
        "usage": "Говорится о культуре речи и сдержанности."
    }
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

user_favorites = {}
last_bot_message = {}

def format_proverb_card(p: dict) -> str:
    return (
        f"🇰🇿 **Мақал:** {p['maqal']}\n"
        f"🇷🇺 **Перевод:** {p['translation']}\n"
        f"💡 **Мағынасы:** {p['meaning']}\n"
        f"📌 **Қолданылуы:** {p['usage']}"
    )

async def ask_gemini_fallback(text: str) -> str:
    """Вызывается ТОЛЬКО если запрос отсутствует в локальной базе"""
    if not GEMINI_API_KEY:
        return "❌ Ошибка: В настройках Render не задан GEMINI_API_KEY!"

    full_prompt = (
        "Инструкция: Сформулируй ответ строго по следующей структуре:\n\n"
        "🇰🇿 **Мақал:** (казахская пословица)\n"
        "🇷🇺 **Перевод:** (перевод на русский)\n"
        "💡 **Мағынасы:** (смысл в 1-2 предложения)\n"
        "📌 **Қолданылуы:** (применение в жизни)\n\n"
        f"Запрос пользователя: {text}"
    )

    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    models = ["gemini-2.0-flash", "gemini-1.5-flash"]
    async with httpx.AsyncClient(timeout=6.0) as client:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return data['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                logging.warning(f"Gemini error {model}: {e}")
                continue

    return "⚠️ Запрос не найден в базе. Попробуй еще раз или выбери вариант из меню!"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Сәлем! 👋 Добро пожаловать в QazaqMaqal 🇰🇿!\n\n"
        "Выбирай пункт из меню — всё работает мгновенно из локальной базы!"
    )
    await update.message.reply_text(welcome_text, reply_markup=MENU_KEYBOARD)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # 1. МГНОВЕННЫЕ ЛОКАЛЬНЫЕ ДЕЙСТВИЯ (0 секунд задержки)
    if text in ["📚 Учить пословицы", "🎲 Случайная пословица"]:
        item = random.choice(PROVERBS_DB)
        reply = format_proverb_card(item)

    elif text == "🎯 Проверь себя":
        item = random.choice(PROVERBS_DB)
        words = item["maqal"].split()
        if len(words) > 2:
            missing_idx = len(words) // 2
            missing_word = words[missing_idx]
            masked_maqal = " ".join([w if i != missing_idx else "___" for i, w in enumerate(words)])
            reply = (
                f"🎯 **Вставьте пропущенное слово:**\n\n"
                f"«{masked_maqal}»\n\n"
                f"💡 *Подсказка (перевод):* {item['translation']}\n"
                f"||Ответ: {missing_word}||"
            )
        else:
            reply = format_proverb_card(item)

    elif text == "🔍 Найти по теме":
        reply = "💡 Напиши ключевое слово (например: *дос*, *труд*, *родина*, *білім*), и я найду пословицу!"

    elif text == "❤️ Избранное":
        favs = user_favorites.get(chat_id, [])
        if not favs:
            await update.message.reply_text("📭 Твой список избранного пуст.", reply_markup=MENU_KEYBOARD)
            return
        else:
            await update.message.reply_text(f"❤️ Твои сохранённые материалы ({len(favs)}):", reply_markup=MENU_KEYBOARD)
            for i, fav in enumerate(favs, 1):
                await update.message.reply_text(f"📌 #{i}\n{fav}")
            return

    elif text == "💾 Сохранить текущее":
        last_msg = last_bot_message.get(chat_id)
        if not last_msg:
            await update.message.reply_text("⚠️ Сначала выбери пословицу!", reply_markup=MENU_KEYBOARD)
            return
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

    elif text == "🏆 Мой результат":
        fav_count = len(user_favorites.get(chat_id, []))
        reply = f"📊 Твой результат:\n- Сохранено пословиц: {fav_count}\n- Статус: Знаток ⭐️"

    else:
        # 2. ПОИСК В ЛОКАЛЬНОЙ БАЗЕ
        found_local = [
            p for p in PROVERBS_DB 
            if text.lower() in p["maqal"].lower() 
            or text.lower() in p["translation"].lower() 
            or text.lower() in p["meaning"].lower()
        ]
        if found_local:
            reply = format_proverb_card(found_local[0])
        else:
            # 3. ТОЛЬКО ЕСЛИ НЕТ В БАЗЕ — ЗАПРОС К ИИ
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            reply = await ask_gemini_fallback(text)

    last_bot_message[chat_id] = reply
    await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=MENU_KEYBOARD)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот QazaqMaqal успешно запущен!")
    app.run_polling()
