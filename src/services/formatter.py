from __future__ import annotations

from datetime import date

from src.models import DaySchedule, HomeworkItem, Lesson, PairedLesson
from src.utils.text import escape_html, format_expandable_quote


_WEEKDAYS_RU = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)


def merge_lessons_into_pairs(lessons: list[Lesson]) -> list[PairedLesson]:
    """Объединяет соседние уроки с одинаковым предметом в пары."""
    if not lessons:
        return []

    sorted_lessons = sorted(lessons, key=lambda x: (x.start_time, x.end_time))
    merged: list[PairedLesson] = []

    for lesson in sorted_lessons:
        if merged and _can_merge(merged[-1], lesson):
            prev = merged[-1]
            prev.end_time = max(prev.end_time, lesson.end_time)
            prev.is_pair = True
            if lesson.number is not None:
                prev.lesson_numbers.append(lesson.number)
            if not prev.room and lesson.room:
                prev.room = lesson.room
        else:
            merged.append(
                PairedLesson(
                    subject=lesson.subject,
                    start_time=lesson.start_time,
                    end_time=lesson.end_time,
                    is_pair=False,
                    room=lesson.room,
                    teacher=lesson.teacher,
                    lesson_numbers=[lesson.number] if lesson.number is not None else [],
                )
            )

    return merged


def _can_merge(prev: PairedLesson, nxt: Lesson) -> bool:
    """Проверяет, можно ли объединить соседние уроки в пару."""
    same_subject = prev.subject.strip().lower() == nxt.subject.strip().lower()
    if not same_subject:
        return False
    # Если уже объединили 2 урока в пару, третий такой же урок подряд не сливаем в "тройку"
    if prev.is_pair:
        return False
    # Проверяем, что перерыв между уроками не больше 30 минут
    prev_minutes = prev.end_time.hour * 60 + prev.end_time.minute
    next_minutes = nxt.start_time.hour * 60 + nxt.start_time.minute
    return 0 <= (next_minutes - prev_minutes) <= 30


def _format_date_ru(target_date: date) -> str:
    weekday = _WEEKDAYS_RU[target_date.weekday()]
    return f"{weekday}, {target_date.strftime('%d.%m.%Y')}"


def _format_paired_lesson(item: PairedLesson) -> str:
    subj = escape_html(item.subject)
    prefix = f"Пара · {subj}" if item.is_pair else subj
    line = f"• <b>{prefix}</b> · <code>{item.time_range}</code>"
    if item.room:
        line += f" <i>(каб. {escape_html(item.room)})</i>"
    return line


def _format_homework_item(hw: HomeworkItem, include_attachments: bool = True) -> str:
    subj = escape_html(hw.subject)
    body = format_expandable_quote(hw.text) if hw.text.strip() else "<i>Без текста</i>"
    lines = [f"• <b>{subj}</b>\n{body}"]

    if include_attachments and hw.attachments:
        att_links = [
            f'📎 <a href="{escape_html(att.url)}">{escape_html(att.name)}</a>'
            for att in hw.attachments
        ]
        lines.append("\n".join(att_links))

    return "\n".join(lines)


def format_morning_digest(
    schedule: DaySchedule,
    homeworks: list[HomeworkItem],
    title: str = "🌅 Утренняя сводка",
) -> str:
    """Форматирует утреннюю сводку: расписание (с парами) + ДЗ на день."""
    date_str = _format_date_ru(schedule.target_date)
    parts: list[str] = [f"🦇 <b>{escape_html(title)}</b>\n<i>{date_str}</i>"]

    paired = merge_lessons_into_pairs(schedule.lessons)
    if paired:
        lessons_block = "\n".join(_format_paired_lesson(item) for item in paired)
        parts.append(f"📅 <b>Расписание:</b>\n{lessons_block}")
    else:
        parts.append("📅 <b>Расписание:</b>\n<i>Уроков нет — можно выдохнуть.</i>")

    if homeworks:
        hw_block = "\n\n".join(_format_homework_item(hw, include_attachments=True) for hw in homeworks)
        parts.append(f"📚 <b>Домашнее задание на день:</b>\n{hw_block}")
    else:
        parts.append("📚 <b>Домашнее задание на день:</b>\n<i>На этот день ДЗ не найдено.</i>")

    return "\n\n".join(parts)


def format_evening_digest(
    target_date: date,
    homeworks: list[HomeworkItem],
    next_school_date: date | None = None,
) -> str:
    """Форматирует вечернюю сводку: ДЗ и вложения."""
    label_date = next_school_date or target_date
    date_str = _format_date_ru(label_date)
    header = f"🌙 <b>Вечерняя сводка</b>\n<i>ДЗ на {date_str}</i>"

    if not homeworks:
        return f"{header}\n\n<i>Домашних заданий на этот день пока нет.</i>"

    hw_block = "\n\n".join(_format_homework_item(hw, include_attachments=True) for hw in homeworks)
    return f"{header}\n\n{hw_block}"
