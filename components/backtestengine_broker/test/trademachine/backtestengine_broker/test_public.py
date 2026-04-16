import logging

from trademachine.backtestengine_broker.public import (
    AccountInfo,
    SnapshotExporters,
    SnapshotImporters,
    SymbolInfo,
    evaluate_margin_state,
)


def test_snapshot_round_trip(tmp_path):
    broker_dir = tmp_path / "broker"
    exporter = SnapshotExporters(
        broker_path=str(broker_dir),
        logger=logging.getLogger("test"),
        file_not_exists=False,
    )

    account = AccountInfo(login=123, leverage=200, balance=1000.0, equity=1000.0)
    symbols = (
        SymbolInfo(name="EURUSD", point=0.0001, trade_contract_size=100000.0),
        SymbolInfo(name="USDJPY", point=0.01, trade_contract_size=100000.0),
    )

    assert exporter.account_info(account)
    assert exporter.all_symbol_info(symbols)

    importer = SnapshotImporters(str(broker_dir))
    imported_account = importer.account_info()
    imported_symbols = importer.all_symbol_info()

    assert imported_account is not None
    assert imported_account.login == 123
    assert imported_account.leverage == 200
    assert [item.name for item in imported_symbols] == ["EURUSD", "USDJPY"]


def test_evaluate_margin_state_handles_percent_mode():
    account = AccountInfo(
        balance=1000.0,
        equity=400.0,
        margin=1000.0,
        margin_free=-600.0,
        margin_so_mode=0,
        margin_so_call=50.0,
        margin_so_so=30.0,
    )

    event = evaluate_margin_state(account)
    assert event.state == "MARGIN_CALL"
    assert event.value == 40.0
