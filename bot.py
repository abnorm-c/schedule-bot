import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN
from database import (
    init_db, init_schedule_db, init_profile_db, add_user, get_balance, add_transaction,
    confirm_transaction, get_pending_transactions, cancel_transaction,
    update_balance, refresh_weekly_schedule, get_slots_by_day, 
    book_slot, get_user_bookings, get_profile, create_profile, update_profile,
    add_template_slot, delete_template_slot, get_all_template_slots,
    cancel_booking
)

# Классы для хранения состояний
class PaymentStates(StatesGroup):
    waiting_for_amount = State()

class ProfileCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_grade = State()
    waiting_for_phone = State()
    waiting_for_format = State()

class ProfileEditing(StatesGroup):
    waiting_for_field = State()
    waiting_for_value = State()

# Настраиваем логирование
logging.basicConfig(level=logging.INFO)

# Создаем бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ID админа (замени на свой)
ADMIN_ID = 702121216

# Хранилище последних сообщений и выбранных слотов
user_last_message = {}
user_selected_slot = {}

# ========== ФУНКЦИИ ДЛЯ ОЧИСТКИ ==========

async def clear_previous_messages(user_id, keep_last=False):
    """Удаляет предыдущие сообщения бота для этого пользователя"""
    if user_id in user_last_message:
        try:
            await user_last_message[user_id].delete()
        except:
            pass
        if not keep_last:
            del user_last_message[user_id]

