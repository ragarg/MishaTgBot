import asyncio
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime
from collections import defaultdict

import sqlite3

NOT_COMPLETED = 0
PENDING  = 1
COMPLETED = 2

# Настройки
TIMEZONE = pytz.timezone("Europe/Moscow")  # Установите свой часовой пояс
TOKEN = "8419794805:AAHekKPaIyAw1YoyJcfMskZeb4lPwI9xMPM"
MORNING_TIME = (8, 0)  # Утреннее время (час, минута)
EVENING_TIME = (21, 0)  # Вечернее время (час, минута)

#База данных
DB_PATH = "reminders.db"
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            morning_reminded INTEGER DEFAULT 1,
            evening_reminded INTEGER DEFAULT 1,
            confirmed INTEGER DEFAULT 0,
            remind_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_user_data(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT morning_reminded, evening_reminded, confirmed, remind_count FROM users WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            'morning_reminded': row[0],
            'evening_reminded': row[1],
            'confirmed': bool(row[2]),
            'remind_count': row[3]
        }
    else:
        return None

def save_user_data(user_id: int, data: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO users (user_id, morning_reminded, evening_reminded, confirmed, remind_count)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            morning_reminded=excluded.morning_reminded,
            evening_reminded=excluded.evening_reminded,
            confirmed=excluded.confirmed,
            remind_count=excluded.remind_count
    ''', (user_id, int(data['morning_reminded']), int(data['evening_reminded']), int(data['confirmed']), data['remind_count']))
    conn.commit()
    conn.close()

def add_subscriber(user_id: int):
    data = get_user_data(user_id)
    save_user_data(user_id,
        {
            'morning_reminded': NOT_COMPLETED,
            'evening_reminded': NOT_COMPLETED,
            'confirmed': False,
            'remind_count': 0
        })  # просто гарантируем, что запись есть

def remove_subscriber(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_all_subscribers():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM users')
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_confirmation_keyboard(reminder_type):
    keyboard = [
        [InlineKeyboardButton("✅ Приняла", callback_data=f"confirmed_{reminder_type}_reminded"),
         InlineKeyboardButton("⏺ Отложить", callback_data=f"postpone_{reminder_type}_reminded")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    add_subscriber(user_id)
    await update.message.reply_text("✅ ❤️Чудесная девочка подписалась на напоминания!❤️")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    remove_subscriber(user_id)
    await update.message.reply_text("❌ Отписались от напоминаний.")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    user_data = get_user_data(user_id);
    if user_data:
        user_data['confirmed'] = True
        user_data['remind_count'] = 0
        await update.message.reply_text("✅ Прием подтвержден!")
    save_user_data(user_id, user_data)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать текущий статус"""
    user_id = update.effective_chat.id
    
    data = get_user_data(user_id);
    if not data:
        await update.message.reply_text("❌ Вы не подписаны на напоминания.")
        return
    print(data)
    status_text = f"📊 Ваш статус:\n"
    status_text += f"Подписка: {'✅ активна' if data else '❌ неактивна'}\n"

    morning_status = '❌ не выполнено'
    if data['morning_reminded'] == PENDING:
        morning_status = '🔔 активно'
    elif data['morning_reminded'] == COMPLETED:
        morning_status = '✅ выполнено'
    status_text += f"Утреннее напоминание: {morning_status}\n"

    evening_status = '❌ не выполнено'
    if data['evening_reminded'] == PENDING:
        evening_status = '🔔 активно'
    elif data['evening_reminded'] == COMPLETED:
        evening_status = '✅ выполнено'
    status_text += f"Вечернее напоминание: {evening_status}\n"
    status_text += f"Подтверждено: {'✅ да' if data['confirmed'] else '❌ нет'}\n"
    status_text += f"Кол-во повторов: {data['remind_count']}"
    
    await update.message.reply_text(status_text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    parts = query.data.split('_', 1)  # maxsplit=1, чтобы не резать, если в типе тоже будет '_'

    id, data_type = parts
    print(id, data_type)
    if id == "confirmed":
        user_data['confirmed'] = True
        user_data['remind_count'] = 0
        user_data[data_type] = COMPLETED
        await query.edit_message_text("✅ Прием подтвержден!")
    elif id == "postpone":
        user_data['remind_count'] += 1
        if user_data['remind_count'] >= 5:
            await query.edit_message_text("⚠️ Примите таблетки как можно скорее!")
        else:
            await query.edit_message_text(f"⏸ Отложено ({user_data['remind_count']} раз)")
    save_user_data(user_id, user_data)

async def send_main_reminder(app: Application, reminder_type: str):
    current_time = datetime.now(TIMEZONE).strftime("%H:%M")
    if reminder_type == "morning":
        message = f"🌅 Доброе утро, мое солнышко! ({current_time})\nПора принять утренние таблетки, чтобы эта прекрасная девочка чувствоала себя просто чудесно 🥰)."
        for user_id in get_all_subscribers():
            user_data = get_user_data(user_id);
            user_data['confirmed'] = False
            user_data['remind_count'] = 0
            user_data['morning_reminded'] = PENDING
            print(user_data)
            save_user_data(user_id, user_data)
    else:
        message = f"🌙 Добрый вечер! ({current_time})\nПора принять вечерние таблетки, чтобы спокойненько можно было уснуть💤."
        for user_id in get_all_subscribers():
            user_data = get_user_data(user_id);
            user_data['confirmed'] = False
            user_data['remind_count'] = 0
            user_data['evening_reminded'] = PENDING
            save_user_data(user_id, user_data)

    print(user_data)
    for user_id in get_all_subscribers():
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=message,
                reply_markup=get_confirmation_keyboard(reminder_type)
            )
        except Exception as e:
            print(f"Ошибка отправки для {user_id}: {e}")

async def send_hourly_reminder(app: Application):
    current_hour = datetime.now(TIMEZONE).hour
    is_morning_time = 5 <= current_hour < 12
    is_evening_time = 18 <= current_hour < 24

    for user_id in get_all_subscribers():
        try:
            data = get_user_data(user_id);
            should_remind = False
            reminder_type = ""
            if is_morning_time and data['morning_reminded'] == PENDING and not data['confirmed']:
                should_remind = True
                reminder_type = "утренние"
            elif is_evening_time and data['evening_reminded'] == PENDING and not data['confirmed']:
                should_remind = True
                reminder_type = "вечерние"

            if should_remind and data['remind_count'] < 10:
                data['remind_count'] += 1
                count_text = ""
                if data['remind_count'] >= 3:
                    count_text = f"\n⚠️ Это уже {data['remind_count']}-е напоминание!"
                await app.bot.send_message(
                    chat_id=user_id,
                    text=f"🔔 Напоминание о {reminder_type} таблетках{count_text}",
                    reply_markup=get_confirmation_keyboard(reminder_type)
                )
            save_user_data(user_id, data)
        except Exception as e:
            print(f"Ошибка отправки часового напоминания для {user_id}: {e}")

async def reset_daily_status():
    for user_id in get_all_subscribers():
        data = get_user_data(user_id);
        data['morning_reminded'] = NOT_COMPLETED
        data['evening_reminded'] = NOT_COMPLETED
        data['confirmed'] = False
        data['remind_count'] = 0
        save_user_data(user_id, data)

def main():
    init_db()
    # Создаем event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Создаем приложение бота
    application = Application.builder().token(TOKEN).build()

    # Настраиваем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Создаем планировщик и передаем ему event loop
    scheduler = AsyncIOScheduler(event_loop=loop, timezone=TIMEZONE)

    # Добавляем задания
    scheduler.add_job(
        send_main_reminder,
        trigger=CronTrigger(hour=MORNING_TIME[0], minute=MORNING_TIME[1], timezone=TIMEZONE),
        args=[application, "morning"],
        id="morning_reminder"
    )
    scheduler.add_job(
        send_main_reminder,
        trigger=CronTrigger(hour=EVENING_TIME[0], minute=EVENING_TIME[1], timezone=TIMEZONE),
        args=[application, "evening"],
        id="evening_reminder"
    )
    scheduler.add_job(
        send_hourly_reminder,
        trigger=CronTrigger(minute=0, timezone=TIMEZONE),
        args=[application],
        id="hourly_reminder"
    )
    scheduler.add_job(
        reset_daily_status,
        trigger=CronTrigger(hour=0, minute=1, timezone=TIMEZONE),
        id="reset_status"
    )

    # Запускаем планировщик
    scheduler.start()

    print("Бот запущен...")

    try:
        # Запускаем бота
        loop.run_until_complete(application.run_polling())
    except KeyboardInterrupt:
        print("Бот остановлен...")
    finally:
        scheduler.shutdown()
        loop.close()

if __name__ == "__main__":
    main()