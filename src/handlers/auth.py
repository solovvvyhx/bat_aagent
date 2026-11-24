from __future__ import annotations

import logging
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.config import Settings
from src.models import User
from src.services.database import UserRepository
from src.services.mes_client import MesAuthError
from src.services.mes_pool import MesClientPool
from src.services.scheduler import BatScheduler
from src.utils.text import escape_html


logger = logging.getLogger(__name__)
router = Router(name="auth")


class AuthStates(StatesGroup):
    waiting_login = State()
    waiting_password = State()


def _help_text(user: User) -> str:
    greeting = f", <b>{escape_html(user.full_name)}</b>" if user.full_name else ""
    return (
        f"🦇 <b>Bat</b> на связи{greeting}.\n\n"
        f"Аккаунт <code>edu.mes.ru</code>: <code>{escape_html(user.mes_login)}</code>\n\n"
        "<b>Команды:</b>\n"
        "• /morning — сводка на сегодня (расписание, работы, ДЗ)\n"
        "• /tomorrow — сводка на завтра\n"
        "• /evening — вечерняя сводка (оценки за сегодня + ДЗ и вложения)\n"
        "• /works (или /tests) — ближайшие контрольные и работы (14 дн.)\n"
        "• /grades (или /marks) — оценки за сегодня и вчера\n"
        "• /avatar — минималистичная аватарка Bat\n"
        "• /login — сменить аккаунт edu.mes.ru\n"
        "• /logout — отключить аккаунт и рассылки"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отменяет текущий шаг авторизации."""
    current = await state.get_state()
    if current is None:
        await message.answer("Сейчас нечего отменять.")
        return
    await state.clear()
    await message.answer("❌ Ввод отменён.")


@router.message(Command("start"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    current_user: Optional[User],
) -> None:
    """Приветствие или запуск регистрации нового ученика."""
    await state.clear()
    if current_user is not None:
        await message.answer(_help_text(current_user))
        return

    await state.set_state(AuthStates.waiting_login)
    await message.answer(
        "🦇 Привет! Я <b>Bat</b> — автономный ассистент для <code>edu.mes.ru</code>.\n\n"
        "Чтобы подключить твоё расписание, ДЗ, работы и оценки, введи свой <b>логин от edu.mes.ru</b>:\n"
        "<i>(Пароль шифруется, а сообщение с ним сразу удаляется из чата. Для отмены — /cancel.)</i>"
    )


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext) -> None:
    """Запускает вход или смену учётной записи edu.mes.ru."""
    await state.clear()
    await state.set_state(AuthStates.waiting_login)
    await message.answer(
        "🔐 Введи свой <b>логин от edu.mes.ru</b>:\n"
        "<i>(Для отмены — /cancel)</i>"
    )


@router.message(AuthStates.waiting_login, F.text)
async def process_login(message: Message, state: FSMContext) -> None:
    login = (message.text or "").strip()
    if not login or login.startswith("/"):
        await message.answer("⚠️ Введи обычный логин от <code>edu.mes.ru</code> (или /cancel).")
        return

    await state.update_data(mes_login=login)
    await state.set_state(AuthStates.waiting_password)
    await message.answer(
        f"Логин <code>{escape_html(login)}</code> принят.\n"
        "Теперь введи <b>пароль от edu.mes.ru</b> "
        "<i>(я сразу удалю твоё сообщение с паролем из чата)</i>:"
    )


@router.message(AuthStates.waiting_password, F.text)
async def process_password(
    message: Message,
    state: FSMContext,
    user_repo: UserRepository,
    mes_pool: MesClientPool,
    scheduler: BatScheduler,
    settings: Settings,
) -> None:
    password = (message.text or "").strip()
    # Удаляем сообщение с паролем из истории чата для безопасности
    try:
        await message.delete()
    except Exception:
        pass

    if not password:
        await message.answer("⚠️ Пароль пустой. Введи пароль ещё раз или /cancel.")
        return

    data = await state.get_data()
    login = str(data.get("mes_login") or "").strip()
    if not login:
        await state.clear()
        await message.answer("⚠️ Сессия ввода сброшена. Начни заново с /login.")
        return

    status_msg = await message.answer("🦇 Проверяю вход на <code>edu.mes.ru</code>...")
    try:
        full_name = await mes_pool.verify_credentials(login=login, password=password)
    except MesAuthError:
        await state.set_state(AuthStates.waiting_login)
        await status_msg.edit_text(
            "❌ Неверный логин или пароль от <code>edu.mes.ru</code>.\n"
            "Введи <b>логин</b> ещё раз (или /cancel):"
        )
        return
    except Exception as exc:
        logger.exception("Ошибка при проверке входа на edu.mes.ru")
        await state.clear()
        await status_msg.edit_text(
            f"⚠️ Не удалось подключиться к <code>edu.mes.ru</code>: <code>{escape_html(str(exc))}</code>\n"
            "Попробуй ещё раз чуть позже командой /login."
        )
        return

    tg_user = message.from_user
    if tg_user is None:
        await state.clear()
        return

    user = await user_repo.upsert_user(
        telegram_id=tg_user.id,
        mes_login=login,
        mes_password=password,
        username=tg_user.username,
        full_name=full_name,
        timezone_name=settings.timezone,
        is_admin=(tg_user.id == settings.admin_id),
    )
    await mes_pool.invalidate(tg_user.id)
    await scheduler.refresh_users_count()
    await scheduler.schedule_evening_for_user(user)
    await state.clear()

    await status_msg.edit_text(
        "✅ <b>Аккаунт подключён!</b> Пароль сохранён в зашифрованном виде.\n\n"
        + _help_text(user)
    )


@router.message(Command("logout"))
async def cmd_logout(
    message: Message,
    state: FSMContext,
    current_user: Optional[User],
    user_repo: UserRepository,
    mes_pool: MesClientPool,
    scheduler: BatScheduler,
) -> None:
    """Удаляет аккаунт пользователя из БД и отключает уведомления."""
    await state.clear()
    if current_user is None or message.from_user is None:
        await message.answer("Ты ещё не подключил аккаунт. Используй /login.")
        return

    tg_id = message.from_user.id
    await user_repo.delete_user(tg_id)
    await mes_pool.invalidate(tg_id)
    scheduler.unschedule_user(tg_id)
    await scheduler.refresh_users_count()

    await message.answer(
        "👋 Аккаунт <code>edu.mes.ru</code> удалён, рассылки отключены.\n"
        "Если захочешь вернуться — просто нажми /start или /login."
    )
