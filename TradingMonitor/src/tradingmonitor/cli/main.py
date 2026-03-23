import os
from datetime import UTC, datetime

import typer
from tradingmonitor.config import settings
from tradingmonitor.db.database import SessionLocal, init_db
from tradingmonitor.db.models import Account, Portfolio, Strategy
from tradingmonitor.ingestion.tcp_server import HEARTBEAT_FILE
from tradingmonitor.utils.notifications import notifier

app = typer.Typer(help="MT5 Trading Monitor CLI")


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
    init_db()
    typer.echo("Database initialized successfully.")


@app.command()
def start_ingestion(host: str = settings.server_host, port: int = settings.server_port):
    """Start the TCP ingestion server to receive MT5 data."""
    typer.echo(f"Starting TCP ingestion server on {host}:{port}...")
    from tradingmonitor.ingestion.tcp_server import start_server

    start_server(host, port)


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
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_number).first()
        if not acc:
            acc = Account(id=account_number)
            db.add(acc)

        acc.name = name
        acc.broker = broker
        acc.account_type = account_type
        acc.currency = currency
        acc.description = description

        db.commit()
        typer.echo(f"Account {account_number} registered.")
    finally:
        db.close()


@app.command()
def list_accounts():
    """List all registered trading accounts."""
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        for acc in accounts:
            typer.echo(
                f"[{acc.id}] {acc.name} - Broker: {acc.broker} - Balance: {acc.balance} {acc.currency}"
            )
    finally:
        db.close()


@app.command()
def register_strategy(
    strategy_id: str,
    name: str = typer.Option(..., help="Name of the strategy"),
    account_id: str | None = typer.Option(None, help="Link to an Account ID"),
    symbol: str | None = typer.Option(None, help="Asset symbol"),
    timeframe: str | None = typer.Option(None, help="Graphic timeframe (e.g., M15, H1)"),
    style: str | None = typer.Option(None, help="Operational style (Momentum, Breakout, etc.)"),
    duration: str | None = typer.Option(None, help="Trade duration (Day Trading, Swing, etc.)"),
    balance: float = typer.Option(0.0, help="Initial balance"),
    currency: str = typer.Option("USD", help="Base currency"),
    description: str | None = typer.Option(None, help="Strategy description"),
    live: bool = typer.Option(
        False, "--live/--incubation", help="Set strategy as Live or Incubation"
    ),
    real: bool = typer.Option(False, "--real/--demo", help="Set account as Real or Demo"),
):
    """Register or update strategy metadata."""
    db = SessionLocal()
    try:
        strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()

        if not strategy:
            strategy = Strategy(id=strategy_id)
            db.add(strategy)
            typer.echo(f"Creating new strategy: {strategy_id}")
        else:
            typer.echo(f"Updating strategy: {strategy_id}")

        strategy.name = name
        strategy.account_id = account_id
        strategy.symbol = symbol
        strategy.timeframe = timeframe
        strategy.operational_style = style
        strategy.trade_duration = duration
        strategy.initial_balance = balance
        strategy.base_currency = currency
        strategy.description = description
        strategy.live = live
        strategy.real_account = real

        db.commit()
        typer.echo(f"Strategy '{name}' registered successfully.")
    finally:
        db.close()


@app.command()
def create_portfolio(
    name: str = typer.Option(..., help="Portfolio Name"),
    balance: float = typer.Option(0.0, help="Initial balance"),
    description: str | None = typer.Option(None),
    live: bool = typer.Option(False, "--live/--incubation"),
    real: bool = typer.Option(False, "--real/--demo"),
):
    """Create a new portfolio."""
    db = SessionLocal()
    try:
        portfolio = Portfolio(
            name=name,
            initial_balance=balance,
            description=description,
            live=live,
            real_account=real,
        )
        db.add(portfolio)
        db.commit()
        typer.echo(f"Portfolio '{name}' (ID: {portfolio.id}) created.")
    finally:
        db.close()


@app.command()
def add_to_portfolio(portfolio_id: int, strategy_id: str):
    """Add a strategy to a portfolio."""
    db = SessionLocal()
    try:
        portfolio = db.query(Portfolio).get(portfolio_id)
        strategy = db.query(Strategy).get(strategy_id)

        if not portfolio or not strategy:
            typer.echo("Portfolio or Strategy not found.", err=True)
            return

        if strategy not in portfolio.strategies:
            portfolio.strategies.append(strategy)
            db.commit()
            typer.echo(f"Strategy {strategy_id} added to Portfolio {portfolio_id}.")
        else:
            typer.echo(f"Strategy {strategy_id} is already in Portfolio {portfolio_id}.")
    finally:
        db.close()


