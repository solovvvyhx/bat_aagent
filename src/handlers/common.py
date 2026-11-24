from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from src.config import Settings


router = Router(name="common")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Приветствие и список доступных команд."""
    text = (
        "🦇 <b>Bat</b> на связи.\n\n"
        "Автономный ассистент для <code>edu.mes.ru</code>.\n\n"
        "<b>Команды:</b>\n"
        "• /morning — утренняя сводка на сегодня (расписание, работы, ДЗ)\n"
        "• /tomorrow — сводка на завтра\n"
        "• /evening — вечерняя сводка (новые оценки за сегодня + ДЗ и вложения)\n"
        "• /works (или /tests) — ближайшие контрольные и работы на 14 дней\n"
        "• /grades (или /marks) — оценки за сегодня и вчера\n"
        "• /avatar — минималистичная аватарка Bat"
    )
    await message.answer(text)


@router.message(Command("avatar"))
async def cmd_avatar(message: Message, settings: Settings) -> None:
    """Отправляет сгенерированную аватарку Bat."""
    if not settings.avatar_path.exists():
        await message.answer("⚠️ Файл аватарки не найден.")
        return

    photo = FSInputFile(settings.avatar_path)
    await message.answer_photo(photo=photo, caption="🦇 Bat — минималистичная аватарка")
