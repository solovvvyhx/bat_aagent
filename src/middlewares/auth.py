from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.services.database import UserRepository
from src.services.mes_pool import MesClientPool


class UserContextMiddleware(BaseMiddleware):
    """Подгружает текущего пользователя из БД и его MesClient в контекст хендлера."""

    def __init__(self, user_repo: UserRepository, mes_pool: MesClientPool) -> None:
        self._user_repo = user_repo
        self._mes_pool = mes_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        current_user = None
        mes_client = None

        if tg_user is not None:
            current_user = await self._user_repo.get_user(tg_user.id)
            if current_user is not None:
                mes_client = await self._mes_pool.get_client(current_user)

        data["current_user"] = current_user
        data["mes_client"] = mes_client
        return await handler(event, data)
