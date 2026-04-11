from trademachine.portfoliomaster.services.portfolio import PortfolioManager


def test_add_strategy_returns_true(pt_parser):
    """add_strategy returns True for a valid report."""
    name = list(pt_parser.deals_by_expert.keys())[0]
    pm = PortfolioManager()
    success = pm.add_strategy(name, pt_parser.deals_by_expert[name])

    assert success is True
    assert name in pm.strategies


def test_add_strategy_stores_net_profit_column(pt_parser):
    """Stored strategy DataFrame contains Net_Profit column with non-zero values."""
    name = list(pt_parser.deals_by_expert.keys())[0]
    pm = PortfolioManager()
    pm.add_strategy(name, pt_parser.deals_by_expert[name])

    df = pm.strategies[name]
    assert "Net_Profit" in df.columns
    assert len(df) > 0
    assert df["Net_Profit"].sum() != 0.0


def test_strategy_metrics_are_valid(loaded_manager):
    """calculate_strategy_metrics returns valid non-null metrics."""
    for name in loaded_manager.strategies:
        metrics = loaded_manager.calculate_strategy_metrics(name)

        assert metrics is not None, f"None metrics for {name}"
        assert "Profit" in metrics
        assert "MaxDD" in metrics
        assert "RetDD" in metrics
        assert "Trades" in metrics
        assert metrics["MaxDD"] >= 0.0
        assert metrics["Trades"] > 0


def test_get_returns_matrix_shape_and_columns(loaded_manager):
    """get_returns_matrix returns a wide DataFrame with one column per strategy."""
    matrix = loaded_manager.get_returns_matrix()

    assert not matrix.is_empty()
    assert "Horário" in matrix.columns

    for name in loaded_manager.strategies:
        assert name in matrix.columns, f"Strategy column missing: {name}"


def test_get_returns_matrix_no_nulls(loaded_manager):
    """Returns matrix has no null values (all timestamps filled with 0.0)."""
    matrix = loaded_manager.get_returns_matrix()

    for name in loaded_manager.strategies:
        assert matrix[name].null_count() == 0, f"Nulls found in column: {name}"


def test_get_all_trades_long_format(loaded_manager):
    """get_all_trades_long returns all trades with Strategy and Net_Profit columns."""
    long_df = loaded_manager.get_all_trades_long()

    assert not long_df.is_empty()
    assert "Strategy" in long_df.columns
    assert "Net_Profit" in long_df.columns
    assert "Horário" in long_df.columns

    expected_strategies = set(loaded_manager.strategies.keys())
    actual_strategies = set(long_df["Strategy"].unique().to_list())
    assert actual_strategies == expected_strategies


def test_empty_manager_returns_empty_matrix():
    """An empty PortfolioManager returns an empty matrix."""
    pm = PortfolioManager()
    matrix = pm.get_returns_matrix()
    assert matrix.is_empty()
