import os
from datetime import UTC, datetime

import typer
from trademachine.core.logger import setup_logger
from trademachine.tradingmonitor_ingestion.public import HEARTBEAT_FILE
from trademachine.tradingmonitor_storage.public import (
    AccountRepository,
    DatabaseInitializationError,
    DatabaseUnavailableError,
    PortfolioRepository,
    StrategyRepository,
    init_db,
    notifier,
    settings,
)

app = typer.Typer(help="MT5 Trading Monitor CLI")


@app.callback()
def callback():
    """MT5 Trading Monitor CLI."""
    setup_logger(log_path="projects/tradingmonitor/log.log")


@app.command()
def status():
    """Check if the ingestion daemon is running and healthy."""
    if not os.path.exists(HEARTBEAT_FILE):
        typer.echo("Status: Inactive (Heartbeat file not found).", err=True)
        return

    mtime = os.path.getmtime(HEARTBEAT_FILE)
    last_heartbeat = datetime.fromtimestamp(mtime, tz=UTC)
    diff = datetime.now(UTC) - last_heartbeat

    with open(HEARTBEAT_FILE) as f:
        content = f.read()

    typer.echo("Ingestion Daemon Status:")
    typer.echo(f"  Last Heartbeat: {content}")

    if diff.total_seconds() > 30:
        typer.echo("  Health: WARNING (No update in the last 30 seconds)", err=True)
    else:
        typer.echo("  Health: Healthy (Running)")


@app.command()
def setup_db():
    """Initializes the database schema and TimescaleDB hypertables."""
    typer.echo("Initializing database...")
    try:
        init_db()
    except DatabaseInitializationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except DatabaseUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("Database initialized successfully.")


@app.command()
def start_ingestion(host: str = settings.server_host, port: int = settings.server_port):
    """Start the TCP ingestion server to receive MT5 data."""
    from trademachine.tradingmonitor_ingestion.public import start_server

    typer.echo(f"Starting TCP ingestion server on {host}:{port}...")
    try:
        start_server(host, port)
    except DatabaseUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def register_account(
    account_number: str,
    name: str = typer.Option(..., help="Account Name"),
    broker: str = typer.Option(..., help="Broker Name"),
    account_type: str = typer.Option("Demo", help="Real, Demo, etc."),
    currency: str = typer.Option("USD", help="Currency (BRL, USD, etc.)"),
    description: str | None = typer.Option(None),
):
    """Register or update a trading account."""
    account_repo = AccountRepository()
    account_repo.create_or_update(
        account_id=account_number,
        name=name,
        broker=broker,
        account_type=account_type,
        currency=currency,
        description=description,
    )
    typer.echo(f"Account {account_number} registered.")


@app.command()
def list_accounts():
    """List all registered trading accounts."""
    account_repo = AccountRepository()
    accounts = account_repo.get_all()
    for acc in accounts:
        typer.echo(
            f"[{acc.get('id')}] {acc.get('name')} - Broker: {acc.get('broker')} - Balance: {acc.get('balance')} {acc.get('currency')}"
        )


@app.command()
def register_strategy(
    strategy_id: str,
    name: str = typer.Option(..., help="Name of the strategy"),
    account_id: str | None = typer.Option(None, help="Link to an Account ID"),
    symbol: str | None = typer.Option(None, help="Asset symbol"),
    timeframe: str | None = typer.Option(
        None, help="Graphic timeframe (e.g., M15, H1)"
    ),
    style: str | None = typer.Option(
        None, help="Operational style (Momentum, Breakout, etc.)"
    ),
    duration: str | None = typer.Option(
        None, help="Trade duration (Day Trading, Swing, etc.)"
    ),
    balance: float = typer.Option(0.0, help="Initial balance"),
    currency: str = typer.Option("USD", help="Base currency"),
    description: str | None = typer.Option(None, help="Strategy description"),
    live: bool = typer.Option(
        False, "--live/--incubation", help="Set strategy as Live or Incubation"
    ),
    real: bool = typer.Option(
        False, "--real/--demo", help="Set account as Real or Demo"
    ),
):
    """Register or update strategy metadata."""
    strategy_repo = StrategyRepository()

    # Check if exists for messaging
    existing = strategy_repo.get_by_id(strategy_id)
    if existing:
        typer.echo(f"Updating strategy: {strategy_id}")
    else:
        typer.echo(f"Creating new strategy: {strategy_id}")

    strategy_repo.create_or_update(
        strategy_id=strategy_id,
        name=name,
        account_id=account_id,
        symbol=symbol,
        timeframe=timeframe,
        operational_style=style,
        trade_duration=duration,
        initial_balance=balance,
        base_currency=currency,
        description=description,
        live=live,
        real_account=real,
    )
    typer.echo(f"Strategy '{name}' registered successfully.")


