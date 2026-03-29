import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from trademachine.datamanager.db.models import Base

# Forçamos o uso de um banco de dados de teste
TEST_DB_URL = (
    "postgresql://postgres:password@localhost:5433/trademachine.datamanager_test"
)
os.environ["DATAMANAGER_DATABASE_URL"] = TEST_DB_URL


@pytest.fixture(scope="session")
def db_engine():
    """Cria o banco de dados de teste e as tabelas (incluindo hypertables)."""
    admin_url = "postgresql://postgres:password@localhost:5433/postgres"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM pg_database WHERE datname='trademachine.datamanager_test'"
            )
        ).scalar()
        if not exists:
            conn.execute(text('CREATE DATABASE "trademachine.datamanager_test"'))

    engine = create_engine(TEST_DB_URL)

    # Prepara o banco: apaga tudo com CASCADE para evitar erro de dependência
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
        # Apaga as visões materializadas primeiro
        timeframes = ["m5", "h1"]
        for tf in timeframes:
            conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS ohlcv_{tf} CASCADE;"))

        # Apaga as tabelas
        conn.execute(text("DROP TABLE IF EXISTS ohlcv_m1 CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS assets CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS sources CASCADE;"))
        conn.commit()

    # Cria o esquema do zero
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.execute(
            text(
                "SELECT create_hypertable('ohlcv_m1', 'timestamp', if_not_exists => TRUE);"
            )
        )

        # Cria as continuous aggregates para teste
        for tf, interval in [("m5", "5 minutes"), ("h1", "1 hour")]:
            query = f"""
                CREATE MATERIALIZED VIEW ohlcv_{tf}
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket('{interval}', timestamp) AS timestamp,
                    asset_id,
                    first(open, timestamp) AS open,
                    max(high) AS high,
                    min(low) AS low,
                    last(close, timestamp) AS close,
                    sum(volume) AS volume
                FROM ohlcv_m1
                GROUP BY time_bucket('{interval}', timestamp), asset_id
                WITH NO DATA;
            """  # noqa: S608
            conn.execute(text(query))

    yield engine


@pytest.fixture
def db_session(db_engine):
    """Retorna uma sessão limpa para cada teste."""
    Session = sessionmaker(bind=db_engine)
    session = Session()

    # Limpa os dados, mas mantém a estrutura (tabelas e visões)
    session.execute(text("TRUNCATE TABLE ohlcv_m1, assets, sources CASCADE;"))
    session.commit()

    yield session
    session.close()
