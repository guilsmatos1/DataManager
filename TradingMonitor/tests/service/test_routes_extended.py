from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from tradingmonitor.config import settings
from tradingmonitor.dashboard.app import create_app
from tradingmonitor.db.database import get_db
from tradingmonitor.db.models import Deal, DealType, Portfolio, Strategy


@pytest.fixture()
def client(db_session):
    app = create_app(with_ingestion=False)
    app.dependency_overrides[get_db] = lambda: db_session
    # Don't use with statement to avoid lifespan issues in tests
    return TestClient(app, raise_server_exceptions=True, headers={"X-API-Key": settings.api_key})


class TestRoutesExtended:
    def test_get_strategy_metrics(self, client, db_session):
        db_session.add(Strategy(id="s1", name="Test Strat"))
        db_session.flush()

        with patch("tradingmonitor.metrics.calculator.calculate_metrics") as mock_calc:
            mock_calc.return_value = {"Total Trades": 10, "Net Profit": 500.0}
            response = client.get("/api/strategies/s1/metrics")
            assert response.status_code == 200
            assert response.json()["Total Trades"] == 10

    def test_get_strategy_trade_stats(self, client, db_session):
        db_session.add(Strategy(id="s1", name="Test Strat"))
        db_session.flush()

        # We don't need to mock _q because we can just let it run on the db_session
        # but we need to avoid the 'isodow' error.
        # So we patch 'extract' to return something SQLite likes.
        with patch("tradingmonitor.dashboard.routes.extract") as mock_extract:
            mock_extract.side_effect = lambda field, col: (
                func.strftime("%H", col) if field == "hour" else func.strftime("%w", col)
            )
            response = client.get("/api/strategies/s1/trade-stats")
            assert response.status_code == 200
            assert "by_hour" in response.json()
            assert "by_dow" in response.json()

    def test_get_strategy_deals_paginated(self, client, db_session):
        db_session.add(Strategy(id="s1", name="Test Strat"))
        for i in range(10):
            db_session.add(
                Deal(
                    timestamp=datetime(2024, 1, 1, i, 0, 0, tzinfo=UTC),
                    ticket=i,
                    strategy_id="s1",
                    symbol="EURUSD",
                    type=DealType.BUY,
                    volume=0.1,
                    price=1.0,
                    profit=10.0,
                    commission=0.0,
                    swap=0.0,
                )
            )
        db_session.flush()

        response = client.get("/api/strategies/s1/deals?page=1&page_size=5")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10
        assert len(data["items"]) == 5

    def test_create_portfolio_with_strategies(self, client, db_session):
        db_session.add(Strategy(id="s1", name="S1"))
        db_session.add(Strategy(id="s2", name="S2"))
        db_session.flush()

        payload = {"name": "New Portfolio", "strategy_ids": ["s1", "s2"]}
        response = client.post("/api/portfolios", json=payload)
        assert response.status_code == 201
        assert response.json()["name"] == "New Portfolio"
        assert len(response.json()["strategy_ids"]) == 2

    def test_update_portfolio_strategies(self, client, db_session):
        p = Portfolio(name="Old")
        s1 = Strategy(id="s1", name="S1")
        db_session.add(p)
        db_session.add(s1)
        db_session.flush()

        response = client.patch(f"/api/portfolios/{p.id}", json={"strategy_ids": ["s1"]})
        assert response.status_code == 200
        assert "s1" in response.json()["strategy_ids"]

    def test_get_portfolio_metrics(self, client, db_session):
        p = Portfolio(name="P1")
        s1 = Strategy(id="s1", name="S1")
        p.strategies.append(s1)
        db_session.add(p)
        db_session.flush()

        with patch("tradingmonitor.metrics.calculator.calculate_portfolio_metrics") as mock_calc:
            mock_calc.return_value = {"Net Profit": 1000.0}
            response = client.get(f"/api/portfolios/{p.id}/metrics")
            assert response.status_code == 200
            assert response.json()["Net Profit"] == 1000.0

    def test_get_portfolio_correlation(self, client, db_session):
        p = Portfolio(name="P1")
        s1 = Strategy(id="s1", name="S1")
        s2 = Strategy(id="s2", name="S2")
        p.strategies.extend([s1, s2])
        db_session.add(p)
        db_session.flush()

        with patch("tradingmonitor.metrics.calculator.calculate_correlation_matrix") as mock_calc:
            mock_calc.return_value = {"matrix": [[1, 0.5], [0.5, 1]]}
            response = client.get(f"/api/portfolios/{p.id}/correlation")
            assert response.status_code == 200
            assert "matrix" in response.json()

    def test_export_strategy_deals(self, client, db_session):
        db_session.add(Strategy(id="s1", name="S1"))
        db_session.add(
            Deal(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                ticket=1,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.0,
                profit=10.0,
                commission=0.0,
                swap=0.0,
            )
        )
        db_session.flush()

        response = client.get("/api/strategies/s1/deals/export")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "ticket,strategy_id" in response.text