@app.command()
def create_portfolio(
    name: str = typer.Option(..., help="Portfolio Name"),
    balance: float = typer.Option(0.0, help="Initial balance"),
    description: str | None = typer.Option(None),
    live: bool = typer.Option(False, "--live/--incubation"),
    real: bool = typer.Option(False, "--real/--demo"),
):
    """Create a new portfolio."""
    portfolio_repo = PortfolioRepository()
    portfolio_id = portfolio_repo.create(
        name=name,
        initial_balance=balance,
        description=description,
        live=live,
        real_account=real,
    )
    typer.echo(f"Portfolio '{name}' (ID: {portfolio_id}) created.")


@app.command()
def add_to_portfolio(portfolio_id: int, strategy_id: str):
    """Add a strategy to a portfolio."""
    portfolio_repo = PortfolioRepository()
    success = portfolio_repo.add_strategy(portfolio_id, strategy_id)
    if not success:
        typer.echo("Portfolio or Strategy not found.", err=True)
        return

    # Check if already exists
    portfolio = portfolio_repo.get_by_id(portfolio_id, include_strategies=True)
    if portfolio:
        strategy_ids = [s["id"] for s in portfolio.get("strategies", [])]
        if strategy_id in strategy_ids:
            typer.echo(
                f"Strategy {strategy_id} is already in Portfolio {portfolio_id}."
            )
            return

    typer.echo(f"Strategy {strategy_id} added to Portfolio {portfolio_id}.")


@app.command()
def list_portfolios():
    """List all portfolios."""
    portfolio_repo = PortfolioRepository()
    portfolios = portfolio_repo.get_all(include_strategies=True)
    for p in portfolios:
        strategies_ids = [s["id"] for s in p.get("strategies", [])]
        typer.echo(
            f"[{p.get('id')}] {p.get('name')} - Initial: {p.get('initial_balance')} - Strategies: {strategies_ids}"
        )


@app.command()
def report(strategy_id: str):
    """Generate a performance report for a specific strategy."""
    strategy_repo = StrategyRepository()
    strategy = strategy_repo.get_by_id(strategy_id, include_account=True)

    if not strategy:
        typer.echo(f"Strategy {strategy_id} not found in database.")
        return

    typer.echo(f"Generating report for {strategy.get('name')} ({strategy_id})...")
    from trademachine.tradingmonitor_analytics.metrics.calculator import (
        calculate_metrics,
    )

    metrics = calculate_metrics(strategy_id)

    if "error" in metrics:
        typer.echo(f"Error: {metrics['error']}", err=True)
        return

    typer.echo("\n--- Strategy Info ---")
    typer.echo(f"Symbol: {strategy.get('symbol')}")
    typer.echo(f"Timeframe: {strategy.get('timeframe')}")
    typer.echo(f"Style: {strategy.get('operational_style')}")
    typer.echo(f"Status: {'Live' if strategy.get('live') else 'Incubation'}")
    typer.echo(f"Account: {'Real' if strategy.get('real_account') else 'Demo'}")
    if strategy.get("account"):
        typer.echo(
            f"Broker/Account: {strategy.get('account', {}).get('broker')} / {strategy.get('account', {}).get('id')}"
        )

    typer.echo("\n--- Performance Metrics ---")
    for key, value in metrics.items():
        if isinstance(value, float):
            typer.echo(f"{key}: {value:.2f}")
        else:
            typer.echo(f"{key}: {value}")
    typer.echo("-----------------------------------")


