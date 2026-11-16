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
        "Автономный ассистент для <code>edu.mes.ru</code> (Этап 1: расписание и ДЗ).\n\n"
        "<b>Команды:</b>\n"
        "• /morning — утренняя сводка на сегодня\n"
        "• /tomorrow — расписание и ДЗ на завтра\n"
        "• /evening — вечерняя сводка (ДЗ и вложения)\n"
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
