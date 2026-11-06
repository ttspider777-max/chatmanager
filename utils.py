import html
import re

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

import config

SUFFIX = {"к": 10**3, "k": 10**3, "кк": 10**6, "kk": 10**6, "м": 10**6, "m": 10**6,
          "ккк": 10**9, "kkk": 10**9, "б": 10**9, "b": 10**9, "мрд": 10**9}


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def money(n) -> str:
    return f"{fmt(n)} {config.CUR}"


def esc(s) -> str:
    return html.escape(str(s or ""))


def mention(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{esc(name) or uid}</a>'


def parse_amount(s: str, balance: int | None = None) -> int | None:
    s = (s or "").strip().lower().replace(" ", "")
    if s in ("все", "всё", "all", "allin") and balance:
        return int(balance)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)([a-zа-я]*)", s)
    if not m:
        return None
    num = float(m.group(1).replace(",", "."))
    suf = m.group(2)
    mult = 1
    if suf:
        if suf not in SUFFIX:
            return None
        mult = SUFFIX[suf]
    val = int(num * mult)
    return val if val > 0 else None


DUR = {"с": 1, "s": 1, "сек": 1, "м": 60, "m": 60, "мин": 60, "min": 60, "ч": 3600, "h": 3600, "час": 3600,
       "д": 86400, "d": 86400, "дн": 86400, "н": 604800, "w": 604800}


def parse_duration(s: str) -> int | None:
    m = re.fullmatch(r"(\d+)\s*([a-zа-я]+)", (s or "").strip().lower())
    if not m or m.group(2) not in DUR:
        return None
    return int(m.group(1)) * DUR[m.group(2)]


def fmt_dur(sec: int) -> str:
    for unit, n in (("д", 86400), ("ч", 3600), ("мин", 60)):
        if sec >= n:
            return f"{sec // n} {unit}"
    return f"{sec} с"


def bar(p: float, width: int = 12) -> str:
    p = max(0.0, min(1.0, p))
    full = int(round(p * width))
    return "▓" * full + "░" * (width - full)


async def screen(ev, text: str, kb=None, entities=None):
    """Показать экран: редактируем сообщение для колбэков, отправляем новое для сообщений.
    entities — готовая разметка (например премиум-эмодзи); тогда parse_mode отключается."""
    extra = dict(entities=entities, parse_mode=None) if entities else {}
    if isinstance(ev, CallbackQuery):
        try:
            await ev.message.edit_text(text, reply_markup=kb, **extra)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                await ev.message.answer(text, reply_markup=kb, **extra)
        try:
            await ev.answer()
        except Exception:
            pass
    else:
        await ev.answer(text, reply_markup=kb, **extra)


def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def fill_name(text: str, ents: list[dict], name: str, uid: int | None = None):
    """Подставляет имя вместо {name}, сдвигая сущности (смещения в UTF-16).
    Если передан uid, имя становится кликабельным упоминанием."""
    ph = "{name}"
    ents = [dict(e) for e in ents]
    start = 0
    while ph in text[start:]:
        i = text.index(ph, start)
        pos, old, new = _u16(text[:i]), _u16(ph), _u16(name)
        d = new - old
        text = text[:i] + name + text[i + len(ph):]
        start = i + len(name)
        for e in ents:
            if e["offset"] >= pos + old:
                e["offset"] += d
            elif e["offset"] <= pos and e["offset"] + e["length"] >= pos + old:
                e["length"] += d
        if uid is not None and new:
            ents.append(dict(type="text_mention", offset=pos, length=new,
                             user=dict(id=uid, is_bot=False, first_name=name)))
    return text, ents


def cid_of(m: Message):
    return None if m.chat.type == "private" else m.chat.id
