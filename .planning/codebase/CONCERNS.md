# Codebase Concerns

**Analysis Date:** 2026-03-28

---

## Tech Debt

### Active Mid-Migration Architectural State

**Severity: High**

- Issue: Codebase is frozen mid-migration on two axes simultaneously. The DataManager component migrated storage from Parquet/SQLite to TimescaleDB. The TradingMonitor component deleted its `trading_monitor_ingestion` base without committing a replacement. Multiple untracked new modules exist alongside stale deleted references — none of it committed.
- Files:
  - Deleted base: `bases/trading_monitor_ingestion/` (pyproject.toml, `__init__.py`, test files — all tracked deletions, uncommitted)
  - New untracked: `components/tradingmonitor/src/trademachine/tradingmonitor/ingestion/cache.py`
  - New untracked: `components/tradingmonitor/src/trademachine/tradingmonitor/db/repository.py`
  - New untracked: `components/tradingmonitor/src/trademachine/tradingmonitor/facade.py`
  - New untracked: `components/tradingmonitor/src/trademachine/tradingmonitor/api_schemas.py`
  - New untracked: `components/datamanager/src/trademachine/datamanager/db/database.py`
  - New untracked: `components/datamanager/src/trademachine/datamanager/db/models.py`
- Impact: New code written against old interface contracts may be immediately obsolete. Polylith workspace may report inconsistency. CI operates on committed state so untracked files are invisible to all automated quality gates (`poly check`, `lint-imports`, `xenon`, `vulture`).
- Fix approach: Commit or formally discard all untracked modules. Ensure the replacement ingestion base is created and wired into a project pyproject.toml before merging. Run `uv tool run --from polylith-cli poly check` and `uv run lint-imports` post-commit.

---

### Duplicate In-Memory Cache State

**Severity: High**

- Issue: Two modules independently define and manage the same five cache objects (`EXISTING_STRATEGIES`, `EXISTING_ACCOUNTS`, `EXISTING_SYMBOLS`, `_active_backtests`, `_deal_counters`) with their own separate threading locks. `cache.py` is the canonical new home, but `tcp_server.py` still declares its own copies via a `ServerState` dataclass with backward-compatible module-level aliases. The test conftest clears state from `tcp_server` only, not from `cache.py`.
- Files:
  - `components/tradingmonitor/src/trademachine/tradingmonitor/ingestion/cache.py` lines 12–33 — defines canonical sets/dicts with 5 independent threading locks
  - `components/tradingmonitor/src/trademachine/tradingmonitor/ingestion/tcp_server.py` lines 83–119 — redefines same state in `ServerState` dataclass; module-level aliases (`EXISTING_STRATEGIES = _state.existing_strategies`) point to the dataclass fields, not to `cache.py`
  - `components/tradingmonitor/test/trademachine/tradingmonitor/conftest.py` lines 103–115 — clears only `tcp_server` attributes; does not touch `cache.py`
- Impact: Any consumer importing `invalidate_cache` from `cache.py` operates on a different object than the live TCP server uses. Cache invalidation triggered from the dashboard or API layer (e.g., after deleting a strategy) will have no effect on the running ingestion loop.
- Fix approach: Remove the duplicate state from `tcp_server.py`. Import and use `EXISTING_STRATEGIES`, `EXISTING_ACCOUNTS`, `EXISTING_SYMBOLS`, `_active_backtests`, `_deal_counters`, and their locks from `cache.py`. Update the test conftest `clear_ingestion_caches` fixture to clear via `cache.py`.

---

### BacktestEngine Logic in Wrong Polylith Layer

**Severity: Medium**

