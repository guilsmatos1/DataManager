"""
Service-layer tests for src/dashboard/routes.py

Uses FastAPI's TestClient with get_db overridden to an in-memory SQLite session.
Metric-heavy endpoints (which call calculate_metrics internally) are tested with
the mock patches so PostgreSQL is never required.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tradingmonitor.config import settings
from tradingmonitor.dashboard.app import create_app
from tradingmonitor.db.database import get_db
from tradingmonitor.db.models import Account, Base, Deal, DealType, Portfolio, Strategy

# ── Shared SQLite engine (module-scoped for performance) ──────────────────────


@pytest.fixture(scope="module")
def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
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
    return TestClient(app, raise_server_exceptions=True, headers={"X-API-Key": settings.api_key})


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
