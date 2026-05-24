import asyncio
from datetime import datetime
from typing import Dict, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, VideoNote, Video
)
from aiogram.fsm.storage.memory import MemoryStorage

# ========== КОНФИГ ==========
BOT_TOKEN = "8808715816:AAExklLswlVG7eofArKz4woeB4kQtxZIPuc"   # замените!
ADMIN_IDS = [1896036065]                # замените на свой Telegram ID

# ========== ХРАНЕНИЕ ДАННЫХ (в памяти) ==========
users = {}          # user_id -> {nickname, stance, contacts, is_admin, city}

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

games = {}          # game_id -> {...}
forum_messages = []   # list of dict
market_messages = []  # list of dict

next_game_id = 1
next_forum_msg_id = 1
next_market_msg_id = 1

timer_tasks = {}      # (game_id, user_id) -> asyncio.Task

# ========== FSM СОСТОЯНИЯ ==========
class RegStates(StatesGroup):
    waiting_city = State()
    waiting_nickname = State()
    waiting_stance = State()
    waiting_contacts = State()

class GameStates(StatesGroup):
    waiting_for_trick_video = State()
    waiting_for_repeat_video = State()
    waiting_game_mode = State()

class ReplyStates(StatesGroup):
    waiting_reply_forum = State()
    waiting_reply_market = State()

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    buttons = [
        [KeyboardButton(text="🏙️ Выбрать город")],
        [KeyboardButton(text="🛹 Споты"), KeyboardButton(text="🔄 Game of Skate")],
        [KeyboardButton(text="🏪 Барахолка"), KeyboardButton(text="💬 Форум / Чат")],
        [KeyboardButton(text="👤 Моя анкета")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def spots_keyboard():
    kb = []
    for spot_id, spot in spots.items():
        kb.append([InlineKeyboardButton(text=spot["name"], callback_data=f"spot_{spot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def spot_actions_keyboard(spot_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я здесь катаюсь", callback_data=f"spot_join_{spot_id}")],
        [InlineKeyboardButton(text="❌ Закончил кататься", callback_data=f"spot_leave_{spot_id}")],
        [InlineKeyboardButton(text="👥 Кто на споте", callback_data=f"spot_who_{spot_id}")]
    ])

def game_mode_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Быстрая игра (5 мин на повтор)", callback_data="game_mode_fast")],
        [InlineKeyboardButton(text="🐢 Долгая игра (2 часа на повтор)", callback_data="game_mode_long")]
    ])

def game_lobby_keyboard(game_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Присоединиться", callback_data=f"game_join_{game_id}")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data=f"game_start_{game_id}")],
        [InlineKeyboardButton(text="🚪 Выйти из лобби", callback_data=f"game_leave_{game_id}")]
    ])

def game_active_keyboard(game_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎥 Загрузить трюк (мой ход)", callback_data=f"game_trick_{game_id}")]
    ])

def game_repeat_keyboard(game_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить трюк", callback_data=f"game_repeat_{game_id}")],
        [InlineKeyboardButton(text="💀 Сдаюсь (LOSE)", callback_data=f"game_lose_{game_id}")]
    ])

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user_nickname(user_id: int) -> str:
    return users.get(user_id, {}).get("nickname", f"User_{user_id}")

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
    current_idx = game["current_player_index"]
    new_idx = (current_idx + 1) % len(game["turn_order"])
    game["current_player_index"] = new_idx
    return game["turn_order"][new_idx]

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
    await bot.send_message(user_id, "⏰ Время вышло! Ты проиграл (LOSE).")
    await notify_game_participants(game_id, f"⏰ {get_user_nickname(user_id)} не успел повторить трюк и выбывает!", bot)
    if len(game["participants"]) == 1:
        winner = game["participants"][0]
        game["status"] = "finished"
        game["winner"] = winner
        await notify_game_participants(game_id, f"🏆 Игра окончена! Победитель: {get_user_nickname(winner)}. Все молодцы!", bot)
        del games[game_id]
    else:
        if game["turn_order"][game["current_player_index"]] == user_id:
            if game["current_player_index"] >= len(game["turn_order"]):
                game["current_player_index"] = 0
            else:
                if game["current_player_index"] > 0:
                    game["current_player_index"] -= 1

