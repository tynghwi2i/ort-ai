import asyncio
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import google.generativeai as genai

# ============================================================
# 🔑 ВСТАВЬ СВОИ КЛЮЧИ ЗДЕСЬ
# ============================================================
TELEGRAM_TOKEN = "8705362343:AAE2GjeNRIUWqQDziko5VM7s1CYP_gSQIk0"
GEMINI_API_KEY = "AIzaSyCgwDuSAI8EJiBG4PR5YrscE4gggjGh4Bw"
# ============================================================

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction="""
    Ты ORT AI — умный репетитор для подготовки к ОРТ в Кыргызстане.
    Правила:
    - Всегда отвечай на русском языке
    - Объясняй просто и понятно для школьника 11 класса
    - Используй эмодзи чтобы текст был живым
    - Помни всё что говорил пользователь в этом разговоре
    - Учитывай уровень знаний пользователя
    - Давай конкретные примеры
    - Если пользователь ошибся — объясни мягко
    - Мотивируй пользователя продолжать учиться
    Предметы ОРТ: математика, русский язык, кыргызский язык,
    биология, химия, физика, история КР, английский язык.
    """
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# ============================================================
# 🧠 ПАМЯТЬ РАЗГОВОРОВ
# ============================================================
chat_sessions = {}
user_states = {}

def get_chat(user_id):
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    return chat_sessions[user_id]

async def ask_ai(user_id, prompt):
    chat = get_chat(user_id)
    response = chat.send_message(prompt)
    return response.text

def clear_memory(user_id):
    if user_id in chat_sessions:
        del chat_sessions[user_id]

# ============================================================
# 💾 БАЗА ДАННЫХ
# ============================================================
def init_db():
    conn = sqlite3.connect("ortai.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            is_premium INTEGER DEFAULT 0,
            daily_questions INTEGER DEFAULT 0,
            daily_topics INTEGER DEFAULT 0,
            last_reset TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            correct INTEGER DEFAULT 0,
            wrong INTEGER DEFAULT 0,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("ortai.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, name):
    conn = sqlite3.connect("ortai.db")
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("INSERT OR IGNORE INTO users (user_id, name, last_reset) VALUES (?, ?, ?)",
              (user_id, name, today))
    conn.commit()
    conn.close()

def reset_daily(user_id):
    conn = sqlite3.connect("ortai.db")
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT last_reset FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row and row[0] != today:
        c.execute("UPDATE users SET daily_questions=0, daily_topics=0, last_reset=? WHERE user_id=?",
                  (today, user_id))
        conn.commit()
    conn.close()

def increment(user_id, field):
    conn = sqlite3.connect("ortai.db")
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = {field} + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_progress(user_id, subject, correct):
    conn = sqlite3.connect("ortai.db")
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT id FROM progress WHERE user_id=? AND subject=? AND date=?",
              (user_id, subject, today))
    row = c.fetchone()
    if row:
        field = "correct" if correct else "wrong"
        c.execute(f"UPDATE progress SET {field}={field}+1 WHERE id=?", (row[0],))
    else:
        c.execute("INSERT INTO progress (user_id, subject, correct, wrong, date) VALUES (?,?,?,?,?)",
                  (user_id, subject, 1 if correct else 0, 0 if correct else 1, today))
    conn.commit()
    conn.close()

def get_progress(user_id):
    conn = sqlite3.connect("ortai.db")
    c = conn.cursor()
    c.execute("SELECT subject, SUM(correct), SUM(wrong) FROM progress WHERE user_id=? GROUP BY subject",
              (user_id,))
    data = c.fetchall()
    conn.close()
    return data

def get_readiness(user_id):
    progress = get_progress(user_id)
    if not progress:
        return 0
    total_c = sum(r[1] for r in progress)
    total_w = sum(r[2] for r in progress)
    total = total_c + total_w
    return int((total_c / total) * 100) if total > 0 else 0

def check_limit(user_id, field, limit):
    user = get_user(user_id)
    if not user:
        return False
    if user[2]:  # is_premium
        return False
    idx = 3 if field == "daily_questions" else 4
    return user[idx] >= limit

# ============================================================
# ⌨️ КЛАВИАТУРЫ
# ============================================================
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📚 Объяснить тему"), KeyboardButton(text="✅ Пройти тест")],
        [KeyboardButton(text="💬 Спросить ИИ"), KeyboardButton(text="📊 Мой прогресс")],
        [KeyboardButton(text="🏆 Готовность к ОРТ"), KeyboardButton(text="🔄 Очистить память")],
        [KeyboardButton(text="💎 Premium"), KeyboardButton(text="ℹ️ Помощь")]
    ], resize_keyboard=True)

