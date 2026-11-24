from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.config import Settings
from src.models import User
from src.utils.crypto import PasswordCipher


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """ORM-модель таблицы пользователей."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    mes_login: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    morning_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    evening_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class UserRepository:
    """Асинхронный репозиторий пользователей с Fernet-шифрованием паролей."""

    def __init__(self, database_url: str, cipher: PasswordCipher) -> None:
        self._cipher = cipher
        self._ensure_sqlite_dir(database_url)
        clean_url, connect_args = self._prepare_async_engine_args(database_url)
        self._engine: AsyncEngine = create_async_engine(
            clean_url,
            echo=False,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @staticmethod
    def _prepare_async_engine_args(url: str) -> tuple[str, dict[str, Any]]:
        """Адаптирует sslmode/channel_binding из PostgreSQL URL (Neon/Supabase) для asyncpg."""
        if not url.startswith("postgresql+asyncpg://"):
            return url, {}
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        connect_args: dict[str, Any] = {}
        sslmode = params.pop("sslmode", None)
        params.pop("channel_binding", None)
        if sslmode and sslmode != "disable":
            connect_args["ssl"] = "require"
        clean_query = urlencode(params)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, clean_query, parts.fragment))
        return clean_url, connect_args

    @staticmethod
    def _ensure_sqlite_dir(url: str) -> None:
        if "sqlite" not in url:
            return
        # Формат sqlite+aiosqlite:////app/data/bat.db или sqlite+aiosqlite:///bat.db
        parts = url.split(":///", 1)
        if len(parts) == 2 and parts[1] and parts[1] != ":memory:":
            db_path = Path(parts[1])
            if db_path.parent and str(db_path.parent) not in ("", "."):
                db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self) -> None:
        """Создаёт таблицы в БД при первом запуске."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("База данных пользователей инициализирована")

    async def close(self) -> None:
        """Закрывает пул соединений с БД."""
        await self._engine.dispose()

    async def seed_admin_if_missing(self, settings: Settings) -> None:
        """Добавляет владельца из .env в БД, если его ещё нет."""
        if not (settings.admin_id and settings.mes_login and settings.mes_password):
            return
        existing = await self.get_user(settings.admin_id)
        if existing is not None:
            return
        await self.upsert_user(
            telegram_id=settings.admin_id,
            mes_login=settings.mes_login,
            mes_password=settings.mes_password,
            timezone_name=settings.timezone,
            is_admin=True,
        )
        logger.info("Владелец (ID=%s) автоматически добавлен в БД из настроек", settings.admin_id)

    def _row_to_user(self, row: UserRow) -> User:
        return User(
            telegram_id=row.telegram_id,
            mes_login=row.mes_login,
            mes_password=self._cipher.decrypt(row.encrypted_password),
            timezone=row.timezone,
            is_admin=row.is_admin,
            username=row.username,
            full_name=row.full_name,
            morning_enabled=row.morning_enabled,
            evening_enabled=row.evening_enabled,
        )

    async def get_user(self, telegram_id: int) -> Optional[User]:
        async with self._session_factory() as session:
            row = await session.get(UserRow, telegram_id)
            if row is None:
                return None
            return self._row_to_user(row)

    async def upsert_user(
        self,
        telegram_id: int,
        mes_login: str,
        mes_password: str,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        timezone_name: str = "Europe/Moscow",
        is_admin: bool = False,
    ) -> User:
        encrypted = self._cipher.encrypt(mes_password)
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            row = await session.get(UserRow, telegram_id)
            if row is None:
                row = UserRow(
                    telegram_id=telegram_id,
                    username=username,
                    full_name=full_name,
                    mes_login=mes_login,
                    encrypted_password=encrypted,
                    timezone=timezone_name,
                    is_admin=is_admin,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.mes_login = mes_login
                row.encrypted_password = encrypted
                if username is not None:
                    row.username = username
                if full_name is not None:
                    row.full_name = full_name
                row.timezone = timezone_name
                if is_admin:
                    row.is_admin = True
                row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return self._row_to_user(row)

    async def delete_user(self, telegram_id: int) -> bool:
        async with self._session_factory() as session:
            row = await session.get(UserRow, telegram_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def list_active_users(self) -> list[User]:
        async with self._session_factory() as session:
            res = await session.execute(select(UserRow))
            rows = res.scalars().all()
            return [self._row_to_user(r) for r in rows]

    async def count_users(self) -> int:
        async with self._session_factory() as session:
            res = await session.execute(select(func.count(UserRow.telegram_id)))
            return int(res.scalar_one() or 0)
