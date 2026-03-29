from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from trademachine.tradingmonitor.config import settings
from trademachine.tradingmonitor.db.models import Base

DATABASE_URL = settings.database_url

engine = create_engine(DATABASE_URL, echo=settings.debug, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "SELECT create_hypertable('deals', 'timestamp', if_not_exists => TRUE);"
                )
            )
            conn.execute(
                text(
                    "SELECT create_hypertable('equity_curve', 'timestamp', if_not_exists => TRUE);"
                )
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Hypertable creation error: {e}")
    # Idempotent column migrations for existing tables
    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE strategies ADD COLUMN IF NOT EXISTS"
                " max_allowed_drawdown NUMERIC(6, 2);"
            )
        )
        conn.commit()
