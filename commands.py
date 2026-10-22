"""Текстовые команды (работают в чатах и частично в личке) + общий диспетчер."""
import re
import time

from aiogram import F, Router
from aiogram.types import Message

import config
import db
import economy as eco
import games  # noqa: F401  (регистрирует игровые команды)
import moderation
import texts
from access import SUB_TEXT, missing_subs, sub_markup
from config import *
from registry import COMMANDS, cmd
from utils import cid_of, esc, fmt, money, mention, parse_amount

router = Router()
router.include_router(games.router)


# ---------- кошелёк ----------
@cmd("баланс", "кошелек", "кошелёк")
async def c_balance(m: Message, args: str):
    cid = cid_of(m)
    if cid is None:
        return await m.answer(await texts.account_text(m.from_user.id))
    bal = await eco.ensure_wallet(m.from_user.id, cid)
    u = await db.get_user(m.from_user.id)
    await m.reply(f"👛 <b>Кошелёк чата:</b> {money(bal)}\n💳 На счёте: {money(u['account'])}\n"
                  f"📜 Облигации: {fmt(u['bonds'])}\n💰 Всего: {money(await eco.wealth(m.from_user.id))}")


@cmd("счет снять", "счёт снять", chat_only=True)
async def c_withdraw(m: Message, args: str):
    u = await db.get_user(m.from_user.id)
    amt = parse_amount(args.split()[0] if args.split() else "", u["account"])
    if not amt:
        return await m.reply("Формат: <code>счет снять 100</code>")
    if not await eco.a_take(m.from_user.id, amt):
        return await m.reply(f"На счёте только {money(u['account'])}")
    await eco.w_add(m.from_user.id, m.chat.id, amt)
    await m.reply(f"💳➡️👛 Переведено на кошелёк чата: <b>{money(amt)}</b>")


@cmd("счет", "счёт")
async def c_account(m: Message, args: str):
    await m.answer(await texts.account_text(m.from_user.id))


@cmd("бонус", chat_only=True)
async def c_bonus(m: Message, args: str):
    ok, msg = await eco.daily_bonus(m.from_user.id, m.chat.id)
    await m.reply(msg)


@cmd("перевод", chat_only=True)
async def c_transfer(m: Message, args: str):
    t = await moderation.resolve_target(m, args)
    if not t:
        return await m.reply("Ответь на сообщение получателя: <code>перевод 100</code> (или <code>перевод @user 100</code>)")
    uid, name, rest = t
    if uid == m.from_user.id or uid == m.bot.id:
        return await m.reply("Нельзя перевести этому получателю")
    bal = await eco.ensure_wallet(m.from_user.id, m.chat.id)
    amt = parse_amount(rest.split()[0] if rest.split() else "", bal)
    if not amt:
        return await m.reply("Укажи сумму: <code>перевод 100</code>")
    ok, err, fee = await eco.transfer(m.from_user.id, uid, m.chat.id, amt)
    await m.reply(f"💸 {mention(m.from_user.id, m.from_user.full_name)} → {mention(uid, name)}: <b>{money(amt)}</b>"
                  f"\nКомиссия: {money(fee)}" if ok else err)


@cmd("вклад снять", chat_only=True)
async def c_dep_out(m: Message, args: str):
    await eco.accrue(m.from_user.id)
    u = await db.get_user(m.from_user.id)
    amt = parse_amount(args.split()[0] if args.split() else "", u["deposit"])
    if not amt:
        return await m.reply("Формат: <code>вклад снять 500</code> или <code>вклад снять все</code>")
    ok, msg = await eco.deposit_out(m.from_user.id, m.chat.id, amt)
    await m.reply(msg)


@cmd("вклад", chat_only=True)
async def c_dep(m: Message, args: str):
    await eco.accrue(m.from_user.id)
    u = await db.get_user(m.from_user.id)
    bank = await eco.elite_state("bank")
    rate = DEPOSIT_RATE_DAY * (BANK_BONUS if bank else 1) * 100
    if not args.strip():
        return await m.reply(f"🏦 <b>Вклад:</b> {money(u['deposit'])}\nПроцент: {rate:.2f}% в сутки (копится до 7 дней)\n"
                             f"Комиссия на вход: {int(DEPOSIT_FEE * 100)}%\n\n"
                             "<code>вклад 1000</code> — положить из кошелька\n<code>вклад снять 500</code> — забрать")
    bal = await eco.ensure_wallet(m.from_user.id, m.chat.id)
    amt = parse_amount(args.split()[0], bal)
    if not amt:
        return await m.reply("Формат: <code>вклад 1000</code>")
    ok, msg = await eco.deposit_in(m.from_user.id, m.chat.id, amt)
    await m.reply(msg)


