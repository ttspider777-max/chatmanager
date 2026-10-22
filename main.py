import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import admin
import commands
import config
import db
import economy as eco
import menu
import moderation
from config import ELITE, STAGES
from middlewares import Gate
from utils import fmt


async def announce_stage(bot: Bot, old: int, new: int):
    chats = await db.many("SELECT id FROM chats WHERE active=1")
    for n in range(old + 1, new + 1):
        thr, name, novelty = STAGES[n - 1]
        text = (f"🏛 <b>Этап {n} открыт: «{name}»!</b>\nБюджет города достиг {fmt(thr)} {config.CUR}.\n\n"
                f"Новинка: {novelty}")
        for c in chats:
            try:
                await bot.send_message(c["id"], text)
            except Exception:
                pass
            await asyncio.sleep(0.05)


async def elite_loop(bot: Bot):
    while True:
        try:
            for key, owner in await eco.expire_elite():
                e = ELITE[key]
                try:
                    await bot.send_message(owner, f"⌛ Аренда «{e['name']}» закончилась. Продли её в «Элитные бизнесы».")
                except Exception:
                    pass
        except Exception:
            logging.exception("elite loop")
        await asyncio.sleep(300)


async def main():
    logging.basicConfig(level=logging.INFO)
    await db.init()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    config.BOT_USERNAME = (await bot.get_me()).username
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(Gate())
    dp.callback_query.outer_middleware(Gate())
    dp.include_routers(admin.router, menu.router, moderation.router, commands.router)

    async def on_stage(old, new):
        await announce_stage(bot, old, new)
    eco.on_stage = on_stage

    await bot.set_my_commands([BotCommand(command="start", description="Главное меню"),
                               BotCommand(command="help", description="Все команды")])
    asyncio.create_task(elite_loop(bot))
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot @%s started", config.BOT_USERNAME)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
