from datetime import datetime

import db
import economy as eco
from config import *
from utils import bar, esc, fmt, money


def uname(r) -> str:
    return esc(r["name"] or (("@" + r["username"]) if r["username"] else r["id"]))


async def account_text(uid: int) -> str:
    await eco.accrue(uid)
    u = await db.get_user(uid)
    w = await db.one("SELECT COALESCE(SUM(balance),0) s, COUNT(*) n FROM wallets WHERE user_id=?", (uid,))
    return (
        "💰 <b>Мой счёт</b>\n\n"
        f"💳 На счёте: <b>{money(u['account'])}</b>\n"
        f"📜 Облигации: <b>{fmt(u['bonds'])}</b>\n"
        f"👛 В кошельках чатов: <b>{money(w['s'])}</b> (чатов: {w['n']})\n"
        f"🏦 Во вкладах: <b>{money(u['deposit'])}</b>\n"
        f"🏛 Вложено в город: <b>{money(u['invested'])}</b>\n\n"
        "Счёт общий для всех чатов: сюда капает доход элитных бизнесменов.\n"
        "Снять в кошелёк — в любом чате с ботом: <code>счет снять 100</code>"
    )


async def top_text() -> str:
    rich = await db.many(
        "SELECT id,name,username, account+deposit+COALESCE((SELECT SUM(balance) FROM wallets WHERE user_id=users.id),0) AS w "
        "FROM users WHERE banned=0 ORDER BY w DESC LIMIT 10")
    act = await db.many("SELECT id,name,username,msgs FROM users WHERE banned=0 AND msgs>0 ORDER BY msgs DESC LIMIT 10")
    medals = ["🥇", "🥈", "🥉"]

    def pos(i):
        return medals[i] if i < 3 else f"{i + 1}."

    t = "🏆 <b>Топ богачей</b>\n<i>все чаты: кошельки + вклады + счёт</i>\n\n"
    t += "\n".join(f"{pos(i)} {uname(r)} — {fmt(r['w'])}" for i, r in enumerate(rich)) or "Пока пусто"
    t += "\n\n👥 <b>Топ пользователей</b>\n<i>по активности в чатах</i>\n\n"
    t += "\n".join(f"{pos(i)} {uname(r)} — {fmt(r['msgs'])} сообщ." for i, r in enumerate(act)) or "Пока пусто"
    return t


async def city_text() -> str:
    c = await eco.city()
    total = c["total"]
    opened = eco.stage_of(total)
    t = "🏛 <b>Бюджет города</b>\n\n"
    if opened >= len(STAGES):
        t += f"Все этапы открыты ({opened} из {len(STAGES)}) 🎉\n"
    else:
        thr, name, nov = STAGES[opened]
        t += f"Сейчас этап <b>{opened + 1}</b> из {len(STAGES)}: «{name}»\n"
    t += (f"Собрано: <b>{fmt(total)}</b> / {fmt(CITY_MAX)} {CUR}\n"
          f"{bar(total / CITY_MAX)} {total / CITY_MAX * 100:.2f}%\n")
    if opened < len(STAGES):
        thr, name, nov = STAGES[opened]
        t += f"Этап {opened + 1} откроется при {fmt(thr)} (осталось {fmt(thr - total)})\nНовинка: {nov}\n"
    t += (
        "\n<b>Откуда деньги:</b>\n"
        f"• взносы игроков — облигации по {fmt(BOND_PRICE)} {CUR} за штуку\n"
        f"• налог {int(TAX * 100)}% с доходов элитных бизнесов\n\n"
        "Из бюджета деньги не возвращаются: так коины не обесцениваются, "
        "а каждый заполненный этап открывает новинку во всех чатах.\n\n"
        "<b>Меценаты:</b>\n")
    top = await db.many("SELECT id,name,username,invested FROM users WHERE invested>0 ORDER BY invested DESC LIMIT 10")
    if top:
        t += "\n".join(f"{i + 1}. {uname(r)} — {money(r['invested'])}" for i, r in enumerate(top))
    else:
        t += "Пока никто не вкладывался — стань первым."
    t += (f"\n\nВсего вложено: <b>{money(c['players_total'])}</b>\n"
          f"Облигаций продано: <b>{fmt(c['bonds_sold'])}</b>\n\n"
          "Вложить можно в любом чате с ботом: <code>бюджет 1000</code>")
    return t


