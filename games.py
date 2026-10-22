"""Игры: кубики Telegram, 21, краш, мины, монета, рулетка."""
import asyncio
import math
import random
import secrets
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import economy as eco
from config import *
from registry import cmd
from utils import cid_of, esc, fmt, money, parse_amount

router = Router()
ACTIVE: dict[tuple, tuple] = {}   # (uid,cid) -> (gid, ts)
GAMES: dict[str, dict] = {}


async def place_bet(m: Message, arg: str):
    """Списывает ставку. Возвращает (cid, bet) или None."""
    cid = cid_of(m)
    uid = m.from_user.id
    bal = await eco.ensure_wallet(uid, cid)
    bet = parse_amount(arg.split()[0] if arg.split() else "", bal)
    if not bet:
        await m.reply("Укажи ставку, например: <code>100</code>, <code>5к</code> или <code>все</code>")
        return None
    if bet < MIN_BET:
        await m.reply(f"Минимальная ставка — {MIN_BET}")
        return None
    if not await eco.w_take(uid, cid, bet):
        await m.reply(f"Недостаточно хел коинов. В кошельке: {money(bal)}")
        return None
    await eco.pay_elite("casino", bet, 0.01)
    return cid, bet


def busy(uid, cid) -> bool:
    cur = ACTIVE.get((uid, cid))
    return bool(cur and time.time() - cur[1] < 600 and cur[0] in GAMES)


def register(uid, cid, gid):
    ACTIVE[(uid, cid)] = (gid, time.time())


def finish(gid):
    g = GAMES.pop(gid, None)
    if g:
        ACTIVE.pop((g["uid"], g["cid"]), None)


async def result_line(uid, cid, bet, payout):
    bal = await eco.ensure_wallet(uid, cid)
    if payout > bet:
        head = f"🎉 Выигрыш: <b>+{fmt(payout - bet)}</b> (×{payout / bet:.2f})"
    elif payout == bet:
        head = "🤝 Ничья, ставка возвращена"
    else:
        head = f"😔 Проигрыш: <b>-{fmt(bet - payout)}</b>"
    return f"{head}\n👛 Кошелёк: {money(bal)}"


# ---------------- кубики Telegram ----------------
def slots_mult(v):
    return 25 if v == 64 else 10 if v in (1, 22, 43) else 0


DICE = {
    "футбол": ("⚽", lambda v: 1.6 if v >= 3 else 0),
    "баскетбол": ("🏀", lambda v: 2.3 if v >= 4 else 0),
    "дартс": ("🎯", lambda v: {6: 3, 5: 2, 4: 0.5}.get(v, 0)),
    "боулинг": ("🎳", lambda v: {6: 4, 5: 1.5}.get(v, 0)),
    "слоты": ("🎰", slots_mult),
    "кости": ("🎲", lambda v: 1.9 if v >= 4 else 0),
}


def make_dice(name):
    emoji, fn = DICE[name]

    async def handler(m: Message, args: str):
        bet_info = await place_bet(m, args)
        if not bet_info:
            return
        cid, bet = bet_info
        sent = await m.reply_dice(emoji=emoji)
        await asyncio.sleep(4)
        payout = int(bet * fn(sent.dice.value))
        if payout:
            await eco.w_add(m.from_user.id, cid, payout)
        await m.reply(await result_line(m.from_user.id, cid, bet, payout))

    return handler


for _n in DICE:
    cmd(_n, chat_only=True)(make_dice(_n))


# ---------------- монета ----------------
@cmd("монета", "монетка", chat_only=True)
async def coin(m: Message, args: str):
    parts = args.lower().split()
    if len(parts) < 2 or parts[1] not in ("орел", "орёл", "решка"):
        return await m.reply("Формат: <code>монета 100 орёл</code> или <code>монета 100 решка</code>")
    bi = await place_bet(m, parts[0])
    if not bi:
        return
    cid, bet = bi
    pick = "орел" if parts[1] in ("орел", "орёл") else "решка"
    res = random.choice(["орел", "решка"])
    payout = int(bet * 1.95) if res == pick else 0
    if payout:
        await eco.w_add(m.from_user.id, cid, payout)
    await m.reply(f"🪙 Выпало: <b>{'орёл' if res == 'орел' else 'решка'}</b>\n" +
                  await result_line(m.from_user.id, cid, bet, payout))


