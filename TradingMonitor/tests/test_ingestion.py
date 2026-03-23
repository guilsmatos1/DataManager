from unittest.mock import MagicMock

from tradingmonitor.db.models import Account, Strategy
from tradingmonitor.ingestion.schemas import AccountSchema, DealSchema
from tradingmonitor.ingestion.tcp_server import process_account, process_deal


def test_process_deal_logic():
    # Mock database session
    db = MagicMock()

    # Mock query for ensure_strategy_exists
    db.query.return_value.filter.return_value.first.return_value = Strategy(id="123")

    # Valid data according to DealSchema
    deal_data = DealSchema(
        time=1704067200,
        ticket=123456,
        magic=123,
        symbol="EURUSD",
        type="buy",
        volume=0.1,
        price=1.10,
        profit=10.0,
        commission=-1.0,
        swap=0.0,
    )

    process_deal(db, deal_data)

    # process_deal now uses db.execute() with pg_insert for on_conflict semantics
    assert db.execute.called
    # We can't easily inspect the SQLAlchemy statement object in a simple mock,
    # but verifying it was called is the first step.


def test_process_account_logic():
    db = MagicMock()

    # Mock query for ensure_account_exists
    db.query.return_value.filter.return_value.first.return_value = Account(id="999")

    acc_data = AccountSchema(
        login=999,
        broker="IC Markets",
        balance=10000.0,
        free_margin=9500.0,
        deposits=10000.0,
        withdrawals=0.0,
    )

    process_account(db, acc_data)

    # Verify account properties were updated
    acc = db.query.return_value.filter.return_value.first.return_value
    assert acc.balance == 10000.0
    assert acc.free_margin == 9500.0
