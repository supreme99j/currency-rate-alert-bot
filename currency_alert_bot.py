# currency_alert_bot.py
import sqlite3
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# === НАСТРОЙКИ ===
TOKEN = "test"
DB_PATH = "user_data.db"
BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol="

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# === ФУНКЦИИ РАБОТЫ С БД ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        username TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS expectations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        symbol TEXT,
        price_min REAL,
        price_max REAL,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        triggered_at TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    conn.commit()
    conn.close()

def add_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def add_expectation(user_id, symbol, price_min, price_max):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO expectations (user_id, symbol, price_min, price_max) VALUES (?, ?, ?, ?)",
        (user_id, symbol.upper(), price_min, price_max)
    )
    conn.commit()
    conn.close()

def get_expectations(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, symbol, price_min, price_max, created_at FROM expectations WHERE user_id=? AND active=1", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_active_expectations():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, user_id, symbol, price_min, price_max FROM expectations WHERE active=1")
    rows = c.fetchall()
    conn.close()
    return rows

def trigger_expectation(exp_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE expectations SET active=0, triggered_at=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), exp_id)
    )
    conn.commit()
    conn.close()

def cancel_expectation(user_id, exp_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE expectations SET active=0 WHERE id=? AND user_id=?", (exp_id, user_id))
    conn.commit()
    conn.close()

def get_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, symbol, price_min, price_max, created_at, triggered_at
        FROM expectations
        WHERE user_id=? AND active=0 AND triggered_at IS NOT NULL
        ORDER BY triggered_at DESC
        LIMIT 10
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# === ФУНКЦИИ ДЛЯ РАБОТЫ С ЦЕНАМИ ===
def get_price(symbol: str) -> float | None:
    try:
        resp = requests.get(BINANCE_URL + symbol.upper(), timeout=5)
        data = resp.json()
        if "price" in data:
            return float(data["price"])
    except Exception as e:
        logger.error(f"Ошибка получения цены {symbol}: {e}")
    return None

# === КОМАНДЫ БОТА ===
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    add_user(user.id, user.username)
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n"
        "Я бот для отслеживания курсов валют и криптовалют.\n"
        "Введи, например:\n\n"
        "`BTCUSDT 90000-90500`\n"
        "или\n"
        "`EURUSD 1.05-1.06`\n\n"
        "Чтобы узнать список команд: /help",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "📌 Доступные команды:\n"
        "/start – начать работу с ботом\n"
        "/help – список команд\n"
        "/list – показать активные ожидания\n"
        "/cancel ID – отменить ожидание по ID\n\n"
        "/history – последние 10 срабатываний\n\n"
        "👉 Также можно просто написать: `SYMBOL min-max`\n"
        "Пример: `BTCUSDT 90000-90500`",
        parse_mode="Markdown"
    )

async def list_command(update: Update, context: CallbackContext):
    user = update.effective_user
    expectations = get_expectations(user.id)
    if not expectations:
        await update.message.reply_text("У тебя нет активных ожиданий.")
        return

    msg = "📋 Твои активные ожидания:\n"
    for exp_id, symbol, pmin, pmax, created in expectations:
        msg += f"ID {exp_id}: {symbol} {pmin}-{pmax} (создано {created})\n"
    await update.message.reply_text(msg)

async def cancel_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /cancel ID")
        return

    exp_id = int(context.args[0])
    cancel_expectation(user.id, exp_id)
    await update.message.reply_text(f"Ожидание ID {exp_id} отменено.")

async def history_command(update: Update, context: CallbackContext):
    user = update.effective_user
    history = get_history(user.id)
    if not history:
        await update.message.reply_text("Истории срабатываний пока нет.")
        return

    msg = "📜 Последние срабатывания:\n"
    for exp_id, symbol, pmin, pmax, created, triggered in history:
        msg += (f"ID {exp_id}: {symbol} {pmin}-{pmax}\n"
                f"Создано: {created}\n"
                f"Сработало: {triggered}\n\n")
    await update.message.reply_text(msg)

async def handle_message(update: Update, context: CallbackContext):
    user = update.effective_user
    text = update.message.text.strip().upper()

    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError

        symbol = parts[0]
        price_range = parts[1].split("-")
        if len(price_range) != 2:
            raise ValueError

        price_min = float(price_range[0])
        price_max = float(price_range[1])

        add_expectation(user.id, symbol, price_min, price_max)
        await update.message.reply_text(
            f"✅ Добавлено ожидание: {symbol} {price_min}-{price_max}"
        )
    except Exception:
        await update.message.reply_text(
            "❌ Неверный формат. Используй:\n`SYMBOL min-max`\nПример: `BTCUSDT 90000-90500`",
            parse_mode="Markdown"
        )

# === ПРОВЕРКА ОЖИДАНИЙ ===
async def check_expectations(context: CallbackContext):
    expectations = get_all_active_expectations()
    for exp_id, user_id, symbol, pmin, pmax in expectations:
        price = get_price(symbol)
        if price is None:
            continue

        if pmin <= price <= pmax:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔔 {symbol} достиг диапазона {pmin}-{pmax}\nТекущая цена: {price}"
                )
                trigger_expectation(exp_id)
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления: {e}")

# === ЗАПУСК БОТА ===
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_repeating(check_expectations, interval=15, first=5)

    app.run_polling()

if __name__ == "__main__":
    main()
