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

# 🔐 Безопасное получение токена
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("❌ BOT_TOKEN не установлен!")
    exit(1)

# 👤 Разрешённые пользователи (ЗАМЕНИТЕ НА СВОИ ID!)
ALLOWED_USERS = {
    157901324,  # Твой ID
    382950376   # ID твоей девушки
}

DATA_FILE = "pill_data.json"

# Расписание приёмов (UTC время для Render)
SCHEDULE = [
    {"time_utc": time(7, 0), "label": "утренняя", "hour_msk": 10},   # 10:00 МСК
    {"time_utc": time(11, 0), "label": "дневная", "hour_msk": 14},   # 14:00 МСК  
    {"time_utc": time(20, 0), "label": "вечерняя", "hour_msk": 23}   # 23:00 МСК
]

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"user_id": None, "history": {}}

def save_data(data):
    # Сохраняем данные за последние 14 дней
    if "history" in data and data["history"]:
        recent_dates = sorted(data["history"].keys())[-14:]
        data["history"] = {d: data["history"][d] for d in recent_dates if d in data["history"]}
    
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS

# === HTTP-сервер для Render ===
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
        pass

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"🌐 Health-check сервер запущен на порту {port}")
    server.serve_forever()

# Запускаем HTTP-сервер в фоне
Thread(target=run_http_server, daemon=True).start()

# === ОСНОВНОЙ КОД БОТА ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if not is_allowed(user.id):
            await update.message.reply_text("🔒 Извини, этот бот только для избранных котиков 🐾")
            return

        # Инициализируем или обновляем данные
        data = load_data()
        today = get_today()
        
        # Сохраняем user_id
        data["user_id"] = user.id
        if today not in data["history"]:
            data["history"][today] = {"утренняя": False, "дневная": False, "вечерняя": False}
        save_data(data)

        # Перезапускаем jobs для этого пользователя
        await schedule_jobs(context.application)

        await update.message.reply_text(
            "✅ Бот активирован! Напоминания придут в:\n"
            "• 10:00 (утренняя) 🐦\n"  
            "• 14:00 (дневная) ☀️\n"
            "• 23:00 (вечерняя) 🌙\n\n"
            "По московскому времени ❤️"
        )
        
        logger.info(f"✅ Пользователь {user.id} активировал бота")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в /start: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка. Попробуй позже.")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        job = context.job
        user_id = job.data["user_id"]
        pill_time = job.data["pill_time"]
        today = get_today()

        logger.info(f"🔔 Отправка напоминания: {pill_time} для пользователя {user_id}")

        # Обновляем данные на сегодня
        data = load_data()
        if today not in data["history"]:
            data["history"][today] = {"утренняя": False, "дневная": False, "вечерняя": False}
        save_data(data)

        await context.bot.send_message(
            chat_id=user_id,
            text=f"💊 Котик, пора пить {pill_time} таблеточку!\nПожалуйста, не забудь ❤️",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Выпила", callback_data=f"taken_{pill_time}")]
            ])
        )

        # Проверка через час
        context.job_queue.run_once(
            check_if_taken,
            when=3600,  # 1 час
            data={"user_id": user_id, "date": today, "pill_time": pill_time},
            name=f"check_{today}_{pill_time}"
        )
        
        logger.info(f"✅ Напоминание отправлено пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки напоминания: {e}")

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
                chat_id=157901324,  # Твой ID для уведомлений
                text=f"⚠️ Твоя котик-девушка ещё не отметила приём {pill_time} таблетки ({date}).\nМожет, стоит нежно напомнить? 💬"
            )
            logger.info(f"📢 Уведомление отправлено админу о пропущенной {pill_time} таблетке")
        except Exception as e:
            logger.error(f"❌ Не удалось отправить уведомление админу: {e}")

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
            chat_id=157901324,  # Твой ID для уведомлений
            text=f"✅ Твоя котик-девушка только что выпила {pill_time} таблеточку! 🐾\nВремя: {datetime.now().strftime('%d.%m в %H:%M')}"
        )
        logger.info(f"✅ Уведомление админу о приёме {pill_time} таблетки")
    except Exception as e:
        logger.error(f"❌ Не удалось отправить уведомление админу: {e}")

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
            chat_id=157901324,  # Твой ID для уведомлений
            text=f"📆 Отчёт за {today}:\n{taken_count}/3 приёмов"
        )
    except Exception as e:
        logger.error(f"❌ Не удалось отправить отчёт админу: {e}")

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
            chat_id=157901324,  # Твой ID для уведомлений
            text=f"📊 Недельный отчёт:\n{total_taken}/{total_possible} таблеток"
        )
    except Exception as e:
        logger.error(f"❌ Не удалось отправить недельный отчёт админу: {e}")

