import pytest
from pydantic import ValidationError
from trademachine.portifoliomaster.core.config import AppConfig


def test_default_config():
    """Test that default values are correctly loaded."""
    config = AppConfig()
    assert config.min_assets == 5
    assert config.max_assets == 5
    assert config.top_n == 10
    assert config.max_corr == 0.3
    assert config.corr_period == "D"
    assert config.rank_by == "RetDD"
    assert config.num_workers == 0
    assert config.print_results is False
    assert config.output_dir == ""
    assert len(config.csv_columns) > 0


def test_min_max_assets_validation():
    """Test min_assets and max_assets validation."""
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        AppConfig(min_assets=0)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        AppConfig(max_assets=0)

    # Valid values
    config = AppConfig(min_assets=2, max_assets=10)
    assert config.min_assets == 2
    assert config.max_assets == 10


def test_max_corr_validation():
    """Test max_corr validation bounds (-1.0 to 1.0)."""
    with pytest.raises(ValidationError, match="less than or equal to 1"):
        AppConfig(max_corr=1.5)

    with pytest.raises(ValidationError, match="greater than or equal to -1"):
        AppConfig(max_corr=-1.5)

    # Valid values
    config = AppConfig(max_corr=0.8)
    assert config.max_corr == 0.8
    config2 = AppConfig(max_corr=-0.5)
    assert config2.max_corr == -0.5


def test_corr_period_validation():
    """Test corr_period accepts valid periods and rejects invalid ones."""
    for period in ["H", "D", "W", "M"]:
        config = AppConfig(corr_period=period)
        assert config.corr_period == period

    with pytest.raises(ValidationError, match="corr_period must be one of"):
        AppConfig(corr_period="X")


def test_rank_by_validation():
    """Test rank_by accepts valid rankings and rejects invalid ones."""
    for rank in ["RetDD", "NetProfit"]:
        config = AppConfig(rank_by=rank)
        assert config.rank_by == rank

    with pytest.raises(ValidationError, match="rank_by must be one of"):
        AppConfig(rank_by="TotalProfit")


def test_from_json():
    """Test from_json() backward compatibility method."""
    config = AppConfig.from_json()
    assert isinstance(config, AppConfig)
    assert config.min_assets >= 1  # Should be the default or loaded env value
