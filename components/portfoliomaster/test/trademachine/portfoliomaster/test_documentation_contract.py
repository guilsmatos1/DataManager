"""Contract tests for operational documentation files."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
GEMINI_PATH = REPO_ROOT / "projects" / "portfoliomaster" / "GEMINI.md"
CLAUDE_PATH = REPO_ROOT / "projects" / "portfoliomaster" / "CLAUDE.md"
AGENTS_PATH = REPO_ROOT / "projects" / "portfoliomaster" / "AGENTS.md"
DOC_PATHS = (GEMINI_PATH, CLAUDE_PATH, AGENTS_PATH)

CURRENT_DOC_TOKENS = [
    "uv run portfoliomaster load",
    "uv run portfoliomaster benchmark",
    "uv run portfoliomaster optimize-genetic",
    "--ga-loop",
    "cache save",
    "cache load",
    "cache merge",
    "--greedy-loops",
    "--prune-cache",
    "--exclude-strats",
    "--export-passed-reports",
    "pairing --load",
    "pairing.csv",
]

LEGACY_DOC_TOKENS = [
    "portfoliomaster --optimize",
    "portfoliomaster drawdown pairing",
    "portfoliomaster --load reports/ --list",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operational_docs_are_identical_to_gemini():
    gemini_text = _read(GEMINI_PATH)

    for path in (CLAUDE_PATH, AGENTS_PATH):
        assert _read(path) == gemini_text


def test_operational_docs_cover_current_cli_contract():
    for path in DOC_PATHS:
        text = _read(path)
        for token in CURRENT_DOC_TOKENS:
            assert token in text


def test_operational_docs_exclude_legacy_cli_examples():
    for path in DOC_PATHS:
        text = _read(path)
        for token in LEGACY_DOC_TOKENS:
            assert token not in text
