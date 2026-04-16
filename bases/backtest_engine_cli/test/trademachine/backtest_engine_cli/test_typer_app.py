import json

import pandas as pd
import polars as pl
from trademachine.backtest_engine_cli.typer_app import app
from typer.testing import CliRunner


def _write_config_and_data(tmp_path):
    broker_dir = tmp_path / "broker"
    broker_dir.mkdir(parents=True)
    (broker_dir / "account_info.json").write_text(
        json.dumps({"account_info": {"login": 1, "balance": 1000.0, "equity": 1000.0}}),
        encoding="utf-8",
    )
    (broker_dir / "symbol_info.json").write_text(
        json.dumps(
            {
                "all_symbols_info": [
                    {
                        "name": "EURUSD",
                        "point": 0.0001,
                        "trade_contract_size": 100000.0,
                        "filling_mode": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    history_dir = (
        tmp_path / "History" / "Bars" / "EURUSD" / "M1" / "year=2024" / "month=1"
    )
    history_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "time": [1704067200, 1704067260],
            "open": [1.1000, 1.1005],
            "high": [1.1010, 1.1015],
            "low": [1.0995, 1.1000],
            "close": [1.1005, 1.1010],
            "tick_volume": [4, 4],
            "spread": [10, 10],
            "real_volume": [0, 0],
        }
    ).write_parquet(history_dir / "chunk.parquet")

    config_path = tmp_path / "tester.json"
    config_path.write_text(
        json.dumps(
            {
                "tester": {
                    "bot_name": "cli-test",
                    "symbols": ["EURUSD"],
                    "timeframe": "H1",
                    "start_date": "01.01.2024 00:00",
                    "end_date": "01.01.2024 00:02",
                    "modelling": "every_tick",
                    "deposit": 1000,
                    "leverage": "1:100",
                }
            }
        ),
        encoding="utf-8",
    )
    return config_path, tmp_path / "History", broker_dir


def test_run_command_outputs_json_summary(tmp_path):
    config_path, history_dir, broker_dir = _write_config_and_data(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            str(config_path),
            "--history-dir",
            str(history_dir),
            "--broker-data-dir",
            str(broker_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["bot_name"] == "cli-test"
    assert payload["total_trades"] == 0


def test_download_data_command_persists_history(tmp_path, monkeypatch):
    class _FakeClient:
        def __init__(self, base_url: str, api_key: str):
            self.base_url = base_url
            self.api_key = api_key

        def get_data(self, source: str, asset: str, timeframe: str):
            assert source == "dukascopy"
            assert asset == "EURUSD"
            assert timeframe == "M1"
            return pd.DataFrame(
                {
                    "Open": [1.1, 1.2],
                    "High": [1.11, 1.21],
                    "Low": [1.09, 1.19],
                    "Close": [1.105, 1.205],
                    "Volume": [10.0, 20.0],
                },
                index=pd.date_range(
                    "2024-01-01 00:00:00", periods=2, freq="min", tz="UTC"
                ),
            )

    monkeypatch.setattr(
        "trademachine.backtest_engine_cli.typer_app.DataManagerClient",
        _FakeClient,
    )

    runner = CliRunner()
    history_dir = tmp_path / "History"
    result = runner.invoke(
        app,
        [
            "download-data",
            "dukascopy",
            "EURUSD",
            "--timeframe",
            "M1",
            "--history-dir",
            str(history_dir),
            "--base-url",
            "http://100.100.10.240:8686",
            "--api-key",
            "test-key",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["asset"] == "EURUSD"
    assert payload["rows"] == 2
    files = list((history_dir / "Bars" / "EURUSD" / "M1").glob("**/*.parquet"))
    assert files


def test_download_data_command_can_bootstrap_remote_download(tmp_path, monkeypatch):
    class _FakeClient:
        def __init__(self, base_url: str, api_key: str):
            self.base_url = base_url
            self.api_key = api_key
            self.calls: list[tuple[str, object]] = []
            self._ready = False

        def download(self, source: str, asset: str, start_date=None, end_date=None):
            self.calls.append(("download", source, asset, start_date, end_date))
            self._ready = True
            return {"status": "success"}

        def get_data(self, source: str, asset: str, timeframe: str):
            self.calls.append(("get_data", source, asset, timeframe))
            if not self._ready:
                raise RuntimeError("not ready")
            return pd.DataFrame(
                {
                    "Open": [1.1],
                    "High": [1.2],
                    "Low": [1.0],
                    "Close": [1.15],
                    "Volume": [10.0],
                },
                index=pd.date_range(
                    "2024-01-01 00:00:00", periods=1, freq="min", tz="UTC"
                ),
            )

    monkeypatch.setattr(
        "trademachine.backtest_engine_cli.typer_app.DataManagerClient",
        _FakeClient,
    )

    runner = CliRunner()
    history_dir = tmp_path / "History"
    result = runner.invoke(
        app,
        [
            "download-data",
            "dukascopy",
            "EURUSD",
            "--history-dir",
            str(history_dir),
            "--api-key",
            "test-key",
            "--download-first",
            "--start-date",
            "2024-01-01T00:00:00",
            "--end-date",
            "2024-01-02T00:00:00",
            "--poll-seconds",
            "0.01",
            "--timeout-seconds",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["download_first"] is True