@app.command()
def portfolio_report(portfolio_id: int):
    """Generate aggregate report for a portfolio."""
    portfolio_repo = PortfolioRepository()
    portfolio = portfolio_repo.get_by_id(portfolio_id, include_strategies=True)
    if not portfolio:
        typer.echo("Portfolio not found.", err=True)
        return

    typer.echo(f"\n=== PORTFOLIO REPORT: {portfolio.get('name')} ===")
    typer.echo(f"Initial Balance: {portfolio.get('initial_balance')}")
    typer.echo(f"Status: {'Live' if portfolio.get('live') else 'Incubation'}")

    strategy_ids = [s["id"] for s in portfolio.get("strategies", [])]
    if not strategy_ids:
        typer.echo("No strategies in this portfolio.")
        return

    from trademachine.tradingmonitor_analytics.metrics.calculator import (
        calculate_portfolio_metrics,
    )

    metrics = calculate_portfolio_metrics(strategy_ids)

    if "error" in metrics:
        typer.echo(f"Error: {metrics['error']}", err=True)
        return

    typer.echo("\n--- Aggregate Performance ---")
    for key, value in metrics.items():
        if isinstance(value, float):
            typer.echo(f"{key}: {value:.2f}")
        else:
            typer.echo(f"{key}: {value}")
    typer.echo("===========================================")


@app.command()
def send_report(
    strategy_id: str | None = typer.Option(None, help="Strategy ID"),
    portfolio_id: int | None = typer.Option(None, help="Portfolio ID"),
    output: str = typer.Option("report.html", help="Output filename"),
):
    """Generate and send QuantStats report to Telegram."""
    if not strategy_id and not portfolio_id:
        typer.echo(
            "Error: Either --strategy-id or --portfolio-id must be provided.", err=True
        )
        raise typer.Exit(1)

    from trademachine.tradingmonitor_analytics.metrics.calculator import (
        generate_qs_report,
    )

    typer.echo("Generating report...")
    report_path = generate_qs_report(
        strategy_id=strategy_id, portfolio_id=portfolio_id, output_path=output
    )

    if not report_path or not os.path.exists(report_path):
        typer.echo("Error: Failed to generate report (possibly no data).", err=True)
        return

    typer.echo(f"Report generated: {report_path}")

    if settings.telegram_token and settings.telegram_chat_id:
        typer.echo("Sending to Telegram...")
        caption = "📊 <b>Performance Report</b>"
        if strategy_id:
            caption += f"\nStrategy: <code>{strategy_id}</code>"
        elif portfolio_id:
            caption += f"\nPortfolio ID: <code>{portfolio_id}</code>"

        notifier.send_document_sync(report_path, caption=caption)
        typer.echo("Report sent successfully.")
    else:
        typer.echo("Skipping Telegram send (Token/ChatID not configured).")


@app.command()
def start_dashboard(
    host: str = typer.Option("127.0.0.1", help="Dashboard host"),
    port: int = typer.Option(8000, help="Dashboard port"),
    no_ingestion: bool = typer.Option(
        False, "--no-ingestion", help="Disable MT5 ingestion"
    ),
    ingestion_host: str = typer.Option(settings.server_host, help="TCP ingestion host"),
    ingestion_port: int = typer.Option(settings.server_port, help="TCP ingestion port"),
):
    """Start the real-time web dashboard (includes MT5 TCP ingestion by default)."""
    import uvicorn

    with_ingestion = not no_ingestion
    typer.echo(f"Starting dashboard on http://{host}:{port}")
    if with_ingestion:
        typer.echo(f"MT5 ingestion enabled on {ingestion_host}:{ingestion_port}")
    else:
        typer.echo("MT5 ingestion disabled (--no-ingestion)")

    os.environ["_TM_WITH_INGESTION"] = "1" if with_ingestion else "0"
    os.environ["_TM_INGESTION_HOST"] = ingestion_host
    os.environ["_TM_INGESTION_PORT"] = str(ingestion_port)
    app_target = ".".join(
        ["trademachine", "trading_monitor_dashboard", "app:create_configured_app"]
    )

    try:
        uvicorn.run(
            app_target,
            factory=True,
            host=host,
            port=port,
        )
    except DatabaseUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def test_telegram(message: str = "Test message from TradingMonitor CLI"):
    """Send a test message to Telegram to verify integration."""
    if not settings.enable_notifications:
        typer.echo(
            "Error: Notifications are disabled in settings (ENABLE_NOTIFICATIONS).",
            err=True,
        )
        raise typer.Exit(1)

    if not settings.telegram_token or not settings.telegram_chat_id:
        typer.echo("Error: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Sending test message to Telegram chat {settings.telegram_chat_id}...")
    notifier.send_message_sync(f"🚀 <b>TradingMonitor Test</b>\n\n{message}")
    typer.echo("Success! (Check your Telegram chat)")


if __name__ == "__main__":
    app()