async def schedule_jobs(app: Application):
    try:
        data = load_data()
        user_id = data.get("user_id")
        
        if not user_id or not is_allowed(user_id):
            logger.warning("❌ User ID не установлен или пользователь не разрешён")
            return

        job_queue = app.job_queue
        if not job_queue:
            logger.error("❌ Job queue не доступна")
            return

        # Удаляем старые jobs чтобы избежать дублирования
        current_jobs = job_queue.jobs()
        for job in current_jobs:
            if job.name and (job.name.startswith("reminder_") or job.name.startswith("daily_report") or job.name.startswith("weekly_report")):
                job.schedule_removal()

        # Создаём новые jobs для напоминаний
        for pill in SCHEDULE:
            job_queue.run_daily(
                send_reminder,
                time=pill["time_utc"],
                data={"user_id": user_id, "pill_time": pill["label"]},
                name=f"reminder_{pill['label']}_{user_id}"
            )
            logger.info(f"✅ Напоминание '{pill['label']}' установлено на {pill['time_utc']} UTC ({pill['hour_msk']}:00 МСК)")

        # Ежедневный отчёт
        job_queue.run_daily(
            daily_report,
            time=time(20, 30),  # = 23:30 МСК
            name=f"daily_report_{user_id}"
        )
        logger.info("✅ Ежедневный отчёт установлен на 23:30 МСК")

        # Еженедельный отчёт (воскресенье)
        job_queue.run_daily(
            weekly_report,
            time=time(20, 30),  # = 23:30 МСК
            days=(6,),  # воскресенье (0=пн, 6=вс)
            name=f"weekly_report_{user_id}"
        )
        logger.info("✅ Еженедельный отчёт установлен на воскресенье 23:30 МСК")

        logger.info(f"✅ Все jobs успешно установлены для пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в schedule_jobs: {e}")

# === НОВЫЕ КОМАНДЫ ДЛЯ ОТЛАДКИ ===

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статус приёма таблеток сегодня"""
    if not is_allowed(update.effective_user.id):
        return
    
    data = load_data()
    today = get_today()
    day_data = data["history"].get(today, {"утренняя": False, "дневная": False, "вечерняя": False})
    
    status_text = "💊 Сегодняшний статус:\n"
    for pill, taken in day_data.items():
        status_text += f"{'✅' if taken else '❌'} {pill.capitalize()}\n"
    
    await update.message.reply_text(status_text)

async def timecheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить текущее время"""
    now_utc = datetime.utcnow()
    now_msk = now_utc + timedelta(hours=3)
    
    await update.message.reply_text(
        f"🕐 Время проверки:\n"
        f"UTC: {now_utc.strftime('%H:%M')}\n"
        f"МСК: {now_msk.strftime('%H:%M')}\n"
        f"Дата: {now_utc.strftime('%Y-%m-%d')}"
    )

async def debug_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать активные jobs"""
    if not is_allowed(update.effective_user.id):
        return
        
    job_queue = context.application.job_queue
    if not job_queue:
        await update.message.reply_text("❌ Job queue не доступна")
        return
        
    jobs = job_queue.jobs()
    if not jobs:
        await update.message.reply_text("📭 Нет активных jobs")
        return
        
    message = "📋 Активные jobs:\n"
    for i, job in enumerate(jobs, 1):
        next_run = job.next_t.strftime("%d.%m %H:%M UTC") if job.next_t else "не установлено"
        message += f"{i}. {job.name} - след. запуск: {next_run}\n"
    
    await update.message.reply_text(message)

async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовое напоминание"""
    if not is_allowed(update.effective_user.id):
        return
        
    pill_time = "утренняя"  # можно изменить на "дневная" или "вечерняя"
    
    await update.message.reply_text(f"🔔 Тестовое напоминание: {pill_time}")
    
    # Имитируем отправку напоминания
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=f"💊 ТЕСТ: Котик, пора пить {pill_time} таблеточку!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выпила", callback_data=f"taken_{pill_time}")]
        ])
    )

def main():
    application = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("time", timecheck))
    application.add_handler(CommandHandler("debug", debug_jobs))
    application.add_handler(CommandHandler("test", test_reminder))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"taken_.*"))
    
    # Запускаем планировщик jobs
    application.job_queue.run_once(schedule_jobs, when=1)
    
    logger.info("🚀 Бот запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()