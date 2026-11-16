from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from src.models import Attachment, DaySchedule, HomeworkItem, Lesson


logger = logging.getLogger(__name__)

_WEEKDAY_TO_INDEX = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "четверг": 3,
    "пятница": 4,
    "суббота": 5,
    "воскресенье": 6,
}

_TIME_PAIR_RE = re.compile(r"(\d{1,2})[:](\d{2})\s*[-–]\s*(\d{1,2})[:](\d{2})")
_ROOM_RE = re.compile(r"\bауд\.\s*([^\s,]+)\s*(.*)$", re.IGNORECASE)
_GROUP_TAG_RE = re.compile(r"\s*\((?:гр\.|проф|баз)[^)]*\)", re.IGNORECASE)


class MesAuthError(RuntimeError):
    """Ошибка авторизации на edu.mes.ru."""


class MesClient:
    """Асинхронный клиент edu.mes.ru (httpx + cookie, Yii2 CSRF)."""

    def __init__(
        self,
        base_url: str,
        login: str,
        password: str,
        timeout: float = 45.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._login = login
        self._password = password
        self._timeout = timeout
        self._auth_lock = asyncio.Lock()
        self._is_authenticated = False

        # IPv4 transport: edu.mes.ru может зависать на IPv6 handshake
        transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=2)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            transport=transport,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                )
            },
        )

    async def close(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def ensure_authenticated(self, force: bool = False) -> None:
        """Гарантирует активную сессию на edu.mes.ru."""
        if self._is_authenticated and not force:
            return
        async with self._auth_lock:
            if self._is_authenticated and not force:
                return
            await self._perform_login()

    async def _perform_login(self) -> None:
        """Выполняет вход через Yii2 CSRF-форму POST /login."""
        logger.info("Выполняю вход на %s для пользователя %s", self._base_url, self._login)
        resp = await self._client.get("/login")
        resp.raise_for_status()

        csrf = self._extract_login_csrf(resp.text)
        if not csrf:
            raise MesAuthError("Не удалось найти CSRF-токен на странице /login")

        payload = {
            "_csrf": csrf,
            "LoginForm[username]": self._login,
            "LoginForm[password]": self._password,
            "LoginForm[rememberMe]": "1",
        }
        post_resp = await self._client.post(
            "/login",
            data=payload,
            headers={
                "Referer": f"{self._base_url}/login",
                "Origin": self._base_url,
            },
        )
        post_resp.raise_for_status()

        if "/login" in str(post_resp.url) or 'id="login-form"' in post_resp.text:
            self._is_authenticated = False
            raise MesAuthError("Неверный логин или пароль от edu.mes.ru")

        self._is_authenticated = True
        logger.info("Успешный вход на edu.mes.ru (%s)", post_resp.url)

    async def _get_authenticated(self, path: str) -> httpx.Response:
        """GET-запрос с автоматическим повторным логином при протухшей сессии."""
        await self.ensure_authenticated()
        resp = await self._client.get(path)
        if "/login" in str(resp.url) or 'id="login-form"' in resp.text:
            logger.info("Сессия истекла, выполняю повторный вход")
            await self.ensure_authenticated(force=True)
            resp = await self._client.get(path)
        resp.raise_for_status()
        return resp

    async def fetch_day_data(self, target_date: date) -> tuple[DaySchedule, list[HomeworkItem]]:
        """Параллельно загружает расписание и домашние задания на указанную дату."""
        await self.ensure_authenticated()
        schedule_resp, hometasks_resp = await asyncio.gather(
            self._get_authenticated("/psychologistmentor/schedules/student"),
            self._get_authenticated("/psychologistmentor/schedules/hometasks"),
        )

        schedule = self._parse_schedule(schedule_resp.text, target_date)
        homeworks = await self._parse_hometasks(hometasks_resp.text, target_date)
        return schedule, homeworks

    async def fetch_schedule(self, target_date: date) -> DaySchedule:
        """Загружает только расписание на указанную дату."""
        resp = await self._get_authenticated("/psychologistmentor/schedules/student")
        return self._parse_schedule(resp.text, target_date)

    async def fetch_hometasks(self, target_date: date) -> list[HomeworkItem]:
        """Загружает только ДЗ (с вложениями) на указанную дату."""
        resp = await self._get_authenticated("/psychologistmentor/schedules/hometasks")
        return await self._parse_hometasks(resp.text, target_date)

    @staticmethod
    def _extract_login_csrf(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "lxml")
        inp = soup.select_one('form#login-form input[name="_csrf"]')
        if inp and inp.get("value"):
            return str(inp["value"])
        meta = soup.select_one('meta[name="csrf-token"]')
        if meta and meta.get("content"):
            return str(meta["content"])
        return None

    def _parse_schedule(self, html: str, target_date: date) -> DaySchedule:
        """Парсит таблицу расписания на нужный день недели."""
        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("table.table-striped")
        if not table:
            logger.warning("Таблица расписания не найдена")
            return DaySchedule(target_date=target_date, lessons=[])

        target_weekday = target_date.weekday()
        current_weekday: Optional[int] = None
        lessons: list[Lesson] = []

        for tr in table.find_all("tr"):
            # Пропускаем вложенные <tr> из внутренних таблиц
            if tr.find_parent("table") is not table:
                continue

            if "success" in (tr.get("class") or []):
                day_name = tr.get_text(" ", strip=True).lower()
                current_weekday = _WEEKDAY_TO_INDEX.get(day_name)
                continue

            if current_weekday != target_weekday:
                continue

            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue

            num_text = tds[0].get_text(strip=True)
            if not num_text.isdigit():
                # Это Ассамблея, Завтрак, Перемена или Обед
                continue

            lesson_number = int(num_text)
            time_pair = self._parse_time_cell(tds[1])
            if not time_pair:
                continue
            start_t, end_t = time_pair

            raw_info = tds[2].get_text(" ", strip=True)
            subject, room, teacher = self._parse_lesson_info(raw_info)
            if not subject:
                continue

            lessons.append(
                Lesson(
                    number=lesson_number,
                    subject=subject,
                    start_time=start_t,
                    end_time=end_t,
                    room=room,
                    teacher=teacher,
                )
            )

        return DaySchedule(target_date=target_date, lessons=lessons)

    @staticmethod
    def _parse_time_cell(td: Any) -> Optional[tuple[time, time]]:
        # В ячейке формат: 09<sup>00</sup>-09<sup>40</sup>
        raw_html = str(td)
        normalized = re.sub(r"<sup[^>]*>(\d{2})</sup>", r":\1", raw_html)
        text = BeautifulSoup(normalized, "lxml").get_text(" ", strip=True)
        m = _TIME_PAIR_RE.search(text)
        if not m:
            return None
        sh, sm, eh, em = map(int, m.groups())
        return time(sh, sm), time(eh, em)

    @staticmethod
    def _parse_lesson_info(raw_info: str) -> tuple[str, Optional[str], Optional[str]]:
        text = re.sub(r"\s+", " ", raw_info).strip()
        room: Optional[str] = None
        teacher: Optional[str] = None

        room_match = _ROOM_RE.search(text)
        if room_match:
            room = room_match.group(1).strip()
            teacher_raw = room_match.group(2).strip()
            teacher = teacher_raw or None
            text = text[: room_match.start()].strip()

        # Убираем служебные теги (гр. B), (проф) и т.д.
        subject = _GROUP_TAG_RE.sub("", text).strip()
        # Если длинное уточнение в скобках вроде "Математика (Алгебра и начала анализа...)", сократим
        if subject.startswith("Математика ("):
            subject = "Математика"

        return subject, room, teacher

    async def _parse_hometasks(self, html: str, target_date: date) -> list[HomeworkItem]:
        """Извлекает ДЗ из dataResult и параллельно подгружает вложения."""
        student_match = re.search(r"var\s+id_student\s*=\s*(\d+)\s*;", html)
        data_match = re.search(r"var\s+dataResult\s*=\s*(\[.*?\])\s*;", html, flags=re.S)
        csrf_match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)

        if not data_match:
            logger.warning("dataResult не найден на странице ДЗ")
            return []

        raw_events: list[dict[str, Any]] = json.loads(data_match.group(1))
        student_id = int(student_match.group(1)) if student_match else None
        csrf_token = csrf_match.group(1) if csrf_match else None

        matching_events: list[dict[str, Any]] = []
        for ev in raw_events:
            title = (ev.get("title") or "").strip()
            if not title or title == "Настрой на учебную деятельность":
                continue

            end_str = ev.get("end") or ev.get("start")
            if not end_str:
                continue

            try:
                # FullCalendar хранит end как exclusive (+1 день к DateTo)
                end_dt = datetime.strptime(end_str[:10], "%Y-%m-%d").date()
                due_date = end_dt - timedelta(days=1) if ev.get("end") else end_dt
            except ValueError:
                continue

            if due_date == target_date:
                matching_events.append(ev)

        if not matching_events:
            return []

        # Параллельно запрашиваем вложения для ДЗ этого дня
        attachments_map: dict[int, list[Attachment]] = {}
        if student_id and csrf_token:
            tasks = [
                self._fetch_hometask_files(int(ev["id"]), student_id, csrf_token)
                for ev in matching_events
                if ev.get("id") is not None
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for ev, res in zip(matching_events, results):
                if isinstance(res, list):
                    attachments_map[int(ev["id"])] = res
                elif isinstance(res, Exception):
                    logger.warning("Ошибка загрузки вложений для ДЗ %s: %s", ev.get("id"), res)

        items: list[HomeworkItem] = []
        for ev in matching_events:
            ev_id = int(ev["id"]) if ev.get("id") is not None else 0
            title = _GROUP_TAG_RE.sub("", str(ev.get("title", ""))).strip()
            if title.startswith("Математика ("):
                title = "Математика"

            raw_desc = (ev.get("extendedProps") or {}).get("description") or ""
            clean_desc = self._clean_homework_html(raw_desc)

            items.append(
                HomeworkItem(
                    subject=title,
                    text=clean_desc,
                    due_date=target_date,
                    attachments=attachments_map.get(ev_id, []),
                )
            )

        return items

    async def _fetch_hometask_files(
        self,
        event_id: int,
        student_id: int,
        csrf_token: str,
    ) -> list[Attachment]:
        """Загружает список прикреплённых файлов для конкретного ДЗ."""
        resp = await self._client.post(
            "/psychologistmentor/schedules/ajax-get-update-hometasks",
            data={"id": str(event_id), "id_student": str(student_id)},
            headers={
                "X-CSRF-Token": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw_files = data.get("files") or []

        attachments: list[Attachment] = []
        for f in raw_files:
            name = (f.get("name") or "Файл").strip()
            rel_url = (f.get("url") or "").strip()
            if not rel_url:
                continue
            full_url = (
                rel_url
                if rel_url.startswith("http")
                else f"{self._base_url}/uploads/hometasks/{rel_url.lstrip('/')}"
            )
            attachments.append(Attachment(name=name, url=full_url))
        return attachments

    @staticmethod
    def _clean_homework_html(raw_html: str) -> str:
        """Преобразует HTML-описание ДЗ в чистый текст с переносами строк."""
        if not raw_html:
            return ""
        text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
        soup = BeautifulSoup(text, "lxml")
        clean = soup.get_text()
        # Схлопываем лишние пустые строки
        lines = [line.strip() for line in clean.splitlines()]
        compacted = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", compacted).strip()
