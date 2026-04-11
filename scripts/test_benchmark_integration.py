from trademachine.tradingmonitor_ingestion.ingestion.benchmark_sync import (
    sync_benchmark_from_datamanager,
)
from trademachine.tradingmonitor_storage.db.database import SessionLocal
from trademachine.tradingmonitor_storage.db.models import Benchmark


def run_sync():
    db = SessionLocal()
    try:
        # 1. Check if benchmark exists or create it
        benchmark = (
            db.query(Benchmark)
            .filter(Benchmark.source == "BINANCE", Benchmark.asset == "BTCUSD")
            .first()
        )

        if not benchmark:
            print("Creating benchmark BINANCE BTCUSD...")
            benchmark = Benchmark(
                name="Bitcoin Binance",
                source="BINANCE",
                asset="BTCUSD",
                timeframe="M1",
                enabled=True,
                is_default=False,
            )
            db.add(benchmark)
            db.commit()
            db.refresh(benchmark)

        print(f"Syncing benchmark ID {benchmark.id} from DataManager...")
        result = sync_benchmark_from_datamanager(db, benchmark)
        db.commit()
        print(f"Result: {result}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run_sync()
