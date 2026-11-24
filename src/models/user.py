from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """Модель зарегистрированного пользователя Bat."""

    telegram_id: int
    mes_login: str
    mes_password: str
    timezone: str = "Europe/Moscow"
    is_admin: bool = False
    username: Optional[str] = None
    full_name: Optional[str] = None
    morning_enabled: bool = True
    evening_enabled: bool = True
