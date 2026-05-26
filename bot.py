import asyncio
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, Location
)
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# ========== ХРАНЕНИЕ ==========
users = {}
# Стандартные споты + пользовательские будут в одном словаре
# Структура: spot_id: {"name": str, "description": str, "photo_id": str (опционально), "lat": float, "lon": float, "added_by": int, "is_custom": bool}
spots = {
    "dumskaya": {"name": "Думская", "description": "", "photo_id": None, "lat": 59.9343, "lon": 30.3351, "added_by": 0, "is_custom": False, "active": []},
    "skripka": {"name": "Скрипка", "description": "", "photo_id": None, "lat": 59.9345, "lon": 30.3355, "added_by": 0, "is_custom": False, "active": []},
    "pionerka_pod_mostom": {"name": "Пионерка под мостом", "description": "", "photo_id": None, "lat": 59.9500, "lon": 30.3167, "added_by": 0, "is_custom": False, "active": []},
    "pionerka_park": {"name": "Пионерка парк", "description": "", "photo_id": None, "lat": 59.9500, "lon": 30.3167, "added_by": 0, "is_custom": False, "active": []},
    "ska": {"name": "СКА", "description": "", "photo_id": None, "lat": 59.9345, "lon": 30.3351, "added_by": 0, "is_custom": False, "active": []},
    "moskovskaya": {"name": "Московская", "description": "", "photo_id": None, "lat": 59.8925, "lon": 30.3189, "added_by": 0, "is_custom": False, "active": []},
    "porebriki_obvodny": {"name": "Поребрики на Обводном", "description": "", "photo_id": None, "lat": 59.9126, "lon": 30.3202, "added_by": 0, "is_custom": False, "active": []},
    "piskar_pod_mostom": {"name": "Пискарь под мостом", "description": "", "photo_id": None, "lat": 59.9500, "lon": 30.3167, "added_by": 0, "is_custom": False, "active": []},
    "udelka": {"name": "Уделка", "description": "", "photo_id": None, "lat": 60.0167, "lon": 30.3167, "added_by": 0, "is_custom": False, "active": []},
    "ploshad_lenina": {"name": "Площадь Ленина", "description": "", "photo_id": None, "lat": 59.9325, "lon": 30.3069, "added_by": 0, "is_custom": False, "active": []},
    "ssa": {"name": "ССА", "description": "", "photo_id": None, "lat": 59.9343, "lon": 30.3351, "added_by": 0, "is_custom": False, "active": []},
    "virazh": {"name": "ВираЖ", "description": "", "photo_id": None, "lat": 59.9343, "lon": 30.3351, "added_by": 0, "is_custom": False, "active": []},
    "begovaya": {"name": "Беговая", "description": "", "photo_id": None, "lat": 59.9895, "lon": 30.1942, "added_by": 0, "is_custom": False, "active": []},
    "park_trekhsotletiya": {"name": "Парк Трехсотлетия", "description": "", "photo_id": None, "lat": 59.9711, "lon": 30.2083, "added_by": 0, "is_custom": False, "active": []},
    "veteranov": {"name": "Ветеранов", "description": "", "photo_id": None, "lat": 59.8425, "lon": 30.2600, "added_by": 0, "is_custom": False, "active": []},
    "bugry_park": {"name": "Парк в Бугpax", "description": "", "photo_id": None, "lat": 60.0800, "lon": 30.4300, "added_by": 0, "is_custom": False, "active": []},
}
next_spot_id = 1000  # для пользовательских спотов
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

class EditProfileStates(StatesGroup):
    waiting_nickname = State()
    waiting_stance = State()
    waiting_contacts = State()

class ForumStates(StatesGroup):
    waiting_topic_name = State()
    waiting_topic_message = State()

class MarketStates(StatesGroup):
    waiting_listing_text = State()
    waiting_listing_photo = State()

