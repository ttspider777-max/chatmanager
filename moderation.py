"""Модерация чатов + события входа/выхода бота. Разработчик (DEV_ID) неприкасаем."""
import json
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (CallbackQuery, ChatMemberUpdated, ChatPermissions, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, MessageEntity)

import db
from access import is_chat_admin, is_mod
from config import DEV_ID, WARN_LIMIT
from registry import cmd
from utils import esc, fill_name, fmt_dur, mention, parse_duration

router = Router()
DEFAULT_WELCOME = ("👋 Добро пожаловать, {name}!\n\n"
                   "Я чат-менеджер Cursed: играй, копи cur коины и вкладывай в бюджет города.\n"
                   "Все команды — напиши «команды».")
URL_RE = re.compile(r"(https?://|www\.|t\.me/|@\w+\.\w{2,}|\b\w+\.(com|ru|io|me|org|net|xyz)\b)", re.I)
flood: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=6))


# ---------- вспомогательное ----------
async def resolve_target(m: Message, args: str):
    """(uid, name, rest) по ответу / @username / id. None если не нашли."""
    if m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        return u.id, u.full_name, args
    parts = args.split(maxsplit=1)
    if not parts:
        return None
    for ent in m.entities or []:
        if ent.type == "text_mention" and ent.user:
            return ent.user.id, ent.user.full_name, args.replace(parts[0], "", 1).strip()
    row = await db.find_user(parts[0])
    if row:
        return row["id"], row["name"] or parts[0], parts[1] if len(parts) > 1 else ""
    if parts[0].lstrip("-").isdigit():
        return int(parts[0]), parts[0], parts[1] if len(parts) > 1 else ""
    return None


async def mod_guard(m: Message, args: str, need_target=True):
    """Проверка прав и цели. Возвращает (uid, name, rest) или None (ответ уже отправлен)."""
    bot = m.bot
    if not await is_mod(bot, m.chat.id, m.from_user.id):
        return None  # обычным участникам молчим, чтобы не засорять чат
    if not need_target:
        return 0, "", args
    t = await resolve_target(m, args)
    if not t:
        await m.reply("Ответь на сообщение пользователя или укажи @username / id")
        return None
    uid, name, rest = t
    if uid == DEV_ID and m.from_user.id != DEV_ID:
        await m.reply("🛡 Разработчика бота нельзя наказывать")
        return None
    if uid == bot.id:
        await m.reply("Себя я наказывать не буду 🙂")
        return None
    if uid == m.from_user.id:
        await m.reply("Нельзя применить к себе")
        return None
    if await is_chat_admin(bot, m.chat.id, uid):
        await m.reply("🚫 Это администратор чата, а Telegram не позволяет боту наказывать админов.\n"
                      "Сними с него права админа в настройках чата и повтори команду.")
        return None
    return uid, name, rest


async def default_perms(bot: Bot, cid: int) -> ChatPermissions:
    try:
        p = (await bot.get_chat(cid)).permissions
        if p:
            return p
    except Exception:
        pass
    return ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True,
                           can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                           can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                           can_add_web_page_previews=True)


async def safe(m: Message, coro, ok: str, markup=None):
    try:
        await coro
        await m.reply(ok, reply_markup=markup)
        return True
    except TelegramBadRequest as e:
        msg = e.message.lower()
        if "administrator of the chat" in msg or "chat owner" in msg:
            hint = "Цель — админ или владелец чата: Telegram не даёт боту наказывать админов."
        elif "not enough rights" in msg or "need to be administrator" in msg or "can_restrict" in msg:
            hint = "У бота нет права «Блокировка пользователей» (или он не админ)."
        else:
            hint = "Проверь, что бот — админ с нужными правами."
        await m.reply(f"⚠️ Не получилось: {esc(e.message)}\n{hint}")
    except Exception as e:
        await m.reply(f"⚠️ Ошибка: {esc(e)}")
    return False


async def do_mute(bot: Bot, cid: int, uid: int, seconds: int | None):
    until = datetime.now() + timedelta(seconds=seconds) if seconds else None
    await bot.restrict_chat_member(cid, uid, ChatPermissions(can_send_messages=False), until_date=until)


