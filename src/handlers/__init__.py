from aiogram import Router

from .auth import router as auth_router
from .common import router as common_router
from .schedule import router as schedule_router


def get_main_router() -> Router:
    """Собирает главный роутер со всеми обработчиками."""
    root = Router()
    root.include_router(auth_router)
    root.include_router(common_router)
    root.include_router(schedule_router)
    return root
