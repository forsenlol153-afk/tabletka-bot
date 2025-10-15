import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import json
from datetime import datetime, time, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["BOT_TOKEN"]

# 👤 Разрешённые пользователи
ALLOWED_USERS = {
    157901324,  # Твой ID
    382950376   # ID твоей девушки
}

DATA_FILE = "/tmp/pill_data.json"

# Расписание приёмов (МСК → UTC)
SCHEDULE = [
    {"time_utc": time(7, 0), "label": "утренняя", "hour_msk": 10},
    {"time_utc": time(11, 0), "label": "дневная", "hour_msk": 14},
    {"time_utc": time(20, 0), "label": "вечерняя", "hour_msk": 23}
]

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "user_id": None,
            "history": {}
        }

def save_data(data):
    recent_dates = sorted(data["history"].keys())[-14:]
    data["history"] = {d: data["history"][d] for d in recent_dates}
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS

# === HTTP-сервер для Render (поддержка GET и HEAD) ===
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        # Отключаем логирование health-check запросов
        pass

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Запускаем HTTP-сервер в фоне
Thread(target=run_http_server, daemon=True).start()

# === ОСНОВНОЙ КОД БОТА ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("🔒 Извини, этот бот только для избранных котиков 🐾")
        return

    data = load_data()
    data["user_id"] = user.id
    today = get_today()
    data["history"].setdefault(today, {"утренняя": False, "дневная": False, "вечерняя": False})
    save_data(data)
    await update.message.reply_text("Привет, котик! Я буду напоминать тебе пить таблетки три раза в день ❤️")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data["user_id"]
    pill_time = job.data["pill_time"]
    today = get_today()

    data = load_data()
    if today not in data["history"]:
        data["history"][today] = {"утренняя": False, "дневная": False, "вечерняя": False}
    save_data(data)

    await context.bot.send_message(
        chat_id=user_id,
        text=f"Котик, пора пить {pill_time} таблеточку! 💊\nПожалуйста, не забудь ❤️",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выпила", callback_data=f"taken_{pill_time}")]
        ])
    )

    context.job_queue.run_once(
        check_if_taken,
        when=3600,
        data={"user_id": user_id, "date": today, "pill_time": pill_time},
        name=f"check_{today}_{pill_time}"
    )

async def check_if_taken(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    date = job_data["date"]
    pill_time = job_data["pill_time"]

    data = load_data()
    taken = data["history"].get(date, {}).get(pill_time, False)

    if not taken:
        try:
            await context.bot.send_message(
                chat_id=157901324,
                text=f"⚠️ Твоя котик-девушка ещё не отметила приём {pill_time} таблетки ({date}).\nМожет, стоит нежно напомнить? 💬"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not is_allowed(user_id):
        await query.message.reply_text("🔒 Ты не можешь использовать этого бота.")
        return

    data = load_data()
    if data.get("user_id") != user_id:
        await query.edit_message_text(text="Это не твоя таблетка 😉")
        return

    pill_time = query.data.replace("taken_", "")
    today = get_today()

    if today not in data["history"]:
        data["history"][today] = {"утренняя": False, "дневная": False, "вечерняя": False}
    data["history"][today][pill_time] = True
    save_data(data)

    await query.edit_message_text(text=f"Отлично! {pill_time.capitalize()} таблеточка принята! 🌟")

    try:
        await context.bot.send_message(
            chat_id=157901324,
            text=f"✅ Твоя котик-девушка только что выпила {pill_time} таблеточку! 🐾\nВремя: {datetime.now().strftime('%d.%m в %H:%M')}"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = data.get("user_id")
    if not user_id or user_id not in ALLOWED_USERS:
        return

    today = get_today()
    day_data = data["history"].get(today, {"утренняя": False, "дневная": False, "вечерняя": False})

    taken_count = sum(day_data.values())
    total = 3

    status_lines = []
    for pill in ["утренняя", "дневная", "вечерняя"]:
        status = "✅" if day_data.get(pill) else "❌"
        status_lines.append(f"{status} {pill.capitalize()}")

    message = "📊 Сегодняшний приём таблеток:\n" + "\n".join(status_lines)
    message += f"\n\nИтого: {taken_count} из {total} 💊"

    if taken_count == 3:
        message += "\n\nТы молодец! Полный успех! 🌈"
    elif taken_count == 0:
        message += "\n\nЗавтра всё получится! Я верю в тебя! 💖"

    await context.bot.send_message(chat_id=user_id, text=message)

    try:
        await context.bot.send_message(
            chat_id=157901324,
            text=f"📆 Отчёт за {today}:\n{taken_count}/3 приёмов"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить отчёт админу: {e}")

async def weekly_report(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = data.get("user_id")
    if not user_id or user_id not in ALLOWED_USERS:
        return

    today = datetime.now().date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    
    total_taken = 0
    total_possible = 0

    for d in dates:
        day_data = data["history"].get(d, {"утренняя": False, "дневная": False, "вечерняя": False})
        total_taken += sum(day_data.values())
        total_possible += 3

    message = (
        f"📈 Недельная статистика:\n"
        f"Ты приняла {total_taken} из {total_possible} таблеток! 🌟\n\n"
    )

    if total_taken == total_possible:
        message += "Ты невероятна! 100% — это круто! ✨"
    elif total_taken / total_possible >= 0.8:
        message += "Отличный результат! Так держать! 💪"
    elif total_taken / total_possible >= 0.5:
        message += "Хорошо стараешься! Продолжай в том же духе! 🌈"
    else:
        message += "Я знаю, ты можешь лучше! Завтра — новый шанс! 💖"

    await context.bot.send_message(chat_id=user_id, text=message)

    try:
        await context.bot.send_message(
            chat_id=157901324,
            text=f"📊 Недельный отчёт:\n{total_taken}/{total_possible} таблеток"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить недельный отчёт админу: {e}")

async def schedule_jobs(app: Application):
    data = load_data()
    user_id = data.get("user_id")
    if not user_id or user_id not in ALLOWED_USERS:
        return

    job_queue = app.job_queue

    for pill in SCHEDULE:
        job_queue.run_daily(
            send_reminder,
            time=pill["time_utc"],
            data={"user_id": user_id, "pill_time": pill["label"]},
            name=f"reminder_{pill['label']}"
        )

    job_queue.run_daily(
        daily_report,
        time=time(20, 30),  # = 23:30 МСК
        name="daily_report"
    )

    job_queue.run_daily(
        weekly_report,
        time=time(20, 30),  # = 23:30 МСК
        days=(6,),          # воскресенье
        name="weekly_report"
    )

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"taken_.*"))
    application.job_queue.run_once(schedule_jobs, when=1)
    application.run_polling()

if __name__ == '__main__':
    main()