async def start_repeat_timer(game_id: int, user_id: int, bot: Bot):
    game = games.get(game_id)
    if not game:
        return
    timeout = game["time_limit_seconds"]
    try:
        await asyncio.sleep(timeout)
        if game_id in games and user_id in games[game_id]["participants"]:
            await auto_lose(game_id, user_id, bot)
    except asyncio.CancelledError:
        pass

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
async def start_command(message: Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in users:
        users[uid] = {"is_admin": uid in ADMIN_IDS}
        await message.answer("Привет! Давай создадим анкету. Сначала выбери город (пока только СПб):", reply_markup=spots_keyboard())
        await state.set_state(RegStates.waiting_city)
    else:
        await message.answer("Ты уже зарегистрирован. Вот главное меню:", reply_markup=main_keyboard())

async def city_chosen(callback: CallbackQuery, state: FSMContext):
    spot_id = callback.data.split("_")[1]   # не используется, просто подтверждение
    users[callback.from_user.id]["city"] = "spb"
    await callback.message.edit_text("Город сохранён: Санкт-Петербург. Теперь придумай никнейм (он будет виден всем):")
    await state.set_state(RegStates.waiting_nickname)
    await callback.answer()

async def nickname_received(message: Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("Никнейм должен быть от 2 до 20 символов. Попробуй ещё:")
        return
    users[message.from_user.id]["nickname"] = nickname
    await message.answer("Отлично! Теперь выбери любимую стойку (обычная / гуфи / не важно):")
    await state.set_state(RegStates.waiting_stance)

async def stance_received(message: Message, state: FSMContext):
    stance = message.text.strip()
    users[message.from_user.id]["stance"] = stance
    await message.answer("Можешь оставить контакты (Telegram, Instagram и т.д.) или пропустить командой /skip")
    await state.set_state(RegStates.waiting_contacts)

async def contacts_received(message: Message, state: FSMContext):
    users[message.from_user.id]["contacts"] = message.text
    await message.answer("Анкета готова! Ты в главном меню.", reply_markup=main_keyboard())
    await state.clear()

async def skip_contacts(message: Message, state: FSMContext):
    users[message.from_user.id]["contacts"] = "Не указаны"
    await message.answer("Анкета готова (контакты пропущены). Главное меню:", reply_markup=main_keyboard())
    await state.clear()

async def show_profile(message: Message):
    uid = message.from_user.id
    if uid not in users:
        await message.answer("Сначала используй /start")
        return
    u = users[uid]
    text = f"👤 Твоя анкета:\nНик: {u.get('nickname', '—')}\nГород: Санкт-Петербург\nСтойка: {u.get('stance', '—')}\nКонтакты: {u.get('contacts', '—')}"
    await message.answer(text, reply_markup=main_keyboard())

# ---------- СПОТЫ ----------
async def show_spots(message: Message):
    await message.answer("Выбери спот:", reply_markup=spots_keyboard())

async def spot_menu(callback: CallbackQuery):
    spot_id = callback.data.split("_")[1]
    await callback.message.edit_text(spots[spot_id]["name"], reply_markup=spot_actions_keyboard(spot_id))
    await callback.answer()

async def join_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    if uid not in users:
        await callback.answer("Сначала /start", show_alert=True)
        return
    if uid not in spots[spot_id]["active"]:
        spots[spot_id]["active"].append(uid)
    await callback.answer("Тебя отметили на споте!", show_alert=True)

async def leave_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    uid = callback.from_user.id
    if uid in spots[spot_id]["active"]:
        spots[spot_id]["active"].remove(uid)
    await callback.answer("Ты ушёл со спота", show_alert=True)

async def who_on_spot(callback: CallbackQuery):
    spot_id = callback.data.split("_")[2]
    active_ids = spots[spot_id]["active"]
    if not active_ids:
        text = "На споте никого нет."
    else:
        names = [get_user_nickname(uid) for uid in active_ids]
        text = "Сейчас катаются:\n" + "\n".join(names)
    await callback.message.answer(text)
    await callback.answer()

# ---------- ФОРУМ И БАРАХОЛКА ----------
async def show_forum(message: Message):
    await message.answer("📢 Форум: пиши сообщения, другие могут ответить.\nИспользуй /reply <id> <текст>")

async def show_market(message: Message):
    await message.answer("🛍️ Барахолка: продажа/обмен.\nИспользуй /reply_market <id> <текст>")

async def post_to_forum(message: Message):
    if message.text.startswith('/'):
        return
    uid = message.from_user.id
    if uid not in users:
        await message.answer("Сначала /start")
        return
    global next_forum_msg_id
    forum_messages.append({
        "msg_id": next_forum_msg_id,
        "user_id": uid,
        "nickname": get_user_nickname(uid),
        "text": message.text,
        "timestamp": datetime.now()
    })
    await message.answer(f"Сообщение #{next_forum_msg_id} опубликовано в форуме. Чтобы ответить, отправь /reply {next_forum_msg_id} текст")
    next_forum_msg_id += 1

async def post_to_market(message: Message):
    if message.text.startswith('/'):
        return
    uid = message.from_user.id
    if uid not in users:
        await message.answer("Сначала /start")
        return
    global next_market_msg_id
    market_messages.append({
        "msg_id": next_market_msg_id,
        "user_id": uid,
        "nickname": get_user_nickname(uid),
        "text": message.text,
        "timestamp": datetime.now()
    })
    await message.answer(f"Объявление #{next_market_msg_id} на барахолке. Ответить: /reply_market {next_market_msg_id} текст")
    next_market_msg_id += 1

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
            await message.answer(f"Ответ отправлен пользователю {msg['nickname']} на сообщение #{target_id}:\n{reply_text}")
            try:
                await bot.send_message(msg["user_id"], f"Ответ от {author} на твоё сообщение в форуме:\n{reply_text}")
            except:
                pass
            return
    await message.answer("Сообщение не найдено")

async def reply_to_market(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Используй: /reply_market <id объявления> <текст>")
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
            await message.answer(f"Ответ отправлен {msg['nickname']} на объявление #{target_id}:\n{reply_text}")
            try:
                await bot.send_message(msg["user_id"], f"Ответ от {author} на твоё объявление:\n{reply_text}")
            except:
                pass
            return
    await message.answer("Объявление не найдено")

# ---------- GAME OF SKATE ----------
async def game_menu(message: Message):
    active_games = [(gid, g) for gid, g in games.items() if g["status"] in ["waiting", "active"]]
    if not active_games:
        await message.answer("Нет активных игр. Нажми 'Создать игру'", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Создать игру", callback_data="game_create")]
        ]))
    else:
        kb = []
        for gid, g in active_games:
            mode = "⚡5m" if g.get("time_limit_seconds") == 300 else "🐢2h"
            status = "⏳ лобби" if g["status"] == "waiting" else "🔥 в процессе"
            kb.append([InlineKeyboardButton(text=f"Игра #{gid} ({len(g['participants'])} чел) {mode} {status}", callback_data=f"game_view_{gid}")])
        kb.append([InlineKeyboardButton(text="➕ Создать новую", callback_data="game_create")])
        await message.answer("Выбери игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

async def game_create(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in users:
        await callback.answer("Сначала /start", show_alert=True)
        return
    await callback.message.edit_text("Выбери режим игры:", reply_markup=game_mode_keyboard())
    await state.set_state(GameStates.waiting_game_mode)
    await callback.answer()

async def game_mode_chosen(callback: CallbackQuery, state: FSMContext):
    mode = callback.data
    if mode == "game_mode_fast":
        time_limit = 300
        mode_name = "Быстрая (5 мин на повтор)"
    else:
        time_limit = 7200
        mode_name = "Долгая (2 часа на повтор)"
    global next_game_id
    uid = callback.from_user.id
    gid = next_game_id
    games[gid] = {
        "creator_id": uid,
        "status": "waiting",
        "participants": [uid],
        "current_player_index": 0,
        "turn_order": [uid],
        "last_trick_file_id": None,
        "winner": None,
        "time_limit_seconds": time_limit,
        "mode_name": mode_name
    }
    next_game_id += 1
    await callback.message.edit_text(f"Игра #{gid} создана в режиме {mode_name}!\nОжидаем участников.", reply_markup=game_lobby_keyboard(gid))
    await state.clear()
    await callback.answer()

async def game_join(callback: CallbackQuery):
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    if not game or game["status"] != "waiting":
        await callback.answer("Игра уже началась или не существует", show_alert=True)
        return
    if uid in game["participants"]:
        await callback.answer("Ты уже в игре", show_alert=True)
        return
    game["participants"].append(uid)
    game["turn_order"].append(uid)
    await callback.message.edit_text(f"Игра #{gid}\nУчастники: {len(game['participants'])}", reply_markup=game_lobby_keyboard(gid))
    await callback.answer("Ты присоединился!")

async def game_leave(callback: CallbackQuery):
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    if not game:
        await callback.answer("Игра не найдена")
        return
    if uid not in game["participants"]:
        await callback.answer("Ты не в игре")
        return
    if game["status"] == "active":
        await callback.answer("Нельзя выйти из активной игры. Используй LOSE")
        return
    game["participants"].remove(uid)
    game["turn_order"].remove(uid)
    if len(game["participants"]) == 0:
        del games[gid]
        await callback.message.edit_text("Игра удалена (нет участников)")
    else:
        if uid == game["creator_id"] and len(game["participants"]) > 0:
            game["creator_id"] = game["participants"][0]
        await callback.message.edit_text(f"Игра #{gid}. Участников: {len(game['participants'])}", reply_markup=game_lobby_keyboard(gid))
    await callback.answer("Ты вышел из лобби")

async def game_start(callback: CallbackQuery):
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    if not game or game["status"] != "waiting":
        await callback.answer("Игра недоступна")
        return
    if uid != game["creator_id"]:
        await callback.answer("Только создатель может начать игру")
        return
    if len(game["participants"]) < 2:
        await callback.answer("Нужно минимум 2 игрока")
        return
    game["status"] = "active"
    game["current_player_index"] = 0
    current_player = game["turn_order"][0]
    await callback.message.edit_text(f"Игра #{gid} началась!\nПервый ход: {get_user_nickname(current_player)}\nПравила: по очереди загружайте кружок/видео трюка. Остальные должны повторить. Если не можешь повторить — нажми LOSE.\nРежим: {game['mode_name']}")
    await bot.send_message(current_player, "🔥 YOUR TURN! Загрузи кружок или видео с трюком.", reply_markup=game_active_keyboard(gid))
    await callback.answer()

async def game_upload_trick(callback: CallbackQuery, state: FSMContext):
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    if not game or game["status"] != "active":
        await callback.answer("Игра не активна")
        return
    if game["turn_order"][game["current_player_index"]] != uid:
        await callback.answer("Сейчас не твой ход")
        return
    await state.update_data(game_id=gid)
    await callback.message.answer("Отправь кружок (video note) или видео с трюком. Он будет отправлен всем участникам для повтора.")
    await state.set_state(GameStates.waiting_for_trick_video)
    await callback.answer()

async def trick_video_received(message: Message, state: FSMContext):
    data = await state.get_data()
    gid = data["game_id"]
    game = games.get(gid)
    if not game or game["status"] != "active":
        await message.answer("Игра уже не активна")
        await state.clear()
        return
    uid = message.from_user.id
    if game["turn_order"][game["current_player_index"]] != uid:
        await message.answer("Сейчас не твой ход")
        await state.clear()
        return
    if message.video_note:
        file_id = message.video_note.file_id
    elif message.video:
        file_id = message.video.file_id
    else:
        await message.answer("Нужно отправить кружок или обычное видео. Попробуй ещё раз.")
        return
    game["last_trick_file_id"] = file_id
    for pid in game["participants"]:
        if pid != uid:
            try:
                if message.video_note:
                    await bot.send_video_note(pid, file_id)
                else:
                    await bot.send_video(pid, file_id)
                await bot.send_message(pid, f"{get_user_nickname(uid)} заказал трюк! YOUR TURN TO REPEAT.\nЗагрузи свой трюк или нажми LOSE.\nУ тебя {game['time_limit_seconds']//60} минут.", reply_markup=game_repeat_keyboard(gid))
                task = asyncio.create_task(start_repeat_timer(gid, pid, bot))
                timer_tasks[(gid, pid)] = task
            except:
                pass
    next_player = advance_turn(gid)
    await message.answer(f"Трюк отправлен! Теперь очередь {get_user_nickname(next_player)} заказывать следующий трюк (после того как все повторят или проиграют).")
    await state.clear()

async def game_repeat_trick(callback: CallbackQuery, state: FSMContext):
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    if not game or game["status"] != "active":
        await callback.answer("Игра не активна")
        return
    if uid == game["turn_order"][game["current_player_index"]]:
        await callback.answer("Ты заказал трюк, теперь очередь других")
        return
    cancel_timer(gid, uid)
    await state.update_data(game_id=gid)
    await callback.message.answer(f"Загрузи кружок или видео с ПОВТОРОМ этого трюка.\nУ тебя есть {game['time_limit_seconds']//60} минут.")
    await state.set_state(GameStates.waiting_for_repeat_video)
    await callback.answer()

async def repeat_video_received(message: Message, state: FSMContext):
    data = await state.get_data()
    gid = data["game_id"]
    game = games.get(gid)
    if not game or game["status"] != "active":
        await message.answer("Игра не активна")
        await state.clear()
        return
    uid = message.from_user.id
    cancel_timer(gid, uid)
    await message.answer("Твой повтор принят. Ожидай следующего хода.")
    await state.clear()

async def game_lose(callback: CallbackQuery):
    gid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    game = games.get(gid)
    if not game or game["status"] != "active":
        await callback.answer("Игра не активна")
        return
    if uid not in game["participants"]:
        return
    cancel_timer(gid, uid)
    game["participants"].remove(uid)
    game["turn_order"].remove(uid)
    await callback.message.answer(f"{get_user_nickname(uid)} LOSE! Выбывает.")
    if len(game["participants"]) == 1:
        winner = game["participants"][0]
        game["status"] = "finished"
        game["winner"] = winner
        await notify_game_participants(gid, f"🏆 Игра окончена! Победитель: {get_user_nickname(winner)}. Все молодцы!", callback.bot)
        del games[gid]
    else:
        if game["turn_order"][game["current_player_index"]] == uid:
            if game["current_player_index"] >= len(game["turn_order"]):
                game["current_player_index"] = 0
            else:
                if game["current_player_index"] > 0:
                    game["current_player_index"] -= 1
    await callback.answer()

# ---------- АДМИН: БРОДКАСТ ----------
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

# ========== РЕГИСТРАЦИЯ И ЗАПУСК ==========
async def main():
    global bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(start_command, Command("start"))
    dp.message.register(skip_contacts, Command("skip"))
    dp.message.register(show_profile, F.text == "👤 Моя анкета")
    dp.message.register(show_spots, F.text == "🛹 Споты")
    dp.message.register(game_menu, F.text == "🔄 Game of Skate")
    dp.message.register(show_forum, F.text == "💬 Форум / Чат")
    dp.message.register(show_market, F.text == "🏪 Барахолка")
    dp.message.register(post_to_forum, F.text & ~F.text.startswith('/') & (F.chat.type == "private"))
    dp.message.register(post_to_market, F.text & ~F.text.startswith('/') & (F.chat.type == "private"))
    dp.message.register(reply_to_forum, Command("reply"))
    dp.message.register(reply_to_market, Command("reply_market"))
    dp.message.register(broadcast, Command("broadcast"))

    dp.message.register(nickname_received, RegStates.waiting_nickname)
    dp.message.register(stance_received, RegStates.waiting_stance)
    dp.message.register(contacts_received, RegStates.waiting_contacts)
    dp.callback_query.register(city_chosen, F.data.startswith("spot_"), RegStates.waiting_city)

    dp.callback_query.register(spot_menu, F.data.startswith("spot_") & ~F.data.startswith("spot_join_") & ~F.data.startswith("spot_leave_") & ~F.data.startswith("spot_who_"))
    dp.callback_query.register(join_spot, F.data.startswith("spot_join_"))
    dp.callback_query.register(leave_spot, F.data.startswith("spot_leave_"))
    dp.callback_query.register(who_on_spot, F.data.startswith("spot_who_"))

    dp.callback_query.register(game_mode_chosen, F.data.in_({"game_mode_fast", "game_mode_long"}), GameStates.waiting_game_mode)
    dp.callback_query.register(game_create, F.data == "game_create")
    dp.callback_query.register(game_join, F.data.startswith("game_join_"))
    dp.callback_query.register(game_leave, F.data.startswith("game_leave_"))
    dp.callback_query.register(game_start, F.data.startswith("game_start_"))
    dp.callback_query.register(game_upload_trick, F.data.startswith("game_trick_"))
    dp.callback_query.register(game_repeat_trick, F.data.startswith("game_repeat_"))
    dp.callback_query.register(game_lose, F.data.startswith("game_lose_"))

    dp.message.register(trick_video_received, GameStates.waiting_for_trick_video, F.video | F.video_note)
    dp.message.register(repeat_video_received, GameStates.waiting_for_repeat_video, F.video | F.video_note)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())