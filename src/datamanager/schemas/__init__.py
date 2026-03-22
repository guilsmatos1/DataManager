from typing import Any, Optional

from pydantic import BaseModel, Field

SAFE_PATTERN = r"^[a-zA-Z0-9_,\s\-]+$"

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class DownloadRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class UpdateRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    timeframe: str = Field("M1", pattern=r"^[a-zA-Z0-9_]+$")


class DeleteRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    timeframe: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_]+$")


class ResampleRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    target_timeframe: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")


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
    file_size_kb: float


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
    cron: Optional[str] = None
    interval_minutes: Optional[int] = None


class ScheduleJobInfo(BaseModel):
    job_id: str
    source: str
    asset: str
    timeframe: str
    trigger: str
    cron: Optional[str] = None
    interval_minutes: Optional[int] = None
    next_run: str


class ScheduleListResponse(BaseModel):
    jobs: list[ScheduleJobInfo]
