"""Unit tests for DataManager fetchers."""

from datetime import datetime

import pandas as pd
import pytest
from trademachine.datamanager.fetchers.base import BaseFetcher


class ConcreteFetcher(BaseFetcher):
    """Concrete implementation of BaseFetcher for testing."""

    @property
    def source_name(self) -> str:
        return "TEST"

    def fetch_data(
        self, asset: str, start_date: datetime, end_date: datetime
    ) -> pd.DataFrame:
        return pd.DataFrame()


class TestBaseFetcher:
    """Tests for BaseFetcher common methods."""

    @pytest.fixture
    def fetcher(self) -> ConcreteFetcher:
        return ConcreteFetcher()

    # ── _normalize_timezone ─────────────────────────────────────────────────

    def test_normalize_timezone_removes_tz(self, fetcher):
        """_normalize_timezone should convert tz-aware index to naive."""
        df = pd.DataFrame(
            {
                "Open": [100],
                "High": [105],
                "Low": [95],
                "Close": [102],
                "Volume": [1000],
            },
            index=pd.DatetimeIndex(["2024-01-01"]).tz_localize("UTC"),
        )

        result = fetcher._normalize_timezone(df)

        assert result.index.tz is None

    def test_normalize_timezone_preserves_naive(self, fetcher):
        """_normalize_timezone should not modify tz-naive index."""
        df = pd.DataFrame(
            {
                "Open": [100],
                "High": [105],
                "Low": [95],
                "Close": [102],
                "Volume": [1000],
            },
            index=pd.DatetimeIndex(["2024-01-01"]),
        )

        result = fetcher._normalize_timezone(df)

        assert result.index.tz is None

    # ── _normalize_columns ──────────────────────────────────────────────────

    def test_normalize_columns_renames_lowercase(self, fetcher):
        """_normalize_columns should rename lowercase columns to Title-Case."""
        df = pd.DataFrame(
            {
                "open": [100],
                "high": [105],
                "low": [95],
                "close": [102],
                "volume": [1000],
            }
        )

        result = fetcher._normalize_columns(df)

        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_normalize_columns_preserves_title_case(self, fetcher):
        """_normalize_columns should not change already Title-Case columns."""
        df = pd.DataFrame(
            {
                "Open": [100],
                "High": [105],
                "Low": [95],
                "Close": [102],
                "Volume": [1000],
            }
        )

        result = fetcher._normalize_columns(df)

        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    # ── search ──────────────────────────────────────────────────────────────

    def test_search_raises_not_implemented(self, fetcher):
        """search should raise NotImplementedError by default."""
        with pytest.raises(NotImplementedError, match="Search not implemented"):
            fetcher.search("BTC")
