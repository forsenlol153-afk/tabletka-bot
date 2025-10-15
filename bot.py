import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import json
from datetime import datetime, time

# Логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен из переменной окружения (не в коде!)
TOKEN = os.environ["BOT_TOKEN"]

# Файл данных — сохраняем в /tmp (работает на Render)
DATA_FILE = "/tmp/user_data.json"

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_taken": None, "user_id": None}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

MOTIVATIONAL_PHRASES = [
    "Отлично, что ты выпила таблеточку — ты настоящая героиня!",
    "Молодец! Ты заботишься о себе — это самое важное 💖",
    "Ты супер! Так держать 👏",
    "Таблеточка принята? Уже на пути к здоровью! 🌿",
    "Я горжусь тобой! 🐱"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    data["user_id"] = user.id
    save_data(data)
    await update.message.reply_text("Привет, котик! Я буду напоминать тебе пить таблетки ❤️")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data["user_id"]
    await context.bot.send_message(
        chat_id=user_id,
        text="Котик, выпей таблеточку 🐱\nКотик, выпей, пожалуйста, таблеточку",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выпила", callback_data="taken")]
        ])
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = load_data()
    
    if data.get("user_id") != user_id:
        await query.edit_message_text(text="Это не твоя таблетка 😉")
        return

    data["last_taken"] = datetime.now().isoformat()
    save_data(data)
    await query.edit_message_text(text=MOTIVATIONAL_PHRASES[0])

async def schedule_reminders(app: Application):
    data = load_data()
    user_id = data.get("user_id")
    if user_id:
        app.job_queue.run_daily(
            send_reminder,
            time=time(16, 0),  # 19:00 по UTC+3 → см. примечание ниже!
            data={"user_id": user_id},
            name="daily_reminder"
        )

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="taken"))
    application.job_queue.run_once(schedule_reminders, when=1)
    application.run_polling()

if __name__ == '__main__':
    main()