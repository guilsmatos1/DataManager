# Coding Conventions

**Analysis Date:** 2026-03-28

## Formatting & Style Tooling

**Formatter:** Ruff (v0.9.9 in pre-commit)
**Linter:** Ruff lint
**Config location:** `pyproject.toml` under `[tool.ruff]`

```toml
[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "W", "B", "UP", "S"]
ignore = ["E501", "S101", "S108", "S603", "B904", "B008", "S110", "B018", "S311"]
```

**Enabled rule sets:**
- `E` / `W` — pycodestyle errors and warnings
- `F` — Pyflakes (undefined names, unused imports)
- `I` — isort (import ordering)
- `B` — flake8-bugbear (common bug patterns)
- `UP` — pyupgrade (modern Python syntax)
- `S` — flake8-bandit (security checks, with selective ignores)

**Ignored rules of note:**
- `E501` — line length not enforced beyond formatter
- `S101` — `assert` in tests allowed
- `B904` — exception chaining not required in `except` blocks

**Run linting and formatting:**
```bash
uv run ruff check --fix . && uv run ruff format .
```

## Naming Patterns

**Files:**
- `snake_case.py` for all Python source files (e.g., `tcp_server.py`, `storage.py`, `base_fetcher.py`)
- Test files: `test_<subject>.py` (e.g., `test_calculator.py`, `test_storage.py`)
- Config files follow tool conventions (`pyproject.toml`, `.importlinter`, `.pre-commit-config.yaml`)

**Directories:**
- `snake_case` throughout (`components/`, `tradingmonitor/`, `db/`, `ingestion/`)

**Classes:**
- `PascalCase` (e.g., `DataManager`, `StorageManager`, `BaseFetcher`, `CcxtFetcher`)
- Abstract base classes prefixed conventionally with `Base` (e.g., `BaseFetcher`, `BaseMetric`)
- Pydantic settings: `Settings` class in `config.py`

**Functions and methods:**
- `snake_case` (e.g., `fetch_data`, `get_or_create_source`, `calculate_metrics_from_df`)
- Private helpers prefixed with `_` (e.g., `_get_fetcher`, `_normalize_timezone`, `_patch_sqlite_jsonb`)
- Factory helpers in conftest use `_make` prefix (e.g., `_make_deals`, `_make_equity`)

**Variables:**
- `snake_case` for all locals and instance attributes
- Module-level constants in `UPPER_SNAKE_CASE` (e.g., `SPIKE_THRESHOLD`, `LOGGER_NAME`, `DRIFT_CHECK_INTERVAL`, `EXISTING_STRATEGIES`)
- Private module-level caches/state prefixed with `_` (e.g., `_plugin_instances`, `_json_formatter`)

**Type aliases and enums:**
- Enums use `PascalCase` class name, `UPPER_CASE` members (e.g., `DealType.BUY`, `DealType.SELL`)

## Import Organization

Ruff `I` rules enforce isort-compatible ordering. The observed pattern:

```python
# 1. Future imports (when needed)
from __future__ import annotations

# 2. Standard library
import json
import logging
from datetime import UTC, datetime

# 3. Third-party packages
import pandas as pd
from sqlalchemy.orm import Session
from tenacity import retry

# 4. Internal (trademachine namespace)
from trademachine.core.logger import LOGGER_NAME
from trademachine.datamanager.db.storage import StorageManager
```

**Relative imports** are used within the same package only when a module is in the same directory (e.g., `from .base import BaseFetcher` inside `fetchers/`). Cross-component imports always use the full `trademachine.<component>` path.

**`from __future__ import annotations`** is used in modules with forward references (TYPE_CHECKING blocks, self-referential type hints). It is not applied universally — only where needed.

**TYPE_CHECKING guard:**
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    pass  # only forward-reference type imports go here
```

## Type Annotations

Python 3.12+ type syntax is used throughout (enforced by `UP` rules):

```python
# Modern union syntax (not Optional or Union)
def search(self, query: str | None = None) -> pd.DataFrame: ...

# Built-in generics (not typing.List, typing.Dict)
def list_databases(self) -> list: ...
_fetchers: dict[str, BaseFetcher] = {}

# Mapped columns in SQLAlchemy (typed ORM)
id: Mapped[str] = mapped_column(String, primary_key=True)
name: Mapped[str | None] = mapped_column(String)
```

`mypy` is configured with strict options in `pyproject.toml`:
```toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_ignores = true
check_untyped_defs = true
no_implicit_optional = true
ignore_missing_imports = true
```

Type stubs are installed as dev dependencies (`types-python-dateutil`, `types-requests`).

## Docstring and Comment Conventions

**Module-level docstrings:** Used to describe the module's responsibility and list what is covered/delegated.
```python
"""TCP ingestion server for MT5 terminals.

Handles socket communication, client management, message routing, and persistence.
This module orchestrates the ingestion pipeline by delegating pure DB operations
to processors.py and drift checking to drift_checker.py.
"""
```

**Class docstrings:** Short one-liner or paragraph, no parameter documentation style enforced.
```python
class StorageManager:
    """Manages OHLCV storage using TimescaleDB (PostgreSQL) with Continuous Aggregates.

    Layout:
        - Relational tables: sources, assets (metadata catalog)
        - Hypertable: ohlcv_m1 (primary 1-minute data)
        - Continuous Aggregates: ohlcv_m5, ohlcv_h1, etc. (derived timeframes)
    """