def subjects_kb(action):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📐 Математика", callback_data=f"{action}_математика"),
         InlineKeyboardButton(text="🔤 Русский", callback_data=f"{action}_русский")],
        [InlineKeyboardButton(text="📖 Кыргызский", callback_data=f"{action}_кыргызский"),
         InlineKeyboardButton(text="🧬 Биология", callback_data=f"{action}_биология")],
        [InlineKeyboardButton(text="⚗️ Химия", callback_data=f"{action}_химия"),
         InlineKeyboardButton(text="🌍 История КР", callback_data=f"{action}_история")],
        [InlineKeyboardButton(text="🌐 Английский", callback_data=f"{action}_английский"),
         InlineKeyboardButton(text="⚡ Физика", callback_data=f"{action}_физика")]
    ])

def answers_kb(subject):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="A", callback_data=f"ans_{subject}_A"),
         InlineKeyboardButton(text="B", callback_data=f"ans_{subject}_B"),
         InlineKeyboardButton(text="C", callback_data=f"ans_{subject}_C"),
         InlineKeyboardButton(text="D", callback_data=f"ans_{subject}_D")]
    ])

# ============================================================
# 👋 СТАРТ
# ============================================================
@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    create_user(user_id, name)
    await message.answer(
        f"👋 Салам, *{name}*!\n\n"
        f"Мен *ORT AI* — сенин акылдуу репетиторуңмун 🤖📚\n\n"
        f"✨ *Менде эмне бар:*\n"
        f"• 📚 Кандай болсо да теманы түшүндүрөм\n"
        f"• ✅ ОРТ форматында тест берем\n"
        f"• 💬 Каалаган суроого жооп берем\n"
        f"• 🧠 Сени эстейм — алдыңкы сабактарды унутпайм\n"
        f"• 📊 Прогрессиңди көрсөтөм\n\n"
        f"*Бесплатно:* 10 тест + 3 тема в день\n"
        f"*Premium 💎:* безлимит за 199 сом/мес\n\n"
        f"Баштайлы! 👇",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

# ============================================================
# 📚 ОБЪЯСНИТЬ ТЕМУ
# ============================================================
@dp.message(F.text == "📚 Объяснить тему")
async def explain_start(message: types.Message):
    if check_limit(message.from_user.id, "daily_topics", 3):
        await message.answer(
            "⚠️ *Бесплатный лимит: 3 темы в день*\n\n"
            "💎 Premium — безлимит за 199 сом/мес!",
            parse_mode="Markdown"
        )
        return
    await message.answer("📚 *Выбери предмет:*", parse_mode="Markdown",
                         reply_markup=subjects_kb("topic"))

# ============================================================
# ✅ ПРОЙТИ ТЕСТ
# ============================================================
@dp.message(F.text == "✅ Пройти тест")
async def test_start(message: types.Message):
    if check_limit(message.from_user.id, "daily_questions", 10):
        await message.answer(
            "⚠️ *Бесплатный лимит: 10 вопросов в день*\n\n"
            "💎 Premium — безлимит за 199 сом/мес!",
            parse_mode="Markdown"
        )
        return
    await message.answer("✅ *Выбери предмет для теста:*", parse_mode="Markdown",
                         reply_markup=subjects_kb("test"))

# ============================================================
# 💬 СПРОСИТЬ ИИ
# ============================================================
@dp.message(F.text == "💬 Спросить ИИ")
async def free_chat(message: types.Message):
    user_states[message.from_user.id] = {"state": "free_chat"}
    await message.answer(
        "💬 *Свободный чат с ИИ*\n\n"
        "🧠 Я помню всё что ты мне говорил!\n\n"
        "Задай любой вопрос по учёбе или ОРТ:\n"
        "• *Объясни мне логарифмы*\n"
        "• *Почему я неправильно решил задачу?*\n"
        "• *Составь мне план на неделю*\n\n"
        "_Для выхода нажми любую кнопку меню_",
        parse_mode="Markdown"
    )

# ============================================================
# 🔄 ОЧИСТИТЬ ПАМЯТЬ
# ============================================================
@dp.message(F.text == "🔄 Очистить память")
async def clear_chat(message: types.Message):
    clear_memory(message.from_user.id)
    user_states.pop(message.from_user.id, None)
    await message.answer(
        "🔄 *Память очищена!*\n\nНачинаем с чистого листа 📝",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

# ============================================================
# 📊 ПРОГРЕСС
# ============================================================
@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message):
    progress = get_progress(message.from_user.id)
    if not progress:
        await message.answer("📊 Пока нет данных.\n\nПройди тест! ✅")
        return
    text = "📊 *Твой прогресс:*\n\n"
    for subject, correct, wrong in progress:
        total = correct + wrong
        percent = int((correct / total) * 100) if total > 0 else 0
        bar = "🟩" * (percent // 10) + "⬜" * (10 - percent // 10)
        text += f"*{subject}*\n{bar} {percent}%\n✅ {correct} | ❌ {wrong}\n\n"
    await message.answer(text, parse_mode="Markdown")

# ============================================================
# 🏆 ГОТОВНОСТЬ К ОРТ
# ============================================================
@dp.message(F.text == "🏆 Готовность к ОРТ")
async def readiness(message: types.Message):
    user_id = message.from_user.id
    percent = get_readiness(user_id)
    progress = get_progress(user_id)
    bar = "🟩" * (percent // 10) + "⬜" * (10 - percent // 10)

    if percent >= 80:
        level = "🔥 Отлично! Ты готов к ОРТ!"
    elif percent >= 60:
        level = "💪 Хорошо! Продолжай!"
    elif percent >= 40:
        level = "📈 Неплохо, нужно больше практики"
    else:
        level = "📚 Нужно больше заниматься"

    weak = [s for s, c, w in progress if (c + w) > 0 and c / (c + w) < 0.6]
    weak_text = ", ".join(weak) if weak else "Все предметы в норме 👍"

    advice = await ask_ai(user_id,
        f"Мой результат по тестам ОРТ: {percent}%. "
        f"Слабые предметы: {weak_text}. "
        f"Дай 2 конкретных совета как улучшить. Кратко с эмодзи."
    )

    await message.answer(
        f"🏆 *Готовность к ОРТ*\n\n"
        f"{bar}\n*{percent}%* — {level}\n\n"
        f"⚠️ *Слабые места:* {weak_text}\n\n"
        f"💡 *Советы ИИ:*\n{advice}",
        parse_mode="Markdown"
    )

# ============================================================
# 💎 PREMIUM
# ============================================================
@dp.message(F.text == "💎 Premium")
async def premium(message: types.Message):
    await message.answer(
        "💎 *ORT AI Premium*\n\n"
        "*Бесплатно:*\n"
        "• 10 тестов в день\n"
        "• 3 темы в день\n\n"
        "*Premium — 199 сом/месяц:*\n"
        "• ♾ Безлимитные тесты и темы\n"
        "• 🧠 Расширенная память разговора\n"
        "• 📋 Персональный план подготовки\n"
        "• 🎯 Анализ слабых мест\n"
        "• 📄 PDF-отчёт для родителей\n\n"
        "👨‍🏫 Репетитор = 3000 сом/час\n"
        "🤖 ORT AI = 199 сом/месяц\n\n"
        "📩 Для оплаты: @твой_username",
        parse_mode="Markdown"
    )

# ============================================================
# ℹ️ ПОМОЩЬ
# ============================================================
@dp.message(F.text == "ℹ️ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "ℹ️ *ORT AI — Помощь*\n\n"
        "• *📚 Объяснить тему* — выбери предмет и напиши тему\n"
        "• *✅ Пройти тест* — вопросы в формате ОРТ\n"
        "• *💬 Спросить ИИ* — свободный чат с памятью\n"
        "• *📊 Прогресс* — статистика по предметам\n"
        "• *🏆 Готовность* — % готовности к ОРТ\n"
        "• *🔄 Очистить память* — начать новый сеанс\n"
        "• *💎 Premium* — безлимит за 199 сом/мес\n\n"
        "По вопросам: @твой_username",
        parse_mode="Markdown"
    )

# ============================================================
# 🔄 CALLBACKS
# ============================================================
@dp.callback_query(F.data.startswith("topic_"))
async def topic_subject(callback: types.CallbackQuery):
    subject = callback.data.replace("topic_", "")
    user_states[callback.from_user.id] = {"state": "waiting_topic", "subject": subject}
    await callback.message.edit_text(
        f"📚 *{subject.capitalize()}*\n\n"
        f"Напиши тему которую хочешь изучить:\n\n"
        f"Например:\n"
        f"• Математика → *квадратные уравнения*\n"
        f"• Русский → *причастный оборот*\n"
        f"• История → *Манас эпосу*",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("test_"))
async def test_subject(callback: types.CallbackQuery):
    subject = callback.data.replace("test_", "")
    user_id = callback.from_user.id
    await callback.message.edit_text(f"⏳ Генерирую вопрос по *{subject}*...", parse_mode="Markdown")

    prompt = (
        f"Создай 1 тестовый вопрос для ОРТ по предмету: {subject}\n\n"
        f"Формат СТРОГО:\n"
        f"❓ *Вопрос:* [вопрос]\n\n"
        f"A) [вариант]\nB) [вариант]\nC) [вариант]\nD) [вариант]\n\n"
        f"✅ Правильный ответ: [только буква]\n"
        f"💡 Объяснение: [1-2 предложения]"
    )

    response_text = await ask_ai(user_id, prompt)

    correct = "A"
    for line in response_text.split("\n"):
        if "Правильный ответ:" in line:
            for letter in ["A", "B", "C", "D"]:
                if letter in line:
                    correct = letter
                    break

    user_states[user_id] = {
        "state": "answering",
        "subject": subject,
        "correct": correct,
        "question_text": response_text
    }
    increment(user_id, "daily_questions")

    await callback.message.edit_text(
        f"✅ *Тест — {subject.capitalize()}*\n\n{response_text}\n\n👇 *Выбери ответ:*",
        parse_mode="Markdown",
        reply_markup=answers_kb(subject)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("ans_"))
async def process_answer(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    subject = parts[1]
    user_answer = parts[2]
    user_id = callback.from_user.id

    state_data = user_states.get(user_id, {})
    if state_data.get("state") != "answering":
        await callback.answer("Начни новый тест!")
        return

    correct = state_data.get("correct", "A")
    is_correct = user_answer == correct
    save_progress(user_id, subject, is_correct)

    result = "✅ *Правильно! Молодец!* 🎉" if is_correct else f"❌ *Неправильно.*\nПравильный ответ: *{correct}*"
    question_text = state_data.get("question_text", "")
    user_states.pop(user_id, None)

    await callback.message.edit_text(
        f"{question_text}\n\n"
        f"Твой ответ: *{user_answer}*\n{result}\n\n"
        f"_Продолжай практиковаться! 💪_",
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# 📝 ОБРАБОТКА ТЕКСТА
# ============================================================
@dp.message()
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    reset_daily(user_id)

    state_data = user_states.get(user_id, {})
    state = state_data.get("state")

    if state == "waiting_topic":
        subject = state_data.get("subject")
        topic = message.text
        user_states.pop(user_id, None)

        await message.answer(f"⏳ Объясняю *{topic}*...", parse_mode="Markdown")

        response = await ask_ai(user_id,
            f"Объясни тему '{topic}' по предмету {subject} для школьника 11 класса КР.\n"
            f"Структура:\n"
            f"1️⃣ Краткое определение\n"
            f"2️⃣ Главное правило / формула\n"
            f"3️⃣ Простой пример\n"
            f"4️⃣ Типичная ошибка на ОРТ"
        )
        increment(user_id, "daily_topics")

        await message.answer(
            f"📚 *{topic} — {subject.capitalize()}*\n\n{response}",
            parse_mode="Markdown",
            reply_markup=main_kb()
        )

    elif state == "free_chat":
        await message.answer("⏳ Думаю...")
        response = await ask_ai(user_id, message.text)
        await message.answer(response, parse_mode="Markdown")

    else:
        await message.answer("Выбери действие 👇", reply_markup=main_kb())

# ============================================================
# 🚀 ЗАПУСК
# ============================================================
async def main():
    init_db()
    print("✅ ORT AI Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