async def send_clean_message(user_id, text, reply_markup=None, parse_mode=None, keep_previous=False):
    """Отправляет сообщение, опционально удаляя предыдущее"""
    if not keep_previous:
        await clear_previous_messages(user_id)
    msg = await bot.send_message(user_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    user_last_message[user_id] = msg
    return msg

async def safe_delete(message):
    """Безопасно удаляет любое сообщение"""
    try:
        await message.delete()
    except:
        pass

# ========== INLINE-КЛАВИАТУРЫ ==========

def get_main_menu():
    """Главное меню"""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile"))
    builder.add(types.InlineKeyboardButton(text="💰 Кошелек", callback_data="wallet"))
    builder.add(types.InlineKeyboardButton(text="💳 Пополнить", callback_data="pay"))
    builder.add(types.InlineKeyboardButton(text="📅 Расписание", callback_data="booking"))
    builder.add(types.InlineKeyboardButton(text="📋 Мои записи", callback_data="my_bookings"))
    builder.add(types.InlineKeyboardButton(text="📋 Правила", callback_data="rules"))
    builder.adjust(2, 2, 2)  # 3 ряда по 2 кнопки
    return builder.as_markup()

def get_back_button():
    """Кнопка возврата в меню"""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    return builder.as_markup()

# ========== КОМАНДЫ ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "нет_username"
    full_name = message.from_user.full_name
    
    # Удаляем все предыдущие сообщения этого пользователя
    await clear_previous_messages(user_id, keep_last=False)
    await safe_delete(message)
    
    is_new = add_user(user_id, username, full_name)
    
    welcome_text = f"""
🎓 **Добро пожаловать, {full_name}!**

Я — твой личный помощник для записи на занятия по математике.

📋 **Правила занятий:**

1️⃣ **Запись**
   • Выбирай свободное время в расписании
   • Указывай длительность (1 или 2 урока)
   • Выбирай формат: онлайн или оффлайн

2️⃣ **Оплата**
   • Деньги списываются с баланса сразу при записи
   • Пополнить баланс можно в разделе "Пополнить"

3️⃣ **Отмена занятия**
   • За 2+ часа до урока → полный возврат
   • Менее чем за 2 часа до урока → деньги уйдут на удержание 25%
   • Отменить запись можно в разделе "Мои записи"

4️⃣ **Напоминания**
   • Я пришлю напоминание за 2 часа до урока

💡 **Для начала создай свой профиль!**
Нажми на кнопку "Мой профиль" в главном меню.
    """
    
    await send_clean_message(
        user_id,
        welcome_text,
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    user_id = message.from_user.id
    await safe_delete(message)
    await send_clean_message(
        user_id,
        "Главное меню:",
        reply_markup=get_main_menu()
    )

@dp.message(Command("refresh"))
async def cmd_refresh(message: Message):
    """Обновляет расписание (только для админа)"""
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    deleted, created = refresh_weekly_schedule()
    
    await send_clean_message(
        user_id,
        f"📅 **Расписание обновлено!**\n\n"
        f"🗑 Удалено старых: {deleted}\n"
        f"✨ Создано новых: {created}",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )

# ========== АДМИН-КОМАНДЫ ==========

@dp.message(Command("pending"))
async def cmd_pending(message: Message):
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    transactions = get_pending_transactions()
    
    if not transactions:
        await send_clean_message(user_id, "📭 Нет неподтвержденных платежей", reply_markup=get_main_menu())
        return
    
    text = "📋 **Ожидают подтверждения:**\n\n"
    for t in transactions:
        text += f"🆔 {t[0]} | @{t[1] or 'нет'} | {t[2]} | {t[3]}₽ | {t[4]}\n"
        text += f"✅ Подтвердить: `/confirm {t[0]}`\n"
        text += f"❌ Отменить: `/cancel {t[0]}`\n\n"
    
    await send_clean_message(user_id, text, parse_mode="Markdown", reply_markup=get_main_menu())

@dp.message(Command("confirm"))
async def cmd_confirm(message: Message):
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await send_clean_message(user_id, "❌ Укажи ID транзакции: /confirm 123", reply_markup=get_main_menu())
            return
        
        transaction_id = int(parts[1])
        target_user_id, amount = confirm_transaction(transaction_id)
        
        if target_user_id:
            await send_clean_message(
                user_id,
                f"✅ Транзакция {transaction_id} подтверждена! Пользователю начислено {amount}₽",
                reply_markup=get_main_menu()
            )
            
            try:
                await bot.send_message(
                    target_user_id,
                    f"✅ Твой кошелек пополнен на **{amount}₽**!\nБаланс: **{get_balance(target_user_id)}₽**",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            await send_clean_message(
                user_id,
                "❌ Транзакция не найдена или уже подтверждена",
                reply_markup=get_main_menu()
            )
            
    except ValueError:
        await send_clean_message(
            user_id,
            "❌ Неверный формат ID. Используй: /confirm 123",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        await send_clean_message(
            user_id,
            f"❌ Ошибка: {e}",
            reply_markup=get_main_menu()
        )

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await send_clean_message(user_id, "❌ Укажи ID транзакции: /cancel 123", reply_markup=get_main_menu())
            return
        
        transaction_id = int(parts[1])
        target_user_id = cancel_transaction(transaction_id)
        
        if target_user_id:
            await send_clean_message(
                user_id,
                f"✅ Транзакция {transaction_id} отменена!",
                reply_markup=get_main_menu()
            )
            
            try:
                await bot.send_message(
                    target_user_id,
                    f"❌ Твоя заявка на пополнение №{transaction_id} была отменена.",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            await send_clean_message(
                user_id,
                "❌ Транзакция не найдена или уже обработана",
                reply_markup=get_main_menu()
            )
            
    except ValueError:
        await send_clean_message(
            user_id,
            "❌ Неверный формат ID. Используй: /cancel 123",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        await send_clean_message(
            user_id,
            f"❌ Ошибка: {e}",
            reply_markup=get_main_menu()
        )

@dp.message(Command("balance"))
async def cmd_set_balance(message: Message):
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            await send_clean_message(
                user_id,
                "❌ Неправильный формат. Используй:\n"
                "`/balance @username 500` - добавить\n"
                "`/balance @username -200` - вычесть\n"
                "`/balance @username =1000` - установить",
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )
            return
        
        user_identifier = parts[1]
        amount_str = parts[2]
        
        if amount_str.startswith('='):
            operation = "set"
            amount = int(amount_str[1:])
        else:
            operation = "add"
            amount = int(amount_str)
        
        if user_identifier.startswith('@'):
            username = user_identifier[1:]
            conn = sqlite3.connect('rep_bot.db')
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE username = ?", (username,))
            result = cur.fetchone()
            conn.close()
            
            if not result:
                await send_clean_message(user_id, f"❌ Пользователь {user_identifier} не найден", reply_markup=get_main_menu())
                return
            target_user_id = result[0]
        else:
            target_user_id = int(user_identifier)
        
        user_info, new_balance = update_balance(target_user_id, amount, operation)
        
        if user_info:
            username, full_name = user_info
            username_display = f"@{username}" if username and username != "нет_username" else "без username"
            
            if operation == "add":
                action = "добавлено" if amount > 0 else "вычтено"
                await send_clean_message(
                    user_id,
                    f"✅ Баланс обновлен!\nПользователь: {full_name} ({username_display})\n"
                    f"{action}: {abs(amount)}₽\nНовый баланс: **{new_balance}₽**",
                    parse_mode="Markdown",
                    reply_markup=get_main_menu()
                )
            else:
                await send_clean_message(
                    user_id,
                    f"✅ Баланс установлен!\nПользователь: {full_name} ({username_display})\n"
                    f"Новый баланс: **{new_balance}₽**",
                    parse_mode="Markdown",
                    reply_markup=get_main_menu()
                )
            
            try:
                await bot.send_message(
                    target_user_id,
                    f"💰 Твой баланс изменен. Новый баланс: **{new_balance}₽**",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            await send_clean_message(user_id, "❌ Ошибка при обновлении баланса", reply_markup=get_main_menu())
            
    except ValueError:
        await send_clean_message(user_id, "❌ Неверный формат суммы. Используй числа.", reply_markup=get_main_menu())
    except Exception as e:
        await send_clean_message(user_id, f"❌ Ошибка: {e}", reply_markup=get_main_menu())

# ========== АДМИН-КОМАНДЫ ДЛЯ ШАБЛОНА ==========

@dp.message(Command("add_time"))
async def cmd_add_time(message: Message):
    """Добавить время в шаблон: /add_time Пн 16:00 500 900"""
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 4:
            await send_clean_message(
                user_id,
                "❌ Формат: /add_time ДЕНЬ ВРЕМЯ ЦЕНА_1 ЦЕНА_2\n"
                "Пример: /add_time Пн 16:00 500 900",
                reply_markup=get_main_menu()
            )
            return
        
        day = parts[1]
        time = parts[2]
        price_1 = int(parts[3])
        price_2 = int(parts[4]) if len(parts) > 4 else price_1 * 2
        
        valid_days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        if day not in valid_days:
            await send_clean_message(user_id, f"❌ День должен быть: {', '.join(valid_days)}", reply_markup=get_main_menu())
            return
        
        template_id = add_template_slot(day, time, price_1, price_2)
        
        await send_clean_message(
            user_id,
            f"✅ Время добавлено в шаблон!\n"
            f"ID: {template_id} | {day} {time} | {price_1}/{price_2}₽",
            reply_markup=get_main_menu()
        )
        
    except ValueError:
        await send_clean_message(user_id, "❌ Цены должны быть числами", reply_markup=get_main_menu())
    except Exception as e:
        await send_clean_message(user_id, f"❌ Ошибка: {e}", reply_markup=get_main_menu())

@dp.message(Command("del_time"))
async def cmd_del_time(message: Message):
    """Удалить время из шаблона: /del_time ID"""
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await send_clean_message(user_id, "❌ Укажи ID: /del_time 123", reply_markup=get_main_menu())
            return
        
        template_id = int(parts[1])
        
        if delete_template_slot(template_id):
            await send_clean_message(user_id, f"✅ Время {template_id} удалено из шаблона", reply_markup=get_main_menu())
        else:
            await send_clean_message(user_id, f"❌ Время {template_id} не найдено", reply_markup=get_main_menu())
            
    except ValueError:
        await send_clean_message(user_id, "❌ ID должен быть числом", reply_markup=get_main_menu())

@dp.message(Command("template"))
async def cmd_show_template(message: Message):
    """Показать текущий шаблон"""
    user_id = message.from_user.id
    await safe_delete(message)
    
    if user_id != ADMIN_ID:
        await send_clean_message(user_id, "⛔ У тебя нет прав на эту команду.", reply_markup=get_main_menu())
        return
    
    slots = get_all_template_slots()
    
    if not slots:
        await send_clean_message(user_id, "📭 Шаблон пуст. Добавь время через /add_time", reply_markup=get_main_menu())
        return
    
    text = "📋 **Текущий шаблон расписания:**\n\n"
    current_day = ""
    for slot in slots:
        if slot[1] != current_day:
            current_day = slot[1]
            text += f"\n{current_day}:\n"
        text += f"  ID {slot[0]}: {slot[2]} | {slot[3]}/{slot[4]}₽\n"
    
    await send_clean_message(user_id, text, parse_mode="Markdown", reply_markup=get_main_menu())

# ========== ОБРАБОТЧИКИ КОЛБЭКОВ ==========

@dp.callback_query(F.data == "menu")
async def callback_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    user_id = callback.from_user.id
    await state.clear()
    
    await clear_previous_messages(user_id, keep_last=False)
    
    await send_clean_message(
        user_id,
        "Главное меню:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "wallet")
async def callback_wallet(callback: CallbackQuery):
    """Показать кошелек с кнопками пополнения и истории"""
    user_id = callback.from_user.id
    
    await clear_previous_messages(user_id, keep_last=False)
    
    balance = get_balance(user_id)
    
    # Получаем последние транзакции
    conn = sqlite3.connect('rep_bot.db')
    cur = conn.cursor()
    cur.execute('''
    SELECT amount, status, date FROM transactions 
    WHERE user_id = ? 
    ORDER BY date DESC LIMIT 3
    ''', (user_id,))
    recent_transactions = cur.fetchall()
    conn.close()
    
    text = f"""
💰 **Твой кошелек**

**Баланс:** {balance} ₽
    """
    
    if recent_transactions:
        text += "\n\n📊 **Последние операции:**\n"
        for t in recent_transactions:
            amount, status, date = t
            if status == 'confirmed':
                text += f"✅ +{amount}₽ {date[:10]}\n"
            elif status == 'pending':
                text += f"⏳ Заявка {amount}₽ {date[:10]}\n"
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="💳 Пополнить", callback_data="pay"))
    builder.add(types.InlineKeyboardButton(text="📋 Полная история", callback_data="transaction_history"))
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "pay")
async def callback_pay(callback: CallbackQuery, state: FSMContext):
    """Начать пополнение"""
    user_id = callback.from_user.id
    
    await clear_previous_messages(user_id, keep_last=False)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="◀️ Назад к кошельку", callback_data="wallet"))
    
    await send_clean_message(
        user_id,
        "💰 **Введи сумму пополнения**\n\n"
        "Напиши в чат число (например: 500, 1000, 1500):\n\n"
        "⚠️ Минимальная сумма: 100₽\n"
        "⚠️ Максимальная сумма: 15 000₽",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await state.set_state(PaymentStates.waiting_for_amount)
    await callback.answer()

@dp.callback_query(F.data == "rules")
async def callback_rules(callback: CallbackQuery):
    """Показать правила"""
    user_id = callback.from_user.id
    
    await clear_previous_messages(user_id, keep_last=False)
    
    rules_text = """
📋 **Правила занятий**

📅 **Запись**
• Выбирай свободное время в расписании
• Можно записаться на 1 урок (45 мин) или 2 урока (90 мин)
• Доступные форматы: онлайн или оффлайн

💰 **Оплата**
• Баланс пополняется вручную после перевода на карту
• Стоимость урока списывается сразу при записи
• Проверяй баланс в разделе "Кошелек"

❌ **Отмена**
• За 2 и более часов до урока → полный возврат
• Менее чем за 2 часа → деньги уйдут на удержание 25%
• Отменить запись можно в разделе "Мои записи"

⚠️ **Важно**
• Если опаздываешь, предупреди заранее

По всем вопросам пиши @nimpii
    """
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    
    await send_clean_message(
        user_id,
        rules_text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "my_bookings")
async def callback_my_bookings(callback: CallbackQuery):
    """Показать записи пользователя"""
    user_id = callback.from_user.id
    
    await clear_previous_messages(user_id, keep_last=False)
    
    bookings = get_user_bookings(user_id)
    
    if not bookings:
        await send_clean_message(
            user_id,
            "📭 У тебя пока нет записей.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    
    for b in bookings:
        date_obj = datetime.strptime(b[1], "%Y-%m-%d")
        date_str = date_obj.strftime("%d.%m")
        
        if b[3] == 1:
            price = b[5]
            duration_text = "1 урок"
        else:
            price = b[6]
            duration_text = "2 урока"
        
        format_text = "Онлайн" if b[4] == 'online' else "Оффлайн"
        
        button_text = f"{b[0]} {date_str} {b[2]} | {duration_text} | {format_text}"
        builder.add(types.InlineKeyboardButton(
            text=button_text,
            callback_data=f"view_booking_{b[8]}"
        ))
    
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        "📋 **Твои записи:**\n\nНажми на запись, чтобы посмотреть детали или отменить её:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# ========== ПРОФИЛЬ ==========

@dp.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery, state: FSMContext):
    """Показать профиль"""
    user_id = callback.from_user.id
    await state.clear()
    
    await clear_previous_messages(user_id, keep_last=False)
    
    profile = get_profile(user_id)
    
    if not profile:
        await send_clean_message(
            user_id,
            "📋 **Создание профиля**\n\n"
            "Это нужно, чтобы я знал, кто записывается на уроки.\n\n"
            "Шаг 1 из 3:\n"
            "Напиши своё имя:",
            parse_mode="Markdown"
        )
        await state.set_state(ProfileCreation.waiting_for_name)
        await callback.answer()
        return
    
    (_, name, grade, _, default_format, phone, 
     parent_phone, notes, reg_date, last_visit, total_lessons) = profile
    
    format_emoji = "💻 Онлайн" if default_format == 'online' else "🏢 Оффлайн"
    
    text = f"""
📋 **Твой профиль**

👤 **Имя:** {name}
🎓 **Класс:** {grade}
📞 **Телефон:** {phone}
📍 **Формат:** {format_emoji}
📊 **Всего уроков:** {total_lessons}
    """
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data="edit_profile"))
    builder.add(types.InlineKeyboardButton(text="📅 Записаться на урок", callback_data="booking"))
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

# Шаги создания профиля
@dp.message(ProfileCreation.waiting_for_name)
async def process_profile_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    name = message.text.strip()
    
    await safe_delete(message)
    await state.update_data(name=name)
    
    await send_clean_message(
        user_id,
        "📋 **Шаг 2 из 3**\n\n"
        "📚 **Укажи класс:**\n"
        "• Если вы **ученик** - напиши свой класс (1-11)\n"
        "• Если вы **родитель** - напиши класс своего ребёнка\n\n"
        "Пример: 5, 9, 11",
        parse_mode="Markdown"
    )
    await state.set_state(ProfileCreation.waiting_for_grade)

@dp.message(ProfileCreation.waiting_for_grade)
async def process_profile_grade(message: Message, state: FSMContext):
    user_id = message.from_user.id
    grade_input = message.text.strip()
    
    await safe_delete(message)
    
    await state.update_data(grade=grade_input)
    
    await send_clean_message(
        user_id,
        "📋 **Шаг 3 из 3**\n\n"
        "📞 Твой номер телефона для связи\n"
        "(в формате +7XXXXXXXXXX или 8XXXXXXXXXX):",
        parse_mode="Markdown"
    )
    await state.set_state(ProfileCreation.waiting_for_phone)

@dp.message(ProfileCreation.waiting_for_phone)
async def process_profile_phone(message: Message, state: FSMContext):
    user_id = message.from_user.id
    phone = message.text.strip()
    
    await safe_delete(message)
    
    if not phone.replace('+', '').replace('-', '').replace(' ', '').isdigit():
        await send_clean_message(
            user_id,
            "❌ Пожалуйста, введи корректный номер телефона",
            parse_mode="Markdown"
        )
        return
    
    await state.update_data(phone=phone)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="💻 Онлайн", 
        callback_data="format_online"
    ))
    builder.add(types.InlineKeyboardButton(
        text="🏢 Оффлайн", 
        callback_data="format_offline"
    ))
    builder.add(types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        "📍 **Выбери предпочтительный формат занятий:**\n\n"
        "Это можно будет изменить при каждой записи.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await state.set_state(ProfileCreation.waiting_for_format)

@dp.callback_query(ProfileCreation.waiting_for_format, F.data.startswith("format_"))
async def process_profile_format(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    selected_format = callback.data.replace("format_", "")
    
    await clear_previous_messages(user_id, keep_last=False)
    
    data = await state.get_data()
    name = data.get('name')
    grade = data.get('grade')
    phone = data.get('phone')
    
    create_profile(user_id, name, grade, "", phone, selected_format)
    
    await state.clear()
    
    await send_clean_message(
        user_id,
        "✅ **Профиль успешно создан!**\n\n"
        "Теперь ты можешь записываться на уроки.",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== РАСПИСАНИЕ ==========

@dp.callback_query(F.data == "booking")
async def callback_booking(callback: CallbackQuery):
    """Показать дни с доступными окошками"""
    user_id = callback.from_user.id
    
    await clear_previous_messages(user_id, keep_last=False)
    
    # Проверяем, есть ли профиль
    profile = get_profile(user_id)
    if not profile:
        await send_clean_message(
            user_id,
            "⚠️ **Сначала создай профиль!**\n\n"
            "Нажми на кнопку 'Мой профиль' в главном меню.",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return
    
    refresh_weekly_schedule()
    
    slots_by_day = get_slots_by_day()
    
    if not slots_by_day:
        await send_clean_message(
            user_id,
            "Нет свободных окошек.\nПопробуйте позже.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    
    days_mapping = {
        'Пн': 'Понедельник',
        'Вт': 'Вторник', 
        'Ср': 'Среда',
        'Чт': 'Четверг',
        'Пт': 'Пятница',
        'Сб': 'Суббота',
        'Вс': 'Воскресенье'
    }
    
    for day_short, day_full in days_mapping.items():
        if day_short in slots_by_day:
            count = len(slots_by_day[day_short])
            builder.add(types.InlineKeyboardButton(
                text=f"{day_full} ({count})",
                callback_data=f"day_{day_short}"
            ))
    
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    builder.adjust(2)
    
    await send_clean_message(
        user_id,
        "📅 **Выберите день:**\n\nВ скобках количество свободных окошек:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("day_"))
async def callback_show_day_slots(callback: CallbackQuery):
    """Показать окошки для выбранного дня"""
    user_id = callback.from_user.id
    day_short = callback.data.replace("day_", "")
    
    days_mapping = {
        'Пн': 'Понедельник',
        'Вт': 'Вторник', 
        'Ср': 'Среда',
        'Чт': 'Четверг',
        'Пт': 'Пятница',
        'Сб': 'Суббота',
        'Вс': 'Воскресенье'
    }
    day_full = days_mapping.get(day_short, day_short)
    
    await clear_previous_messages(user_id, keep_last=False)
    
    slots_by_day = get_slots_by_day()
    day_slots = slots_by_day.get(day_short, [])
    
    if not day_slots:
        await send_clean_message(
            user_id,
            f"В {day_full} нет свободных окошек.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    
    for slot in day_slots:
        date_obj = datetime.strptime(slot['date'], "%Y-%m-%d")
        date_str = date_obj.strftime("%d.%m")
        
        button_text = f"{slot['time']} ({date_str}) | {slot['price_1']}/{slot['price_2']}₽"
        builder.add(types.InlineKeyboardButton(
            text=button_text,
            callback_data=f"slot_{slot['id']}"
        ))
    
    builder.add(types.InlineKeyboardButton(text="◀️ К выбору дня", callback_data="booking"))
    builder.add(types.InlineKeyboardButton(text="🏠 Меню", callback_data="menu"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        f"📅 **{day_full}**\n\nСвободное время (цена за 1/2 урока):",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("slot_"))
async def process_slot_selection(callback: CallbackQuery):
    """Обрабатывает выбор слота"""
    user_id = callback.from_user.id
    slot_id = int(callback.data.replace("slot_", ""))
    
    user_selected_slot[user_id] = slot_id
    
    await clear_previous_messages(user_id, keep_last=False)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="1 урок (45 мин)",
        callback_data="dur_1"
    ))
    builder.add(types.InlineKeyboardButton(
        text="2 урока (90 мин)",
        callback_data="dur_2"
    ))
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data="booking"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        "⏳ **Выбери длительность урока:**",
        reply_markup=builder.as_markup()
    )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("dur_"))
async def process_duration_selection(callback: CallbackQuery):
    """Обрабатывает выбор длительности"""
    user_id = callback.from_user.id
    duration = int(callback.data.replace("dur_", ""))
    
    slot_id = user_selected_slot.get(user_id)
    
    if not slot_id:
        await send_clean_message(
            user_id,
            "❌ Что-то пошло не так. Попробуй выбрать время заново.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return
    
    await clear_previous_messages(user_id, keep_last=False)
    
    profile = get_profile(user_id)
    default_format = profile[4] if profile else 'online'
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="💻 Онлайн", 
        callback_data=f"book_{slot_id}_{duration}_online"
    ))
    builder.add(types.InlineKeyboardButton(
        text="🏢 Оффлайн", 
        callback_data=f"book_{slot_id}_{duration}_offline"
    ))
    builder.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"slot_{slot_id}"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        f"📍 **Выбери формат занятия:**\n\n"
        f"Продолжительность: {'1 урок (45 мин)' if duration == 1 else '2 урока (90 мин)'}",
        reply_markup=builder.as_markup()
    )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("book_"))
async def process_final_booking(callback: CallbackQuery):
    """Финальное бронирование с форматом"""
    user_id = callback.from_user.id
    
    parts = callback.data.replace("book_", "").split("_")
    slot_id = int(parts[0])
    duration = int(parts[1])
    lesson_format = parts[2]
    
    await clear_previous_messages(user_id, keep_last=False)
    
    new_balance, price = book_slot(slot_id, user_id, duration, lesson_format)
    
    if new_balance is None and price is None:
        await send_clean_message(
            user_id,
            "❌ Это окошко уже занято.\n\n"
            "Попробуй выбрать другое время:",
            reply_markup=get_main_menu()
        )
    elif new_balance is None:
        await send_clean_message(
            user_id,
            f"❌ Недостаточно средств.\n\n"
            f"Нужно: {price}₽\n"
            f"Твой баланс: {get_balance(user_id)}₽\n\n"
            f"Пополни баланс и попробуй снова.",
            reply_markup=get_main_menu()
        )
    else:
        profile = get_profile(user_id)
        name = profile[1] if profile else "Неизвестно"
        phone = profile[5] if profile else "Не указан"
        grade = profile[2] if profile else "?"
        
        duration_text = "2 урока (90 мин)" if duration == 2 else "1 урок (45 мин)"
        format_text = "Онлайн" if lesson_format == "online" else "Оффлайн"
        
        await send_clean_message(
            user_id,
            f"✅ **Ты записан на урок!**\n\n"
            f"⏳ {duration_text}\n"
            f"📍 Формат: {format_text}\n"
            f"💰 Списано: {price}₽\n"
            f"💰 Остаток: {new_balance}₽\n\n"
            f"Если не сможешь прийти, сообщи заранее.",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
        
        try:
            conn = sqlite3.connect('rep_bot.db')
            cur = conn.cursor()
            cur.execute("SELECT day, date, time FROM schedule WHERE id = ?", (slot_id,))
            slot_info = cur.fetchone()
            conn.close()
            
            if slot_info:
                day, date, time = slot_info
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                date_str = date_obj.strftime("%d.%m.%Y")
                
                await bot.send_message(
                    ADMIN_ID,
                    f"📅 **НОВАЯ ЗАПИСЬ!**\n\n"
                    f"👤 **Ученик:** {name}\n"
                    f"📞 **Телефон:** {phone}\n"
                    f"🎓 **Класс:** {grade}\n\n"
                    f"📅 **День:** {day} {date_str}\n"
                    f"⏰ **Время:** {time}\n"
                    f"⏳ **Длительность:** {duration_text}\n"
                    f"📍 **Формат:** {format_text}\n"
                    f"💰 **Списано:** {price}₽\n\n"
                    f"🆔 **ID ученика:** {user_id}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"Ошибка при отправке уведомления админу: {e}")
    
    if user_id in user_selected_slot:
        del user_selected_slot[user_id]
    
    await callback.answer()

# ========== ДЕТАЛИ ЗАПИСИ И ОТМЕНА ==========

@dp.callback_query(F.data.startswith("view_booking_"))
async def callback_view_booking(callback: CallbackQuery):
    """Просмотр деталей записи и возможность отмены"""
    user_id = callback.from_user.id
    booking_id = int(callback.data.replace("view_booking_", ""))
    
    await clear_previous_messages(user_id, keep_last=False)
    
    conn = sqlite3.connect('rep_bot.db')
    cur = conn.cursor()
    cur.execute('''
    SELECT day, date, time, booked_duration, booked_format, price_1, price_2, booked_date 
    FROM schedule 
    WHERE id = ? AND booked_by = ?
    ''', (booking_id, user_id))
    
    booking = cur.fetchone()
    conn.close()
    
    if not booking:
        await send_clean_message(
            user_id,
            "❌ Запись не найдена.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return
    
    day, date, time, duration, lesson_format, price_1, price_2, booked_date = booking
    
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    date_str = date_obj.strftime("%d.%m.%Y")
    
    lesson_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    now = datetime.now()
    hours_before = (lesson_datetime - now).total_seconds() / 3600
    
    if duration == 1:
        price = price_1
        duration_text = "1 урок (45 мин)"
    else:
        price = price_2
        duration_text = "2 урока (90 мин)"
    
    format_text = "Онлайн" if lesson_format == 'online' else "Оффлайн"
    
    text = f"""
📅 **Детали записи:**

📆 **День:** {day} {date_str}
⏰ **Время:** {time}
⏳ **Длительность:** {duration_text}
📍 **Формат:** {format_text}
💰 **Стоимость:** {price}₽
📝 **Записан:** {booked_date[:16]}

📋 **Правила отмены:**
• Больше 2 часов до урока → полный возврат
• Меньше 2 часов до урока →  25% на удержание 
    """
    
    if hours_before < 2 and hours_before > 0:
        text += f"\n⚠️ **До урока осталось менее {hours_before:.1f} часов!**"
    
    builder = InlineKeyboardBuilder()
    
    if lesson_datetime > now:
        builder.add(types.InlineKeyboardButton(
            text="❌ Отменить запись", 
            callback_data=f"cancel_booking_{booking_id}"
        ))
    
    builder.add(types.InlineKeyboardButton(text="◀️ Назад к записям", callback_data="my_bookings"))
    builder.add(types.InlineKeyboardButton(text="🏠 Меню", callback_data="menu"))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_booking_"))
async def callback_cancel_booking(callback: CallbackQuery):
    """Отмена записи"""
    user_id = callback.from_user.id
    booking_id = int(callback.data.replace("cancel_booking_", ""))
    
    await clear_previous_messages(user_id, keep_last=False)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="✅ Да, отменить", 
        callback_data=f"confirm_cancel_{booking_id}"
    ))
    builder.add(types.InlineKeyboardButton(
        text="❌ Нет, оставить", 
        callback_data=f"view_booking_{booking_id}"
    ))
    builder.adjust(1)
    
    await send_clean_message(
        user_id,
        "⚠️ **Ты уверен, что хочешь отменить запись?**\n\n"
        "Деньги вернутся на баланс (с учётом правил отмены).",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_cancel_"))
async def callback_confirm_cancel(callback: CallbackQuery):
    """Подтверждение отмены записи"""
    user_id = callback.from_user.id
    booking_id = int(callback.data.replace("confirm_cancel_", ""))
    
    await clear_previous_messages(user_id, keep_last=False)
    
    result = cancel_booking(booking_id, user_id)
    
    if result[0] is None:
        await send_clean_message(
            user_id,
            f"❌ {result[4]}",
            reply_markup=get_main_menu()
        )
    else:
        new_balance, refund, penalty, booking_info, lesson_format = result
        
        if penalty > 0:
            await send_clean_message(
                user_id,
                f"⚠️ **Запись отменена менее чем за 2 часа до урока!**\n\n"
                f"📅 Запись: {booking_info}\n"
                f"💰 Стоимость урока: {refund + penalty}₽\n"
                f"💸 Удержание (25%): {penalty}₽\n"
                f"✅ Возвращено: {refund}₽\n"
                f"💰 Новый баланс: {new_balance}₽\n\n"
                f"Правила отмены: при отмене менее чем за 2 часа "
                f"производится удержание 25% от стоимости урока.",
                reply_markup=get_main_menu(),
                parse_mode="Markdown"
            )
            
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️ **ЗАПИСЬ ОТМЕНЕНА (УДЕРЖАНИЕ)!**\n\n"
                    f"👤 Пользователь ID: {user_id}\n"
                    f"📅 Запись: {booking_info}\n"
                    f"📍 Формат: {'Онлайн' if lesson_format == 'online' else 'Оффлайн'}\n"
                    f"💰 Стоимость: {refund + penalty}₽\n"
                    f"💸 Удержание (25%): {penalty}₽\n"
                    f"✅ Возвращено: {refund}₽",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            await send_clean_message(
                user_id,
                f"✅ **Запись отменена!**\n\n"
                f"📅 Запись: {booking_info}\n"
                f"💰 Возвращено: {refund}₽\n"
                f"💰 Новый баланс: {new_balance}₽",
                reply_markup=get_main_menu(),
                parse_mode="Markdown"
            )
            
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"✅ **ЗАПИСЬ ОТМЕНЕНА!**\n\n"
                    f"👤 Пользователь ID: {user_id}\n"
                    f"📅 Запись: {booking_info}\n"
                    f"📍 Формат: {'Онлайн' if lesson_format == 'online' else 'Оффлайн'}\n"
                    f"💰 Возвращено: {refund}₽",
                    parse_mode="Markdown"
                )
            except:
                pass
    
    await callback.answer()

# ========== ОБРАБОТЧИК ВВОДА СУММЫ ==========

@dp.message(PaymentStates.waiting_for_amount)
async def process_payment_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Получаем предыдущее сообщение бота (с просьбой ввести сумму)
    prev_msg = user_last_message.get(user_id)
    
    # Удаляем сообщение пользователя с суммой
    await safe_delete(message)
    
    try:
        amount = int(message.text.strip())
        
        if amount < 100:
            # Если ошибка - удаляем старое и отправляем новое
            if prev_msg:
                try:
                    await prev_msg.delete()
                except:
                    pass
            await send_clean_message(
                user_id,
                "❌ Минимальная сумма: 100₽\n\n💰 Введи сумму еще раз:",
                parse_mode="Markdown"
            )
            return
        
        if amount > 15000:
            if prev_msg:
                try:
                    await prev_msg.delete()
                except:
                    pass
            await send_clean_message(
                user_id,
                "❌ Максимальная сумма: 15000₽\n\n💰 Введи сумму еще раз:",
                parse_mode="Markdown"
            )
            return
        
        transaction_id = add_transaction(user_id, amount)
        
        # Создаем клавиатуру
        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="◀️ Назад к кошельку", 
            callback_data="wallet"
        ))
        builder.adjust(1)
        
        # Если есть предыдущее сообщение бота - удаляем его
        if prev_msg:
            try:
                await prev_msg.delete()
            except:
                pass
        
        # Отправляем фото с реквизитами
        photo = FSInputFile("images/qr_payment.jpg")
        
        sent_photo = await bot.send_photo(
            user_id,
            photo,
            caption=f"✅ **Заявка на пополнение {amount}₽ создана!**\n\n"
                    "💳 **Реквизиты для оплаты:**\n"
                    "`8-(927)-922-00-32`\n"
                    "Получатель: **З.Д.К.**\n\n"
                    "📝 **В комментарии к переводу укажите:**\n"
                    f"`USER-{user_id}`\n\n"
                    "⚠️ Кошелек пополнится в течение некоторого времени",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        # Сохраняем новое сообщение
        user_last_message[user_id] = sent_photo
        
        # Уведомление админу
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔔 **Новый запрос на пополнение!**\n\n"
                f"Пользователь: @{message.from_user.username or 'нет'} ({message.from_user.full_name})\n"
                f"ID: {user_id}\n"
                f"Сумма: {amount}₽\n"
                f"Транзакция №: {transaction_id}\n\n"
                f"Подтверди: `/confirm {transaction_id}`\n"
                f"Отмени: `/cancel {transaction_id}`",
                parse_mode="Markdown"
            )
        except:
            pass
        
        await state.clear()
        
    except ValueError:
        if prev_msg:
            try:
                await prev_msg.delete()
            except:
                pass
        await send_clean_message(
            user_id,
            "❌ Это не число!\n\n💰 Введи сумму цифрами (например: 500):",
            parse_mode="Markdown"
        )
    except Exception as e:
        if prev_msg:
            try:
                await prev_msg.delete()
            except:
                pass
        await send_clean_message(
            user_id,
            f"❌ Ошибка: {e}",
            reply_markup=get_main_menu()
        )
        await state.clear()

# ========== ЗАПУСК ==========

async def main():
    init_db()
    init_schedule_db()
    init_profile_db()
    
    deleted, created = refresh_weekly_schedule()
    print(f" Расписание обновлено: удалено {deleted}, создано {created}")
    
    print("База данных готова")
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())