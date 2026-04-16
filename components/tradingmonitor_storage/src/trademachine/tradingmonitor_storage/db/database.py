import logging
import shutil
import subprocess
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from trademachine.core.logger import LOGGER_NAME
from trademachine.tradingmonitor_storage.config import settings

DATABASE_URL = settings.database_url
logger = logging.getLogger(LOGGER_NAME)

engine = create_engine(DATABASE_URL, echo=settings.debug, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_DOCKER_DATABASE_HOST = "127.0.0.1"
_DOCKER_DATABASE_PORT = 5433
_DOCKER_DATABASE_NAME = "tradingmonitor"
_DOCKER_SERVICE_NAME = "timescaledb"


def _find_alembic_ini() -> Path:
    """Locate alembic.ini by walking up from this file.

    Works in both local development (deep Polylith layout) and Docker
    (alembic.ini copied to /app/alembic.ini).
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "projects" / "tradingmonitor" / "alembic.ini"
        if candidate.exists():
            return candidate
        flat_candidate = parent / "alembic.ini"
        if flat_candidate.exists():
            return flat_candidate
    raise FileNotFoundError(
        "Cannot locate alembic.ini. "
        "In Docker, ensure COPY projects/tradingmonitor/alembic.ini ./alembic.ini "
        "is present in the Dockerfile."
    )


_ALEMBIC_INI_PATH = _find_alembic_ini()
_ALEMBIC_SCRIPT_DIR = _ALEMBIC_INI_PATH.parent / "alembic"


class DatabaseUnavailableError(RuntimeError):
    """Raised when TradingMonitor cannot reach its configured database."""


class DatabaseInitializationError(RuntimeError):
    """Raised when TradingMonitor cannot finish database initialization."""


def _render_database_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001
        return url


def _docker_compose_hint(url: str) -> str:
    try:
        parsed = make_url(url)
        current_host = parsed.host or "localhost"
        current_port = parsed.port or 5432
        current_db = parsed.database or "<unknown>"
        return (
            "If you are using `projects/tradingmonitor/docker-compose.yml`, "
            f"TimescaleDB is exposed on `{_DOCKER_DATABASE_HOST}:{_DOCKER_DATABASE_PORT}` "
            f"with database `{_DOCKER_DATABASE_NAME}`. The current `DATABASE_URL` points to "
            f"`{current_host}:{current_port}/{current_db}`."
        )
    except Exception:  # noqa: BLE001
        return (
            "If you are using `projects/tradingmonitor/docker-compose.yml`, "
            f"TimescaleDB is exposed on `{_DOCKER_DATABASE_HOST}:{_DOCKER_DATABASE_PORT}` "
            f"with database `{_DOCKER_DATABASE_NAME}`."
        )


def _get_docker_compose_command() -> list[str] | None:
    docker = shutil.which("docker")
    if docker:
        return [docker, "compose"]

    docker_compose = shutil.which("docker-compose")
    if docker_compose:
        return [docker_compose]

    return None


def _docker_database_diagnosis() -> str:
    compose_cmd = _get_docker_compose_command()
    if compose_cmd is None:
        return (
            "Docker CLI not found. Install Docker or start the database manually before "
            "starting the ingestion."
        )

    try:
        result = subprocess.run(
            [
                *compose_cmd,
                "ps",
                "--services",
                "--filter",
                "status=running",
            ],
            cwd=_ALEMBIC_INI_PATH.parent,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"Could not inspect Docker status: {exc}"

    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()

    if result.returncode != 0:
        lowered = error.lower()
        if "cannot connect to the docker daemon" in lowered:
            return (
                "Docker is installed, but the Docker daemon is not running. Start Docker "
                "and then run `docker compose up -d timescaledb` in `projects/tradingmonitor`."
            )
        if "is the docker daemon running" in lowered:
            return (
                "Docker daemon is unavailable. Start Docker and then run "
                "`docker compose up -d timescaledb` in `projects/tradingmonitor`."
            )
        return (
            "Could not inspect the Docker Compose service status for "
            f"`{_DOCKER_SERVICE_NAME}`: {error or output or 'unknown error'}"
        )

    running_services = {line.strip() for line in output.splitlines() if line.strip()}
    if _DOCKER_SERVICE_NAME not in running_services:
        return (
            "The database container is not running in Docker. Start it with "
            "`docker compose up -d timescaledb` inside `projects/tradingmonitor`."
        )

    return (
        "The `timescaledb` container is running in Docker, so this looks like a database "
        "readiness issue, credentials problem, or `DATABASE_URL` mismatch."
    )


def ensure_database_connection(context: str = "TradingMonitor") -> None:
    """Fail fast with an actionable error when the configured DB is unavailable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except (OperationalError, SQLAlchemyError) as exc:
        driver_error = str(getattr(exc, "orig", exc)).strip() or exc.__class__.__name__
        message = (
            f"Cannot start {context}: database connection failed.\n"
            f"Configured `DATABASE_URL`: {_render_database_url(DATABASE_URL)}\n"
            f"Driver error: {driver_error}\n"
            f"Docker diagnosis: {_docker_database_diagnosis()}\n"
            f"{_docker_compose_hint(DATABASE_URL)}\n"
            "Set `DATABASE_URL` to something like "
            "`postgresql://postgres:<POSTGRES_PASSWORD>@127.0.0.1:5433/tradingmonitor` "
            "and run `uv run trading-monitor setup-db`."
        )
        raise DatabaseUnavailableError(message) from exc


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _build_alembic_config() -> Config:
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPT_DIR))
    return config


def _run_migrations() -> None:
    command.upgrade(_build_alembic_config(), "head")


def _ensure_hypertables() -> None:
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "SELECT create_hypertable('deals', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
                )
            )
            conn.execute(
                text(
                    "SELECT create_hypertable('equity_curve', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
                )
            )
            conn.commit()
        except SQLAlchemyError as exc:
            conn.rollback()
            logger.exception("Failed to create TradingMonitor hypertables")
            raise DatabaseInitializationError(
                "TradingMonitor database setup failed while creating hypertables."
            ) from exc


def init_db():
    ensure_database_connection("TradingMonitor database setup")
    _run_migrations()
    _ensure_hypertables()
