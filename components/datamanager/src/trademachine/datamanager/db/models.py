from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)

    assets: Mapped[list["Asset"]] = relationship(
        "Asset", back_populates="source", cascade="all, delete-orphan"
    )


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("ticker", "source_id", name="uq_asset_ticker_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, index=True, nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)

    min_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    max_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source: Mapped["Source"] = relationship("Source", back_populates="assets")
    # Nota: a relação com OHLCV não é estrita aqui porque ohlcv_m1 será uma hypertable particionada no TimescaleDB.


class OhlcvM1(Base):
    __tablename__ = "ohlcv_m1"

    # TimescaleDB hypertables precisam do timestamp como parte da primary key
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"), primary_key=True, nullable=False
    )

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
