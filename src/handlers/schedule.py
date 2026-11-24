from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.config import Settings
from src.services.formatter import (
    format_evening_digest,
    format_grades_summary,
    format_morning_digest,
    format_works_digest,
)
from src.services.mes_client import MesAuthError, MesClient
from src.services.scheduler import BatScheduler
from src.utils.text import escape_html, split_telegram_message


router = Router(name="schedule")

_AUTH_REQUIRED_TEXT = (
    "🔐 Сначала подключи свой аккаунт <code>edu.mes.ru</code> командой /login (или /start)."
)


async def _reply_long(message: Message, text: str) -> None:
    for chunk in split_telegram_message(text):
        await message.answer(chunk, disable_web_page_preview=True)


async def _handle_error(wait_msg: Message, exc: Exception) -> None:
    if isinstance(exc, MesAuthError):
        await wait_msg.edit_text(
            "⚠️ Не удалось войти в <code>edu.mes.ru</code> (возможно, изменился пароль).\n"
            "Обнови данные командой /login."
        )
        return
    await wait_msg.edit_text(f"⚠️ Не удалось получить данные: <code>{escape_html(str(exc))}</code>")


@router.message(Command("morning"))
async def cmd_morning(
    message: Message,
    mes_client: Optional[MesClient],
    settings: Settings,
) -> None:
    """Утренняя сводка на сегодня (расписание + работы + ДЗ)."""
    if mes_client is None:
        await message.answer(_AUTH_REQUIRED_TEXT)
        return

    wait_msg = await message.answer("🦇 Загружаю сводку на сегодня...")
    today = datetime.now(settings.tz).date()
    try:
        schedule, homeworks, works = await mes_client.fetch_morning_data(today)
        text = format_morning_digest(
            schedule,
            homeworks,
            works=works,
            title="🌅 Сводка на сегодня",
        )
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await _handle_error(wait_msg, exc)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(
    message: Message,
    mes_client: Optional[MesClient],
    settings: Settings,
) -> None:
    """Расписание, работы и ДЗ на завтра."""
    if mes_client is None:
        await message.answer(_AUTH_REQUIRED_TEXT)
        return

    wait_msg = await message.answer("🦇 Загружаю данные на завтра...")
    tomorrow = datetime.now(settings.tz).date() + timedelta(days=1)
    try:
        schedule, homeworks, works = await mes_client.fetch_morning_data(tomorrow)
        text = format_morning_digest(
            schedule,
            homeworks,
            works=works,
            title="📆 Сводка на завтра",
        )
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await _handle_error(wait_msg, exc)


@router.message(Command("evening"))
async def cmd_evening(
    message: Message,
    mes_client: Optional[MesClient],
    scheduler: BatScheduler,
    settings: Settings,
) -> None:
    """Вечерняя сводка: новые оценки за сегодня + ДЗ и вложения."""
    if mes_client is None:
        await message.answer(_AUTH_REQUIRED_TEXT)
        return

    wait_msg = await message.answer("🦇 Собираю оценки и ДЗ...")
    today = datetime.now(settings.tz).date()
    try:
        target = await scheduler.find_next_school_date(mes_client, today)
        homeworks, today_grades = await asyncio.gather(
            mes_client.fetch_hometasks(target),
            mes_client.fetch_grades_for_date(today),
        )
        text = format_evening_digest(
            today,
            homeworks,
            next_school_date=target,
            today_grades=today_grades,
        )
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await _handle_error(wait_msg, exc)


@router.message(Command("works", "tests"))
async def cmd_works(
    message: Message,
    mes_client: Optional[MesClient],
    settings: Settings,
) -> None:
    """Ближайшие контрольные, суммативные и формативные работы."""
    if mes_client is None:
        await message.answer(_AUTH_REQUIRED_TEXT)
        return

    wait_msg = await message.answer("🦇 Загружаю календарь работ...")
    today = datetime.now(settings.tz).date()
    try:
        works = await mes_client.fetch_works(from_date=today, days=14)
        text = format_works_digest(works, start_date=today, days=14)
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await _handle_error(wait_msg, exc)


@router.message(Command("grades", "marks"))
async def cmd_grades(
    message: Message,
    mes_client: Optional[MesClient],
    settings: Settings,
) -> None:
    """Оценки за сегодня и вчера."""
    if mes_client is None:
        await message.answer(_AUTH_REQUIRED_TEXT)
        return

    wait_msg = await message.answer("🦇 Загружаю оценки...")
    today = datetime.now(settings.tz).date()
    try:
        subjects = await mes_client.fetch_grades()
        text = format_grades_summary(subjects, today=today)
        await wait_msg.delete()
        await _reply_long(message, text)
    except Exception as exc:
        await _handle_error(wait_msg, exc)
