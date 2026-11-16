from __future__ import annotations

import logging
from aiohttp import web


logger = logging.getLogger(__name__)


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "bat"})


async def start_health_server(port: int) -> web.AppRunner:
    """Запускает встроенный HTTP-сервер /health на указанном порту."""
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/", _health_handler)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Health HTTP server started on 0.0.0.0:%s", port)
    return runner
