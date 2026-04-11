import polars as pl
import pytest
from trademachine.portfoliomaster.services.pairing import PairingService
from trademachine.portfoliomaster.services.portfolio import PortfolioManager


def _make_manager() -> PortfolioManager:
    manager = PortfolioManager()
    manager.strategies = {
        "A": pl.DataFrame({"Net_Profit": [1000.0, -2000.0, 2000.0]}),
        "B": pl.DataFrame({"Net_Profit": [100.0]}),
    }
    manager.strategy_lots = {"A": 0.5, "B": 0.5}
    return manager


def test_pairing_service_analyze_builds_rows():
    manager = _make_manager()

    rows = PairingService(target_dd=4000.0, lot_tick=0.1).analyze(
        ["A", "B"], manager.strategies, manager.strategy_lots
    )

    assert [row.name for row in rows] == ["A", "B"]
    assert rows[0].base_lot == 0.5
    assert rows[0].paired_lot == pytest.approx(1.0)
    assert rows[0].paired_dd == pytest.approx(4000.0)
    assert rows[1].paired_lot is None


def test_pairing_service_apply_scales_and_sets_meta():
    manager = _make_manager()
    service = PairingService(target_dd=4000.0, lot_tick=0.1)
    rows = service.analyze(["A", "B"], manager.strategies, manager.strategy_lots)

    result = service.apply(manager, rows)

    assert result.analyzed == 2
    assert result.changed == 1
    assert result.unchanged == 1
    assert manager.strategies["A"]["Net_Profit"].to_list() == pytest.approx(
        [2000.0, -4000.0, 4000.0]
    )
    assert manager.strategy_lots["A"] == pytest.approx(1.0)
    assert manager._lots_meta == {"dd_paired": True, "target": 4000.0, "tick": 0.1}


def test_pairing_service_export_report_writes_csv(tmp_path):
    manager = _make_manager()
    service = PairingService(target_dd=4000.0, lot_tick=0.1)
    rows = service.analyze(["A"], manager.strategies, manager.strategy_lots)

    report_path = service.export_report(rows, str(tmp_path / "pairing.csv"))

    report = pl.read_csv(report_path)
    assert report.columns == [
        "name",
        "base_lot",
        "paired_lot",
        "orig_dd",
        "paired_dd",
        "paired_profit",
        "diff",
    ]
    assert report["name"].to_list() == ["A"]


@pytest.mark.parametrize(
    ("lot_tick", "expected"),
    [
        (1.0, 0),
        (0.5, 1),
        (0.25, 2),
        (0.1, 1),
        (0.01, 2),
        (0.125, 3),
    ],
)
def test_pairing_service_decimals_matches_lot_tick_precision(lot_tick, expected):
    service = PairingService(target_dd=4000.0, lot_tick=lot_tick)

    assert service.decimals == expected
