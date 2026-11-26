from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Конфигурация приложения из переменных окружения и .env."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    admin_id: int = 5267340908

    mes_login: str = ""
    mes_password: str = ""
    mes_base_url: str = "https://edu.mes.ru"

    timezone: str = "Europe/Moscow"
    morning_time: str = "07:30"
    evening_offset_minutes: int = 10

    port: int = 8080
    render_external_url: str = ""
    keepalive_url: str = ""
    keepalive_interval_minutes: int = 5

    # База данных и шифрование (Этап 4: мульти-юзер)
    encryption_key: str = ""
    database_url: str = "sqlite:///bat.db"
    max_concurrent_users: int = 5

    @property
    def async_database_url(self) -> str:
        """Нормализует DATABASE_URL для асинхронного SQLAlchemy (SQLite / PostgreSQL)."""
        url = self.database_url.strip()
        # Если случайно скопировали целиком команду `psql 'postgresql://...'` из Neon
        if url.startswith("psql "):
            url = url[len("psql ") :].strip()
        url = url.strip("'\"")
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://") :]
        if url.startswith("sqlite:///") and "+aiosqlite" not in url:
            return "sqlite+aiosqlite:///" + url[len("sqlite:///") :]
        return url

    @property
    def effective_keepalive_url(self) -> str:
        """Возвращает внешний URL сервиса для self-ping (/health)."""
        base = (self.keepalive_url or self.render_external_url).strip().rstrip("/")
        if not base:
            return ""
        return base if base.endswith("/health") else f"{base}/health"

    @property
    def tz(self) -> ZoneInfo:
        """Возвращает объект часового пояса."""
        return ZoneInfo(self.timezone)

    @property
    def avatar_path(self) -> Path:
        """Путь к файлу аватарки бота."""
        return BASE_DIR / "assets" / "avatar.jpg"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает синглтон настроек приложения."""
    return Settings()
