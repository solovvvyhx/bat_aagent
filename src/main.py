from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import get_settings
from src.handlers import get_main_router
from src.middlewares import AdminOnlyMiddleware
from src.services import BatScheduler, MesClient, start_health_server


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def run() -> None:
    """Точка входа: поднимает /health, планировщик и Telegram-бота."""
    _configure_logging()
    settings = get_settings()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.message.middleware(AdminOnlyMiddleware(settings.admin_id))
    dp.include_router(get_main_router())

    mes_client = MesClient(
        base_url=settings.mes_base_url,
        login=settings.mes_login,
        password=settings.mes_password,
    )
    scheduler = BatScheduler(bot=bot, mes_client=mes_client, settings=settings)

    dp["settings"] = settings
    dp["mes_client"] = mes_client
    dp["scheduler"] = scheduler

    health_runner = await start_health_server(settings.port)
    scheduler.start()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.stop()
        await mes_client.close()
        await health_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
