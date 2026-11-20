from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from src.config import Settings
from src.services.formatter import format_evening_digest, format_morning_digest
from src.services.mes_client import MesClient
from src.utils.text import split_telegram_message


logger = logging.getLogger(__name__)


class BatScheduler:
    """Планировщик утренних и динамических вечерних сводок."""

    def __init__(self, bot: Bot, mes_client: MesClient, settings: Settings) -> None:
        self._bot = bot
        self._mes = mes_client
        self._settings = settings
        self._scheduler = AsyncIOScheduler(timezone=settings.tz)

    def start(self) -> None:
        """Запускает планировщик и регистрирует задачи."""
        hour, minute = map(int, self._settings.morning_time.split(":"))
        self._scheduler.add_job(
            self.send_morning_digest,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=self._settings.tz),
            id="morning_digest",
            replace_existing=True,
        )
        # Также запланируем сегодняшнюю вечернюю сводку при старте (если ещё не поздно)
        self._scheduler.add_job(
            self.schedule_today_evening,
            trigger=DateTrigger(run_date=datetime.now(self._settings.tz) + timedelta(seconds=5)),
            id="init_evening_schedule",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("Планировщик запущен (утро в %s %s)", self._settings.morning_time, self._settings.timezone)

    def stop(self) -> None:
        """Останавливает планировщик."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def send_morning_digest(self) -> None:
        """Отправляет утреннюю сводку (расписание + работы + ДЗ) и планирует вечернюю."""
        today = datetime.now(self._settings.tz).date()
        try:
            schedule, homeworks, works = await self._mes.fetch_morning_data(today)
            if not schedule.lessons:
                logger.info("Сегодня (%s) уроков нет, утренняя сводка пропущена.", today)
                return

            text = format_morning_digest(schedule, homeworks, works=works)
            await self._send_long_message(text)
            await self._schedule_evening_for_day(schedule.target_date, schedule.last_lesson_end)
        except Exception:
            logger.exception("Ошибка при отправке утренней сводки")

    async def schedule_today_evening(self) -> None:
        """Проверяет расписание на сегодня и планирует вечернюю сводку, если она ещё впереди."""
        today = datetime.now(self._settings.tz).date()
        try:
            schedule = await self._mes.fetch_schedule(today)
            await self._schedule_evening_for_day(today, schedule.last_lesson_end)
        except Exception:
            logger.exception("Не удалось запланировать вечернюю сводку при старте")

    async def _schedule_evening_for_day(self, day: date, last_end) -> None:
        if last_end is None:
            return

        run_at = datetime.combine(day, last_end, tzinfo=self._settings.tz) + timedelta(
            minutes=self._settings.evening_offset_minutes
        )
        now = datetime.now(self._settings.tz)
        if run_at <= now:
            logger.info("Время вечерней сводки (%s) уже прошло, пропускаем.", run_at)
            return

        self._scheduler.add_job(
            self.send_evening_digest,
            trigger=DateTrigger(run_date=run_at),
            id=f"evening_digest_{day.isoformat()}",
            replace_existing=True,
        )
        logger.info("Вечерняя сводка запланирована на %s", run_at.strftime("%Y-%m-%d %H:%M"))

    async def send_evening_digest(self) -> None:
        """Отправляет вечернюю сводку: новые оценки за сегодня + ДЗ на следующий учебный день."""
        today = datetime.now(self._settings.tz).date()
        try:
            target = await self.find_next_school_date(today)
            homeworks, today_grades = await asyncio.gather(
                self._mes.fetch_hometasks(target),
                self._mes.fetch_grades_for_date(today),
            )
            text = format_evening_digest(
                today,
                homeworks,
                next_school_date=target,
                today_grades=today_grades,
            )
            await self._send_long_message(text)
        except Exception:
            logger.exception("Ошибка при отправке вечерней сводки")

    async def find_next_school_date(self, from_date: date) -> date:
        """Ищет ближайший день после from_date, в который есть уроки (до +4 дней)."""
        for offset in range(1, 5):
            candidate = from_date + timedelta(days=offset)
            sched = await self._mes.fetch_schedule(candidate)
            if sched.lessons:
                return candidate
        return from_date + timedelta(days=1)

    async def _send_long_message(self, text: str) -> None:
        for chunk in split_telegram_message(text):
            await self._bot.send_message(
                chat_id=self._settings.admin_id,
                text=chunk,
                disable_web_page_preview=True,
            )