# ---------------- рулетка (открывается на этапе 1) ----------------
RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


@cmd("рулетка", chat_only=True)
async def roulette(m: Message, args: str):
    if eco.stage_of((await eco.city())["total"]) < 1:
        return await m.reply("🔒 Рулетка откроется, когда бюджет города заполнит этап 1 (смотри «бюджет»)")
    parts = args.lower().split()
    if len(parts) < 2:
        return await m.reply("Формат: <code>рулетка 100 красное</code> / <code>чёрное</code> / <code>зеро</code> / число 0-36")
    pick = parts[1].replace("ё", "е")
    if pick not in ("красное", "черное", "зеро") and not (pick.isdigit() and 0 <= int(pick) <= 36):
        return await m.reply("Ставь на красное, чёрное, зеро или число 0-36")
    bi = await place_bet(m, parts[0])
    if not bi:
        return
    cid, bet = bi
    n = random.randint(0, 36)
    color = "зеро" if n == 0 else "красное" if n in RED else "черное"
    if pick.isdigit():
        mult = 36 if int(pick) == n else 0
    elif pick == "зеро":
        mult = 36 if n == 0 else 0
    else:
        mult = 2 if pick == color else 0
    payout = bet * mult
    if payout:
        await eco.w_add(m.from_user.id, cid, payout)
    icon = "🟢" if n == 0 else "🔴" if n in RED else "⚫"
    await m.reply(f"🎡 Выпало: {icon} <b>{n}</b>\n" + await result_line(m.from_user.id, cid, bet, payout))


# ---------------- 21 (блэкджек) ----------------
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = "♠♥♦♣"


def draw():
    return random.choice(RANKS), random.choice(SUITS)


def score(hand):
    total = aces = 0
    for r, _ in hand:
        if r == "A":
            aces += 1
            total += 11
        elif r in "JQK" or r == "10":
            total += 10
        else:
            total += int(r)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def hand_str(hand):
    return " ".join(f"{r}{s}" for r, s in hand)


def bj_kb(gid):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj:{gid}:hit"),
        InlineKeyboardButton(text="✋ Хватит", callback_data=f"bj:{gid}:stand")]])


def bj_text(g, reveal=False, footer=""):
    d = hand_str(g["dealer"]) if reveal else f"{g['dealer'][0][0]}{g['dealer'][0][1]} ??"
    ds = score(g["dealer"]) if reveal else "?"
    return (f"🃏 <b>21</b> · ставка {fmt(g['bet'])}\n\n"
            f"Дилер: {d} ({ds})\nТы: {hand_str(g['player'])} ({score(g['player'])})\n{footer}")


@cmd("21", "очко", "блэкджек", chat_only=True)
async def blackjack(m: Message, args: str):
    uid, cid = m.from_user.id, m.chat.id
    if busy(uid, cid):
        return await m.reply("Сначала закончи текущую игру")
    bi = await place_bet(m, args)
    if not bi:
        return
    _, bet = bi
    gid = secrets.token_hex(4)
    g = dict(uid=uid, cid=cid, bet=bet, player=[draw(), draw()], dealer=[draw(), draw()])
    GAMES[gid] = g
    register(uid, cid, gid)
    p, d = score(g["player"]), score(g["dealer"])
    if p == 21:
        finish(gid)
        payout = bet if d == 21 else int(bet * 2.5)
        await eco.w_add(uid, cid, payout)
        return await m.reply(bj_text(g, True, "Блэкджек! 🎊\n") + await result_line(uid, cid, bet, payout))
    await m.reply(bj_text(g), reply_markup=bj_kb(gid))


