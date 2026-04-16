# USATECH M1 Smoke Test

Este exemplo baixa `USATECH` do `Dukascopy` via `DataManager` e roda um backtest em:

- `timeframe`: `M1`
- `modelling`: `every_tick`

Uso direto:

```bash
DATAMANAGER_API_KEY='SUA_CHAVE' \
uv run python projects/backtestengine/examples/usatech_m1_smoke/run_example.py
```

Para reutilizar o histórico local já baixado:

```bash
uv run python projects/backtestengine/examples/usatech_m1_smoke/run_example.py --skip-download
```
