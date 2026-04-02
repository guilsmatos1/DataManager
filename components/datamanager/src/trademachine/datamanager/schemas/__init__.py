from typing import Any

from pydantic import BaseModel, Field

SAFE_PATTERN = r"^[a-zA-Z0-9_,\s\-]+$"

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class DownloadRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    start_date: str | None = None
    end_date: str | None = None


class UpdateRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    timeframe: str = Field("M1", pattern=r"^[a-zA-Z0-9_]+$")


class DeleteRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    timeframe: str | None = Field(None, pattern=r"^[a-zA-Z0-9_]+$")


class SeriesDownloadRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    series_id: str = Field(..., pattern=r"^[a-zA-Z0-9_.\-]+$")
    start_date: str | None = None
    end_date: str | None = None
    frequency: str | None = Field(None, pattern=r"^[a-zA-Z0-9_]+$")


class SeriesUpdateRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    series_id: str = Field(..., pattern=r"^[a-zA-Z0-9_.\-]+$")
    lookback_period: str | None = Field(None, pattern=r"^[a-zA-Z0-9_]+$")
    frequency: str | None = Field(None, pattern=r"^[a-zA-Z0-9_]+$")


class SeriesDeleteRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    series_id: str = Field(..., pattern=r"^[a-zA-Z0-9_.\-]+$")


class SeriesSearchRequest(BaseModel):
    source: str = Field("fred", pattern=r"^[a-zA-Z0-9_]+$")
    query: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DatabaseInfo(BaseModel):
    source: str
    asset: str
    timeframe: str
    rows: int
    start_date: str
    end_date: str


class TaskResponse(BaseModel):
    status: str
    message: str


class ListResponse(BaseModel):
    databases: list[DatabaseInfo]
    total: int
    skip: int
    limit: int


class SearchResponse(BaseModel):
    assets: list[Any]


# ---------------------------------------------------------------------------
# Scheduler models
# ---------------------------------------------------------------------------


class ScheduleRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=r"^[a-zA-Z0-9_.\-]+$")
    timeframe: str = Field("M1", pattern=r"^[a-zA-Z0-9_]+$")
    cron: str | None = None
    interval_minutes: int | None = None


class ScheduleJobInfo(BaseModel):
    job_id: str
    source: str
    asset: str
    timeframe: str
    trigger: str
    cron: str | None = None
    interval_minutes: int | None = None
    next_run: str


class ScheduleListResponse(BaseModel):
    jobs: list[ScheduleJobInfo]


# ---------------------------------------------------------------------------
# Series / FRED models
# ---------------------------------------------------------------------------


class SeriesInfo(BaseModel):
    source: str
    series_id: str
    title: str | None = None
    frequency: str | None = None
    units: str | None = None
    seasonal_adjustment: str | None = None
    observation_start: str | None = None
    observation_end: str | None = None
    last_updated: str | None = None
    rows: int | None = None
    metadata: dict[str, Any] | None = None


class SeriesSearchResponse(BaseModel):
    series: list[Any]


class SeriesListResponse(BaseModel):
    series: list[SeriesInfo]
    total: int
    skip: int
    limit: int
