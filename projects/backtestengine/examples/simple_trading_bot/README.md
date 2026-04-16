# Simple Trading Bot Smoke Test

Este exemplo adapta o bot simples da pasta `StrategyTester5/examples/simple trading bot`.

Execute a partir da raiz do monorepo:

```bash
uv run backtestengine run \
  projects/backtestengine/examples/simple_trading_bot/tester.json \
  --history-dir projects/backtestengine/examples/simple_trading_bot/History \
  --broker-data-dir projects/backtestengine/examples/simple_trading_bot/ICMarketsSC-Demo \
  --strategy projects/backtestengine/examples/simple_trading_bot/strategy.py:on_tick
```

O histórico offline desta pasta foi gerado só para smoke test, então ele serve para validar o fluxo end-to-end da CLI e da engine.

Para baixar do DataManager e rodar em sequência com um único script:

```bash
DATAMANAGER_API_KEY='SUA_CHAVE' \
uv run python projects/backtestengine/examples/simple_trading_bot/run_example.py
```

O script usa por padrão:

- `base-url`: `http://100.100.10.240:8686`
- `source`: `dukascopy`
- `asset`: `EURUSD`
- `timeframe`: `M1`
- `start-date`: `2024-01-01T00:00:00`
- `end-date`: `2024-01-03T00:00:00`

Você também pode pular o download e usar só o histórico local:

```bash
uv run python projects/backtestengine/examples/simple_trading_bot/run_example.py --skip-download
```
