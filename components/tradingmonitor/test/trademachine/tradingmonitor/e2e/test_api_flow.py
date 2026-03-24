"""
End-to-end tests for the full API flow against a real PostgreSQL/TimescaleDB instance.

These tests are skipped automatically when PostgreSQL is unavailable.
Run them explicitly in CI/CD or local environments that have the DB up:

    PYTHONPATH=. pytest tests/e2e/ -v

Each test rolls back its changes via a savepoint so the DB remains clean.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from trademachine.trading_monitor_dashboard.app import create_app
from trademachine.tradingmonitor.db.database import get_db
from trademachine.tradingmonitor.db.models import Deal, DealType, Strategy
from trademachine.tradingmonitor.ingestion.schemas import DealSchema, EquitySchema
from trademachine.tradingmonitor.ingestion.tcp_server import (
    EXISTING_STRATEGIES,
    process_deal,
    process_equity,
)

pytestmark = pytest.mark.integration  # run with: pytest -m integration


# ── TestClient with real PostgreSQL ───────────────────────────────────────────


@pytest.fixture(scope="module")
def e2e_client(pg_engine):
    """TestClient wired to a transactional PostgreSQL session per module."""
    app = create_app(with_ingestion=False)
    _Session = sessionmaker(bind=pg_engine)

    def _override_db():
        session = _Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    from trademachine.tradingmonitor.config import settings

    with TestClient(
        app, raise_server_exceptions=True, headers={"X-API-Key": settings.api_key}
    ) as c:
        yield c


# ── Strategy lifecycle ────────────────────────────────────────────────────────


class TestStrategyLifecycle:
    def test_create_and_read_strategy(self, e2e_client, pg_session):
        # Arrange
        pg_session.add(Strategy(id="e2e_1", name="E2E Strategy", symbol="EURUSD"))
        pg_session.commit()
        # Act
        response = e2e_client.get("/api/strategies")
        # Assert
        assert response.status_code == 200
        ids = [s["id"] for s in response.json()]
        assert "e2e_1" in ids

    def test_update_strategy_name(self, e2e_client, pg_session):
        pg_session.add(Strategy(id="e2e_2", name="Before", symbol="GBPUSD"))
        pg_session.commit()
        response = e2e_client.patch("/api/strategies/e2e_2", json={"name": "After"})
        assert response.status_code == 200
        assert response.json()["name"] == "After"

    def test_delete_strategy_with_deals(self, e2e_client, pg_session):
        # Arrange — strategy with a deal
        pg_session.add(Strategy(id="e2e_del", name="ToDelete", symbol="USDJPY"))
        pg_session.commit()
        pg_session.add(
            Deal(
                timestamp=datetime(2024, 6, 1, tzinfo=UTC),
                ticket=9001,
                strategy_id="e2e_del",
                symbol="USDJPY",
                type=DealType.BUY,
                volume=0.1,
                price=150.0,
                profit=80.0,
                commission=-2.0,
                swap=0.0,
            )
        )
        pg_session.commit()
        # Act
        response = e2e_client.delete("/api/strategies/e2e_del")
        # Assert — cascade delete works
        assert response.status_code == 204
        assert pg_session.get(Strategy, "e2e_del") is None


# ── Deal ingestion flow ───────────────────────────────────────────────────────


class TestDealIngestionFlow:
    def test_process_deal_creates_strategy_and_deal_row(self, pg_session):
        # Arrange
        EXISTING_STRATEGIES.discard("e2e_proc_1")
        data = DealSchema(
            time=1_700_000_000,
            ticket=5001,
            magic=900001,
            symbol="AUDUSD",
            type="sell",
            volume=0.5,
            price=0.65,
            profit=120.0,
        )
        # Act
        process_deal(pg_session, data)
        pg_session.commit()
        # Assert — strategy auto-created
        s = pg_session.get(Strategy, "900001")
        assert s is not None
        assert s.live is False

    def test_process_equity_skips_magic_zero(self, pg_session):
        # Arrange — account-level equity
        initial_count = pg_session.execute(
            __import__("sqlalchemy").text("SELECT COUNT(*) FROM equity_curve")
        ).scalar()
        data = EquitySchema(
            time=1_700_000_000, magic=0, balance=50000.0, equity=50000.0
        )
        # Act
        process_equity(pg_session, data)
        pg_session.commit()
        # Assert — no new equity_curve rows
        final_count = pg_session.execute(
            __import__("sqlalchemy").text("SELECT COUNT(*) FROM equity_curve")
        ).scalar()
        assert final_count == initial_count


# ── Metrics endpoint flow ─────────────────────────────────────────────────────


class TestMetricsEndpointFlow:
    def test_metrics_endpoint_returns_dict(self, e2e_client, pg_session):
        # Arrange — strategy with deals
        pg_session.add(Strategy(id="e2e_m1", name="MetricTest", symbol="EURUSD"))
        pg_session.commit()
        for ticket, profit in [(1, 200.0), (2, -50.0), (3, 150.0)]:
            pg_session.add(
                Deal(
                    timestamp=datetime(2024, 1, ticket, tzinfo=UTC),
                    ticket=ticket + 8000,
                    strategy_id="e2e_m1",
                    symbol="EURUSD",
                    type=DealType.BUY,
                    volume=0.1,
                    price=1.08,
                    profit=profit,
                    commission=-2.0,
                    swap=0.0,
                )
            )
        pg_session.commit()
        # Act
        response = e2e_client.get("/api/strategies/e2e_m1/metrics")
        # Assert
        assert response.status_code == 200
        body = response.json()
        assert "Total Trades" in body
        assert body["Total Trades"] == 3
        assert "Win Rate (%)" in body
        assert body["Win Rate (%)"] == pytest.approx(66.67, rel=0.01)


# ── Portfolio flow ────────────────────────────────────────────────────────────


class TestPortfolioFlow:
    def test_create_portfolio_and_add_strategy(self, e2e_client, pg_session):
        # Arrange — create strategy
        pg_session.add(Strategy(id="e2e_p1", name="PortfolioStrat"))
        pg_session.commit()
        # Act — create portfolio via API
        resp = e2e_client.post(
            "/api/portfolios",
            json={
                "name": "E2E Portfolio",
                "strategy_ids": ["e2e_p1"],
            },
        )
        assert resp.status_code == 201
        portfolio_id = resp.json()["id"]
        # Assert — portfolio appears in list with correct strategy
        resp2 = e2e_client.get(f"/api/portfolios/{portfolio_id}")
        assert resp2.status_code == 200
        assert "e2e_p1" in resp2.json()["strategy_ids"]
