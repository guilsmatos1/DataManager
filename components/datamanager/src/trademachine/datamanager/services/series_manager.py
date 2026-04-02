from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pandas as pd
from trademachine.core.logger import LOGGER_NAME
from trademachine.datamanager.db.series_storage import SeriesStorageManager
from trademachine.datamanager.fetchers.fred import FredFetcher

logger = logging.getLogger(LOGGER_NAME)


class SeriesManager:
    """Orchestrates FRED economic series operations."""

    def __init__(
        self,
        storage: SeriesStorageManager | None = None,
        fetcher: FredFetcher | None = None,
    ):
        self.storage = storage or SeriesStorageManager()
        self.fetcher = fetcher or FredFetcher()

    @staticmethod
    def _validate_source(source: str) -> str:
        if source.lower() != "fred":
            raise ValueError("Only the FRED source is supported for economic series.")
        return source.lower()

    @staticmethod
    def _coerce_datetime(value: str | datetime | None, default: datetime) -> datetime:
        if value is None:
            return default
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    @staticmethod
    def _parse_lookback_period(
        lookback_period: str | None,
        default_days: int = 365,
    ) -> timedelta:
        if not lookback_period:
            return timedelta(days=default_days)

        raw = lookback_period.strip().upper()
        if raw.endswith("D") and raw[:-1].isdigit():
            return timedelta(days=int(raw[:-1]))
        if raw.endswith("W") and raw[:-1].isdigit():
            return timedelta(weeks=int(raw[:-1]))
        if raw.endswith("M") and raw[:-1].isdigit():
            return timedelta(days=int(raw[:-1]) * 30)
        if raw.endswith("Y") and raw[:-1].isdigit():
            return timedelta(days=int(raw[:-1]) * 365)
        if raw.isdigit():
            return timedelta(days=int(raw))

        raise ValueError(
            "Invalid lookback_period. Use values like '30D', '12M', '2Y', or '365'."
        )

    @staticmethod
    def _to_series_info_payload(info: dict[str, Any]) -> dict[str, Any]:
        if info.get("status") == "Not Found":
            return {}

        return {
            "source": info["source"],
            "series_id": info["series_id"],
            "title": info.get("title"),
            "frequency": info.get("frequency") or info.get("native_frequency"),
            "units": info.get("units"),
            "seasonal_adjustment": info.get("seasonal_adjustment"),
            "observation_start": info.get("observation_start"),
            "observation_end": info.get("observation_end"),
            "last_updated": info.get("last_updated") or info.get("last_fetched_at"),
            "rows": info.get("rows"),
            "metadata": info.get("metadata") or {},
        }

    def search_series(
        self, source: str = "fred", query: str | None = None
    ) -> pd.DataFrame:
        self._validate_source(source)
        return cast(pd.DataFrame, self.fetcher.search(query=query))

    def download_series(
        self,
        source: str,
        series_id: str,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        frequency: str | None = None,
    ) -> dict:
        normalized_source = self._validate_source(source)
        start_dt = self._coerce_datetime(
            start_date, default=datetime(1900, 1, 1, tzinfo=UTC)
        )
        end_dt = self._coerce_datetime(end_date, default=datetime.now(UTC))

        logger.info(f"Downloading FRED series {series_id}...")
        metadata = self.fetcher.fetch_metadata(series_id)
        df = self.fetcher.fetch_data(series_id, start_dt, end_dt, frequency=frequency)
        rows = self.storage.save_series_data(
            df,
            normalized_source,
            series_id,
            metadata=metadata,
            update_stats=True,
        )
        return {"status": "ok", "series_id": series_id, "rows": rows}

    def update_series(
        self,
        source: str,
        series_id: str,
        lookback_period: str | None = None,
        frequency: str | None = None,
    ) -> dict:
        normalized_source = self._validate_source(source)
        info = self.storage.get_series_info(normalized_source, series_id)
        if info.get("status") == "Not Found":
            raise FileNotFoundError(
                f"Series not found: {normalized_source}/{series_id}"
            )

        end_date = datetime.now(UTC)
        last_end = info.get("observation_end")
        if last_end:
            start_date = self._coerce_datetime(last_end, end_date)
            start_date -= self._parse_lookback_period(lookback_period)
        else:
            start_date = datetime(1900, 1, 1, tzinfo=UTC)

        metadata = self.fetcher.fetch_metadata(series_id)
        df = self.fetcher.fetch_data(
            series_id,
            start_date,
            end_date,
            frequency=frequency,
        )
        rows = self.storage.save_series_data(
            df,
            normalized_source,
            series_id,
            metadata=metadata,
            update_stats=True,
        )
        return {"status": "ok", "series_id": series_id, "rows": rows}

    def list_series(self, source: str = "fred") -> list[dict]:
        normalized_source = self._validate_source(source)
        return [
            self._to_series_info_payload(item)
            for item in self.storage.list_series()
            if item.get("source") == normalized_source
        ]

    def info_series(self, source: str, series_id: str) -> dict:
        normalized_source = self._validate_source(source)
        return self._to_series_info_payload(
            self.storage.get_series_info(normalized_source, series_id)
        )

    def load_series_data(self, source: str, series_id: str) -> pd.DataFrame:
        normalized_source = self._validate_source(source)
        return self.storage.load_series_data(normalized_source, series_id)

    def delete_series(self, source: str, series_id: str) -> bool:
        normalized_source = self._validate_source(source)
        return self.storage.delete_series(normalized_source, series_id)
