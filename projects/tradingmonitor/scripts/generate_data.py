import random
from datetime import datetime, timedelta

import pytz  # type: ignore[import-untyped]
from trademachine.tradingmonitor.db.database import SessionLocal
from trademachine.tradingmonitor.db.models import (
    Account,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Strategy,
)


def generate_synthetic_data():
    db = SessionLocal()

    # 1. Criar Conta
    acc_id = "987654321"
    account = db.query(Account).filter(Account.id == acc_id).first()
    if not account:
        account = Account(
            id=acc_id,
            name="Test Real Account",
            broker="IC Markets",
            account_type="Real",
            currency="USD",
            balance=10000.0,
            free_margin=9500.0,
            total_deposits=10000.0,
        )
        db.add(account)
        db.commit()

    # 2. Criar Estratégias
    strategies_config = [
        {
            "id": "1001",
            "name": "Trend Magic",
            "symbol": "EURUSD",
            "style": "Trend Following",
            "win_rate": 0.4,
            "avg_win": 150,
            "avg_loss": -50,
            "freq": 1,
        },
        {
            "id": "1002",
            "name": "Mean Revert Pro",
            "symbol": "GBPUSD",
            "style": "Mean Reversion",
            "win_rate": 0.65,
            "avg_win": 40,
            "avg_loss": -60,
            "freq": 3,
        },
        {
            "id": "1003",
            "name": "Gold Scalper",
            "symbol": "XAUUSD",
            "style": "Scalping",
            "win_rate": 0.55,
            "avg_win": 15,
            "avg_loss": -12,
            "freq": 8,
        },
    ]

    strategies = []
    for config in strategies_config:
        st = db.query(Strategy).filter(Strategy.id == config["id"]).first()
        if not st:
            st = Strategy(
                id=config["id"],
                name=config["name"],
                symbol=config["symbol"],
                timeframe="H1",
                operational_style=config["style"],
                trade_duration="Day Trade",
                initial_balance=2000.0,
                base_currency="USD",
                live=True,
                real_account=True,
                account_id=acc_id,
            )
            db.add(st)
            strategies.append((st, config))
    db.commit()

    # 3. Criar Portfólio
    portfolio = db.query(Portfolio).filter(Portfolio.name == "Main Portfolio").first()
    if not portfolio:
        portfolio = Portfolio(
            name="Main Portfolio",
            initial_balance=6000.0,
            description="Agregado de testes",
            live=True,
            real_account=True,
        )
        db.add(portfolio)
        db.commit()
        # Vincular estratégias
        for st, _ in strategies:
            portfolio.strategies.append(st)
        db.commit()

    # 4. Gerar Histórico de 60 dias
    print("Gerando histórico de trades e equity...")
    start_date = datetime.now(pytz.utc) - timedelta(days=60)

    for st_obj, config in strategies:
        current_balance = 2000.0
        ticket_counter = int(config["id"]) * 1000  # type: ignore[call-overload]

        for day in range(60):
            current_time = start_date + timedelta(days=day)

            # Gerar N trades para o dia baseado na frequência
            num_trades = config["freq"] + random.randint(-1, 2)  # type: ignore[operator]
            for _ in range(max(0, num_trades)):
                is_win = random.random() < config["win_rate"]  # type: ignore[operator]
                profit = (
                    float(config["avg_win"]) if is_win else float(config["avg_loss"])
                )  # type: ignore[arg-type]
                profit *= float(random.uniform(0.8, 1.2))  # Adicionar variabilidade

                commission = -1.5
                swap = random.choice([0, 0, -0.5])

                deal = Deal(
                    timestamp=current_time + timedelta(hours=random.randint(1, 23)),
                    ticket=ticket_counter,
                    strategy_id=st_obj.id,
                    symbol=config["symbol"],
                    type=DealType.BUY if random.random() > 0.5 else DealType.SELL,
                    volume=0.1,
                    price=1.1000 + random.uniform(-0.01, 0.01),
                    profit=round(profit, 2),
                    commission=commission,
                    swap=swap,
                )
                db.add(deal)
                ticket_counter += 1
                current_balance += profit + commission + swap

            # Salvar ponto na curva de equity ao final do dia
            eq = EquityCurve(
                timestamp=current_time.replace(hour=23, minute=59),
                strategy_id=st_obj.id,
                balance=round(current_balance, 2),
                equity=round(current_balance + random.uniform(-10, 10), 2),
            )
            db.add(eq)

        print(
            f"Finalizado: {config['name']} | Final Balance: {round(current_balance, 2)}"
        )

    db.commit()
    db.close()
    print("\nSucesso! Dados sintéticos inseridos.")


if __name__ == "__main__":
    generate_synthetic_data()
