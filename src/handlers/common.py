from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from src.config import Settings
from src.services.database import UserRepository
from src.services.scheduler import BatScheduler


router = Router(name="common")


@router.message(Command("avatar"))
async def cmd_avatar(message: Message, settings: Settings) -> None:
    """Отправляет сгенерированную аватарку Bat."""
    if not settings.avatar_path.exists():
        await message.answer("◆ Файл аватарки не найден.")
        return

    photo = FSInputFile(settings.avatar_path)
    await message.answer_photo(photo=photo, caption="<b>BAT</b> · аватар")


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    settings: Settings,
    user_repo: UserRepository,
    scheduler: BatScheduler,
) -> None:
    """Статистика бота (только для владельца)."""
    if message.from_user is None or message.from_user.id != settings.admin_id:
        return

    count = await user_repo.count_users()
    status = scheduler.get_status()
    uptime_min = status["uptime_seconds"] // 60
    text = (
        "<b>BAT</b> · Телеметрия системы\n\n"
        f"▪ Пользователей: <b>{count}</b>\n"
        f"▪ Аптайм: <b>{uptime_min} мин</b> <i>(с {status['started_at']})</i>\n"
        f"▪ Self-ping: <b>{status['self_ping_count']}</b> <i>(последний: {status['last_self_ping_at']})</i>\n"
        f"▪ Утро: <code>{status['morning_time']}</code> <i>(отправлено: {status['last_morning_sent_at']})</i>\n"
        f"▪ Вечер (+{status['evening_offset_minutes']} мин): <code>{status['next_evening_at']}</code>\n"
        f"▪ Ошибка: <code>{status['last_error']}</code>"
    )
    await message.answer(text)
