from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AdminOnlyMiddleware(BaseMiddleware):
    """Ограничивает доступ к боту только владельцем на Этапах 1–3.

    На Этапе 4 этот middleware будет заменён на UserContextMiddleware,
    подгружающий пользователя из БД.
    """

    def __init__(self, admin_id: int) -> None:
        self._admin_id = admin_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id != self._admin_id:
            if isinstance(event, Message):
                await event.answer("🦇 Доступ пока открыт только владельцу бота.")
            return None
        return await handler(event, data)
