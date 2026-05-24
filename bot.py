import asyncio
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# ========== ХРАНЕНИЕ ==========
users = {}
spots = {
    "dumskaya": {"name": "Думская", "active": []},
    "skripka": {"name": "Скрипка", "active": []},
    "pionerka_pod_mostom": {"name": "Пионерка под мостом", "active": []},
    "pionerka_park": {"name": "Пионерка парк", "active": []},
    "ska": {"name": "СКА", "active": []},
    "moskovskaya": {"name": "Московская", "active": []},
    "porebriki_obvodny": {"name": "Поребрики на Обводном", "active": []},
    "piskar_pod_mostom": {"name": "Пискарь под мостом", "active": []},
    "udelka": {"name": "Уделка", "active": []},
    "ploshad_lenina": {"name": "Площадь Ленина", "active": []},
    "ssa": {"name": "ССА", "active": []},
    "virazh": {"name": "ВираЖ", "active": []},
    "begovaya": {"name": "Беговая", "active": []},
    "park_trekhsotletiya": {"name": "Парк Трехсотлетия", "active": []},
    "veteranov": {"name": "Ветеранов", "active": []},
}
forum_topics = {}
market_listings = {}

next_topic_id = 1
next_topic_msg_id = 1
next_listing_id = 1

# ========== FSM ==========
class ProfileStates(StatesGroup):
    waiting_nickname = State()
    waiting_stance = State()
    waiting_contacts = State()

class ForumStates(StatesGroup):
    waiting_topic_name = State()
    waiting_topic_message = State()

class MarketStates(StatesGroup):
    waiting_listing_text = State()
    waiting_listing_photo = State()

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    buttons = [
        [KeyboardButton(text="🛹 Споты")],
        [KeyboardButton(text="🏪 Барахолка"), KeyboardButton(text="💬 Форум / Чат")],
        [KeyboardButton(text="👤 Моя анкета")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def spots_list_keyboard():
    kb = []
    for spot_id, spot in spots.items():
        indicator = "🔥 " if spot["active"] else ""
        kb.append([InlineKeyboardButton(text=f"{indicator}{spot['name']}", callback_data=f"spot_{spot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def spot_detail_keyboard(spot_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я здесь", callback_data=f"spot_join_{spot_id}")],
        [InlineKeyboardButton(text="❌ Уехал", callback_data=f"spot_leave_{spot_id}")],
        [InlineKeyboardButton(text="👥 Кто на споте", callback_data=f"spot_who_{spot_id}")]
    ])

def topics_list_keyboard():
    kb = []
    for tid, topic in forum_topics.items():
        kb.append([InlineKeyboardButton(text=f"📌 {topic['name']} ({len(topic['messages'])} соо)", callback_data=f"topic_{tid}")])
    kb.append([InlineKeyboardButton(text="➕ Создать тему", callback_data="topic_create")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def topic_actions_keyboard(topic_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Написать в тему", callback_data=f"topic_write_{topic_id}")],
        [InlineKeyboardButton(text="📋 Список тем", callback_data="topic_list")]
    ])

def market_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все объявления", callback_data="market_list")],
        [InlineKeyboardButton(text="➕ Разместить объявление", callback_data="market_create")]
    ])

