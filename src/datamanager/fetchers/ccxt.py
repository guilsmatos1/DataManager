from datetime import datetime, timezone

import pandas as pd
from tqdm import tqdm

from ..utils.retry import with_retry
from .base import BaseFetcher

try:
    import ccxt  # noqa: F401
except ImportError as exc:
    raise ImportError("ccxt is required for the CcxtFetcher: pip install ccxt") from exc

# Default number of M1 candles to request per API call
_CHUNK_SIZE = 500


class CcxtFetcher(BaseFetcher):
    """Fetch M1 OHLCV data for crypto assets via CCXT.

    The exchange can be specified by prefixing the asset with ``exchange:``
    (e.g. ``binance:BTC/USDT``).  When no prefix is given, Binance is used.

    Examples::

        fetch_data("BTC/USDT", start, end)          # uses Binance
        fetch_data("bybit:BTC/USDT", start, end)    # uses Bybit
    """

    @property
    def source_name(self) -> str:
        return "ccxt"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_asset(asset: str) -> tuple[str, str]:
        """Return (exchange_id, symbol).

        Accepts ``exchange:SYMBOL`` or plain ``SYMBOL`` (defaults to binance).
        """
        if ":" in asset:
            exchange_id, symbol = asset.split(":", 1)
        else:
            exchange_id, symbol = "binance", asset
        return exchange_id.lower(), symbol.upper()

    @staticmethod
    def _get_exchange(exchange_id: str):
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Unknown CCXT exchange: '{exchange_id}'")
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({"enableRateLimit": True})
        return exchange

    # ------------------------------------------------------------------
    # BaseFetcher interface
    # ------------------------------------------------------------------

    def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        exchange_id, symbol = self._parse_asset(asset)
        exchange = self._get_exchange(exchange_id)

        if not exchange.has.get("fetchOHLCV"):
            raise ValueError(f"Exchange '{exchange_id}' does not support OHLCV fetching")

        # Convert to millisecond timestamps
        since_ms = int(start_date.replace(tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = int(end_date.replace(tzinfo=timezone.utc).timestamp() * 1000)

        all_rows: list[list] = []
        current_ms = since_ms

        # Estimate total candles for progress bar (approximate)
        total_minutes = max(1, int((end_ms - since_ms) / 60_000))
        pbar = tqdm(total=total_minutes, desc=f"[ccxt/{exchange_id}] {symbol} M1", unit=" candles")

        try:
            while current_ms < end_ms:
                batch = with_retry(
                    exchange.fetch_ohlcv,
                    symbol,
                    timeframe="1m",
                    since=current_ms,
                    limit=_CHUNK_SIZE,
                    exceptions=(OSError, ConnectionError, TimeoutError),
                )
                if not batch:
                    break

                # Filter out candles beyond end_date
                batch = [row for row in batch if row[0] < end_ms]
                if not batch:
                    break

                all_rows.extend(batch)
                pbar.update(len(batch))
                current_ms = batch[-1][0] + 60_000  # advance by 1 minute
        finally:
            pbar.close()

        if not all_rows:
            raise ValueError(f"No data returned for {symbol} on {exchange_id} between {start_date} and {end_date}")

        df = pd.DataFrame(all_rows, columns=["datetime", "Open", "High", "Low", "Close", "Volume"])
        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert(None)
        df.set_index("datetime", inplace=True)
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep="last")]
        return df

    def search(self, query: str = None, **kwargs) -> pd.DataFrame:
        """Return available markets for the given exchange (default: binance)."""
        exchange_id = kwargs.get("exchange", "binance").lower()
        exchange = self._get_exchange(exchange_id)
        markets = exchange.load_markets()
        rows = [
            {"ticker": sym, "base": m.get("base", ""), "quote": m.get("quote", ""), "exchange": exchange_id}
            for sym, m in markets.items()
        ]
        df = pd.DataFrame(rows)
        if query:
            mask = df["ticker"].str.contains(query, case=False, na=False)
            df = df[mask]
        return df
