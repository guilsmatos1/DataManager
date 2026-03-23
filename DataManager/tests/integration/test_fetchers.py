"""Tests for DukascopyFetcher, OpenBBFetcher and CcxtFetcher (all network calls mocked)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv_df(n=5):
    dates = pd.date_range("2023-01-02 00:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"open": [1.0] * n, "high": [2.0] * n, "low": [0.5] * n, "close": [1.5] * n, "volume": [100.0] * n},
        index=dates,
    )


# ---------------------------------------------------------------------------
# DukascopyFetcher
# ---------------------------------------------------------------------------


class TestDukascopyFetcher:
    @pytest.fixture
    def fetcher(self):
        from datamanager.fetchers.dukascopy import DukascopyFetcher

        return DukascopyFetcher()

    def test_source_name(self, fetcher):
        assert fetcher.source_name == "Dukascopy"

    def test_fetch_data_returns_dataframe(self, fetcher, tmp_path, monkeypatch):
        """fetch_data concatenates chunks and returns a normalised DataFrame."""
        monkeypatch.chdir(tmp_path)  # no metadata/dukas_assets.csv → skips validation
        chunk_df = _make_ohlcv_df()

        with patch("datamanager.fetchers.dukascopy.with_retry", return_value=chunk_df):
            result = fetcher.fetch_data("EURUSD", datetime(2023, 1, 2), datetime(2023, 1, 3))

        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        assert "Open" in result.columns

    def test_fetch_data_empty_when_no_chunks(self, fetcher, tmp_path, monkeypatch):
        """fetch_data returns empty DataFrame when all chunks fail."""
        monkeypatch.chdir(tmp_path)

        with patch("datamanager.fetchers.dukascopy.with_retry", side_effect=Exception("no data")):
            result = fetcher.fetch_data("EURUSD", datetime(2023, 1, 2), datetime(2023, 1, 3))

        assert result.empty

    def test_fetch_data_raises_when_asset_not_in_csv(self, fetcher, tmp_path, monkeypatch):
        """Raises ValueError if CSV exists but asset is not found."""
        monkeypatch.chdir(tmp_path)
        meta = tmp_path / "metadata"
        meta.mkdir()
        pd.DataFrame({"ticker": ["GBPUSD"], "alias": [""]}).to_csv(meta / "dukas_assets.csv", index=False)

        with pytest.raises(ValueError, match="does not exist in the Dukascopy database"):
            fetcher.fetch_data("EURUSD", datetime(2023, 1, 2), datetime(2023, 1, 3))

    def test_search_returns_empty_when_no_csv(self, fetcher, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no metadata dir → csv_path.exists() is False
        result = fetcher.search("EUR")
        assert result.empty


# ---------------------------------------------------------------------------
# OpenBBFetcher
# ---------------------------------------------------------------------------


class TestOpenBBFetcher:
    @pytest.fixture
    def fetcher(self):
        from datamanager.fetchers.openbb import OpenBBFetcher

        return OpenBBFetcher()

    def _make_obb_response(self):
        df = _make_ohlcv_df()
        df.index = df.index.tz_convert(None)
        mock_res = MagicMock()
        mock_res.to_df.return_value = df
        return mock_res

    def test_source_name(self, fetcher):
        assert fetcher.source_name == "OpenBB"

    def test_fetch_data_returns_dataframe(self, fetcher):
        obb_response = self._make_obb_response()

        with (
            patch("datamanager.fetchers.openbb.with_retry", return_value=obb_response),
            patch.dict("sys.modules", {"openbb": MagicMock(obb=MagicMock())}),
        ):
            result = fetcher.fetch_data("AAPL", datetime(2023, 1, 2), datetime(2023, 1, 3))

        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_fetch_data_raises_on_empty_response(self, fetcher):
        empty_res = MagicMock()
        empty_res.to_df.return_value = pd.DataFrame()

        with (
            patch("datamanager.fetchers.openbb.with_retry", return_value=empty_res),
            patch.dict("sys.modules", {"openbb": MagicMock(obb=MagicMock())}),
        ):
            with pytest.raises(ValueError, match="returned empty"):
                fetcher.fetch_data("AAPL", datetime(2023, 1, 2), datetime(2023, 1, 3))

    def test_fetch_data_raises_on_exception(self, fetcher):
        with (
            patch("datamanager.fetchers.openbb.with_retry", side_effect=RuntimeError("API down")),
            patch.dict("sys.modules", {"openbb": MagicMock(obb=MagicMock())}),
        ):
            with pytest.raises(RuntimeError):
                fetcher.fetch_data("AAPL", datetime(2023, 1, 2), datetime(2023, 1, 3))

    def test_columns_are_capitalised(self, fetcher):
        df = _make_ohlcv_df().tz_localize(None)
        res = MagicMock()
        res.to_df.return_value = df

        with (
            patch("datamanager.fetchers.openbb.with_retry", return_value=res),
            patch.dict("sys.modules", {"openbb": MagicMock(obb=MagicMock())}),
        ):
            result = fetcher.fetch_data("AAPL", datetime(2023, 1, 2), datetime(2023, 1, 3))

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            assert col in result.columns


# ---------------------------------------------------------------------------
# CcxtFetcher
# ---------------------------------------------------------------------------


class TestCcxtFetcher:
    @pytest.fixture
    def fetcher(self):
        # We need to mock ccxt before importing CcxtFetcher if it's not installed
        # or just to avoid any real interaction.
        with patch.dict("sys.modules", {"ccxt": MagicMock()}):
            from datamanager.fetchers.ccxt import CcxtFetcher

            return CcxtFetcher()

    def test_source_name(self, fetcher):
        assert fetcher.source_name == "ccxt"

    def test_parse_asset(self, fetcher):
        assert fetcher._parse_asset("BTC/USDT") == ("binance", "BTC/USDT")
        assert fetcher._parse_asset("bybit:ETH/USDT") == ("bybit", "ETH/USDT")

    def test_fetch_data_success(self, fetcher):
        mock_exchange = MagicMock()
        mock_exchange.has = {"fetchOHLCV": True}
        # CCXT returns list of lists: [timestamp, open, high, low, close, volume]
        data = [
            [1672617600000, 16000, 16100, 15900, 16050, 100],
            [1672617660000, 16050, 16200, 16000, 16150, 150],
        ]
        # Return data on first call, empty list on subsequent calls to avoid infinite loop
        mock_exchange.fetch_ohlcv.side_effect = [data, []]

        with (
            patch("datamanager.fetchers.ccxt.with_retry", side_effect=lambda f, *a, **k: f(*a, **k)),
            patch.object(fetcher, "_get_exchange", return_value=mock_exchange),
        ):
            result = fetcher.fetch_data("BTC/USDT", datetime(2023, 1, 2), datetime(2023, 1, 2, 0, 5))

        assert len(result) == 2
        assert "Open" in result.columns
        assert result.index[0] == pd.Timestamp("2023-01-02 00:00:00")

    def test_fetch_data_no_support(self, fetcher):
        mock_exchange = MagicMock()
        mock_exchange.has = {"fetchOHLCV": False}

        with patch.object(fetcher, "_get_exchange", return_value=mock_exchange):
            with pytest.raises(ValueError, match="does not support OHLCV fetching"):
                fetcher.fetch_data("BTC/USDT", datetime(2023, 1, 2), datetime(2023, 1, 3))

    def test_fetch_data_no_data_raises(self, fetcher):
        mock_exchange = MagicMock()
        mock_exchange.has = {"fetchOHLCV": True}
        mock_exchange.fetch_ohlcv.return_value = []

        with (
            patch("datamanager.fetchers.ccxt.with_retry", return_value=[]),
            patch.object(fetcher, "_get_exchange", return_value=mock_exchange),
        ):
            with pytest.raises(ValueError, match="No data returned"):
                fetcher.fetch_data("BTC/USDT", datetime(2023, 1, 2), datetime(2023, 1, 3))

    def test_search_calls_load_markets(self, fetcher):
        mock_exchange = MagicMock()
        mock_exchange.load_markets.return_value = {
            "BTC/USDT": {"base": "BTC", "quote": "USDT"},
            "ETH/USDT": {"base": "ETH", "quote": "USDT"},
        }

        with patch.object(fetcher, "_get_exchange", return_value=mock_exchange):
            result = fetcher.search("BTC")

        assert len(result) == 1
        assert result.iloc[0]["ticker"] == "BTC/USDT"
