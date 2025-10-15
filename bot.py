import logging
import os
import json
from datetime import datetime, time, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен из переменной окружения (безопасно!)
TOKEN = os.environ["BOT_TOKEN"]

# Файл данных — сохраняем в /tmp (работает на Render)
DATA_FILE = "/tmp/user_data.json"

# Загрузка данных
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_taken": None, "user_id": None}

# Сохранение данных
def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Мотивирующие фразы
MOTIVATIONAL_PHRASES = [
    "Отлично, что ты выпила таблеточку — ты настоящая героиня!",
    "Молодец! Ты заботишься о себе — это самое важное 💖",
    "Ты супер! Так держать 👏",
    "Таблеточка принята? Уже на пути к здоровью! 🌿",
    "Я горжусь тобой! 🐱"
]

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    data["user_id"] = user.id
    save_data(data)
    await update.message.reply_text(
        "Привет, котик! 💊\nЯ буду напоминать тебе пить таблетки в 10:00, 14:00 и 23:00.\n\nНажми на кнопку, когда выпьёшь — я похвалю тебя! ❤️"
    )

# Отправка напоминания
async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data["user_id"]
    dose = job.data.get("dose", 1)

    # Разные сообщения для разных приёмов
    messages = {
        1: "Котик, пора пить утреннюю таблеточку! 🌞",
        2: "Котик, не забудь про дневную таблеточку! ☀️",
        3: "Котик, выпей вечернюю таблеточку перед сном 💤",
    }
    text = messages.get(dose, "Котик, выпей таблеточку 🐱")

    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выпила", callback_data=f"taken_{dose}")]
        ])
    )

# Обработка кнопки
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = load_data()

    if data.get("user_id") != user_id:
        await query.edit_message_text(text="Это не твоя таблетка 😉")
        return

    # Сохраняем факт приёма
    data["last_taken"] = datetime.now().isoformat()
    save_data(data)

    # Похвала
    await query.edit_message_text(text=MOTIVATIONAL_PHRASES[0])

# Планировщик всех напоминаний
async def schedule_all_reminders(app: Application):
    data = load_data()
    user_id = data.get("user_id")
    if not user_id:
        return

    # ⚠️ ЗАМЕНИ ЧАСОВОЙ ПОЯС ПОД СЕБЯ!
    # Примеры:
    # Москва, Минск       → timedelta(hours=3)
    # Киев, Рига          → timedelta(hours=2)
    # Екатеринбург        → timedelta(hours=5)
    # Лондон              → timedelta(hours=0)
    # Нью-Йорк (летом)    → timedelta(hours=-4)
    tz = timezone(timedelta(hours=3))  # ← ИЗМЕНИ ЭТО!

    times = [
        time(10, 0, tzinfo=tz),   # утро
        time(14, 0, tzinfo=tz),   # день
        time(23, 0, tzinfo=tz),   # ночь
    ]

    for i, t in enumerate(times):
        app.job_queue.run_daily(
            send_reminder,
            time=t,
            data={"user_id": user_id, "dose": i + 1},
            name=f"reminder_dose_{i+1}"
        )
        logger.info(f"Запланировано напоминание на {t}")

# Основная функция
def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"taken_\d"))

    # Запуск планировщика после старта
    application.job_queue.run_once(schedule_all_reminders, when=1)

    application.run_polling()

if __name__ == '__main__':
    main()