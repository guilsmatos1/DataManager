import sys
import time
from pathlib import Path

import pandas as pd
from nautilus_trader.backtest.config import BacktestEngineConfig

# Nautilus Imports
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import LoggingConfig
from nautilus_trader.indicators import MovingAverageConvergenceDivergence
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import (
    AccountType,
    AggregationSource,
    BarAggregation,
    OmsType,
    OrderSide,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

# DataManager path
_DM_PATH = Path(__file__).parent.parent / "DataManager"
sys.path.insert(0, str(_DM_PATH))
from client import DataManagerClient

# Constants
ASSET = "USA30"
START_DATE = "2020-01-01"
END_DATE = "2026-01-01"

# DataHandler
class DataHandler:
    def __init__(self, catalog_path: Path, dm_url: str, dm_api_key: str):
        self.catalog = ParquetDataCatalog(str(catalog_path))
        self.dm = DataManagerClient(dm_url, api_key=dm_api_key)

    def _normalize_ohlc(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize DataFrame from DataManager for NautilusTrader."""
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        needed = ["open", "high", "low", "close", "volume"]
        df = df[needed]
        for col in needed:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(inplace=True)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df.sort_index(inplace=True)
        # Sanitization
        df['high'] = df[['open', 'high', 'low', 'close']].max(axis=1)
        df['low'] = df[['open', 'high', 'low', 'close']].min(axis=1)
        return df

    def get_target_range(self, start_str: str, end_str: str):
        """Calculates the target end date (capped at now) for data requests."""
        req_start = pd.Timestamp(start_str, tz='UTC')
        now_utc = pd.Timestamp.now(tz='UTC')
        req_end = min(pd.Timestamp(end_str, tz='UTC'), now_utc)
        return req_start, req_end

    def check_local_completeness(self, bar_type: BarType, req_start: pd.Timestamp, req_end: pd.Timestamp):
        """Checks if the local catalog contains the full requested data range."""
        if not self.catalog.instruments():
            return False

        m1_bars = self.catalog.bars(bar_types=[str(bar_type)])
        if not m1_bars:
            return False

        first_ts = pd.Timestamp(m1_bars[0].ts_event, unit='ns', tz='UTC')
        last_ts = pd.Timestamp(m1_bars[-1].ts_event, unit='ns', tz='UTC')

        if first_ts > req_start or last_ts < req_end:
            print(f"Local incomplete: {first_ts} to {last_ts}. Needed: {req_start} to {req_end}")
            return False
        return True

    def sync_server(self, source: str, asset: str, req_start: pd.Timestamp, req_end: pd.Timestamp):
        """Ensures the DataManager server has the required data."""
        try:
            info = self.dm.info(source, asset, "M1")
            srv_start = pd.Timestamp(info['start_date'], tz='UTC')
            srv_end = pd.Timestamp(info['end_date'], tz='UTC')

            if srv_start > req_start or srv_end < req_end:
                print(f"Server incomplete ({srv_start} to {srv_end}). Updating...")
                self.dm.download(source, asset, req_start.strftime("%Y-%m-%d"), req_end.strftime("%Y-%m-%d"))
                self.dm.update(source, asset, "M1")

                while True:
                    time.sleep(5)
                    info = self.dm.info(source, asset, "M1")
                    if pd.Timestamp(info['end_date'], tz='UTC') >= req_end:
                        break
                    print(f"  Wait server update... (End: {info['end_date']})")
        except Exception as e:
            print(f"Server missing asset/data: {e}. Downloading...")
            self.dm.download(source, asset, req_start.strftime("%Y-%m-%d"), req_end.strftime("%Y-%m-%d"))
            while True:
                try:
                    time.sleep(5)
                    info = self.dm.info(source, asset, "M1")
                    if info.get("status") != "Not Found":
                        if pd.Timestamp(info['end_date'], tz='UTC') >= req_end:
                            break
                    print("  Wait server initial download...")
                except:
                    print("  Wait server init...")

    def update_local(self, source: str, asset: str, m1_type: BarType):
        """Downloads data from DataManager server and writes it to the local catalog."""
        print(f"Downloading {asset} via {source} to local catalog...")
        df_raw = self.dm.get_data(source, asset, "M1")
        df = self._normalize_ohlc(df_raw)

        instrument = TestInstrumentProvider.equity(symbol=asset, venue="SIM")
        wrangler = BarDataWrangler(bar_type=m1_type, instrument=instrument)
        bars = wrangler.process(df)

        self.catalog.write_data([instrument])
        self.catalog.write_data(bars)
        print(f"Catalog updated with {len(bars):,} bars.")

    def get_bars(self, bar_type, start, end):
        return self.catalog.bars(bar_types=[str(bar_type)], start=start, end=end)


class MACDConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    h1_bar_type: BarType


class MACDStrategy(Strategy):
    def __init__(self, config: MACDConfig):
        super().__init__(config=config)
        self.macd = MovingAverageConvergenceDivergence(12, 26, PriceType.LAST)
        self.last_above = None
        self.h1_received = 0
        self.trades = 0

    def on_start(self):
        self.register_indicator_for_bars(self.config.h1_bar_type, self.macd)
        self.subscribe_bars(self.config.h1_bar_type)

    def on_bar(self, bar: Bar):
        if str(bar.bar_type) == str(self.config.h1_bar_type).split('@')[0]:
            self.h1_received += 1
            if self.macd.initialized:
                curr_above = self.macd.value > 0
                if self.last_above is not None and curr_above != self.last_above:
                    side = OrderSide.BUY if curr_above else OrderSide.SELL
                    if not self.cache.positions_open(instrument_id=self.config.instrument_id):
                        self.submit_order(self.order_factory.market(
                            instrument_id=self.config.instrument_id,
                            order_side=side,
                            quantity=Quantity.from_int(1)
                        ))
                        self.trades += 1
                self.last_above = curr_above

    def on_stop(self):
        print(f"\n[STRATEGY SUMMARY] {self.config.instrument_id}")
        print(f"H1 Bars: {self.h1_received:,} | Trades: {self.trades} | MACD Init: {self.macd.initialized}")

#----------------#
def main():
    data = DataHandler(
        catalog_path=Path(__file__).parent / "catalog",
        dm_url="http://10.10.10.240:8686",
        dm_api_key="K91DS441s31"
    )

    inst_id = InstrumentId(Symbol(ASSET), Venue("SIM"))
    m1_type = BarType(inst_id, BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST), AggregationSource.EXTERNAL)
    h1_type = BarType.from_str(f"{inst_id}-1-HOUR-LAST-INTERNAL@1-MINUTE-EXTERNAL")

    req_start, req_end = data.get_target_range(START_DATE, END_DATE)

    if not data.check_local_completeness(m1_type, req_start, req_end):
        print(f"Syncing {ASSET} data...")
        data.sync_server("DUKASCOPY", ASSET, req_start, req_end)
        data.update_local("DUKASCOPY", ASSET, m1_type)

    instrument = data.catalog.instruments()[0]
    m1_bars = data.get_bars(m1_type, START_DATE, END_DATE)
    print(f"Loaded {len(m1_bars):,} M1 bars ({START_DATE} to {END_DATE})")

    engine = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )
    engine.add_instrument(instrument)
    engine.add_data(m1_bars)

    strategy = MACDStrategy(config=MACDConfig(instrument_id=instrument.id, h1_bar_type=h1_type))
    engine.add_strategy(strategy)

    print("Running Backtest...")
    engine.run()

    fills = engine.trader.generate_order_fills_report()
    print(f"Total Order Fills: {len(fills)}")
    #----------------#
    engine.dispose()

if __name__ == "__main__":
    main()
