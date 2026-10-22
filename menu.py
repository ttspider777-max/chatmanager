"""Главное меню в личке бота."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
import economy as eco
import texts
from access import SUB_TEXT, missing_subs, sub_markup
from config import *
from aiogram.types import MessageEntity

import json
from utils import esc, fill_name, fmt, screen

router = Router()
router.message.filter(F.chat.type == "private")

BACK = [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu")]


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def main_kb(uid: int) -> InlineKeyboardMarkup:
    add_url = (f"https://t.me/{config.BOT_USERNAME}?startgroup=true"
               "&admin=delete_messages+restrict_members+invite_users+pin_messages")
    rows = [
        [InlineKeyboardButton(text="➕ Добавить в свой чат", url=add_url)],
        [InlineKeyboardButton(text="💰 Мой счёт", callback_data="acc"),
         InlineKeyboardButton(text="🏆 Топ богачей", callback_data="top")],
        [InlineKeyboardButton(text="🏛 Бюджет города", callback_data="city"),
         InlineKeyboardButton(text="📜 Облигации города", callback_data="bonds")],
        [InlineKeyboardButton(text="💠 Элитные бизнесы", callback_data="elite")],
        [InlineKeyboardButton(text="📖 Все команды", callback_data="cmds")],
    ]
    if uid == DEV_ID:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_text(name: str) -> str:
    return (f"👋 Привет, <b>{esc(name)}</b>!\n\n"
            "Я чат-менеджер <b>Heliys</b>: экономика с хел коинами, игры, элитные бизнесы и модерация чатов.\n"
            "Добавь меня в свой чат кнопкой ниже — и играйте прямо там.")


async def show_main(ev, user):
    """Главное меню с приветствием: своё (из админки, с премиум-эмодзи) или стандартное."""
    raw = await db.get_setting("greeting")
    if raw:
        try:
            g = json.loads(raw)
            text, ents = fill_name(g["text"], g["entities"], user.first_name or "")
            return await screen(ev, text, main_kb(user.id), entities=[MessageEntity(**e) for e in ents] or None)
        except Exception:
            pass
    await screen(ev, main_text(user.first_name), main_kb(user.id))


@router.message(CommandStart())
async def start(m: Message):
    missing = await missing_subs(m.bot, m.from_user.id)
    if missing:
        return await m.answer(SUB_TEXT, reply_markup=sub_markup(missing))
    await show_main(m, m.from_user)


@router.callback_query(F.data == "chk_sub")
async def chk_sub(cb: CallbackQuery):
    missing = await missing_subs(cb.bot, cb.from_user.id)
    if missing:
        return await cb.answer("Ты ещё не подписался на все каналы", show_alert=True)
    await show_main(cb, cb.from_user)


@router.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery):
    await show_main(cb, cb.from_user)


@router.callback_query(F.data == "acc")
async def acc(cb: CallbackQuery):
    await screen(cb, await texts.account_text(cb.from_user.id), kb(BACK))


@router.callback_query(F.data == "top")
async def top(cb: CallbackQuery):
    await screen(cb, await texts.top_text(), kb(BACK))


@router.callback_query(F.data == "city")
async def city(cb: CallbackQuery):
    await screen(cb, await texts.city_text(), kb(BACK))


@router.callback_query(F.data == "cmds")
async def cmds(cb: CallbackQuery):
    await screen(cb, texts.help_text(), kb(BACK))


def bonds_kb():
    return kb([InlineKeyboardButton(text=f"Купить {n}", callback_data=f"bb:{n}") for n in (1, 10, 100)], BACK)


@router.callback_query(F.data == "bonds")
async def bonds(cb: CallbackQuery):
    await screen(cb, await texts.bonds_text(cb.from_user.id), bonds_kb())


@router.callback_query(F.data.startswith("bb:"))
async def bond_buy(cb: CallbackQuery):
    ok, msg = await eco.buy_bonds(cb.from_user.id, None, int(cb.data.split(":")[1]))
    await cb.answer(msg, show_alert=True)
    if ok:
        await screen(cb, await texts.bonds_text(cb.from_user.id), bonds_kb())


def elite_kb():
    rows = [[InlineKeyboardButton(text=f"{e['emoji']} Арендовать: {e['name']}", callback_data=f"eb:{k}")]
            for k, e in ELITE.items()]
    return kb(*rows, BACK)


@router.callback_query(F.data == "elite")
async def elite(cb: CallbackQuery):
    await screen(cb, await texts.elite_text(), elite_kb())


@router.callback_query(F.data.startswith("eb:"))
async def elite_buy(cb: CallbackQuery):
    ok, msg = await eco.rent_elite(cb.from_user.id, cb.data.split(":")[1])
    await cb.answer(msg, show_alert=True)
    if ok:
        await screen(cb, await texts.elite_text(), elite_kb())