- Issue: The `backtestengine` component namespace is effectively empty. The component `__init__.py` is one blank line. All substantive logic — `DataHandler`, `MACDStrategy`, `MACDConfig`, the NautilusTrader engine setup, and `main()` (~256 lines) — lives inside the base entry point. This violates the Polylith rule that business logic must reside in components, not bases.
- Files:
  - `components/backtestengine/src/trademachine/backtestengine/__init__.py` — 1 blank line, nothing exported
  - `bases/backtest_engine_cli/src/trademachine/backtest_engine_cli/main.py` — contains `DataHandler`, `MACDStrategy`, `MACDConfig`, `main()`, imports `DataManagerClient` directly
  - `components/backtestengine/test/trademachine/backtestengine/test_core.py` — stub: `assert core is not None`
- Impact: The backtest strategy cannot be reused from any other base. The test suite provides zero real backtest coverage. `lint-imports` does not flag this because no base imports from another base — but the architectural inversion is present.
- Fix approach: Move `DataHandler`, `MACDStrategy`, `MACDConfig` into `components/backtestengine/`. Keep `main.py` in the base as a thin entry point calling `from trademachine.backtestengine import run_backtest`. Write real component-level tests in isolation using a mocked `DataManagerClient`.

---

### Stale DataManager Documentation

**Severity: Medium**

- Issue: `projects/datamanager/CLAUDE.md` describes a Parquet/SQLite storage layout that no longer exists. The documented storage path (`database/{source}/{ASSET}/{TIMEFRAME}/data.parquet`), SQLite catalog (`metadata/catalog.db`), and concepts (`file_size_kb`, `rebuild_catalog`, `DataProcessor`) are all obsolete. The actual implementation uses TimescaleDB hypertables with continuous aggregate views. `StorageManager.__init__` accepts a `base_dir` argument that is a no-op, kept only for backward compatibility.
- Files:
  - `projects/datamanager/CLAUDE.md` — Module Responsibilities section documents `storage.py` as "Parquet I/O + SQLite catalog"; Storage Layout section shows Parquet directory paths; Data Flow section shows `StorageManager.save_data() → Parquet on disk`
  - `components/datamanager/src/trademachine/datamanager/db/storage.py` line 36 — `__init__` body is `pass`; uses `SessionLocal`, `TF_VIEW_MAPPING`, continuous aggregate views
- Impact: Any developer or Claude instance reading the project docs will implement against a storage API that does not exist. The `base_dir` parameter creates false confidence that filesystem paths are still meaningful.
- Fix approach: Rewrite the Architecture, Module Responsibilities, and Data Flow sections of `projects/datamanager/CLAUDE.md` to reflect the TimescaleDB layout. Remove all references to Parquet paths, SQLite catalog, `rebuild_catalog`, `DataProcessor`, and `file_size_kb`.

---

## Known Bugs

### Broken Migration Script NameError

**Severity: Medium**

- Symptoms: Running `projects/datamanager/scripts/migrate_parquet_to_timescale.py` crashes immediately with `NameError: name 'base_path_absolute' is not defined`.
- Files:
  - `projects/datamanager/scripts/migrate_parquet_to_timescale.py` line 22: `base_path = Path(base_path_absolute)` — `base_path_absolute` is only defined at line 70 inside `if __name__ == "__main__":`, never passed into the function or defined at function scope
- Trigger: Any attempt to run the Parquet-to-TimescaleDB migration on a pre-existing deployment
- Workaround: None — the script crashes before performing any work. Fix by changing line 22 to `base_path = Path(base_dir)` to use the existing function parameter.

---

## Security Considerations

### Default `0.0.0.0` API Binding with Optional Auth

**Severity: Medium**

- Risk: `components/datamanager/src/trademachine/datamanager/core/config.py` line 12 defaults `host` to `"0.0.0.0"`, binding the DataManager REST API to all network interfaces. The `api_key` defaults to empty string. While `is_api_key_configured` returns `False` when the key is empty, there is no enforcement that prevents the server from starting unauthenticated and accessible on all interfaces.
- Files:
  - `components/datamanager/src/trademachine/datamanager/core/config.py` line 12: `host: str = "0.0.0.0"  # noqa: S104`
  - The `# noqa: S104` suppression permanently silences the Ruff `S104` (binding to all interfaces) lint on this line
