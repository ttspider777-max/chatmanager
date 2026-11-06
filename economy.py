"""Вся логика денег. Операции списания атомарны (UPDATE ... WHERE balance>=?)."""
import asyncio
import time

import db
from config import *

on_stage = None  # async def (old:int, new:int)


def now() -> float:
    return time.time()


# ---------- кошельки и счёт ----------
async def ensure_wallet(uid, cid) -> int:
    await db.run("INSERT OR IGNORE INTO wallets(user_id,chat_id,balance) VALUES(?,?,?)", (uid, cid, START_BALANCE))
    return await db.scalar("SELECT balance FROM wallets WHERE user_id=? AND chat_id=?", (uid, cid))


async def w_take(uid, cid, amt) -> bool:
    return await db.run("UPDATE wallets SET balance=balance-? WHERE user_id=? AND chat_id=? AND balance>=?",
                        (amt, uid, cid, amt)) == 1


async def w_add(uid, cid, amt):
    await ensure_wallet(uid, cid)
    await db.run("UPDATE wallets SET balance=balance+? WHERE user_id=? AND chat_id=?", (amt, uid, cid))


async def a_take(uid, amt) -> bool:
    return await db.run("UPDATE users SET account=account-? WHERE id=? AND account>=?", (amt, uid, amt)) == 1


async def a_add(uid, amt):
    await db.run("UPDATE users SET account=account+? WHERE id=?", (amt, uid))


async def pay_from(uid, cid, amt) -> bool:
    """В чате платим из кошелька чата, в личке — со счёта."""
    return await (a_take(uid, amt) if cid is None else w_take(uid, cid, amt))


async def refund_to(uid, cid, amt):
    await (a_add(uid, amt) if cid is None else w_add(uid, cid, amt))


async def source_balance(uid, cid) -> int:
    if cid is None:
        return await db.scalar("SELECT account FROM users WHERE id=?", (uid,))
    return await ensure_wallet(uid, cid)


async def wealth(uid) -> int:
    await accrue(uid)
    return await db.scalar(
        "SELECT account+deposit+COALESCE((SELECT SUM(balance) FROM wallets WHERE user_id=users.id),0) "
        "FROM users WHERE id=?", (uid,))


# ---------- бюджет города ----------
def stage_of(total: int) -> int:
    return sum(1 for s in STAGES if total >= s[0])


async def city():
    return await db.one("SELECT * FROM city WHERE id=1")


async def city_room() -> int:
    return max(0, CITY_MAX - (await city())["total"])


async def city_add(amount: int, players: int = 0, bonds: int = 0):
    await db.run("UPDATE city SET total=MIN(?, total+?), players_total=players_total+?, bonds_sold=bonds_sold+? "
                 "WHERE id=1", (CITY_MAX, amount, players, bonds))
    row = await city()
    st = stage_of(row["total"])
    if st > row["announced"]:
        old = row["announced"]
        if await db.run("UPDATE city SET announced=? WHERE id=1 AND announced<?", (st, st)) and on_stage:
            asyncio.create_task(on_stage(old, st))


async def contribute(uid, amount: int, bonds: int = 0):
    await db.run("UPDATE users SET invested=invested+?, bonds_bought=bonds_bought+? WHERE id=?",
                 (amount, bonds, uid))
    await city_add(amount, players=amount, bonds=bonds)


async def invest(uid, cid, amount: int):
    room = await city_room()
    if room <= 0:
        return False, "Бюджет города уже заполнен 🎉"
    if amount > room:
        return False, f"В бюджет влезает ещё максимум {amount_fmt(room)}"
    if not await pay_from(uid, cid, amount):
        return False, "Недостаточно cur коинов" + ("" if cid else " на счёте")
    await contribute(uid, amount)
    return True, f"🏛 Ты вложил {amount_fmt(amount)} в бюджет города. Спасибо, меценат!"


