import io
import logging
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security.api_key import APIKeyHeader

from datamanager import __version__
from datamanager.core.config import settings
from datamanager.schemas import (
    DatabaseInfo,
    DeleteRequest,
    DownloadRequest,
    ListResponse,
    ResampleRequest,
    ScheduleJobInfo,
    ScheduleListResponse,
    ScheduleRequest,
    SearchResponse,
    TaskResponse,
    UpdateRequest,
)
from datamanager.services.manager import DataManager
from datamanager.services.scheduler import SchedulerService

manager = DataManager()
scheduler = SchedulerService(manager)
logger = logging.getLogger("DataManager")

# ---------------------------------------------------------------------------
# Rate limiting: sliding window (60 req / 60 s per IP)
# ---------------------------------------------------------------------------
_RATE_LIMIT = 60
_RATE_WINDOW = 60.0
_rate_store: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _rate_store[ip]
    # evict requests outside the rolling window
    while window and window[0] <= now - _RATE_WINDOW:
        window.popleft()
    if len(window) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    window.append(now)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.is_api_key_configured:
        logger.warning("⚠  DATAMANAGER_API_KEY is not set — the API is running UNPROTECTED!")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="DataManager Network API", version=__version__, lifespan=lifespan)


# --- Dashboard & health (no auth required) ---
@app.get("/")
def dashboard():
    """Summary stats for the DataManager instance."""
    stats = manager.storage.get_stats()
    return {"status": "ok", "version": __version__, **stats, "timestamp": datetime.now().isoformat()}


@app.get("/health")
def health_check():
    dbs = manager.storage.list_databases()
    return {"status": "ok", "databases_count": len(dbs), "timestamp": datetime.now().isoformat()}



# --- SECURITY: 1. Authentication via API Key ---
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)


async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key == settings.api_key:
        return api_key
    raise HTTPException(status_code=403, detail="Access denied: Invalid API Key")


# --- SECURITY: 2. Asynchronous tasks (BackgroundTasks) to avoid blocking the server ---


@app.post("/rebuild", response_model=TaskResponse)
def rebuild_catalog(api_key: str = Depends(get_api_key)):
    """Rebuild the SQLite catalog by scanning the database directory on disk.

    Use this if the catalog drifts out of sync with physical files
    (e.g., after manual operations or a crash during write).
    """
    try:
        result = manager.storage.rebuild_catalog()
        return {"status": "success", "message": f"Catalog rebuilt ({result['count']} databases indexed)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rebuild failed: {e}")


@app.post("/download", response_model=TaskResponse)
def download_data(
    req: DownloadRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    api_key: str = Depends(get_api_key),
    _rl=Depends(_check_rate_limit),
):
    try:
        start_dt = datetime.fromisoformat(req.start_date) if req.start_date else datetime(2000, 1, 1)
        end_dt = datetime.fromisoformat(req.end_date) if req.end_date else datetime.now()

        assets = [a.strip() for a in req.asset.split(",") if a.strip()]

        # Validation to prevent duplicate downloads
        for asset in assets:
            info = manager.storage.get_database_info(req.source, asset, "M1")
            if info.get("status") != "Not Found":
                raise HTTPException(
                    status_code=409,
                    detail=f"The database for {asset} via {req.source} already exists on the server. Use the /update request to update the data.",  # noqa: E501
                )

        for asset in assets:
            background_tasks.add_task(manager.download_data, req.source, asset, start_dt, end_dt)
        return {"status": "success", "message": f"Download of {req.asset} via {req.source} started in background"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/update", response_model=TaskResponse)
def update_data(req: UpdateRequest, background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    try:
        assets = [a.strip() for a in req.asset.split(",") if a.strip()]
        for asset in assets:
            background_tasks.add_task(manager.update_data, req.source, asset, req.timeframe)
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
        return {"status": "success", "message": f"Deleted {req.asset} from {req.source} ({target})"}
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
def get_info(source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)):
    if not all(re.match(r"^[a-zA-Z0-9_.\-]+$", p) for p in [source, asset, timeframe]):
        raise HTTPException(status_code=400, detail="Invalid path parameters in URLs")

    info = manager.info(source, asset, timeframe)
    if info.get("status") == "Not Found":
        raise HTTPException(status_code=404, detail="Database not found")
    return info


@app.get("/search", response_model=SearchResponse)
def search_assets(source: str = "openbb", query: str = None, exchange: str = None, api_key: str = Depends(get_api_key)):
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


@app.post("/resample", response_model=TaskResponse)
def resample_data(req: ResampleRequest, background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    try:
        background_tasks.add_task(manager.resample_database, req.source, req.asset, req.target_timeframe)
        return {
            "status": "success",
            "message": f"Resample of {req.asset} to {req.target_timeframe} started in background",
        }  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/data/{source}/{asset}/{timeframe}")
def get_data_file(source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)):
    if not all(re.match(r"^[a-zA-Z0-9_\-]+$", p) for p in [source, asset, timeframe]):
        raise HTTPException(status_code=400, detail="Invalid path parameters")

    file_path = manager.storage._get_path(source, asset, timeframe)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Data file not found")

    return FileResponse(
        path=file_path, media_type="application/octet-stream", filename=f"{source}_{asset}_{timeframe}.parquet"
    )


@app.get("/data/{source}/{asset}/{timeframe}/stream")
def stream_data(source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)):
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
        for line in buf:
            yield line

    filename = f"{source}_{asset}_{timeframe}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(_csv_generator(), media_type="text/csv", headers=headers)


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
        raise HTTPException(status_code=400, detail=f"Invalid schedule configuration: {e}")


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