- Current mitigation: `is_api_key_configured` property exists; router middleware checks for an API key on each request
- Recommendations: Change default `host` to `"127.0.0.1"`. Add a startup-time log warning when `api_key` is empty and `host` is `"0.0.0.0"`. Remove `# noqa: S104` after tightening the default.

---

## Performance Bottlenecks

### Brute-Force Optimizer Memory Ceiling

**Severity: Medium**

- Problem: The portfolio optimizer uses fully vectorized NumPy batch computation. Code comments at lines 24–29 document the known memory budget: `MATRIX_ALGEBRA_BATCH_SIZE = 1000` with ~100 strategies × 10,000 timestamps consumes ~800 MB per worker process. With `multiprocessing`, each worker process duplicates the full returns matrix. There is no dynamic memory guard or pre-flight check.
- Files:
  - `components/portifoliomaster/src/trademachine/portifoliomaster/services/optimization.py` lines 24–29 (memory budget comments)
  - `MATRIX_ALGEBRA_BATCH_SIZE = 1000`, `CORRELATION_FILTER_BATCH_SIZE = 10000` defined at module level
  - Multi-process path at line 451+
- Cause: Exhaustive combination enumeration via `itertools.combinations`; matrix operations hold all combinations for a batch in memory simultaneously; `multiprocessing.Pool` forks copies of the full data
- Improvement path: Add a pre-flight memory estimate before starting multiprocessing (using `psutil.virtual_memory()`). Log a warning or abort if estimated peak usage exceeds ~80% of available RAM. Reduce `MATRIX_ALGEBRA_BATCH_SIZE` dynamically based on available memory.

### Per-Call DB Sessions in Repository

**Severity: Medium**

- Problem: Every public method in `components/tradingmonitor/src/trademachine/tradingmonitor/db/repository.py` opens a new `SessionLocal()`, executes its query, then closes it in a `finally` block. With dashboard polling every few seconds, each page load creates and destroys several sessions across multiple repository calls.
- Files:
  - `components/tradingmonitor/src/trademachine/tradingmonitor/db/repository.py` — `AccountRepository.get_by_id`, `get_all`, `create_or_update`, `update_balance`, `delete` (and equivalent methods across `StrategyRepository`, `DealRepository`, etc.) all follow `db = SessionLocal(); try: ...; finally: db.close()`
- Cause: Repository instances carry no state; session lifecycle is managed inside each method rather than injected
- Improvement path: Refactor repository methods to accept an optional `Session` parameter, or adopt FastAPI `Depends(get_db)` for request-scoped sessions. This also enables transactional coordination across multiple repository calls within a single HTTP request.

---

## Fragile Areas

### SQLite Shims for PostgreSQL Types in Tests

- Files:
  - `components/tradingmonitor/test/trademachine/tradingmonitor/conftest.py` lines 42–96
  - Three monkey-patches: `_patch_sqlite_jsonb()`, `_patch_sqlite_biginteger()`, `_patch_sqlite_composite_pk()`
- Why fragile: The patches mutate SQLAlchemy's `SQLiteTypeCompiler` globally for the test session. `_patch_sqlite_composite_pk()` directly modifies `Base.metadata.tables` — a class-level singleton — by removing and re-adding `PrimaryKeyConstraint` objects. If SQLAlchemy's internal compiler API changes, these patches silently fail or raise. Any new PostgreSQL-specific column type added to ORM models will require a corresponding new shim.
- Safe modification: Any change to `Base.metadata` ORM models must be validated against all three shims. When adding new PostgreSQL-specific types (e.g., `ARRAY`, `TSVECTOR`), a corresponding SQLite shim may be required or the test will fail at table creation time.
- Test coverage gap: TimescaleDB-specific behaviors (`ON CONFLICT DO NOTHING` semantics, `pg_insert` upserts with `on_conflict_do_update`, hypertable chunk routing) are not exercised by the SQLite path and require the `pg_engine` E2E fixture.

