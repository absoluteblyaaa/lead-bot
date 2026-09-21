import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ---------------------------------------------------------
# НАСТРОЙКИ (Твои данные)
# ---------------------------------------------------------
BOT_TOKEN = "8906348070:AAHrbZIl5jT_Lt99VYEU6V1srCUTToU8Tl0"
ADMIN_ID = 5113398392

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------
# БАЗА ДАННЫХ (SQLite)
# ---------------------------------------------------------
def init_db():
    """Создаёт таблицу в базе данных, если её ещё нет."""
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            name TEXT,
            phone TEXT,
            problem TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_request(user_id: int, username: str, name: str, phone: str, problem: str):
    """Сохраняет новую заявку в БД."""
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO requests (user_id, username, name, phone, problem, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, username, name, phone, problem, now))
    conn.commit()
    conn.close()

def get_all_requests():
    """Получает последние заявки из БД."""
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, phone, problem, created_at FROM requests ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    return rows

# Инициализируем БД при запуске
init_db()

# ---------------------------------------------------------
# ИНИЦИАЛИЗА БОТА И FSM
# ---------------------------------------------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class OrderForm(StatesGroup):
    name = State()
    phone = State()
    problem = State()

# ---------------------------------------------------------
# ХЕНДЛЕРЫ (ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ)
# ---------------------------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я бот для приёма заявок на услугу.\n\n"
        "Давай оформим заявку. Как к вам обращаться (Ваше имя)?"
    )
    await state.set_state(OrderForm.name)

@dp.message(OrderForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отлично! Укажите ваш номер телефона для связи:")
    await state.set_state(OrderForm.phone)

@dp.message(OrderForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("Опишите кратко вашу задачу или интересующую услугу:")
    await state.set_state(OrderForm.problem)

@dp.message(OrderForm.problem)
async def process_problem(message: types.Message, state: FSMContext):
    await state.update_data(problem=message.text)
    
    data = await state.get_data()
    user_name = data.get("name")
    user_phone = data.get("phone")
    user_problem = data.get("problem")
    
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет username"

    # 1. Сохраняем в базу данных
    save_request(
        user_id=message.from_user.id,
        username=username,
        name=user_name,
        phone=user_phone,
        problem=user_problem
    )

    # 2. Отправляем подтверждение пользователю
    await message.answer("Спасибо! Ваша заявка успешно принята и сохранена в БД. Менеджер свяжется с вами в ближайшее время!")

    # 3. Отправляем уведомление администратору в ЛС
    admin_text = (
        "📥 **НОВАЯ ЗАЯВКА (Сохранена в БД)!**\n\n"
        f"👤 **Имя:** {user_name}\n"
        f"📞 **Телефон:** {user_phone}\n"
        f"💬 **Задача:** {user_problem}\n"
        f"🔗 **Профиль:** {username} (ID: {message.from_user.id})"
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение админу: {e}")

    await state.clear()

# ---------------------------------------------------------
# КОМАНДА ДЛЯ АДМИНА: Просмотр последних заявок из БД
# ---------------------------------------------------------
@dp.message(Command("requests"))
async def cmd_requests(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return

    requests = get_all_requests()
    if not requests:
        await message.answer("В базе пока нет заявок.")
        return

    res_text = "📋 **Последние заявки из базы данных:**\n\n"
    for req in requests:
        req_id, name, phone, problem, created_at = req
        res_text += f"🔹 **№{req_id}** ({created_at})\nИмя: {name}\nТел: {phone}\nЗадача: {problem}\n\n"

    await message.answer(res_text, parse_mode="Markdown")

# ---------------------------------------------------------
# ЗАПУСК БОТА
# ---------------------------------------------------------
async def main():
    print("Бот с базой данных запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())