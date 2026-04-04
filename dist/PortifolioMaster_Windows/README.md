# PortifolioMaster for Windows

Este pacote contem apenas o necessario para rodar o `PortifolioMaster` fora do monorepo principal.

## Requisitos

- Windows 10 ou 11
- Python 3.12 instalado
- `uv` instalado

Instalacao do `uv` no PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Como usar

1. Extraia o `.zip`.
2. Abra o PowerShell dentro da pasta `PortifolioMaster_Windows`.
3. Instale o ambiente:

```powershell
uv sync
```

4. Valide o CLI:

```powershell
uv run portifoliomaster --help
```

## Fluxos comuns

Carregar relatorios MT5:

```powershell
uv run portifoliomaster load .\reports --workers 8 --list
```

Aplicar drawdown pairing:

```powershell
uv run portifoliomaster pairing --load .\reports --workers 8 --target 4000 --tick 0.1 --apply
```

Medir throughput do motor para uma janela de 10 minutos:

```powershell
uv run portifoliomaster benchmark --load .\reports --load-workers 8 --min 5 --max 5 --corr 0.3 --workers 8 --sample-seconds 5 --target-time 600
```

Rodar otimizacao greedy com 2 loops:

```powershell
uv run portifoliomaster optimize --greedy --greedy-loops 2 --min 5 --top 10 --corr 0.3 --rank RetDD --print --output .\run_greedy
```

## Arquivos importantes

- `pyproject.toml`: workspace standalone do PortifolioMaster
- `bases/portifolio_master_cli/`: CLI
- `components/core/`: utilitarios compartilhados
- `components/mt5/`: parser dos reports HTML do MT5
- `components/portifoliomaster/`: logica do projeto
- `run_portifoliomaster.bat`: atalho opcional para chamar o CLI

## Atalho opcional

Voce tambem pode executar:

```powershell
.\run_portifoliomaster.bat --help
```
