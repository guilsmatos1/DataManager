"""Dashboard UI routes for the DataManager API."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from trademachine.datamanager.public import settings
from trademachine.datamanager_api._state import (
    activity,
    logger,
    manager,
    scheduler,
    series_manager,
    tracker,
)
from trademachine.datamanager_api.task_tracker import ProgressAdapter, TaskStatus

_BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))

dashboard_router = APIRouter()

# Session tokens (in-memory, single-worker)
_sessions: set[str] = set()


def _check_auth(request: Request) -> bool:
    """Return True if the request has a valid session cookie."""
    if not settings.is_api_key_configured:
        return True
    token = request.cookies.get("dm_session_key")
    return token is not None and token in _sessions


def _require_auth(request: Request) -> RedirectResponse | None:
    """Return a redirect to login if not authenticated, else None."""
    if not _check_auth(request):
        return RedirectResponse(url="/ui/login", status_code=303)
    return None


# ── Login ──


@dashboard_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@dashboard_router.post("/login")
async def login_submit(request: Request, api_key: str = Form(...)):
    if api_key != settings.api_key:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid API key"}
        )
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    response = RedirectResponse(url="/ui/", status_code=303)
    response.set_cookie(
        key="dm_session_key",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
    )
    return response


# ── Page routes ──


@dashboard_router.get("/", response_class=HTMLResponse)
async def overview_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    stats = manager.storage.get_stats()
    databases = manager.list_all()
    series_count = len(series_manager.list_series())

    # Source distribution for chart
    source_distribution = stats.get("sources", {})

    # Coverage data: count assets per source
    coverage_data = dict(Counter(db["source"] for db in databases))

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "stats": {**stats, "series_count": series_count},
            "databases": databases,
            "source_distribution": source_distribution,
            "coverage_data": coverage_data,
        },
    )


@dashboard_router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "assets.html",
        {"request": request, "today": datetime.now(UTC).strftime("%Y-%m-%d")},
    )


@dashboard_router.get("/series", response_class=HTMLResponse)
async def series_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("series.html", {"request": request})


@dashboard_router.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("scheduler.html", {"request": request})


# ── Task progress SSE endpoints ──


@dashboard_router.get("/api/tasks/active")
async def api_active_tasks(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect
    tasks = tracker.list_active()
    return JSONResponse(
        [
            {
                "task_id": t.task_id,
                "status": t.status.value,
                "progress": round(t.progress, 4),
                "description": t.description,
            }
            for t in tasks
        ]
    )


@dashboard_router.get("/api/tasks/{task_id}/progress")
async def sse_task_progress(request: Request, task_id: str):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    async def event_stream():
        while True:
            if await request.is_disconnected():
                break
            task = tracker.get(task_id)
            if task is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break
            payload = {
                "task_id": task.task_id,
                "status": task.status.value,
                "progress": round(task.progress, 4),
                "description": task.description,
                "message": task.message,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── HTMX API endpoints (return HTML partials) ──


@dashboard_router.get("/api/assets", response_class=HTMLResponse)
async def htmx_assets(request: Request, source: str = "", q: str = ""):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    databases = manager.list_all()
    if source:
        databases = [db for db in databases if db["source"] == source]
    if q:
        query_lower = q.lower()
        databases = [db for db in databases if query_lower in db["asset"].lower()]

    return templates.TemplateResponse(
        "partials/asset_table.html",
        {"request": request, "databases": databases},
    )


@dashboard_router.get(
    "/api/asset-info/{source}/{asset}/{timeframe}", response_class=HTMLResponse
)
async def htmx_asset_info(request: Request, source: str, asset: str, timeframe: str):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    info = manager.info(source, asset, timeframe)
    return templates.TemplateResponse(
        "partials/asset_info.html",
        {"request": request, "info": info},
    )


@dashboard_router.post("/api/download")
async def htmx_download(
    request: Request,
    background_tasks: BackgroundTasks,
    source: str = Form(...),
    asset: str = Form(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    start_dt = (
        datetime.fromisoformat(start_date).replace(tzinfo=None)
        if start_date
        else datetime(2000, 1, 1)
    )
    end_dt = (
        datetime.fromisoformat(end_date).replace(tzinfo=None)
        if end_date
        else datetime.now(UTC).replace(tzinfo=None)
    )
    total_days = max((end_dt - start_dt).days, 1)

    assets = [a.strip() for a in asset.split(",") if a.strip()]
    task_ids = []
    for a in assets:
        task_id = tracker.create_task(description=f"Downloading {a} from {source}")
        task_ids.append(task_id)

        def _run_download(
            src: str, ast: str, s: datetime, e: datetime, tid: str
        ) -> None:
            pbar = ProgressAdapter(tid, total=total_days, desc=f"Downloading {ast}")
            try:
                manager.download_data(src, ast, s, e, pbar=pbar)
                tracker.update(
                    tid,
                    status=TaskStatus.COMPLETED,
                    progress=1.0,
                    message=f"{ast} downloaded successfully",
                )
                activity.log_activity("download", f"{src}/{ast}", "success")
            except Exception as exc:
                logger.exception("Download task failed")
                tracker.update(tid, status=TaskStatus.FAILED, message=str(exc))
                activity.log_activity("download", f"{src}/{ast}", "failed", str(exc))

        background_tasks.add_task(_run_download, source, a, start_dt, end_dt, task_id)

    return JSONResponse(
        {"task_ids": task_ids, "message": f"Downloading {asset} from {source}"}
    )


@dashboard_router.post("/api/update")
async def htmx_update(
    request: Request,
    background_tasks: BackgroundTasks,
    source: str = Form(...),
    asset: str = Form(...),
    timeframe: str = Form("M1"),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    assets = [a.strip() for a in asset.split(",") if a.strip()]
    task_ids = []
    for a in assets:
        task_id = tracker.create_task(description=f"Updating {a} ({timeframe})")
        task_ids.append(task_id)

        def _run_update(src: str, ast: str, tf: str, tid: str) -> None:
            pbar = ProgressAdapter(tid, total=1, desc=f"Updating {ast}")
            try:
                manager.update_data(src, ast, tf, pbar=pbar)
                tracker.update(
                    tid,
                    status=TaskStatus.COMPLETED,
                    progress=1.0,
                    message=f"{ast} updated successfully",
                )
                activity.log_activity("update", f"{src}/{ast}/{tf}", "success")
            except Exception as exc:
                logger.exception("Update task failed")
                tracker.update(tid, status=TaskStatus.FAILED, message=str(exc))
                activity.log_activity("update", f"{src}/{ast}/{tf}", "failed", str(exc))

        background_tasks.add_task(_run_update, source, a, timeframe, task_id)

    return JSONResponse(
        {
            "task_ids": task_ids,
            "message": f"Updating {asset} ({timeframe}) from {source}",
        }
    )


@dashboard_router.post("/api/delete", response_class=HTMLResponse)
async def htmx_delete(
    request: Request,
    source: str = Form(...),
    asset: str = Form(...),
    timeframe: str = Form(""),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    try:
        manager.delete_database(source, asset, timeframe or None)
        activity.log_activity(
            "delete", f"{source}/{asset}/{timeframe or 'ALL'}", "success"
        )
        return templates.TemplateResponse(
            "partials/toast.html",
            {
                "request": request,
                "title": "Deleted",
                "message": f"Deleted {asset} from {source}",
                "level": "success",
            },
        )
    except Exception as exc:
        logger.exception("Delete failed")
        activity.log_activity("delete", f"{source}/{asset}", "failed", str(exc))
        return templates.TemplateResponse(
            "partials/toast.html",
            {
                "request": request,
                "title": "Error",
                "message": str(exc),
                "level": "error",
            },
        )


# ── FRED Series HTMX endpoints ──


@dashboard_router.get("/api/series", response_class=HTMLResponse)
async def htmx_series(request: Request, q: str = ""):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    items = series_manager.list_series()
    if q:
        query_lower = q.lower()
        items = [
            s
            for s in items
            if query_lower in s.get("series_id", "").lower()
            or query_lower in (s.get("title") or "").lower()
        ]

    return templates.TemplateResponse(
        "partials/series_table.html",
        {"request": request, "series_list": items},
    )


@dashboard_router.get(
    "/api/series-info/{source}/{series_id}", response_class=HTMLResponse
)
async def htmx_series_info(request: Request, source: str, series_id: str):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    info = series_manager.info_series(source, series_id)
    return templates.TemplateResponse(
        "partials/series_info.html",
        {"request": request, "info": info},
    )


@dashboard_router.post("/api/series/download")
async def htmx_series_download(
    request: Request,
    background_tasks: BackgroundTasks,
    source: str = Form("fred"),
    series_id: str = Form(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    task_id = tracker.create_task(description=f"Downloading series {series_id}")

    def _run_series_download(
        src: str, sid: str, s: str | None, e: str | None, tid: str
    ) -> None:
        pbar = ProgressAdapter(tid, total=3, desc=f"Downloading series {sid}")
        try:
            series_manager.download_series(src, sid, s, e, pbar=pbar)
            tracker.update(
                tid,
                status=TaskStatus.COMPLETED,
                progress=1.0,
                message=f"Series {sid} downloaded successfully",
            )
            activity.log_activity("download", f"{src}/{sid}", "success")
        except Exception as exc:
            logger.exception("Series download task failed")
            tracker.update(tid, status=TaskStatus.FAILED, message=str(exc))
            activity.log_activity("download", f"{src}/{sid}", "failed", str(exc))

    background_tasks.add_task(
        _run_series_download,
        source,
        series_id,
        start_date or None,
        end_date or None,
        task_id,
    )

    return JSONResponse(
        {
            "task_ids": [task_id],
            "message": f"Downloading series {series_id} from {source}",
        }
    )


@dashboard_router.post("/api/series/update")
async def htmx_series_update(
    request: Request,
    background_tasks: BackgroundTasks,
    source: str = Form(...),
    series_id: str = Form(...),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    task_id = tracker.create_task(description=f"Updating series {series_id}")

    def _run_series_update(src: str, sid: str, tid: str) -> None:
        pbar = ProgressAdapter(tid, total=3, desc=f"Updating series {sid}")
        try:
            series_manager.update_series(src, sid, pbar=pbar)
            tracker.update(
                tid,
                status=TaskStatus.COMPLETED,
                progress=1.0,
                message=f"Series {sid} updated successfully",
            )
            activity.log_activity("update", f"{src}/{sid}", "success")
        except Exception as exc:
            logger.exception("Series update task failed")
            tracker.update(tid, status=TaskStatus.FAILED, message=str(exc))
            activity.log_activity("update", f"{src}/{sid}", "failed", str(exc))

    background_tasks.add_task(_run_series_update, source, series_id, task_id)

    return JSONResponse(
        {"task_ids": [task_id], "message": f"Updating series {series_id}"}
    )


@dashboard_router.post("/api/series/delete", response_class=HTMLResponse)
async def htmx_series_delete(
    request: Request,
    source: str = Form(...),
    series_id: str = Form(...),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    try:
        removed = series_manager.delete_series(source, series_id)
        if not removed:
            return templates.TemplateResponse(
                "partials/toast.html",
                {
                    "request": request,
                    "title": "Not Found",
                    "message": f"Series {series_id} not found",
                    "level": "warning",
                },
            )
        activity.log_activity("delete", f"{source}/{series_id}", "success")
        return templates.TemplateResponse(
            "partials/toast.html",
            {
                "request": request,
                "title": "Deleted",
                "message": f"Deleted series {series_id}",
                "level": "success",
            },
        )
    except Exception as exc:
        logger.exception("Series delete failed")
        activity.log_activity("delete", f"{source}/{series_id}", "failed", str(exc))
        return templates.TemplateResponse(
            "partials/toast.html",
            {
                "request": request,
                "title": "Error",
                "message": str(exc),
                "level": "error",
            },
        )


# ── Scheduler HTMX endpoints ──


@dashboard_router.get("/api/schedules", response_class=HTMLResponse)
async def htmx_schedules(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    raw_jobs = scheduler.list_jobs()
    jobs = []
    for job in raw_jobs:
        if isinstance(job, dict):
            jobs.append(job)
        else:
            jobs.append(
                job.model_dump() if hasattr(job, "model_dump") else job.__dict__
            )

    return templates.TemplateResponse(
        "partials/schedule_table.html",
        {"request": request, "jobs": jobs},
    )


@dashboard_router.post("/api/schedule", response_class=HTMLResponse)
async def htmx_create_schedule(
    request: Request,
    source: str = Form(...),
    asset: str = Form(...),
    timeframe: str = Form("M1"),
    interval_minutes: int | None = Form(None),
    cron: str | None = Form(None),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    try:
        scheduler.add_job(
            source=source,
            asset=asset,
            timeframe=timeframe,
            cron=cron or None,
            interval_minutes=interval_minutes,
        )
        activity.log_activity(
            "schedule_create", f"{source}/{asset}/{timeframe}", "success"
        )
        return await htmx_schedules(request)
    except (ValueError, Exception) as exc:
        logger.exception("Schedule creation failed")
        return templates.TemplateResponse(
            "partials/toast.html",
            {
                "request": request,
                "title": "Error",
                "message": str(exc),
                "level": "error",
            },
        )


@dashboard_router.delete("/api/schedule/{job_id}", response_class=HTMLResponse)
async def htmx_delete_schedule(request: Request, job_id: str):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    removed = scheduler.remove_job(job_id)
    if not removed:
        return templates.TemplateResponse(
            "partials/toast.html",
            {
                "request": request,
                "title": "Not Found",
                "message": f"Job '{job_id}' not found",
                "level": "warning",
            },
        )
    activity.log_activity("schedule_delete", job_id, "success")
    return await htmx_schedules(request)


# ── Activity Log ──


@dashboard_router.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("activity.html", {"request": request})


@dashboard_router.get("/api/activity", response_class=HTMLResponse)
async def htmx_activity(request: Request, page: int = 1):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    per_page = 50
    offset = (page - 1) * per_page
    entries = activity.list_activities(limit=per_page, offset=offset)
    total = activity.count_activities()
    has_next = offset + per_page < total
    has_prev = page > 1

    return templates.TemplateResponse(
        "partials/activity_table.html",
        {
            "request": request,
            "entries": entries,
            "page": page,
            "has_next": has_next,
            "has_prev": has_prev,
        },
    )
