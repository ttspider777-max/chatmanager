"""Админ-панель разработчика (только DEV_ID, только личка)."""
import asyncio
import json
import time

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
import economy as eco
import texts
from access import sub_channels
from config import *
from utils import esc, fmt, money, screen

router = Router()
router.message.filter(F.chat.type == "private", F.from_user.id == DEV_ID)
router.callback_query.filter(F.from_user.id == DEV_ID, F.data.startswith("adm:"))

PAGE = 12


class St(StatesGroup):
    wait = State()


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def B(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


HOME = [B("⬅️ Админ-панель", "adm:home")]
MAIN = [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")]


async def home_kb():
    maint = await db.get_setting("maint") == "1"
    return kb(
        [B("📊 Статистика", "adm:stats"), B("👥 Пользователи", "adm:users:0")],
        [B("💸 Выдать HC", "adm:in:give"), B("💳 Забрать HC", "adm:in:take")],
        [B("📜 Выдать облигации", "adm:in:bgive"), B("✂️ Забрать облигации", "adm:in:btake")],
        [B("🚫 Бан в боте", "adm:in:ban"), B("✅ Разбан", "adm:in:unban")],
        [B("🔎 Найти юзера", "adm:in:find"), B("🏆 Топы", "adm:tops")],
        [B("📢 Рассылка", "adm:bc"), B("🔔 Обяз. подписка", "adm:sub")],
        [B("💬 Чаты бота", "adm:chats:0"), B("🎁 Промокоды", "adm:promo")],
        [B("🏛 Добавить в бюджет", "adm:in:city"), B("🔓 Освободить бизнес", "adm:in:free")],
        [B("👋 Приветствие бота", "adm:greet"), B("🎉 Приветствие новичков", "adm:wgreet")],
        [B("🆔 ID премиум-эмодзи", "adm:in:emojiid")],
        [B("🛠 Тех. режим: " + ("ВКЛ" if maint else "выкл"), "adm:maint")],
        MAIN,
    )


async def show_home(ev):
    await screen(ev, "🛠 <b>Админ-панель</b>\nРазработчик: тебя нельзя замутить ботом в любом чате 🛡", await home_kb())


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await show_home(m)


@router.callback_query(F.data == "adm:home")
async def cb_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_home(cb)


# ---------- статистика / списки ----------
@router.callback_query(F.data == "adm:stats")
async def cb_stats(cb: CallbackQuery):
    day = time.time() - 86400
    s = dict(
        users=await db.scalar("SELECT COUNT(*) FROM users"),
        active=await db.scalar("SELECT COUNT(*) FROM users WHERE seen>?", (day,)),
        banned=await db.scalar("SELECT COUNT(*) FROM users WHERE banned=1"),
        chats=await db.scalar("SELECT COUNT(*) FROM chats WHERE active=1"),
        acc=await db.scalar("SELECT COALESCE(SUM(account),0) FROM users"),
        wal=await db.scalar("SELECT COALESCE(SUM(balance),0) FROM wallets"),
        dep=await db.scalar("SELECT COALESCE(SUM(deposit),0) FROM users"),
        bonds=await db.scalar("SELECT COALESCE(SUM(bonds),0) FROM users"),
    )
    c = await eco.city()
    await screen(cb, (
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: {fmt(s['users'])} (за сутки: {fmt(s['active'])}, в бане: {s['banned']})\n"
        f"Активных чатов: {fmt(s['chats'])}\n\n"
        f"HC на счетах: {fmt(s['acc'])}\nHC в кошельках: {fmt(s['wal'])}\nHC во вкладах: {fmt(s['dep'])}\n"
        f"Облигаций на руках: {fmt(s['bonds'])}\n\n"
        f"Бюджет города: {fmt(c['total'])} / {fmt(CITY_MAX)} (этап {eco.stage_of(c['total'])})"), kb(HOME))


@router.callback_query(F.data.startswith("adm:users:"))
async def cb_users(cb: CallbackQuery):
    p = int(cb.data.split(":")[2])
    total = await db.scalar("SELECT COUNT(*) FROM users")
    rows = await db.many(
        "SELECT id,name,username,banned, account+deposit+COALESCE((SELECT SUM(balance) FROM wallets WHERE user_id=users.id),0) AS w "
        "FROM users ORDER BY w DESC LIMIT ? OFFSET ?", (PAGE, p * PAGE))
    lines = [f"{'🚫' if r['banned'] else '•'} <code>{r['id']}</code> {texts.uname(r)}"
             f"{' @' + r['username'] if r['username'] else ''} — {fmt(r['w'])}" for r in rows]
    nav = []
    if p > 0:
        nav.append(B("◀️", f"adm:users:{p - 1}"))
    if (p + 1) * PAGE < total:
        nav.append(B("▶️", f"adm:users:{p + 1}"))
    await screen(cb, f"👥 <b>Пользователи</b> ({fmt(total)}), по богатству · стр. {p + 1}\n\n" + ("\n".join(lines) or "Пусто"),
                 kb(nav, HOME) if nav else kb(HOME))


@router.callback_query(F.data == "adm:tops")
async def cb_tops(cb: CallbackQuery):
    patrons = await db.many("SELECT id,name,username,invested,bonds FROM users WHERE invested>0 ORDER BY invested DESC LIMIT 10")
    t = await texts.top_text()
    t += "\n\n🏛 <b>Меценаты</b>\n" + ("\n".join(
        f"{i + 1}. <code>{r['id']}</code> {texts.uname(r)} — {fmt(r['invested'])}" for i, r in enumerate(patrons)) or "нет")
    await screen(cb, t, kb(HOME))


@router.callback_query(F.data.startswith("adm:chats:"))
async def cb_chats(cb: CallbackQuery):
    p = int(cb.data.split(":")[2])
    total = await db.scalar("SELECT COUNT(*) FROM chats WHERE active=1")
    rows = await db.many("SELECT * FROM chats WHERE active=1 ORDER BY joined DESC LIMIT ? OFFSET ?", (PAGE, p * PAGE))
    lines = [f"<code>{r['id']}</code> {esc(r['title'])} (добавил <code>{r['added_by'] or '—'}</code>)" for r in rows]
    nav = []
    if p > 0:
        nav.append(B("◀️", f"adm:chats:{p - 1}"))
    if (p + 1) * PAGE < total:
        nav.append(B("▶️", f"adm:chats:{p + 1}"))
    rows_kb = [nav] if nav else []
    rows_kb += [[B("🚪 Покинуть чат", "adm:in:leave")], HOME]
    await screen(cb, f"💬 <b>Чаты бота</b> ({total})\n\n" + ("\n".join(lines) or "Пусто"), kb(*rows_kb))


@router.callback_query(F.data == "adm:maint")
async def cb_maint(cb: CallbackQuery):
    await db.set_setting("maint", "0" if await db.get_setting("maint") == "1" else "1")
    await show_home(cb)


# ---------- обязательная подписка ----------
@router.callback_query(F.data == "adm:sub")
async def cb_sub(cb: CallbackQuery):
    ch = await sub_channels()
    rows = [[B(f"❌ {c['title']}", f"adm:subdel:{i}")] for i, c in enumerate(ch)]
    await screen(cb, "🔔 <b>Обязательная подписка</b>\n\n" +
                 ("Каналы:\n" + "\n".join(f"• {esc(c['title'])} — {c['link']}" for c in ch) if ch else "Не настроена.") +
                 "\n\nБот должен быть админом канала, чтобы проверять подписку.",
                 kb(*rows, [B("➕ Добавить канал", "adm:in:sub")], HOME))


@router.callback_query(F.data.startswith("adm:subdel:"))
async def cb_subdel(cb: CallbackQuery):
    ch = await sub_channels()
    i = int(cb.data.split(":")[2])
    if 0 <= i < len(ch):
        ch.pop(i)
        await db.set_setting("sub_channels", json.dumps(ch, ensure_ascii=False))
    await cb_sub(cb)


# ---------- приветствие ----------
@router.callback_query(F.data == "adm:greet")
async def cb_greet(cb: CallbackQuery):
    custom = bool(await db.get_setting("greeting"))
    nl = chr(10)
    text = ("👋 <b>Приветствие бота</b>" + nl*2 + "Сейчас: " + ("своё" if custom else "стандартное") + nl*2 +
            "Это текст над кнопками главного меню в личке. Пришли новое сообщение: "
            "форматирование (жирный, курсив, цитаты, спойлеры) и <b>премиум-эмодзи</b> сохранятся. "
            "<code>{name}</code> заменится на имя пользователя." + nl*2 +
            "⚠️ Премиум-эмодзи видят только пользователи с Telegram Premium, а отправлять их ботом Telegram "
            "разрешает лишь ботам с юзернеймом, купленным на Fragment. Если не отобразится — будет обычный эмодзи.")
    await screen(cb, text,
                 kb([B("✏️ Изменить", "adm:in:greet"), B("👁 Предпросмотр", "adm:greetview")],
                    [B("🔄 Вернуть стандартное", "adm:greetreset")], HOME))


@router.callback_query(F.data == "adm:greetview")
async def cb_greetview(cb: CallbackQuery):
    from menu import show_main
    await show_main(cb.message, cb.from_user)
    await cb.answer()


@router.callback_query(F.data == "adm:greetreset")
async def cb_greetreset(cb: CallbackQuery):
    await db.set_setting("greeting", "")
    await cb.answer("Вернул стандартное приветствие", show_alert=True)
    await cb_greet(cb)


# ---------- приветствие новых участников чатов ----------
@router.callback_query(F.data == "adm:wgreet")
async def cb_wgreet(cb: CallbackQuery):
    custom = bool(await db.get_setting("welcome_default"))
    on = await db.get_setting("welcome_on", "1") == "1"
    nl = chr(10)
    text = ("🎉 <b>Приветствие новичков в чатах</b>" + nl * 2 +
            f"Включено: {'да' if on else 'нет'} · Текст: {'свой' if custom else 'стандартный'}" + nl * 2 +
            "Показывается, когда в чат заходит новый участник. Форматирование и премиум-эмодзи сохраняются, "
            "<code>{name}</code> превращается в кликабельное имя новичка." + nl * 2 +
            "Админ чата может заменить его своим (<code>+приветствие текст</code>) или выключить (<code>-приветствие</code>).")
    await screen(cb, text, kb(
        [B("✏️ Изменить", "adm:in:wgreet"), B("👁 Предпросмотр", "adm:wgreetview")],
        [B("⛔ Выключить" if on else "✅ Включить", "adm:wgreetoggle"), B("🔄 Стандартное", "adm:wgreetreset")], HOME))


@router.callback_query(F.data == "adm:wgreetview")
async def cb_wgreetview(cb: CallbackQuery):
    from moderation import DEFAULT_WELCOME
    from aiogram.types import MessageEntity
    from utils import fill_name
    try:
        g = json.loads(await db.get_setting("welcome_default"))
        text, ents = g["text"], g["entities"]
    except Exception:
        text, ents = DEFAULT_WELCOME, []
    t, e = fill_name(text, ents, cb.from_user.first_name or "", cb.from_user.id)
    await cb.message.answer(t, entities=[MessageEntity(**x) for x in e] or None, parse_mode=None)
    await cb.answer()


@router.callback_query(F.data == "adm:wgreettoggle")
async def cb_wgreettoggle(cb: CallbackQuery):
    on = await db.get_setting("welcome_on", "1") == "1"
    await db.set_setting("welcome_on", "0" if on else "1")
    await cb_wgreet(cb)


@router.callback_query(F.data == "adm:wgreetreset")
async def cb_wgreetreset(cb: CallbackQuery):
    await db.set_setting("welcome_default", "")
    await cb.answer("Вернул стандартный текст", show_alert=True)
    await cb_wgreet(cb)


# ---------- промокоды ----------
@router.callback_query(F.data == "adm:promo")
async def cb_promo(cb: CallbackQuery):
    rows = await db.many("SELECT * FROM promos ORDER BY rowid DESC LIMIT 15")
    t = "🎁 <b>Промокоды</b>\n\n" + ("\n".join(
        f"<code>{r['code']}</code> — {fmt(r['amount'])} HC" + (f" + {r['bonds']} обл." if r['bonds'] else "") +
        f" · осталось {r['uses']}" for r in rows) or "Нет")
    await screen(cb, t, kb([B("➕ Создать", "adm:in:promo")], HOME))


# ---------- ввод данных ----------
PROMPTS = {
    "give": "💸 Выдать cur коины на счёт.\nФормат: <code>id_или_@username сумма</code>",
    "take": "💳 Забрать cur коины со счёта (если не хватает — спишется всё).\nФормат: <code>id_или_@username сумма</code>",
    "bgive": "📜 Выдать облигации.\nФормат: <code>id_или_@username количество</code>",
    "btake": "✂️ Забрать облигации.\nФормат: <code>id_или_@username количество</code>",
    "ban": "🚫 Бан в боте.\nФормат: <code>id_или_@username</code>",
    "unban": "✅ Разбан.\nФормат: <code>id_или_@username</code>",
    "find": "🔎 Введи id или @username",
    "promo": "🎁 Новый промокод.\nФормат: <code>КОД сумма_HC количество_активаций [облигаций]</code>",
    "sub": "🔔 Пришли @username канала или его id (-100…). Бот должен быть админом канала.",
    "leave": "🚪 Пришли id чата, который нужно покинуть.",
    "city": "🏛 Сколько cur коинов добавить в бюджет города?",
    "greet": "✏️ Пришли новый текст приветствия (можно с форматированием и премиум-эмодзи, {name} — имя).",
    "wgreet": "✏️ Пришли текст приветствия новичков (форматирование и премиум-эмодзи сохранятся, {name} — имя новичка).",
    "emojiid":"🆔 Пришли сообщение с премиум-эмодзи — я верну их ID (custom_emoji_id).",
    "free": "🔓 Какой бизнес освободить? Ключ: " + ", ".join(ELITE),
}


@router.callback_query(F.data.startswith("adm:in:"))
async def cb_input(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":")[2]
    await state.set_state(St.wait)
    await state.update_data(action=action)
    await screen(cb, PROMPTS[action], kb(HOME))


async def user_card(r) -> str:
    chats = await db.scalar("SELECT COUNT(*) FROM wallets WHERE user_id=?", (r["id"],))
    return (f"👤 <b>{texts.uname(r)}</b> {'@' + r['username'] if r['username'] else ''}\nID: <code>{r['id']}</code>\n"
            f"{'🚫 В БАНЕ' + chr(10) if r['banned'] else ''}"
            f"Всего: {money(await eco.wealth(r['id']))}\nСчёт: {fmt(r['account'])} · Вклад: {fmt(r['deposit'])}\n"
            f"Облигации: {fmt(r['bonds'])} · Вложено в город: {fmt(r['invested'])}\n"
            f"Кошельков: {chats} · Сообщений: {fmt(r['msgs'])}")


@router.message(StateFilter(St.wait))
async def on_input(m: Message, state: FSMContext):
    action = (await state.get_data()).get("action")
    text = (m.text or "").strip()
    parts = text.split()
    if action == "bc_msg":
        return await bc_collect(m, state)
    out = None
    try:
        if action in ("greet", "wgreet"):
            key = "greeting" if action == "greet" else "welcome_default"
            if not m.text:
                out = "⚠️ Нужен текст (можно с эмодзи и форматированием)"
            else:
                ents = [e.model_dump(exclude_none=True) for e in (m.entities or [])]
                await db.set_setting(key, json.dumps(dict(text=m.text, entities=ents), ensure_ascii=False))
                n = sum(1 for e in ents if e["type"] == "custom_emoji")
                out = f"✅ Приветствие сохранено (премиум-эмодзи: {n}). Проверь: «Предпросмотр»."
        elif action == "emojiid":
            ids = [e.custom_emoji_id for e in (m.entities or []) if e.type == "custom_emoji"]
            out = ("🆔 Найдено:" + chr(10) + chr(10).join(f"<code>{i}</code>" for i in ids)) if ids else "⚠️ В сообщении нет премиум-эмодзи"
        elif action in ("give", "take", "bgive", "btake"):
            u = await db.find_user(parts[0])
            n = int(parts[1].replace("_", ""))
            if not u or n <= 0:
                out = "Пользователь не найден или неверная сумма"
            elif action == "give":
                await eco.a_add(u["id"], n)
                out = f"✅ Выдано {money(n)} → {texts.uname(u)}"
            elif action == "take":
                have = u["account"]
                await eco.a_take(u["id"], min(n, have))
                out = f"✅ Забрано {money(min(n, have))} у {texts.uname(u)}"
            elif action == "bgive":
                await db.run("UPDATE users SET bonds=bonds+? WHERE id=?", (n, u["id"]))
                out = f"✅ Выдано облигаций: {n} → {texts.uname(u)}"
            else:
                await db.run("UPDATE users SET bonds=MAX(bonds-?,0) WHERE id=?", (n, u["id"]))
                out = f"✅ Забрано облигаций: {n} у {texts.uname(u)}"
        elif action in ("ban", "unban", "find"):
            u = await db.find_user(parts[0])
            if not u:
                out = "Пользователь не найден (он должен был хоть раз написать боту)"
            elif action == "find":
                out = await user_card(u)
            elif u["id"] == DEV_ID:
                out = "Себя банить нельзя 🙂"
            else:
                await db.run("UPDATE users SET banned=? WHERE id=?", (1 if action == "ban" else 0, u["id"]))
                out = f"{'🚫 Забанен' if action == 'ban' else '✅ Разбанен'}: {texts.uname(u)}"
        elif action == "promo":
            code, amount, uses = parts[0].upper(), int(parts[1]), int(parts[2])
            bonds = int(parts[3]) if len(parts) > 3 else 0
            await db.run("INSERT OR REPLACE INTO promos(code,amount,bonds,uses) VALUES(?,?,?,?)", (code, amount, bonds, uses))
            out = f"✅ Промокод <code>{esc(code)}</code>: {fmt(amount)} HC" + (f" + {bonds} обл." if bonds else "") + f", активаций: {uses}"
        elif action == "sub":
            chat = await m.bot.get_chat(parts[0] if parts[0].startswith("@") else int(parts[0]))
            me = await m.bot.get_chat_member(chat.id, m.bot.id)
            link = f"https://t.me/{chat.username}" if chat.username else await m.bot.export_chat_invite_link(chat.id)
            ch = await sub_channels()
            ch.append(dict(id=chat.id, title=chat.title or str(chat.id), link=link))
            await db.set_setting("sub_channels", json.dumps(ch, ensure_ascii=False))
            out = f"✅ Канал «{esc(chat.title)}» добавлен." + ("" if me.status == "administrator" else
                                                              "\n⚠️ Бот не админ канала — подписку проверить не сможет!")
        elif action == "leave":
            cid = int(parts[0])
            await m.bot.leave_chat(cid)
            await db.run("UPDATE chats SET active=0 WHERE id=?", (cid,))
            out = "🚪 Чат покинут"
        elif action == "city":
            n = int(parts[0])
            await eco.city_add(n)
            out = f"✅ В бюджет города добавлено {money(n)}"
        elif action == "free":
            if parts[0] not in ELITE:
                out = "Нет такого ключа"
            else:
                await db.run("UPDATE elite SET owner_id=NULL, until=0 WHERE key=?", (parts[0],))
                out = "✅ Бизнес освобождён"
    except (IndexError, ValueError):
        out = "⚠️ Неверный формат. Попробуй ещё раз:\n" + PROMPTS.get(action, "")
    except Exception as e:
        out = f"⚠️ Ошибка: {esc(e)}"
    await m.answer(out or "Готово", reply_markup=kb(HOME))
    if out and not out.startswith("⚠️"):
        await state.clear()


# ---------- рассылка ----------
@router.callback_query(F.data == "adm:bc")
async def cb_bc(cb: CallbackQuery):
    u = await db.scalar("SELECT COUNT(*) FROM users WHERE banned=0")
    c = await db.scalar("SELECT COUNT(*) FROM chats WHERE active=1")
    await screen(cb, f"📢 <b>Рассылка</b>\nКому отправить?\nПользователей: {u} · Чатов: {c}",
                 kb([B("👤 Пользователям", "adm:bct:users"), B("💬 В чаты", "adm:bct:chats")],
                    [B("📣 Всем", "adm:bct:all")], HOME))


@router.callback_query(F.data.startswith("adm:bct:"))
async def cb_bct(cb: CallbackQuery, state: FSMContext):
    await state.set_state(St.wait)
    await state.update_data(action="bc_msg", target=cb.data.split(":")[2])
    await screen(cb, "Пришли сообщение для рассылки (текст, фото, видео — что угодно, перешлю как есть).", kb(HOME))


async def bc_collect(m: Message, state: FSMContext):
    await state.update_data(src_chat=m.chat.id, src_msg=m.message_id)
    d = await state.get_data()
    await m.answer(f"Отправить это сообщение ({d['target']})?", reply_markup=kb([B("✅ Отправить", "adm:bcgo"), B("✖️ Отмена", "adm:home")]))


@router.callback_query(F.data == "adm:bcgo")
async def cb_bcgo(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    if not d.get("src_msg"):
        return await cb.answer("Нет сообщения", show_alert=True)
    ids = []
    if d["target"] in ("users", "all"):
        ids += [r[0] for r in await db.many("SELECT id FROM users WHERE banned=0")]
    if d["target"] in ("chats", "all"):
        ids += [r[0] for r in await db.many("SELECT id FROM chats WHERE active=1")]
    await cb.message.edit_text(f"📢 Рассылка запущена: {len(ids)} получателей…")
    ok = fail = 0
    for cid in ids:
        try:
            await cb.bot.copy_message(cid, d["src_chat"], d["src_msg"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await cb.message.answer(f"📢 Готово: доставлено {ok}, не доставлено {fail}", reply_markup=kb(HOME))
    await cb.answer()
