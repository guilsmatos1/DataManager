from datetime import datetime

from sqlalchemy import (
    JSON,
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


class EconomicSeries(Base):
    __tablename__ = "economic_series"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "series_id", name="uq_economic_series_source_series"
        ),
        Index("ix_economic_series_source_series", "source_id", "series_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    series_id: Mapped[str] = mapped_column(String, nullable=False)

    title: Mapped[str | None] = mapped_column(String, nullable=True)
    native_frequency: Mapped[str | None] = mapped_column(String, nullable=True)
    units: Mapped[str | None] = mapped_column(String, nullable=True)
    seasonal_adjustment: Mapped[str | None] = mapped_column(String, nullable=True)
    observation_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observation_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    source: Mapped["Source"] = relationship("Source")


class EconomicObservation(Base):
    __tablename__ = "economic_observations"
    __table_args__ = (
        Index("ix_economic_observations_series_ref_id", "series_ref_id"),
        UniqueConstraint(
            "timestamp", "series_ref_id", name="uq_economic_observation_timestamp"
        ),
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    series_ref_id: Mapped[int] = mapped_column(
        ForeignKey("economic_series.id"), primary_key=True, nullable=False
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