# ---------- команды ----------
@cmd("бан", mod=True)
async def ban(m: Message, args: str):
    t = await mod_guard(m, args)
    if t:
        uid, name, rest = t
        if await safe(m, m.bot.ban_chat_member(m.chat.id, uid),
                      f"🔨 {mention(uid, name)} забанен" + (f"\nПричина: {esc(rest)}" if rest else ""),
                      InlineKeyboardMarkup(inline_keyboard=[[
                          InlineKeyboardButton(text="✅ Разбанить и вернуть", callback_data=f"unb:{uid}")]])):
            await db.run("INSERT OR REPLACE INTO bans(chat_id,user_id,name,ts) VALUES(?,?,?,?)",
                         (m.chat.id, uid, name, time.time()))


async def do_unban(bot: Bot, cid: int, uid: int, name: str) -> str:
    """Снимает бан, кидает человеку одноразовую ссылку для возврата. Возвращает текст-итог."""
    await bot.unban_chat_member(cid, uid, only_if_banned=True)
    await db.run("DELETE FROM bans WHERE chat_id=? AND user_id=?", (cid, uid))
    text = f"✅ {mention(uid, name)} разбанен."
    try:
        link = (await bot.create_chat_invite_link(cid, member_limit=1)).invite_link
    except Exception:
        return text + "\nМожет вернуться по обычной ссылке-приглашению."
    title = (await db.get_chat(cid) or {"title": "чат"})["title"]
    try:
        await bot.send_message(uid, f"✅ Тебя разбанили в чате «{esc(title)}». Вернуться: {link}")
        return text + "\n📩 Ссылка для возврата отправлена ему в личку."
    except Exception:
        return text + f"\nВ личку написать не вышло (он не запускал бота). Ссылка для возврата, одноразовая:\n{link}"


@cmd("разбан", mod=True)
async def unban(m: Message, args: str):
    t = await mod_guard(m, args)
    if not t:
        return
    uid, name, _ = t
    try:
        await m.reply(await do_unban(m.bot, m.chat.id, uid, name))
    except TelegramBadRequest as e:
        await m.reply(f"⚠️ Не получилось: {esc(e.message)}")


@cmd("баны", "забаненные", mod=True)
async def bans_list(m: Message, args: str):
    if not await mod_guard(m, args, need_target=False):
        return
    rows = await db.many("SELECT * FROM bans WHERE chat_id=? ORDER BY ts DESC LIMIT 30", (m.chat.id,))
    if not rows:
        return await m.reply("Список банов через бота пуст.")
    await m.reply("🔨 <b>Забанены через бота</b>\n" + "\n".join(
        f"• {esc(r['name'])} — <code>{r['user_id']}</code>" for r in rows) +
        "\n\nРазбанить: <code>разбан id</code> или кнопка «Разбанить и вернуть» под сообщением о бане.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ {r['name'][:25]}", callback_data=f"unb:{r['user_id']}")] for r in rows[:10]]))


@router.callback_query(F.data.startswith("unb:"))
async def unban_cb(cb: CallbackQuery):
    cid = cb.message.chat.id
    if not await is_mod(cb.bot, cid, cb.from_user.id):
        return await cb.answer("Только для админов чата", show_alert=True)
    uid = int(cb.data.split(":")[1])
    row = await db.one("SELECT name FROM bans WHERE chat_id=? AND user_id=?", (cid, uid))
    name = (row["name"] if row else None) or str(uid)
    try:
        text = await do_unban(cb.bot, cid, uid, name)
    except TelegramBadRequest as e:
        return await cb.answer(e.message, show_alert=True)
    await cb.answer("Разбанен")
    await cb.message.reply(text)


@cmd("кик", mod=True)
async def kick(m: Message, args: str):
    t = await mod_guard(m, args)
    if t:
        uid, name, _ = t

        async def go():
            await m.bot.ban_chat_member(m.chat.id, uid)
            await m.bot.unban_chat_member(m.chat.id, uid, only_if_banned=True)
        await safe(m, go(), f"👢 {mention(uid, name)} выгнан")


@cmd("мут", mod=True)
async def mute(m: Message, args: str):
    t = await mod_guard(m, args)
    if not t:
        return
    uid, name, rest = t
    first = rest.split()[0] if rest.split() else ""
    sec = parse_duration(first) if first else 3600
    if first and first.lower() in ("навсегда", "forever"):
        sec = None
    elif sec is None:
        sec = 3600
    label = fmt_dur(sec) if sec else "навсегда"
    await safe(m, do_mute(m.bot, m.chat.id, uid, sec), f"🔇 {mention(uid, name)} в муте: {label}")


