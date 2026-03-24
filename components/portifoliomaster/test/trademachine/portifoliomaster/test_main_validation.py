"""
Tests for validate_cli_args() in main.py.
Covers all validation branches: min/max assets, correlation range, greedy constraint.
"""

import argparse

import pytest
from trademachine.portifolio_master_cli.main import validate_cli_args
from trademachine.portifoliomaster.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _args(**kwargs):
    """Build a minimal Namespace with sensible defaults, overridden by kwargs."""
    defaults = dict(min=2, max=5, corr=0.3, optimize=True, greedy=False)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# --min validation
# ---------------------------------------------------------------------------


def test_min_below_1_raises():
    with pytest.raises(ValidationError, match="at least 1"):
        validate_cli_args(_args(min=0))


def test_min_equal_1_passes():
    validate_cli_args(_args(min=1, max=5))  # should not raise


def test_min_equal_max_passes():
    validate_cli_args(_args(min=3, max=3))


def test_min_greater_than_max_raises():
    with pytest.raises(ValidationError, match="cannot be greater than"):
        validate_cli_args(_args(min=5, max=3))


# ---------------------------------------------------------------------------
# --corr validation
# ---------------------------------------------------------------------------


def test_corr_below_minus1_raises():
    with pytest.raises(ValidationError, match="between -1.0 and 1.0"):
        validate_cli_args(_args(corr=-1.1))


def test_corr_above_1_raises():
    with pytest.raises(ValidationError, match="between -1.0 and 1.0"):
        validate_cli_args(_args(corr=1.01))


def test_corr_at_minus1_passes():
    validate_cli_args(_args(corr=-1.0))


def test_corr_at_1_passes():
    validate_cli_args(_args(corr=1.0))


def test_corr_zero_passes():
    validate_cli_args(_args(corr=0.0))


# ---------------------------------------------------------------------------
# --greedy validation
# ---------------------------------------------------------------------------


def test_greedy_without_optimize_raises():
    with pytest.raises(ValidationError, match="--greedy requires --optimize"):
        validate_cli_args(_args(greedy=True, optimize=False))


def test_greedy_with_optimize_passes():
    validate_cli_args(_args(greedy=True, optimize=True))


def test_greedy_false_without_optimize_passes():
    validate_cli_args(_args(greedy=False, optimize=False))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_args_do_not_raise():
    validate_cli_args(_args(min=2, max=5, corr=0.3, greedy=False, optimize=True))


def test_valid_args_single_asset():
    validate_cli_args(_args(min=1, max=1, corr=0.0, greedy=False, optimize=True))


def test_valid_args_extreme_corr_values():
    validate_cli_args(_args(corr=-1.0))
    validate_cli_args(_args(corr=1.0))
