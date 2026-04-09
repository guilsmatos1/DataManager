from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from trademachine.datamanager.services import scheduler as scheduler_module
from trademachine.datamanager.services.scheduler import SchedulerService


class _FakeJob:
    def __init__(self, *, func, args, job_id, name, trigger, next_run_time):
        self.func = func
        self.args = args
        self.id = job_id
        self.name = name
        self.trigger = trigger
        self.next_run_time = next_run_time


class _FakeBackgroundScheduler:
    def __init__(self, jobstores=None, daemon=None):
        self.jobstores = jobstores
        self.daemon = daemon
        self.running = False
        self.jobs: dict[str, _FakeJob] = {}
        self.removed: list[str] = []

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.last_wait = wait
        self.running = False

    def add_job(self, func, trigger, args, id, name, replace_existing):
        job = _FakeJob(
            func=func,
            args=tuple(args),
            job_id=id,
            name=name,
            trigger=trigger,
            next_run_time=datetime(2024, 1, 1, 12, 0, 0),
        )
        self.last_replace_existing = replace_existing
        self.jobs[id] = job
        return job

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.removed.append(job_id)
        del self.jobs[job_id]


class _FakeSQLAlchemyJobStore:
    def __init__(self, engine=None, tablename=None):
        self.engine = engine
        self.tablename = tablename


class _Trigger:
    def __init__(self, label):
        self.label = label

    def __str__(self):
        return self.label


def _install_scheduler_fakes(monkeypatch):
    monkeypatch.setattr(
        scheduler_module, "BackgroundScheduler", _FakeBackgroundScheduler
    )
    monkeypatch.setattr(scheduler_module, "SQLAlchemyJobStore", _FakeSQLAlchemyJobStore)
    monkeypatch.setattr(
        scheduler_module,
        "CronTrigger",
        SimpleNamespace(from_crontab=lambda cron: _Trigger(f"cron:{cron}")),
    )
    monkeypatch.setattr(
        scheduler_module,
        "IntervalTrigger",
        lambda minutes: _Trigger(f"interval:{minutes}"),
    )


def test_add_job_keeps_ohlcv_contract(monkeypatch):
    _install_scheduler_fakes(monkeypatch)
    monkeypatch.setattr(scheduler_module.uuid, "uuid4", lambda: "job-1")

    service = SchedulerService(manager=MagicMock())
    job = service.add_job("dukascopy", "EURUSD", "M1", interval_minutes=60)

    assert job["timeframe"] == "M1"
    assert job["asset"] == "EURUSD"
    assert job["trigger"] == "every 60min"
    assert service._scheduler.get_jobs()[0].func is scheduler_module.execute_update_job


def test_add_series_job_uses_series_contract(monkeypatch):
    _install_scheduler_fakes(monkeypatch)
    monkeypatch.setattr(scheduler_module.uuid, "uuid4", lambda: "series-job-1")

    service = SchedulerService(manager=MagicMock())
    job = service.add_series_job(
        "fred",
        "CPIAUCSL",
        lookback_period="30D",
        frequency="m",
        cron="0 6 * * 1",
    )

    assert job["timeframe"] == "SERIES"
    assert job["asset"] == "CPIAUCSL"
    assert job["lookback_period"] == "30D"
    assert job["frequency"] == "m"
    assert (
        service._scheduler.get_jobs()[0].func
        is scheduler_module.execute_update_series_job
    )


def test_list_jobs_represents_series_jobs_backward_compatibly(monkeypatch):
    _install_scheduler_fakes(monkeypatch)
    service = SchedulerService(manager=MagicMock())
    service._scheduler.jobs = {
        "ohlcv": _FakeJob(
            func=scheduler_module.execute_update_job,
            args=("dukascopy", "EURUSD", "H1"),
            job_id="ohlcv",
            name="dukascopy/EURUSD/H1",
            trigger=_Trigger("interval:60"),
            next_run_time=datetime(2024, 1, 1, 12, 0, 0),
        ),
        "fred": _FakeJob(
            func=scheduler_module.execute_update_series_job,
            args=("fred", "CPIAUCSL", "30D", "m"),
            job_id="fred",
            name="fred/CPIAUCSL/SERIES",
            trigger=_Trigger("cron:0 6 * * 1"),
            next_run_time=datetime(2024, 1, 1, 12, 0, 0),
        ),
    }

    jobs = service.list_jobs()

    assert jobs[0]["timeframe"] == "H1"
    assert jobs[1]["timeframe"] == "SERIES"
    assert jobs[1]["asset"] == "CPIAUCSL"
    assert jobs[1]["lookback_period"] == "30D"
    assert jobs[1]["frequency"] == "m"


def test_remove_job_delegates(monkeypatch):
    _install_scheduler_fakes(monkeypatch)
    service = SchedulerService(manager=MagicMock())
    service._scheduler.jobs = {
        "abc": _FakeJob(
            func=scheduler_module.execute_update_job,
            args=("binance", "BTCUSD", "M1"),
            job_id="abc",
            name="binance/BTCUSD/M1",
            trigger=_Trigger("interval:60"),
            next_run_time=datetime(2024, 1, 1, 12, 0, 0),
        )
    }

    assert service.remove_job("abc") is True
    assert service.remove_job("missing") is False
