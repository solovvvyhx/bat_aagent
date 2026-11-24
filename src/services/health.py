from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from aiohttp import web


logger = logging.getLogger(__name__)


async def start_health_server(
    port: int,
    status_provider: Optional[Callable[[], dict[str, Any]]] = None,
) -> web.AppRunner:
    """Запускает встроенный HTTP-сервер /health на указанном порту."""

    async def _health_handler(request: web.Request) -> web.Response:
        payload: dict[str, Any] = {"status": "ok", "service": "bat"}
        if status_provider is not None:
            payload.update(status_provider())
        return web.json_response(payload)

    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/", _health_handler)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Health HTTP server started on 0.0.0.0:%s", port)
    return runner
