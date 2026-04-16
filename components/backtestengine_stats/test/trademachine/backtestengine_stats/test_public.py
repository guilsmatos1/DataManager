import numpy as np
from trademachine.backtestengine_broker.public import MetaTrader5, TradeDeal
from trademachine.backtestengine_stats.public import BacktestStats


def test_backtest_stats_computes_summary_metrics():
    deals = [
        TradeDeal(
            ticket=1,
            order=1,
            time=1,
            time_msc=1000,
            type=MetaTrader5.DEAL_TYPE_BALANCE,
            entry=MetaTrader5.DEAL_ENTRY_IN,
            magic=0,
            position_id=0,
            reason=0,
            volume=0.0,
            price=0.0,
            commission=0.0,
            swap=0.0,
            profit=0.0,
            fee=0.0,
            symbol="",
            comment="deposit",
            balance=1000.0,
        ),
        TradeDeal(
            ticket=2,
            order=1,
            time=2,
            time_msc=2000,
            type=MetaTrader5.DEAL_TYPE_BUY,
            entry=MetaTrader5.DEAL_ENTRY_OUT,
            magic=1,
            position_id=10,
            reason=0,
            volume=0.1,
            price=1.1010,
            commission=0.0,
            swap=0.0,
            profit=50.0,
            fee=0.0,
            symbol="EURUSD",
            comment="tp",
            balance=1050.0,
        ),
        TradeDeal(
            ticket=3,
            order=2,
            time=3,
            time_msc=3000,
            type=MetaTrader5.DEAL_TYPE_SELL,
            entry=MetaTrader5.DEAL_ENTRY_OUT,
            magic=1,
            position_id=11,
            reason=0,
            volume=0.1,
            price=1.1000,
            commission=0.0,
            swap=0.0,
            profit=-20.0,
            fee=0.0,
            symbol="EURUSD",
            comment="sl",
            balance=1030.0,
        ),
    ]

    stats = BacktestStats(
        deals=deals,
        initial_deposit=1000.0,
        balance_curve=np.array([1000.0, 1050.0, 1030.0]),
        equity_curve=np.array([1000.0, 1050.0, 1030.0]),
        margin_level_curve=np.array([np.inf, 250.0, np.inf]),
        ticks=20,
        symbols=1,
    )

    assert stats.total_trades == 2
    assert stats.net_profit == 30.0
    assert round(stats.win_rate, 2) == 50.0
    assert stats.max_drawdown_money == 20.0