async def buy_bonds(uid, cid, n: int):
    cost = n * BOND_PRICE
    room = await city_room()
    if room < cost:
        return False, "Бюджет города заполнен — облигации больше не продаются" if room <= 0 else \
            f"В бюджет влезает не больше {room // BOND_PRICE} облигаций"
    if not await pay_from(uid, cid, cost):
        return False, f"Не хватает cur коинов: нужно {amount_fmt(cost)}" + ("" if cid else " (на счёте)")
    await contribute(uid, cost, bonds=n)
    await db.run("UPDATE users SET bonds=bonds+? WHERE id=?", (n, uid))
    return True, f"📜 Куплено облигаций: {n} за {amount_fmt(cost)}. Коины ушли в бюджет города."


def amount_fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ") + f" {CUR}"


# ---------- элитные бизнесы ----------
async def elite_state(key):
    r = await db.one("SELECT * FROM elite WHERE key=?", (key,))
    if r and r["owner_id"] and r["until"] > now():
        return r
    return None


async def pay_elite(key, base: float, pct: float):
    """Комиссия владельцу структуры: 13% налога уходит в бюджет города, остальное на счёт владельца."""
    amt = int(base * pct)
    if amt <= 0:
        return
    st = await elite_state(key)
    if not st:
        return
    tax = int(amt * TAX)
    await a_add(st["owner_id"], amt - tax)
    await db.run("UPDATE elite SET earned=earned+? WHERE key=?", (amt - tax, key))
    if tax:
        await city_add(tax)


async def rent_elite(uid, key):
    e = ELITE[key]
    st = await elite_state(key)
    if st and st["owner_id"] != uid:
        return False, "Этот бизнес уже арендован другим игроком"
    if not await db.run("UPDATE users SET bonds=bonds-? WHERE id=? AND bonds>=?", (e["cost"], uid, e["cost"])):
        have = await db.scalar("SELECT bonds FROM users WHERE id=?", (uid,))
        return False, f"Не хватает облигаций: нужно {e['cost']}, у тебя {have}"
    start = st["until"] if st else now()
    await db.run("UPDATE elite SET owner_id=?, until=? WHERE key=?", (uid, start + RENT_DAYS * 86400, key))
    verb = "продлена" if st else "оформлена"
    return True, f"{e['emoji']} Аренда «{e['name']}» {verb} на {RENT_DAYS} дней!"


async def expire_elite():
    """Освобождает просроченные бизнесы, возвращает [(key, owner_id)]."""
    rows = await db.many("SELECT key, owner_id FROM elite WHERE owner_id IS NOT NULL AND until<=?", (now(),))
    for r in rows:
        await db.run("UPDATE elite SET owner_id=NULL, until=0 WHERE key=?", (r["key"],))
    return [(r["key"], r["owner_id"]) for r in rows]


# ---------- вклады ----------
async def accrue(uid):
    u = await db.one("SELECT deposit, deposit_ts FROM users WHERE id=?", (uid,))
    if not u or u["deposit"] <= 0:
        return
    hours = min((now() - u["deposit_ts"]) / 3600, 168)
    rate = DEPOSIT_RATE_DAY * (BANK_BONUS if await elite_state("bank") else 1)
    interest = int(u["deposit"] * rate * hours / 24)
    if interest > 0:
        await db.run("UPDATE users SET deposit=deposit+?, deposit_ts=? WHERE id=?", (interest, now(), uid))


async def deposit_in(uid, cid, amount):
    await accrue(uid)
    if not await w_take(uid, cid, amount):
        return False, "Недостаточно cur коинов в кошельке"
    fee = int(amount * DEPOSIT_FEE)
    await db.run("UPDATE users SET deposit=deposit+?, deposit_ts=CASE WHEN deposit=0 THEN ? ELSE deposit_ts END "
                 "WHERE id=?", (amount - fee, now(), uid))
    await pay_elite("bank", fee, 1.0)
    return True, f"🏦 Во вклад положено {amount_fmt(amount - fee)} (комиссия {amount_fmt(fee)})"