@router.callback_query(F.data.startswith("bj:"))
async def bj_cb(cb: CallbackQuery):
    _, gid, act = cb.data.split(":")
    g = GAMES.get(gid)
    if not g:
        return await cb.answer("Игра уже закончена", show_alert=True)
    if cb.from_user.id != g["uid"]:
        return await cb.answer("Это не твоя игра", show_alert=True)
    uid, cid, bet = g["uid"], g["cid"], g["bet"]
    if act == "hit":
        g["player"].append(draw())
        p = score(g["player"])
        if p > 21:
            finish(gid)
            return await cb.message.edit_text(bj_text(g, True, "Перебор! 💥\n") + await result_line(uid, cid, bet, 0))
        if p == 21:
            act = "stand"
        else:
            await cb.message.edit_text(bj_text(g), reply_markup=bj_kb(gid))
            return await cb.answer()
    # stand
    finish(gid)
    while score(g["dealer"]) < 17:
        g["dealer"].append(draw())
    p, d = score(g["player"]), score(g["dealer"])
    payout = bet * 2 if (d > 21 or p > d) else bet if p == d else 0
    if payout:
        await eco.w_add(uid, cid, payout)
    await cb.message.edit_text(bj_text(g, True) + "\n" + await result_line(uid, cid, bet, payout))
    await cb.answer()


# ---------------- краш ----------------
def crash_kb(gid):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💸 Забрать", callback_data=f"cr:{gid}")]])


@cmd("краш", "crash", chat_only=True)
async def crash(m: Message, args: str):
    uid, cid = m.from_user.id, m.chat.id
    if busy(uid, cid):
        return await m.reply("Сначала закончи текущую игру")
    bi = await place_bet(m, args)
    if not bi:
        return
    _, bet = bi
    gid = secrets.token_hex(4)
    point = min(1000.0, max(1.0, round(0.95 / (1 - random.random()), 2)))
    g = dict(uid=uid, cid=cid, bet=bet, mult=1.0, point=point, done=False)
    GAMES[gid] = g
    register(uid, cid, gid)
    msg = await m.reply(f"📈 <b>Краш</b> · ставка {fmt(bet)}\n\nМножитель: <b>x1.00</b>", reply_markup=crash_kb(gid))
    asyncio.create_task(crash_loop(gid, msg))


async def crash_loop(gid, msg: Message):
    g = GAMES.get(gid)
    while g and not g["done"]:
        await asyncio.sleep(1.3)
        if g["done"]:
            return
        g["mult"] = round(g["mult"] * 1.15 + 0.01, 2)
        if g["mult"] >= g["point"]:
            g["done"] = True
            finish(gid)
            txt = (f"💥 <b>Краш на x{g['point']:.2f}</b> · ставка {fmt(g['bet'])}\n\n" +
                   await result_line(g["uid"], g["cid"], g["bet"], 0))
            try:
                await msg.edit_text(txt)
            except Exception:
                pass
            return
        try:
            await msg.edit_text(f"📈 <b>Краш</b> · ставка {fmt(g['bet'])}\n\nМножитель: <b>x{g['mult']:.2f}</b>",
                                reply_markup=crash_kb(gid))
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith("cr:"))
async def crash_cb(cb: CallbackQuery):
    gid = cb.data.split(":")[1]
    g = GAMES.get(gid)
    if not g or g["done"]:
        return await cb.answer("Раунд уже закончился", show_alert=True)
    if cb.from_user.id != g["uid"]:
        return await cb.answer("Это не твоя игра", show_alert=True)
    g["done"] = True
    finish(gid)
    payout = int(g["bet"] * g["mult"])
    await eco.w_add(g["uid"], g["cid"], payout)
    await cb.message.edit_text(f"✅ <b>Забрал на x{g['mult']:.2f}</b>\n\n" +
                               await result_line(g["uid"], g["cid"], g["bet"], payout))
    await cb.answer()


