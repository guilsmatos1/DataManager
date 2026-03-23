import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tradingmonitor.config import settings
from tradingmonitor.dashboard.bridge import init_bridge, push_event
from tradingmonitor.dashboard.routes import router
from tradingmonitor.dashboard.websocket import manager

logger = logging.getLogger("Dashboard")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_app(
    with_ingestion: bool = False, server_host: str = "127.0.0.1", server_port: int = 5555
) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_event_loop()
        init_bridge(manager.queue, loop)

        broadcaster_task = asyncio.create_task(manager.run_broadcaster())

        if with_ingestion:
            from tradingmonitor.ingestion.tcp_server import start_server

            threading.Thread(
                target=start_server,
                args=(server_host, server_port),
                kwargs={"on_event": push_event},
                daemon=True,
            ).start()
            logger.info(f"TCP ingestion thread started on {server_host}:{server_port}.")

        yield

        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass

    app = FastAPI(
        title="TradingMonitor Dashboard",
        lifespan=lifespan,
        json_encoders={Decimal: float},
    )

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.include_router(router)

    _ctx = {"api_key": settings.api_key}

    @app.get("/")
    async def index(request: Request):
        return templates.TemplateResponse("index.html", {"request": request, **_ctx})

    @app.get("/strategy/{strategy_id}")
    async def strategy_page(request: Request, strategy_id: str):
        return templates.TemplateResponse(
            "strategy.html", {"request": request, "strategy_id": strategy_id, **_ctx}
        )

    @app.get("/strategy/{strategy_id}/advanced-metrics")
    async def advanced_metrics_page(request: Request, strategy_id: str):
        return templates.TemplateResponse(
            "advanced_metrics.html", {"request": request, "strategy_id": strategy_id, **_ctx}
        )

    @app.get("/portfolio/{portfolio_id}")
    async def portfolio_page(request: Request, portfolio_id: int):
        return templates.TemplateResponse(
            "portfolio.html", {"request": request, "portfolio_id": portfolio_id, **_ctx}
        )

    @app.get("/compare")
    async def compare_page(request: Request):
        return templates.TemplateResponse("compare.html", {"request": request, **_ctx})

    @app.get("/real")
    async def real_page(request: Request):
        return templates.TemplateResponse("real.html", {"request": request, **_ctx})

    @app.get("/settings")
    async def settings_page(request: Request):
        return templates.TemplateResponse("settings.html", {"request": request, **_ctx})

    @app.get("/portfolio/{portfolio_id}/advanced-metrics")
    async def portfolio_advanced_metrics_page(request: Request, portfolio_id: int):
        return templates.TemplateResponse(
            "portfolio_advanced_metrics.html",
            {"request": request, "portfolio_id": portfolio_id, **_ctx},
        )

    @app.get("/portfolio/{portfolio_id}/correlation")
    async def correlation_page(request: Request, portfolio_id: int):
        return templates.TemplateResponse(
            "correlation.html", {"request": request, "portfolio_id": portfolio_id, **_ctx}
        )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app
