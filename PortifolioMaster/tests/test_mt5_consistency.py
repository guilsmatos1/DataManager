import glob
import os

from portifoliomaster.services.metrics import calculate_metrics_from_deals
from portifoliomaster.services.portfolio import PortfolioManager
from portifoliomaster.utils.mt5_parser import MT5ReportParser

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
REPORTS_EN_DIR = os.path.join(os.path.dirname(__file__), "reports-en")


def test_all_reports_parse_without_error():
    """All HTML reports in tests/reports/ parse without raising exceptions."""
    report_files = glob.glob(os.path.join(REPORTS_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports/"

    parser = MT5ReportParser()
    failed = []

    for filepath in report_files[:10]:
        try:
            expert_name = parser.parse_report(filepath)
            deals_df = parser.deals_by_expert[expert_name]
            assert not deals_df.empty
        except Exception as e:
            failed.append((os.path.basename(filepath), str(e)))

    assert not failed, f"Failed to parse reports: {failed}"


def test_parser_deals_have_required_columns():
    """Parsed deals DataFrames contain the expected MT5 columns."""
    report_files = glob.glob(os.path.join(REPORTS_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports/"

    parser = MT5ReportParser()
    expert_name = parser.parse_report(report_files[0])
    deals_df = parser.deals_by_expert[expert_name]

    required_cols = ["Horário", "Tipo", "Direção", "Lucro", "Comissão", "Swap"]
    for col in required_cols:
        assert col in deals_df.columns, f"Missing column: {col}"


def test_metrics_calculation_from_real_reports():
    """calculate_metrics_from_deals returns valid results for real MT5 reports."""
    report_files = glob.glob(os.path.join(REPORTS_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports/"

    parser = MT5ReportParser()

    for filepath in report_files[:5]:
        expert_name = parser.parse_report(filepath)
        deals_df = parser.deals_by_expert[expert_name]

        metrics = calculate_metrics_from_deals(deals_df)
        if not metrics:
            continue  # skip if report has no closed trades

        assert "Net_Profit" in metrics
        assert "Maximum_Drawdown" in metrics
        assert "Total_Trades" in metrics
        assert isinstance(metrics["Net_Profit"], float)
        assert metrics["Maximum_Drawdown"] >= 0.0
        assert metrics["Total_Trades"] > 0


def test_metrics_retdd_consistency():
    """RetDD equals Net_Profit / Maximum_Drawdown when MaxDD > 0."""
    report_files = glob.glob(os.path.join(REPORTS_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports/"

    parser = MT5ReportParser()
    checked = 0

    for filepath in report_files[:10]:
        expert_name = parser.parse_report(filepath)
        deals_df = parser.deals_by_expert[expert_name]
        metrics = calculate_metrics_from_deals(deals_df)

        if not metrics or metrics.get("Maximum_Drawdown", 0) == 0:
            continue

        expected_retdd = metrics["Net_Profit"] / metrics["Maximum_Drawdown"]
        assert abs(metrics["RetDD"] - expected_retdd) < 0.01, (
            f"RetDD inconsistency for {os.path.basename(filepath)}: "
            f"got {metrics['RetDD']:.4f}, expected {expected_retdd:.4f}"
        )
        checked += 1

    assert checked > 0, "No reports with non-zero MaxDD found to validate"


# ---------------------------------------------------------------------------
# English report tests
# ---------------------------------------------------------------------------


def test_en_report_parses_without_error():
    """English MT5 report parses successfully and returns a non-empty deals table."""
    report_files = glob.glob(os.path.join(REPORTS_EN_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports-en/"

    parser = MT5ReportParser()
    for filepath in report_files[:10]:
        expert_name = parser.parse_report(filepath)
        deals_df = parser.deals_by_expert[expert_name]
        assert not deals_df.empty, f"Empty deals for {os.path.basename(filepath)}"


def test_en_report_has_pt_columns():
    """After parsing, EN report columns are renamed to Portuguese (internal standard)."""
    report_files = glob.glob(os.path.join(REPORTS_EN_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports-en/"

    parser = MT5ReportParser()
    expert_name = parser.parse_report(report_files[0])
    deals_df = parser.deals_by_expert[expert_name]

    required = ["Horário", "Tipo", "Direção", "Lucro", "Comissão", "Swap", "Saldo"]
    for col in required:
        assert col in deals_df.columns, f"Missing column after EN→PT rename: {col}"


def test_en_report_tipo_values():
    """EN report preserves the expected Tipo values (buy/sell/balance)."""
    report_files = glob.glob(os.path.join(REPORTS_EN_DIR, "*.html"))
    assert report_files

    parser = MT5ReportParser()
    expert_name = parser.parse_report(report_files[0])
    deals_df = parser.deals_by_expert[expert_name]

    tipos = set(deals_df["Tipo"].unique())
    assert tipos.issubset({"buy", "sell", "balance"}), f"Unexpected Tipo values: {tipos}"


def test_en_report_direcao_values():
    """EN report preserves the expected Direção values (in/out/in/out or empty for balance)."""
    report_files = glob.glob(os.path.join(REPORTS_EN_DIR, "*.html"))
    assert report_files

    parser = MT5ReportParser()
    expert_name = parser.parse_report(report_files[0])
    deals_df = parser.deals_by_expert[expert_name]

    direcoes = set(deals_df["Direção"].unique())
    assert direcoes.issubset({"in", "out", "in/out", ""}), f"Unexpected Direção values: {direcoes}"


def test_en_report_metrics_are_valid():
    """Full pipeline: EN report → PortfolioManager → valid metrics."""
    report_files = glob.glob(os.path.join(REPORTS_EN_DIR, "*.html"))
    assert report_files

    parser = MT5ReportParser()
    pm = PortfolioManager()

    for filepath in report_files[:10]:
        expert_name = parser.parse_report(filepath)
        deals_df = parser.deals_by_expert[expert_name]

        ok = pm.add_strategy(expert_name, deals_df)
        assert ok, f"add_strategy failed for {expert_name}"

        metrics = pm.calculate_strategy_metrics(expert_name)
        assert metrics is not None
        assert metrics["Trades"] > 0
        assert isinstance(metrics["Profit"], float)
        assert metrics["MaxDD"] >= 0.0


def test_en_report_metrics_retdd_consistency():
    """RetDD from EN report equals Net_Profit / Maximum_Drawdown."""
    report_files = glob.glob(os.path.join(REPORTS_EN_DIR, "*.html"))
    assert report_files

    parser = MT5ReportParser()
    for filepath in report_files[:10]:
        expert_name = parser.parse_report(filepath)
        deals_df = parser.deals_by_expert[expert_name]
        metrics = calculate_metrics_from_deals(deals_df)

        if not metrics or metrics.get("Maximum_Drawdown", 0) == 0:
            continue

        expected = round(metrics["Net_Profit"] / metrics["Maximum_Drawdown"], 2)
        assert abs(metrics["RetDD"] - expected) < 0.01, (
            f"RetDD mismatch for {expert_name}: got {metrics['RetDD']}, expected {expected}"
        )
