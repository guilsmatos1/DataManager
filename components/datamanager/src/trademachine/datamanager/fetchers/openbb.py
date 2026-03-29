from datetime import datetime
from typing import Any, cast

import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .base import BaseFetcher


class OpenBBFetcher(BaseFetcher):
    """
    Downloads M1 data via OpenBB (usually YFinance proxy).
    """

    @property
    def source_name(self) -> str:
        return "OpenBB"

    def fetch_data(
        self, asset: str, start_date: datetime, end_date: datetime, **kwargs
    ) -> pd.DataFrame:
        # Obb equity price history method (using yfinance provider as default for M1)
        # Note that in openbb V4 the syntax is struct: obb.equity.price.historical()

        obb_kwargs = {"symbol": asset, "interval": "1m", "provider": "yfinance"}

        # If the year is > 2000, it means the user specified a range.
        # Otherwise (2000-01-01 absolute default of the CLI for Full History),
        # we omit start and end so the provider brings its own historical limit.
        if start_date.year > 2000:
            obb_kwargs["start_date"] = start_date.strftime("%Y-%m-%d")
            obb_kwargs["end_date"] = end_date.strftime("%Y-%m-%d")

        try:
            from openbb import obb

            equity_api = obb.equity  # type: ignore[union-attr]

            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential_jitter(initial=1.0, max=10.0),
                retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
                reraise=True,
            )
            def _fetch_historical() -> Any:
                return cast(Any, equity_api.price.historical(**obb_kwargs))

            res = cast(Any, _fetch_historical())
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
        self._normalize_timezone(df)
        self._normalize_columns(df)

        pbar = kwargs.get("pbar")
        if pbar is not None:
            pbar.update((end_date - start_date).days)

        return df

    def search(self, query: str | None = None, **kwargs) -> pd.DataFrame:
        """Search assets via OpenBB API."""
        from openbb import obb

        search_args: dict[str, str] = {}
        if query:
            search_args["query"] = query
        if "exchange" in kwargs:
            search_args["exchange"] = kwargs["exchange"]

        equity_api = obb.equity  # type: ignore[union-attr]
        res = equity_api.search(**search_args)
        df = res.to_df()
        return df
