from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from trademachine.datamanager.infrastructure.config import settings

DATABASE_URL = settings.database_url

# O pool_pre_ping garante que conexões inativas ou mortas sejam descartadas antes do uso
engine = create_engine(DATABASE_URL, echo=settings.debug, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency para injeção de sessão do banco de dados (útil para FastAPI)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Inicializa as tabelas do DataManager."""
    from trademachine.datamanager.db.models import Base

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "SELECT create_hypertable('ohlcv_m1', 'timestamp', if_not_exists => TRUE);"
            )
        )
        conn.execute(
            text(
                "SELECT create_hypertable('economic_observations', 'timestamp', if_not_exists => TRUE);"
            )
        )
