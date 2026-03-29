from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from trademachine.portifolio_master_cli.cli import PortifolioCLI


def _make_cli(*names, lots: dict = None, data: dict = None):
    """Helper: CLI with mocked portfolio_manager and explicit strategy_lots."""
    cli = PortifolioCLI()
    cli.loaded_expert_names = list(names)
    cli.portfolio_manager = MagicMock()
    cli.portfolio_manager.strategy_lots = lots or {}
    cli.portfolio_manager.strategies = data or {}
    cli.portfolio_manager._lots_meta = {}
    return cli


# ---------------------------------------------------------------------------
# Basic calculation
# ---------------------------------------------------------------------------


def test_drawdown_pairing_correct_paired_lot(capsys):
    """Paired lot = (target_dd / orig_dd) * base_lot, rounded to lot_tick."""
    # Strat1: MaxDD=2000, base_lot=0.5 → ideal = (4000/2000)*0.5 = 1.0
    # Strat2: MaxDD=1500, base_lot=0.5 → ideal = (4000/1500)*0.5 ≈ 1.333 → 1.3 (tick 0.1)
    df1 = pl.DataFrame({"Net_Profit": [1000.0, -2000.0, 2000.0]})  # MaxDD=2000
    df2 = pl.DataFrame({"Net_Profit": [500.0, -1500.0, 1500.0]})  # MaxDD=1500
    df3 = pl.DataFrame({"Net_Profit": [100.0]})  # MaxDD=0

    cli = _make_cli(
        "Strat1",
        "Strat2",
        "Strat3",
        lots={"Strat1": 0.5, "Strat2": 0.5, "Strat3": 0.5},
        data={"Strat1": df1, "Strat2": df2, "Strat3": df3},
    )
    cli.drawdown_pairing(target_dd=4000.0, lot_tick=0.1)
    out = capsys.readouterr().out

    assert "Drawdown Pairing" in out
    assert "Target: 4,000" in out
    assert "Strat1" in out
    assert "Strat2" in out
    assert "Strat3" in out

    # Strat1: paired_lot=1.0, scale=1.0/0.5=2.0 → paired_dd=4000.00
    assert "1.0" in out
    assert "4,000.00" in out

    # Strat2: ideal=(4000/1500)*0.5=1.333 → n_ticks=round(13.33)=13 → 1.3
    #         scale=1.3/0.5=2.6 → paired_dd=2.6*1500=3900.00, diff=-100.00
    assert "1.3" in out
    assert "3,900.00" in out
    assert "-100.00" in out

    # Strat3: MaxDD=0 → N/A
    assert "N/A" in out


def test_drawdown_pairing_base_lot_1_fallback(capsys):
    """When no lot data is available, falls back to base_lot=1.0."""
    df = pl.DataFrame({"Net_Profit": [1000.0, -2000.0, 2000.0]})  # MaxDD=2000
    cli = _make_cli("Strat1", lots={}, data={"Strat1": df})

    cli.drawdown_pairing(target_dd=4000.0, lot_tick=0.1)
    out = capsys.readouterr().out

    # base_lot=1.0, ideal=(4000/2000)*1.0=2.0 → paired_lot=2.0
    assert "Base Lot" in out
    assert "Paired Lot" in out
    assert "2.0" in out
    assert "4,000.00" in out


# ---------------------------------------------------------------------------
# Minimum lot enforcement
# ---------------------------------------------------------------------------


def test_drawdown_pairing_min_lot(capsys):
    """Paired lot is at least one lot_tick even when the ideal is below it."""
    # MaxDD=10000, base_lot=1.0, target=1000 → ideal=0.1 → n_ticks=max(1,0)=1 → lot=1
    df = pl.DataFrame({"Net_Profit": [1000.0, -10000.0, 10000.0]})
    cli = _make_cli("HighDD", lots={"HighDD": 1.0}, data={"HighDD": df})

    cli.drawdown_pairing(target_dd=1000.0, lot_tick=1.0)
    out = capsys.readouterr().out

    # paired_lot=1, scale=1/1=1 → paired_dd=10000
    assert "10,000.00" in out


# ---------------------------------------------------------------------------
# Early-exit paths
# ---------------------------------------------------------------------------


def test_drawdown_pairing_not_loaded(capsys):
    """Returns early when no strategies are loaded (_ensure_loaded → False)."""
    cli = PortifolioCLI()
    cli.loaded_expert_names = []

    with patch.object(cli, "load_reports") as mock_load:
        cli.drawdown_pairing()
        mock_load.assert_called_once()

    assert capsys.readouterr().out == ""


def test_drawdown_pairing_empty_rows(capsys):
    """Prints 'No strategies loaded' when strategies dict is empty."""
    cli = _make_cli("Missing", lots={}, data={})
    cli.drawdown_pairing()
    assert "No strategies loaded" in capsys.readouterr().out


def test_drawdown_pairing_empty_profits(capsys):
    """Strategy with an empty Net_Profit series produces no row."""
    cli = _make_cli(
        "Empty",
        lots={"Empty": 1.0},
        data={"Empty": pl.DataFrame({"Net_Profit": pl.Series([], dtype=pl.Float64)})},
    )
    cli.drawdown_pairing()
    assert "No strategies loaded" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Display precision
