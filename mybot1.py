import asyncio
import os
import re
import sqlite3
import time
import csv
import io
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
    BufferedInputFile,
)

# -------------------------------------------------------------------
# НАСТРОЙКИ
# -------------------------------------------------------------------
TOKEN = "8906348070:AAHnIDMz2_vQ_wSto329qYcIRflYpbA2fwk"

# Главный владелец бота (вшит в код, имеет полный доступ к админам)
OWNER_ID = 5113398392

cooldowns = {}
COOLDOWN_TIME = 60  # Секунд задержки между заявками для защиты от спама

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# -------------------------------------------------------------------
# БАЗА ДАННЫХ (LEADS + BANS + ADMINS)
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

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS banned (
        user_id INTEGER PRIMARY KEY
    )
"""
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )
"""
)
conn.commit()

# Автоматически добавляем главного владельца в базу админов при запуске
cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
conn.commit()


def is_banned(user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM banned WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None


def is_admin(user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None


def get_all_admins():
    cursor.execute("SELECT user_id FROM admins")
    return [row[0] for row in cursor.fetchall()]


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
def get_main_keyboard(user_id: int):
    if is_admin(user_id):
        kb = [
            [KeyboardButton(text="📝 Оставить заявку")],
            [KeyboardButton(text="ℹ️ О нас"), KeyboardButton(text="📞 Контакты")],
            [KeyboardButton(text="📊 Панель управления (CRM)")],
        ]
    else:
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
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы заблокированы администратором бота.")
        return

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


# Добавление админа через команду: /addadmin ID
@dp.message(Command("addadmin"))
async def cmd_add_admin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только главный владелец может добавлять администраторов.")
        return

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("⚠️ Использование: `/addadmin <TELEGRAM_ID>`", parse_mode="Markdown")
        return

    new_admin_id = int(parts[1])
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_admin_id,))
    conn.commit()

    await message.answer(f"✅ Пользователь `{new_admin_id}` успешно назначен администратором!", parse_mode="Markdown")
    try:
        await bot.send_message(new_admin_id, "🎉 Вас назначили администратором/менеджером бота!", reply_markup=get_main_keyboard(new_admin_id))
    except Exception:
        pass


# Удаление админа через команду: /deladmin ID
@dp.message(Command("deladmin"))
async def cmd_del_admin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только главный владелец может удалять администраторов.")
        return

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("⚠️ Использование: `/deladmin <TELEGRAM_ID>`", parse_mode="Markdown")
        return

    target_id = int(parts[1])
    if target_id == OWNER_ID:
        await message.answer("⛔ Нельзя удалить главного владельца бота.")
        return

    cursor.execute("DELETE FROM admins WHERE user_id = ?", (target_id,))
    conn.commit()

    await message.answer(f"🚫 Пользователь `{target_id}` лишен прав администратора.", parse_mode="Markdown")
    try:
        await bot.send_message(target_id, "⛔ Ваши права администратора были отозваны.", reply_markup=get_main_keyboard(target_id))
    except Exception:
        pass


# CRM-панель администратора
@dp.message(F.text == "📊 Панель управления (CRM)")
async def process_admin_requests_btn(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой панели.")
        return

    cursor.execute(
        "SELECT id, user_id, name, phone, service, status, created_at FROM leads ORDER BY id DESC LIMIT 5"
    )
    rows = cursor.fetchall()

    if not rows:
        await message.answer("📋 Заявок в базе пока нет.")
        return

    await message.answer("📊 **CRM — Управление заявками (Последние 5):**", parse_mode="Markdown")

    for row in rows:
        lead_id, client_id, name, phone, service, status, created_at = row
        text = (
            f"📌 **Заявка №{lead_id}** [{status}]\n"
            f"👤 Имя: {name}\n"
            f"📞 Телефон: `{phone}`\n"
            f"🛠 Услуга: {service}\n"
            f"🆔 ID клиента: `{client_id}`\n"
            f"📅 Дата: {created_at}"
        )
        
        user_is_banned = is_banned(client_id)
        ban_button_text = "✅ Разбанить" if user_is_banned else "🚫 Бан"
        ban_callback = f"unban_{client_id}" if user_is_banned else f"ban_{client_id}"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴", callback_data=f"status_{lead_id}_🔴 Новая"),
                InlineKeyboardButton(text="🟡", callback_data=f"status_{lead_id}_🟡 В работе"),
                InlineKeyboardButton(text="🟢", callback_data=f"status_{lead_id}_🟢 Закрыта"),
                InlineKeyboardButton(text=ban_button_text, callback_data=ban_callback),
            ]
        ])
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)

    menu_buttons = [
        [InlineKeyboardButton(text="📥 Скачать все заявки (CSV / Excel)", callback_data="export_csv")]
    ]
    
    if message.from_user.id == OWNER_ID or message.from_user.id in get_all_admins():
        menu_buttons.append([InlineKeyboardButton(text="👥 Список админов", callback_data="list_admins")])

    menu_kb = InlineKeyboardMarkup(inline_keyboard=menu_buttons)
    await message.answer("Управление базой данных:", reply_markup=menu_kb)


@dp.callback_query(F.data == "list_admins")
async def process_list_admins(callback: types.CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    admins = get_all_admins()
    text = "👥 **Список текущих администраторов:**\n\n"
    for idx, adm_id in enumerate(admins, 1):
        role = "👑 Владелец" if adm_id == OWNER_ID else "🛡 Менеджер"
        text += f"{idx}. ID: `{adm_id}` ({role})\n"

    text += "\n💡 *Чтобы добавить нового:* `/addadmin ID`\n💡 *Чтобы удалить:* `/deladmin ID`"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("status_"))