def market_list_keyboard(page: int = 0, items_per_page: int = 5):
    listings = list(market_listings.values())
    listings.reverse()
    total = len(listings)
    start = page * items_per_page
    end = start + items_per_page
    current = listings[start:end]
    
    kb = []
    for listing in current:
        preview = listing['text'][:30] + "..." if len(listing['text']) > 30 else listing['text']
        kb.append([InlineKeyboardButton(text=f"📦 {listing['nickname']}: {preview}", callback_data=f"market_view_{listing['listing_id']}")])
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"market_page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"market_page_{page+1}"))
    if nav:
        kb.append(nav)
    
    kb.append([InlineKeyboardButton(text="➕ Новое объявление", callback_data="market_create")])
    kb.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="market_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def listing_detail_keyboard(listing_id: int, user_id: int):
    kb = [
        [InlineKeyboardButton(text="📋 Список объявлений", callback_data="market_list")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="market_main")]
    ]
    if market_listings[listing_id]["user_id"] == user_id:
        kb.append([InlineKeyboardButton(text="🗑️ Удалить объявление", callback_data=f"market_delete_{listing_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ========== ВСПОМОГАТЕЛЬНЫЕ ==========
def get_user_nickname(user_id: int) -> str:
    u = users.get(user_id, {})
    return u.get("nickname", f"User_{user_id}")

def ensure_user(user_id: int):
    if user_id not in users:
        users[user_id] = {"nickname": None, "stance": None, "contacts": None, "is_admin": user_id in ADMIN_IDS}

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
async def start_command(message: Message):
    ensure_user(message.from_user.id)
    await message.answer(
        "Салют!\n\nСпоты, барахолка, форум — всё здесь.\n\nЗаполни анкету: /profile",
        reply_markup=main_keyboard()
    )

async def profile_command(message: Message, state: FSMContext):
    uid = message.from_user.id
    ensure_user(uid)
    if users[uid].get("nickname"):
        u = users[uid]
        text = f"👤 Анкета:\nНик: {u.get('nickname', '—')}\nСтойка: {u.get('stance', '—')}\nКонтакты: {u.get('contacts', '—')}"
        await message.answer(text, reply_markup=main_keyboard())
    else:
        await message.answer("Придумай никнейм (он будет виден всем):")
        await state.set_state(ProfileStates.waiting_nickname)

async def nickname_received(message: Message, state: FSMContext):
    if len(message.text) < 2 or len(message.text) > 20:
        await message.answer("Никнейм должен быть от 2 до 20 символов.")
        return
    users[message.from_user.id]["nickname"] = message.text
    await message.answer("Любимая стойка (обычная / гуфи / не важно):")
    await state.set_state(ProfileStates.waiting_stance)

async def stance_received(message: Message, state: FSMContext):
    users[message.from_user.id]["stance"] = message.text
    await message.answer("Контакты (Telegram/Instagram) или /skip:")
    await state.set_state(ProfileStates.waiting_contacts)

async def contacts_received(message: Message, state: FSMContext):
    users[message.from_user.id]["contacts"] = message.text
    await message.answer("Анкета готова!", reply_markup=main_keyboard())
    await state.clear()

async def skip_contacts(message: Message, state: FSMContext):
    users[message.from_user.id]["contacts"] = "Не указаны"
    await message.answer("Анкета готова!", reply_markup=main_keyboard())
    await state.clear()

# ---------- СПОТЫ ----------
async def show_spots_list(message: Message):
    await message.answer("Выбери спот:", reply_markup=spots_list_keyboard())

async def spot_detail(callback: CallbackQuery):
    spot_id = callback.data.split("_")[1]
    spot = spots[spot_id]
    active_count = len(spot["active"])
    status_text = "🟢 Активен" if active_count > 0 else "⚪ Нет активных"
    text = f"📍 *{spot['name']}*\n{status_text} (катаются: {active_count})"
    
    if callback.message.text != text:
        await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id), parse_mode="Markdown")
    await callback.answer()

async def join_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    ensure_user(uid)
    if uid not in spots[spot_id]["active"]:
        spots[spot_id]["active"].append(uid)
    await callback.answer("✅ Ты на споте!", show_alert=True)
    
    spot = spots[spot_id]
    text = f"📍 *{spot['name']}*\n🟢 Активен (катаются: {len(spot['active'])})\n\nТы отметился!"
    
    if callback.message.text != text:
        await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id), parse_mode="Markdown")

async def leave_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    if uid in spots[spot_id]["active"]:
        spots[spot_id]["active"].remove(uid)
    await callback.answer("❌ Ты уехал", show_alert=True)
    
    spot = spots[spot_id]
    text = f"📍 *{spot['name']}*\n{'🟢 Активен' if spot['active'] else '⚪ Нет активных'} (катаются: {len(spot['active'])})"
    
    if callback.message.text != text:
        await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id), parse_mode="Markdown")