async def bonds_text(uid: int) -> str:
    u = await db.get_user(uid)
    return (
        "📜 <b>Облигации города</b>\n\n"
        f"Цена: <b>{fmt(BOND_PRICE)} {CUR}</b> за штуку\n"
        f"У тебя облигаций: <b>{fmt(u['bonds'])}</b>\n"
        f"На счёте: {money(u['account'])}\n\n"
        "За облигации берут в аренду элитные бизнесы — казино, банк, автосалон. "
        f"Самый доступный стоит {fmt(min(e['cost'] for e in ELITE.values()))} облигаций.\n"
        "Хелы за облигации уходят в бюджет города и обратно не продаются.\n\n"
        "<b>Купить облигации:</b>\n"
        "• в чате, из кошелька: <code>купить облигации 5</code>\n"
        "• в личке бота — со счёта, кнопками ниже"
    )


async def elite_text() -> str:
    t = (f"💠 <b>Элитные бизнесы — по одному на весь бот</b>\n"
         f"Аренда на {RENT_DAYS} дней за облигации, налог {int(TAX * 100)}% с дохода.\n")
    for key, e in ELITE.items():
        st = await eco.elite_state(key)
        t += f"\n{e['emoji']} <b>{e['name']}</b> — {fmt(e['cost'])} облигаций\n   {e['desc']}\n"
        if st:
            owner = await db.get_user(st["owner_id"])
            until = datetime.fromtimestamp(st["until"]).strftime("%d.%m %H:%M")
            t += f"   🔒 занят: {uname(owner)} до {until}\n"
        else:
            t += "   ✅ свободен\n"
    return t


def help_text() -> str:
    return (
        "📖 <b>Все команды бота</b> (пиши в чате, можно без «/»)\n\n"
        "<b>💰 Экономика</b>\n"
        "баланс — кошелёк этого чата и счёт\n"
        "бонус — ежедневный подарок\n"
        "счет — общий счёт · <code>счет снять 100</code>\n"
        "перевод 100 (ответом на сообщение) — комиссия 3%\n"
        "вклад 1000 · <code>вклад снять 500</code> — 2% в сутки\n"
        "купить облигации 5 · облигации\n"
        "бюджет — город · <code>бюджет 1000</code> — вложить\n"
        "бизнесы — элитные бизнесы\n"
        "магазин · купить b1 · имущество · собрать\n"
        "доход — сколько приносит имущество и что накопилось\n"
        "топ · топ чата · профиль\n"
        "промо КОД — активировать промокод\n\n"
        "<b>🎄 Новогоднее</b>\n"
        "ограбить (ответом на сообщение или @user) — шанс 55%, добыча до 20% кошелька жертвы, "
        "картинка с гирляндами; раз в 30 мин\n"
        "подарок — подарок из-под ёлки раз в 6 ч\n"
        "болтовня вкл/выкл — бот иногда сам пишет и отмечает людей (для админов)\n\n"
        "<b>🎮 Игры</b> (ставка: число, 5к, 2кк, все)\n"
        "футбол · баскетбол · дартс · боулинг · слоты · кости ставка\n"
        "21 ставка — блэкджек\n"
        "краш ставка — забери до взрыва\n"
        "мины ставка [мин 1-20] — поле 5×5\n"
        "монета ставка орёл/решка\n"
        "рулетка ставка красное/чёрное/зеро/число (после 1-го этапа города)\n\n"
        "<b>🛡 Модерация</b> (админы чата и тот, кто добавил бота)\n"
        "бан · разбан (вернёт человека ссылкой) · баны · кик · мут 10м · размут · варн · снять варн · варны\n"
        "закрепить · открепить · удалить · очистить 20\n"
        "+правила текст · правила · +приветствие текст · -приветствие · приветствие сброс\n"
        "антиссылки вкл/выкл · антифлуд вкл/выкл · настройки\n"
        "+оп @канал — обязательная подписка · оп — список · -оп @канал / -оп все\n"
        "репорт (ответом) · админы · инфо\n\n"
        "ℹ️ В группе дай боту права админа, а в @BotFather отключи Group Privacy — "
        "иначе бот не увидит обычные сообщения."
    )