---

## Test Coverage Gaps

### CLI Bases: Only Stub Tests

- What's not tested: Interactive CLI commands, argument parsing, error handling for bad inputs, `--help` output, `CliRunner` integration
- Files:
  - `bases/datamanager_cli/test/trademachine/datamanager_cli/test_core.py` — 5 lines: `assert core is not None`
  - `bases/datamanager_api/test/trademachine/datamanager_api/test_core.py` — same stub pattern
- Risk: Regressions in CLI command routing, argument validation, and interactive shell behavior are undetected by CI
- Priority: Medium

### BacktestEngine Component: No Real Tests

- What's not tested: `DataHandler` OHLCV normalization, `MACDStrategy` signal logic, engine configuration, `while True: time.sleep(5)` polling loop in `sync_server`
- Files: `components/backtestengine/test/trademachine/backtestengine/test_core.py` — 5 lines: `assert core is not None`
- Risk: The blocking poll loop (`bases/backtest_engine_cli/src/trademachine/backtest_engine_cli/main.py` lines 112–135) has no timeout test, no graceful-exit test, and no mock for the DataManager client. A hung DataManager will block the process indefinitely with no test to catch the regression.
- Priority: Medium

### Concrete DataManager Fetchers: No Integration Tests

- What's not tested: `ccxt.py`, `openbb.py`, `dukascopy.py` error paths (network timeout, empty response, malformed data), column normalization behavior on real SDK output
- Files:
  - `components/datamanager/test/trademachine/datamanager/test_fetchers.py` — tests only `BaseFetcher` with a `ConcreteFetcher` stub; no production fetcher is instantiated
- Risk: Any SDK API change (openbb version bump, ccxt symbol format change) will not be caught until runtime
- Priority: Medium

### Dashboard Routes Post-Serializer Deletion

- What's not tested: Route behavior after `serializers.py` was deleted; routes may now import from `repository.py` and `api_schemas.py` without test validation that the new imports are correct
- Files:
  - `bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/serializers.py` — deleted
  - `bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/routes.py` — modified
  - `components/tradingmonitor/test/trademachine/tradingmonitor/service/test_routes.py` and `test_routes_extended.py` — may reference deleted serializer mock targets
- Risk: Silent import errors or incorrect route responses after the serializer deletion; tests may be passing against a stale code path
- Priority: Medium

---

## Consistent `portifolio` Typo

**Severity: Low**

- Issue: "portfolio" is consistently misspelled as "portifolio" across 25+ Python files, directory names, Python package names, import paths, CLI commands, and pyproject.toml entry points. The misspelling is a load-bearing identifier present in the Polylith namespace.
- Files (representative — 25+ total):
  - `bases/portifolio_master_cli/` — directory and Python package name `trademachine.portifolio_master_cli`
  - `components/portifoliomaster/` — directory and Python package name `trademachine.portifoliomaster`
  - `components/portifoliomaster/src/trademachine/portifoliomaster/services/portfolio.py`
  - `components/portifoliomaster/src/trademachine/portifoliomaster/services/optimization.py`
  - All test files under `components/portifoliomaster/test/`
- Impact: Cosmetically incorrect but internally consistent. Any partial rename (e.g., fixing only some files) will produce broken imports. The risk of introducing a regression during rename is higher than the benefit for a single-developer personal project.
- Fix approach: Either accept permanently as an internal convention, or rename atomically in a single commit: (1) rename directories, (2) update all `pyproject.toml` `[tool.polylith.bricks]` entries, (3) global find-and-replace `portifolio` → `portfolio` scoped to project source, (4) run `poly check` + full test suite before merging.

---

## No TODO/FIXME/HACK/XXX Inline Markers Found

A codebase-wide grep for `TODO`, `FIXME`, `HACK`, `XXX` in `components/` and `bases/` returned no matches. The single developer uses git status and external planning files rather than inline code markers.

---

*Concerns audit: 2026-03-28*
