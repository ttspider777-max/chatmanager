"""🎄 Новогоднее обновление: ограбить, доход, подарок и случайные реплики бота в чате."""
import asyncio
import random
import time
from collections import defaultdict, deque

from aiogram.types import BufferedInputFile, Message

import db
import economy as eco
import moderation
import newyear_img
from config import *
from registry import cmd
from utils import esc, fmt, money, mention

# --- настройки (крути под себя) ---
ROB_COOLDOWN = 30 * 60        # как часто можно грабить
ROB_PROTECT = 20 * 60         # после ограбления жертву 20 минут не трогают
ROB_MIN_VICTIM = 1_000        # меньше этого в кошельке — грабить нет смысла
ROB_MIN_THIEF = 500           # нужно иметь хоть что-то, чтобы заплатить штраф
ROB_CHANCE = 0.55
ROB_PCT = (0.05, 0.20)        # доля от кошелька жертвы
ROB_CAP = 100_000             # максимум за одно ограбление
FINE_PCT = 0.10
FINE_CAP = 20_000
GIFT_COOLDOWN = 6 * 3600
GIFT_RANGE = (500, 3_000)
CHATTER_CHANCE = 0.04         # шанс отреагировать на обычное сообщение
CHATTER_GAP = 8 * 60          # не чаще раза в 8 минут на чат

# ---------- кулдауны ----------
async def cd_left(uid, cid, kind, length) -> float:
    ts = await db.scalar("SELECT ts FROM cooldowns WHERE user_id=? AND chat_id=? AND kind=?", (uid, cid, kind))
    return max(0.0, ts + length - time.time())


async def cd_set(uid, cid, kind):
    await db.run("INSERT INTO cooldowns(user_id,chat_id,kind,ts) VALUES(?,?,?,?) "
                 "ON CONFLICT(user_id,chat_id,kind) DO UPDATE SET ts=excluded.ts", (uid, cid, kind, time.time()))


