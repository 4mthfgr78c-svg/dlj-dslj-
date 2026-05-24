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
users = {}          # user_id -> {nickname, stance, contacts, is_admin}

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
forum_messages = []
market_messages = []

next_game_id = 1
next_forum_msg_id = 1
next_market_msg_id = 1
timer_tasks = {}

# ========== FSM ==========
class ProfileStates(StatesGroup):
    waiting_nickname = State()
    waiting_stance = State()
    waiting_contacts = State()

class GameStates(StatesGroup):
    waiting_for_trick_video = State()
    waiting_for_repeat_video = State()
    waiting_game_mode = State()

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    buttons = [
        [KeyboardButton(text="🛹 Споты"), KeyboardButton(text="🔄 Game of Skate")],
        [KeyboardButton(text="🏪 Барахолка"), KeyboardButton(text="💬 Форум / Чат")],
        [KeyboardButton(text="👤 Моя анкета")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def spots_list_keyboard():
    """Клавиатура со списком всех спотов"""
    kb = []
    for spot_id, spot in spots.items():
        # Если есть активные пользователи — ставим огонёк
        indicator = "🔥 " if spot["active"] else ""
        kb.append([InlineKeyboardButton(text=f"{indicator}{spot['name']}", callback_data=f"spot_{spot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def spot_detail_keyboard(spot_id: str):
    """Клавиатура для конкретного спота: отметить/уехать + кто тут"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я здесь", callback_data=f"spot_join_{spot_id}")],
        [InlineKeyboardButton(text="❌ Уехал", callback_data=f"spot_leave_{spot_id}")],
        [InlineKeyboardButton(text="👥 Кто на споте", callback_data=f"spot_who_{spot_id}")]
    ])

def game_mode_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Быстрая игра (5 мин)", callback_data="game_mode_fast")],
        [InlineKeyboardButton(text="🐢 Долгая игра (2 часа)", callback_data="game_mode_long")]
    ])

def game_lobby_keyboard(game_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Присоединиться", callback_data=f"game_join_{game_id}")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data=f"game_start_{game_id}")],
        [InlineKeyboardButton(text="🚪 Выйти из лобби", callback_data=f"game_leave_{game_id}")]
    ])

def game_active_keyboard(game_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎥 Загрузить трюк", callback_data=f"game_trick_{game_id}")]
    ])

def game_repeat_keyboard(game_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить трюк", callback_data=f"game_repeat_{game_id}")],
        [InlineKeyboardButton(text="💀 LOSE", callback_data=f"game_lose_{game_id}")]
    ])

# ========== ВСПОМОГАТЕЛЬНЫЕ ==========
def get_user_nickname(user_id: int) -> str:
    u = users.get(user_id, {})
    return u.get("nickname", f"User_{user_id}")

def ensure_user(user_id: int):
    """Создаём пользователя, если его нет (без регистрации)"""
    if user_id not in users:
        users[user_id] = {
            "nickname": None,
            "stance": None,
            "contacts": None,
            "is_admin": user_id in ADMIN_IDS
        }

async def notify_game_participants(game_id: int, text: str, bot: Bot, reply_markup=None):
    game = games.get(game_id)
    if not game:
        return
    for pid in game["participants"]:
        try:
            await bot.send_message(pid, text, reply_markup=reply_markup)
        except:
            pass

def advance_turn(game_id: int):
    game = games[game_id]
    game["current_player_index"] = (game["current_player_index"] + 1) % len(game["turn_order"])
    return game["turn_order"][game["current_player_index"]]

def cancel_timer(game_id: int, user_id: int):
    key = (game_id, user_id)
    if key in timer_tasks:
        timer_tasks[key].cancel()
        del timer_tasks[key]

async def auto_lose(game_id: int, user_id: int, bot: Bot):
    game = games.get(game_id)
    if not game or user_id not in game["participants"]:
        return
    game["participants"].remove(user_id)
    game["turn_order"].remove(user_id)
    await bot.send_message(user_id, "⏰ Время вышло! LOSE.")
    await notify_game_participants(game_id, f"⏰ {get_user_nickname(user_id)} не успел повторить и выбывает!", bot)
    if len(game["participants"]) == 1:
        winner = game["participants"][0]
        await notify_game_participants(game_id, f"🏆 Победитель: {get_user_nickname(winner)}!", bot)
        del games[game_id]
    else:
        if game["turn_order"][game["current_player_index"]] == user_id:
            if game["current_player_index"] >= len(game["turn_order"]):
                game["current_player_index"] = 0
            elif game["current_player_index"] > 0:
                game["current_player_index"] -= 1

async def start_repeat_timer(game_id: int, user_id: int, bot: Bot):
    game = games.get(game_id)
    if not game:
        return
    try:
        await asyncio.sleep(game["time_limit_seconds"])
        if game_id in games and user_id in games[game_id]["participants"]:
            await auto_lose(game_id, user_id, bot)
    except asyncio.CancelledError:
        pass

# ========== ОБРАБОТЧИКИ ==========
async def start_command(message: Message):
    ensure_user(message.from_user.id)
    await message.answer(
        "🛹 Привет, скейтер!\n\n"
        "Это бот для скейтеров Санкт-Петербурга.\n"
        "Здесь можно:\n"
        "• Отмечаться на спотах\n"
        "• Играть в Game of Skate\n"
        "• Общаться на форуме\n"
        "• Покупать/продавать на барахолке\n\n"
        "Заполни анкету, чтобы другие знали, как тебя зовут: /profile",
        reply_markup=main_keyboard()
    )

async def profile_command(message: Message, state: FSMContext):
    uid = message.from_user.id
    ensure_user(uid)
    if users[uid].get("nickname"):
        u = users[uid]
        text = f"👤 Твоя анкета:\nНик: {u.get('nickname', '—')}\nСтойка: {u.get('stance', '—')}\nКонтакты: {u.get('contacts', '—')}"
        await message.answer(text, reply_markup=main_keyboard())
    else:
        await message.answer("Давай заполним анкету! Придумай никнейм (он будет виден всем):")
        await state.set_state(ProfileStates.waiting_nickname)

async def nickname_received(message: Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("Никнейм должен быть от 2 до 20 символов. Попробуй ещё:")
        return
    users[message.from_user.id]["nickname"] = nickname
    await message.answer("Отлично! Теперь выбери любимую стойку (обычная / гуфи / не важно):")
    await state.set_state(ProfileStates.waiting_stance)

async def stance_received(message: Message, state: FSMContext):
    users[message.from_user.id]["stance"] = message.text.strip()
    await message.answer("Можешь оставить контакты (Telegram, Instagram) или пропустить командой /skip")
    await state.set_state(ProfileStates.waiting_contacts)

async def contacts_received(message: Message, state: FSMContext):
    users[message.from_user.id]["contacts"] = message.text.strip()
    await message.answer("Анкета готова!", reply_markup=main_keyboard())
    await state.clear()

async def skip_contacts(message: Message, state: FSMContext):
    users[message.from_user.id]["contacts"] = "Не указаны"
    await message.answer("Анкета готова (контакты пропущены).", reply_markup=main_keyboard())
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
    await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id), parse_mode="Markdown")
    await callback.answer()

async def join_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    ensure_user(uid)
    if uid not in spots[spot_id]["active"]:
        spots[spot_id]["active"].append(uid)
    await callback.answer("✅ Ты отметился на споте!", show_alert=True)
    # Обновляем сообщение, чтобы обновить статус
    spot = spots[spot_id]
    active_count = len(spot["active"])
    status_text = "🟢 Активен" if active_count > 0 else "⚪ Нет активных"
    text = f"📍 *{spot['name']}*\n{status_text} (катаются: {active_count})"
    await callback.message.edit_text(text, reply_markup=spot_detail_keyboard(spot_id), parse_mode="Markdown")

async def leave_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    if uid in spots[spot_id]["active"]:
        spots[spot_id]["active"].remove(uid)
    await callback.answer("❌ Ты уехал со спота", show_alert=True)
    spot = spots[spot_id]
    active_count = len(spot["active"])
    status_text = "🟢 Активен" if active_count > 0 else "⚪ Нет активных"
    text = f"📍 *{spot['name']}*\n{status_text} (катаются: {active_count})"
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
async def show_forum(message: Message):
    await message.answer("📢 Форум: пиши сообщения. Чтобы ответить: /reply <id> <текст>")

async def post_to_forum(message: Message):
    if message.text.startswith('/'):
        return
    uid = message.from_user.id
    ensure_user(uid)
    global next_forum_msg_id
    forum_messages.append({
        "msg_id": next_forum_msg_id,
        "user_id": uid,
        "nickname": get_user_nickname(uid),
        "text": message.text,
        "timestamp": datetime.now()
    })
    await message.answer(f"Сообщение #{next_forum_msg_id} опубликовано в форуме.\nОтветить: /reply {next_forum_msg_id} <текст>")
    next_forum_msg_id += 1

async def reply_to_forum(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Используй: /reply <id сообщения> <твой ответ>")
        return
    try:
        target_id = int(parts[1])
        reply_text = parts[2]
    except:
        await message.answer("Неверный формат")
        return
    for msg in forum_messages:
        if msg["msg_id"] == target_id:
            author = get_user_nickname(message.from_user.id)
            await message.answer(f"✅ Ответ отправлен {msg['nickname']} на сообщение #{target_id}")
            try:
                await bot.send_message(msg["user_id"], f"📩 Ответ от {author}:\n{reply_text}")
            except:
                pass
            return
    await message.answer("Сообщение не найдено")

# ---------- БАРАХОЛКА ----------
async def show_market(message: Message):
    await message.answer("🛍️ Барахолка: продажа/обмен. Чтобы ответить: /reply_market <id> <текст>")

async def post_to_market(message: Message):
    if message.text.startswith('/'):
        return
    uid = message.from_user.id
    ensure_user(uid)
    global next_market_msg_id
    market_messages.append({
        "msg_id": next_market_msg_id,
        "user_id": uid,
        "nickname": get_user_nickname(uid),
        "text": message.text,
        "timestamp": datetime.now()
    })
    await message.answer(f"Объявление #{next_market_msg_id} на барахолке.\nОтветить: /reply_market {next_market_msg_id} <текст>")
    next_market_msg_id += 1

async def reply_to_market(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Используй: /reply_market <id объявления> <твой ответ>")
        return
    try:
        target_id = int(parts[1])
        reply_text = parts[2]
    except:
        await message.answer("Неверный формат")
        return
    for msg in market_messages:
        if msg["msg_id"] == target_id:
            author = get_user_nickname(message.from_user.id)
            await message.answer(f"✅ Ответ отправлен {msg['nickname']} на объявление #{target_id}")
            try:
                await bot.send_message(msg["user_id"], f"📩 Ответ от {author} на твоё объявление:\n{reply_text}")
            except:
                pass
            return
    await message.answer("Объявление не найдено")

# ---------- GAME OF SKATE (код остаётся таким же, как в прошлой версии) ----------
# ... (здесь весь код игры из предыдущей версии, он не меняется)

# Для краткости, вставь сюда весь код игры из предыдущего сообщения (от async def game_menu до async def game_lose)

# ---------- АДМИН ----------
async def broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет прав")
        return
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("Напиши /broadcast <текст>")
        return
    count = 0
    for uid in users.keys():
        try:
            await bot.send_message(uid, f"📢 АДМИН: {text}")
            count += 1
        except:
            pass
    await message.answer(f"Рассылка отправлена {count} пользователям")

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
    dp.message.register(show_forum, F.text == "💬 Форум / Чат")
    dp.message.register(show_market, F.text == "🏪 Барахолка")
    dp.message.register(game_menu, F.text == "🔄 Game of Skate")  # нужно добавить функцию game_menu

    dp.message.register(post_to_forum, F.text & ~F.text.startswith('/'))
    dp.message.register(post_to_market, F.text & ~F.text.startswith('/'))
    dp.message.register(reply_to_forum, Command("reply"))
    dp.message.register(reply_to_market, Command("reply_market"))

    dp.message.register(nickname_received, ProfileStates.waiting_nickname)
    dp.message.register(stance_received, ProfileStates.waiting_stance)
    dp.message.register(contacts_received, ProfileStates.waiting_contacts)

    dp.callback_query.register(spot_detail, F.data.startswith("spot_") & ~F.data.contains("join") & ~F.data.contains("leave") & ~F.data.contains("who"))
    dp.callback_query.register(join_spot, F.data.startswith("spot_join_"))
    dp.callback_query.register(leave_spot, F.data.startswith("spot_leave_"))
    dp.callback_query.register(who_on_spot, F.data.startswith("spot_who_"))

    # Регистрация игровых обработчиков (из предыдущей версии)
    # ...

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())