@app.command()
def list_portfolios():
    """List all portfolios."""
    db = SessionLocal()
    try:
        portfolios = db.query(Portfolio).all()
        for p in portfolios:
            strategies_ids = [s.id for s in p.strategies]
            typer.echo(
                f"[{p.id}] {p.name} - Initial: {p.initial_balance} - Strategies: {strategies_ids}"
            )
    finally:
        db.close()


@app.command()
def report(strategy_id: str):
    """Generate a performance report for a specific strategy."""
    db = SessionLocal()
    try:
        strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()

        if not strategy:
            typer.echo(f"Strategy {strategy_id} not found in database.")
            return

        typer.echo(f"Generating report for {strategy.name} ({strategy_id})...")
        from tradingmonitor.metrics.calculator import calculate_metrics

        metrics = calculate_metrics(strategy_id)

        if "error" in metrics:
            typer.echo(f"Error: {metrics['error']}", err=True)
            return

        typer.echo("\n--- Strategy Info ---")
        typer.echo(f"Symbol: {strategy.symbol}")
        typer.echo(f"Timeframe: {strategy.timeframe}")
        typer.echo(f"Style: {strategy.operational_style}")
        typer.echo(f"Status: {'Live' if strategy.live else 'Incubation'}")
        typer.echo(f"Account: {'Real' if strategy.real_account else 'Demo'}")
        if strategy.account:
            typer.echo(f"Broker/Account: {strategy.account.broker} / {strategy.account.id}")

        typer.echo("\n--- Performance Metrics ---")
        for key, value in metrics.items():
            if isinstance(value, float):
                typer.echo(f"{key}: {value:.2f}")
            else:
                typer.echo(f"{key}: {value}")
        typer.echo("-----------------------------------")
    finally:
        db.close()


@app.command()
def portfolio_report(portfolio_id: int):
    """Generate aggregate report for a portfolio."""
    db = SessionLocal()
    try:
        portfolio = db.query(Portfolio).get(portfolio_id)
        if not portfolio:
            typer.echo("Portfolio not found.", err=True)
            return

        typer.echo(f"\n=== PORTFOLIO REPORT: {portfolio.name} ===")
        typer.echo(f"Initial Balance: {portfolio.initial_balance}")
        typer.echo(f"Status: {'Live' if portfolio.live else 'Incubation'}")

        strategy_ids = [s.id for s in portfolio.strategies]
        if not strategy_ids:
            typer.echo("No strategies in this portfolio.")
            return

        from tradingmonitor.metrics.calculator import calculate_portfolio_metrics

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
    finally:
        db.close()


@app.command()
def start_dashboard(
    host: str = typer.Option("127.0.0.1", help="Dashboard host"),
    port: int = typer.Option(8000, help="Dashboard port"),
    no_ingestion: bool = typer.Option(False, "--no-ingestion", help="Disable MT5 ingestion"),
    ingestion_host: str = typer.Option(settings.server_host, help="TCP ingestion host"),
    ingestion_port: int = typer.Option(settings.server_port, help="TCP ingestion port"),
):
    """Start the real-time web dashboard (includes MT5 TCP ingestion by default)."""
    import uvicorn
    from tradingmonitor.dashboard.app import create_app

    with_ingestion = not no_ingestion
    typer.echo(f"Starting dashboard on http://{host}:{port}")
    if with_ingestion:
        typer.echo(f"MT5 ingestion enabled on {ingestion_host}:{ingestion_port}")
    else:
        typer.echo("MT5 ingestion disabled (--no-ingestion)")

    app_instance = create_app(
        with_ingestion=with_ingestion,
        server_host=ingestion_host,
        server_port=ingestion_port,
    )
    uvicorn.run(app_instance, host=host, port=port)


@app.command()
def test_telegram(message: str = "Test message from TradingMonitor CLI"):
    """Send a test message to Telegram to verify integration."""
    if not settings.enable_notifications:
        typer.echo(
            "Error: Notifications are disabled in settings (ENABLE_NOTIFICATIONS).", err=True
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
