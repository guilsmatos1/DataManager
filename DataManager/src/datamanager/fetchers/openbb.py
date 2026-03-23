from datetime import datetime

import pandas as pd

from ..utils.retry import with_retry
from .base import BaseFetcher


class OpenBBFetcher(BaseFetcher):
    """
    Downloads M1 data via OpenBB (usually YFinance proxy).
    """

    @property
    def source_name(self) -> str:
        return "OpenBB"

    def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        # Obb equity price history method (using yfinance provider as default for M1)
        # Note that in openbb V4 the syntax is struct: obb.equity.price.historical()

        kwargs = {"symbol": asset, "interval": "1m", "provider": "yfinance"}

        # If the year is > 2000, it means the user specified a range.
        # Otherwise (2000-01-01 absolute default of the CLI for Full History),
        # we omit start and end so the provider brings its own historical limit.
        if start_date.year > 2000:
            kwargs["start_date"] = start_date.strftime("%Y-%m-%d")
            kwargs["end_date"] = end_date.strftime("%Y-%m-%d")

        try:
            from openbb import obb

            res = with_retry(
                obb.equity.price.historical,
                exceptions=(OSError, ConnectionError, TimeoutError),
                **kwargs,
            )
            df = res.to_df()
        except Exception as e:
            raise RuntimeError(f"Error fetching {asset} from OpenBB: {str(e)}")

        if df.empty:
            raise ValueError(
                f"OpenBB (YFinance) returned empty for {asset} from {start_date.date()} to {end_date.date()}"
            )  # noqa: E501

        # OpenBB V4 returns the "date" index
        if df.index.name != "date" and "date" in df.columns:
            df.set_index("date", inplace=True)

        # Adjust timezone and columns to match the standard layout of the storage manager
        if df.index.tz is not None:
            df.index = df.index.tz_convert(None)

        col_map = {c.lower(): c.capitalize() for c in df.columns}
        df.rename(columns=col_map, inplace=True)

        return df

    def search(self, query: str = None, **kwargs) -> pd.DataFrame:
        """Search assets via OpenBB API."""
        from openbb import obb

        search_args = {}
        if query:
            search_args["query"] = query
        if "exchange" in kwargs:
            search_args["exchange"] = kwargs["exchange"]

        res = obb.equity.search(**search_args)
        df = res.to_df()
        return df
