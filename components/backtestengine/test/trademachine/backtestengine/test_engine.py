import json

import polars as pl
from trademachine.backtestengine.public import (
    BacktestEngine,
    MetaTrader5,
    TradeExecutor,
)


def _write_broker_snapshot(base_dir):
    broker_dir = base_dir / "broker"
    broker_dir.mkdir(parents=True)
    (broker_dir / "account_info.json").write_text(
        json.dumps({"account_info": {"login": 1, "balance": 1000.0, "equity": 1000.0}}),
        encoding="utf-8",
    )
    (broker_dir / "symbol_info.json").write_text(
        json.dumps(
            {
                "all_symbols_info": [
                    {
                        "name": "EURUSD",
                        "point": 0.0001,
                        "trade_contract_size": 100000.0,
                        "filling_mode": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return broker_dir


def _write_history(base_dir):
    history_dir = (
        base_dir / "History" / "Bars" / "EURUSD" / "M1" / "year=2024" / "month=1"
    )
    history_dir.mkdir(parents=True)
    bars = pl.DataFrame(
        {
            "time": [1704067200, 1704067260, 1704067320],
            "open": [1.1000, 1.1005, 1.1010],
            "high": [1.1010, 1.1020, 1.1025],
            "low": [1.0995, 1.1000, 1.1005],
            "close": [1.1005, 1.1015, 1.1020],
            "tick_volume": [4, 4, 4],
            "spread": [10, 10, 10],
            "real_volume": [0, 0, 0],
        }
    )
    bars.write_parquet(history_dir / "chunk.parquet")
    return base_dir / "History"


def _config():
    return {
        "bot_name": "unit-test",
        "symbols": ["EURUSD"],
        "timeframe": "H1",
        "start_date": "01.01.2024 00:00",
        "end_date": "01.01.2024 00:03",
        "modelling": "every_tick",
        "deposit": 1000,
        "leverage": "1:100",
    }


def test_engine_runs_offline_trade_cycle(tmp_path):
    broker_dir = _write_broker_snapshot(tmp_path)
    history_dir = _write_history(tmp_path)
    engine = BacktestEngine(
        tester_config=_config(),
        history_dir=str(history_dir),
        broker_data_dir=str(broker_dir),
    )
    trade = TradeExecutor(
        simulator=engine,
        magic_number=42,
        filling_type_symbol="EURUSD",
        deviation_points=20,
    )

    def on_tick():
        tick = engine.symbol_info_tick("EURUSD")
        if tick is None:
            return
        if not engine.positions_get():
            trade.buy(volume=0.1, symbol="EURUSD", price=tick.ask)
            return
        position = engine.positions_get()[0]
        if tick.bid > position.price_open:
            assert engine.position_close(position.ticket, tick.bid)
            engine.stop()

    result = engine.run(on_tick)

    assert result.stats.total_trades == 1
    assert result.stats.net_profit > 0
    assert result.stats.final_balance > 1000.0


def test_strategytester5_compatibility_imports(tmp_path):
    broker_dir = _write_broker_snapshot(tmp_path)
    history_dir = _write_history(tmp_path)

    from strategytester5.tester import MetaTrader5 as compat_mt5
    from strategytester5.tester import StrategyTester
    from strategytester5.trade_classes.Trade import CTrade
    from strategytester5.validators.tester_configs import TesterConfigValidators

    parsed = TesterConfigValidators.parse_tester_configs(_config())
    engine = StrategyTester(
        tester_config=parsed,
        history_dir=str(history_dir),
        broker_data_dir=str(broker_dir),
    )
    trade = CTrade(
        simulator=engine,
        magic_number=7,
        filling_type_symbol="EURUSD",
        deviation_points=10,
    )

    def on_tick():
        tick = engine.symbol_info_tick("EURUSD")
        if tick is None:
            return
        if not engine.positions_get():
            trade.buy(volume=0.1, symbol="EURUSD", price=tick.ask)
        else:
            engine.stop()

    result = engine.OnTick(on_tick)

    assert compat_mt5.ORDER_TYPE_BUY == MetaTrader5.ORDER_TYPE_BUY
    assert result.ticks_processed >= 1