class AddSpotStates(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_photo = State()
    waiting_location = State()

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
    # Показываем только активные споты (без учёта is_custom, все)
    for spot_id, spot in spots.items():
        indicator = "🔥 " if spot.get("active") and len(spot["active"]) > 0 else ""
        # Помечаем пользовательские споты звёздочкой
        marker = "⭐ " if spot.get("is_custom") else ""
        kb.append([InlineKeyboardButton(text=f"{indicator}{marker}{spot['name']}", callback_data=f"spot_{spot_id}")])
    # Кнопка добавления спота
    kb.append([InlineKeyboardButton(text="➕ Добавить свой спот", callback_data="add_spot_start")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def spot_detail_keyboard(spot_id: str, user_id: int = None):
    kb = [
        [InlineKeyboardButton(text="✅ Я здесь", callback_data=f"spot_join_{spot_id}")],
        [InlineKeyboardButton(text="❌ Уехал", callback_data=f"spot_leave_{spot_id}")],
        [InlineKeyboardButton(text="👥 Кто на споте", callback_data=f"spot_who_{spot_id}")]
    ]
    # Если у спота есть координаты, добавим кнопку карты
    spot = spots.get(spot_id)
    if spot and spot.get("lat") and spot.get("lon"):
        maps_url = f"https://www.google.com/maps?q={spot['lat']},{spot['lon']}"
        kb.append([InlineKeyboardButton(text="🗺️ Показать на карте", url=maps_url)])
    # Если спот добавлен пользователем и это его спот, можно добавить кнопку удаления (опционально)
    if user_id and spot and spot.get("added_by") == user_id:
        kb.append([InlineKeyboardButton(text="🗑️ Удалить мой спот", callback_data=f"spot_delete_{spot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

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
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать анкету", callback_data="edit_profile")]
        ])
        await message.answer(text, reply_markup=kb)
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

# ---------- РЕДАКТИРОВАНИЕ АНКЕТЫ ----------
async def edit_profile_command(message: Message, state: FSMContext):
    uid = message.from_user.id
    ensure_user(uid)
    u = users[uid]
    await message.answer(
        "✏️ *Редактирование анкеты*\n\n"
        "Введи новый никнейм (или `-` чтобы оставить текущий):\n"
        f"Текущий: `{u.get('nickname', 'не задан')}`",
        parse_mode="Markdown"
    )
    await state.set_state(EditProfileStates.waiting_nickname)

async def edit_nickname_received(message: Message, state: FSMContext):
    uid = message.from_user.id
    new_nick = message.text.strip()
    if new_nick != "-":
        if len(new_nick) < 2 or len(new_nick) > 20:
            await message.answer("Никнейм должен быть от 2 до 20 символов. Попробуй ещё (или `-` чтобы пропустить):")
            return
        users[uid]["nickname"] = new_nick
    await message.answer(
        "✏️ Введи новую любимую стойку (или `-` чтобы оставить текущую):\n"
        f"Текущая: `{users[uid].get('stance', 'не задана')}`",
        parse_mode="Markdown"
    )
    await state.set_state(EditProfileStates.waiting_stance)

async def edit_stance_received(message: Message, state: FSMContext):
    uid = message.from_user.id
    new_stance = message.text.strip()
    if new_stance != "-":
        users[uid]["stance"] = new_stance
    await message.answer(
        "✏️ Введи новые контакты (или `-` чтобы оставить текущие):\n"
        f"Текущие: `{users[uid].get('contacts', 'не указаны')}`",
        parse_mode="Markdown"
    )
    await state.set_state(EditProfileStates.waiting_contacts)

async def edit_contacts_received(message: Message, state: FSMContext):
    uid = message.from_user.id
    new_contacts = message.text.strip()
    if new_contacts != "-":
        users[uid]["contacts"] = new_contacts
    await message.answer("✅ Анкета обновлена!", reply_markup=main_keyboard())
    await state.clear()

async def edit_profile_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Редактирование анкеты")
    await edit_profile_command(callback.message, state)
    await callback.answer()

# ---------- СПОТЫ (основные функции + добавление) ----------
async def show_spots_list(message: Message):
    await message.answer("Выбери спот или добавь свой:", reply_markup=spots_list_keyboard())

async def spot_detail(callback: CallbackQuery):
    spot_id = callback.data.split("_")[1]
    spot = spots.get(spot_id)
    if not spot:
        await callback.message.edit_text("❌ Спот не найден")
        await callback.answer()
        return
    active_count = len(spot.get("active", []))
    status_text = "🟢 Активен" if active_count > 0 else "⚪ Нет активных"
    text = f"📍 *{spot['name']}*\n{status_text} (катаются: {active_count})\n\n"
    if spot.get("description"):
        text += f"📝 {spot['description']}\n\n"
    if spot.get("is_custom"):
        text += f"👤 Добавлен: {get_user_nickname(spot['added_by'])}\n"
    
    await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id, callback.from_user.id), parse_mode="Markdown")
    await callback.answer()

async def join_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    ensure_user(uid)
    spot = spots.get(spot_id)
    if not spot:
        await callback.answer("Спот не найден", show_alert=True)
        return
    if "active" not in spot:
        spot["active"] = []
    if uid not in spot["active"]:
        spot["active"].append(uid)
    await callback.answer("✅ Ты на споте!", show_alert=True)
    
    active_count = len(spot["active"])
    text = f"📍 *{spot['name']}*\n🟢 Активен (катаются: {active_count})\n\nТы отметился!"
    if spot.get("description"):
        text += f"\n📝 {spot['description']}"
    await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id, callback.from_user.id), parse_mode="Markdown")

