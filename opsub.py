"""Обязательная подписка (ОП) для отдельного чата.

Админ чата пишет «+оп @канал» — после этого сообщения тех, кто не подписан на канал/чат,
удаляются, а бот показывает кнопки «Подписаться» и «Я подписался».
"""
import asyncio
import re
import time

from aiogram import Bot, F, Router
from aiogram.enums import ContentType
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
from access import is_chat_admin, is_mod
from config import DEV_ID
from registry import cmd
from utils import esc, mention

router = Router()
MAX_SUBS = 5
WARN_TTL = 60          # через сколько секунд удалять предупреждение бота
WARN_COOLDOWN = 30     # не чаще одного предупреждения на человека за это время
OK_TTL = 120           # сколько секунд помнить, что человек подписан

_ok: dict[tuple, float] = {}       # (chat, user) -> до какого времени не проверять
_warned: dict[tuple, float] = {}   # (chat, user) -> когда последний раз предупреждали
USER_CONTENT = {ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.ANIMATION, ContentType.STICKER,
                ContentType.DOCUMENT, ContentType.AUDIO, ContentType.VOICE, ContentType.VIDEO_NOTE,
                ContentType.POLL, ContentType.DICE, ContentType.CONTACT, ContentType.LOCATION,
                ContentType.VENUE, ContentType.STORY}
LINK_RE = re.compile(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z0-9_]{4,})/?$", re.I)


async def chat_subs(cid: int) -> list:
    return await db.many("SELECT * FROM chat_subs WHERE chat_id=? ORDER BY rowid", (cid,))


def _is_member(m) -> bool:
    return m.status in ("creator", "administrator", "member") or (m.status == "restricted" and m.is_member)


async def missing_for(bot: Bot, cid: int, uid: int) -> list:
    """Каналы/чаты ОП этого чата, на которые человек не подписан."""
    subs = await chat_subs(cid)
    if not subs or _ok.get((cid, uid), 0) > time.time():
        return []
    out = []
    for s in subs:
        try:
            ok = _is_member(await bot.get_chat_member(s["target_id"], uid))
        except Exception:
            ok = True  # бот потерял доступ к каналу — не блокируем людей зря
        if not ok:
            out.append(s)
    if not out:
        _ok[(cid, uid)] = time.time() + OK_TTL
    return out