async def who_on_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    active_ids = spots[spot_id]["active"]
    if not active_ids:
        text = "На споте никого нет."
    else:
        names = [get_user_nickname(uid) for uid in active_ids]
        text = "👥 Сейчас катаются:\n" + "\n".join(f"• {name}" for name in names)
    await callback.message.answer(text)
    await callback.answer()

# ---------- ФОРУМ ----------
async def forum_menu(message: Message):
    await message.answer("📚 Форум: выбери тему или создай новую:", reply_markup=topics_list_keyboard())

async def topic_create_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Придумай название для новой темы (3-50 символов):")
    await state.set_state(ForumStates.waiting_topic_name)
    await callback.answer()

async def topic_name_received(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3 or len(name) > 50:
        await message.answer("Название должно быть от 3 до 50 символов.")
        return
    global next_topic_id
    forum_topics[next_topic_id] = {
        "name": name,
        "creator_id": message.from_user.id,
        "created_at": datetime.now(),
        "messages": []
    }
    await message.answer(f"✅ Тема «{name}» создана!", reply_markup=main_keyboard())
    next_topic_id += 1
    await state.clear()

async def topic_open(callback: CallbackQuery):
    topic_id = int(callback.data.split("_")[1])
    topic = forum_topics.get(topic_id)
    if not topic:
        await callback.message.edit_text("❌ Тема не найдена")
        return
    text = f"📌 *{topic['name']}*\n\n"
    for msg in topic["messages"][-10:]:
        text += f"👤 {msg['nickname']} [{msg['timestamp'].strftime('%H:%M')}]:\n{msg['text']}\n\n"
    text += f"\n💡 Ответить: `/reply_topic {topic_id} <id сообщения> <текст>`"
    
    if callback.message.text != text:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=topic_actions_keyboard(topic_id))
    await callback.answer()

async def topic_write_start(callback: CallbackQuery, state: FSMContext):
    topic_id = int(callback.data.split("_")[2])
    await state.update_data(topic_id=topic_id)
    await callback.message.answer("✏️ Напиши сообщение в тему:")
    await state.set_state(ForumStates.waiting_topic_message)
    await callback.answer()

async def topic_message_received(message: Message, state: FSMContext):
    data = await state.get_data()
    topic_id = data["topic_id"]
    topic = forum_topics.get(topic_id)
    if not topic:
        await message.answer("❌ Тема не найдена")
        await state.clear()
        return
    global next_topic_msg_id
    msg = {
        "msg_id": next_topic_msg_id,
        "user_id": message.from_user.id,
        "nickname": get_user_nickname(message.from_user.id),
        "text": message.text,
        "timestamp": datetime.now()
    }
    topic["messages"].append(msg)
    await message.answer(f"✅ Сообщение #{next_topic_msg_id} добавлено в тему «{topic['name']}»")
    next_topic_msg_id += 1
    await state.clear()

async def reply_to_topic_message(message: Message):
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer("📝 Используй: `/reply_topic <id темы> <id сообщения> <твой ответ>`", parse_mode="Markdown")
        return
    try:
        topic_id = int(parts[1])
        target_msg_id = int(parts[2])
        reply_text = parts[3]
    except:
        await message.answer("❌ Неверный формат")
        return
    topic = forum_topics.get(topic_id)
    if not topic:
        await message.answer("❌ Тема не найдена")
        return
    target_msg = None
    for msg in topic["messages"]:
        if msg["msg_id"] == target_msg_id:
            target_msg = msg
            break
    if not target_msg:
        await message.answer("❌ Сообщение не найдено")
        return
    author = get_user_nickname(message.from_user.id)
    await message.answer(f"✅ Ответ отправлен {target_msg['nickname']}")
    try:
        await bot.send_message(target_msg["user_id"], f"📩 Ответ от {author}:\n{reply_text}")
    except:
        pass

async def topic_list(callback: CallbackQuery):
    text = "📚 Список тем:"
    if callback.message.text != text:
        await callback.message.edit_text(text, reply_markup=topics_list_keyboard())
    await callback.answer()