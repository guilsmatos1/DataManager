from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
from trademachine.datamanager.fetchers.fred import FredFetcher


class _DummyResult:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def to_df(self) -> pd.DataFrame:
        return self._df.copy()


def _install_openbb(
    monkeypatch,
    *,
    search_df: pd.DataFrame | None = None,
    series_df: pd.DataFrame | None = None,
):
    calls: dict[str, dict] = {}

    def fred_search(**kwargs):
        calls["search"] = kwargs
        return _DummyResult(search_df if search_df is not None else pd.DataFrame())

    def fred_series(**kwargs):
        calls["series"] = kwargs
        return _DummyResult(series_df if series_df is not None else pd.DataFrame())

    module = types.ModuleType("openbb")
    module.obb = SimpleNamespace(
        economy=SimpleNamespace(
            fred_search=fred_search,
            fred_series=fred_series,
        )
    )
    monkeypatch.setitem(sys.modules, "openbb", module)
    return calls


def test_search_renames_openbb_columns(monkeypatch):
    calls = _install_openbb(
        monkeypatch,
        search_df=pd.DataFrame(
            {
                "symbol": ["CPIAUCSL"],
                "name": ["Consumer Price Index"],
                "frequency": ["Monthly"],
            }
        ),
    )
    fetcher = FredFetcher()

    result = fetcher.search("inflation")

    assert result.loc[0, "series_id"] == "CPIAUCSL"
    assert result.loc[0, "title"] == "Consumer Price Index"
    assert calls["search"] == {"provider": "fred", "query": "inflation"}


def test_fetch_data_normalizes_to_value_series(monkeypatch):
    calls = _install_openbb(
        monkeypatch,
        series_df=pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=3, freq="D", tz=UTC),
                "value": ["1.0", "2.5", None],
            }
        ),
    )
    fetcher = FredFetcher()

    result = fetcher.fetch_data(
        "CPIAUCSL",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 3, tzinfo=UTC),
        frequency="m",
    )

    assert list(result.columns) == ["Value"]
    assert result["Value"].tolist() == [1.0, 2.5]
    assert result.index.name == "timestamp"
    assert calls["series"]["provider"] == "fred"
    assert calls["series"]["frequency"] == "m"


def test_fetch_data_handles_openbb_date_index_and_series_id_column(monkeypatch):
    _install_openbb(
        monkeypatch,
        series_df=pd.DataFrame(
            {"DFF": [5.33, 5.34]},
            index=pd.Index(
                pd.date_range("2024-01-01", periods=2, freq="D"),
                name="date",
            ),
        ),
    )
    fetcher = FredFetcher()

    result = fetcher.fetch_data(
        "DFF",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 2, tzinfo=UTC),
    )

    assert list(result.columns) == ["Value"]
    assert result.index.name == "timestamp"
    assert result["Value"].tolist() == [5.33, 5.34]
