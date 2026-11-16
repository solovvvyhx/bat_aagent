from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional


@dataclass
class Attachment:
    """Вложение к домашнему заданию."""

    name: str
    url: str


@dataclass
class HomeworkItem:
    """Домашнее задание по предмету."""

    subject: str
    text: str
    due_date: Optional[date] = None
    teacher: Optional[str] = None
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class Lesson:
    """Одиночный урок в расписании."""

    number: Optional[int]
    subject: str
    start_time: time
    end_time: time
    room: Optional[str] = None
    teacher: Optional[str] = None


@dataclass
class PairedLesson:
    """Объединённая пара (или одиночный урок) для отображения."""

    subject: str
    start_time: time
    end_time: time
    is_pair: bool = False
    room: Optional[str] = None
    teacher: Optional[str] = None
    lesson_numbers: list[int] = field(default_factory=list)

    @property
    def time_range(self) -> str:
        """Форматированный интервал времени ЧЧ:ММ–ЧЧ:ММ."""
        return f"{self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')}"


@dataclass
class DaySchedule:
    """Расписание на конкретный день."""

    target_date: date
    lessons: list[Lesson] = field(default_factory=list)

    @property
    def last_lesson_end(self) -> Optional[time]:
        """Время окончания последнего урока дня."""
        if not self.lessons:
            return None
        return max(lesson.end_time for lesson in self.lessons)
