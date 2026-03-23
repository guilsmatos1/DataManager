Overview

This quickstart tutorial shows you how to get up and running with NautilusTrader backtesting using FX data. To support this, we provide pre-loaded test data in the standard Nautilus persistence format (Parquet).
Prerequisites

    Python 3.12+ installed.
    NautilusTrader latest release installed (uv pip install nautilus_trader).
    JupyterLab or similar installed (uv pip install jupyterlab).

1. Get sample data

To save time, we have prepared sample data in the Nautilus format for use with this example. Run the next cell to download and set up the data (this takes 1-2 minutes).

For further details on how to load data into Nautilus, see the Loading External Data guide.

import os
import urllib.request
from pathlib import Path

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import QuoteTickDataWrangler
from nautilus_trader.test_kit.providers import CSVTickDataLoader
from nautilus_trader.test_kit.providers import TestInstrumentProvider


# Create catalog directory in current working directory
catalog_path = Path.cwd() / "catalog"
catalog_path.mkdir(exist_ok=True)

print(f"Working directory: {Path.cwd()}")
print(f"Catalog directory: {catalog_path}")

try:
    # Download EUR/USD sample data
    print("Downloading EUR/USD sample data...")
    url = "https://raw.githubusercontent.com/nautechsystems/nautilus_data/main/raw_data/fx_hist_data/DAT_ASCII_EURUSD_T_202001.csv.gz"
    filename = "EURUSD_202001.csv.gz"

    print(f"Downloading from: {url}")
    urllib.request.urlretrieve(url, filename)  # noqa: S310
    print("Download complete")

    # Create the instrument
    print("Creating EUR/USD instrument...")
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")

    # Load and process the tick data
    print("Loading tick data...")
    wrangler = QuoteTickDataWrangler(instrument)

    df = CSVTickDataLoader.load(
        filename,
        index_col=0,
        datetime_format="%Y%m%d %H%M%S%f",
    )
    df.columns = ["bid_price", "ask_price", "size"]
    print(f"Loaded {len(df)} ticks")

    # Process ticks
    print("Processing ticks...")
    ticks = wrangler.process(df)

    # Write to catalog
    print("Writing data to catalog...")
    catalog = ParquetDataCatalog(str(catalog_path))

    catalog.write_data([instrument])
    print("Instrument written to catalog")

    catalog.write_data(ticks)
    print("Tick data written to catalog")

    # Verify what was written
    print("\nVerifying catalog contents...")
    test_catalog = ParquetDataCatalog(str(catalog_path))
    loaded_instruments = test_catalog.instruments()
    print(f"Instruments in catalog: {[str(i.id) for i in loaded_instruments]}")

    # Clean up downloaded file
    os.unlink(filename)
    print("\nData setup complete!")

except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()

from nautilus_trader.backtest.node import BacktestDataConfig
from nautilus_trader.backtest.node import BacktestEngineConfig
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.backtest.node import BacktestRunConfig
from nautilus_trader.backtest.node import BacktestVenueConfig
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model import Quantity
from nautilus_trader.model import QuoteTick
from nautilus_trader.persistence.catalog import ParquetDataCatalog

2. Set up a Parquet data catalog

If everything worked correctly, you should be able to see a single EUR/USD instrument in the catalog.

# Load the catalog from current working directory
catalog_path = Path.cwd() / "catalog"

catalog = ParquetDataCatalog(str(catalog_path))
instruments = catalog.instruments()

print(f"Loaded catalog from: {catalog_path}")
print(f"Available instruments: {[str(i.id) for i in instruments]}")

if instruments:
    print(f"\nUsing instrument: {instruments[0].id}")
else:
    print("\nNo instruments found. Please run the data download cell first.")

3. Write a trading strategy

NautilusTrader includes many built-in indicators. In this example we use the MACD indicator to build a simple trading strategy.

You can read more about MACD here; this indicator merely serves as an example without any expected alpha. You can also register indicators to receive certain data types; however, in this example we manually pass the received QuoteTick to the indicator in the on_quote_tick method.

