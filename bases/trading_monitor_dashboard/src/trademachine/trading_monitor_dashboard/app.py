import asyncio
import hashlib
import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from trademachine.core.logger import LOGGER_NAME, setup_logger
from trademachine.trading_monitor_dashboard.bridge import init_bridge, push_event
from trademachine.trading_monitor_dashboard.routes import router
from trademachine.trading_monitor_dashboard.websocket import manager
from trademachine.tradingmonitor_storage.public import (
    ensure_database_connection,
    settings,
)

logger = logging.getLogger(LOGGER_NAME)

BASE_DIR = Path(__file__).parent
WORKSPACE_DIR = BASE_DIR.parents[4]
METRICS_PUBLISHER_PATH = (
    WORKSPACE_DIR / "projects" / "tradingmonitor" / "mt5" / "MetricsPublisher.mq5"
)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()[:8]  # noqa: S324


def create_app(
    with_ingestion: bool = False,
    server_host: str = "127.0.0.1",
    server_port: int = settings.server_port,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logger(log_path="projects/tradingmonitor/log.log")
        loop = asyncio.get_event_loop()
        init_bridge(manager.queue, loop)

        broadcaster_task = asyncio.create_task(manager.run_broadcaster())

        if with_ingestion:
            from trademachine.tradingmonitor_ingestion.public import (
                start_server,
            )

            ensure_database_connection("TradingMonitor dashboard ingestion")

            threading.Thread(
                target=start_server,
                args=(server_host, server_port),
                kwargs={"on_event": push_event, "require_database": False},
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

    _ctx = {
        "api_key": settings.api_key,
        "js_v": _file_hash(BASE_DIR / "static" / "dashboard.js"),
    }

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

    @app.get("/account/{account_id}")
    async def account_page(request: Request, account_id: str):
        return templates.TemplateResponse(
            "account.html", {"request": request, "account_id": account_id, **_ctx}
        )

    @app.get("/symbol/{symbol_name:path}")
    async def symbol_page(request: Request, symbol_name: str):
        return templates.TemplateResponse(
            "symbol.html", {"request": request, "symbol_name": symbol_name, **_ctx}
        )

    @app.get("/advanced-analysis")
    async def advanced_analysis_page(request: Request):
        return templates.TemplateResponse(
            "advanced_analysis.html", {"request": request, **_ctx}
        )

    @app.get("/real")
    async def real_page(request: Request):
        return templates.TemplateResponse("real.html", {"request": request, **_ctx})

    @app.get("/settings")
    async def settings_page(request: Request):
        return templates.TemplateResponse("settings.html", {"request": request, **_ctx})

    @app.get("/benchmarks")
    async def benchmarks_page(request: Request):
        return templates.TemplateResponse(
            "benchmarks.html", {"request": request, **_ctx}
        )

    @app.get("/downloads/metrics-publisher")
    async def download_metrics_publisher():
        return FileResponse(
            path=str(METRICS_PUBLISHER_PATH),
            filename="MetricsPublisher.mq5",
            media_type="text/plain",
        )

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
        from trademachine.tradingmonitor_analytics.public import (
            generate_qs_report,
        )

        fd, tmp_path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            result = await run_in_threadpool(
                generate_qs_report, strategy_id=strategy_id, output_path=tmp_path
            )
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

    @app.get("/backtest/{backtest_id}/quantstats-report", response_class=HTMLResponse)
    async def backtest_quantstats_report(backtest_id: int):
        from trademachine.tradingmonitor_analytics.public import (
            generate_qs_report,
        )

        fd, tmp_path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            result = await run_in_threadpool(
                generate_qs_report, backtest_id=backtest_id, output_path=tmp_path
            )
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
        from trademachine.tradingmonitor_analytics.public import (
            generate_qs_report,
        )

        fd, tmp_path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            result = await run_in_threadpool(
                generate_qs_report, portfolio_id=portfolio_id, output_path=tmp_path
            )
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


def create_configured_app() -> FastAPI:
    """No-argument factory for uvicorn factory mode.

    Reads dashboard configuration from environment variables set by the CLI
    launcher so that trading_monitor_cli does not need to import this module.

    Env vars:
        _TM_WITH_INGESTION  — "1" to start the TCP ingestion thread (default "0")
        _TM_INGESTION_HOST  — TCP server host (default "127.0.0.1")
        _TM_INGESTION_PORT  — TCP server port (default: settings.server_port)
    """
    with_ingestion = os.environ.get("_TM_WITH_INGESTION", "0") == "1"
    server_host = os.environ.get("_TM_INGESTION_HOST", "127.0.0.1")
    server_port = int(os.environ.get("_TM_INGESTION_PORT", str(settings.server_port)))
    return create_app(
        with_ingestion=with_ingestion,
        server_host=server_host,
        server_port=server_port,
    )
