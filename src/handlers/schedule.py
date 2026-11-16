from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.config import Settings
from src.services.formatter import format_evening_digest, format_morning_digest
from src.services.mes_client import MesClient
from src.services.scheduler import BatScheduler
from src.utils.text import split_telegram_message


router = Router(name="schedule")


async def _reply_long(message: Message, text: str) -> None:
    for chunk in split_telegram_message(text):
        await message.answer(chunk, disable_web_page_preview=True)


@router.message(Command("morning"))
async def cmd_morning(message: Message, mes_client: MesClient, settings: Settings) -> None:
    """Утренняя сводка на сегодня (расписание + ДЗ)."""
    wait_msg = await message.answer("🦇 Загружаю сводку на сегодня...")
    today = datetime.now(settings.tz).date()
    try:
        schedule, homeworks = await mes_client.fetch_day_data(today)
        text = format_morning_digest(schedule, homeworks, title="🌅 Сводка на сегодня")
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await wait_msg.edit_text(f"⚠️ Не удалось получить данные: <code>{exc}</code>")


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, mes_client: MesClient, settings: Settings) -> None:
    """Расписание и ДЗ на завтра."""
    wait_msg = await message.answer("🦇 Загружаю данные на завтра...")
    tomorrow = datetime.now(settings.tz).date() + timedelta(days=1)
    try:
        schedule, homeworks = await mes_client.fetch_day_data(tomorrow)
        text = format_morning_digest(schedule, homeworks, title="📆 Сводка на завтра")
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await wait_msg.edit_text(f"⚠️ Не удалось получить данные: <code>{exc}</code>")


@router.message(Command("evening"))
async def cmd_evening(
    message: Message,
    mes_client: MesClient,
    scheduler: BatScheduler,
    settings: Settings,
) -> None:
    """Вечерняя сводка: ДЗ и вложения на следующий учебный день."""
    wait_msg = await message.answer("🦇 Собираю ДЗ и вложения...")
    today = datetime.now(settings.tz).date()
    try:
        target = await scheduler.find_next_school_date(today)
        homeworks = await mes_client.fetch_hometasks(target)
        text = format_evening_digest(today, homeworks, next_school_date=target)
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await wait_msg.edit_text(f"⚠️ Не удалось получить ДЗ: <code>{exc}</code>")
