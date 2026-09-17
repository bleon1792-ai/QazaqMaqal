import os
import sys
import logging
import random
import threading
import re
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

# ==========================================
# 1. СЕРВЕР ДЛЯ ПОДДЕРЖАНИЯ АКТИВНОСТИ (RENDER)
# ==========================================
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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# ==========================================
# 2. БАЗА ДАННЫХ ПОСЛОВИЦ (КЕШИРОВАНИЕ)
# ==========================================
PROVERBS_DB = [
    {
        "maqal": "Отан — оттан да ыстық.",
        "translation": "Родина горячее огня.",
        "meaning": "Любовь к своей родине — самое сильное и священное чувство.",
        "usage": "Применяется, когда говорят о патриотизме и любви к родному краю.",
        "keys": ["родина", "отан", "патриот", "страна"]
    },
    {
        "maqal": "Ғылым таппай мақтанба, Орын таппай баптанба.",
        "translation": "Не хвастайся, не найдя знания, не гордись, не найдя своего места.",
        "meaning": "Настоящее уважение приносят только знания и реальный труд.",
        "usage": "Применяется как наставление к учебе и скромности.",
        "keys": ["учеба", "знания", "білім", "ғылым", "наука", "школа"]
    },
    {
        "maqal": "Еңбек етсең ерінбей, Тояды қарның тіленбей.",
        "translation": "Если будешь трудиться без лени, будешь сыт без попрошайничества.",
        "meaning": "Честный труд гарантирует достаток и независимость.",
        "usage": "Используется для мотивирования к работе и борьбе с ленью.",
        "keys": ["труд", "еңбек", "работа", "лень", "деньги"]
    },
    {
        "maqal": "Білекті бірді жығады, Білімді мыңды жығады.",
        "translation": "Сильный победит одного, знающий — победит тысячу.",
        "meaning": "Ум и знания намного сильнее физической силы.",
        "usage": "Подчеркивает важность образования и интеллекта.",
        "keys": ["ум", "сила", "знания", "білім", "интеллект"]
    },
    {
        "maqal": "Досы көпті жау алмайды, Ақылы көпті дау алмайды.",
        "translation": "У кого много друзей — того враг не одолеет, у кого много ума — тот в споре не проиграет.",
        "meaning": "Дружба и разум — главные защитники человека в сложных ситуациях.",
        "usage": "Применяется для объяснения ценности дружбы и здравомыслия.",
        "keys": ["друг", "дружба", "дос", "друзья", "достық"]
    },
    {
        "maqal": "Жақсы байқап сөйлер, Жаман шайқап сөйлер.",
        "translation": "Мудрый говорит обдуманно, глупый — наобум.",
        "meaning": "Умный человек всегда взвешивает свои слова перед тем как сказать.",
        "usage": "Говорится о культуре речи и сдержанности.",
        "keys": ["слово", "сөз", "мудрость", "речь", "глупость"]
    },
    {
        "maqal": "Ананың көңілі балада, баланың көңілі далада.",
        "translation": "Душа матери — в ребенке, душа ребенка — в степи (на улице).",
        "meaning": "Родители всегда переживают за детей, а дети часто беспечны.",
        "usage": "Используется, когда говорят о родительской любви и заботе.",
        "keys": ["мама", "ана", "семья", "ребенок", "бала", "родители"]
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

# ==========================================
# 3. ИНТЕГРАЦИЯ С GEMINI 3.6 FLASH
# ==========================================
async def ask_gemini_fallback(text: str) -> str:
    if not GEMINI_API_KEY:
        return "❌ Ошибка системы: API ключ GEMINI_API_KEY не задан!"

    full_prompt = (
        "Действуй как эксперт по казахскому фольклору.\n"
        "Сформулируй ответ строго по следующей структуре без вводных слов:\n\n"
        "🇰🇿 **Мақал:** (казахская пословица)\n"
        "🇷🇺 **Перевод:** (перевод на русский)\n"
        "💡 **Мағынасы:** (смысл пословицы)\n"
        "📌 **Қолданылуы:** (применение в жизни)\n\n"
        f"Запрос пользователя: {text}"
    )

    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    # Использование модели Gemini 3.6 Flash
    model = "gemini-3.6-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            else:
                logging.error(f"Gemini 3.6 API Error: {response.status_code} - {response.text}")
                return f"⚠️ Ошибка ИИ (Код {response.status_code}). Попробуй выбрать из меню!"
        except Exception as e:
            logging.error(f"Network Error: {e}")
            return "⚠️ Ошибка сети при обращении к нейросети."

# ==========================================
# 4. ОБРАБОТКА КОМАНД И СООБЩЕНИЙ
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = "Сәлем! 👋 Добро пожаловать в QazaqMaqal 🇰🇿!\n\nИнтерактивный помощник по изучению казахских пословиц. Выберите команду:"
    await update.message.reply_text(welcome_text, reply_markup=MENU_KEYBOARD)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    chat_id = update.effective_chat.id
    reply = ""

    if text in ["📚 учить пословицы", "🎲 случайная пословица"]:
        item = random.choice(PROVERBS_DB)
        reply = format_proverb_card(item)

    elif text == "🎯 проверь себя":
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

    elif text == "🔍 найти по теме":
        reply = "💡 Напиши ключевое слово (например: дос, семья, родина, білім), и я найду пословицу!"

    elif text == "❤️ избранное":
        favs = user_favorites.get(chat_id, [])
        if not favs:
            reply = "📭 Твой список избранного пуст."
        else:
            await update.message.reply_text(f"❤️ Сохраненные пословицы ({len(favs)}):", reply_markup=MENU_KEYBOARD)
            for i, fav in enumerate(favs, 1):
                await update.message.reply_text(f"📌 #{i}\n{fav}")
            return

    elif text == "💾 сохранить текущее":
        last_msg = last_bot_message.get(chat_id)
        if not last_msg or "Вставьте пропущенное" in last_msg or "💡 Напиши ключевое" in last_msg:
            reply = "⚠️ Сначала выведи пословицу, чтобы ее сохранить!"
        else:
            if chat_id not in user_favorites:
                user_favorites[chat_id] = []
            if last_msg not in user_favorites[chat_id]:
                user_favorites[chat_id].append(last_msg)
                reply = "✅ Сохранено в Избранное!"
            else:
                reply = "📌 Ужe есть в избранном!"

    elif text == "🗑 очистить избранное":
        user_favorites[chat_id] = []
        reply = "🗑 Избранное очищено."

    elif text == "🏆 мой результат":
        fav_count = len(user_favorites.get(chat_id, []))
        reply = f"📊 Твой результат:\n- Сохранено пословиц: {fav_count}\n- Статус: Знаток ⭐️"

    else:
        found_local = None
        
        # Точный локальный поиск
        for p in PROVERBS_DB:
            if text in p.get("keys", []):
                found_local = p
                break
                
        if not found_local:
            for p in PROVERBS_DB:
                full_text = f"{p['maqal']} {p['translation']} {p['meaning']}".lower()
                if re.search(rf"\b{re.escape(text)}\b", full_text):
                    found_local = p
                    break
        
        if found_local:
            reply = format_proverb_card(found_local)
        else:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            reply = await ask_gemini_fallback(text)

    last_bot_message[chat_id] = reply
    await update.message.reply_text(reply, reply_markup=MENU_KEYBOARD)

# ==========================================
# 5. ТОЧКА ВХОДА
# ==========================================
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот QazaqMaqal на Gemini 3.6 успешно запущен!")
    app.run_polling()