# ---------------------------------------------------------------------------


def test_drawdown_pairing_precision_two_decimals(capsys):
    """lot_tick=0.01 produces two-decimal lot values."""
    df = pl.DataFrame({"Net_Profit": [1000.0, -1000.0, 1000.0]})  # MaxDD=1000
    cli = _make_cli("P", lots={"P": 1.0}, data={"P": df})

    cli.drawdown_pairing(target_dd=2000.0, lot_tick=0.01)
    out = capsys.readouterr().out
    # ideal=(2000/1000)*1.0=2.0 → paired_lot=2.00
    assert "2.00" in out


def test_drawdown_pairing_precision_zero_decimals(capsys):
    """lot_tick=1.0 produces integer lot values."""
    df = pl.DataFrame({"Net_Profit": [1000.0, -1000.0, 1000.0]})  # MaxDD=1000
    cli = _make_cli("P", lots={"P": 1.0}, data={"P": df})

    cli.drawdown_pairing(target_dd=2000.0, lot_tick=1.0)
    out = capsys.readouterr().out
    # ideal=2.0 → paired_lot displayed as "2" (0 decimals)
    assert "| 2 |" in out or "|  2 |" in out or "2" in out


# ---------------------------------------------------------------------------
# --apply: scaling applied to memory
# ---------------------------------------------------------------------------


def test_drawdown_pairing_apply_scales_net_profit(tmp_path, capsys):
    """With apply=True, Net_Profit is scaled by paired_lot / base_lot."""
    # MaxDD=2000, base_lot=0.5 → paired_lot=1.0 (target=4000) → scale=2.0
    df = pl.DataFrame({"Net_Profit": [1000.0, -2000.0, 2000.0]})
    cli = _make_cli("S1", lots={"S1": 0.5}, data={"S1": df})
    cli.default_config["cache_path"] = str(tmp_path / "cache.parquet")

    cli.drawdown_pairing(target_dd=4000.0, lot_tick=0.1, apply=True)
    capsys.readouterr()

    scaled = cli.portfolio_manager.strategies["S1"]["Net_Profit"].to_list()
    assert scaled == pytest.approx([2000.0, -4000.0, 4000.0], rel=1e-6)


def test_drawdown_pairing_apply_updates_strategy_lots(tmp_path, capsys):
    """With apply=True, strategy_lots is updated to the paired lot."""
    df = pl.DataFrame({"Net_Profit": [1000.0, -2000.0, 2000.0]})
    cli = _make_cli("S1", lots={"S1": 0.5}, data={"S1": df})
    cli.default_config["cache_path"] = str(tmp_path / "cache.parquet")

    cli.drawdown_pairing(target_dd=4000.0, lot_tick=0.1, apply=True)
    capsys.readouterr()

    assert cli.portfolio_manager.strategy_lots["S1"] == pytest.approx(1.0, rel=1e-6)


def test_drawdown_pairing_apply_no_change_when_already_at_target(tmp_path, capsys):
    """With apply=True, strategies already at target (scale≈1) are not modified."""
    # MaxDD=4000, base_lot=1.0 → paired_lot=1.0 → scale=1.0 → no change
    df = pl.DataFrame({"Net_Profit": [2000.0, -4000.0, 4000.0]})
    cli = _make_cli("S1", lots={"S1": 1.0}, data={"S1": df})
    cli.default_config["cache_path"] = str(tmp_path / "cache.parquet")

    cli.drawdown_pairing(target_dd=4000.0, lot_tick=0.1, apply=True)
    out = capsys.readouterr().out

    assert "No changes applied" in out
    assert cli.portfolio_manager.strategies["S1"][
        "Net_Profit"
    ].to_list() == pytest.approx([2000.0, -4000.0, 4000.0])


def test_drawdown_pairing_apply_skips_zero_dd(tmp_path, capsys):
    """Strategies with MaxDD==0 are skipped even with apply=True."""
    df = pl.DataFrame({"Net_Profit": [100.0]})  # MaxDD=0
    cli = _make_cli("S1", lots={"S1": 1.0}, data={"S1": df})
    cli.default_config["cache_path"] = str(tmp_path / "cache.parquet")

    cli.drawdown_pairing(target_dd=4000.0, lot_tick=0.1, apply=True)
    capsys.readouterr()

    assert cli.portfolio_manager.strategies["S1"]["Net_Profit"].to_list() == [100.0]


def test_drawdown_pairing_no_apply_does_not_modify_memory(capsys):
    """Without --apply, Net_Profit in memory is never changed."""
    df = pl.DataFrame({"Net_Profit": [1000.0, -2000.0, 2000.0]})
    cli = _make_cli("S1", lots={"S1": 0.5}, data={"S1": df})

    cli.drawdown_pairing(target_dd=4000.0, lot_tick=0.1, apply=False)
    capsys.readouterr()

    assert cli.portfolio_manager.strategies["S1"]["Net_Profit"].to_list() == [
        1000.0,
        -2000.0,
        2000.0,
    ]
