from datetime import UTC, datetime

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.analysis import benchmarks as bm
from trademachine.tradingmonitor_ingestion.ingestion import benchmark_sync as bs
from trademachine.tradingmonitor_storage.db.models import Benchmark, BenchmarkPrice


class _FakeClient:
    def __init__(self, rows=None, data=None):
        self._rows = rows or []
        self._data = data
        self.download_calls = []

    def list_databases(self):
        return self._rows

    def download(self, **kwargs):
        self.download_calls.append(kwargs)
        return {"status": "success"}

    def get_data(self, **kwargs):
        return self._data


def test_list_remote_databases_normalizes_and_sorts(monkeypatch):
    fake = _FakeClient(
        rows=[
            {"source": "openbb", "asset": "qqq", "timeframe": "m1", "rows": 10},
            {"source": "dukascopy", "asset": "spy", "timeframe": "m1", "rows": 20},
        ]
    )
    monkeypatch.setattr(bs, "create_datamanager_client", lambda db=None: fake)

    rows = bm.list_remote_databases()

    assert rows[0]["source"] == "DUKASCOPY"
    assert rows[0]["asset"] == "SPY"
    assert rows[1]["source"] == "OPENBB"
    assert rows[1]["asset"] == "QQQ"


def test_remote_database_exists_ignores_requested_timeframe(monkeypatch, db_session):
    benchmark = Benchmark(name="S&P 500", source="OPENBB", asset="SPY", timeframe="D1")
    db_session.add(benchmark)
    db_session.flush()

    monkeypatch.setattr(
        bs,
        "list_remote_databases",
        lambda db=None: [{"source": "OPENBB", "asset": "SPY", "timeframe": "M1"}],
    )

    assert bs._remote_database_exists(benchmark) is True


def test_benchmark_to_dict_includes_local_stats(db_session):
    benchmark = Benchmark(name="Nasdaq", source="OPENBB", asset="QQQ", timeframe="D1")
    db_session.add(benchmark)
    db_session.flush()
    db_session.add_all(
        [
            BenchmarkPrice(
                benchmark_id=benchmark.id,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                close=100.0,
            ),
            BenchmarkPrice(
                benchmark_id=benchmark.id,
                timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                close=101.0,
            ),
        ]
    )
    db_session.flush()

    payload = bm.benchmark_to_dict(db_session, benchmark)

    assert payload["local_points"] == 2
    assert payload["latest_price_timestamp"].date().isoformat() == "2026-01-02"


def test_extract_close_frame_normalizes_columns_and_timezone():
    df = pd.DataFrame(
        {"Close": [100.0, 101.5]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )

    result = bs._extract_close_frame(df)

    assert list(result.columns) == ["close"]
    assert result.index.tz is not None
    assert result.iloc[1]["close"] == pytest.approx(101.5)


def test_sync_benchmark_from_datamanager_replaces_local_prices(monkeypatch, db_session):
    benchmark = Benchmark(name="S&P 500", source="OPENBB", asset="SPY", timeframe="D1")
    db_session.add(benchmark)
    db_session.flush()
    db_session.add(
        BenchmarkPrice(
            benchmark_id=benchmark.id,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            close=90.0,
        )
    )
    db_session.flush()

    df = pd.DataFrame(
        {"close": [200.0, 220.0]},
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)]
        ),
    )
    fake = _FakeClient(data=df)
    monkeypatch.setattr(
        bs, "_trigger_download_if_needed", lambda benchmark, db=None: True
    )
    monkeypatch.setattr(bs, "create_datamanager_client", lambda db=None: fake)

    result = bs.sync_benchmark_from_datamanager(db_session, benchmark)

    db_session.expire_all()
    prices = (
        db_session.query(BenchmarkPrice)
        .filter(BenchmarkPrice.benchmark_id == benchmark.id)
        .order_by(BenchmarkPrice.timestamp.asc())
        .all()
    )
    assert result["status"] == "synced"
    assert len(prices) == 2
    assert float(prices[0].close) == pytest.approx(200.0)
    assert benchmark.last_error is None


def test_load_benchmark_curve_filters_date_range(db_session):
    benchmark = Benchmark(name="Gold", source="OPENBB", asset="GLD", timeframe="D1")
    db_session.add(benchmark)
    db_session.flush()
    db_session.add_all(
        [
            BenchmarkPrice(
                benchmark_id=benchmark.id,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                close=100.0,
            ),
            BenchmarkPrice(
                benchmark_id=benchmark.id,
                timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                close=101.0,
            ),
            BenchmarkPrice(
                benchmark_id=benchmark.id,
                timestamp=datetime(2026, 1, 3, tzinfo=UTC),
                close=102.0,
            ),
        ]
    )
    db_session.flush()

    df = bm.load_benchmark_curve(
        db_session,
        benchmark.id,
        date_from=datetime(2026, 1, 2, tzinfo=UTC),
        date_to=datetime(2026, 1, 3, tzinfo=UTC),
    )

    assert len(df) == 2
    assert list(df["close"]) == [101.0, 102.0]


def test_create_benchmark_record_normalizes_and_marks_default(db_session):
    payload = bm.create_benchmark_record(
        db_session,
        name=" Nasdaq 100 ",
        source="openbb",
        asset="qqq",
        timeframe="d1",
        description="growth",
        enabled=True,
        is_default=True,
    )

    assert payload["name"] == "Nasdaq 100"
    assert payload["source"] == "OPENBB"
    assert payload["asset"] == "QQQ"
    assert payload["timeframe"] == "D1"
    assert payload["is_default"] is True


def test_update_benchmark_record_rejects_duplicate_identity(db_session):
    db_session.add_all(
        [
            Benchmark(name="A", source="OPENBB", asset="SPY", timeframe="D1"),
            Benchmark(name="B", source="OPENBB", asset="QQQ", timeframe="D1"),
        ]
    )
    db_session.flush()

    duplicate = db_session.query(Benchmark).filter(Benchmark.asset == "QQQ").first()

    with pytest.raises(bm.BenchmarkConflictError):
        bm.update_benchmark_record(
            db_session,
            duplicate.id,
            {"asset": "SPY", "source": "OPENBB", "timeframe": "D1"},
        )


def test_sync_benchmark_record_raises_for_unknown_id(db_session):
    with pytest.raises(bm.BenchmarkNotFoundError):
        bm.sync_benchmark_record(db_session, 999)
