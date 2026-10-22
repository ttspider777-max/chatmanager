from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

import db
from access import SUB_TEXT, missing_subs, sub_markup
from config import DEV_ID


class Gate(BaseMiddleware):
    """Регистрация пользователя, бан в боте, техрежим и обязательная подписка (в личке и на кнопках)."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)
        await db.touch_user(user)
        if user.id == DEV_ID:
            return await handler(event, data)
        row = await db.get_user(user.id)
        is_cb = isinstance(event, CallbackQuery)
        chat = event.message.chat if is_cb and event.message else getattr(event, "chat", None)
        private = bool(chat and chat.type == "private")
        if row and row["banned"]:
            if is_cb:
                await event.answer("⛔ Ты заблокирован в боте", show_alert=True)
            elif private:
                await event.answer("⛔ Ты заблокирован в боте.")
            return
        if await db.get_setting("maint") == "1":
            if is_cb:
                await event.answer("🛠 Технические работы, загляни позже", show_alert=True)
            elif private:
                await event.answer("🛠 Технические работы, загляни позже.")
            return
        if private and not (is_cb and event.data == "chk_sub"):
            missing = await missing_subs(event.bot, user.id)
            if missing:
                if is_cb:
                    await event.answer("Сначала подпишись на канал", show_alert=True)
                    await event.message.answer(SUB_TEXT, reply_markup=sub_markup(missing))
                else:
                    await event.answer(SUB_TEXT, reply_markup=sub_markup(missing))
                return
        return await handler(event, data)
