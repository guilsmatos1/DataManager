"""
Service-layer tests for bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/routes.py

Uses FastAPI's TestClient with get_db overridden to an in-memory SQLite session.
Metric-heavy endpoints (which call calculate_metrics internally) are tested with
the mock patches so PostgreSQL is never required.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from trademachine.trading_monitor_dashboard.app import create_app
from trademachine.tradingmonitor.analysis.benchmarks import _remote_database_exists
from trademachine.tradingmonitor.config import settings
from trademachine.tradingmonitor.db.database import get_db
from trademachine.tradingmonitor.db.models import (
    Account,
    Backtest,
    BacktestDeal,
    Base,
    Benchmark,
    BenchmarkPrice,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Setting,
    Strategy,
    StrategyRuntimeSnapshot,
)

# ── Shared SQLite engine (module-scoped for performance) ──────────────────────


@pytest.fixture(scope="module")
def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if (
                column.primary_key
                and getattr(column, "autoincrement", False) is True
                and len(table.primary_key.columns) > 1
            ):
                column.autoincrement = False
                column.info["was_autoincrement"] = True

    Base.metadata.create_all(bind=engine)

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.info.get("was_autoincrement"):
                column.autoincrement = True
                del column.info["was_autoincrement"]

    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def session(_engine):
    """Transactional SQLite session, rolled back after each test."""
    connection = _engine.connect()
    transaction = connection.begin()
    _Session = sessionmaker(bind=connection)
    s = _Session()
    yield s
    s.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(session):
    """
    FastAPI TestClient with get_db overridden to use the per-test SQLite session.
    Ingestion thread is disabled (with_ingestion=False).
    """
    app = create_app(with_ingestion=False)
    app.dependency_overrides[get_db] = lambda: session
    # Without the 'with' context manager, the app lifespan (broadcaster)
    # is NOT triggered, avoiding potential deadlocks in tests.
    return TestClient(
        app, raise_server_exceptions=True, headers={"X-API-Key": settings.api_key}
    )


# ── GET /api/accounts ─────────────────────────────────────────────────────────


class TestListAccounts:
    def test_returns_empty_list_when_no_accounts(self, client):
        response = client.get("/api/accounts")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_seeded_accounts(self, client, session):
        # Arrange
        session.add(Account(id="111", name="Alpha Fund", broker="IG"))
        session.add(Account(id="222", name="Beta Fund", broker="CMC"))
        session.flush()
        # Act
        response = client.get("/api/accounts")
        # Assert
        assert response.status_code == 200
        ids = {a["id"] for a in response.json()}
        assert {"111", "222"} == ids

    def test_account_response_includes_expected_fields(self, client, session):
        session.add(Account(id="333", name="Test", broker="XPTO", balance=5000.0))
        session.flush()
        data = client.get("/api/accounts").json()
        acc = next(a for a in data if a["id"] == "333")
        assert acc["name"] == "Test"
        assert acc["broker"] == "XPTO"


# ── DELETE /api/accounts/{id} ─────────────────────────────────────────────────


class TestDeleteAccount:
    def test_delete_existing_account_returns_204(self, client, session):
        session.add(Account(id="del1", name="ToDelete", broker="B"))
        session.flush()
        response = client.delete("/api/accounts/del1")
        assert response.status_code == 204

    def test_delete_missing_account_returns_404(self, client):
        response = client.delete("/api/accounts/does_not_exist")
        assert response.status_code == 404

    def test_deleted_account_no_longer_appears_in_list(self, client, session):
        session.add(Account(id="del2", name="Gone", broker="B"))
        session.flush()
        client.delete("/api/accounts/del2")
        response = client.get("/api/accounts")
        ids = [a["id"] for a in response.json()]
        assert "del2" not in ids


# ── GET /api/strategies ───────────────────────────────────────────────────────


class TestListStrategies:
    def test_returns_empty_list_when_no_strategies(self, client):
        response = client.get("/api/strategies")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_seeded_strategies(self, client, session):
        session.add(Strategy(id="10", name="Scalper", symbol="EURUSD"))
        session.add(Strategy(id="20", name="Swing", symbol="GBPUSD"))
        session.flush()
        response = client.get("/api/strategies")
        assert response.status_code == 200
        ids = {s["id"] for s in response.json()}
        assert {"10", "20"} == ids

    def test_net_profit_is_none_for_strategy_with_no_deals(self, client, session):
        session.add(Strategy(id="30", name="NoDeals"))
        session.flush()
        data = client.get("/api/strategies").json()
        s = next(x for x in data if x["id"] == "30")
        assert s["net_profit"] is None

    def test_net_profit_computed_from_deals(self, client, session):
        # Arrange — strategy with 2 BUY deals; net = profit + commission + swap
        session.add(Strategy(id="40", name="WithDeals"))
        session.flush()
        session.add(
            Deal(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                ticket=101,
                strategy_id="40",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.08,
                profit=200.0,
                commission=-4.0,
                swap=0.0,
            )
        )
        session.add(
            Deal(
                timestamp=datetime(2024, 1, 2, tzinfo=UTC),
                ticket=102,
                strategy_id="40",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.09,
                profit=100.0,
                commission=-2.0,
                swap=-1.0,
            )
        )
        session.flush()
        data = client.get("/api/strategies").json()
        s = next(x for x in data if x["id"] == "40")
        # 200-4 + 100-2-1 = 293
        assert s["net_profit"] == pytest.approx(293.0)

    def test_balance_deals_excluded_from_net_profit(self, client, session):
        session.add(Strategy(id="50", name="BalanceDeal"))
        session.flush()
        session.add(
            Deal(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                ticket=200,
                strategy_id="50",
                symbol="DEPOSIT",
                type=DealType.BALANCE,
                volume=0.0,
                price=0.0,
                profit=10000.0,
                commission=0.0,
                swap=0.0,
            )
        )
        session.flush()
        data = client.get("/api/strategies").json()
        s = next(x for x in data if x["id"] == "50")
        # Balance deals must not inflate net_profit
        assert s["net_profit"] is None


# ── GET /api/strategies/{id} ──────────────────────────────────────────────────


class TestGetStrategy:
    def test_existing_strategy_returns_200(self, client, session):
        session.add(Strategy(id="60", name="Fetch Me", symbol="USDJPY"))
        session.flush()
        response = client.get("/api/strategies/60")
        assert response.status_code == 200
        assert response.json()["name"] == "Fetch Me"

    def test_missing_strategy_returns_404(self, client):
        response = client.get("/api/strategies/99999")
        assert response.status_code == 404


# ── DELETE /api/strategies/{id} ───────────────────────────────────────────────


class TestDeleteStrategy:
    def test_delete_existing_strategy_returns_204(self, client, session):
        session.add(Strategy(id="del_s1", name="ToDelete"))
        session.flush()
        response = client.delete("/api/strategies/del_s1")
        assert response.status_code == 204

    def test_delete_missing_strategy_returns_404(self, client):
        response = client.delete("/api/strategies/not_here")
        assert response.status_code == 404

    def test_deleted_strategy_no_longer_appears_in_list(self, client, session):
        session.add(Strategy(id="del_s2", name="Gone"))
        session.flush()
        client.delete("/api/strategies/del_s2")
        data = client.get("/api/strategies").json()
        assert not any(s["id"] == "del_s2" for s in data)


# ── PATCH /api/strategies/{id} ───────────────────────────────────────────────


class TestUpdateStrategy:
    def test_update_name_returns_updated_value(self, client, session):
        session.add(Strategy(id="upd1", name="Old Name"))
        session.flush()
        response = client.patch("/api/strategies/upd1", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_update_initial_balance(self, client, session):
        session.add(Strategy(id="upd_ib", name="S", initial_balance=1000.0))
        session.flush()
        response = client.patch(
            "/api/strategies/upd_ib",
            json={"initial_balance": 2500.0},
        )
        assert response.status_code == 200
        assert response.json()["initial_balance"] == 2500.0

    def test_update_live_flag(self, client, session):
        session.add(Strategy(id="upd2", name="S", live=False))
        session.flush()
        response = client.patch("/api/strategies/upd2", json={"live": True})
        assert response.status_code == 200
        assert response.json()["live"] is True

    def test_update_missing_strategy_returns_404(self, client):
        response = client.patch("/api/strategies/no_such", json={"name": "X"})
        assert response.status_code == 404


# ── GET /api/portfolios ───────────────────────────────────────────────────────


class TestListPortfolios:
    def test_returns_empty_list_initially(self, client):
        response = client.get("/api/portfolios")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_seeded_portfolio(self, client, session):
        session.add(Portfolio(name="Growth", live=False, real_account=False))
        session.flush()
        data = client.get("/api/portfolios").json()
        assert len(data) == 1
        assert data[0]["name"] == "Growth"

    def test_portfolio_strategy_ids_list_is_present(self, client, session):
        session.add(Portfolio(name="Alpha"))
        session.flush()
        data = client.get("/api/portfolios").json()
        assert "strategy_ids" in data[0]
        assert isinstance(data[0]["strategy_ids"], list)

    def test_portfolios_return_backtest_demo_and_real_net_profit_columns(
        self, client, session
    ):
        demo = Strategy(id="sd", name="Demo Strat", real_account=False)
        real = Strategy(id="sr", name="Real Strat", real_account=True)
        portfolio = Portfolio(name="Mixed")
        portfolio.strategies = [demo, real]
        session.add_all([demo, real, portfolio])
        session.flush()

        session.add_all(
            [
                Deal(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                    ticket=1,
                    strategy_id="sd",
                    symbol="EURUSD",
                    type=DealType.BUY,
                    volume=0.1,
                    price=1.1,
                    profit=12.0,
                    commission=-1.0,
                    swap=0.0,
                ),
                Deal(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                    ticket=2,
                    strategy_id="sr",
                    symbol="EURUSD",
                    type=DealType.BUY,
                    volume=0.1,
                    price=1.1,
                    profit=30.0,
                    commission=0.0,
                    swap=0.0,
                ),
            ]
        )
        bt1 = Backtest(
            strategy_id="sd",
            client_run_id=1001,
            status="complete",
            initial_balance=100.0,
        )
        bt2 = Backtest(
            strategy_id="sr",
            client_run_id=1002,
            status="complete",
            initial_balance=100.0,
        )
        session.add_all([bt1, bt2])
        session.flush()

        session.add_all(
            [
                BacktestDeal(
                    backtest_id=bt1.id,
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                    ticket=101,
                    symbol="EURUSD",
                    type=DealType.BUY,
                    volume=0.1,
                    price=1.1,
                    profit=10.0,
                    commission=-1.0,
                    swap=0.0,
                ),
                BacktestDeal(
                    backtest_id=bt2.id,
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                    ticket=102,
                    symbol="EURUSD",
                    type=DealType.BUY,
                    volume=0.1,
                    price=1.1,
                    profit=6.0,
                    commission=0.0,
                    swap=0.0,
                ),
            ]
        )
        session.flush()

        data = client.get("/api/portfolios").json()
        row = next(p for p in data if p["name"] == "Mixed")
        assert row["demo_net_profit"] == pytest.approx(11.0)
        assert row["real_net_profit"] == pytest.approx(30.0)
        assert row["backtest_net_profit"] == pytest.approx(15.0)


# ── GET /api/summary ──────────────────────────────────────────────────────────


class TestSummary:
    def test_summary_counts_are_zero_on_empty_db(self, client):
        response = client.get("/api/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["strategies_count"] == 0
        assert body["portfolios_count"] == 0
        assert body["accounts_count"] == 0

    def test_summary_counts_reflect_seeded_data(self, client, session):
        session.add(Strategy(id="s1", name="A", symbol="EU"))
        session.add(Strategy(id="s2", name="B", symbol="GB"))
        session.add(Account(id="a1", name="Acc", broker="B"))
        session.add(Portfolio(name="P"))
        session.flush()
        body = client.get("/api/summary").json()
        assert body["strategies_count"] == 2
        assert body["accounts_count"] == 1
        assert body["portfolios_count"] == 1

    def test_summary_by_symbol_groups_correctly(self, client, session):
        session.add(Strategy(id="x1", symbol="EURUSD"))
        session.add(Strategy(id="x2", symbol="EURUSD"))
        session.add(Strategy(id="x3", symbol="GBPUSD"))
        session.flush()
        body = client.get("/api/summary").json()
        assert body["by_symbol"]["EURUSD"] == 2
        assert body["by_symbol"]["GBPUSD"] == 1


class TestRealOverview:
    def test_limits_equity_points_per_strategy(self, client, session):
        session.add(
            Strategy(
                id="s1", name="Real Strat", real_account=True, initial_balance=1000
            )
        )
        session.flush()

        for i in range(150):
            session.add(
                EquityCurve(
                    timestamp=datetime(2024, 1, 1, i // 60, i % 60, 0, tzinfo=UTC),
                    strategy_id="s1",
                    balance=1000.0,
                    equity=1000.0 + i,
                )
            )
        session.flush()

        response = client.get("/api/real?max_points_per_strategy=100")
        assert response.status_code == 200
        data = response.json()
        assert len(data["strategies"]) == 1
        assert len(data["strategies"][0]["equity_curve"]) == 100

    def test_returns_intraday_pnl_and_latest_update(self, client, session):
        session.add(
            Strategy(
                id="s1", name="Real Strat", real_account=True, initial_balance=1000
            )
        )
        session.flush()

        session.add(
            EquityCurve(
                timestamp=datetime(2024, 1, 1, 15, 30, tzinfo=UTC),
                strategy_id="s1",
                balance=1000.0,
                equity=1025.0,
            )
        )
        session.add(
            Deal(
                timestamp=datetime(2026, 3, 29, 13, 0, tzinfo=UTC),
                ticket=1001,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.10,
                profit=25.0,
                commission=-1.5,
                swap=0.0,
            )
        )
        session.add(
            Deal(
                timestamp=datetime(2026, 3, 28, 18, 0, tzinfo=UTC),
                ticket=1002,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.09,
                profit=40.0,
                commission=-1.0,
                swap=0.0,
            )
        )
        session.flush()

        response = client.get("/api/real")
        assert response.status_code == 200

        body = response.json()
        assert body["totals"]["day_pnl"] == pytest.approx(23.5)
        assert body["totals"]["open_trades_count"] is None
        assert body["totals"]["pending_orders_count"] is None
        assert body["totals"]["counts_available"] is False
        assert body["strategies"][0]["day_pnl"] == pytest.approx(23.5)
        assert body["strategies"][0]["last_update"] == "2024-01-01T15:30:00"

    def test_returns_runtime_counts_when_snapshots_exist(self, client, session):
        session.add(Strategy(id="s1", name="Real 1", real_account=True))
        session.add(Strategy(id="s2", name="Real 2", real_account=True))
        session.add(
            StrategyRuntimeSnapshot(
                strategy_id="s1",
                timestamp=datetime(2026, 3, 29, 10, 0, tzinfo=UTC),
                open_profit=12.5,
                open_trades_count=2,
                pending_orders_count=1,
            )
        )
        session.add(
            StrategyRuntimeSnapshot(
                strategy_id="s2",
                timestamp=datetime(2026, 3, 29, 10, 5, tzinfo=UTC),
                open_profit=-7.25,
                open_trades_count=3,
                pending_orders_count=4,
            )
        )
        session.flush()

        response = client.get("/api/real")
        assert response.status_code == 200

        body = response.json()
        assert body["totals"]["open_trades_count"] == 5
        assert body["totals"]["pending_orders_count"] == 5
        assert body["totals"]["counts_available"] is True
        assert body["totals"]["floating_pnl"] == pytest.approx(5.25)

        strategy_one = next(s for s in body["strategies"] if s["id"] == "s1")
        assert strategy_one["open_trades_count"] == 2
        assert strategy_one["pending_orders_count"] == 1
        assert strategy_one["floating_pnl"] == pytest.approx(12.5)

    def test_can_switch_real_page_to_demo_mode(self, client, session):
        session.add(Strategy(id="real_1", name="Real 1", real_account=True))
        session.add(Strategy(id="demo_1", name="Demo 1", real_account=False))
        session.add(Setting(key="real_page_mode", value="demo"))
        session.flush()

        response = client.get("/api/real")
        assert response.status_code == 200

        body = response.json()
        assert body["mode"] == "demo"
        strategy_ids = {s["id"] for s in body["strategies"]}
        assert strategy_ids == {"demo_1"}

    def test_real_page_demo_mode_prefers_account_type_over_strategy_flag(
        self, client, session
    ):
        session.add(Account(id="acc_demo", name="Demo Account", account_type="Demo"))
        session.add(Account(id="acc_real", name="Real Account", account_type="Real"))
        session.add(
            Strategy(
                id="flagged_real_but_demo_account",
                name="Mismatch Demo",
                real_account=True,
                account_id="acc_demo",
            )
        )
        session.add(
            Strategy(
                id="flagged_demo_but_real_account",
                name="Mismatch Real",
                real_account=False,
                account_id="acc_real",
            )
        )
        session.add(Setting(key="real_page_mode", value="demo"))
        session.flush()

        response = client.get("/api/real")
        assert response.status_code == 200

        body = response.json()
        strategy_ids = {s["id"] for s in body["strategies"]}
        assert strategy_ids == {"flagged_real_but_demo_account"}

    def test_real_recent_deals_follow_current_real_page_mode(self, client, session):
        session.add(Account(id="acc_demo2", name="Demo Account", account_type="Demo"))
        session.add(Account(id="acc_real2", name="Real Account", account_type="Real"))
        session.add(
            Strategy(
                id="demo_recent",
                name="Demo Recent",
                real_account=False,
                account_id="acc_demo2",
            )
        )
        session.add(
            Strategy(
                id="real_recent",
                name="Real Recent",
                real_account=True,
                account_id="acc_real2",
            )
        )
        session.add(
            Deal(
                timestamp=datetime(2026, 3, 29, 13, 0, tzinfo=UTC),
                ticket=2001,
                strategy_id="demo_recent",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.10,
                profit=10.0,
                commission=-1.0,
                swap=0.0,
            )
        )
        session.add(
            Deal(
                timestamp=datetime(2026, 3, 29, 14, 0, tzinfo=UTC),
                ticket=2002,
                strategy_id="real_recent",
                symbol="XAUUSD",
                type=DealType.SELL,
                volume=0.1,
                price=2100.0,
                profit=20.0,
                commission=-2.0,
                swap=0.0,
            )
        )
        session.add(Setting(key="real_page_mode", value="demo"))
        session.flush()

        response = client.get("/api/real/recent-deals")
        assert response.status_code == 200

        body = response.json()
        assert len(body) == 1
        assert body[0]["strategy_id"] == "demo_recent"
        assert body[0]["net_profit"] == pytest.approx(9.0)

    def test_real_daily_aggregates_pnl_for_current_mode(self, client, session):
        session.add(Account(id="acc_demo3", name="Demo Account", account_type="Demo"))
        session.add(Account(id="acc_real3", name="Real Account", account_type="Real"))
        session.add(
            Strategy(
                id="demo_daily",
                name="Demo Daily",
                real_account=False,
                account_id="acc_demo3",
            )
        )
        session.add(
            Strategy(
                id="real_daily",
                name="Real Daily",
                real_account=True,
                account_id="acc_real3",
            )
        )
        session.add(
            Deal(
                timestamp=datetime(2026, 3, 29, 13, 0, tzinfo=UTC),
                ticket=3001,
                strategy_id="demo_daily",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.10,
                profit=15.0,
                commission=-1.0,
                swap=0.0,
            )
        )
        session.add(
            Deal(
                timestamp=datetime(2026, 3, 29, 14, 0, tzinfo=UTC),
                ticket=3002,
                strategy_id="real_daily",
                symbol="XAUUSD",
                type=DealType.SELL,
                volume=0.1,
                price=2100.0,
                profit=20.0,
                commission=-2.0,
                swap=0.0,
            )
        )
        session.add(Setting(key="real_page_mode", value="demo"))
        session.flush()

        response = client.get("/api/real/daily")
        assert response.status_code == 200

        body = response.json()
        assert len(body) == 1
        assert body[0]["date"] == "2026-03-29"
        assert body[0]["net_profit"] == pytest.approx(14.0)


class TestTelegramSettings:
    def test_returns_real_page_mode_setting(self, client, session):
        session.add(Setting(key="real_page_mode", value="demo"))
        session.add(Setting(key="telegram_notify_closed_trades", value="true"))
        session.add(Setting(key="telegram_notify_system_errors", value="true"))
        session.flush()

        response = client.get("/api/settings/telegram")
        assert response.status_code == 200
        assert response.json()["real_page_mode"] == "demo"
        assert response.json()["notify_closed_trades"] is True
        assert response.json()["notify_system_errors"] is True

    def test_updates_real_page_mode_setting(self, client, session):
        response = client.post(
            "/api/settings/telegram",
            json={
                "bot_token": "",
                "chat_id": "",
                "notify_closed_trades": True,
                "notify_system_errors": True,
                "var_95_threshold": 0,
                "default_initial_balance": 100000,
                "real_page_mode": "demo",
            },
            headers={"X-API-Key": settings.api_key},
        )
        assert response.status_code == 204

        setting = session.query(Setting).filter(Setting.key == "real_page_mode").first()
        assert setting is not None
        assert setting.value == "demo"
        notify_closed_trades = (
            session.query(Setting)
            .filter(Setting.key == "telegram_notify_closed_trades")
            .first()
        )
        notify_system_errors = (
            session.query(Setting)
            .filter(Setting.key == "telegram_notify_system_errors")
            .first()
        )
        assert notify_closed_trades is not None
        assert notify_closed_trades.value == "True"
        assert notify_system_errors is not None
        assert notify_system_errors.value == "True"


class TestBenchmarks:
    def test_create_and_list_benchmarks(self, client):
        response = client.post(
            "/api/benchmarks",
            json={
                "name": "S&P 500",
                "source": "OPENBB",
                "asset": "SPY",
                "timeframe": "D1",
                "is_default": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["is_default"] is True

        listed = client.get("/api/benchmarks")
        assert listed.status_code == 200
        assert listed.json()[0]["name"] == "S&P 500"

    def test_set_default_benchmark_switches_previous_default(self, client, session):
        b1 = Benchmark(
            name="A", source="OPENBB", asset="SPY", timeframe="D1", is_default=True
        )
        b2 = Benchmark(
            name="B", source="OPENBB", asset="QQQ", timeframe="D1", is_default=False
        )
        session.add_all([b1, b2])
        session.flush()

        response = client.post(f"/api/benchmarks/{b2.id}/set-default")
        assert response.status_code == 200
        assert response.json()["id"] == b2.id
        assert response.json()["is_default"] is True

        session.refresh(b1)
        session.refresh(b2)
        assert b1.is_default is False
        assert b2.is_default is True

    def test_sync_benchmark_returns_service_payload(self, client, session, monkeypatch):
        benchmark = Benchmark(
            name="Nasdaq", source="OPENBB", asset="QQQ", timeframe="D1"
        )
        session.add(benchmark)
        session.flush()

        def fake_sync(db, bm):
            bm.last_error = None
            return {
                "status": "synced",
                "message": "Imported 10 price points.",
                "points": 10,
            }

        monkeypatch.setattr(
            "trademachine.trading_monitor_dashboard.routes.sync_benchmark_from_datamanager",
            fake_sync,
        )

        response = client.post(f"/api/benchmarks/{benchmark.id}/sync")
        assert response.status_code == 200
        assert response.json()["status"] == "synced"
        assert response.json()["benchmark"]["name"] == "Nasdaq"

    def test_duplicate_benchmark_create_returns_409(self, client, session):
        session.add(
            Benchmark(name="S&P 500", source="OPENBB", asset="SPY", timeframe="D1")
        )
        session.flush()

        response = client.post(
            "/api/benchmarks",
            json={
                "name": "S&P 500 Copy",
                "source": "OPENBB",
                "asset": "SPY",
                "timeframe": "D1",
            },
        )
        assert response.status_code == 409

    def test_duplicate_benchmark_update_returns_409(self, client, session):
        first = Benchmark(name="A", source="OPENBB", asset="SPY", timeframe="D1")
        second = Benchmark(name="B", source="OPENBB", asset="QQQ", timeframe="D1")
        session.add_all([first, second])
        session.flush()

        response = client.patch(
            f"/api/benchmarks/{second.id}",
            json={"asset": "SPY"},
        )
        assert response.status_code == 409

    def test_sync_accepts_remote_m1_for_d1_benchmark(self, session, monkeypatch):
        benchmark = Benchmark(
            name="S&P 500", source="OPENBB", asset="SPY", timeframe="D1"
        )
        session.add(benchmark)
        session.flush()

        monkeypatch.setattr(
            "trademachine.tradingmonitor.analysis.benchmarks.list_remote_databases",
            lambda: [{"source": "OPENBB", "asset": "SPY", "timeframe": "M1"}],
        )

        assert _remote_database_exists(benchmark) is True


class TestAdvancedAnalysisBenchmarks:
    def test_returns_normalized_benchmark_curve_for_comparison(
        self, client, session, monkeypatch
    ):
        import pandas as pd

        session.add(Strategy(id="cmp1", name="Compare", real_account=True))
        session.add(
            Deal(
                timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                ticket=1,
                strategy_id="cmp1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=50.0,
                commission=0.0,
                swap=0.0,
            )
        )
        session.add_all(
            [
                EquityCurve(
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    strategy_id="cmp1",
                    balance=1000.0,
                    equity=1000.0,
                ),
                EquityCurve(
                    timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                    strategy_id="cmp1",
                    balance=1050.0,
                    equity=1050.0,
                ),
            ]
        )
        benchmark = Benchmark(
            name="S&P 500",
            source="OPENBB",
            asset="SPY",
            timeframe="D1",
            is_default=True,
        )
        session.add(benchmark)
        session.flush()
        session.add_all(
            [
                BenchmarkPrice(
                    benchmark_id=benchmark.id,
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    close=200.0,
                ),
                BenchmarkPrice(
                    benchmark_id=benchmark.id,
                    timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                    close=220.0,
                ),
            ]
        )
        session.flush()

        deals_df = pd.DataFrame(
            [
                {
                    "timestamp": datetime(2026, 1, 2, tzinfo=UTC),
                    "profit": 50.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "type": "BUY",
                }
            ]
        ).set_index("timestamp")
        equity_df = pd.DataFrame(
            [
                {"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "equity": 1000.0},
                {"timestamp": datetime(2026, 1, 2, tzinfo=UTC), "equity": 1050.0},
            ]
        ).set_index("timestamp")

        monkeypatch.setattr(
            "trademachine.tradingmonitor.metrics.repository.get_strategy_deals",
            lambda *args, **kwargs: deals_df,
        )
        monkeypatch.setattr(
            "trademachine.tradingmonitor.metrics.repository.get_strategy_equity_curve",
            lambda *args, **kwargs: equity_df,
        )

        response = client.get(
            "/api/advanced-analysis",
            params={
                "strategy_ids": ["cmp1"],
                "history_type": "real",
                "initial_balance": 1000,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["benchmark"]["name"] == "S&P 500"
        assert len(body["comparison_curve"]) == 2
        assert body["comparison_curve"][0]["portfolio"] == pytest.approx(1000.0)
        assert body["comparison_curve"][0]["benchmark"] == pytest.approx(1000.0)
        assert body["comparison_curve"][1]["benchmark"] == pytest.approx(1100.0)
        assert body["metrics"]["Benchmark Return (%)"] == pytest.approx(10.0)
