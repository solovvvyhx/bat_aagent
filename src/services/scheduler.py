from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import Settings
from src.models import User
from src.services.database import UserRepository
from src.services.formatter import format_evening_digest, format_morning_digest
from src.services.mes_client import MesAuthError, MesClient
from src.services.mes_pool import MesClientPool
from src.utils.text import split_telegram_message


logger = logging.getLogger(__name__)


class BatScheduler:
    """Персональный планировщик утренних и вечерних сводок для всех пользователей."""

    def __init__(
        self,
        bot: Bot,
        user_repo: UserRepository,
        mes_pool: MesClientPool,
        settings: Settings,
    ) -> None:
        self._bot = bot
        self._user_repo = user_repo
        self._mes_pool = mes_pool
        self._settings = settings
        self._scheduler = AsyncIOScheduler(timezone=settings.tz)
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_users))

        self._started_at: datetime = datetime.now(settings.tz)
        self._self_ping_count: int = 0
        self._last_self_ping_at: Optional[str] = None
        self._last_morning_sent_at: Optional[str] = None
        self._next_evening_at: Optional[str] = None
        self._last_evening_sent_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._cached_users_count: int = 0

    def get_status(self) -> dict[str, Any]:
        """Возвращает телеметрию планировщика для /health."""
        now = datetime.now(self._settings.tz)
        return {
            "started_at": self._started_at.isoformat(timespec="seconds"),
            "uptime_seconds": int((now - self._started_at).total_seconds()),
            "users_count": self._cached_users_count,
            "morning_time": self._settings.morning_time,
            "evening_offset_minutes": self._settings.evening_offset_minutes,
            "self_ping_count": self._self_ping_count,
            "last_self_ping_at": self._last_self_ping_at,
            "last_morning_sent_at": self._last_morning_sent_at,
            "next_evening_at": self._next_evening_at,
            "last_evening_sent_at": self._last_evening_sent_at,
            "last_error": self._last_error,
        }

    def start(self) -> None:
        """Запускает планировщик и регистрирует задачи."""
        hour, minute = map(int, self._settings.morning_time.split(":"))
        self._scheduler.add_job(
            self.send_morning_digest_all,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=self._settings.tz),
            id="morning_digest_all",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self.schedule_today_evening_all,
            trigger=DateTrigger(run_date=datetime.now(self._settings.tz) + timedelta(seconds=5)),
            id="init_evening_schedule_all",
            replace_existing=True,
        )
        if self._settings.effective_keepalive_url:
            self._scheduler.add_job(
                self._self_ping,
                trigger=IntervalTrigger(minutes=self._settings.keepalive_interval_minutes),
                id="self_keepalive_ping",
                replace_existing=True,
            )
            logger.info(
                "Self-keepalive включён: %s каждые %s мин",
                self._settings.effective_keepalive_url,
                self._settings.keepalive_interval_minutes,
            )
        self._scheduler.start()
        logger.info("Планировщик запущен (утро в %s %s)", self._settings.morning_time, self._settings.timezone)

    def stop(self) -> None:
        """Останавливает планировщик."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def refresh_users_count(self) -> int:
        """Обновляет кэш количества пользователей для /health."""
        self._cached_users_count = await self._user_repo.count_users()
        return self._cached_users_count

    async def _self_ping(self) -> None:
        """Пингует внешний /health endpoint, чтобы сбрасывать таймер сна Render."""
        url = self._settings.effective_keepalive_url
        if not url:
            return
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                self._self_ping_count += 1
                self._last_self_ping_at = datetime.now(self._settings.tz).isoformat(timespec="seconds")
                logger.info("Self-keepalive ping %s -> %s", url, resp.status_code)
        except Exception as exc:
            self._last_error = f"self_ping: {exc}"
            logger.warning("Self-keepalive ping failed (%s): %s", url, exc)

    async def send_morning_digest_all(self) -> None:
        """Рассылает утреннюю сводку всем активным пользователям и ставит их вечерние сводки."""
        users = await self._user_repo.list_active_users()
        self._cached_users_count = len(users)
        if not users:
            return
        await asyncio.gather(*(self._send_morning_for_user(u) for u in users if u.morning_enabled))

    async def _send_morning_for_user(self, user: User) -> None:
        today = datetime.now(self._settings.tz).date()
        async with self._semaphore:
            try:
                client = await self._mes_pool.get_client(user)
                schedule, homeworks, works = await client.fetch_morning_data(today)
                if not schedule.lessons:
                    logger.info("У пользователя %s сегодня (%s) уроков нет.", user.telegram_id, today)
                    return

                text = format_morning_digest(schedule, homeworks, works=works)
                await self._send_long_message(user.telegram_id, text)
                self._last_morning_sent_at = datetime.now(self._settings.tz).isoformat(timespec="seconds")
                if user.evening_enabled:
                    await self._schedule_evening_job(user.telegram_id, schedule.target_date, schedule.last_lesson_end)
            except MesAuthError:
                await self._notify_auth_expired(user.telegram_id)
            except TelegramForbiddenError:
                logger.warning("Пользователь %s заблокировал бота", user.telegram_id)
            except Exception as exc:
                self._last_error = f"morning({user.telegram_id}): {exc}"
                logger.exception("Ошибка утренней сводки для %s", user.telegram_id)

    async def schedule_today_evening_all(self) -> None:
        """При старте планирует сегодняшнюю вечернюю сводку для всех пользователей."""
        users = await self._user_repo.list_active_users()
        self._cached_users_count = len(users)
        await asyncio.gather(*(self.schedule_evening_for_user(u) for u in users if u.evening_enabled))

    async def schedule_evening_for_user(self, user: User) -> None:
        """Проверяет расписание пользователя на сегодня и ставит вечернюю сводку."""
        today = datetime.now(self._settings.tz).date()
        async with self._semaphore:
            try:
                client = await self._mes_pool.get_client(user)
                schedule = await client.fetch_schedule(today)
                await self._schedule_evening_job(user.telegram_id, today, schedule.last_lesson_end)
            except Exception as exc:
                logger.warning("Не удалось запланировать вечернюю сводку для %s: %s", user.telegram_id, exc)

    def unschedule_user(self, telegram_id: int) -> None:
        """Удаляет запланированную вечернюю сводку пользователя (при /logout)."""
        today = datetime.now(self._settings.tz).date()
        job_id = f"evening_digest_{telegram_id}_{today.isoformat()}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    async def _schedule_evening_job(self, telegram_id: int, day: date, last_end) -> None:
        if last_end is None:
            return

        run_at = datetime.combine(day, last_end, tzinfo=self._settings.tz) + timedelta(
            minutes=self._settings.evening_offset_minutes
        )
        now = datetime.now(self._settings.tz)
        if run_at <= now:
            return

        job_id = f"evening_digest_{telegram_id}_{day.isoformat()}"
        self._scheduler.add_job(
            self._send_evening_for_user_id,
            trigger=DateTrigger(run_date=run_at),
            args=[telegram_id],
            id=job_id,
            replace_existing=True,
        )
        if telegram_id == self._settings.admin_id or self._next_evening_at is None:
            self._next_evening_at = run_at.isoformat(timespec="seconds")
        logger.info("Вечерняя сводка для %s запланирована на %s", telegram_id, run_at.strftime("%Y-%m-%d %H:%M"))

    async def _send_evening_for_user_id(self, telegram_id: int) -> None:
        user = await self._user_repo.get_user(telegram_id)
        if user is None or not user.evening_enabled:
            return

        today = datetime.now(self._settings.tz).date()
        async with self._semaphore:
            try:
                client = await self._mes_pool.get_client(user)
                target = await self.find_next_school_date(client, today)
                homeworks, today_grades = await asyncio.gather(
                    client.fetch_hometasks(target),
                    client.fetch_grades_for_date(today),
                )
                text = format_evening_digest(
                    today,
                    homeworks,
                    next_school_date=target,
                    today_grades=today_grades,
                )
                await self._send_long_message(user.telegram_id, text)
                self._last_evening_sent_at = datetime.now(self._settings.tz).isoformat(timespec="seconds")
            except MesAuthError:
                await self._notify_auth_expired(user.telegram_id)
            except TelegramForbiddenError:
                logger.warning("Пользователь %s заблокировал бота", user.telegram_id)
            except Exception as exc:
                self._last_error = f"evening({telegram_id}): {exc}"
                logger.exception("Ошибка вечерней сводки для %s", telegram_id)

    async def find_next_school_date(self, client: MesClient, from_date: date) -> date:
        """Ищет ближайший день после from_date, в который есть уроки (до +4 дней)."""
        for offset in range(1, 5):
            candidate = from_date + timedelta(days=offset)
            sched = await client.fetch_schedule(candidate)
            if sched.lessons:
                return candidate
        return from_date + timedelta(days=1)

    async def _notify_auth_expired(self, telegram_id: int) -> None:
        try:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=(
                    "⚠️ Не удалось войти в <code>edu.mes.ru</code> (возможно, изменился пароль).\n"
                    "Обнови данные командой /login."
                ),
            )
        except Exception:
            pass

    async def _send_long_message(self, chat_id: int, text: str) -> None:
        for chunk in split_telegram_message(text):
            await self._bot.send_message(
                chat_id=chat_id,
                text=chunk,
                disable_web_page_preview=True,
            )
