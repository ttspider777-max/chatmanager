import json
import time

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
from config import DEV_ID

_sub_ok: dict[int, float] = {}
_mod_cache: dict[tuple, tuple] = {}


async def sub_channels() -> list:
    try:
        return json.loads(await db.get_setting("sub_channels", "[]"))
    except Exception:
        return []


async def missing_subs(bot: Bot, uid: int) -> list:
    if uid == DEV_ID:
        return []
    chans = await sub_channels()
    if not chans or _sub_ok.get(uid, 0) > time.time():
        return []
    out = []
    for ch in chans:
        try:
            m = await bot.get_chat_member(ch["id"], uid)
            ok = m.status in ("creator", "administrator", "member") or (m.status == "restricted" and m.is_member)
        except Exception:
            ok = True  # не смогли проверить (бот не админ канала) — не блокируем
        if not ok:
            out.append(ch)
    if not out:
        _sub_ok[uid] = time.time() + 60
    return out


def sub_markup(missing: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['title']}", url=c["link"])] for c in missing]
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="chk_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


SUB_TEXT = "🔔 Чтобы пользоваться ботом, подпишись на канал(ы) ниже и нажми «Я подписался»."


async def is_mod(bot: Bot, cid: int, uid: int) -> bool:
    if uid == DEV_ID:
        return True
    key = (cid, uid)
    hit = _mod_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    ok = False
    chat = await db.get_chat(cid)
    if chat and chat["added_by"] == uid:
        ok = True
    else:
        try:
            m = await bot.get_chat_member(cid, uid)
            ok = m.status in ("creator", "administrator")
        except Exception:
            ok = False
    _mod_cache[key] = (time.time() + 60, ok)
    return ok


async def is_chat_admin(bot: Bot, cid: int, uid: int) -> bool:
    try:
        m = await bot.get_chat_member(cid, uid)
        return m.status in ("creator", "administrator")
    except Exception:
        return False
