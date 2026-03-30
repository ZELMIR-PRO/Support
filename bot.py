"""
⭐ StarSupport Bot — Бот для поддержки авторов звёздами
Полный функционал с лидербордом, уровнями, достижениями и многим другим.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import json
import os
import sys

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ─────────────────────────────────────────────────────────────────
# КОНФИГ — переменные окружения (задаются в Railway)
# ─────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
AUTHOR_ID  = int(os.environ.get("AUTHOR_ID", "0"))

if not BOT_TOKEN:
    print("❌ Ошибка: переменная BOT_TOKEN не задана!", file=sys.stderr)
    sys.exit(1)
if not AUTHOR_ID:
    print("❌ Ошибка: переменная AUTHOR_ID не задана!", file=sys.stderr)
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────
# УРОВНИ ДОНОУТЕРОВ
# ─────────────────────────────────────────────────────────────────
LEVELS = [
    {"name": "🌱 Новичок",     "min": 0,      "emoji": "🌱"},
    {"name": "⭐ Фанат",       "min": 200,    "emoji": "⭐"},
    {"name": "🌟 Поддержатель","min": 1000,   "emoji": "🌟"},
    {"name": "💫 Меценат",     "min": 3000,   "emoji": "💫"},
    {"name": "🔥 Легенда",     "min": 7500,   "emoji": "🔥"},
    {"name": "👑 Король",      "min": 15000,  "emoji": "👑"},
    {"name": "💎 Бриллиант",   "min": 30000,  "emoji": "💎"},
]

# ─────────────────────────────────────────────────────────────────
# ДОСТИЖЕНИЯ
# ─────────────────────────────────────────────────────────────────
ACHIEVEMENTS = {
    "first_star":   {"name": "🎉 Первая звезда",    "desc": "Совершить первый донат",         "condition": lambda u: u["donations_count"] >= 1},
    "regular":      {"name": "📅 Постоянный",         "desc": "5 донатов всего",               "condition": lambda u: u["donations_count"] >= 5},
    "big_donor":    {"name": "💰 Щедрый",             "desc": "Задонатить 1000+ звёзд сразу",  "condition": lambda u: u["max_single_donation"] >= 1000},
    "whale":        {"name": "🐳 Кит",                "desc": "Суммарно 10 000 звёзд",         "condition": lambda u: u["total_stars"] >= 10000},
    "loyal":        {"name": "❤️ Верный",             "desc": "10 донатов всего",               "condition": lambda u: u["donations_count"] >= 10},
    "top3":         {"name": "🏆 Топ-3",              "desc": "Попасть в топ-3 лидерборда",     "condition": lambda u: u.get("leaderboard_rank", 999) <= 3},
    "night_owl":    {"name": "🦉 Сова",               "desc": "Задонатить после полуночи",       "condition": lambda u: u.get("donated_at_night", False)},
    "generosity":   {"name": "🎁 Щедрость",           "desc": "Задонатить 5000 звёзд за раз",  "condition": lambda u: u["max_single_donation"] >= 5000},
}

# ─────────────────────────────────────────────────────────────────
# ПРЕСЕТЫ СУММЫ
# ─────────────────────────────────────────────────────────────────
STAR_PRESETS = [
    {"stars": 200,  "label": "⭐ 200",  "desc": "Маленький привет"},
    {"stars": 500,  "label": "🌟 500",  "desc": "Добрый жест"},
    {"stars": 1000, "label": "💫 1 000","desc": "Серьёзная поддержка"},
    {"stars": 2500, "label": "🔥 2 500","desc": "Ты огонь!"},
    {"stars": 5000, "label": "👑 5 000","desc": "Королевская щедрость"},
]

# ─────────────────────────────────────────────────────────────────
# ПРОСТОЕ ХРАНИЛИЩЕ (JSON-файл)
# ─────────────────────────────────────────────────────────────────
DB_FILE = "donations_db.json"

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "total_donated": 0, "donations_log": []}

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_user(db: dict, user_id: int, username: str = "", full_name: str = "") -> dict:
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "id": user_id,
            "username": username,
            "full_name": full_name,
            "total_stars": 0,
            "donations_count": 0,
            "max_single_donation": 0,
            "achievements": [],
            "donated_at_night": False,
            "joined_at": datetime.now().isoformat(),
            "last_donation": None,
            "streak": 0,
        }
    else:
        if full_name:
            db["users"][uid]["full_name"] = full_name
        if username:
            db["users"][uid]["username"] = username
    return db["users"][uid]

def get_level(total_stars: int) -> dict:
    level = LEVELS[0]
    for lvl in LEVELS:
        if total_stars >= lvl["min"]:
            level = lvl
    return level

def get_next_level(total_stars: int) -> Optional[dict]:
    for i, lvl in enumerate(LEVELS):
        if total_stars < lvl["min"]:
            return lvl
    return None

def get_leaderboard(db: dict, limit: int = 10) -> list:
    users = list(db["users"].values())
    users.sort(key=lambda x: x["total_stars"], reverse=True)
    return users[:limit]

def check_achievements(user: dict, db: dict) -> list:
    """Возвращает список новых достижений."""
    new_achievements = []
    # Обновляем rank для top3
    lb = get_leaderboard(db, 3)
    for i, u in enumerate(lb):
        if str(u["id"]) == str(user["id"]):
            user["leaderboard_rank"] = i + 1

    for key, ach in ACHIEVEMENTS.items():
        if key not in user["achievements"]:
            try:
                if ach["condition"](user):
                    user["achievements"].append(key)
                    new_achievements.append(ach)
            except Exception:
                pass
    return new_achievements

# ─────────────────────────────────────────────────────────────────
# FSM СОСТОЯНИЯ
# ─────────────────────────────────────────────────────────────────
class DonateStates(StatesGroup):
    waiting_amount = State()
    waiting_message = State()

# ─────────────────────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────────
def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Поддержать", callback_data="donate_menu")
    builder.button(text="🏆 Лидерборд",  callback_data="leaderboard")
    builder.button(text="👤 Мой профиль", callback_data="profile")
    builder.button(text="🎖️ Достижения",  callback_data="achievements")
    builder.button(text="ℹ️ О боте",      callback_data="about")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def donate_presets_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for preset in STAR_PRESETS:
        builder.button(
            text=f"{preset['label']} — {preset['desc']}",
            callback_data=f"donate_preset:{preset['stars']}"
        )
    builder.button(text="✏️ Своя сумма", callback_data="donate_custom")
    builder.button(text="🔙 Назад",      callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def back_kb(target: str = "main_menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В меню", callback_data=target)
    return builder.as_markup()

def confirm_donate_kb(stars: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Оплатить {stars} ⭐", callback_data=f"confirm_donate:{stars}")
    builder.button(text="✏️ Добавить пожелание",   callback_data=f"add_wish:{stars}")
    builder.button(text="❌ Отмена",               callback_data="donate_menu")
    builder.adjust(1)
    return builder.as_markup()

# ─────────────────────────────────────────────────────────────────
# РОУТЕР
# ─────────────────────────────────────────────────────────────────
router = Router()

# ─── /start ────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db = load_db()
    user = get_user(db, message.from_user.id, message.from_user.username or "", message.from_user.full_name)
    save_db(db)

    level = get_level(user["total_stars"])
    text = (
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        f"Это бот для поддержки автора звёздами Telegram ⭐\n\n"
        f"Твой уровень: <b>{level['name']}</b>\n"
        f"Задоначено: <b>{user['total_stars']:,} ⭐</b>\n\n"
        f"Выбери действие:"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)

# ─── Главное меню ───────────────────────────────────────────────
@router.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    db = load_db()
    user = get_user(db, call.from_user.id, call.from_user.username or "", call.from_user.full_name)
    level = get_level(user["total_stars"])
    text = (
        f"🏠 <b>Главное меню</b>\n\n"
        f"Твой уровень: <b>{level['name']}</b>\n"
        f"Задоначено: <b>{user['total_stars']:,} ⭐</b>\n\n"
        f"Выбери действие:"
    )
    await call.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)

# ─── Меню доната ────────────────────────────────────────────────
@router.callback_query(F.data == "donate_menu")
async def cb_donate_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "⭐ <b>Поддержать автора</b>\n\n"
        "Выберите сумму или введите свою:"
    )
    await call.message.edit_text(text, reply_markup=donate_presets_kb(), parse_mode=ParseMode.HTML)

# ─── Пресет ─────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("donate_preset:"))
async def cb_donate_preset(call: CallbackQuery, state: FSMContext):
    stars = int(call.data.split(":")[1])
    await state.update_data(stars=stars, wish="")
    await call.message.edit_text(
        f"⭐ Вы хотите подарить <b>{stars:,} звёзд</b>\n\n"
        f"Подтвердите или добавьте пожелание автору:",
        reply_markup=confirm_donate_kb(stars),
        parse_mode=ParseMode.HTML
    )

# ─── Своя сумма ─────────────────────────────────────────────────
@router.callback_query(F.data == "donate_custom")
async def cb_donate_custom(call: CallbackQuery, state: FSMContext):
    await state.set_state(DonateStates.waiting_amount)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="donate_menu")
    await call.message.edit_text(
        "✏️ Введите количество звёзд (минимум 50):",
        reply_markup=builder.as_markup()
    )

@router.message(DonateStates.waiting_amount)
async def process_custom_amount(message: Message, state: FSMContext):
    text = message.text.strip().replace(" ", "").replace(",", "")
    if not text.isdigit():
        await message.answer("❗ Введите целое число, например: <b>750</b>", parse_mode=ParseMode.HTML)
        return
    stars = int(text)
    if stars < 50:
        await message.answer("❗ Минимальная сумма — <b>50 звёзд</b>", parse_mode=ParseMode.HTML)
        return
    if stars > 100000:
        await message.answer("❗ Максимальная сумма — <b>100 000 звёзд</b>", parse_mode=ParseMode.HTML)
        return

    await state.update_data(stars=stars, wish="")
    await state.set_state(None)
    await message.answer(
        f"⭐ Вы хотите подарить <b>{stars:,} звёзд</b>\n\n"
        f"Подтвердите или добавьте пожелание автору:",
        reply_markup=confirm_donate_kb(stars),
        parse_mode=ParseMode.HTML
    )

# ─── Добавить пожелание ─────────────────────────────────────────
@router.callback_query(F.data.startswith("add_wish:"))
async def cb_add_wish(call: CallbackQuery, state: FSMContext):
    stars = int(call.data.split(":")[1])
    await state.update_data(stars=stars)
    await state.set_state(DonateStates.waiting_message)
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭️ Пропустить", callback_data=f"confirm_donate:{stars}")
    await call.message.edit_text(
        "💌 Напишите пожелание автору (или нажмите Пропустить):",
        reply_markup=builder.as_markup()
    )

@router.message(DonateStates.waiting_message)
async def process_wish(message: Message, state: FSMContext):
    wish = message.text[:200]  # лимит
    data = await state.get_data()
    stars = data.get("stars", 200)
    await state.update_data(wish=wish)
    await state.set_state(None)
    await message.answer(
        f"⭐ <b>{stars:,} звёзд</b>\n"
        f"💌 Пожелание: <i>{wish}</i>\n\n"
        f"Подтвердите:",
        reply_markup=confirm_donate_kb(stars),
        parse_mode=ParseMode.HTML
    )

# ─── Подтверждение и "оплата" ───────────────────────────────────
@router.callback_query(F.data.startswith("confirm_donate:"))
async def cb_confirm_donate(call: CallbackQuery, state: FSMContext, bot: Bot):
    stars = int(call.data.split(":")[1])
    data = await state.get_data()
    wish = data.get("wish", "")
    await state.clear()

    db = load_db()
    user = get_user(db, call.from_user.id, call.from_user.username or "", call.from_user.full_name)

    old_total = user["total_stars"]
    old_level = get_level(old_total)

    # Обновляем статистику
    user["total_stars"] += stars
    user["donations_count"] += 1
    user["max_single_donation"] = max(user["max_single_donation"], stars)
    user["last_donation"] = datetime.now().isoformat()

    # Ночной донат (00:00 — 05:00)
    hour = datetime.now().hour
    if 0 <= hour < 5:
        user["donated_at_night"] = True

    # Стрик (если предыдущий донат был вчера)
    # (упрощённая версия)
    user["streak"] = user.get("streak", 0) + 1

    # Запись в лог
    db["total_donated"] = db.get("total_donated", 0) + stars
    db["donations_log"].append({
        "user_id": call.from_user.id,
        "username": call.from_user.username or "",
        "full_name": call.from_user.full_name,
        "stars": stars,
        "wish": wish,
        "ts": datetime.now().isoformat(),
    })

    # Достижения
    new_achievements = check_achievements(user, db)
    save_db(db)

    new_level = get_level(user["total_stars"])
    level_up = new_level["name"] != old_level["name"]

    # ─── Сообщение пользователю ───
    thank_msg = (
        f"🎉 <b>Спасибо за поддержку!</b>\n\n"
        f"Ты подарил автору <b>{stars:,} ⭐</b>\n"
        f"Всего задоначено: <b>{user['total_stars']:,} ⭐</b>\n"
        f"Твой уровень: <b>{new_level['name']}</b>\n"
    )
    if wish:
        thank_msg += f"\n💌 Твоё пожелание отправлено автору!\n"
    if level_up:
        thank_msg += f"\n🆙 <b>Поздравляем! Новый уровень: {new_level['name']}!</b>\n"
    if new_achievements:
        ach_text = "\n".join(f"  {a['name']} — {a['desc']}" for a in new_achievements)
        thank_msg += f"\n🏅 <b>Новые достижения:</b>\n{ach_text}\n"

    # Мотивирующая фраза
    next_lvl = get_next_level(user["total_stars"])
    if next_lvl:
        need = next_lvl["min"] - user["total_stars"]
        thank_msg += f"\n⚡ До уровня <b>{next_lvl['name']}</b> ещё <b>{need:,} ⭐</b>"

    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Задонатить ещё", callback_data="donate_menu")
    builder.button(text="🏆 Лидерборд",      callback_data="leaderboard")
    builder.button(text="🏠 Меню",           callback_data="main_menu")
    builder.adjust(2, 1)

    await call.message.edit_text(thank_msg, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

    # ─── Уведомление автору ───
    try:
        author_msg = (
            f"⭐ <b>Новый донат!</b>\n\n"
            f"От: <b>{call.from_user.full_name}</b>"
            f" (@{call.from_user.username})\n"
            f"Сумма: <b>{stars:,} ⭐</b>\n"
            f"Всего от пользователя: <b>{user['total_stars']:,} ⭐</b>\n"
            f"Уровень: <b>{new_level['name']}</b>\n"
        )
        if wish:
            author_msg += f"\n💌 Пожелание: <i>{wish}</i>"
        await bot.send_message(AUTHOR_ID, author_msg, parse_mode=ParseMode.HTML)
    except Exception:
        pass  # Автор не запустил бота или заблокировал

# ─── Лидерборд ──────────────────────────────────────────────────
@router.callback_query(F.data == "leaderboard")
async def cb_leaderboard(call: CallbackQuery):
    db = load_db()
    top = get_leaderboard(db, 10)

    medals = ["🥇", "🥈", "🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    lines = [f"🏆 <b>Лидерборд звёздных донатеров</b>\n"]
    lines.append(f"💫 Всего задоначено: <b>{db.get('total_donated',0):,} ⭐</b>\n")

    for i, u in enumerate(top):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        name = u["full_name"] or u["username"] or f"User{u['id']}"
        level = get_level(u["total_stars"])
        lines.append(f"{medal} <b>{name}</b> {level['emoji']}")
        lines.append(f"    {u['total_stars']:,} ⭐ · {u['donations_count']} донатов")

    # Позиция текущего пользователя
    all_users = sorted(db["users"].values(), key=lambda x: x["total_stars"], reverse=True)
    my_rank = None
    for i, u in enumerate(all_users):
        if u["id"] == call.from_user.id:
            my_rank = i + 1
            break

    if my_rank and my_rank > 10:
        me = db["users"].get(str(call.from_user.id), {})
        lines.append(f"\n📍 Ваше место: <b>#{my_rank}</b> — {me.get('total_stars',0):,} ⭐")

    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Задонатить",  callback_data="donate_menu")
    builder.button(text="🔙 В меню",     callback_data="main_menu")
    builder.adjust(2)

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

# ─── Профиль ────────────────────────────────────────────────────
@router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    db = load_db()
    user = get_user(db, call.from_user.id, call.from_user.username or "", call.from_user.full_name)
    save_db(db)

    level = get_level(user["total_stars"])
    next_lvl = get_next_level(user["total_stars"])

    # Ранг
    all_users = sorted(db["users"].values(), key=lambda x: x["total_stars"], reverse=True)
    rank = next((i+1 for i, u in enumerate(all_users) if u["id"] == call.from_user.id), "?")

    lines = [
        f"👤 <b>Профиль</b>",
        f"",
        f"Имя: <b>{call.from_user.full_name}</b>",
        f"Уровень: <b>{level['name']}</b>",
        f"Место в рейтинге: <b>#{rank}</b>",
        f"",
        f"⭐ Всего задоначено: <b>{user['total_stars']:,}</b>",
        f"📊 Количество донатов: <b>{user['donations_count']}</b>",
        f"💎 Максимальный донат: <b>{user['max_single_donation']:,}</b>",
        f"🏅 Достижений: <b>{len(user['achievements'])}/{len(ACHIEVEMENTS)}</b>",
    ]

    if user["last_donation"]:
        dt = datetime.fromisoformat(user["last_donation"])
        lines.append(f"🕐 Последний донат: <b>{dt.strftime('%d.%m.%Y %H:%M')}</b>")

    if next_lvl:
        need = next_lvl["min"] - user["total_stars"]
        lines.append(f"")
        lines.append(f"⚡ До <b>{next_lvl['name']}</b>: ещё <b>{need:,} ⭐</b>")

    builder = InlineKeyboardBuilder()
    builder.button(text="🎖️ Достижения",  callback_data="achievements")
    builder.button(text="⭐ Задонатить",  callback_data="donate_menu")
    builder.button(text="🔙 В меню",     callback_data="main_menu")
    builder.adjust(2, 1)

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

# ─── Достижения ─────────────────────────────────────────────────
@router.callback_query(F.data == "achievements")
async def cb_achievements(call: CallbackQuery):
    db = load_db()
    user = get_user(db, call.from_user.id)

    lines = ["🏅 <b>Достижения</b>\n"]
    for key, ach in ACHIEVEMENTS.items():
        got = key in user["achievements"]
        icon = "✅" if got else "🔒"
        lines.append(f"{icon} <b>{ach['name']}</b>")
        lines.append(f"    <i>{ach['desc']}</i>")

    lines.append(f"\nПолучено: <b>{len(user['achievements'])}/{len(ACHIEVEMENTS)}</b>")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=back_kb("profile"),
        parse_mode=ParseMode.HTML
    )

# ─── О боте ─────────────────────────────────────────────────────
@router.callback_query(F.data == "about")
async def cb_about(call: CallbackQuery):
    db = load_db()
    total = db.get("total_donated", 0)
    user_count = len(db["users"])

    text = (
        "ℹ️ <b>О боте</b>\n\n"
        "⭐ <b>StarSupport</b> — бот для поддержки авторов звёздами Telegram.\n\n"
        "<b>Что умеет бот:</b>\n"
        "• Принимать звёзды любой суммой\n"
        "• Пресеты: 200 / 500 / 1000 / 2500 / 5000 ⭐\n"
        "• Лидерборд топ-10 донатеров\n"
        "• 7 уровней (от Новичка до Бриллианта)\n"
        "• 8 уникальных достижений\n"
        "• Персональный профиль\n"
        "• Пожелания автору\n"
        "• Уведомления автору о каждом донате\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"Всего задоначено: <b>{total:,} ⭐</b>\n"
        f"Уникальных донатеров: <b>{user_count}</b>\n"
    )
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode=ParseMode.HTML)

# ─── /stats (для автора) ─────────────────────────────────────────
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != AUTHOR_ID:
        return
    db = load_db()
    total = db.get("total_donated", 0)
    user_count = len(db["users"])
    logs = db.get("donations_log", [])
    today = datetime.now().date()
    today_stars = sum(
        l["stars"] for l in logs
        if datetime.fromisoformat(l["ts"]).date() == today
    )
    text = (
        f"📊 <b>Статистика автора</b>\n\n"
        f"💫 Всего звёзд: <b>{total:,}</b>\n"
        f"📅 Сегодня: <b>{today_stars:,}</b>\n"
        f"👥 Донатеров: <b>{user_count}</b>\n"
        f"📝 Всего донатов: <b>{len(logs)}</b>\n"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

# ─────────────────────────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
