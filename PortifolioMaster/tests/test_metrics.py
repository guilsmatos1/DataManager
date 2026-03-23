import pandas as pd
import polars as pl

from portifoliomaster.services.metrics import (
    clean_mt5_numeric_string,
    compute_vector_metrics,
)


def test_compute_vector_metrics_simple():
    # Lucro: 100, MaxDD: 20 (pico 100 -> queda para 80), RetDD: 5
    returns = [50, 50, -20, 20]
    results = compute_vector_metrics(returns)

    assert results["Profit"] == 100.0
    assert results["MaxDD"] == 20.0
    assert results["RetDD"] == 5.0


def test_compute_vector_metrics_empty():
    results = compute_vector_metrics([])
    assert results["Profit"] == 0.0
    assert results["RetDD"] == 0.0


def test_clean_mt5_numeric_string_pandas():
    s = pd.Series(["1 000.50", "-500.00", "", "  "])
    cleaned = clean_mt5_numeric_string(s)
    assert cleaned.iloc[0] == 1000.50
    assert cleaned.iloc[1] == -500.00
    assert cleaned.iloc[2] == 0.0
    assert cleaned.iloc[3] == 0.0


def test_clean_mt5_numeric_string_polars():
    s = pl.Series(["1 200.00", "invalid", ""])
    cleaned = clean_mt5_numeric_string(s)
    assert cleaned[0] == 1200.0
    assert cleaned[1] == 0.0  # fallback fill_null
    assert cleaned[2] == 0.0
