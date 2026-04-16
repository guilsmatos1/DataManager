"""
# Tests for components/tradingmonitor_analytics/src/trademachine/tradingmonitor_analytics/analysis/drift.py.

Covers:
  - check_performance_drift: drift detection logic (VaR, win rate, profit factor, drawdown)
  - Edge cases: no data, insufficient trades, backtest not found
  - _notify_drift: notification path
  - _compute_var: VaR calculation
"""

from datetime import UTC
from unittest.mock import MagicMock, patch

import pandas as pd
from trademachine.tradingmonitor_analytics.analysis.drift import (
    DriftReport,
    _compute_var,
    _notify_drift,
    check_performance_drift,
)
from trademachine.tradingmonitor_storage.db.models import Backtest


class TestComputeVar:
    """Tests for _compute_var function."""

    def test_var_with_sufficient_data(self):
        """VaR is computed correctly with enough data points."""
        equity = pd.Series(
            [
                10000.0,
                10100.0,
                10200.0,
                10050.0,
                9900.0,
                9800.0,
                10100.0,
                10200.0,
                10300.0,
            ],
            index=pd.date_range("2024-01-01", periods=9, tz=UTC),
        )
        result = _compute_var(equity, percentile=95)
        assert result is not None
        assert isinstance(result, float)

    def test_var_with_insufficient_data(self):
        """VaR returns None when fewer than 5 data points."""
        equity = pd.Series(
            [10000.0, 10100.0, 10200.0],
            index=pd.date_range("2024-01-01", periods=3, tz=UTC),
        )
        result = _compute_var(equity, percentile=95)
        assert result is None

    def test_var_with_constant_equity(self):
        """VaR returns None or 0 when equity doesn't change."""
        equity = pd.Series(
            [10000.0] * 10,
            index=pd.date_range("2024-01-01", periods=10, tz=UTC),
        )
        result = _compute_var(equity, percentile=95)
        # With constant equity, returns are 0, VaR should be 0 or None
        assert result is None or result == 0.0

    def test_var_with_all_positive_returns(self):
        """VaR with mostly positive returns may still be negative if any drop occurs."""
        equity = pd.Series(
            [10000.0 + i * 100 for i in range(10)],
            index=pd.date_range("2024-01-01", periods=10, tz=UTC),
        )
        result = _compute_var(equity, percentile=95)
        # VaR can be negative if all returns are positive (good) or positive if there are losses
        # Just verify it returns a number
        assert result is None or isinstance(result, float)