```

**Method docstrings:** Short description only, no formal Args/Returns/Raises sections. Inline comments preferred over detailed docstrings for logic explanation.
```python
def _normalize_timezone(self, df: pd.DataFrame) -> pd.DataFrame:
    """Strip timezone from index if present — ensures timezone-naive datetimes."""
```

**Inline comments:** Used liberally to explain non-obvious logic, thresholds, and DB quirks. Section dividers with `# ── Section Name ───` are used to visually group code blocks within long files (common in `conftest.py` and `tcp_server.py`).

**Exceptions docstring style:** Module-level docstring with a title block:
```python
"""
Exceptions Module
=================
Custom exception hierarchy for the PortfolioMaster system.
"""
```

## Error Handling Patterns

**Domain-specific exception hierarchy:** Each component defines a base exception class and specialized subclasses in `core/exceptions.py`:
```python
class PortfolioMasterError(Exception):
    """Base class for all exceptions in PortfolioMaster."""
    pass

class ValidationError(PortfolioMasterError): ...
class ParserError(PortfolioMasterError): ...
class DataError(PortfolioMasterError): ...
```

**Raise with context:** `ValueError` with descriptive messages for invalid inputs; custom exceptions for domain errors.
```python
raise ValueError(
    f"Data source not supported: {source_name}. Available: {list(self._fetchers.keys())}"
)
```

**Retry with tenacity:** Used for network-level operations (fetchers) with exponential backoff and jitter:
```python
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

@retry(
    retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
    reraise=True,
)
```

**Graceful degradation with logging:** Non-fatal errors (e.g., failed fetcher initialization) are caught, logged, and skipped:
```python
try:
    instance = fetcher_class()
    self._fetchers[instance.source_name.upper()] = instance
except Exception as e:
    logger.warning(f"Failed to initialize fetcher {fetcher_class.__name__}: {e}")
```

**`B904` is ignored** — exception chaining (`raise X from e`) is not required in re-raise blocks, though explicit `from exc` is used in `ImportError` guards.

## Logging Patterns

**Shared logger name constant:** `LOGGER_NAME = "TradeMachine"` in `components/core/src/trademachine/core/logger.py`.

**Setup via `setup_logger()`:** The `core` component provides `setup_logger()` for configuring the global logger with dual output:
- Console: `%(asctime)s [%(levelname)s] %(message)s` (HH:MM:SS format)
- File: structured JSON (`_JSONFormatter`), one entry per line

**Module-level logger acquisition pattern:**
```python
import logging
from trademachine.core.logger import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)
```

**TCP server uses a dedicated JSON logger** (`TCPServer` logger with `python-json-logger`), separate from the shared `TradeMachine` logger. This is an exception to the general pattern.

**Log levels in use:**
- `logger.info()` — progress, data download status
- `logger.warning()` — duplicate data, failed fetcher init
- `logger.debug()` — per-chunk details, verbose diagnostics

**Suppressing noisy external libraries:**
```python
logging.getLogger("dukascopy_python").setLevel(logging.WARNING)
logging.getLogger("DUKASCRIPT").setLevel(logging.WARNING)
```

## Configuration Pattern

**Pydantic Settings** with `.env` file loading. One `Settings` class per component in `config.py`, cached with `@lru_cache`:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    api_key: str = Field(alias="API_KEY")
    database_url: str = Field(default="...", alias="DATABASE_URL")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()  # module-level backward-compatible instance
```

`Field(alias="ENV_VAR_NAME")` maps `UPPER_SNAKE_CASE` env vars to `lower_snake_case` Python attributes.

## Module `__all__` Usage

Used selectively for re-export and backward compatibility in public API surfaces:
```python
__all__ = [
    "get_strategy_deals",
    "calculate_metrics_from_df",
    ...
]
```

## Pre-commit Hooks and Enforcement

All hooks run on every commit via `.pre-commit-config.yaml`. Run manually with:
```bash
uv run pre-commit run --all-files
```

| Hook | Tool | What it enforces |
|------|------|-----------------|
| `trailing-whitespace` | pre-commit-hooks | No trailing whitespace |
| `end-of-file-fixer` | pre-commit-hooks | Files end with newline |
| `check-yaml` | pre-commit-hooks | Valid YAML syntax |
| `check-added-large-files` | pre-commit-hooks | No files >2000 KB |
| `check-ast` | pre-commit-hooks | Valid Python AST |
| `ruff` | astral-sh/ruff | Lint + auto-fix |
| `ruff-format` | astral-sh/ruff | Auto-format |
| `gitleaks` | gitleaks | No secrets committed |
| `polylith-check` | polylith-cli | Polylith workspace integrity |
| `import-linter` | import-linter | Layer isolation contracts |
| `xenon` | xenon | Complexity: `--max-absolute E --max-modules D --max-average B` |
| `vulture` | vulture | Dead code ≥80% confidence |

**Layer isolation contracts** (`.importlinter`) enforce that no component (`trademachine.datamanager`, `tradingmonitor`, `portifoliomaster`, `backtestengine`, `core`, `mt5`) imports from any base (entry point).

**Complexity thresholds (xenon):**
- `--max-absolute E` — no single function may exceed grade E cyclomatic complexity
- `--max-modules D` — module average must be ≤ D
- `--max-average B` — project average must be ≤ B

**Dead code detection (vulture):** `vulture_whitelist.py` at project root whitelists legitimate false positives. Minimum confidence threshold: 80%.

---

*Convention analysis: 2026-03-28*
