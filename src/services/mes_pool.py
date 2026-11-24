from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.models import User
from src.services.mes_client import MesClient


logger = logging.getLogger(__name__)


class MesClientPool:
    """Кэш авторизованных клиентов edu.mes.ru по telegram_id."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._clients: dict[int, MesClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, user: User) -> MesClient:
        """Возвращает существующий или создаёт новый MesClient для пользователя."""
        async with self._lock:
            existing = self._clients.get(user.telegram_id)
            if (
                existing is not None
                and existing.login == user.mes_login
                and existing.password == user.mes_password
            ):
                return existing

            if existing is not None:
                await existing.close()

            client = MesClient(
                base_url=self._base_url,
                login=user.mes_login,
                password=user.mes_password,
            )
            self._clients[user.telegram_id] = client
            return client

    async def verify_credentials(self, login: str, password: str) -> Optional[str]:
        """Проверяет логин/пароль на edu.mes.ru и возвращает ФИО студента."""
        client = MesClient(base_url=self._base_url, login=login, password=password)
        try:
            await client.ensure_authenticated(force=True)
            return client.student_name
        finally:
            await client.close()

    async def invalidate(self, telegram_id: int) -> None:
        """Удаляет и закрывает клиент пользователя из кэша."""
        async with self._lock:
            client = self._clients.pop(telegram_id, None)
        if client is not None:
            await client.close()

    async def close_all(self) -> None:
        """Закрывает все активные HTTP-клиенты."""
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        await asyncio.gather(*(c.close() for c in clients), return_exceptions=True)
