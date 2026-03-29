import json
import os
import shutil
import subprocess
import sys

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_optimization(output_dir, top_n=5, rank="RetDD", min_a=2, max_a=2, corr=1.0):
    """Helper: run optimization via CLI and return the subprocess result."""
    env = os.environ.copy()
    src_path = os.path.join(PROJECT_ROOT, "src")
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = os.pathsep.join([src_path, env["PYTHONPATH"]])
    else:
        env["PYTHONPATH"] = src_path

    cmd = [
        sys.executable,
        "-m",
        "trademachine.portifolio_master_cli.main",
        "optimize",
        "--load",
        REPORTS_DIR,
        "--min",
        str(min_a),
        "--max",
        str(max_a),
        "--corr",
        str(corr),
        "--top",
        str(top_n),
        "--rank",
        rank,
        "--workers",
        "1",
        "--output",
        output_dir,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, env=env
    )


def _load_rank_json(output_dir):
    """Read portfolios list from rank.json in the given output directory."""
    rank_path = os.path.join(output_dir, "rank.json")
    with open(rank_path, encoding="utf-8") as f:
        return json.load(f)["portfolios"]


def test_optimization_produces_output():
    """Optimization creates the output directory with rank.json from tests/reports/."""
    output_dir = os.path.join(PROJECT_ROOT, "_test_output")
    try:
        result = _run_optimization(output_dir)
        rank_path = os.path.join(output_dir, "rank.json")
        assert os.path.exists(rank_path), (
            f"rank.json not created.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        portfolios = _load_rank_json(output_dir)
        assert len(portfolios) > 0, "Optimization produced an empty rank.json"
    finally:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)


def test_optimization_is_deterministic():
    """Two consecutive runs with identical params produce identical portfolio rankings."""
    out1 = os.path.join(PROJECT_ROOT, "_test_det1")
    out2 = os.path.join(PROJECT_ROOT, "_test_det2")
    try:
        _run_optimization(out1)
        _run_optimization(out2)

        p1 = _load_rank_json(out1)
        p2 = _load_rank_json(out2)

        assert len(p1) == len(p2), "Different result counts between runs"
        assert [p["strategies"] for p in p1] == [p["strategies"] for p in p2], (
            "Portfolio order differs between runs"
        )
    finally:
        for d in [out1, out2]:
            if os.path.exists(d):
                shutil.rmtree(d)


def test_optimization_top_n_respected():
    """Optimization returns at most top_n results."""
    top_n = 5
    output_dir = os.path.join(PROJECT_ROOT, "_test_topn")
    try:
        _run_optimization(output_dir, top_n=top_n)
        portfolios = _load_rank_json(output_dir)
        assert len(portfolios) <= top_n, (
            f"Got {len(portfolios)} results, expected at most {top_n}"
        )
    finally:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)


def test_optimization_retdd_sorted_descending():
    """Results are sorted by RetDD descending when --rank RetDD."""
    output_dir = os.path.join(PROJECT_ROOT, "_test_sort")
    try:
        _run_optimization(output_dir, top_n=10, rank="RetDD")
        portfolios = _load_rank_json(output_dir)
        assert len(portfolios) > 0

        retdd_values = [p["metrics"]["RetDD"] for p in portfolios]
        assert retdd_values == sorted(retdd_values, reverse=True), (
            f"Results not sorted by RetDD descending: {retdd_values}"
        )
    finally:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)


def test_optimization_metrics_are_mathematically_valid():
    """Every result row satisfies: MaxDD >= 0 and RetDD == Profit/MaxDD (when MaxDD > 0)."""
    output_dir = os.path.join(PROJECT_ROOT, "_test_math")
    try:
        _run_optimization(output_dir, top_n=10, corr=1.0)
        portfolios = _load_rank_json(output_dir)
        assert len(portfolios) > 0

        for p in portfolios:
            m = p["metrics"]
            assert m["Maximum_Drawdown"] >= 0.0, "Negative MaxDD found"
            if m["Maximum_Drawdown"] > 0:
                expected_retdd = m["Net_Profit"] / m["Maximum_Drawdown"]
                assert abs(m["RetDD"] - expected_retdd) < 0.01, (
                    f"RetDD mismatch for {p['strategies']}: "
                    f"got {m['RetDD']:.4f}, expected {expected_retdd:.4f}"
                )
    finally:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)


def test_optimization_3asset_portfolios():
    """3-asset portfolios are generated and all combos have exactly 3 strategies."""
    output_dir = os.path.join(PROJECT_ROOT, "_test_3asset")
    try:
        _run_optimization(output_dir, top_n=5, min_a=3, max_a=3, corr=1.0)
        portfolios = _load_rank_json(output_dir)
        assert len(portfolios) > 0

        for p in portfolios:
            strategies = p["strategies"]
            assert len(strategies) == 3, (
                f"Expected 3 strategies, got {len(strategies)}: {strategies}"
            )
    finally:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
