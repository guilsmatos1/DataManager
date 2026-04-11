import json
from datetime import datetime

import polars as pl
from trademachine.portfoliomaster.services.cache import CacheService
from trademachine.portfoliomaster.services.portfolio import PortfolioManager


def test_cache_service_load_into_manager_resets_memory(tmp_path):
    cache_path = tmp_path / "cache.parquet"
    pl.DataFrame(
        {"Horário": [datetime(2024, 1, 1)], "A": [1.0], "B": [0.0]}
    ).write_parquet(cache_path)
    (tmp_path / "cache_lots.json").write_text(json.dumps({"A": 0.5, "B": 0.7}))

    manager = PortfolioManager()
    manager.strategies["OLD"] = pl.DataFrame(
        {"Horário": [datetime(2023, 1, 1)], "Net_Profit": [9.0]}
    )
    manager.strategy_lots["OLD"] = 9.0

    loaded = CacheService(str(cache_path)).load_into_manager(manager)

    assert loaded == ["A", "B"]
    assert set(manager.strategies) == {"A", "B"}
    assert manager.strategy_lots == {"A": 0.5, "B": 0.7}


def test_cache_service_merge_snapshots_overrides_right_side(tmp_path):
    left = tmp_path / "left.parquet"
    right = tmp_path / "right.parquet"
    destination = tmp_path / "merged" / "merged_cache.parquet"

    pl.DataFrame(
        {
            "Horário": [datetime(2024, 1, 1), datetime(2024, 1, 2)],
            "A": [1.0, 0.0],
            "B": [2.0, 2.0],
        }
    ).write_parquet(left)
    pl.DataFrame(
        {
            "Horário": [datetime(2024, 1, 2), datetime(2024, 1, 3)],
            "B": [9.0, 9.0],
            "C": [3.0, 4.0],
        }
    ).write_parquet(right)
    (tmp_path / "left_lots.json").write_text(json.dumps({"A": 0.5, "B": 0.6}))
    (tmp_path / "right_lots.json").write_text(json.dumps({"B": 1.1, "C": 1.2}))

    duplicates, lots_path = CacheService.merge_snapshots(
        str(left), str(right), str(destination)
    )

    assert duplicates == ["B"]
    merged = pl.read_parquet(destination).sort("Horário")
    assert merged.select("B").to_series().to_list() == [None, 9.0, 9.0]
    assert lots_path is not None
    assert json.loads((tmp_path / "merged" / "merged_cache_lots.json").read_text()) == {
        "A": 0.5,
        "B": 1.1,
        "C": 1.2,
    }


def test_cache_service_load_snapshot_removes_existing_active_lots(tmp_path):
    source = tmp_path / "imports" / "snapshot.parquet"
    source.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"Horário": [datetime(2024, 1, 1)], "A": [1.0]}).write_parquet(source)

    active_cache = tmp_path / "active_cache.parquet"
    active_lots = tmp_path / "active_cache_lots.json"
    active_lots.write_text(json.dumps({"OLD": 9.0}))

    service = CacheService(str(active_cache))
    _, loaded_lots_path = service.load_snapshot(str(source))

    assert active_cache.exists()
    assert loaded_lots_path is None
    assert not active_lots.exists()
