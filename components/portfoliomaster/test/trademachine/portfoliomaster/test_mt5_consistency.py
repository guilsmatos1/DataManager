from trademachine.portfoliomaster.services.metrics import calculate_metrics_from_deals
from trademachine.portfoliomaster.services.portfolio import PortfolioManager


def test_all_reports_parse_without_error(pt_parser):
    """All HTML reports in tests/reports/ parse without raising exceptions."""
    assert pt_parser.deals_by_expert, "No reports were parsed"
    for name, deals_df in pt_parser.deals_by_expert.items():
        assert not deals_df.empty, f"Empty deals for expert: {name}"


def test_parser_deals_have_required_columns(pt_parser):
    """Parsed deals DataFrames contain the expected MT5 columns."""
    name = list(pt_parser.deals_by_expert.keys())[0]
    deals_df = pt_parser.deals_by_expert[name]

    required_cols = ["Horário", "Tipo", "Direção", "Lucro", "Comissão", "Swap"]
    for col in required_cols:
        assert col in deals_df.columns, f"Missing column: {col}"


def test_metrics_calculation_from_real_reports(pt_parser):
    """calculate_metrics_from_deals returns valid results for real MT5 reports."""
    items = list(pt_parser.deals_by_expert.items())[:5]

    for _name, deals_df in items:
        metrics = calculate_metrics_from_deals(deals_df)
        if not metrics:
            continue  # skip if report has no closed trades

        assert "Net_Profit" in metrics
        assert "Maximum_Drawdown" in metrics
        assert "Total_Trades" in metrics
        assert isinstance(metrics["Net_Profit"], float)
        assert metrics["Maximum_Drawdown"] >= 0.0
        assert metrics["Total_Trades"] > 0


def test_metrics_retdd_consistency(pt_parser):
    """RetDD equals Net_Profit / Maximum_Drawdown when MaxDD > 0."""
    checked = 0

    for name, deals_df in pt_parser.deals_by_expert.items():
        metrics = calculate_metrics_from_deals(deals_df)

        if not metrics or metrics.get("Maximum_Drawdown", 0) == 0:
            continue

        expected_retdd = metrics["Net_Profit"] / metrics["Maximum_Drawdown"]
        assert abs(metrics["RetDD"] - expected_retdd) < 0.01, (
            f"RetDD inconsistency for {name}: "
            f"got {metrics['RetDD']:.4f}, expected {expected_retdd:.4f}"
        )
        checked += 1

    assert checked > 0, "No reports with non-zero MaxDD found to validate"


# ---------------------------------------------------------------------------
# English report tests
# ---------------------------------------------------------------------------


def test_en_report_parses_without_error(en_parser):
    """English MT5 report parses successfully and returns a non-empty deals table."""
    assert en_parser.deals_by_expert, "No EN reports were parsed"
    for name, deals_df in en_parser.deals_by_expert.items():
        assert not deals_df.empty, f"Empty deals for {name}"


def test_en_report_has_pt_columns(en_parser):
    """After parsing, EN report columns are renamed to Portuguese (internal standard)."""
    name = list(en_parser.deals_by_expert.keys())[0]
    deals_df = en_parser.deals_by_expert[name]

    required = ["Horário", "Tipo", "Direção", "Lucro", "Comissão", "Swap", "Saldo"]
    for col in required:
        assert col in deals_df.columns, f"Missing column after EN→PT rename: {col}"


def test_en_report_tipo_values(en_parser):
    """EN report preserves the expected Tipo values (buy/sell/balance)."""
    name = list(en_parser.deals_by_expert.keys())[0]
    deals_df = en_parser.deals_by_expert[name]

    tipos = set(deals_df["Tipo"].unique())
    assert tipos.issubset({"buy", "sell", "balance"}), (
        f"Unexpected Tipo values: {tipos}"
    )


def test_en_report_direcao_values(en_parser):
    """EN report preserves the expected Direção values (in/out/in/out or empty for balance)."""
    name = list(en_parser.deals_by_expert.keys())[0]
    deals_df = en_parser.deals_by_expert[name]

    direcoes = set(deals_df["Direção"].unique())
    assert direcoes.issubset({"in", "out", "in/out", ""}), (
        f"Unexpected Direção values: {direcoes}"
    )


def test_en_report_metrics_are_valid(en_parser):
    """Full pipeline: EN report → PortfolioManager → valid metrics."""
    pm = PortfolioManager()

    for name, deals_df in en_parser.deals_by_expert.items():
        ok = pm.add_strategy(name, deals_df)
        assert ok, f"add_strategy failed for {name}"

        metrics = pm.calculate_strategy_metrics(name)
        assert metrics is not None
        assert metrics["Trades"] > 0
        assert isinstance(metrics["Profit"], float)
        assert metrics["MaxDD"] >= 0.0


def test_en_report_metrics_retdd_consistency(en_parser):
    """RetDD from EN report equals Net_Profit / Maximum_Drawdown."""
    for name, deals_df in en_parser.deals_by_expert.items():
        metrics = calculate_metrics_from_deals(deals_df)

        if not metrics or metrics.get("Maximum_Drawdown", 0) == 0:
            continue

        expected = round(metrics["Net_Profit"] / metrics["Maximum_Drawdown"], 2)
        assert abs(metrics["RetDD"] - expected) < 0.01, (
            f"RetDD mismatch for {name}: got {metrics['RetDD']}, expected {expected}"
        )