async def leave_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    spot = spots.get(spot_id)
    if spot and uid in spot.get("active", []):
        spot["active"].remove(uid)
    await callback.answer("❌ Ты уехал", show_alert=True)
    
    active_count = len(spot.get("active", []))
    text = f"📍 *{spot['name']}*\n{'🟢 Активен' if active_count > 0 else '⚪ Нет активных'} (катаются: {active_count})"
    if spot.get("description"):
        text += f"\n📝 {spot['description']}"
    await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id, callback.from_user.id), parse_mode="Markdown")

async def who_on_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    spot = spots.get(spot_id)
    if not spot:
        await callback.answer("Спот не найден", show_alert=True)
        return
    active_ids = spot.get("active", [])
    if not active_ids:
        text = "На споте никого нет."
    else:
        names = [get_user_nickname(uid) for uid in active_ids]
        text = "👥 Сейчас катаются:\n" + "\n".join(f"• {name}" for name in names)
    await callback.message.answer(text)
    await callback.answer()

# ---------- ДОБАВЛЕНИЕ НОВОГО СПОТА ----------
async def add_spot_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Давай добавим новый спот!\n\nВведи название спота:")
    await state.set_state(AddSpotStates.waiting_name)
    await callback.answer()

async def add_spot_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3 or len(name) > 50:
        await message.answer("Название должно быть от 3 до 50 символов. Попробуй ещё:")
        return
    await state.update_data(name=name)
    await message.answer("📝 Теперь введи описание спота (что там за особенности, какой рельс, и т.д.):")
    await state.set_state(AddSpotStates.waiting_description)

async def add_spot_description(message: Message, state: FSMContext):
    description = message.text.strip()
    if len(description) < 5:
        await message.answer("Описание должно быть хотя бы 5 символов. Попробуй ещё:")
        return
    await state.update_data(description=description)
    await message.answer("📸 Отправь фото спота (можно просто крутое фото или /skip):")
    await state.set_state(AddSpotStates.waiting_photo)

async def add_spot_photo(message: Message, state: FSMContext):
    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await message.answer("📍 Теперь отправь *геолокацию* спота (кнопка 📎 → Location).\n\nЕсли не хочешь указывать координаты, отправь /skip.", parse_mode="Markdown")
    await state.set_state(AddSpotStates.waiting_location)

async def add_spot_skip_photo(message: Message, state: FSMContext):
    await state.update_data(photo_id=None)
    await message.answer("📍 Теперь отправь *геолокацию* спота (кнопка 📎 → Location).\n\nЕсли не хочешь указывать координаты, отправь /skip.", parse_mode="Markdown")
    await state.set_state(AddSpotStates.waiting_location)

async def add_spot_location(message: Message, state: FSMContext):
    lat = None
    lon = None
    if message.location:
        lat = message.location.latitude
        lon = message.location.longitude
    data = await state.get_data()
    name = data.get("name")
    description = data.get("description")
    photo_id = data.get("photo_id")
    
    global next_spot_id
    spot_id = str(next_spot_id)
    next_spot_id += 1
    
    spots[spot_id] = {
        "name": name,
        "description": description,
        "photo_id": photo_id,
        "lat": lat,
        "lon": lon,
        "added_by": message.from_user.id,
        "is_custom": True,
        "active": []
    }
    
    await message.answer(f"✅ Спот «{name}» успешно добавлен! Теперь его могут видеть все скейтеры.", reply_markup=main_keyboard())
    await state.clear()