async def deposit_out(uid, cid, amount):
    await accrue(uid)
    if await db.run("UPDATE users SET deposit=deposit-? WHERE id=? AND deposit>=?", (amount, uid, amount)) != 1:
        return False, "Столько нет во вкладе"
    await w_add(uid, cid, amount)
    return True, f"🏦 Со вклада в кошелёк чата: {amount_fmt(amount)}"


# ---------- переводы ----------
async def transfer(frm, to, cid, amount):
    fee = max(1, int(amount * TRANSFER_FEE))
    if not await w_take(frm, cid, amount + fee):
        return False, f"Недостаточно: нужно {amount_fmt(amount + fee)} (комиссия {int(TRANSFER_FEE * 100)}%)", fee
    await w_add(to, cid, amount)
    await pay_elite("bank", fee, 1.0)
    return True, "", fee


# ---------- бонус / промо ----------
async def daily_bonus(uid, cid):
    ts = await db.scalar("SELECT bonus_ts FROM users WHERE id=?", (uid,))
    left = ts + 86400 - now()
    if left > 0:
        return False, f"Бонус уже получен. Следующий через {int(left // 3600)} ч {int(left % 3600 // 60)} мин"
    await db.run("UPDATE users SET bonus_ts=? WHERE id=?", (now(), uid))
    await w_add(uid, cid, DAILY_BONUS)
    return True, f"🎁 Ежедневный бонус: +{amount_fmt(DAILY_BONUS)} в кошелёк этого чата"


async def redeem_promo(uid, code):
    code = code.strip().upper()
    p = await db.one("SELECT * FROM promos WHERE code=?", (code,))
    if not p or p["uses"] <= 0:
        return False, "Промокод не найден или закончился"
    if await db.one("SELECT 1 FROM promo_used WHERE code=? AND user_id=?", (code, uid)):
        return False, "Ты уже активировал этот промокод"
    if await db.run("UPDATE promos SET uses=uses-1 WHERE code=? AND uses>0", (code,)) != 1:
        return False, "Промокод закончился"
    await db.run("INSERT INTO promo_used(code,user_id) VALUES(?,?)", (code, uid))
    if p["amount"]:
        await a_add(uid, p["amount"])
    if p["bonds"]:
        await db.run("UPDATE users SET bonds=bonds+? WHERE id=?", (p["bonds"], uid))
    got = []
    if p["amount"]:
        got.append(amount_fmt(p["amount"]) + " на счёт")
    if p["bonds"]:
        got.append(f"{p['bonds']} облигаций")
    return True, "🎁 Промокод активирован: " + ", ".join(got)


# ---------- магазин ----------
async def buy_item(uid, cid, code):
    item = SHOP.get(code)
    if not item:
        return False, "Нет такого товара. Список: магазин"
    cat, emoji, name, price, _ = item
    if await db.one("SELECT 1 FROM props WHERE user_id=? AND item=?", (uid, code)):
        return False, "У тебя это уже есть"
    if not await w_take(uid, cid, price):
        return False, f"Не хватает cur коинов: нужно {amount_fmt(price)}"
    await db.run("INSERT INTO props(user_id,item,ts) VALUES(?,?,?)", (uid, code, now()))
    key, pct = SHOP_COMMISSION[cat]
    await pay_elite(key, price, pct)
    return True, f"{emoji} Куплено: {name} за {amount_fmt(price)}. Доход: «собрать»"


async def collect(uid, cid):
    rows = await db.many("SELECT item, ts FROM props WHERE user_id=?", (uid,))
    if not rows:
        return False, "У тебя пока ничего нет. Загляни в «магазин»"
    total = 0
    for r in rows:
        hours = min((now() - r["ts"]) / 3600, 24)
        total += int(SHOP[r["item"]][4] * hours)
        await db.run("UPDATE props SET ts=? WHERE user_id=? AND item=?", (now(), uid, r["item"]))
    if total <= 0:
        return False, "Пока нечего собирать, загляни позже"
    await w_add(uid, cid, total)
    return True, f"💼 Собрано дохода: +{amount_fmt(total)} (копится до 24 ч)"
