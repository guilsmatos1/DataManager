import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# Add components/datamanager/src to path for imports
# Assuming script is run from projects/datamanager/scripts/
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parents[2]
datamanager_src = project_root / "components" / "datamanager" / "src"
sys.path.insert(0, str(datamanager_src))

from trademachine.datamanager.db.database import init_db  # noqa: E402
from trademachine.datamanager.db.storage import StorageManager  # noqa: E402


def migrate_parquet_to_timescale(base_dir: str = "database"):
    """
    Scans the database directory for M1 parquet files and migrates them to TimescaleDB.
    """
    base_path = Path(base_path_absolute)
    if not base_path.exists():
        print(f"Error: Base directory '{base_dir}' not found.")
        return

    # Initialize TimescaleDB (creates hypertables if they don't exist)
    print("Initializing TimescaleDB schema...")
    init_db()

    storage = StorageManager()

    # Identify M1 parquet files
    m1_files = []
    for source_dir in base_path.iterdir():
        if not source_dir.is_dir() or source_dir.name.startswith("."):
            continue
        for asset_dir in source_dir.iterdir():
            if not asset_dir.is_dir():
                continue
            m1_path = asset_dir / "M1" / "data.parquet"
            if m1_path.exists():
                m1_files.append((source_dir.name, asset_dir.name, m1_path))

    if not m1_files:
        print("No M1 Parquet files found for migration.")
        return

    print(f"Found {len(m1_files)} databases to migrate.")

    for source, asset, file_path in tqdm(m1_files, desc="Migrating databases"):
        try:
            # Load parquet
            df = pd.read_parquet(file_path, engine="pyarrow")

            if df.empty:
                print(f"  Skipping empty database: {source}/{asset}")
                continue

            # Save to TimescaleDB (M1)
            storage.save_data(df, source, asset, "M1")

        except Exception as e:
            print(f"\n  [ERROR] Failed to migrate {source}/{asset}: {e}")

    print("\nMigration completed!")


if __name__ == "__main__":
    # Base dir is in the project root
    base_path_absolute = project_root / "database"
    if not base_path_absolute.exists():
        # Fallback to local database dir if running from project context
        base_path_absolute = project_root.parent / "database"

    print(f"Searching for Parquet files in: {base_path_absolute}")
    migrate_parquet_to_timescale()
