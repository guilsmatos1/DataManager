from trademachine.portifoliomaster.utils.help import get_detailed_help


def test_detailed_help_includes_current_cli_contract():
    help_text = get_detailed_help()

    assert "portifoliomaster optimize --load reports/" in help_text
    assert "optimize --exclude-strats <L>" in help_text
    assert "cache merge <A> <B> <C>" in help_text
    assert "--report file.csv" in help_text
    assert "optimize --prune-cache" in help_text


def test_detailed_help_excludes_legacy_cli_contract():
    help_text = get_detailed_help()

    assert "portifoliomaster --optimize" not in help_text
    assert "portifoliomaster drawdown pairing" not in help_text
    assert "portifoliomaster --load reports/ --list" not in help_text