@cmd("размут", mod=True)
async def unmute(m: Message, args: str):
    t = await mod_guard(m, args)
    if t:
        uid, name, _ = t
        await safe(m, m.bot.restrict_chat_member(m.chat.id, uid, await default_perms(m.bot, m.chat.id)),
                   f"🔊 {mention(uid, name)} размучен")


@cmd("варн", "пред", mod=True)
async def warn(m: Message, args: str):
    t = await mod_guard(m, args)
    if not t:
        return
    uid, name, rest = t
    await db.run("INSERT INTO warns(chat_id,user_id,n) VALUES(?,?,1) ON CONFLICT(chat_id,user_id) DO UPDATE SET n=n+1",
                 (m.chat.id, uid))
    n = await db.scalar("SELECT n FROM warns WHERE chat_id=? AND user_id=?", (m.chat.id, uid))
    text = f"⚠️ {mention(uid, name)} получил предупреждение ({n}/{WARN_LIMIT})" + (f"\nПричина: {esc(rest)}" if rest else "")
    if n >= WARN_LIMIT:
        await db.run("UPDATE warns SET n=0 WHERE chat_id=? AND user_id=?", (m.chat.id, uid))
        await safe(m, do_mute(m.bot, m.chat.id, uid, 86400), text + "\n🔇 Лимит достигнут — мут на 1 день")
    else:
        await m.reply(text)


@cmd("снять варн", "снять пред", "анварн", mod=True)
async def unwarn(m: Message, args: str):
    t = await mod_guard(m, args)
    if t:
        uid, name, _ = t
        await db.run("UPDATE warns SET n=MAX(n-1,0) WHERE chat_id=? AND user_id=?", (m.chat.id, uid))
        await m.reply(f"✅ Предупреждение снято у {mention(uid, name)}")


@cmd("варны", chat_only=True, gate=False)
async def warns(m: Message, args: str):
    t = await resolve_target(m, args)
    uid, name = (t[0], t[1]) if t else (m.from_user.id, m.from_user.full_name)
    n = await db.scalar("SELECT n FROM warns WHERE chat_id=? AND user_id=?", (m.chat.id, uid))
    await m.reply(f"⚠️ У {mention(uid, name)} предупреждений: {n}/{WARN_LIMIT}")


@cmd("закрепить", mod=True)
async def pin(m: Message, args: str):
    if not await mod_guard(m, args, need_target=False):
        return
    if not m.reply_to_message:
        return await m.reply("Ответь на сообщение, которое нужно закрепить")
    await safe(m, m.bot.pin_chat_message(m.chat.id, m.reply_to_message.message_id), "📌 Закреплено")


@cmd("открепить", mod=True)
async def unpin(m: Message, args: str):
    if not await mod_guard(m, args, need_target=False):
        return
    await safe(m, m.bot.unpin_chat_message(m.chat.id, m.reply_to_message.message_id if m.reply_to_message else None),
               "📌 Откреплено")


@cmd("удалить", mod=True)
async def delete(m: Message, args: str):
    if not await mod_guard(m, args, need_target=False):
        return
    if not m.reply_to_message:
        return await m.reply("Ответь на сообщение, которое нужно удалить")
    try:
        await m.bot.delete_messages(m.chat.id, [m.reply_to_message.message_id, m.message_id])
    except TelegramBadRequest as e:
        await m.reply(f"⚠️ {esc(e.message)}")


@cmd("очистить", mod=True)
async def purge(m: Message, args: str):
    if not await mod_guard(m, args, need_target=False):
        return
    n = int(args.split()[0]) if args.split() and args.split()[0].isdigit() else 0
    if not 1 <= n <= 100:
        return await m.reply("Формат: <code>очистить 20</code> (1–100)")
    try:
        await m.bot.delete_messages(m.chat.id, list(range(max(1, m.message_id - n), m.message_id + 1)))
    except TelegramBadRequest as e:
        await m.reply(f"⚠️ {esc(e.message)}")


# ---------- настройки чата ----------
@cmd("+правила", mod=True)
async def set_rules(m: Message, args: str):
    if await mod_guard(m, args, need_target=False) and args.strip():
        await db.run("UPDATE chats SET rules=? WHERE id=?", (args.strip(), m.chat.id))
        await m.reply("📜 Правила сохранены")