from nautilus_trader.core.message import Event
from nautilus_trader.indicators import MovingAverageConvergenceDivergence
from nautilus_trader.model import InstrumentId
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.events import PositionClosed
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.trading.strategy import StrategyConfig


class MACDConfig(StrategyConfig):
    instrument_id: InstrumentId
    fast_period: int = 12
    slow_period: int = 26
    trade_size: int = 1_000_000


class MACDStrategy(Strategy):
    """Simple MACD crossover strategy."""

    def __init__(self, config: MACDConfig):
        super().__init__(config=config)
        self.macd = MovingAverageConvergenceDivergence(
            fast_period=config.fast_period,
            slow_period=config.slow_period,
            price_type=PriceType.MID,
        )
        self.trade_size = Quantity.from_int(config.trade_size)
        self.last_macd_above_zero: bool | None = None
        self.pending_entry: OrderSide | None = None

    def on_start(self):
        self.subscribe_quote_ticks(instrument_id=self.config.instrument_id)

    def on_stop(self):
        self.close_all_positions(self.config.instrument_id)
        self.unsubscribe_quote_ticks(instrument_id=self.config.instrument_id)

    def on_quote_tick(self, tick: QuoteTick):
        self.macd.handle_quote_tick(tick)
        if self.macd.initialized:
            self.check_signals()

    def on_event(self, event: Event):
        # When a position closes, enter the pending order if we were flipping
        if (
            isinstance(event, PositionClosed)
            and self.pending_entry
            and event.instrument_id == self.config.instrument_id
        ):
            self.enter(self.pending_entry)
            self.pending_entry = None

    def check_signals(self):
        current_above = self.macd.value > 0

        if self.last_macd_above_zero is None:
            self.last_macd_above_zero = current_above
            return

        # Only act on crossovers
        if self.last_macd_above_zero == current_above:
            return

        self.last_macd_above_zero = current_above
        target_side = OrderSide.BUY if current_above else OrderSide.SELL

        # If we have a position, close it first and queue the new entry
        if self.cache.positions_open(instrument_id=self.config.instrument_id):
            self.pending_entry = target_side
            self.close_all_positions(self.config.instrument_id)
        else:
            self.enter(target_side)

    def enter(self, side: OrderSide):
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=self.trade_size,
        )
        self.submit_order(order)

4. Configure backtest

Now that we have a trading strategy and data, we can begin to configure a backtest run. Nautilus uses a BacktestNode to orchestrate backtest runs, which requires some setup. This may seem complex at first, however this is necessary for the capabilities that Nautilus provides.

To configure a BacktestNode, we first need to create an instance of a BacktestRunConfig, configuring the following (minimal) aspects of the backtest:

    engine: The engine for the backtest representing our core system, which will also contain our strategies.
    venues: The simulated venues (exchanges or brokers) available in the backtest.
    data: The input data we would like to perform the backtest on.

There are many more configurable features described later in the docs; for now this will get us up and running.

venue = BacktestVenueConfig(
    name="SIM",
    oms_type="NETTING",
    account_type="MARGIN",
    base_currency="USD",
    starting_balances=["1_000_000 USD"],
)

5. Configure data

We need to know about the instruments that we would like to load data for. We can use the ParquetDataCatalog for this.

instruments = catalog.instruments()
instruments

Next, configure the data for the backtest. Nautilus provides a flexible data-loading system for backtests, but that flexibility requires some configuration.

For each tick type (and instrument), we add a BacktestDataConfig. In this instance we are adding the QuoteTick(s) for our EUR/USD instrument:

from nautilus_trader.model import QuoteTick


data = BacktestDataConfig(
    catalog_path=str(catalog.path),
    data_cls=QuoteTick,
    instrument_id=instruments[0].id,
    end_time="2020-01-10",
)

6. Configure engine

