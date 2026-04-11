from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session
from trademachine.tradingmonitor_ingestion.integrations.datamanager import (
    create_datamanager_client,
)
from trademachine.tradingmonitor_storage.public import Benchmark, BenchmarkPrice


def list_remote_databases(db: Session | None = None) -> list[dict[str, Any]]:
    client = create_datamanager_client(db)
    rows = client.list_databases()
    normalized: list[dict[str, Any]] = [
        {
            "source": str(row.get("source", "")).upper(),
            "asset": str(row.get("asset", "")).upper(),
            "timeframe": str(row.get("timeframe", "")).upper(),
            "status": row.get("status"),
            "rows": row.get("rows"),
            "last_timestamp": row.get("last_timestamp"),
        }
        for row in rows
    ]
    return sorted(normalized, key=lambda r: (r["source"], r["asset"], r["timeframe"]))


def _remote_database_exists(benchmark: Benchmark, db: Session | None = None) -> bool:
    remote_rows = list_remote_databases(db)
    source = benchmark.source.upper()
    asset = benchmark.asset.upper()
    return any(row["source"] == source and row["asset"] == asset for row in remote_rows)


def _trigger_download_if_needed(
    benchmark: Benchmark, db: Session | None = None
) -> bool:
    # Only check if the database exists in DataManager. We should not trigger an external API download.
    return _remote_database_exists(benchmark, db)


def _extract_close_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["close"])

    out = df.copy()
    out.columns = [str(column).lower() for column in out.columns]
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
    remote_ready = _trigger_download_if_needed(benchmark, db)
    if not remote_ready:
        benchmark.last_error = (
            "Benchmark data not found in DataManager. Please download it first."
        )
        db.flush()
        return {"status": "not_found", "message": benchmark.last_error}

    client = create_datamanager_client(db)
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
    price_rows = [
        BenchmarkPrice(
            benchmark_id=benchmark.id,
            timestamp=timestamp.to_pydatetime(),
            close=float(row.close),
        )
        for timestamp, row in close_df.iterrows()
    ]
    db.bulk_save_objects(price_rows)
    benchmark.last_synced_at = datetime.now(UTC)
    benchmark.last_error = None
    db.flush()
    return {
        "status": "synced",
        "message": f"Imported {len(price_rows)} price points.",
        "points": len(price_rows),
    }