@cmd("правила", chat_only=True, gate=False)
async def rules(m: Message, args: str):
    c = await db.get_chat(m.chat.id)
    await m.reply(f"📜 <b>Правила чата</b>\n\n{esc(c['rules'])}" if c and c["rules"] else
                  "Правила не заданы. Админ может добавить: <code>+правила текст</code>")


@cmd("+приветствие", mod=True)
async def set_welcome(m: Message, args: str):
    if await mod_guard(m, args, need_target=False) and args.strip():
        await db.run("UPDATE chats SET welcome=? WHERE id=?", (args.strip(), m.chat.id))
        await m.reply("👋 Приветствие сохранено. {name} заменится на имя новичка.")


@cmd("-приветствие", mod=True)
async def del_welcome(m: Message, args: str):
    if await mod_guard(m, args, need_target=False):
        await db.run("UPDATE chats SET welcome='' WHERE id=?", (m.chat.id,))
        await m.reply("Приветствие новичков выключено. Вернуть стандартное: <code>приветствие сброс</code>")


@cmd("приветствие сброс", mod=True)
async def reset_welcome(m: Message, args: str):
    if await mod_guard(m, args, need_target=False):
        await db.run("UPDATE chats SET welcome=NULL WHERE id=?", (m.chat.id,))
        await m.reply("Вернул стандартное приветствие бота")


async def _toggle(m: Message, args: str, col: str, label: str):
    if not await mod_guard(m, args, need_target=False):
        return
    a = args.strip().lower()
    if a not in ("вкл", "выкл"):
        return await m.reply(f"Формат: <code>{label} вкл</code> или <code>{label} выкл</code>")
    await db.run(f"UPDATE chats SET {col}=? WHERE id=?", (1 if a == "вкл" else 0, m.chat.id))
    await m.reply(f"{'✅' if a == 'вкл' else '⛔'} {label}: {a}")


@cmd("антиссылки", mod=True)
async def antilink(m: Message, args: str):
    await _toggle(m, args, "antilink", "антиссылки")


@cmd("антифлуд", mod=True)
async def antiflood(m: Message, args: str):
    await _toggle(m, args, "antiflood", "антифлуд")


@cmd("настройки", mod=True)
async def settings(m: Message, args: str):
    if not await mod_guard(m, args, need_target=False):
        return
    c = await db.get_chat(m.chat.id)
    onoff = lambda v: "✅ вкл" if v else "⛔ выкл"
    op = await db.scalar("SELECT COUNT(*) FROM chat_subs WHERE chat_id=?", (m.chat.id,))
    await m.reply(f"⚙️ <b>Настройки чата</b>\n\nАнтиссылки: {onoff(c['antilink'])}\nАнтифлуд: {onoff(c['antiflood'])}\n"
                  f"ОП: {f'✅ каналов: {op}' if op else '⛔ выкл'}\n"
                  f"Приветствие: {'выкл' if c['welcome'] == '' else 'своё' if c['welcome'] else 'стандартное'}\nПравила: {'есть' if c['rules'] else 'нет'}\n"
                  f"Добавил бота: <code>{c['added_by'] or '—'}</code>")


# ---------- полезное для всех ----------
@cmd("админы", chat_only=True, gate=False)
async def admins(m: Message, args: str):
    lst = [a for a in await m.bot.get_chat_administrators(m.chat.id) if not a.user.is_bot]
    await m.reply("👮 <b>Админы чата</b>\n" + "\n".join(
        f"• {mention(a.user.id, a.user.full_name)}" + (" 👑" if a.status == "creator" else "") for a in lst))


@cmd("репорт", chat_only=True, gate=False)
async def report(m: Message, args: str):
    if not m.reply_to_message:
        return await m.reply("Ответь командой на сообщение нарушителя")
    lst = [a for a in await m.bot.get_chat_administrators(m.chat.id) if not a.user.is_bot][:10]
    await m.reply("🚨 Жалоба отправлена админам: " + " ".join(mention(a.user.id, "👮") for a in lst))


@cmd("инфо", chat_only=True, gate=False)
async def info(m: Message, args: str):
    t = await resolve_target(m, args)
    uid, name = (t[0], t[1]) if t else (m.from_user.id, m.from_user.full_name)
    try:
        st = (await m.bot.get_chat_member(m.chat.id, uid)).status
    except Exception:
        st = "неизвестно"
    n = await db.scalar("SELECT n FROM warns WHERE chat_id=? AND user_id=?", (m.chat.id, uid))
    extra = "\n🛡 Разработчик бота" if uid == DEV_ID else ""
    await m.reply(f"ℹ️ {mention(uid, name)}\nID: <code>{uid}</code>\nСтатус: {st}\nВарны: {n}/{WARN_LIMIT}{extra}")