async def add_spot_skip_location(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data.get("name")
    description = data.get("description")
    photo_id = data.get("photo_id")
    
    global next_spot_id
    spot_id = str(next_spot_id)
    next_spot_id += 1
    
    spots[spot_id] = {
        "name": name,
        "description": description,
        "photo_id": photo_id,
        "lat": None,
        "lon": None,
        "added_by": message.from_user.id,
        "is_custom": True,
        "active": []
    }
    
    await message.answer(f"✅ Спот «{name}» добавлен без координат. Другие увидят описание и фото.", reply_markup=main_keyboard())
    await state.clear()

async def delete_custom_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    spot = spots.get(spot_id)
    if not spot or not spot.get("is_custom") or spot.get("added_by") != callback.from_user.id:
        await callback.answer("❌ Нельзя удалить чужой спот", show_alert=True)
        return
    del spots[spot_id]
    await callback.message.edit_text("🗑️ Спот удалён!")
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

# ---------- БАРАХОЛКА ----------
async def market_menu(message: Message):
    await message.answer("🛍️ Барахолка:", reply_markup=market_main_keyboard())

async def market_list(callback: CallbackQuery, page: int = 0):
    if not market_listings:
        text = "📭 Пока нет объявлений. Стань первым!"
        if callback.message.text != text:
            await callback.message.edit_text(text, reply_markup=market_main_keyboard())
        await callback.answer()
        return
    text = "📋 Список объявлений:"
    if callback.message.text != text:
        await callback.message.edit_text(text, reply_markup=market_list_keyboard(page))
    await callback.answer()

async def market_list_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    await market_list(callback, page)

async def market_create_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Напиши текст объявления:")
    await state.set_state(MarketStates.waiting_listing_text)
    await callback.answer()

async def market_text_received(message: Message, state: FSMContext):
    if len(message.text) < 5:
        await message.answer("Текст должен быть длиннее 5 символов.")
        return
    await state.update_data(listing_text=message.text)
    await message.answer("📸 Отправь фото (или /skip):")
    await state.set_state(MarketStates.waiting_listing_photo)

async def market_photo_received(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data["listing_text"]
    photo_id = message.photo[-1].file_id if message.photo else None
    global next_listing_id
    market_listings[next_listing_id] = {
        "listing_id": next_listing_id,
        "user_id": message.from_user.id,
        "nickname": get_user_nickname(message.from_user.id),
        "text": text,
        "photo_id": photo_id,
        "created_at": datetime.now()
    }
    await message.answer(f"✅ Объявление #{next_listing_id} опубликовано!", reply_markup=main_keyboard())
    next_listing_id += 1
    await state.clear()

async def market_skip_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data["listing_text"]
    global next_listing_id
    market_listings[next_listing_id] = {
        "listing_id": next_listing_id,
        "user_id": message.from_user.id,
        "nickname": get_user_nickname(message.from_user.id),
        "text": text,
        "photo_id": None,
        "created_at": datetime.now()
    }
    await message.answer(f"✅ Объявление #{next_listing_id} опубликовано!", reply_markup=main_keyboard())
    next_listing_id += 1
    await state.clear()

async def market_view(callback: CallbackQuery):
    listing_id = int(callback.data.split("_")[2])
    listing = market_listings.get(listing_id)
    if not listing:
        await callback.answer("Объявление не найдено", show_alert=True)
        return
    text = f"📦 *Объявление #{listing['listing_id']}*\n👤 {listing['nickname']}\n📅 {listing['created_at'].strftime('%d.%m.%Y %H:%M')}\n\n{listing['text']}"
    if listing['photo_id']:
        await callback.message.answer_photo(listing['photo_id'], caption=text, parse_mode="Markdown", reply_markup=listing_detail_keyboard(listing_id, callback.from_user.id))
    else:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=listing_detail_keyboard(listing_id, callback.from_user.id))
    await callback.answer()

async def market_delete(callback: CallbackQuery):
    listing_id = int(callback.data.split("_")[2])
    listing = market_listings.get(listing_id)
    if not listing or listing["user_id"] != callback.from_user.id:
        await callback.answer("Нельзя удалить чужое объявление", show_alert=True)
        return
    del market_listings[listing_id]
    await callback.message.edit_text("🗑️ Объявление удалено!", reply_markup=market_main_keyboard())
    await callback.answer()

async def market_main(callback: CallbackQuery):
    text = "🛍️ Барахолка:"
    if callback.message.text != text:
        await callback.message.edit_text(text, reply_markup=market_main_keyboard())
    await callback.answer()

# ---------- АДМИН ----------
async def broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет прав")
        return
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("/broadcast <текст>")
        return
    count = 0
    for uid in users:
        try:
            await bot.send_message(uid, f"📢 {text}")
            count += 1
        except:
            pass
    await message.answer(f"Отправлено {count} пользователям")

# ========== ЗАПУСК ==========
async def main():
    global bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(start_command, Command("start"))
    dp.message.register(profile_command, Command("profile"))
    dp.message.register(edit_profile_command, Command("edit_profile"))
    dp.message.register(skip_contacts, Command("skip"))
    dp.message.register(broadcast, Command("broadcast"))

    dp.message.register(show_spots_list, F.text == "🛹 Споты")
    dp.message.register(forum_menu, F.text == "💬 Форум / Чат")
    dp.message.register(market_menu, F.text == "🏪 Барахолка")
    dp.message.register(profile_command, F.text == "👤 Моя анкета")

    dp.message.register(nickname_received, ProfileStates.waiting_nickname)
    dp.message.register(stance_received, ProfileStates.waiting_stance)
    dp.message.register(contacts_received, ProfileStates.waiting_contacts)

    dp.message.register(edit_nickname_received, EditProfileStates.waiting_nickname)
    dp.message.register(edit_stance_received, EditProfileStates.waiting_stance)
    dp.message.register(edit_contacts_received, EditProfileStates.waiting_contacts)

    # Обработчики добавления спота
    dp.callback_query.register(add_spot_start, F.data == "add_spot_start")
    dp.message.register(add_spot_name, AddSpotStates.waiting_name)
    dp.message.register(add_spot_description, AddSpotStates.waiting_description)
    dp.message.register(add_spot_photo, AddSpotStates.waiting_photo, F.photo)
    dp.message.register(add_spot_skip_photo, Command("skip"), AddSpotStates.waiting_photo)
    dp.message.register(add_spot_location, AddSpotStates.waiting_location, F.location)
    dp.message.register(add_spot_skip_location, Command("skip"), AddSpotStates.waiting_location)
    dp.callback_query.register(delete_custom_spot, F.data.startswith("spot_delete_"))

    dp.callback_query.register(spot_detail, F.data.startswith("spot_") & ~F.data.contains("join") & ~F.data.contains("leave") & ~F.data.contains("who") & ~F.data.contains("delete"))
    dp.callback_query.register(join_spot, F.data.startswith("spot_join_"))
    dp.callback_query.register(leave_spot, F.data.startswith("spot_leave_"))
    dp.callback_query.register(who_on_spot, F.data.startswith("spot_who_"))

    dp.callback_query.register(topic_create_start, F.data == "topic_create")
    dp.callback_query.register(topic_open, F.data.startswith("topic_") & ~F.data.contains("write") & ~F.data.contains("list"))
    dp.callback_query.register(topic_write_start, F.data.startswith("topic_write_"))
    dp.callback_query.register(topic_list, F.data == "topic_list")
    dp.message.register(topic_name_received, ForumStates.waiting_topic_name)
    dp.message.register(topic_message_received, ForumStates.waiting_topic_message)
    dp.message.register(reply_to_topic_message, Command("reply_topic"))

    dp.callback_query.register(market_list, F.data == "market_list")
    dp.callback_query.register(market_list_page, F.data.startswith("market_page_"))
    dp.callback_query.register(market_create_start, F.data == "market_create")
    dp.callback_query.register(market_view, F.data.startswith("market_view_"))
    dp.callback_query.register(market_delete, F.data.startswith("market_delete_"))
    dp.callback_query.register(market_main, F.data == "market_main")
    dp.message.register(market_text_received, MarketStates.waiting_listing_text)
    dp.message.register(market_photo_received, MarketStates.waiting_listing_photo, F.photo)
    dp.message.register(market_skip_photo, Command("skip"), MarketStates.waiting_listing_photo)

    dp.callback_query.register(edit_profile_callback, F.data == "edit_profile")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())