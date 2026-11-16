from __future__ import annotations

import html


TELEGRAM_MESSAGE_LIMIT = 4096


def escape_html(text: str) -> str:
    """Экранирует спецсимволы для Telegram HTML parse_mode."""
    return html.escape(text, quote=False)


def format_expandable_quote(text: str, threshold: int = 180) -> str:
    """Оборачивает длинный текст в <blockquote expandable>...</blockquote >."""
    escaped = escape_html(text.strip())
    if len(escaped) >= threshold or escaped.count("\n") >= 3:
        return f"<blockquote expandable>{escaped}</blockquote>"
    return escaped


def split_telegram_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Разбивает длинное сообщение на части, не превышающие лимит Telegram."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            parts.append(current)
            current = ""

        if len(paragraph) <= limit:
            current = paragraph
        else:
            # Режем по строкам, если один блок слишком длинный
            for line in paragraph.splitlines():
                line_candidate = f"{current}\n{line}" if current else line
                if len(line_candidate) <= limit:
                    current = line_candidate
                else:
                    if current:
                        parts.append(current)
                    current = line[:limit]

    if current:
        parts.append(current)
    return parts