def op_markup(missing: list, uid: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {s['title'][:40]}", url=s["link"])] for s in missing]
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data=f"opchk:{uid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _delete_later(msg: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


async def check_message(m: Message) -> bool:
    """True, если сообщение удалено из-за ОП. Вызывается для каждого сообщения в группе."""
    u = m.from_user
    if (not u or u.is_bot or u.id in (DEV_ID, 777000) or m.sender_chat
            or m.content_type not in USER_CONTENT):
        return False
    if not await db.one("SELECT 1 FROM chat_subs WHERE chat_id=? LIMIT 1", (m.chat.id,)):
        return False
    key = (m.chat.id, u.id)
    if _ok.get(key, 0) > time.time():
        return False
    if await is_mod(m.bot, m.chat.id, u.id) or await is_chat_admin(m.bot, m.chat.id, u.id):
        _ok[key] = time.time() + OK_TTL
        return False
    missing = await missing_for(m.bot, m.chat.id, u.id)
    if not missing:
        return False
    try:
        await m.delete()
    except Exception:
        pass  # нет права удалять — всё равно напомним
    if _warned.get(key, 0) + WARN_COOLDOWN > time.time():
        return True
    _warned[key] = time.time()
    try:
        warn = await m.answer(
            f"🔔 {mention(u.id, u.full_name)}, чтобы писать в этом чате, подпишись "
            f"{'на канал' if len(missing) == 1 else 'на каналы'} ниже и нажми «Я подписался».",
            reply_markup=op_markup(missing, u.id))
        asyncio.create_task(_delete_later(warn, WARN_TTL))
    except Exception:
        pass
    return True


@router.callback_query(F.data.startswith("opchk:"))
async def op_check(cb: CallbackQuery):
    uid = int(cb.data.split(":")[1])
    if cb.from_user.id != uid:
        return await cb.answer("Эта кнопка не для тебя 🙂 Напиши что-нибудь в чат — бот покажет твою.", show_alert=True)
    cid = cb.message.chat.id
    _ok.pop((cid, uid), None)
    missing = await missing_for(cb.bot, cid, uid)
    if missing:
        try:
            await cb.message.edit_reply_markup(reply_markup=op_markup(missing, uid))
        except Exception:
            pass
        return await cb.answer("Ты ещё не подписался: " + ", ".join(s["title"] for s in missing), show_alert=True)
    _warned.pop((cid, uid), None)
    await cb.answer("✅ Спасибо! Теперь можешь писать в чат.", show_alert=True)
    try:
        await cb.message.delete()
    except Exception:
        pass


# ---------- команды админов ----------
async def _resolve(m: Message, args: str):
    """Находит канал/чат: ответ на пересланный пост, @username, t.me/username или id. -> (chat, своя_ссылка)"""
    parts = args.split()
    link = next((p for p in parts[1:] if "t.me/" in p or "telegram.me/" in p), None)
    if m.reply_to_message and m.reply_to_message.forward_origin and not parts:
        o = m.reply_to_message.forward_origin
        ch = getattr(o, "chat", None) or getattr(o, "sender_chat", None)
        if ch:
            return await m.bot.get_chat(ch.id), None
    if not parts:
        return None, None
    token = parts[0]
    mt = LINK_RE.match(token)
    if mt:
        token = "@" + mt.group(1)
    elif token.lstrip("-").isdigit():
        token = int(token)
    elif not token.startswith("@"):
        token = "@" + token
    return await m.bot.get_chat(token), link


async def _make_link(bot: Bot, ch) -> str | None:
    if ch.username:
        return f"https://t.me/{ch.username}"
    if ch.invite_link:
        return ch.invite_link
    try:
        return (await bot.create_chat_invite_link(ch.id, name="ОП Heliys")).invite_link
    except Exception:
        return None


HOW = ("Как добавить ОП:\n"
       "• <code>+оп @канал</code> — публичный канал/чат\n"
       "• <code>+оп -100123456789</code> — по id\n"
       "• <code>+оп -100123456789 https://t.me/+ссылка</code> — приватный канал со своей ссылкой\n"
       "• или перешли сюда пост из канала и ответь на него <code>+оп</code>\n\n"
       "⚠️ Бот должен быть <b>админом</b> в этом канале/чате, иначе он не сможет проверять подписку.")


@cmd("+оп", "оп добавить", mod=True)
async def op_add(m: Message, args: str):
    if not await is_mod(m.bot, m.chat.id, m.from_user.id):
        return
    try:
        ch, link = await _resolve(m, args)
    except Exception:
        return await m.reply("⚠️ Не нашёл такой канал/чат. Проверь @username или добавь бота туда админом и укажи id.\n\n" + HOW)
    if not ch:
        return await m.reply(HOW)
    if ch.id == m.chat.id:
        return await m.reply("Нельзя поставить ОП на этот же чат 🙂")
    if len(await chat_subs(m.chat.id)) >= MAX_SUBS:
        return await m.reply(f"Максимум {MAX_SUBS} каналов в ОП. Убери лишний: <code>-оп @канал</code>")
    try:
        me = await m.bot.get_chat_member(ch.id, m.bot.id)
        bot_ok = me.status in ("administrator", "creator") or (ch.type != "channel" and _is_member(me))
    except Exception:
        bot_ok = False
    if not bot_ok:
        return await m.reply(f"⚠️ Я не админ в «{esc(ch.title or ch.id)}». Добавь меня туда администратором "
                             "(права можно минимальные) и повтори команду — иначе я не смогу проверять подписку.")
    link = link or await _make_link(m.bot, ch)
    if not link:
        return await m.reply("⚠️ Не получилось взять ссылку на канал. Укажи её сам:\n"
                             f"<code>+оп {ch.id} https://t.me/+ссылка</code>")
    await db.run("INSERT OR REPLACE INTO chat_subs(chat_id,target_id,title,link) VALUES(?,?,?,?)",
                 (m.chat.id, ch.id, ch.title or str(ch.id), link))
    for k in [k for k in _ok if k[0] == m.chat.id]:
        _ok.pop(k, None)
    await m.reply(f"✅ ОП включена: <a href=\"{esc(link)}\">{esc(ch.title)}</a>\n"
                  "Теперь сообщения неподписанных участников будут удаляться. Админов это не касается.\n\n"
                  "Список: <code>оп</code> · убрать: <code>-оп @канал</code> или <code>-оп все</code>\n"
                  "Не забудь дать мне в этом чате право «Удаление сообщений».")


@cmd("-оп", "оп убрать", "оп удалить", mod=True)
async def op_del(m: Message, args: str):
    if not await is_mod(m.bot, m.chat.id, m.from_user.id):
        return
    a = args.strip()
    if a.lower() in ("все", "всё", "all"):
        n = await db.run("DELETE FROM chat_subs WHERE chat_id=?", (m.chat.id,))
        return await m.reply("⛔ ОП выключена в этом чате" if n else "ОП в этом чате и так не стоит")
    if not a:
        return await m.reply("Формат: <code>-оп @канал</code>, <code>-оп id</code>, <code>-оп 2</code> (номер из списка) "
                             "или <code>-оп все</code>")
    subs = await chat_subs(m.chat.id)
    target = None
    if a.isdigit() and 1 <= int(a) <= len(subs):
        target = subs[int(a) - 1]["target_id"]
    elif a.lstrip("-").isdigit():
        target = int(a)
    else:
        try:
            ch, _ = await _resolve(m, a)
            target = ch.id if ch else None
        except Exception:
            target = None
    n = await db.run("DELETE FROM chat_subs WHERE chat_id=? AND target_id=?", (m.chat.id, target)) if target else 0
    await m.reply("✅ Канал убран из ОП" if n else "Такого канала нет в ОП. Посмотри список: <code>оп</code>")


@cmd("оп", mod=True)
async def op_list(m: Message, args: str):
    if not await is_mod(m.bot, m.chat.id, m.from_user.id):
        return
    subs = await chat_subs(m.chat.id)
    if not subs:
        return await m.reply("🔔 ОП в этом чате выключена.\n\n" + HOW)
    await m.reply("🔔 <b>Обязательная подписка в этом чате</b>\n" + "\n".join(
        f"{i}. <a href=\"{esc(s['link'])}\">{esc(s['title'])}</a> — <code>{s['target_id']}</code>"
        for i, s in enumerate(subs, 1)) +
        "\n\nДобавить: <code>+оп @канал</code> · убрать: <code>-оп 1</code> или <code>-оп все</code>")
