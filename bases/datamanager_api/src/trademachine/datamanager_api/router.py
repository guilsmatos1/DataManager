import io
import logging
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from trademachine.core.logger import LOGGER_NAME, setup_logger

__version__ = "0.1.0"
from trademachine.datamanager.core.config import settings
from trademachine.datamanager.schemas import (
    DatabaseInfo,
    DeleteRequest,
    DownloadRequest,
    ListResponse,
    ScheduleJobInfo,
    ScheduleListResponse,
    ScheduleRequest,
    SearchResponse,
    SeriesDeleteRequest,
    SeriesDownloadRequest,
    SeriesInfo,
    SeriesListResponse,
    SeriesSearchResponse,
    SeriesUpdateRequest,
    TaskResponse,
    UpdateRequest,
)
from trademachine.datamanager.services.manager import DataManager
from trademachine.datamanager.services.scheduler import SchedulerService
from trademachine.datamanager.services.series_manager import SeriesManager

manager = DataManager()
series_manager = SeriesManager()
scheduler = SchedulerService(manager)
logger = logging.getLogger(LOGGER_NAME)

# ---------------------------------------------------------------------------
# Rate limiting: 60 req/min per IP (in-memory, single-worker).
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    raise HTTPException(
        status_code=429,
        detail=f"Rate limit exceeded: {exc.detail}.",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger()
    if not settings.is_api_key_configured:
        logger.warning(
            "⚠  DATAMANAGER_API_KEY is not set — the API is running UNPROTECTED!"
        )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="DataManager Network API",
    version=__version__,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Dashboard & health (no auth required) ---
@app.get("/")
def dashboard():
    """Summary stats for the DataManager instance."""
    stats = manager.storage.get_stats()
    return {
        "status": "ok",
        "version": __version__,
        **stats,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/health")
def health_check():
    dbs = manager.storage.list_databases()
    return {
        "status": "ok",
        "databases_count": len(dbs),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# --- SECURITY: 1. Authentication via API Key ---
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)


async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key == settings.api_key:
        return api_key
    raise HTTPException(status_code=403, detail="Access denied: Invalid API Key")


# --- SECURITY: 2. Asynchronous tasks (BackgroundTasks) to avoid blocking the server ---


@app.post("/download", response_model=TaskResponse)
def download_data(
    req: DownloadRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    try:
        start_dt = (
            datetime.fromisoformat(req.start_date)
            if req.start_date
            else datetime(2000, 1, 1)
        )
        end_dt = (
            datetime.fromisoformat(req.end_date) if req.end_date else datetime.now(UTC)
        )

        assets = [a.strip() for a in req.asset.split(",") if a.strip()]

        for asset in assets:
            background_tasks.add_task(
                manager.download_data, req.source, asset, start_dt, end_dt
            )
        return {
            "status": "success",
            "message": (
                f"Download of {req.asset} via {req.source} started in background "
                "(idempotent if data already exists)"
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/update", response_model=TaskResponse)
def update_data(
    req: UpdateRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    try:
        assets = [a.strip() for a in req.asset.split(",") if a.strip()]
        for asset in assets:
            background_tasks.add_task(
                manager.update_data, req.source, asset, req.timeframe
            )
        return {
            "status": "success",
            "message": f"Update of {req.asset} via {req.source} ({req.timeframe}) started in background",
        }  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/delete", response_model=TaskResponse)
def delete_data(req: DeleteRequest, api_key: str = Depends(get_api_key)):
    try:
        if req.source.lower() == "all" and req.asset.lower() == "all":
            manager.delete_all_databases()
            return {"status": "success", "message": "All databases deleted"}

        assets = [a.strip() for a in req.asset.split(",") if a.strip()]
        for asset in assets:
            manager.delete_database(req.source, asset, req.timeframe)
        target = req.timeframe if req.timeframe else "all timeframes"
        return {
            "status": "success",
            "message": f"Deleted {req.asset} from {req.source} ({target})",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/list", response_model=ListResponse)
def list_databases(
    skip: int = 0,
    limit: int = 100,
    api_key: str = Depends(get_api_key),
):
    try:
        dbs = manager.list_all()
        total = len(dbs)
        page = dbs[skip : skip + limit]
        return {"databases": page, "total": total, "skip": skip, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/info/{source}/{asset}/{timeframe}", response_model=DatabaseInfo)
def get_info(
    source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)
):
    if not all(re.match(r"^[a-zA-Z0-9_.\-]+$", p) for p in [source, asset, timeframe]):
        raise HTTPException(status_code=400, detail="Invalid path parameters in URLs")

    info = manager.info(source, asset, timeframe)
    if info.get("status") == "Not Found":
        raise HTTPException(status_code=404, detail="Database not found")
    return info


@app.get("/search", response_model=SearchResponse)
def search_assets(
    source: str = "openbb",
    query: str | None = None,
    exchange: str | None = None,
    api_key: str = Depends(get_api_key),
):
    try:
        df = manager.search_assets(source=source, query=query, exchange=exchange)
        if df.empty:
            return {"assets": []}

        # Ensure we return a list of dicts with all columns
        # Handle NaN values which are not JSON serializable
        assets = df.reset_index().fillna("").to_dict(orient="records")
        return {"assets": assets}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@app.get("/data/{source}/{asset}/{timeframe}")
def get_data_file(
    source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)
):
    if not all(re.match(r"^[a-zA-Z0-9_\-]+$", p) for p in [source, asset, timeframe]):
        raise HTTPException(status_code=400, detail="Invalid path parameters")

    try:
        df = manager.storage.load_data(source, asset, timeframe)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Database not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Convert to Parquet in memory
    buf = io.BytesIO()
    df.to_parquet(buf, engine="fastparquet")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{source}_{asset}_{timeframe}.parquet"'
        },
    )


@app.get("/data/{source}/{asset}/{timeframe}/stream")
def stream_data(
    source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)
):
    """Stream data as CSV (chunked, line by line). Suitable for large datasets."""
    if not all(re.match(r"^[a-zA-Z0-9_\-]+$", p) for p in [source, asset, timeframe]):
        raise HTTPException(status_code=400, detail="Invalid path parameters")

    try:
        df = manager.storage.load_data(source, asset, timeframe)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Data file not found")

    def _csv_generator():
        buf = io.StringIO()
        df.to_csv(buf)
        buf.seek(0)
        yield from buf

    filename = f"{source}_{asset}_{timeframe}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(_csv_generator(), media_type="text/csv", headers=headers)


# --- FRED / economic series ---


@app.get("/series/search", response_model=SeriesSearchResponse)
def search_series(
    source: str = "fred",
    query: str | None = None,
    api_key: str = Depends(get_api_key),
):
    try:
        df = series_manager.search_series(source=source, query=query)
        if df.empty:
            return {"series": []}

        series = df.reset_index().fillna("").to_dict(orient="records")
        return {"series": series}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@app.post("/series/download", response_model=TaskResponse)
def download_series(
    req: SeriesDownloadRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    try:
        background_tasks.add_task(
            series_manager.download_series,
            req.source,
            req.series_id,
            req.start_date,
            req.end_date,
            req.frequency,
        )
        return {
            "status": "success",
            "message": f"Download of {req.series_id} via {req.source} started in background",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/series/update", response_model=TaskResponse)
def update_series(
    req: SeriesUpdateRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    try:
        background_tasks.add_task(
            series_manager.update_series,
            req.source,
            req.series_id,
            req.lookback_period,
            req.frequency,
        )
        return {
            "status": "success",
            "message": f"Update of {req.series_id} via {req.source} started in background",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/series/list", response_model=SeriesListResponse)
def list_series(
    skip: int = 0,
    limit: int = 100,
    api_key: str = Depends(get_api_key),
):
    try:
        items = series_manager.list_series()
        total = len(items)
        page = items[skip : skip + limit]
        series = [
            item if isinstance(item, SeriesInfo) else SeriesInfo(**item)
            for item in page
        ]
        return {"series": series, "total": total, "skip": skip, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/series/info/{source}/{series_id}", response_model=SeriesInfo)
def get_series_info(source: str, series_id: str, api_key: str = Depends(get_api_key)):
    if not all(re.match(r"^[a-zA-Z0-9_.\-]+$", p) for p in [source, series_id]):
        raise HTTPException(status_code=400, detail="Invalid path parameters in URLs")

    info = series_manager.info_series(source, series_id)
    if not info:
        raise HTTPException(status_code=404, detail="Series not found")
    if isinstance(info, SeriesInfo):
        return info
    return SeriesInfo(**info)


@app.get("/series/data/{source}/{series_id}")
def get_series_data_file(
    source: str, series_id: str, api_key: str = Depends(get_api_key)
):
    if not all(re.match(r"^[a-zA-Z0-9_.\-]+$", p) for p in [source, series_id]):
        raise HTTPException(status_code=400, detail="Invalid path parameters")

    try:
        df = series_manager.load_series_data(source, series_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Series not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    buf = io.BytesIO()
    df.to_parquet(buf, engine="fastparquet")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{source}_{series_id}.parquet"'
        },
    )


@app.post("/series/delete", response_model=TaskResponse)
def delete_series(
    req: SeriesDeleteRequest,
    api_key: str = Depends(get_api_key),
):
    try:
        removed = series_manager.delete_series(req.source, req.series_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Series not found")
        return {
            "status": "success",
            "message": f"Deleted {req.series_id} from {req.source}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/schedule", response_model=ScheduleJobInfo)
def create_schedule(req: ScheduleRequest, api_key: str = Depends(get_api_key)):
    try:
        job = scheduler.add_job(
            source=req.source,
            asset=req.asset,
            timeframe=req.timeframe,
            cron=req.cron,
            interval_minutes=req.interval_minutes,
        )
        return job
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid schedule configuration: {e}"
        )


@app.get("/schedule", response_model=ScheduleListResponse)
def list_schedules(api_key: str = Depends(get_api_key)):
    return {"jobs": scheduler.list_jobs()}


@app.delete("/schedule/{job_id}", response_model=TaskResponse)
def delete_schedule(job_id: str, api_key: str = Depends(get_api_key)):
    removed = scheduler.remove_job(job_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "success", "message": f"Job '{job_id}' removed"}


if __name__ == "__main__":
    import uvicorn

    print("Starting DataManager Network API (Protected) ...")
    uvicorn.run(app, host=settings.host, port=settings.port)
