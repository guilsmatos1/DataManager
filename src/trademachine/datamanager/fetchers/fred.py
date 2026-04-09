from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pandas as pd

from .base import FETCH_RETRY


class FredFetcher:
    """Fetch FRED economic series through OpenBB."""

    @property
    def source_name(self) -> str:
        return "fred"

    @staticmethod
    def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        if result.empty:
            return result

        if not isinstance(result.index, pd.DatetimeIndex):
            converted_index = pd.to_datetime(result.index, errors="coerce")
            if not converted_index.isna().all():
                result.index = pd.DatetimeIndex(converted_index)

        if not isinstance(result.index, pd.DatetimeIndex):
            for candidate in [
                "timestamp",
                "date",
                "datetime",
                "observation_date",
            ]:
                if candidate in result.columns:
                    result[candidate] = pd.to_datetime(
                        result[candidate], errors="coerce"
                    )
                    result.set_index(candidate, inplace=True)
                    break

        if not isinstance(result.index, pd.DatetimeIndex):
            raise ValueError("FRED series must expose a datetime index or date column.")

        if result.index.tz is not None:
            result.index = result.index.tz_convert(None)

        result.sort_index(inplace=True)
        result = result[~result.index.duplicated(keep="last")]
        result.index.name = "timestamp"

        columns = {c.lower(): c for c in result.columns}
        value_column = None
        for candidate in ["value", "observation_value", "series_value"]:
            if candidate in columns:
                value_column = columns[candidate]
                break

        if value_column is None:
            numeric_candidates = [
                c for c in result.columns if c.lower() not in {"timestamp"}
            ]
            if len(numeric_candidates) == 1:
                value_column = numeric_candidates[0]
            else:
                raise ValueError("Unable to determine the FRED value column.")

        if value_column != "Value":
            result.rename(columns={value_column: "Value"}, inplace=True)

        result["Value"] = pd.to_numeric(result["Value"], errors="coerce")
        result.dropna(subset=["Value"], inplace=True)
        return result[["Value"]]

    def search(self, query: str | None = None, **kwargs) -> pd.DataFrame:
        from openbb import obb

        search_args: dict[str, Any] = {"provider": "fred"}
        if query is not None:
            search_args["query"] = query

        try:
            res = cast(Any, obb.economy.fred_search(**search_args))  # type: ignore[union-attr]
            df = res.to_df()
        except Exception as exc:
            raise RuntimeError(f"Error searching FRED series: {exc}") from exc

        if df.empty:
            return df

        rename_map = {}
        for source_col in ["symbol", "id"]:
            if source_col in df.columns and "series_id" not in df.columns:
                rename_map[source_col] = "series_id"
                break
        if "name" in df.columns and "title" not in df.columns:
            rename_map["name"] = "title"
        if rename_map:
            df = df.rename(columns=rename_map)
        return df

    def fetch_metadata(self, series_id: str) -> dict[str, Any]:
        search_df = self.search(series_id)
        if search_df.empty:
            return {"series_id": series_id}

        normalized = search_df.copy()
        if "series_id" not in normalized.columns:
            normalized["series_id"] = series_id

        exact = normalized
        if "series_id" in normalized.columns:
            exact_match = normalized[
                normalized["series_id"].astype(str).str.upper() == series_id.upper()
            ]
            if not exact_match.empty:
                exact = exact_match

        row = exact.iloc[0].to_dict()
        row.setdefault("series_id", series_id)
        return row  # type: ignore[no-any-return]

    def fetch_data(
        self, asset: str, start_date: datetime, end_date: datetime, **kwargs
    ) -> pd.DataFrame:
        from openbb import obb

        fred_kwargs: dict[str, Any] = {
            "symbol": asset,
            "provider": "fred",
        }

        if start_date:
            fred_kwargs["start_date"] = start_date.date().isoformat()
        if end_date:
            fred_kwargs["end_date"] = end_date.date().isoformat()
        if "frequency" in kwargs and kwargs["frequency"]:
            fred_kwargs["frequency"] = kwargs["frequency"]

        @FETCH_RETRY
        def _fetch() -> Any:
            return cast(Any, obb.economy.fred_series(**fred_kwargs))  # type: ignore[union-attr]

        try:
            res = _fetch()
            df = res.to_df()
        except Exception as exc:
            raise RuntimeError(f"Error fetching FRED series {asset}: {exc}") from exc

        if df.empty:
            raise ValueError(
                f"FRED returned empty data for {asset} between {start_date.date()} and {end_date.date()}"
            )

        return self._normalize_dataframe(df)
