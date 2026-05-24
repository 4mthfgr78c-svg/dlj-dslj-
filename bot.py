import asyncio
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, Video, VideoNote
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
games = {}
forum_topics = {}
market_listings = {}

next_game_id = 1
next_topic_id = 1
next_topic_msg_id = 1
next_listing_id = 1

# ========== FSM ==========
class ProfileStates(StatesGroup):
    waiting_nickname = State()
    waiting_stance = State()
    waiting_contacts = State()

class GameStates(StatesGroup):
    waiting_trick = State()
    waiting_repeat = State()

class ForumStates(StatesGroup):
    waiting_topic_name = State()
    waiting_topic_message = State()

class MarketStates(StatesGroup):
    waiting_listing_text = State()
    waiting_listing_photo = State()

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    buttons = [
        [KeyboardButton(text="🛹 Споты"), KeyboardButton(text="🔄 Game of Skate")],
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

def games_list_keyboard():
    active_games = [(gid, g) for gid, g in games.items() if g["status"] == "active"]
    kb = []
    for gid, g in active_games:
        kb.append([InlineKeyboardButton(text=f"🎮 Игра #{gid} ({len(g['participants'])} чел)", callback_data=f"game_join_{gid}")])
    kb.append([InlineKeyboardButton(text="➕ Создать новую игру", callback_data="game_create")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def game_control_keyboard(game_id: int, user_id: int):
    game = games.get(game_id)
    if not game:
        return None
    
    kb = []
    if game["turn_order"] and game["turn_order"][game["current_turn"]] == user_id:
        kb.append([InlineKeyboardButton(text="🎥 Заказать трюк", callback_data=f"game_trick_{game_id}")])
    elif user_id in game.get("waiting_repeat", []):
        kb.append([InlineKeyboardButton(text="🔄 Повторить трюк", callback_data=f"game_repeat_{game_id}")])
    
    kb.append([InlineKeyboardButton(text="💀 LOSE", callback_data=f"game_lose_{game_id}")])
    kb.append([InlineKeyboardButton(text="📋 Список игр", callback_data="game_list")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ========== ВСПОМОГАТЕЛЬНЫЕ ==========
def get_user_nickname(user_id: int) -> str:
    u = users.get(user_id, {})
    return u.get("nickname", f"User_{user_id}")

def ensure_user(user_id: int):
    if user_id not in users:
        users[user_id] = {"nickname": None, "stance": None, "contacts": None, "is_admin": user_id in ADMIN_IDS}

async def notify_game_participants(game_id: int, text: str, bot: Bot, reply_markup=None):
    game = games.get(game_id)
    if not game:
        return
    for pid in game["participants"]:
        try:
            await bot.send_message(pid, text, reply_markup=reply_markup)
        except:
            pass

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
async def start_command(message: Message):
    ensure_user(message.from_user.id)
    await message.answer(
        "🎮 *СКЕЙТЕР-БОТ*\n\n"
        "🛹 *Game of Skate:*\n"
        "• Создай игру или присоединись\n"
        "• По очереди заказывайте трюки\n"
        "• Остальные повторяют\n"
        "• Кто не повторил — выбывает\n"
        "• Побеждает последний!\n\n"
        "📌 *Другие разделы:* Споты, Барахолка, Форум\n\n"
        "Заполни анкету: /profile",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
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

# ---------- GAME OF SKATE (ПРОСТАЯ ЛОГИКА) ----------
async def game_menu(message: Message):
    """Главное меню игр"""
    await message.answer("🎮 Выбери действие:", reply_markup=games_list_keyboard())

async def game_create(callback: CallbackQuery):
    """Создать новую игру"""
    global next_game_id
    uid = callback.from_user.id
    ensure_user(uid)
    
    gid = next_game_id
    games[gid] = {
        "creator_id": uid,
        "status": "active",
        "participants": [uid],
        "turn_order": [uid],
        "current_turn": 0,
        "waiting_repeat": [],
        "last_trick_file": None,
        "last_trick_author": None
    }
    next_game_id += 1
    
    await callback.message.edit_text(
        f"✅ Игра #{gid} создана!\n\n"
        f"Ты первый участник. Жди других игроков.\n"
        f"Когда кто-то присоединится, сможешь заказать трюк.",
        reply_markup=game_control_keyboard(gid, uid)
    )
    await callback.answer()

async def game_join(callback: CallbackQuery):
    """Присоединиться к игре"""
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    
    if not game:
        await callback.answer("❌ Игра не найдена", show_alert=True)
        return
    
    if uid in game["participants"]:
        await callback.answer("❌ Ты уже в игре", show_alert=True)
        return
    
    game["participants"].append(uid)
    game["turn_order"].append(uid)
    
    await callback.answer(f"✅ Ты присоединился к игре #{gid}!")
    await callback.message.edit_text(
        f"🎮 Игра #{gid}\nУчастники: {', '.join([get_user_nickname(p) for p in game['participants']])}\n\n"
        f"Первый ход: {get_user_nickname(game['turn_order'][0])}",
        reply_markup=game_control_keyboard(gid, uid)
    )
    
    await notify_game_participants(gid, f"🎉 {get_user_nickname(uid)} присоединился к игре!", callback.bot)

async def game_trick(callback: CallbackQuery, state: FSMContext):
    """Заказать трюк"""
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    
    if not game:
        await callback.answer("❌ Игра не найдена")
        return
    
    if game["turn_order"][game["current_turn"]] != uid:
        await callback.answer("❌ Сейчас не твой ход!")
        return
    
    await state.update_data(game_id=gid)
    await callback.message.answer("📹 Отправь видео или кружок с трюком!")
    await state.set_state(GameStates.waiting_trick)
    await callback.answer()

async def trick_received(message: Message, state: FSMContext):
    """Получен трюк"""
    data = await state.get_data()
    gid = data["game_id"]
    game = games.get(gid)
    
    if not game or game["status"] != "active":
        await message.answer("❌ Игра не активна")
        await state.clear()
        return
    
    uid = message.from_user.id
    if game["turn_order"][game["current_turn"]] != uid:
        await message.answer("❌ Сейчас не твой ход")
        await state.clear()
        return
    
    file_id = None
    if message.video_note:
        file_id = message.video_note.file_id
    elif message.video:
        file_id = message.video.file_id
    
    if not file_id:
        await message.answer("❌ Нужно отправить видео или кружок!")
        return
    
    game["last_trick_file"] = file_id
    game["last_trick_author"] = uid
    game["waiting_repeat"] = [p for p in game["participants"] if p != uid]
    
    for pid in game["waiting_repeat"]:
        try:
            if message.video_note:
                await bot.send_video_note(pid, file_id)
            else:
                await bot.send_video(pid, file_id)
            await bot.send_message(pid, f"🔥 {get_user_nickname(uid)} заказал трюк! Твоя очередь повторять.", reply_markup=game_control_keyboard(gid, pid))
        except:
            pass
    
    await message.answer(f"✅ Трюк отправлен! Ожидаем пока все повторят.")
    await state.clear()

async def game_repeat(callback: CallbackQuery, state: FSMContext):
    """Повторить трюк"""
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    
    if not game:
        await callback.answer("❌ Игра не найдена")
        return
    
    if uid not in game.get("waiting_repeat", []):
        await callback.answer("❌ Ты уже повторил или не должен повторять")
        return
    
    await state.update_data(game_id=gid)
    await callback.message.answer("📹 Отправь видео с повтором трюка!")
    await state.set_state(GameStates.waiting_repeat)
    await callback.answer()

async def repeat_received(message: Message, state: FSMContext):
    """Получен повтор"""
    data = await state.get_data()
    gid = data["game_id"]
    game = games.get(gid)
    
    if not game or game["status"] != "active":
        await message.answer("❌ Игра не активна")
        await state.clear()
        return
    
    uid = message.from_user.id
    if uid not in game.get("waiting_repeat", []):
        await message.answer("❌ Ты уже повторил или не должен повторять")
        await state.clear()
        return
    
    game["waiting_repeat"].remove(uid)
    await message.answer("✅ Твой повтор принят!")
    
    if not game["waiting_repeat"]:
        game["current_turn"] = (game["current_turn"] + 1) % len(game["turn_order"])
        next_player = game["turn_order"][game["current_turn"]]
        
        await notify_game_participants(gid, f"🔄 Все повторили! Теперь {get_user_nickname(next_player)} заказывает трюк.", message.bot)
        await message.bot.send_message(next_player, "🔥 ТВОЙ ХОД! Закажи трюк.", reply_markup=game_control_keyboard(gid, next_player))
    
    await state.clear()

async def game_lose(callback: CallbackQuery):
    """Проиграть"""
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    
    if not game or game["status"] != "active":
        await callback.answer("❌ Игра не активна")
        return
    
    if uid not in game["participants"]:
        await callback.answer("❌ Ты не в игре")
        return
    
    if uid in game.get("waiting_repeat", []):
        game["waiting_repeat"].remove(uid)
    
    if uid in game["turn_order"]:
        idx = game["turn_order"].index(uid)
        game["turn_order"].remove(uid)
        if idx <= game["current_turn"] and game["turn_order"]:
            game["current_turn"] = (game["current_turn"] - 1) % len(game["turn_order"])
    
    game["participants"].remove(uid)
    
    await callback.answer(f"💀 Ты проиграл! LOSE!")
    await notify_game_participants(gid, f"💀 {get_user_nickname(uid)} проиграл и выбывает!", callback.bot)
    
    if len(game["participants"]) == 1:
        winner = game["participants"][0]
        await notify_game_participants(gid, f"🏆 ПОБЕДИТЕЛЬ: {get_user_nickname(winner)}! 🎉", callback.bot)
        del games[gid]
        await callback.message.edit_text("Игра завершена!")
    elif not game.get("waiting_repeat") and game["turn_order"]:
        next_player = game["turn_order"][game["current_turn"]]
        await callback.bot.send_message(next_player, "🔥 ТВОЙ ХОД! Закажи трюк.", reply_markup=game_control_keyboard(gid, next_player))

async def game_list(callback: CallbackQuery):
    """Показать список игр"""
    await callback.message.edit_text("🎮 Выбери игру:", reply_markup=games_list_keyboard())
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
    dp.message.register(skip_contacts, Command("skip"))
    dp.message.register(broadcast, Command("broadcast"))

    dp.message.register(show_spots_list, F.text == "🛹 Споты")
    dp.message.register(game_menu, F.text == "🔄 Game of Skate")
    dp.message.register(forum_menu, F.text == "💬 Форум / Чат")
    dp.message.register(market_menu, F.text == "🏪 Барахолка")

    dp.message.register(nickname_received, ProfileStates.waiting_nickname)
    dp.message.register(stance_received, ProfileStates.waiting_stance)
    dp.message.register(contacts_received, ProfileStates.waiting_contacts)

    dp.callback_query.register(spot_detail, F.data.startswith("spot_") & ~F.data.contains("join") & ~F.data.contains("leave") & ~F.data.contains("who"))
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

    dp.callback_query.register(game_create, F.data == "game_create")
    dp.callback_query.register(game_join, F.data.startswith("game_join_"))
    dp.callback_query.register(game_trick, F.data.startswith("game_trick_"))
    dp.callback_query.register(game_repeat, F.data.startswith("game_repeat_"))
    dp.callback_query.register(game_lose, F.data.startswith("game_lose_"))
    dp.callback_query.register(game_list, F.data == "game_list")

    dp.message.register(trick_received, GameStates.waiting_trick, F.video | F.video_note)
    dp.message.register(repeat_received, GameStates.waiting_repeat, F.video | F.video_note)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())