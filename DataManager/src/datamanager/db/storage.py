import shutil
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd


@contextmanager
def _file_lock(path: Path):
    """Cross-platform exclusive file lock for Parquet files (sidecar .lock file)."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")
    try:
        if sys.platform == "win32":
            import msvcrt

            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if sys.platform == "win32":
            import msvcrt

            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


class StorageManager:
    """Manages hierarchical OHLCV storage with SQLite catalog and data versioning.

    Layout:
        database/{source}/{asset}/{timeframe}/data.parquet
        database/.versions/{source}/{asset}/{timeframe}/YYYYMMDD_HHMMSS.parquet
        metadata/catalog.db   (SQLite — source of truth)

    Note:
        ``catalog_path`` is kept as a public attribute for backward compatibility
        (e.g. tests that redirect the metadata directory).  The actual SQLite
        database is always placed in the *same directory* as ``catalog_path``
        under the fixed name ``catalog.db``, regardless of the JSON filename.
    """

    def __init__(self, base_dir: str = "database"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.format = ".parquet"
        # catalog_path is kept for backward-compat; the legacy JSON is no longer
        # written by this class — SQLite (catalog.db) is the sole source of truth.
        self.catalog_path = self.base_dir.parent / "metadata" / "catalog.json"
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal: SQLite helpers
    # ------------------------------------------------------------------

    @property
    def _db_path(self) -> Path:
        """SQLite DB path — always ``catalog.db`` in the same dir as catalog_path."""
        return self.catalog_path.parent / "catalog.db"

    def _get_conn(self) -> sqlite3.Connection:
        """Open a WAL-mode SQLite connection and ensure schema exists."""
        conn = sqlite3.connect(str(self._db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog (
                source      TEXT NOT NULL,
                asset       TEXT NOT NULL,
                timeframe   TEXT NOT NULL,
                rows        INTEGER,
                start_date  TEXT,
                end_date    TEXT,
                file_size_kb REAL,
                PRIMARY KEY (source, asset, timeframe)
            )
        """)
        conn.commit()
        return conn

    # ------------------------------------------------------------------
    # Internal: path helpers
    # ------------------------------------------------------------------

    def _get_path(self, source: str, asset: str, timeframe: str) -> Path:
        asset_dir = self.base_dir / source.lower() / asset.upper() / timeframe.upper()
        asset_dir.mkdir(parents=True, exist_ok=True)
        return asset_dir / f"data{self.format}"

    def _versions_dir(self, source: str, asset: str, timeframe: str) -> Path:
        return self.base_dir / ".versions" / source.lower() / asset.upper() / timeframe.upper()

    # ------------------------------------------------------------------
    # Catalog operations
    # ------------------------------------------------------------------

    def _update_catalog_entry(self, source: str, asset: str, timeframe: str):
        """Upsert or delete the catalog entry for source/asset/timeframe."""
        info = self.get_database_info(source, asset, timeframe)
        with self._get_conn() as conn:
            if info.get("status") == "Not Found":
                conn.execute(
                    "DELETE FROM catalog WHERE source=? AND asset=? AND timeframe=?",
                    (source.lower(), asset.upper(), timeframe.upper()),
                )
            else:
                conn.execute(
                    """INSERT OR REPLACE INTO catalog
                       (source, asset, timeframe, rows, start_date, end_date, file_size_kb)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        info["source"],
                        info["asset"],
                        info["timeframe"],
                        info["rows"],
                        info["start_date"],
                        info["end_date"],
                        info["file_size_kb"],
                    ),
                )

    def rebuild_catalog(self) -> dict:
        """Rebuild catalog by scanning disk (use if catalog drifts out of sync)."""
        entries = []
        for source_path in self.base_dir.iterdir():
            if not source_path.is_dir() or source_path.name.startswith("."):
                continue
            for asset_path in source_path.iterdir():
                if not asset_path.is_dir():
                    continue
                for time_path in asset_path.iterdir():
                    if not time_path.is_dir():
                        continue
                    if (time_path / f"data{self.format}").exists():
                        info = self.get_database_info(source_path.name, asset_path.name, time_path.name)
                        if info.get("status") != "Not Found":
                            entries.append(info)

        with self._get_conn() as conn:
            conn.execute("DELETE FROM catalog")
            for info in entries:
                conn.execute(
                    """INSERT INTO catalog
                       (source, asset, timeframe, rows, start_date, end_date, file_size_kb)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        info["source"],
                        info["asset"],
                        info["timeframe"],
                        info["rows"],
                        info["start_date"],
                        info["end_date"],
                        info["file_size_kb"],
                    ),
                )
        return {"status": "success", "count": len(entries)}

    def list_databases(self) -> list:
        """Return all catalog entries (fast SQLite read, no disk scan)."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM catalog ORDER BY source, asset, timeframe").fetchall()
        return [dict(row) for row in rows]

    def get_stats(self) -> dict:
        """Return aggregate statistics across all stored databases."""
        dbs = self.list_databases()
        sources: dict[str, int] = {}
        total_rows = 0
        total_kb = 0.0
        for db in dbs:
            sources[db["source"]] = sources.get(db["source"], 0) + 1
            total_rows += db.get("rows", 0)
            total_kb += db.get("file_size_kb", 0.0)
        return {
            "databases_count": len(dbs),
            "sources": sources,
            "total_rows": total_rows,
            "total_size_kb": round(total_kb, 2),
        }

    # ------------------------------------------------------------------
    # Data versioning
    # ------------------------------------------------------------------

    def _backup_version(self, file_path: Path, source: str, asset: str, timeframe: str, max_versions: int = 5):
        """Create a timestamped backup before overwriting. Best-effort (never raises)."""
        try:
            vdir = self._versions_dir(source, asset, timeframe)
            vdir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(file_path, vdir / f"{ts}.parquet")
            # Prune oldest versions beyond max_versions
            existing = sorted(vdir.glob("*.parquet"))
            for old in existing[:-max_versions]:
                old.unlink()
        except Exception:
            pass

    def list_versions(self, source: str, asset: str, timeframe: str) -> list[str]:
        """Return available version timestamps (newest last)."""
        vdir = self._versions_dir(source, asset, timeframe)
        if not vdir.exists():
            return []
        return sorted(p.stem for p in vdir.glob("*.parquet"))

    def restore_version(self, source: str, asset: str, timeframe: str, version_ts: str = None) -> bool:
        """Restore a specific version (or latest if version_ts is None)."""
        vdir = self._versions_dir(source, asset, timeframe)
        if not vdir.exists():
            return False
        backups = sorted(vdir.glob("*.parquet"))
        if not backups:
            return False
        target = (vdir / f"{version_ts}.parquet") if version_ts else backups[-1]
        if not target.exists():
            return False
        shutil.copy2(target, self._get_path(source, asset, timeframe))
        self._update_catalog_entry(source, asset, timeframe)
        return True

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    def save_data(self, df: pd.DataFrame, source: str, asset: str, timeframe: str):
        """Save data with atomic swap. Backs up previous version if file exists."""
        file_path = self._get_path(source, asset, timeframe)
        temp_path = file_path.with_suffix(f".tmp{self.format}")

        if file_path.exists():
            self._backup_version(file_path, source, asset, timeframe)

        if not isinstance(df.index, pd.DatetimeIndex):
            for col in ["datetime", "date", "time"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col])
                    df.set_index(col, inplace=True)
                    break

        df.sort_index(inplace=True)
        if df.index.tz is not None:
            df.index = df.index.tz_convert(None)

        try:
            if self.format == ".parquet":
                df.to_parquet(temp_path, engine="fastparquet")
            else:
                df.to_csv(temp_path)
            temp_path.replace(file_path)
            self._update_catalog_entry(source, asset, timeframe)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise e

    def append_data(self, df: pd.DataFrame, source: str, asset: str, timeframe: str):
        """Append new data, deduplicating by index (thread/process-safe)."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            return self.save_data(df, source, asset, timeframe)

        with _file_lock(file_path):
            existing_df = self.load_data(source, asset, timeframe)
            combined_df = pd.concat([existing_df, df])
            combined_df = combined_df[~combined_df.index.duplicated(keep="last")]
            self.save_data(combined_df, source, asset, timeframe)

    def load_data(self, source: str, asset: str, timeframe: str) -> pd.DataFrame:
        """Load data from a Parquet file."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            raise FileNotFoundError(f"Database not found: {source} -> {asset} ({timeframe})")
        if self.format == ".parquet":
            return pd.read_parquet(file_path, engine="fastparquet")
        return pd.read_csv(file_path, index_col=0, parse_dates=True)

    def delete_database(self, source: str, asset: str, timeframe: str = None) -> bool:
        """Delete a specific timeframe or all timeframes for an asset."""
        if timeframe:
            file_path = self._get_path(source, asset, timeframe)
            if file_path.exists():
                file_path.unlink()
                self._update_catalog_entry(source, asset, timeframe)
                self._cleanup_empty_dirs(self.base_dir)
                return True
        else:
            asset_dir = self.base_dir / source.lower() / asset.upper()
            if asset_dir.exists():
                shutil.rmtree(asset_dir)
                with self._get_conn() as conn:
                    conn.execute(
                        "DELETE FROM catalog WHERE source=? AND asset=?",
                        (source.lower(), asset.upper()),
                    )
                self._cleanup_empty_dirs(self.base_dir)
                return True
        return False

    def delete_all(self) -> bool:
        """Delete all databases from all sources."""
        try:
            for item in self.base_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
            with self._get_conn() as conn:
                conn.execute("DELETE FROM catalog")
            return True
        except OSError:
            return False

    def get_database_info(self, source: str, asset: str, timeframe: str) -> dict:
        """Return metadata for a specific database."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            return {"status": "Not Found"}
        df = self.load_data(source, asset, timeframe)
        return {
            "source": source.lower(),
            "asset": asset.upper(),
            "timeframe": timeframe.upper(),
            "rows": len(df),
            "start_date": str(df.index.min()),
            "end_date": str(df.index.max()),
            "file_size_kb": round(file_path.stat().st_size / 1024, 2),
        }

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def _cleanup_empty_dirs(self, directory: Path):
        """Recursively remove empty directories (skips .versions)."""
        if not directory.is_dir() or directory.name.startswith("."):
            return
        for entry in directory.iterdir():
            if entry.is_dir():
                self._cleanup_empty_dirs(entry)
        if directory != self.base_dir and not any(directory.iterdir()):
            try:
                directory.rmdir()
            except OSError:
                pass
