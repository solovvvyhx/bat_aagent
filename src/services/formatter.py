from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from src.models import (
    DaySchedule,
    GradeItem,
    HomeworkItem,
    Lesson,
    PairedLesson,
    SubjectGrades,
    WorkItem,
)
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
    if prev.is_pair:
        return False
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


def _format_work_line(work: WorkItem) -> str:
    icon = "🔴" if work.kind == "Summative" else "🟠"
    kind_ru = "Итоговая" if work.kind == "Summative" else "Текущая"
    return (
        f"{icon} <b>{escape_html(work.subject)}</b> "
        f"<i>({kind_ru})</i> — {escape_html(work.title)}"
    )


def _format_grade_line(g: GradeItem) -> str:
    icon = "🔴" if g.kind == "Summative" else "🟠"
    details_parts = [p for p in (g.title, g.work_type) if p]
    details = f" — <i>{escape_html(', '.join(details_parts))}</i>" if details_parts else ""
    return f"{icon} <b>{escape_html(g.subject)}</b>: <b>{g.value}</b>{details}"


def format_morning_digest(
    schedule: DaySchedule,
    homeworks: list[HomeworkItem],
    works: Optional[list[WorkItem]] = None,
    title: str = "🌅 Утренняя сводка",
) -> str:
    """Форматирует утреннюю сводку: расписание (с парами) + работы на день + ДЗ."""
    date_str = _format_date_ru(schedule.target_date)
    parts: list[str] = [f"🦇 <b>{escape_html(title)}</b>\n<i>{date_str}</i>"]

    paired = merge_lessons_into_pairs(schedule.lessons)
    if paired:
        lessons_block = "\n".join(_format_paired_lesson(item) for item in paired)
        parts.append(f"📅 <b>Расписание:</b>\n{lessons_block}")
    else:
        parts.append("📅 <b>Расписание:</b>\n<i>Уроков нет — можно выдохнуть.</i>")

    if works:
        works_block = "\n".join(_format_work_line(w) for w in works)
        parts.append(f"📝 <b>Контрольные и работы на день:</b>\n{works_block}")

    if homeworks:
        hw_block = "\n\n".join(_format_homework_item(hw, include_attachments=True) for hw in homeworks)
        parts.append(f"📚 <b>Домашнее задание на день:</b>\n{hw_block}")
    else:
        parts.append("📚 <b>Домашнее задание на день:</b>\n<i>На этот день ДЗ не найдено.</i>")

    return "\n\n".join(parts)


def format_evening_digest(
    target_date: date,
    homeworks: list[HomeworkItem],
    next_school_date: Optional[date] = None,
    today_grades: Optional[list[GradeItem]] = None,
) -> str:
    """Форматирует вечернюю сводку: новые оценки за сегодня + ДЗ и вложения."""
    label_date = next_school_date or target_date
    date_str = _format_date_ru(label_date)
    parts: list[str] = [f"🌙 <b>Вечерняя сводка</b>\n<i>ДЗ на {date_str}</i>"]

    if today_grades:
        grades_block = "\n".join(_format_grade_line(g) for g in today_grades)
        parts.append(f"🎯 <b>Новые оценки за сегодня:</b>\n{grades_block}")

    if homeworks:
        hw_block = "\n\n".join(_format_homework_item(hw, include_attachments=True) for hw in homeworks)
        parts.append(f"📚 <b>Домашние задания:</b>\n{hw_block}")
    else:
        parts.append("📚 <b>Домашние задания:</b>\n<i>На этот день ДЗ пока нет.</i>")

    return "\n\n".join(parts)


def format_works_digest(works: list[WorkItem], start_date: date, days: int = 14) -> str:
    """Форматирует список ближайших контрольных, суммативных и формативных работ."""
    header = (
        f"📝 <b>Календарь работ</b>\n"
        f"<i>Ближайшие {days} дн. (с {start_date.strftime('%d.%m.%Y')})</i>\n"
        f"<i>🔴 Итоговая (Summative) · 🟠 Текущая (Formative)</i>"
    )
    if not works:
        return f"{header}\n\n<i>На ближайшие {days} дней работ не запланировано.</i>"

    grouped: dict[date, list[WorkItem]] = defaultdict(list)
    for w in works:
        grouped[w.work_date].append(w)

    blocks: list[str] = [header]
    for day in sorted(grouped.keys()):
        lines = [f"<b>📅 {_format_date_ru(day)}</b>"]
        for w in grouped[day]:
            lines.append(_format_work_line(w))
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def format_grades_summary(
    subjects: list[SubjectGrades],
    today: Optional[date] = None,
) -> str:
    """Форматирует текущие оценки по предметам и средний балл."""
    parts: list[str] = ["🎯 <b>Текущие оценки и средний балл</b>"]

    if today is not None:
        today_items = [g for s in subjects for g in s.grades if g.grade_date == today]
        if today_items:
            today_block = "\n".join(_format_grade_line(g) for g in today_items)
            parts.append(f"✨ <b>Сегодня ({today.strftime('%d.%m.%Y')}):</b>\n{today_block}")

    lines: list[str] = []
    all_values: list[int] = []
    for s in subjects:
        if not s.grades:
            continue
        avg = s.average
        vals = [g.value for g in s.grades]
        all_values.extend(vals)
        vals_str = ", ".join(str(v) for v in vals)
        lines.append(
            f"• <b>{escape_html(s.subject)}</b> — <b>{avg:.2f}</b> "
            f"<code>({vals_str})</code>"
        )

    if lines:
        overall = sum(all_values) / len(all_values)
        parts.append("\n".join(lines))
        parts.append(f"📊 <b>Общий средний балл:</b> <b>{overall:.2f}</b> (всего оценок: {len(all_values)})")
    else:
        parts.append("<i>Оценок пока не найдено.</i>")

    return "\n\n".join(parts)
