import json

import polars as pl
from trademachine.portifoliomaster.services.output import OptimizationOutputService


def _sample_service(tmp_path):
    strategies = {
        "A": pl.DataFrame({"Horário": [1, 2, 3], "Net_Profit": [10.0, 20.0, -5.0]}),
        "B": pl.DataFrame({"Horário": [1, 2, 4], "Net_Profit": [5.0, -2.0, 15.0]}),
    }
    lots = {"A": 0.6000000000000001, "B": 1.1}
    written = []

    def save_portfolio_trades(portfolios, path):
        written.append(path)
        pl.DataFrame({"Strategy": ["A"], "Net_Profit": [1.0]}).write_parquet(path)
        return 1

    def report_generator(portfolios, strategies, **kwargs):
        output_path = kwargs["output_path"]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("<html>report</html>")
        return output_path

    service = OptimizationOutputService(
        strategies,
        lots,
        save_portfolio_trades=save_portfolio_trades,
        report_generator=report_generator,
    )
    return service, written


def test_output_service_build_rank_payload_rounds_lots(tmp_path):
    service, _ = _sample_service(tmp_path)

    payload = service.build_rank_payload(
        [{"Combo": ("A", "B"), "Net_Profit": 100.0, "RetDD": 2.5}],
        config={"rank_by": "RetDD"},
    )

    assert set(payload) == {"generated_at", "config", "portfolios"}
    assert payload["portfolios"][0]["lots"] == {"A": 0.6, "B": 1.1}
    assert set(payload["portfolios"][0]["weights"]) == {"A", "B"}


def test_output_service_save_output_bundle_creates_expected_files(tmp_path):
    service, written = _sample_service(tmp_path)

    output_dir = service.save_output_bundle(
        [{"Combo": ("A",), "Net_Profit": 100.0, "RetDD": 2.5}],
        output_dir=str(tmp_path / "run_test"),
        config={"rank_by": "RetDD"},
        strategy_names=["A"],
        correlation_matrix=None,
        correlation_period="D",
    )

    assert (tmp_path / "run_test" / "rank.json").exists()
    assert (tmp_path / "run_test" / "portfolios" / "rank_01.parquet").exists()
    assert (tmp_path / "run_test" / "report.html").exists()
    assert written == [str(tmp_path / "run_test" / "portfolios" / "rank_01.parquet")]
    with open(tmp_path / "run_test" / "rank.json", encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["portfolios"][0]["strategies"] == ["A"]
    assert output_dir == str(tmp_path / "run_test")
