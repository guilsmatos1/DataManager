from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trademachine.tradingmonitor_ingestion.public import (
    list_remote_databases,
    sync_benchmark_from_datamanager,
)

__all__ = ["list_remote_databases", "sync_benchmark_from_datamanager"]
from trademachine.tradingmonitor_storage.public import Benchmark, BenchmarkPrice


class BenchmarkConflictError(ValueError):
    """Raised when a benchmark would violate the uniqueness constraint."""


class BenchmarkNotFoundError(LookupError):
    """Raised when the requested benchmark does not exist."""


def get_benchmark_stats(
    db: Session, benchmark_ids: list[int]
) -> dict[int, dict[str, Any]]:
    if not benchmark_ids:
        return {}

    rows = (
        db.query(
            BenchmarkPrice.benchmark_id,
            func.count(BenchmarkPrice.timestamp),
            func.max(BenchmarkPrice.timestamp),
        )
        .filter(BenchmarkPrice.benchmark_id.in_(benchmark_ids))
        .group_by(BenchmarkPrice.benchmark_id)
        .all()
    )
    return {
        int(benchmark_id): {
            "local_points": int(points or 0),
            "latest_price_timestamp": latest_ts,
        }
        for benchmark_id, points, latest_ts in rows
    }


def benchmark_to_dict(db: Session, benchmark: Benchmark) -> dict[str, Any]:
    stats = get_benchmark_stats(db, [benchmark.id]).get(benchmark.id, {})
    return {
        "id": benchmark.id,
        "name": benchmark.name,
        "source": benchmark.source,
        "asset": benchmark.asset,
        "timeframe": benchmark.timeframe,
        "description": benchmark.description,
        "is_default": benchmark.is_default,
        "enabled": benchmark.enabled,
        "last_synced_at": benchmark.last_synced_at,
        "last_error": benchmark.last_error,
        "local_points": stats.get("local_points", 0),
        "latest_price_timestamp": stats.get("latest_price_timestamp"),
    }


def set_default_benchmark(db: Session, benchmark_id: int) -> Benchmark:
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if benchmark is None:
        raise BenchmarkNotFoundError("Benchmark not found.")

    db.query(Benchmark).update({Benchmark.is_default: False})
    benchmark.is_default = True
    db.flush()
    return benchmark


def list_benchmark_payloads(db: Session) -> list[dict[str, Any]]:
    benchmarks = (
        db.query(Benchmark)
        .order_by(Benchmark.is_default.desc(), Benchmark.name.asc())
        .all()
    )
    return [benchmark_to_dict(db, benchmark) for benchmark in benchmarks]


def create_benchmark_record(
    db: Session,
    *,
    name: str,
    source: str,
    asset: str,
    timeframe: str,
    description: str | None,
    enabled: bool,
    is_default: bool,
) -> dict[str, Any]:
    normalized_source = source.strip().upper()
    normalized_asset = asset.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    existing = (
        db.query(Benchmark)
        .filter(
            Benchmark.source == normalized_source,
            Benchmark.asset == normalized_asset,
            Benchmark.timeframe == normalized_timeframe,
        )
        .first()
    )
    if existing is not None:
        raise BenchmarkConflictError("Benchmark already exists")

    benchmark = Benchmark(
        name=name.strip(),
        source=normalized_source,
        asset=normalized_asset,
        timeframe=normalized_timeframe,
        description=description,
        enabled=enabled,
        is_default=False,
    )
    db.add(benchmark)
    try:
        db.flush()
        if is_default:
            set_default_benchmark(db, benchmark.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BenchmarkConflictError("Benchmark already exists") from exc

    db.refresh(benchmark)
    return benchmark_to_dict(db, benchmark)


def update_benchmark_record(
    db: Session,
    benchmark_id: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if benchmark is None:
        raise BenchmarkNotFoundError("Benchmark not found")

    data = changes.copy()
    is_default = data.pop("is_default", None)
    candidate_source = benchmark.source
    candidate_asset = benchmark.asset
    candidate_timeframe = benchmark.timeframe

    for field, value in data.items():
        if field in {"source", "asset", "timeframe"} and isinstance(value, str):
            value = value.strip().upper()
        if field == "source":
            candidate_source = value
        elif field == "asset":
            candidate_asset = value
        elif field == "timeframe":
            candidate_timeframe = value
        setattr(benchmark, field, value)

    with db.no_autoflush:
        duplicate = (
            db.query(Benchmark)
            .filter(
                Benchmark.id != benchmark_id,
                Benchmark.source == candidate_source,
                Benchmark.asset == candidate_asset,
                Benchmark.timeframe == candidate_timeframe,
            )
            .first()
        )
    if duplicate is not None:
        raise BenchmarkConflictError("Benchmark already exists")

    if is_default is True:
        set_default_benchmark(db, benchmark.id)
    elif is_default is False:
        benchmark.is_default = False

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BenchmarkConflictError("Benchmark already exists") from exc

    db.refresh(benchmark)
    return benchmark_to_dict(db, benchmark)


def set_default_benchmark_record(db: Session, benchmark_id: int) -> dict[str, Any]:
    benchmark = set_default_benchmark(db, benchmark_id)
    db.commit()
    db.refresh(benchmark)
    return benchmark_to_dict(db, benchmark)


def delete_benchmark_record(db: Session, benchmark_id: int) -> None:
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if benchmark is None:
        raise BenchmarkNotFoundError("Benchmark not found")

    db.delete(benchmark)
    db.commit()


def sync_benchmark_record(db: Session, benchmark_id: int) -> dict[str, Any]:
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if benchmark is None:
        raise BenchmarkNotFoundError("Benchmark not found")

    try:
        result = sync_benchmark_from_datamanager(db, benchmark)
        db.commit()
        return {**result, "benchmark": benchmark_to_dict(db, benchmark)}
    except Exception as exc:
        benchmark.last_error = str(exc)
        db.commit()
        raise


def load_benchmark_curve(
    db: Session,
    benchmark_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> pd.DataFrame:
    query = db.query(BenchmarkPrice).filter(BenchmarkPrice.benchmark_id == benchmark_id)
    if date_from is not None:
        query = query.filter(BenchmarkPrice.timestamp >= date_from)
    if date_to is not None:
        query = query.filter(BenchmarkPrice.timestamp <= date_to)

    rows = query.order_by(BenchmarkPrice.timestamp.asc()).all()
    if not rows:
        return pd.DataFrame(columns=["close"])

    df = pd.DataFrame(
        {
            "timestamp": [row.timestamp for row in rows],
            "close": [float(row.close) for row in rows],
        }
    ).set_index("timestamp")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()
