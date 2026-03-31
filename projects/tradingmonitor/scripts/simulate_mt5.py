import json
import random
import socket
import time

from trademachine.tradingmonitor.config import settings


def run_mt5_simulator():
    address = (
        settings.server_host if settings.server_host != "0.0.0.0" else "127.0.0.1",  # noqa: S104
        settings.server_port,
    )  # noqa: S104
    print(f"Simulador MT5 conectando em {address[0]}:{address[1]}...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(address)

    magic = 123456
    account_login = 987654
    symbols = ["EURUSD", "GBPUSD", "XAUUSD"]

    print("Enviando dados sintéticos via TCP... Pressione Ctrl+C para parar.")

    def send(topic, data):
        msg = f"{topic} {json.dumps(data)}\n"
        sock.sendall(msg.encode("utf-8"))

    try:
        while True:
            # 1. Simular Atualização de Conta (cada loop)
            acc_data = {
                "login": account_login,
                "broker": "Simulated Broker",
                "balance": 10000.0 + random.uniform(-100, 500),
                "free_margin": 9500.0,
                "deposits": 10000.0,
                "withdrawals": 0.0,
            }
            send("ACCOUNT", acc_data)
            print(f"[SENT] ACCOUNT update for {account_login}")

            # 2. Simular Trades Aleatórios
            if random.random() > 0.7:  # 30% de chance de ocorrer um trade neste loop
                symbol = random.choice(symbols)
                ticket = random.randint(1000000, 9999999)
                deal_data = {
                    "time": int(time.time()),
                    "ticket": ticket,
                    "magic": magic,
                    "symbol": symbol,
                    "type": random.choice(["buy", "sell"]),
                    "volume": 0.1,
                    "price": 1.1000 + random.uniform(-0.01, 0.01),
                    "profit": random.uniform(-50, 100),
                    "commission": -1.5,
                    "swap": 0.0,
                }
                send("DEAL", deal_data)
                print(f"[SENT] DEAL {ticket} for strategy {magic}")

            # 3. Simular Curva de Equity (cada loop)
            equity_data = {
                "time": int(time.time()),
                "magic": magic,
                "balance": 10500.0,
                "equity": 10500.0 + random.uniform(-50, 50),
            }
            send("EQUITY", equity_data)
            print(f"[SENT] EQUITY update for strategy {magic}")

            runtime_data = {
                "time": int(time.time()),
                "magic": magic,
                "open_profit": round(random.uniform(-80, 140), 2),
                "open_trades_count": random.randint(0, 4),
                "pending_orders_count": random.randint(0, 3),
            }
            send("STRATEGY_RUNTIME", runtime_data)
            print(f"[SENT] STRATEGY_RUNTIME for strategy {magic}")

            time.sleep(2)  # Espera 2 segundos entre envios

    except KeyboardInterrupt:
        print("\nSimulador parado.")
    finally:
        sock.close()


if __name__ == "__main__":
    run_mt5_simulator()
