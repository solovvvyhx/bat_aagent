from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """Модель пользователя (задел под мульти-юзер на Этапе 4)."""

    telegram_id: int
    mes_login: str
    mes_password: str
    timezone: str = "Europe/Moscow"
    is_admin: bool = False
    full_name: Optional[str] = None
