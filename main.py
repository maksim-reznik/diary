import sqlite3
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, \
    ConversationHandler

# Константы
DB_FILE = "diary_db.db"  # Название файла базы данных
BOT_TOKEN = "7472392075:AAECVXgVHUt4g3E5xmF4oFNascVQYttJD4E"  # Токен бота
STATE_WRITE = 1  # Состояние написания записи
STATE_VIEW = 2  # Состояние просмотра записей


class DiaryDB:
    """Класс для работы с базой данных дневника"""

    def __init__(self, db_file):
        """Инициализация соединения с базой данных"""
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self._setup_db()

    def _setup_db(self):
        """Создание таблиц в базе данных (если они не существуют)"""
        cur = self.conn.cursor()
        # Таблица пользователей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Таблица записей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT NOT NULL,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        self.conn.commit()

    def add_user(self, user_id, username, first_name, last_name):
        """Добавление нового пользователя в базу данных"""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) "
            "VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, last_name)
        )
        self.conn.commit()

    def add_entry(self, user_id, text):
        """Добавление новой записи в дневник"""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO entries (user_id, text) VALUES (?, ?)",
            (user_id, text)
        )
        self.conn.commit()
        return cur.lastrowid  # Возвращаем ID созданной записи

    def get_entries(self, user_id, limit=10):
        """Получение списка записей пользователя (по умолчанию 10 последних)"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, text, created FROM entries "
            "WHERE user_id = ? ORDER BY created DESC LIMIT ?",
            (user_id, limit)
        )
        return cur.fetchall()

    def get_entry(self, entry_id):
        """Получение конкретной записи по ID"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT text, created FROM entries WHERE id = ?",
            (entry_id,)
        )
        return cur.fetchone()

    def get_stats(self, user_id):
        """Получение статистики пользователя"""
        cur = self.conn.cursor()

        # Количество записей
        cur.execute("SELECT COUNT(*) FROM entries WHERE user_id = ?", (user_id,))
        count = cur.fetchone()[0]

        # Общее количество символов
        cur.execute("SELECT SUM(LENGTH(text)) FROM entries WHERE user_id = ?", (user_id,))
        chars = cur.fetchone()[0] or 0

        # Дата регистрации
        cur.execute("SELECT reg_date FROM users WHERE user_id = ?", (user_id,))
        reg_date = datetime.strptime(cur.fetchone()[0], "%Y-%m-%d %H:%M:%S")

        # Время использования бота
        used_time = datetime.now() - reg_date

        return {
            "count": count,  # Количество записей
            "chars": chars,  # Сумма символов
            "reg_date": reg_date,  # Дата регистрации
            "used_time": used_time  # Время использования
        }


# Инициализация базы данных
db = DiaryDB(DB_FILE)


# ========== Обработчики команд ==========

async def start(update, context):
    """Обработка команды /start - приветственное сообщение"""
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)

    await update.message.reply_text(
        "📘 *Личный дневник*\n\n"
        "Записывайте мысли и события. Доступные команды:\n"
        "/new - Новая запись\n"
        "/list - Просмотр записей\n"
        "/stats - Статистика\n"
        "/help - Помощь",
        parse_mode="Markdown"
    )


async def help_cmd(update, context):
    """Обработка команды /help - справочная информация"""
    await update.message.reply_text(
        "ℹ️ *Помощь*\n\n"
        "/new - Создать запись\n"
        "/list - Просмотреть записи\n"
        "/stats - Ваша статистика",
        parse_mode="Markdown"
    )


async def new_entry(update, context):
    """Обработка команды /new - начало создания новой записи"""
    context.user_data["entry_parts"] = []  # Инициализация списка для частей записи

    # Создаем кнопку "Готово"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Готово", callback_data="done")]
    ])

    await update.message.reply_text(
        "✍️ Напишите текст записи. Можно несколько сообщений.\n"
        "Нажмите 'Готово' или /done когда закончите.",
        reply_markup=keyboard
    )

    return STATE_WRITE  # Переход в состояние написания


async def get_text(update, context):
    """Получение текста записи (в состоянии STATE_WRITE)"""
    context.user_data["entry_parts"].append(update.message.text)
    return STATE_WRITE


