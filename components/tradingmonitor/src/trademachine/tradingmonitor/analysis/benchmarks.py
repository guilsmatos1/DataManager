from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session
from trademachine.datamanager.client import DataManagerClient
from trademachine.tradingmonitor.config import settings
from trademachine.tradingmonitor.db.models import Benchmark, BenchmarkPrice


def create_datamanager_client() -> DataManagerClient:
    from trademachine.tradingmonitor.db.database import SessionLocal
    from trademachine.tradingmonitor.db.models import Setting

    url = settings.datamanager_url
    api_key = settings.datamanager_api_key
    timeout = settings.datamanager_timeout

    try:
        db = SessionLocal()
        for row in (
            db.query(Setting)
            .filter(
                Setting.key.in_(
                    ["datamanager_url", "datamanager_api_key", "datamanager_timeout"]
                )
            )
            .all()
        ):
            if row.value and row.value.strip():
                if row.key == "datamanager_url":
                    url = row.value.strip()
                elif row.key == "datamanager_api_key":
                    api_key = row.value.strip()
                elif row.key == "datamanager_timeout":
                    timeout = float(row.value.strip())
        db.close()
    except Exception:
        pass  # fall back to env config

    return DataManagerClient(
        base_url=url,
        api_key=api_key,
        timeout=timeout,
    )


def _normalize_remote_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "source": str(row.get("source", "")).upper(),
                "asset": str(row.get("asset", "")).upper(),
                "timeframe": str(row.get("timeframe", "")).upper(),
                "status": row.get("status"),
                "rows": row.get("rows"),
                "last_timestamp": row.get("last_timestamp"),
            }
        )
    return normalized


def list_remote_databases() -> list[dict[str, Any]]:
    client = create_datamanager_client()
    rows = client.list_databases()
    return sorted(
        _normalize_remote_rows(rows),
        key=lambda r: (r["source"], r["asset"], r["timeframe"]),
    )


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
    if not benchmark:
        raise ValueError("Benchmark not found.")

    db.query(Benchmark).update({Benchmark.is_default: False})
    benchmark.is_default = True
    db.flush()
    return benchmark


def _remote_database_exists(benchmark: Benchmark) -> bool:
    remote_rows = list_remote_databases()
    source = benchmark.source.upper()
    asset = benchmark.asset.upper()
    return any(row["source"] == source and row["asset"] == asset for row in remote_rows)


def _trigger_download_if_needed(benchmark: Benchmark) -> bool:
    if _remote_database_exists(benchmark):
        return True

    client = create_datamanager_client()
    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=365 * 10)
    client.download(
        source=benchmark.source,
        asset=benchmark.asset,
        start_date=start_dt.date().isoformat(),
        end_date=end_dt.date().isoformat(),
    )

    for _ in range(8):
        time.sleep(1)
        if _remote_database_exists(benchmark):
            return True
    return False


def _extract_close_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["close"])

    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    if "close" not in out.columns:
        raise ValueError("DataManager response does not include a close column.")

    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True)
    elif out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")

    out = out.sort_index()
    return out[["close"]].dropna()


def sync_benchmark_from_datamanager(
    db: Session, benchmark: Benchmark
) -> dict[str, Any]:
    remote_ready = _trigger_download_if_needed(benchmark)
    if not remote_ready:
        benchmark.last_error = (
            "Download started in DataManager. Retry sync in a few seconds."
        )
        db.flush()
        return {"status": "download_started", "message": benchmark.last_error}

    client = create_datamanager_client()
    df = client.get_data(
        source=benchmark.source,
        asset=benchmark.asset,
        timeframe=benchmark.timeframe,
    )
    if not isinstance(df, pd.DataFrame):
        raise ValueError(
            "Unexpected DataManager response while loading benchmark data."
        )

    close_df = _extract_close_frame(df)
    if close_df.empty:
        raise ValueError("No close prices returned from DataManager.")

    db.query(BenchmarkPrice).filter(
        BenchmarkPrice.benchmark_id == benchmark.id
    ).delete()
    rows = [
        BenchmarkPrice(
            benchmark_id=benchmark.id,
            timestamp=ts.to_pydatetime(),
            close=float(row.close),
        )
        for ts, row in close_df.iterrows()
    ]
    db.bulk_save_objects(rows)
    benchmark.last_synced_at = datetime.now(UTC)
    benchmark.last_error = None
    db.flush()
    return {
        "status": "synced",
        "message": f"Imported {len(rows)} price points.",
        "points": len(rows),
    }


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
            "timestamp": [r.timestamp for r in rows],
            "close": [float(r.close) for r in rows],
        }
    ).set_index("timestamp")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()