# ---------------- мины ----------------
def mines_mult(opened: int, mines: int) -> float:
    if opened == 0:
        return 1.0
    return 0.96 * math.comb(25, opened) / math.comb(25 - mines, opened)


def mines_kb(gid, g, reveal=False):
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            i = r * 5 + c
            if i in g["opened"]:
                t, d = "💎", "noop"
            elif reveal and i in g["mines"]:
                t, d = "💣", "noop"
            else:
                t, d = "▫️", f"mn:{gid}:{i}"
            row.append(InlineKeyboardButton(text=t, callback_data=d if d != "noop" else f"mn:{gid}:x"))
        rows.append(row)
    if not reveal:
        k = len(g["opened"])
        rows.append([InlineKeyboardButton(text=f"💸 Забрать x{mines_mult(k, g['m']):.2f}" if k else "Открой клетку",
                                          callback_data=f"mn:{gid}:cash")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mines_text(g, footer=""):
    k = len(g["opened"])
    return (f"💣 <b>Мины</b> · ставка {fmt(g['bet'])} · мин: {g['m']}\n"
            f"Открыто: {k} · Множитель: <b>x{mines_mult(k, g['m']):.2f}</b>\n{footer}")


@cmd("мины", chat_only=True)
async def mines(m: Message, args: str):
    uid, cid = m.from_user.id, m.chat.id
    if busy(uid, cid):
        return await m.reply("Сначала закончи текущую игру")
    parts = args.split()
    cnt = 3
    if len(parts) > 1:
        if not parts[1].isdigit() or not 1 <= int(parts[1]) <= 20:
            return await m.reply("Количество мин — от 1 до 20: <code>мины 100 5</code>")
        cnt = int(parts[1])
    bi = await place_bet(m, args)
    if not bi:
        return
    _, bet = bi
    gid = secrets.token_hex(4)
    g = dict(uid=uid, cid=cid, bet=bet, m=cnt, mines=set(random.sample(range(25), cnt)), opened=set())
    GAMES[gid] = g
    register(uid, cid, gid)
    await m.reply(mines_text(g), reply_markup=mines_kb(gid, g))


@router.callback_query(F.data.startswith("mn:"))
async def mines_cb(cb: CallbackQuery):
    _, gid, act = cb.data.split(":")
    g = GAMES.get(gid)
    if not g:
        return await cb.answer("Игра уже закончена", show_alert=True)
    if cb.from_user.id != g["uid"]:
        return await cb.answer("Это не твоя игра", show_alert=True)
    uid, cid, bet = g["uid"], g["cid"], g["bet"]
    if act == "x":
        return await cb.answer()
    if act == "cash":
        if not g["opened"]:
            return await cb.answer("Сначала открой хотя бы одну клетку", show_alert=True)
        finish(gid)
        payout = int(bet * mines_mult(len(g["opened"]), g["m"]))
        await eco.w_add(uid, cid, payout)
        await cb.message.edit_text(mines_text(g, "\n✅ Забрал!\n" + await result_line(uid, cid, bet, payout)),
                                   reply_markup=mines_kb(gid, g, reveal=True))
        return await cb.answer()
    i = int(act)
    if i in g["opened"]:
        return await cb.answer()
    if i in g["mines"]:
        finish(gid)
        await cb.message.edit_text(mines_text(g, "\n💥 Мина!\n" + await result_line(uid, cid, bet, 0)),
                                   reply_markup=mines_kb(gid, g, reveal=True))
        return await cb.answer()
    g["opened"].add(i)
    if len(g["opened"]) == 25 - g["m"]:
        finish(gid)
        payout = int(bet * mines_mult(len(g["opened"]), g["m"]))
        await eco.w_add(uid, cid, payout)
        await cb.message.edit_text(mines_text(g, "\n🏆 Всё поле очищено!\n" + await result_line(uid, cid, bet, payout)),
                                   reply_markup=mines_kb(gid, g, reveal=True))
        return await cb.answer()
    await cb.message.edit_text(mines_text(g), reply_markup=mines_kb(gid, g))
    await cb.answer()
