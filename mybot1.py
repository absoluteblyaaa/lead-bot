import asyncio
import os
import re
import sqlite3
from aiohttp import web
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
    BufferedInputFile,
)
import csv
import io

# -------------------------------------------------------------------
# НАСТРОЙКИ
# -------------------------------------------------------------------
TOKEN = "8906348070:AAHuveAtmw8kQ9z3Lj4oc26Poz5oC7lJroc"
ADMIN_ID = 5113398392

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# -------------------------------------------------------------------
# БАЗА ДАННЫХ
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
        status TEXT DEFAULT '🔴 Новая',
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
# КЛАВИАТУРЫ (Красивое меню внизу экрана)
# -------------------------------------------------------------------
def get_main_keyboard(user_id: int):
    if user_id == ADMIN_ID:
        # Меню для администратора (с кнопкой CRM-панели)
        kb = [
            [KeyboardButton(text="📝 Оставить заявку")],
            [KeyboardButton(text="ℹ️ О нас"), KeyboardButton(text="📞 Контакты")],
            [KeyboardButton(text="📊 Панель управления (CRM)")],
        ]
    else:
        # Меню для обычного клиента
        kb = [
            [KeyboardButton(text="📝 Оставить заявку")],
            [KeyboardButton(text="ℹ️ О нас"), KeyboardButton(text="📞 Контакты")],
        ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True
    )


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться контактом", request_contact=True)],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


# -------------------------------------------------------------------
# ХЕНДЛЕРЫ
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я бот для приёма заявок. Выберите нужное действие на клавиатуре внизу:",
        reply_markup=get_main_keyboard(message.from_user.id),
    )


@dp.message(Command("cancel"))
@dp.message(F.text == "❌ Отмена")
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_main_keyboard(message.from_user.id))


@dp.message(F.text == "ℹ️ О нас")
async def process_about(message: types.Message):
    await message.answer(
        "ℹ️ **О нас:**\nМы предоставляем самые качественные услуги! Быстро, надежно и с гарантией.",
        parse_mode="Markdown",
    )


@dp.message(F.text == "📞 Контакты")
async def process_contacts(message: types.Message):
    await message.answer(
        "📞 **Наши контакты:**\n• Телефон: +7 (999) 000-00-00\n• Telegram: @admin\n• Режим работы: 9:00 - 21:00",
        parse_mode="Markdown",
    )


# Кнопка CRM для админа (вместо команды /requests)
@dp.message(F.text == "📊 Панель управления (CRM)")
async def process_admin_requests_btn(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа!")
        return

    cursor.execute(
        "SELECT id, name, phone, service, status, created_at FROM leads ORDER BY id DESC LIMIT 5"
    )
    rows = cursor.fetchall()

    if not rows:
        await message.answer("📋 Заявок в базе пока нет.")
        return

    await message.answer("📊 **CRM — Управление заявками (Последние 5):**", parse_mode="Markdown")

    for row in rows:
        lead_id, name, phone, service, status, created_at = row
        text = (
            f"📌 **Заявка №{lead_id}** [{status}]\n"
            f"👤 Имя: {name}\n"
            f"📞 Телефон: `{phone}`\n"
            f"🛠 Услуга: {service}\n"
            f"📅 Дата: {created_at}"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 Новая", callback_data=f"status_{lead_id}_🔴 Новая"),
                InlineKeyboardButton(text="🟡 В работе", callback_data=f"status_{lead_id}_🟡 В работе"),
                InlineKeyboardButton(text="🟢 Закрыта", callback_data=f"status_{lead_id}_🟢 Закрыта"),
            ]
        ])
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)

    menu_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать все заявки (CSV / Excel)", callback_data="export_csv")]
    ])
    await message.answer("Управление базой данных:", reply_markup=menu_kb)


@dp.callback_query(F.data.startswith("status_"))
async def process_change_status(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    _, lead_id, new_status = callback.data.split("_", 2)
    
    cursor.execute("UPDATE leads SET status = ? WHERE id = ?", (new_status, lead_id))
    conn.commit()

    await callback.answer(f"Статус заявки №{lead_id} изменен!")
    
    original_text = callback.message.text
    lines = original_text.split("\n")
    if lines:
        lines[0] = f"📌 **Заявка №{lead_id}** [{new_status}]"
        updated_text = "\n".join(lines)
        try:
            await callback.message.edit_text(updated_text, parse_mode="Markdown", reply_markup=callback.message.reply_markup)
        except Exception:
            pass


@dp.callback_query(F.data == "export_csv")
async def process_export_csv(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    cursor.execute("SELECT id, user_id, username, name, phone, service, status, created_at FROM leads")
    rows = cursor.fetchall()

    if not rows:
        await callback.answer("Нет данных для экспорта!", show_alert=True)
        return

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["ID", "User ID", "Username", "Имя", "Телефон", "Услуга", "Статус", "Дата создания"])
    for row in rows:
        writer.writerow(row)

    csv_data = output.getvalue().encode('utf-8-sig')
    file_bytes = BufferedInputFile(csv_data, filename="leads_export.csv")

    await callback.message.answer_document(file_bytes, caption="📁 **Экспорт всех заявок готов!**", parse_mode="Markdown")
    await callback.answer()


# -------------------------------------------------------------------
# ЛОГИКА ЗАПОЛНЕНИЯ ЗАЯВКИ (FSM)
# -------------------------------------------------------------------
@dp.message(F.text == "📝 Оставить заявку")
async def process_start_form(message: types.Message, state: FSMContext):
    await state.set_state(LeadForm.name)
    await message.answer(
        "Шаг 1 из 3:\nКак к вам обращаться? (Введите ваше имя)",
        reply_markup=cancel_keyboard(),
    )


@dp.message(LeadForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(LeadForm.phone)
    await message.answer(
        "Шаг 2 из 3:\nУкажите ваш номер телефона или нажмите кнопку ниже:",
        reply_markup=phone_keyboard(),
    )


@dp.message(LeadForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = message.text
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


@dp.message(LeadForm.service)
async def process_service(message: types.Message, state: FSMContext):
    await state.update_data(service=message.text)
    data = await state.get_data()
    await state.clear()

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

    await message.answer(
        "🎉 **Спасибо! Ваша заявка принята.**\nМы свяжемся с вами в ближайшее время!",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id),
    )

    admin_text = (
        "🚨 **НОВАЯ ЗАЯВКА!** [🔴 Новая]\n\n"
        f"👤 **Имя:** {data['name']}\n"
        f"📞 **Телефон:** `{data['phone']}`\n"
        f"🛠 **Услуга:** {data['service']}\n\n"
        f"🔗 **Профиль:** @{message.from_user.username or 'отсутствует'}\n"
        f"🆔 **ID:** `{message.from_user.id}`"
    )
    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка отправки админу: {e}")


# -------------------------------------------------------------------
# ВЕБ-СЕРВЕР ДЛЯ RENDER + ЗАПУСК БОТА
# -------------------------------------------------------------------
async def handle_ping(request):
    return web.Response(text="Bot is alive!")


async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"Сервер открыт на порту {port}")
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