def left_txt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600} ч {sec % 3600 // 60} мин" if sec >= 3600 else f"{sec // 60} мин {sec % 60} с"


# ---------- аватарки ----------
async def avatar_of(bot, uid):
    try:
        photos = await bot.get_user_profile_photos(uid, limit=1)
        if not photos.total_count:
            return None
        buf = await bot.download(photos.photos[0][-1].file_id)
        return newyear_img.load_avatar(buf.read())
    except Exception:
        return None


# ---------- ограбление ----------
@cmd("ограбить", "грабить", "украсть", chat_only=True)
async def c_rob(m: Message, args: str):
    thief = m.from_user
    t = await moderation.resolve_target(m, args)
    if not t:
        return await m.reply("🎅 Кого грабим? Ответь на сообщение жертвы: <code>ограбить</code> "
                             "(или <code>ограбить @user</code>)")
    vid, vname, _ = t
    if vid == thief.id:
        return await m.reply("Самого себя грабить — это уже налоговая 🙃")
    if vid == m.bot.id:
        return await m.reply("У меня нет кошелька, я живу на ёлочных шариках 🎄")
    if vid == DEV_ID:
        return await m.reply("🛡 Разработчика охраняет сам Дед Мороз — не получится.")
    cid = m.chat.id
    left = await cd_left(thief.id, cid, "rob", ROB_COOLDOWN)
    if left:
        return await m.reply(f"🕵️ Полиция ещё ищет тебя. Следующее ограбление через {left_txt(left)}")
    prot = await cd_left(vid, cid, "robbed", ROB_PROTECT)
    if prot:
        return await m.reply(f"🎁 {mention(vid, vname)} только что ограбили — он под защитой ещё {left_txt(prot)}")
    vbal = await eco.ensure_wallet(vid, cid)
    tbal = await eco.ensure_wallet(thief.id, cid)
    if vbal < ROB_MIN_VICTIM:
        return await m.reply(f"У {mention(vid, vname)} в кошельке чата меньше {fmt(ROB_MIN_VICTIM)} — нечего брать")
    if tbal < ROB_MIN_THIEF:
        return await m.reply(f"Нужно хотя бы {money(ROB_MIN_THIEF)} в кошельке, чтобы заплатить штраф, если поймают")
    await cd_set(thief.id, cid, "rob")

    if random.random() < ROB_CHANCE:
        amt = max(1, min(ROB_CAP, int(vbal * random.uniform(*ROB_PCT))))
        if not await eco.w_take(vid, cid, amt):          # жертва успела потратить — атомарная проверка
            return await m.reply("Жертва успела спрятать деньги 🫥")
        await eco.w_add(thief.id, cid, amt)
        await cd_set(vid, cid, "robbed")
        t_ava, v_ava = await asyncio.gather(avatar_of(m.bot, thief.id), avatar_of(m.bot, vid))
        png = await asyncio.to_thread(
            newyear_img.render, thief.full_name, vname, fmt(amt), CUR, t_ava, v_ava, random.randint(0, 10**6),
            thief_username=thief.username or "", pct=f"{amt / vbal * 100:.1f}%".replace(".0%", "%"),
            victim_before=fmt(vbal), thief_balance=fmt(tbal + amt))
        cap = (f"🎅 {mention(thief.id, thief.full_name)} ограбил {mention(vid, vname)} "
               f"на <b>{money(amt)}</b>! 🎄")
        return await m.reply_photo(BufferedInputFile(png, "robbery.png"), caption=cap)

    fine = min(FINE_CAP, max(100, int(tbal * FINE_PCT)), tbal)
    if await eco.w_take(thief.id, cid, fine):
        await eco.w_add(vid, cid, fine)
    await m.reply(f"🚔 {mention(thief.id, thief.full_name)} попался с мешком на плече!\n"
                  f"Штраф <b>{money(fine)}</b> уходит {mention(vid, vname)} за моральный ущерб.")


# ---------- доход ----------
@cmd("доход", "мой доход", chat_only=True)
async def c_income(m: Message, args: str):
    uid = m.from_user.id
    rows = await db.many("SELECT item, ts FROM props WHERE user_id=?", (uid,))
    if not rows:
        return await m.reply("📉 Дохода пока нет. Загляни в «магазин» — купи ларёк или шахту.")
    per_hour = pending = 0
    for r in rows:
        inc = SHOP[r["item"]][4]
        per_hour += inc
        pending += int(inc * min((time.time() - r["ts"]) / 3600, 24))
    full_in = max(0, 24 - max((time.time() - r["ts"]) / 3600 for r in rows))
    txt = (f"💸 <b>Твой доход</b>\n\n"
           f"⏱ В час: <b>{money(per_hour)}</b>\n"
           f"📆 В сутки: <b>{money(per_hour * 24)}</b>\n"
           f"🎁 Накопилось, можно забрать: <b>{money(pending)}</b>\n")
    if full_in:
        txt += f"🧊 До полного накопления (24 ч): {left_txt(full_in * 3600)}\n"
    else:
        txt += "⚠️ Накопление уже упёрлось в лимит 24 ч — собирай!\n"
    owned = [f"{e['emoji']} {e['name']}: {money(st['earned'])}" for k, e in ELITE.items()
             if (st := await eco.elite_state(k)) and st["owner_id"] == uid]
    if owned:
        txt += "\n💠 <b>Элитные бизнесы</b> (заработано всего)\n" + "\n".join(owned) + "\n"
    await m.reply(txt + "\nЗабрать: <code>собрать</code>")


# ---------- новогодний подарок ----------
@cmd("подарок", "ёлка", "елка", chat_only=True)
async def c_gift(m: Message, args: str):
    uid, cid = m.from_user.id, m.chat.id
    left = await cd_left(uid, cid, "gift", GIFT_COOLDOWN)
    if left:
        return await m.reply(f"🎄 Под ёлкой пока пусто. Загляни через {left_txt(left)}")
    await cd_set(uid, cid, "gift")
    if random.random() < 0.05:
        amt, title = GIFT_RANGE[1] * 4, "🌟 Дед Мороз оставил ДЖЕКПОТ!"
    else:
        amt, title = random.randint(*GIFT_RANGE), "🎁 Под ёлкой нашёлся подарок!"
    await eco.w_add(uid, cid, amt)
    await m.reply(f"{title}\n+<b>{money(amt)}</b> в кошелёк этого чата")


# ---------- болтовня бота ----------
KIND = [
    "ты классный(ая), знай это 🎄", "с наступающим тебя! ❄️", "ты лучший(ая) в этом чате 💛",
    "желаю тебе кучу cur коинов и ни одного ограбления 🎅", "ты просто золото 🌟", "спасибо, что ты с нами 🤗",
    "пусть Дед Мороз принесёт тебе всё, что ты хочешь 🎁", "ты украшаешь этот чат лучше любой гирлянды ✨",
    "улыбнись, сегодня почти Новый год! ⛄", "ты молодец, правда 👏", "ты мой любимый(ая) собеседник 💖",
    "пусть в новом году все получится 🥂", "держи виртуальный мандаринчик 🍊", "ты очень крутой(ая) человек 😎",
]
RUDE = [
    "ну ты и дебил, конечно 🤡", "иди ты нахер со своими сообщениями 😂", "заткнись уже, а? 🙃",
    "ты чё, совсем охренел(а)? 😳", "пошёл(пошла) ты в жопу, снеговик 🥶", "блин, ну ты и тупишь 🤦",
    "хватит нести хрень 💩", "ты как всегда — мастер(ица) хуйни 🏆", "да ты вообще офигел(а) 😤",
    "бля, ну ты даёшь 🤣", "отвали, я кормлю оленей 🦌", "сам(а) иди нахуй, я только ёлку наряжаю 🎄",
    "ты реально долбоёб(ка) года, поздравляю 🎖", "ну и рожа у тебя, как у замёрзшего снеговика ⛄",
    "ебать ты зануда(а) 🥱", "нахрена ты это написал(а)? 🤔", "свали в туман, Дед Мороз всё видит 🎅",
]
_recent: dict[int, deque] = defaultdict(lambda: deque(maxlen=15))   # chat -> (uid, name)
_last_talk: dict[int, float] = {}


async def chatter_on(cid: int) -> bool:
    return await db.get_setting(f"chatter:{cid}", "1") == "1"


def _phrase(uid: int) -> str:
    # разработчика бот не ругает
    return random.choice(KIND if uid == DEV_ID or random.random() < 0.5 else RUDE)


async def maybe_chatter(m: Message):
    """Вызывается на каждое обычное сообщение в группе. Иногда бот сам что-то говорит."""
    cid = m.chat.id
    u = m.from_user
    if u.is_bot:
        return
    _recent[cid].append((u.id, u.full_name))
    if random.random() > CHATTER_CHANCE or time.time() - _last_talk.get(cid, 0) < CHATTER_GAP:
        return
    if not await chatter_on(cid):
        return
    _last_talk[cid] = time.time()
    try:
        if random.random() < 0.5:
            await m.reply(_phrase(u.id).capitalize())
        else:
            uid, name = random.choice(list(_recent[cid]))
            await m.answer(f"{mention(uid, name)}, {_phrase(uid)}")
    except Exception:
        pass


@cmd("болтовня", mod=True)
async def c_chatter(m: Message, args: str):
    if not await moderation.is_mod(m.bot, m.chat.id, m.from_user.id):
        return
    a = args.strip().lower()
    if a in ("вкл", "on", "1"):
        await db.set_setting(f"chatter:{m.chat.id}", "1")
        return await m.reply("🎅 Болтовня бота включена")
    if a in ("выкл", "off", "0"):
        await db.set_setting(f"chatter:{m.chat.id}", "0")
        return await m.reply("🤐 Болтовня бота выключена")
    await m.reply(f"Болтовня сейчас: {'включена' if await chatter_on(m.chat.id) else 'выключена'}\n"
                  "<code>болтовня вкл</code> / <code>болтовня выкл</code>")
