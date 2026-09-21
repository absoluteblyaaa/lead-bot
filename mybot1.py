import asyncio
import re
import sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# -------------------------------------------------------------------
# НАСТРОЙКИ (В будущем меняются под клиента)
# -------------------------------------------------------------------
TOKEN = "8906348070:AAHrbZIl5jT_Lt99VYEU6V1srCUTToU8Tl0"  # Укажи токен своего бота
ADMIN_ID = 5113398392  # Твой Telegram ID для получения заявок

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# -------------------------------------------------------------------
conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        name TEXT,
        phone TEXT,
        service TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""
)
conn.commit()


# -------------------------------------------------------------------
# FSM (СОСТОЯНИЯ ФОРМЫ)
# -------------------------------------------------------------------
class LeadForm(StatesGroup):
    name = State()
    phone = State()
    service = State()


# -------------------------------------------------------------------
# КЛАВИАТУРЫ
# -------------------------------------------------------------------
def main_menu_keyboard():
    kb = [
        [
            InlineKeyboardButton(
                text="📝 Оставить заявку", callback_data="start_form"
            )
        ],
        [
            InlineKeyboardButton(
                text="ℹ️ О нас", callback_data="about"
            ),
            InlineKeyboardButton(
                text="📞 Контакты", callback_data="contacts"
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def cancel_keyboard():
    kb = [[KeyboardButton(text="❌ Отмена")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def phone_keyboard():
    kb = [
        [KeyboardButton(text="📱 Поделиться контактом", request_contact=True)],
        [KeyboardButton(text="❌ Отмена")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# -------------------------------------------------------------------
# ХЕНДЛЕРЫ (ОБРАБОТЧИКИ)
# -------------------------------------------------------------------


# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я бот для приёма заявок. Выберите нужное действие в меню ниже:",
        reply_markup=main_menu_keyboard(),
    )


# Отмена в любой момент
@dp.message(Command("cancel"))
@dp.message(F.text == "❌ Отмена")
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Действие отменено.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Чем ещё могу помочь?", reply_markup=main_menu_keyboard()
    )


# Нажатие на кнопки Главного Меню
@dp.callback_query(F.data == "about")
async def process_about(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ **О нас:**\nМы предоставляем самые качественные услуги в городе! Быстро, надежно и с гарантией.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "contacts")
async def process_contacts(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📞 **Наши контакты:**\n• Телефон: +7 (999) 000-00-00\n• Telegram: @admin\n• Режим работы: 9:00 - 21:00",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


# Старт заполнения формы
@dp.callback_query(F.data == "start_form")
async def process_start_form(
    callback: types.CallbackQuery, state: FSMContext
):
    await state.set_state(LeadForm.name)
    await callback.message.answer(
        "Шаг 1 из 3:\nКак к вам обращаться? (Введите ваше имя)",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


# Шаг 1: Получение имени
@dp.message(LeadForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(LeadForm.phone)
    await message.answer(
        "Шаг 2 из 3:\nУкажите ваш номер телефона или нажмите кнопку ниже:",
        reply_markup=phone_keyboard(),
    )


# Шаг 2: Получение и валидация телефона
@dp.message(LeadForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    # Если поделились контактом через кнопку
    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = message.text
        # Простейшая валидация (проверяем, есть ли цифры и длина от 7)
        clean_phone = re.sub(r"\D", "", phone)
        if len(clean_phone) < 7:
            await message.answer(
                "⚠️ Пожалуйста, введите корректный номер телефона (например, +79991234567) или воспользуйтесь кнопкой:",
                reply_markup=phone_keyboard(),
            )
            return

    await state.update_data(phone=phone)
    await state.set_state(LeadForm.service)
    await message.answer(
        "Шаг 3 из 3:\nКакая услуга или товар вас интересует?",
        reply_markup=cancel_keyboard(),
    )


# Шаг 3: Получение услуги + Финал
@dp.message(LeadForm.service)
async def process_service(message: types.Message, state: FSMContext):
    await state.update_data(service=message.text)
    data = await state.get_data()
    await state.clear()

    # 1. Сохраняем в SQLite
    cursor.execute(
        "INSERT INTO leads (user_id, username, name, phone, service) VALUES (?, ?, ?, ?, ?)",
        (
            message.from_user.id,
            message.from_user.username or "нет_юзернейма",
            data["name"],
            data["phone"],
            data["service"],
        ),
    )
    conn.commit()

    # 2. Отправляем ответ клиенту
    await message.answer(
        "🎉 **Спасибо! Ваша заявка принята.**\nМы свяжемся с вами в ближайшее время!",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Главное меню:", reply_markup=main_menu_keyboard()
    )

    # 3. МГНОВЕННОЕ УВЕДОМЛЕНИЕ АДМИНУВ ЛС
    admin_text = (
        "🚨 **НОВАЯ ЗАЯВКА!**\n\n"
        f"👤 **Имя:** {data['name']}\n"
        f"📞 **Телефон:** `{data['phone']}`\n"
        f"🛠 **Услуга:** {data['service']}\n\n"
        f"🔗 **Профиль:** @{message.from_user.username or 'отсутствует'}\n"
        f"🆔 **ID:** `{message.from_user.id}`"
    )
    try:
        await bot.send_message(
            ADMIN_ID, admin_text, parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка отправки админу: {e}")


# Команда просмотра заявок для админа (/requests)
@dp.message(Command("requests"))
async def cmd_requests(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    cursor.execute(
        "SELECT id, name, phone, service, created_at FROM leads ORDER BY id DESC LIMIT 10"
    )
    rows = cursor.fetchall()

    if not rows:
        await message.answer("Заявок пока нет.")
        return

    text = "📋 **Последние 10 заявок:**\n\n"
    for row in rows:
        text += f"№{row[0]} | {row[1]} | `{row[2]}` | {row[3]} | {row[4]}\n"

    await message.answer(text, parse_mode="Markdown")


# -------------------------------------------------------------------
# ЗАПУСК
# -------------------------------------------------------------------
async def main():
    print("Бот с кнопками и уведомлениями запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())