from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from src.config import get_settings
from src.handlers import get_main_router
from src.middlewares import UserContextMiddleware
from src.services import BatScheduler, MesClientPool, UserRepository, start_health_server
from src.utils import PasswordCipher


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def run() -> None:
    """Точка входа: инициализирует БД, /health, планировщик и Telegram-бота."""
    _configure_logging()
    settings = get_settings()

    cipher = PasswordCipher(
        encryption_key=settings.encryption_key,
        fallback_secret=settings.bot_token,
    )
    user_repo = UserRepository(
        database_url=settings.async_database_url,
        cipher=cipher,
    )
    await user_repo.init_db()
    await user_repo.seed_admin_if_missing(settings)

    mes_pool = MesClientPool(base_url=settings.mes_base_url)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(UserContextMiddleware(user_repo=user_repo, mes_pool=mes_pool))
    dp.include_router(get_main_router())

    scheduler = BatScheduler(
        bot=bot,
        user_repo=user_repo,
        mes_pool=mes_pool,
        settings=settings,
    )
    await scheduler.refresh_users_count()

    dp["settings"] = settings
    dp["user_repo"] = user_repo
    dp["mes_pool"] = mes_pool
    dp["scheduler"] = scheduler

    health_runner = await start_health_server(
        settings.port,
        status_provider=scheduler.get_status,
    )
    scheduler.start()

    try:
        await bot.set_my_commands(
            [
                BotCommand(command="morning", description="🌅 Сводка на сегодня (расписание, работы, ДЗ)"),
                BotCommand(command="tomorrow", description="📆 Сводка на завтра"),
                BotCommand(command="evening", description="🌙 Вечерняя сводка (оценки за сегодня + ДЗ)"),
                BotCommand(command="works", description="📝 Ближайшие контрольные и работы (14 дн.)"),
                BotCommand(command="grades", description="🎯 Оценки за сегодня и вчера"),
                BotCommand(command="login", description="🔐 Войти / сменить аккаунт edu.mes.ru"),
                BotCommand(command="logout", description="👋 Отключить аккаунт и рассылки"),
                BotCommand(command="avatar", description="🦇 Аватарка Bat"),
                BotCommand(command="start", description="ℹ️ О боте и список команд"),
            ]
        )
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.stop()
        await mes_pool.close_all()
        await user_repo.close()
        await health_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
