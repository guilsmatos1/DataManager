"""Typer application for BacktestEngine."""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from trademachine.backtestengine.public import (
    BacktestConfig,
    run_backtest,
    snapshot_broker_data,
)
from trademachine.backtestengine_history.public import persist_market_data_as_history
from trademachine.core.logger import configure_console_streams
from trademachine.datamanager.public import DataManagerClient

app = typer.Typer(
    help="BacktestEngine CLI - run offline backtests and broker snapshots",
    add_completion=False,
    no_args_is_help=True,
)


def _load_strategy_callback(strategy: str | None) -> Callable[..., Any] | None:
    if strategy is None:
        return None

    module_name, _, function_name = strategy.partition(":")
    if not function_name:
        function_name = "on_tick"

    if module_name.endswith(".py"):
        path = Path(module_name)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise typer.BadParameter(
                f"Could not load strategy module from {module_name}"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_name)

    callback = getattr(module, function_name, None)
    if callback is None:
        raise typer.BadParameter(
            f"Strategy callable '{function_name}' not found in {module_name}"
        )
    return callback


@app.command("run")
def run_command(
    config: str = typer.Argument(..., help="Path to a tester.json-like config file"),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Optional module[:callable] or /path/to/script.py[:callable] strategy hook",
    ),
    history_dir: str = typer.Option("History", help="Historical data directory"),
    broker_data_dir: str = typer.Option(
        "ICMarketsSC-Demo",
        help="Broker snapshot directory",
    ),
    quiet: bool = typer.Option(False, help="Suppress non-essential log output"),
    use_mt5: bool = typer.Option(
        False, "--mt5", help="Use live MT5 for broker/history data"
    ),
) -> None:
    """Runs a backtest and prints a compact JSON summary."""
    configure_console_streams()
    parsed_config = BacktestConfig.from_json_file(config)
    callback = _load_strategy_callback(strategy)
    result = run_backtest(
        parsed_config,
        strategy=callback,
        history_dir=history_dir,
        broker_data_dir=broker_data_dir,
        use_mt5=use_mt5,
        logging_level=logging.ERROR if quiet else logging.WARNING,
    )
    typer.echo(json.dumps(result.to_summary_dict(), indent=2, ensure_ascii=False))


@app.command("snapshot-broker")
def snapshot_broker_command(
    destination: str = typer.Argument(..., help="Output broker snapshot directory"),
    symbols: str | None = typer.Option(
        None,
        help="Comma-separated symbols to snapshot. Defaults to all terminal symbols.",
    ),
) -> None:
    """Exports account and symbol metadata from a live MetaTrader runtime."""
    configure_console_streams()
    selected_symbols = None
    if symbols:
        selected_symbols = [item.strip() for item in symbols.split(",") if item.strip()]
    account, symbol_rows = snapshot_broker_data(
        broker_path=destination,
        symbols=selected_symbols,
    )
    typer.echo(
        json.dumps(
            {
                "account_login": account.login,
                "symbols": len(symbol_rows),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command("download-data")
def download_data_command(
    source: str = typer.Argument(..., help="Remote DataManager source, e.g. dukascopy"),
    asset: str = typer.Argument(..., help="Asset symbol, e.g. EURUSD"),
    timeframe: str = typer.Option("M1", help="Timeframe to fetch from DataManager"),
    history_dir: str = typer.Option(
        "History", help="Local BacktestEngine history directory"
    ),
    base_url: str = typer.Option(
        "http://127.0.0.1:8686",
        "--base-url",
        help="DataManager base URL",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        envvar="DATAMANAGER_API_KEY",
        help="DataManager API key",
    ),
    start_date: str | None = typer.Option(
        None,
        help="Optional start date for remote server download bootstrap (ISO format)",
    ),
    end_date: str | None = typer.Option(
        None,
        help="Optional end date for remote server download bootstrap (ISO format)",
    ),
    download_first: bool = typer.Option(
        False,
        "--download-first",
        help="Ask the remote DataManager to download the asset before fetching it",
    ),
    poll_seconds: float = typer.Option(
        2.0,
        "--poll-seconds",
        help="Polling interval when --download-first is enabled",
    ),
    timeout_seconds: float = typer.Option(
        120.0,
        "--timeout-seconds",
        help="Max wait for the remote dataset after --download-first",
    ),
) -> None:
    """Downloads OHLCV data from a DataManager server into the local history layout."""
    configure_console_streams()
    client = DataManagerClient(base_url=base_url, api_key=api_key)
    if download_first:
        client.download(
            source=source,
            asset=asset,
            start_date=start_date,
            end_date=end_date,
        )

    started_at = time.monotonic()
    while True:
        try:
            dataframe = client.get_data(source=source, asset=asset, timeframe=timeframe)
            break
        except Exception as exc:
            if not download_first:
                raise typer.BadParameter(str(exc)) from exc
            if (time.monotonic() - started_at) >= timeout_seconds:
                raise typer.BadParameter(
                    f"Timed out waiting for remote dataset {source}/{asset}/{timeframe}: {exc}"
                ) from exc
            time.sleep(poll_seconds)

    if isinstance(dataframe, str):
        raise typer.BadParameter(
            "Unexpected file-path response from DataManager client"
        )
    output_dir = persist_market_data_as_history(
        dataframe,
        symbol=asset,
        timeframe=timeframe,
        history_dir=history_dir,
    )
    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "source": source,
                "asset": asset.upper(),
                "timeframe": timeframe.upper(),
                "rows": int(len(dataframe)),
                "history_dir": str(output_dir),
                "download_first": download_first,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
