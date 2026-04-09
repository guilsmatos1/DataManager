from unittest.mock import Mock

import pandas as pd
from trademachine.datamanager_cli.cli import DataManagerCLI


class _FakeStorage:
    def check_connection(self):
        return None


class _FakeDataManager:
    def __init__(self):
        self.storage = _FakeStorage()
        self.calls = []

    def download_data(self, source, asset, start_date, end_date):
        self.calls.append(("download_data", source, asset, start_date, end_date))

    def update_data(self, source, asset, timeframe="M1"):
        self.calls.append(("update_data", source, asset, timeframe))

    def resample_data(self, source, asset, timeframe):
        self.calls.append(("resample_data", source, asset, timeframe))

    def show_search_summary(self):
        self.calls.append(("show_search_summary",))

    def list_all(self):
        self.calls.append(("list_all",))
        return []

    def info(self, source, asset, timeframe):
        self.calls.append(("info", source, asset, timeframe))
        return {"status": "Not Found"}

    def delete_database(self, source, asset, timeframe=None):
        self.calls.append(("delete_database", source, asset, timeframe))


class _FakeScheduler:
    def __init__(self, server):
        self.server = server

    def start(self):
        return None

    def shutdown(self):
        return None

    def add_job(self, *args, **kwargs):
        return {
            "job_id": "job-1",
            "next_run": "2026-04-02 12:00:00",
        }

    def list_jobs(self):
        return []

    def remove_job(self, job_id):
        return True


class _FakeSeriesManager:
    def __init__(self):
        self.calls = []

    def search_series(self, source="fred", query=None):
        self.calls.append(("search", query))
        return pd.DataFrame(
            [{"series_id": "CPIAUCSL", "title": "Inflation", "frequency": "Monthly"}]
        )

    def download_series(
        self,
        source,
        series_id,
        start_date=None,
        end_date=None,
        frequency=None,
    ):
        self.calls.append(
            ("download", source, series_id, start_date, end_date, frequency)
        )
        return {"status": "ok", "series_id": series_id, "rows": 1}

    def update_series(self, source, series_id, lookback_period=None, frequency=None):
        self.calls.append(("update", source, series_id, lookback_period, frequency))
        return {"status": "ok", "series_id": series_id, "rows": 1}

    def list_series(self):
        self.calls.append(("list",))
        return [
            {
                "source": "fred",
                "series_id": "CPIAUCSL",
                "title": "Inflation",
                "frequency": "Monthly",
                "rows": 12,
                "observation_start": "2024-01-01",
                "observation_end": "2024-12-01",
            }
        ]

    def info_series(self, source, series_id):
        self.calls.append(("info", source, series_id))
        return {
            "source": source,
            "series_id": series_id,
            "title": "Inflation",
            "frequency": "Monthly",
            "rows": 12,
        }

    def delete_series(self, source, series_id):
        self.calls.append(("delete", source, series_id))
        return True


class _FakeSeriesScheduler(_FakeScheduler):
    def add_series_job(
        self,
        source,
        series_id,
        lookback_period=None,
        frequency=None,
        cron=None,
        interval_minutes=None,
    ):
        self.calls = getattr(self, "calls", [])
        self.calls.append(
            (
                "add_series_job",
                source,
                series_id,
                lookback_period,
                frequency,
                cron,
                interval_minutes,
            )
        )
        return {
            "job_id": "series-job-1",
            "next_run": "2026-04-02 12:00:00",
        }


def test_read_interactive_input_falls_back_to_builtin_input(monkeypatch):
    cli = DataManagerCLI.__new__(DataManagerCLI)
    monkeypatch.setattr("builtins.input", lambda prompt: "list")
    assert cli._read_interactive_input(None) == "list"


def test_cmdloop_uses_prompt_session_history(monkeypatch):
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.DataManager", _FakeDataManager
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SchedulerService", _FakeScheduler
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SeriesManager", _FakeSeriesManager
    )

    cli = DataManagerCLI()
    mock_session = Mock()
    mock_session.prompt.side_effect = ["help", "quit"]
    monkeypatch.setattr(cli, "_create_prompt_session", lambda: mock_session)
    monkeypatch.setattr(
        cli, "_read_interactive_input", lambda session: session.prompt()
    )

    handled = []
    original_onecmd = cli.onecmd

    def tracking_onecmd(line):
        handled.append(line)
        return original_onecmd(line)

    monkeypatch.setattr(cli, "onecmd", tracking_onecmd)
    cli.cmdloop()

    assert handled[:2] == ["help", "quit"]


def test_standard_commands_accept_fred_source(monkeypatch):
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.DataManager", _FakeDataManager
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SchedulerService", _FakeScheduler
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SeriesManager", _FakeSeriesManager
    )

    cli = DataManagerCLI()

    cli.do_search("--source fred --query inflation")
    cli.do_download("fred CPIAUCSL 2024-01-01 2024-12-31 --frequency m")
    cli.do_update("fred CPIAUCSL --lookback 30D --frequency m")
    cli.do_list("--source fred")
    cli.do_info("fred CPIAUCSL")
    cli.do_delete("fred CPIAUCSL")

    assert cli.series_server.calls == [
        ("search", "inflation"),
        (
            "download",
            "fred",
            "CPIAUCSL",
            "2024-01-01T00:00:00",
            "2024-12-31T00:00:00",
            "m",
        ),
        ("update", "fred", "CPIAUCSL", "30D", "m"),
        ("list",),
        ("info", "fred", "CPIAUCSL"),
        ("delete", "fred", "CPIAUCSL"),
    ]
    assert cli.server.calls == []


def test_schedule_add_series_uses_series_job(monkeypatch):
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.DataManager", _FakeDataManager
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SchedulerService", _FakeSeriesScheduler
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SeriesManager", _FakeSeriesManager
    )

    cli = DataManagerCLI()

    cli.do_schedule("add-series CPIAUCSL --interval 720 --lookback 30D --frequency m")

    assert cli.scheduler.calls == [
        ("add_series_job", "fred", "CPIAUCSL", "30D", "m", None, 720)
    ]


def test_schedule_add_existing_path_still_works(monkeypatch):
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.DataManager", _FakeDataManager
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SchedulerService", _FakeScheduler
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SeriesManager", _FakeSeriesManager
    )

    cli = DataManagerCLI()
    cli.do_schedule("add DUKASCOPY EURUSD M1 --interval 60")

    assert cli.scheduler.server is cli.server


def test_resample_command_delegates_per_asset_and_timeframe(monkeypatch):
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.DataManager", _FakeDataManager
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SchedulerService", _FakeScheduler
    )
    monkeypatch.setattr(
        "trademachine.datamanager_cli.cli.SeriesManager", _FakeSeriesManager
    )

    cli = DataManagerCLI()
    cli.do_resample("DUKASCOPY EURUSD,GBPUSD M5,H1")

    assert cli.server.calls == [
        ("resample_data", "DUKASCOPY", "EURUSD", "M5"),
        ("resample_data", "DUKASCOPY", "EURUSD", "H1"),
        ("resample_data", "DUKASCOPY", "GBPUSD", "M5"),
        ("resample_data", "DUKASCOPY", "GBPUSD", "H1"),
    ]