async def save_entry(update, context):
    """Сохранение записи (нажатие кнопки 'Готово')"""
    query = update.callback_query
    await query.answer()

    # Объединяем все части текста
    full_text = "\n\n".join(context.user_data["entry_parts"])
    # Сохраняем в базу данных
    entry_id = db.add_entry(update.effective_user.id, full_text)
    # Очищаем временные данные
    del context.user_data["entry_parts"]

    # Подсчет статистики записи
    chars = len(full_text)
    words = len(full_text.split())

    await query.edit_message_text(
        f"📝 Запись #{entry_id} сохранена!\n"
        f"Символов: {chars}, слов: {words}"
    )

    return ConversationHandler.END  # Завершение машины состояний


async def cancel_entry(update, context):
    """Отмена создания записи"""
    if "entry_parts" in context.user_data:
        del context.user_data["entry_parts"]

    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END


async def show_entries(update, context):
    """Обработка команды /list - отображение списка записей"""
    entries = db.get_entries(update.effective_user.id)

    if not entries:
        await update.message.reply_text("📭 Нет записей")
        return ConversationHandler.END

    # Создаем кнопки для каждой записи
    buttons = []
    for entry in entries:
        entry_id, _, date_str = entry
        date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        buttons.append([
            InlineKeyboardButton(date.strftime("%d.%m %H:%M"), callback_data=f"show_{entry_id}")
        ])

    # Добавляем кнопку закрытия
    buttons.append([InlineKeyboardButton("❌ Закрыть", callback_data="close")])

    await update.message.reply_text(
        "📚 Ваши записи:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    return STATE_VIEW  # Переход в состояние просмотра


async def show_entry(update, context):
    """Показ конкретной записи (по нажатию кнопки)"""
    query = update.callback_query
    await query.answer()

    # Получаем ID записи из callback_data
    entry_id = int(query.data.split("_")[1])
    entry = db.get_entry(entry_id)

    if not entry:
        await query.edit_message_text("⚠️ Ошибка")
        return STATE_VIEW

    text, date_str = entry
    date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")

    # Отображаем запись с кнопками навигации
    await query.edit_message_text(
        f"📅 {date.strftime('%d.%m.%Y %H:%M')}\n\n{text}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back")],
            [InlineKeyboardButton("❌ Закрыть", callback_data="close")]
        ])
    )

    return STATE_VIEW


async def back_to_list(update, context):
    """Возврат к списку записей (кнопка 'Назад')"""
    return await show_entries(update, context)


async def close_entries(update, context):
    """Закрытие просмотра записей (кнопка 'Закрыть')"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👋 Завершено")
    return ConversationHandler.END


async def show_stats(update, context):
    """Обработка команды /stats - отображение статистики"""
    stats = db.get_stats(update.effective_user.id)

    # Форматируем время использования
    days = stats["used_time"].days
    hours = stats["used_time"].seconds // 3600
    mins = (stats["used_time"].seconds % 3600) // 60

    # Форматируем дату регистрации
    reg_date = stats["reg_date"].strftime("%d.%m.%Y")
    # Средняя длина записи
    avg_len = stats["chars"] // stats["count"] if stats["count"] > 0 else 0

    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"📅 Регистрация: {reg_date}\n"
        f"⏳ Использование: {days}д {hours}ч {mins}м\n"
        f"📝 Записей: {stats['count']}\n"
        f"🔤 Символов: {stats['chars']}\n"
        f"📏 Среднее: {avg_len} симв/запись",
        parse_mode="Markdown"
    )


def main():
    """Основная функция запуска бота"""
    # Создаем приложение бота
    app = Application.builder().token(BOT_TOKEN).build()

    # Обработчик создания записей (машина состояний)
    entry_handler = ConversationHandler(
        entry_points=[CommandHandler("new", new_entry)],
        states={
            STATE_WRITE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_text),
                CallbackQueryHandler(save_entry, pattern="^done$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_entry)],
    )

    # Обработчик просмотра записей (машина состояний)
    view_handler = ConversationHandler(
        entry_points=[CommandHandler("list", show_entries)],
        states={
            STATE_VIEW: [
                CallbackQueryHandler(show_entry, pattern="^show_"),
                CallbackQueryHandler(back_to_list, pattern="^back$"),
                CallbackQueryHandler(close_entries, pattern="^close$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_entry)],
    )

    # Регистрируем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(entry_handler)
    app.add_handler(view_handler)

    # Обработчик простых текстовых сообщений
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda u, c: u.message.reply_text("Используйте /help")
    ))

    print("Бот запущен...")
    app.run_polling()  # Запуск бота в режиме polling


if __name__ == "__main__":
    main()