async def process_change_status(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    _, lead_id, new_status = callback.data.split("_", 2)
    
    cursor.execute("SELECT user_id FROM leads WHERE id = ?", (lead_id,))
    lead_row = cursor.fetchone()
    
    cursor.execute("UPDATE leads SET status = ? WHERE id = ?", (new_status, lead_id))
    conn.commit()

    await callback.answer(f"Статус заявки №{lead_id} изменен!")
    
    if lead_row:
        client_id = lead_row[0]
        try:
            await bot.send_message(
                client_id,
                f"📌 **Обновление по заявке!**\nСтатус вашей заявки №{lead_id} изменен на: *{new_status}*",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление клиенту: {e}")
    
    original_text = callback.message.text
    lines = original_text.split("\n")
    if lines:
        lines[0] = f"📌 **Заявка №{lead_id}** [{new_status}]"
        updated_text = "\n".join(lines)
        try:
            await callback.message.edit_text(updated_text, parse_mode="Markdown", reply_markup=callback.message.reply_markup)
        except Exception:
            pass


@dp.callback_query(F.data.startswith("ban_"))
async def process_ban_user(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    target_id = int(callback.data.split("_")[1])
    
    cursor.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (target_id,))
    conn.commit()

    await callback.answer(f"🚫 Пользователь {target_id} заблокирован!", show_alert=True)
    
    old_markup = callback.message.reply_markup.inline_keyboard
    new_markup = []
    for row in old_markup:
        new_row = []
        for btn in row:
            if btn.callback_data.startswith("ban_"):
                new_row.append(InlineKeyboardButton(text="✅ Разбанить", callback_data=f"unban_{target_id}"))
            else:
                new_row.append(btn)
        new_markup.append(new_row)
        
    try:
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_markup))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("unban_"))
async def process_unban_user(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    target_id = int(callback.data.split("_")[1])
    
    cursor.execute("DELETE FROM banned WHERE user_id = ?", (target_id,))
    conn.commit()

    await callback.answer(f"✅ Пользователь {target_id} разблокирован!", show_alert=True)
    
    old_markup = callback.message.reply_markup.inline_keyboard
    new_markup = []
    for row in old_markup:
        new_row = []
        for btn in row:
            if btn.callback_data.startswith("unban_"):
                new_row.append(InlineKeyboardButton(text="🚫 Бан", callback_data=f"ban_{target_id}"))
            else:
                new_row.append(btn)
        new_markup.append(new_row)
        
    try:
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_markup))
    except Exception:
        pass


@dp.callback_query(F.data == "export_csv")
async def process_export_csv(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
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


@dp.message(F.text == "📝 Оставить заявку")
async def process_start_form(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы заблокированы и не можете отправлять заявки.")
        return

    current_time = time.time()
    if not is_admin(user_id) and user_id in cooldowns:
        elapsed = current_time - cooldowns[user_id]
        if elapsed < COOLDOWN_TIME:
            remaining = int(COOLDOWN_TIME - elapsed)
            await message.answer(
                f"⏳ Пожалуйста, подождите еще {remaining} сек. перед отправкой новой заявки."
            )
            return

    await state.set_state(LeadForm.name)
    await message.answer(
        "Шаг 1 из 3:\nКак к вам обращаться? (Введите ваше имя)",
        reply_markup=cancel_keyboard(),
    )


@dp.message(LeadForm.name)
async def process_name(message: types.Message, state: FSMContext):
    name_text = message.text.strip()
    if len(name_text) > 50:
        await message.answer("⚠️ Имя слишком длинное. Введите корректное имя до 50 символов:")
        return

    await state.update_data(name=name_text)
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
        phone = message.text.strip()
        clean_phone = re.sub(r"\D", "", phone)
        if len(clean_phone) < 7 or len(phone) > 30:
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
    user_id = message.from_user.id
    if is_banned(user_id):
        await state.clear()
        await message.answer("⛔ Вы заблокированы.")
        return

    service_text = message.text.strip()
    if len(service_text) > 150:
        await message.answer("⚠️ Описание услуги слишком длинное. Сократите до 150 символов:")
        return

    data = await state.get_data()
    
    if not is_admin(user_id):
        cooldowns[user_id] = time.time()

    await state.clear()

    cursor.execute(
        "INSERT INTO leads (user_id, username, name, phone, service) VALUES (?, ?, ?, ?, ?)",
        (
            user_id,
            message.from_user.username or "нет_юзернейма",
            data["name"],
            data["phone"],
            service_text,
        ),
    )
    conn.commit()

    await message.answer(
        "🎉 **Спасибо! Ваша заявка принята.**\nМы свяжемся с вами в ближайшее время!",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id),
    )

    admin_text = (
        "🚨 **НОВАЯ ЗАЯВКА!** [🔴 Новая]\n\n"
        f"👤 **Имя:** {data['name']}\n"
        f"📞 **Телефон:** `{data['phone']}`\n"
        f"🛠 **Услуга:** {service_text}\n\n"
        f"🔗 **Профиль:** @{message.from_user.username or 'отсутствует'}\n"
        f"🆔 **ID:** `{user_id}`"
    )
    
    all_admins = get_all_admins()
    for adm_id in all_admins:
        try:
            await bot.send_message(adm_id, admin_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка отправки админу {adm_id}: {e}")




async def handle_ping(request):
    return web.Response(text="Bot is alive!")


async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    app_setup = runner.setup()
    if asyncio.iscoroutine(app_setup):
        await app_setup
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"Сервер открыт на порту {port}")
    print("Бот полностью запущен и готов к работе!")
    
    # Сбрасываем старый вебхук перед запуском поллинга
    await bot.delete_webhook(drop_pending_updates=True)
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