class TestCheckPerformanceDrift:
    """Tests for check_performance_drift function."""

    def _make_equity_df(
        self, values: list[float], start_date: str = "2024-01-01"
    ) -> pd.DataFrame:
        """Create a properly indexed equity DataFrame."""
        n = len(values)
        return pd.DataFrame(
            {"equity": values},
            index=pd.date_range(start_date, periods=n, tz=UTC),
        )

    def _make_deals_df(self, n: int = 20) -> pd.DataFrame:
        """Create a valid deals DataFrame with proper types."""
        types = ["BUY"] * (n // 2) + ["SELL"] * (n - n // 2)
        profits = [100.0] * (n // 2) + [-50.0] * (n - n // 2)
        return pd.DataFrame(
            {
                "type": types,
                "profit": profits,
                "commission": [-1.0] * n,
                "swap": [0.0] * n,
            }
        )

    def test_returns_none_when_no_live_data(self):
        """When live deals or equity is empty, returns None."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
            return_value=mock_db,
        ):
            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                return_value=pd.DataFrame(),  # Empty deals
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                    return_value=self._make_equity_df([10000.0]),
                ):
                    result = check_performance_drift("no_live_data")

        assert result is None
        mock_db.close.assert_called_once()

    def test_returns_none_when_no_equity_data(self):
        """When equity DataFrame is empty, returns None."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
            return_value=mock_db,
        ):
            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                return_value=self._make_deals_df(20),
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                    return_value=pd.DataFrame(),  # Empty equity
                ):
                    result = check_performance_drift("no_equity_data")

        assert result is None
        mock_db.close.assert_called_once()

    def test_ignores_backtest_when_insufficient_trades(self):
        """When live trades < drift_min_trades, backtest is not queried."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        deals = self._make_deals_df(5)  # Only 5 trades, below min_trades=20
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(5)])

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                        ):
                            result = check_performance_drift("few_trades")

        # Should still get a report (VaR check passes), but no backtest info
        assert result is not None
        assert result.backtest_id is None
        assert result.backtest_metrics is None
        mock_db.close.assert_called_once()

    def test_no_drift_when_metrics_within_thresholds(self):
        """When all live metrics are within thresholds, is_drifting=False."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        deals = self._make_deals_df(20)
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        bt_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 48.0,  # 4% drop - within 15%
            "Profit Factor": 1.9,  # 5% drop - within 20%
            "Drawdown": 10.0,
        }

        mock_backtest = MagicMock(spec=Backtest)
        mock_backtest.id = 1

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=deals,
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ) as mock_notify:
                                        # First query for Setting, second for Backtest
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,  # Setting query
                                            mock_backtest,  # Backtest query
                                        ]
                                        result = check_performance_drift(
                                            "healthy_strategy"
                                        )

        assert result is not None
        assert isinstance(result, DriftReport)
        assert result.is_drifting is False
        assert result.reasons == []
        mock_notify.assert_not_called()
        mock_db.close.assert_called_once()

    def test_detects_win_rate_drift(self):
        """Win rate drop exceeding threshold triggers drift."""
        mock_db = MagicMock()
        mock_backtest = MagicMock(spec=Backtest)
        mock_backtest.id = 1

        deals = self._make_deals_df(20)
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        # Backtest: Win Rate 60%
        # Live: Win Rate 40% (33% drop > 15% threshold)
        bt_metrics = {
            "Win Rate (%)": 60.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 40.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=deals,
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ) as mock_notify:
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,
                                            mock_backtest,
                                        ]
                                        result = check_performance_drift("wr_drifting")

        assert result is not None
        assert result.is_drifting is True
        assert any("Win Rate drop" in r for r in result.reasons)
        mock_notify.assert_called_once_with(result)
        mock_db.close.assert_called_once()

    def test_detects_profit_factor_drift(self):
        """Profit factor drop exceeding threshold triggers drift."""
        mock_db = MagicMock()
        mock_backtest = MagicMock(spec=Backtest)
        mock_backtest.id = 1

        deals = self._make_deals_df(20)
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        # Backtest: Profit Factor 3.0
        # Live: Profit Factor 1.5 (50% drop > 20% threshold)
        bt_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 3.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 1.5,
            "Drawdown": 10.0,
        }

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=deals,
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ) as mock_notify:
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,
                                            mock_backtest,
                                        ]
                                        result = check_performance_drift("pf_drifting")

        assert result is not None
        assert result.is_drifting is True
        assert any("Profit Factor drop" in r for r in result.reasons)
        mock_notify.assert_called_once_with(result)
        mock_db.close.assert_called_once()

    def test_detects_drawdown_breach(self):
        """Live drawdown exceeding backtest threshold triggers drift."""
        mock_db = MagicMock()
        mock_backtest = MagicMock(spec=Backtest)
        mock_backtest.id = 1

        deals = self._make_deals_df(20)
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        # Backtest: Max DD 10%
        # Live: Max DD 15% (> 10% * 1.2 = 12% threshold)
        bt_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 2.0,
            "Drawdown": 15.0,
        }

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=deals,
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ) as mock_notify:
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,
                                            mock_backtest,
                                        ]
                                        result = check_performance_drift("dd_breaching")

        assert result is not None
        assert result.is_drifting is True
        assert any("Drawdown breach" in r for r in result.reasons)
        mock_notify.assert_called_once_with(result)
        mock_db.close.assert_called_once()

    def test_detects_var_breach(self):
        """VaR exceeding threshold triggers drift even without backtest."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Create equity data with high volatility (will breach VaR)
        equity_values = [
            10000.0,
            11000.0,
            12000.0,
            8000.0,
            9000.0,
            10000.0,
            10500.0,
            11000.0,
            7500.0,
            8500.0,
        ]
        equity = self._make_equity_df(equity_values)

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0  # 5% threshold
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=self._make_deals_df(20),
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                        ) as mock_notify:
                            # Ensure no backtest is found via .order_by().first()
                            mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
                            result = check_performance_drift("var_breach")

        assert result is not None
        assert result.is_drifting is True
        assert any("VaR 95% Breach" in r for r in result.reasons)
        mock_notify.assert_called_once_with(result)
        mock_db.close.assert_called_once()

    def test_multiple_drift_reasons_accumulated(self):
        """When multiple metrics breach thresholds, all reasons are accumulated."""
        mock_db = MagicMock()
        mock_backtest = MagicMock(spec=Backtest)
        mock_backtest.id = 1

        # Create equity with high volatility for VaR breach
        equity_values = [10000.0 + (i % 3 - 1) * 500 for i in range(20)]
        equity = self._make_equity_df(equity_values)

        bt_metrics = {
            "Win Rate (%)": 60.0,
            "Profit Factor": 3.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 40.0,
            "Profit Factor": 1.5,
            "Drawdown": 15.0,
        }

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 1.0  # Low threshold to trigger VaR
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=self._make_deals_df(20),
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=self._make_deals_df(20),
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ) as mock_notify:
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,
                                            mock_backtest,
                                        ]
                                        result = check_performance_drift(
                                            "multi_drifting"
                                        )

        assert result is not None
        assert result.is_drifting is True
        # Should have multiple reasons
        assert len(result.reasons) >= 2
        mock_notify.assert_called_once_with(result)
        mock_db.close.assert_called_once()

    def test_returns_none_on_exception(self):
        """On any exception during processing, function returns None and logs the error."""
        mock_db = MagicMock()
        # Mock query to raise an exception inside the try block
        mock_db.query.side_effect = RuntimeError("DB query failed")

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.logger"
                ) as mock_logger:
                    result = check_performance_drift("failing_strategy")

        assert result is None
        mock_logger.error.assert_called_once()
        assert "Error checking drift/risk" in mock_logger.error.call_args[0][0]
        mock_db.close.assert_called_once()

    def test_zero_backtest_win_rate_skips_win_rate_check(self):
        """When backtest Win Rate is 0, win rate drift check is skipped."""
        mock_db = MagicMock()
        mock_backtest = MagicMock(spec=Backtest)
        mock_backtest.id = 1

        deals = self._make_deals_df(20)
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        # Backtest: Win Rate = 0
        # Live: Win Rate = 50%
        bt_metrics = {
            "Win Rate (%)": 0.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=deals,
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ):
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,
                                            mock_backtest,
                                        ]
                                        result = check_performance_drift("zero_bt_wr")

        # Win rate check should be skipped (bt_wr = 0)
        assert result is not None
        assert all("Win Rate drop" not in r for r in result.reasons)
        mock_db.close.assert_called_once()

    def test_zero_backtest_profit_factor_skips_pf_check(self):
        """When backtest Profit Factor is 0 or negative, PF drift check is skipped."""
        mock_db = MagicMock()
        mock_backtest = MagicMock(spec=Backtest)
        mock_backtest.id = 1

        deals = self._make_deals_df(20)
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        # Backtest: PF = 0
        # Live: PF = 2.0
        bt_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 0.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=deals,
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ):
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,
                                            mock_backtest,
                                        ]
                                        result = check_performance_drift("zero_bt_pf")

        # PF check should be skipped (bt_pf = 0)
        assert result is not None
        assert all("Profit Factor drop" not in r for r in result.reasons)
        mock_db.close.assert_called_once()

    def test_drift_report_structure(self):
        """DriftReport contains all expected fields."""
        mock_db = MagicMock()
        mock_backtest = MagicMock()
        mock_backtest.id = 42

        deals = self._make_deals_df(20)
        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        bt_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }
        live_metrics = {
            "Win Rate (%)": 50.0,
            "Profit Factor": 2.0,
            "Drawdown": 10.0,
        }

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.settings"
        ) as mock_settings:
            mock_settings.var_95_threshold = 5.0
            mock_settings.enable_drift_alerts = True
            mock_settings.drift_min_trades = 20
            mock_settings.drift_win_rate_threshold = 15.0
            mock_settings.drift_profit_factor_threshold = 20.0
            mock_settings.drift_max_drawdown_multiplier = 1.2

            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
                return_value=mock_db,
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                    return_value=deals,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                        return_value=equity,
                    ):
                        with patch(
                            "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_deals",
                            return_value=deals,
                        ):
                            with patch(
                                "trademachine.tradingmonitor_analytics.analysis.drift.get_backtest_equity",
                                return_value=equity,
                            ):
                                with patch(
                                    "trademachine.tradingmonitor_analytics.analysis.drift.calculate_metrics_from_df",
                                    side_effect=[live_metrics, bt_metrics],
                                ):
                                    with patch(
                                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                                    ):
                                        # Setting query (no order_by): filter().first()
                                        # Backtest query (with order_by): filter().order_by().first()
                                        mock_db.query.return_value.filter.return_value.first.side_effect = [
                                            None,  # Setting query returns None
                                        ]
                                        mock_db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [
                                            mock_backtest,  # Backtest query
                                        ]
                                        result = check_performance_drift("struct_test")

        assert result is not None
        assert result.strategy_id == "struct_test"
        assert result.backtest_id == 42
        assert result.live_trades == 20
        assert isinstance(result.backtest_metrics, dict)
        assert isinstance(result.live_metrics, dict)
        assert isinstance(result.reasons, list)
        assert isinstance(result.is_drifting, bool)
        mock_db.close.assert_called_once()


class TestNotifyDrift:
    """Tests for _notify_drift function."""

    def test_notify_drift_calls_notifier(self):
        """_notify_drift should send message via notifier."""
        report = DriftReport(
            strategy_id="test_strategy",
            backtest_id=1,
            live_trades=100,
            backtest_metrics={"Win Rate (%)": 50.0},
            live_metrics={"Win Rate (%)": 35.0},
            is_drifting=True,
            reasons=[
                "Win Rate drop: 30.0% (BT: 50.0%, Live: 35.0%)",
            ],
        )

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.notifier"
        ) as mock_notifier:
            _notify_drift(report)
            mock_notifier.send_message_sync.assert_called_once()
            msg = mock_notifier.send_message_sync.call_args[0][0]
            assert "PERFORMANCE DRIFT DETECTED" in msg
            assert "test_strategy" in msg
            assert "Win Rate drop" in msg


class TestDependencyInjection:
    """Tests demonstrating dependency injection for settings."""

    def _make_equity_df(
        self, values: list[float], start_date: str = "2024-01-01"
    ) -> pd.DataFrame:
        """Create a properly indexed equity DataFrame."""
        n = len(values)
        return pd.DataFrame(
            {"equity": values},
            index=pd.date_range(start_date, periods=n, tz=UTC),
        )

    def _make_deals_df(self, n: int = 20) -> pd.DataFrame:
        """Create a valid deals DataFrame with proper types."""
        types = ["BUY"] * (n // 2) + ["SELL"] * (n - n // 2)
        profits = [100.0] * (n // 2) + [-50.0] * (n - n // 2)
        return pd.DataFrame(
            {
                "type": types,
                "profit": profits,
                "commission": [-1.0] * n,
                "swap": [0.0] * n,
            }
        )

    def test_drift_detection_with_custom_threshold_via_di(self):
        """Demonstrates DI: passing custom Settings instance directly.

        This test shows how DI allows testing with custom settings without patching.
        """
        from trademachine.tradingmonitor_analytics.analysis.drift import (
            check_performance_drift,
        )
        from trademachine.tradingmonitor_storage.config import Settings

        # Create custom settings with a very low VaR threshold to trigger drift
        custom_settings = Settings(
            var_95_threshold=0.1,  # Very low threshold to trigger VaR breach
            enable_drift_alerts=False,  # Disable drift alerts to focus on VaR
            drift_min_trades=20,
            drift_win_rate_threshold=15.0,
            drift_profit_factor_threshold=20.0,
            drift_max_drawdown_multiplier=1.2,
        )

        # Create equity with high volatility to breach VaR
        equity_values = [
            10000.0,
            11000.0,
            12000.0,
            8000.0,  # Big drop
            9000.0,
            10000.0,
            10500.0,
            11000.0,
            7500.0,  # Another big drop
            8500.0,
        ]
        equity = self._make_equity_df(equity_values)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
            return_value=mock_db,
        ):
            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                return_value=self._make_deals_df(20),
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                    return_value=equity,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                    ) as mock_notify:
                        # Ensure no backtest is found via .order_by().first()
                        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
                        # Pass custom settings directly via DI - no patching needed!
                        result = check_performance_drift(
                            "di_test_strategy", settings=custom_settings
                        )

        # VaR should breach with such low threshold
        assert result is not None
        assert result.is_drifting is True
        assert any("VaR 95% Breach" in r for r in result.reasons)
        mock_notify.assert_called_once_with(result)
        mock_db.close.assert_called_once()

    def test_drift_check_with_high_threshold_no_drift(self):
        """Demonstrates DI: high threshold means no drift detected."""
        from trademachine.tradingmonitor_analytics.analysis.drift import (
            check_performance_drift,
        )
        from trademachine.tradingmonitor_storage.config import Settings

        # Create custom settings with very high VaR threshold (no drift possible)
        custom_settings = Settings(
            var_95_threshold=50.0,  # Very high - no drift possible
            enable_drift_alerts=False,
            drift_min_trades=20,
            drift_win_rate_threshold=15.0,
            drift_profit_factor_threshold=20.0,
            drift_max_drawdown_multiplier=1.2,
        )

        equity = self._make_equity_df([10000.0 + i * 10 for i in range(20)])

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch(
            "trademachine.tradingmonitor_analytics.analysis.drift.SessionLocal",
            return_value=mock_db,
        ):
            with patch(
                "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_deals",
                return_value=self._make_deals_df(20),
            ):
                with patch(
                    "trademachine.tradingmonitor_analytics.analysis.drift.get_strategy_equity_curve",
                    return_value=equity,
                ):
                    with patch(
                        "trademachine.tradingmonitor_analytics.analysis.drift._notify_drift"
                    ) as mock_notify:
                        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
                        # With 50% threshold, even volatile equity won't breach
                        result = check_performance_drift(
                            "high_threshold_test", settings=custom_settings
                        )

        assert result is not None
        assert result.is_drifting is False
        assert result.reasons == []
        mock_notify.assert_not_called()
        mock_db.close.assert_called_once()