# ---------- фильтры (вызываются из общего обработчика) ----------
async def run_filters(m: Message) -> bool:
    """True, если сообщение удалено/обработано фильтром."""
    chat = await db.get_chat(m.chat.id)
    if not chat or not (chat["antilink"] or chat["antiflood"]):
        return False
    if await is_mod(m.bot, m.chat.id, m.from_user.id) or await is_chat_admin(m.bot, m.chat.id, m.from_user.id):
        return False
    if chat["antilink"] and (URL_RE.search(m.text or "") or any(e.type in ("url", "text_link") for e in m.entities or [])):
        try:
            await m.delete()
            await m.answer(f"🔗 {mention(m.from_user.id, m.from_user.full_name)}, ссылки в этом чате запрещены")
        except Exception:
            pass
        return True
    if chat["antiflood"]:
        q = flood[(m.chat.id, m.from_user.id)]
        q.append(time.time())
        if len(q) == q.maxlen and q[-1] - q[0] < 5:
            q.clear()
            try:
                await do_mute(m.bot, m.chat.id, m.from_user.id, 300)
                await m.answer(f"🌊 {mention(m.from_user.id, m.from_user.full_name)} замучен на 5 мин за флуд")
            except Exception:
                pass
            return True
    return False


# ---------- события ----------
@router.my_chat_member()
async def bot_status(ev: ChatMemberUpdated, bot: Bot):
    if ev.chat.type == "private":
        return
    st = ev.new_chat_member.status
    if st in ("member", "administrator"):
        await db.touch_user(ev.from_user)
        was_in = ev.old_chat_member.status in ("member", "administrator")
        await db.upsert_chat(ev.chat, added_by=None if was_in else ev.from_user.id, active=1)
        if not was_in:
            try:
                await bot.send_message(
                    ev.chat.id,
                    f"👋 Привет! Я чат-менеджер Cursed.\nМеня добавил {mention(ev.from_user.id, ev.from_user.full_name)} — "
                    "теперь он может банить, мутить и настраивать чат через меня.\n\n"
                    "Выдай мне права админа (удаление сообщений, блокировка пользователей) и напиши <code>команды</code>.")
            except Exception:
                pass
    else:
        await db.upsert_chat(ev.chat, active=0)


@router.chat_member()
async def protect_dev(ev: ChatMemberUpdated, bot: Bot):
    """Если кто-то ограничил/выгнал разработчика — пытаемся откатить."""
    if ev.new_chat_member.user.id != DEV_ID or ev.from_user.id in (DEV_ID, bot.id):
        return
    st = ev.new_chat_member.status
    try:
        if st == "restricted":
            await bot.restrict_chat_member(ev.chat.id, DEV_ID, await default_perms(bot, ev.chat.id))
            await bot.send_message(ev.chat.id, "🛡 Разработчика бота нельзя ограничивать — ограничения сняты.")
        elif st == "kicked":
            await bot.unban_chat_member(ev.chat.id, DEV_ID, only_if_banned=True)
            link = await bot.create_chat_invite_link(ev.chat.id, member_limit=1)
            await bot.send_message(DEV_ID, f"🛡 Тебя забанили в «{esc(ev.chat.title)}», я снял бан. Вернуться: {link.invite_link}")
    except Exception:
        pass


@router.message(F.new_chat_members)
async def on_join(m: Message):
    await db.upsert_chat(m.chat)
    chat = await db.get_chat(m.chat.id)
    if not chat or chat["welcome"] == "":
        return  # в этом чате приветствие выключено
    if chat["welcome"]:
        text, ents = chat["welcome"], []  # своё приветствие чата (простой текст)
    else:
        if await db.get_setting("welcome_on", "1") != "1":
            return
        try:
            g = json.loads(await db.get_setting("welcome_default"))
            text, ents = g["text"], g["entities"]
        except Exception:
            text, ents = DEFAULT_WELCOME, []
    for u in m.new_chat_members:
        if u.is_bot:
            continue
        t, e = fill_name(text, ents, u.first_name or u.full_name, u.id)
        try:
            await m.answer(t, entities=[MessageEntity(**x) for x in e] or None, parse_mode=None)
        except Exception:
            pass