# ---------- облигации / бюджет ----------
@cmd("купить облигации", "облигации купить", "купить облигацию")
async def c_buy_bonds(m: Message, args: str):
    a = args.split()[0] if args.split() else "1"
    if not a.isdigit() or not int(a):
        return await m.reply("Формат: <code>купить облигации 5</code>")
    ok, msg = await eco.buy_bonds(m.from_user.id, cid_of(m), int(a))
    await m.reply(msg)


@cmd("облигации")
async def c_bonds(m: Message, args: str):
    await m.answer(await texts.bonds_text(m.from_user.id))


@cmd("бюджет")
async def c_budget(m: Message, args: str):
    if not args.strip():
        return await m.answer(await texts.city_text())
    cid = cid_of(m)
    bal = await eco.source_balance(m.from_user.id, cid)
    amt = parse_amount(args.split()[0], bal)
    if not amt:
        return await m.reply("Формат: <code>бюджет 1000</code>")
    ok, msg = await eco.invest(m.from_user.id, cid, amt)
    await m.reply(msg)


@cmd("бизнесы", "элита", "элитные бизнесы")
async def c_elite(m: Message, args: str):
    await m.answer(await texts.elite_text() + "\nАрендовать: в личке бота → «Элитные бизнесы».")


# ---------- топы / профиль ----------
@cmd("топ")
async def c_top(m: Message, args: str):
    await m.answer(await texts.top_text())


@cmd("топ чата", chat_only=True)
async def c_top_chat(m: Message, args: str):
    rows = await db.many("SELECT u.id,u.name,u.username,w.balance FROM wallets w JOIN users u ON u.id=w.user_id "
                         "WHERE w.chat_id=? ORDER BY w.balance DESC LIMIT 10", (m.chat.id,))
    await m.answer("🏆 <b>Топ кошельков этого чата</b>\n\n" +
                   ("\n".join(f"{i + 1}. {texts.uname(r)} — {fmt(r['balance'])}" for i, r in enumerate(rows)) or "Пока пусто"))


@cmd("профиль")
async def c_profile(m: Message, args: str):
    u = await db.get_user(m.from_user.id)
    props = await db.scalar("SELECT COUNT(*) FROM props WHERE user_id=?", (m.from_user.id,))
    owned = [e["emoji"] + " " + e["name"] for k, e in ELITE.items()
             if (st := await eco.elite_state(k)) and st["owner_id"] == m.from_user.id]
    await m.reply(f"👤 <b>{esc(m.from_user.full_name)}</b>\nID: <code>{m.from_user.id}</code>\n"
                  f"💰 Всего: {money(await eco.wealth(m.from_user.id))}\n📜 Облигации: {fmt(u['bonds'])}\n"
                  f"🏛 Вложено в город: {money(u['invested'])}\n💼 Имущество: {props} шт.\n"
                  f"💬 Сообщений: {fmt(u['msgs'])}" + (f"\n💠 Арендует: {', '.join(owned)}" if owned else ""))


@cmd("промо", "промокод")
async def c_promo(m: Message, args: str):
    if not args.strip():
        return await m.reply("Формат: <code>промо КОД</code>")
    ok, msg = await eco.redeem_promo(m.from_user.id, args.split()[0])
    await m.reply(msg)


# ---------- магазин ----------
@cmd("магазин", chat_only=True)
async def c_shop(m: Message, args: str):
    t = "🛒 <b>Магазин</b> (купить: <code>купить b1</code>)\n"
    for catkey, catname in CATEGORY_NAMES.items():
        t += f"\n<b>{catname}</b>\n"
        for code, (cat, emoji, name, price, inc) in SHOP.items():
            if cat == catkey:
                t += f"<code>{code}</code> {emoji} {name} — {fmt(price)} · +{fmt(inc)}/ч\n"
    await m.reply(t + "\nДоход собирается командой <code>собрать</code> (копится до 24 ч).")


@cmd("купить", chat_only=True)
async def c_buy(m: Message, args: str):
    code = args.split()[0].lower() if args.split() else ""
    if code not in SHOP:
        return
    ok, msg = await eco.buy_item(m.from_user.id, m.chat.id, code)
    await m.reply(msg)