Create a BacktestEngineConfig to represent the configuration of our core trading system. Pass in your trading strategies, adjust the log level as needed, and configure any other components (the defaults are fine too).

Add strategies via the ImportableStrategyConfig, which enables importing strategies from arbitrary files or user packages. In this instance our MACDStrategy lives in the current module, which Python refers to as __main__.

# NautilusTrader currently exceeds the rate limit for Jupyter notebook logging (stdout output),
# which is why the log_level is set to "ERROR". If you lower this level to see more logging
# then the notebook will hang during cell execution. A fix is being investigated which involves
# either raising the configured rate limits for Jupyter, or throttling the log flushing.
# https://github.com/jupyterlab/jupyterlab/issues/12845
# https://github.com/deshaw/jupyterlab-limit-output
engine = BacktestEngineConfig(
    strategies=[
        ImportableStrategyConfig(
            strategy_path="__main__:MACDStrategy",
            config_path="__main__:MACDConfig",
            config={
                "instrument_id": instruments[0].id,
                "fast_period": 12,
                "slow_period": 26,
            },
        )
    ],
    logging=LoggingConfig(log_level="ERROR"),
)

7. Run backtest

We can now pass our various config pieces to the BacktestRunConfig. This object now contains the full configuration for our backtest.

config = BacktestRunConfig(
    engine=engine,
    venues=[venue],
    data=[data],
)

The BacktestNode class orchestrates the backtest run. This separation between configuration and execution enables the BacktestNode to run multiple configurations (different parameters or batches of data). We are now ready to run some backtests.

from nautilus_trader.backtest.results import BacktestResult


node = BacktestNode(configs=[config])

# Runs one or many configs synchronously
results: list[BacktestResult] = node.run()

Expected Output

When you run the backtest, you should see:

    Trades being executed (both BUY and SELL orders).
    Positions being opened and closed based on MACD crossover signals.
    P&L calculations showing wins and losses.
    Performance metrics including win rate, profit factor, and additional statistics.

If you're not seeing any trades, check:

    The data time range (you may need more data).
    The indicator warm-up period (MACD needs time to initialize).

8. Analyze results

Now that the run is complete, we can also directly query for the BacktestEngine(s) used internally by the BacktestNode by using the run configs ID.

The engine(s) can provide additional reports and information.

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.model import Venue


engine: BacktestEngine = node.get_engine(config.id)

len(engine.trader.generate_order_fills_report())

engine.trader.generate_positions_report()

engine.trader.generate_account_report(Venue("SIM"))

9. Performance metrics

Additional performance metrics to better understand how our strategy performed:

# Get performance statistics

# Get the account and positions
account = engine.trader.generate_account_report(Venue("SIM"))
positions = engine.trader.generate_positions_report()
orders = engine.trader.generate_order_fills_report()

# Print summary statistics
print("=== STRATEGY PERFORMANCE ===")
print(f"Total Orders: {len(orders)}")
print(f"Total Positions: {len(positions)}")

if len(positions) > 0:
    # Convert P&L strings to numeric values
    positions["pnl_numeric"] = positions["realized_pnl"].apply(
        lambda x: (
            float(str(x).replace(" USD", "").replace(",", "")) if isinstance(x, str) else float(x)
        )
    )

    # Calculate win rate
    winning_trades = positions[positions["pnl_numeric"] > 0]
    losing_trades = positions[positions["pnl_numeric"] < 0]

    win_rate = len(winning_trades) / len(positions) * 100 if len(positions) > 0 else 0

    print(f"\nWin Rate: {win_rate:.1f}%")
    print(f"Winning Trades: {len(winning_trades)}")
    print(f"Losing Trades: {len(losing_trades)}")

    # Calculate returns
    total_pnl = positions["pnl_numeric"].sum()
    avg_pnl = positions["pnl_numeric"].mean()
    max_win = positions["pnl_numeric"].max()
    max_loss = positions["pnl_numeric"].min()

    print(f"\nTotal P&L: {total_pnl:.2f} USD")