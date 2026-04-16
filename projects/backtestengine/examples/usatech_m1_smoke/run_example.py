"""Download USATECH M1 data and run an every_tick smoke test."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from strategy import on_tick
from trademachine.backtestengine.public import BacktestConfig, run_backtest
from trademachine.backtestengine_history.public import persist_market_data_as_history
from trademachine.datamanager.public import DataManagerClient

DEFAULT_BASE_URL = "http://100.100.10.240:8686"
DEFAULT_SOURCE = "dukascopy"
DEFAULT_ASSET = "USATECH"
DEFAULT_TIMEFRAME = "M1"
DEFAULT_START_DATE = "2026-04-09T00:00:00"
DEFAULT_END_DATE = "2026-04-10T00:00:00"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download USATECH M1 data from DataManager and run an every_tick smoke test."
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DATAMANAGER_API_KEY"),
        help="DataManager API key. Defaults to DATAMANAGER_API_KEY.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--asset", default=DEFAULT_ASSET)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Run with the local History directory without downloading again.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.api_key and not args.skip_download:
        parser.error(
            "Provide --api-key or export DATAMANAGER_API_KEY before downloading."
        )

    base_dir = Path(__file__).resolve().parent
    history_dir = base_dir / "History"
    broker_data_dir = base_dir / "Broker"
    config_path = base_dir / "tester.json"
    broker_data_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        client = DataManagerClient(
            base_url=args.base_url, api_key=args.api_key, timeout=120.0
        )
        dataframe = client.get_data(
            source=args.source,
            asset=args.asset,
            timeframe=args.timeframe,
        )
        if isinstance(dataframe, str):
            raise RuntimeError("Unexpected file-path response from DataManager client")

        window = dataframe.loc[
            f"{args.start_date}+00:00" : f"{args.end_date}+00:00"
        ].copy()
        if window.empty:
            raise RuntimeError(
                f"No rows returned for {args.asset} between {args.start_date} and {args.end_date}"
            )

        persist_market_data_as_history(
            window,
            symbol=args.asset,
            timeframe=args.timeframe,
            history_dir=str(history_dir),
        )

    result = run_backtest(
        BacktestConfig.from_json_file(config_path),
        strategy=on_tick,
        history_dir=str(history_dir),
        broker_data_dir=str(broker_data_dir),
    )
    print(json.dumps(result.to_summary_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