@cmd("имущество", "мои бизнесы", chat_only=True)
async def c_props(m: Message, args: str):
    rows = await db.many("SELECT item FROM props WHERE user_id=?", (m.from_user.id,))
    if not rows:
        return await m.reply("У тебя пока ничего нет. Загляни в «магазин»")
    lines = [f"{SHOP[r['item']][1]} {SHOP[r['item']][2]} — +{fmt(SHOP[r['item']][4])}/ч" for r in rows]
    total = sum(SHOP[r["item"]][4] for r in rows)
    await m.reply("💼 <b>Твоё имущество</b>\n" + "\n".join(lines) + f"\n\nИтого: +{fmt(total)}/ч · команда «собрать»")


@cmd("собрать", chat_only=True)
async def c_collect(m: Message, args: str):
    ok, msg = await eco.collect(m.from_user.id, m.chat.id)
    await m.reply(msg)


# ---------- справка ----------
@cmd("команды", "помощь", "help", "хелп", gate=False)
async def c_help(m: Message, args: str):
    await m.answer(texts.help_text())


@cmd("start", "старт", gate=False)
async def c_start(m: Message, args: str):
    if m.chat.type == "private":
        return  # обрабатывает menu.py
    await m.reply("👋 Я чат-менеджер Heliys: экономика, игры и модерация.\nНапиши <code>команды</code>.")


# ---------- диспетчер ----------
PHRASES = None
PENDING: dict[tuple, tuple] = {}   # (uid, chat) -> (команда, до какого времени ждём ставку)
GAME_CMDS = set(games.DICE) | {"монета", "монетка", "21", "очко", "блэкджек", "краш", "crash", "мины", "рулетка"}


def _normalize(text: str) -> str:
    text = text.strip()
    if text.startswith("/"):
        text = text[1:]
        text = re.sub(r"^(\S+?)@\w+", r"\1", text)
    return text


async def dispatch(m: Message) -> bool:
    global PHRASES
    if PHRASES is None or len(PHRASES) != len(COMMANDS):
        PHRASES = sorted(COMMANDS, key=len, reverse=True)
    text = _normalize(m.text or "")
    low = text.lower()
    for ph in PHRASES:
        if low == ph or low.startswith(ph + " "):
            c = COMMANDS[ph]
            if c.chat_only and m.chat.type == "private":
                await m.answer("Эта команда работает в чатах: добавь бота в свой чат или зайди в чат с ботом 🙂")
                return True
            if c.gate:
                missing = await missing_subs(m.bot, m.from_user.id)
                if missing:
                    await m.reply(SUB_TEXT, reply_markup=sub_markup(missing))
                    return True
            rest = text[len(ph):].strip()
            if ph in GAME_CMDS and not rest:
                # игра без ставки: спрашиваем и ждём следующее сообщение этого игрока
                PENDING[(m.from_user.id, m.chat.id)] = (ph, time.time() + 90)
                await m.reply(f"🎮 <b>{esc(ph)}</b>: напиши ставку ответным сообщением "
                              "(например <code>100</code>, <code>5к</code> или <code>все</code>)." +
                              (" Для монеты: <code>100 орёл</code>." if ph in ("монета", "монетка") else "") +
                              (" Для рулетки: <code>100 красное</code>." if ph == "рулетка" else "") +
                              (" Для мин можно добавить число мин: <code>100 5</code>." if ph == "мины" else ""))
                return True
            PENDING.pop((m.from_user.id, m.chat.id), None)
            await c.fn(m, rest)
            return True
    # ответ на вопрос «напиши ставку»
    pend = PENDING.get((m.from_user.id, m.chat.id)) if m.chat.type != "private" else None
    if pend:
        ph, until = pend
        first = low.split()[0] if low.split() else ""
        if time.time() > until:
            PENDING.pop((m.from_user.id, m.chat.id), None)
        elif parse_amount(first, 1):
            PENDING.pop((m.from_user.id, m.chat.id), None)
            await COMMANDS[ph].fn(m, text)
            return True
    return False


@router.message(F.text, F.from_user)
async def on_text(m: Message):
    if m.chat.type != "private":
        await db.upsert_chat(m.chat)
        await db.run("UPDATE users SET msgs=msgs+1 WHERE id=?", (m.from_user.id,))
        if await moderation.run_filters(m):
            return
    elif (m.text or "").startswith("/start") or (m.text or "").startswith("/admin"):
        return
    await dispatch(m)
