from sqlalchemy.orm import sessionmaker
from trademachine.tradingmonitor.db import repository as repo_module
from trademachine.tradingmonitor.db.models import Strategy
from trademachine.tradingmonitor.db.repository import StrategyRepository


def test_strategy_create_or_update_preserves_live_when_omitted(
    sqlite_engine, monkeypatch
):
    session_factory = sessionmaker(bind=sqlite_engine)
    monkeypatch.setattr(repo_module, "SessionLocal", session_factory)

    db = session_factory()
    try:
        db.add(Strategy(id="s-live", name="Original", live=True, real_account=True))
        db.commit()
    finally:
        db.close()

    StrategyRepository().create_or_update("s-live", name="Updated")

    db = session_factory()
    try:
        strategy = db.get(Strategy, "s-live")
        assert strategy is not None
        assert strategy.name == "Updated"
        assert strategy.live is True
        assert strategy.real_account is True
    finally:
        db.close()
