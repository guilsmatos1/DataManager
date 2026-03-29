import asyncio
import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from trademachine.core.logger import LOGGER_NAME, setup_logger
from trademachine.trading_monitor_dashboard.bridge import init_bridge, push_event
from trademachine.trading_monitor_dashboard.routes import router
from trademachine.trading_monitor_dashboard.websocket import manager
from trademachine.tradingmonitor.config import settings

logger = logging.getLogger(LOGGER_NAME)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_app(
    with_ingestion: bool = False,
    server_host: str = "127.0.0.1",
    server_port: int = settings.server_port,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logger()
        loop = asyncio.get_event_loop()
        init_bridge(manager.queue, loop)

        broadcaster_task = asyncio.create_task(manager.run_broadcaster())

        if with_ingestion:
            from trademachine.tradingmonitor.ingestion.tcp_server import start_server

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
            "advanced_metrics.html",
            {"request": request, "strategy_id": strategy_id, **_ctx},
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
            "correlation.html",
            {"request": request, "portfolio_id": portfolio_id, **_ctx},
        )

    @app.get("/strategy/{strategy_id}/quantstats-report", response_class=HTMLResponse)
    async def strategy_quantstats_report(strategy_id: str):
        from trademachine.tradingmonitor.metrics.calculator import generate_qs_report

        fd, tmp_path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            result = generate_qs_report(strategy_id=strategy_id, output_path=tmp_path)
            if result is None:
                return HTMLResponse(
                    content="<h1>Not enough data to generate report.</h1>",
                    status_code=404,
                )
            with open(tmp_path) as f:
                html_content = f.read()
            return HTMLResponse(content=html_content)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @app.get("/portfolio/{portfolio_id}/quantstats-report", response_class=HTMLResponse)
    async def portfolio_quantstats_report(portfolio_id: int):
        from trademachine.tradingmonitor.metrics.calculator import generate_qs_report

        fd, tmp_path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            result = generate_qs_report(portfolio_id=portfolio_id, output_path=tmp_path)
            if result is None:
                return HTMLResponse(
                    content="<h1>Not enough data to generate report.</h1>",
                    status_code=404,
                )
            with open(tmp_path) as f:
                html_content = f.read()
            return HTMLResponse(content=html_content)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app
