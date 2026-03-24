# PortifolioMaster

Ferramenta de otimização de portfólios para relatórios do MetaTrader 5. O projeto trabalha com parsing de HTML, cache em Parquet, cálculo vetorizado em NumPy/Polars, otimização brute-force ou greedy, relatório HTML e shell interativo.

## O que o projeto faz

- Lê relatórios HTML do MT5 em PT/EN e normaliza os trades.
- Monta uma base consolidada de estratégias com cache em `cache.parquet`.
- Otimiza combinações de estratégias por `RetDD` ou `NetProfit`.
- Aplica filtro de correlação por período `H`, `D`, `W` ou `M`.
- Exporta resultados, trades e portfólios em JSON, CSV e Parquet.
- Gera relatórios HTML com equity curves.
- Executa simulação Monte Carlo sobre o melhor portfólio.
- Valida a aderência entre backtests do StrategyQuant X (SQX) e MetaTrader 5.
- Oferece CLI direta e shell interativo para uso diário.

## Instalação

Requer Python 3.12+ e [`uv`](https://docs.astral.sh/uv/).

### 1. Instalar o uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Clonar e instalar dependências

```bash
git clone <repo>
cd PortifolioMaster
uv sync --dev
```

`uv` cria um ambiente virtual isolado e instala todas as dependências (lxml, polars, numpy, etc.) fixadas no `uv.lock`. O resultado é um ambiente idêntico em qualquer máquina — sem necessidade de Docker.

> **Por que não Docker?** Esta ferramenta é uma CLI que lê arquivos locais, abre relatórios no navegador e usa o modo interativo no terminal. Dentro de um container, o acesso a arquivos locais exigiria mapeamento de volumes, a abertura de HTML no browser precisaria de configuração de DISPLAY/X11, e o motor de otimização multiprocessado perderia performance na camada de virtualização do Docker no macOS. O `uv` já resolve o problema de reprodutibilidade de ambiente sem esse custo.

## Uso rápido

### Shell interativo

```bash
uv run portifoliomaster -i
```

No shell, os comandos `help`, `inspect`, `cache` e `config` ficam disponíveis para exploração rápida.

### Fluxo típico

```bash
uv run portifoliomaster --load tests/reports --list
uv run portifoliomaster --load tests/reports --optimize --min 5 --max 5 --corr 0.3 --print
uv run portifoliomaster --load tests/reports --optimize --min 5 --max 5 --montecarlo 2000 --output ./results
uv run portifoliomaster adherence --mt5-dir tests/reports --sqx-dir tests/reports-sqx
```

## Comandos principais

### `--load <dir>`

Carrega relatórios HTML de uma pasta. Se `cache.parquet` existir e for compatível, ele é usado antes do reparse dos HTMLs.

### `--list`

Lista as estratégias carregadas com métricas básicas.

### `--optimize`

Executa a otimização do portfólio.

Flags mais usadas:

| Flag | Descrição |
|---|---|
| `--min / --max <N>` | Faixa de tamanho dos portfólios |
| `--top <N>` | Quantos resultados manter |
| `--corr <X>` | Correlação máxima permitida |
| `--corr-period <H/D/W/M>` | Período da correlação |
| `--rank <RetDD/NetProfit>` | Métrica de ranking |
| `--workers <N>` | Processo paralelo (`0` = automático, `1` = single process) |
| `--greedy` | Crescimento incremental a partir do melhor seed |
| `--quiet` | Suprime mensagens INFO no console (mostra apenas avisos e erros) |
| `--strats A,B,C` | Filtra estratégias por nome |
| `--date-initial YYYY-MM-DD` | Início do recorte temporal |
| `--date-final YYYY-MM-DD` | Fim do recorte temporal |
| `--filter <N>` | Limite mínimo da métrica de ranking |
| `--save <file.csv>` | Exporta a tabela de resultados |
| `--save-trades <path>` | Exporta trades do melhor portfólio |
| `--import-p <file>` | Importa um portfólio salvo (JSON ou Parquet) |
| `--report` | Gera e abre o relatório HTML |
| `--output <dir>` | Salva os artefatos em uma pasta estruturada |
| `--montecarlo [N]` | Roda simulação Monte Carlo no melhor portfólio |

### Exemplos

```bash
# Brute-force padrão
uv run portifoliomaster --load tests/reports --optimize --min 3 --max 5 --corr 0.3 --print

# Greedy
uv run portifoliomaster --load tests/reports --optimize --greedy --min 5 --corr 0.3 --print

# Suprimir mensagens INFO (exibir apenas resultados e erros)
uv run portifoliomaster --load tests/reports --optimize --min 5 --quiet --print
```

## Subcomandos do shell e do CLI

O projeto também expõe comandos auxiliares previsíveis:

```bash
uv run portifoliomaster inspect correlations
uv run portifoliomaster inspect strategy EA_Momentum_v2 --chart
uv run portifoliomaster cache info
uv run portifoliomaster cache rebuild tests/reports
uv run portifoliomaster cache clear
uv run portifoliomaster adherence --mt5-dir tests/reports --sqx-dir tests/reports-sqx
uv run portifoliomaster drawdown pairing --target 4000 --tick 0.1
uv run portifoliomaster config show
uv run portifoliomaster config validate
```

### `inspect correlations`

Mostra a matriz/pairs de correlação entre estratégias carregadas.

### `inspect strategy <name>`

Mostra métricas detalhadas de uma estratégia, com matching exato ou parcial.

### `cache info | rebuild | clear`

- `info` exibe tamanho, número de estratégias e intervalo de datas.
- `rebuild` reprocessa os HTMLs e recria o cache.
- `clear` remove o arquivo de cache.

**Nota:** O cache agora é composto por dois arquivos: `cache.parquet` (dados de trade) e `cache_lots.json` (tamanhos de lote representativos extraídos automaticamente dos relatórios).

### `config show | validate`

- `show` exibe a configuração efetiva.
- `validate` valida o JSON e os tipos dos campos.

### `adherence`

Compara relatórios do StrategyQuant X (SQX) com os do MetaTrader 5 (MT5). Valida se a estratégia foi exportada corretamente, comparando o número de trades, o RetDD e a correlação de Pearson entre as curvas de equity.

Critérios de aprovação:
- **Trade Ratio**: `sqx_trades / mt5_trades >= threshold` (padrão 80%).
- **RetDD Ratio**: `sqx_retdd / mt5_retdd >= threshold` (padrão 80%).
- **Pearson**: Correlação entre as curvas de equity >= `pearson_threshold` (padrão 0.85).

Flags:
- `--mt5-dir`: Pasta com relatórios HTML do MT5.
- `--sqx-dir`: Pasta com CSVs do SQX.
- `--threshold`: Limite para trade ratio e RetDD ratio (0.0 a 1.0).
- `--pearson`: Limite para correlação de Pearson (0.0 a 1.0).
- `--output`: Pasta de saída (auto-gerada com timestamp se omitida).
- `--no-browser`: Não abre o navegador automaticamente.

Os artefatos são sempre salvos em uma pasta `adherence_YYYY-MM-DD_HH-MM/` contendo `adherence_report.html` e `results.json` (com listas separadas de estratégias aprovadas e reprovadas).

### `drawdown pairing`

Extrai o lote representativo de cada estratégia diretamente do histórico MT5 (mediana da coluna Volume) e calcula o lote ideal para que o MaxDD individual se aproxime de um alvo financeiro. Útil para equalizar o risco entre estratégias com volatilidades diferentes antes da otimização.

Flags:
- `--target`: Alvo de drawdown na moeda da conta (padrão 4000).
- `--tick`: Incremento mínimo de lote do ativo (padrão 0.1).
- `--apply`: Escala o histórico de Net_Profit na memória e atualiza o `cache.parquet` e `cache_lots.json`.

## Artefatos gerados

### Otimização (`--output <dir>`)

Uma pasta de execução é criada com:

- `rank.json`: Ranking dos top-N portfólios com métricas e pesos calculados (volatility-inverse).
- `portfolios/`: Um `.parquet` por portfólio do ranking, incluindo a coluna `Lot` com o lote de cada estratégia.
- `report.html`: Relatório visual interativo com equity curves.
- `montecarlo_report.html`: Quando `--montecarlo` é usado.

Quando `--save-trades` é usado separadamente, o arquivo de trades é gravado no caminho informado.

### Aderência (`adherence`)

Uma pasta `adherence_YYYY-MM-DD_HH-MM/` é sempre criada (ou a pasta especificada em `--output`):

- `adherence_report.html`: Relatório visual com equity curves lado a lado.
- `results.json`: Resultado estruturado com `passed_strategies`, `failed_strategies` e métricas detalhadas por estratégia.

## Configuração

Crie `config.json` no diretório de trabalho. Todos os campos são opcionais.

```json
{
  "min_assets": 5,
  "max_assets": 5,
  "top_n": 10,
  "max_corr": 0.3,
  "corr_period": "D",
  "rank_by": "RetDD",
  "num_workers": 0,
  "print_results": false,
  "generate_report": false,
  "corr_filter_batch_size": 10000,
  "matrix_algebra_batch_size": 1000,
  "log_path": "log.log",
  "cache_path": "cache.parquet"
}
```

## Estrutura do projeto

```text
src/portifoliomaster/
├── main.py
├── api/
│   └── cli.py
├── core/
│   ├── config.py
│   └── exceptions.py
├── services/
│   ├── metrics.py
│   ├── montecarlo.py
│   ├── optimization.py
│   └── portfolio.py
└── utils/
    ├── help.py
    ├── logger.py
    ├── mt5_parser.py
    └── visualizer.py
```

## Desenvolvimento

```bash
# Testes
uv run pytest tests/ -v

# Type checking (mypy intermediário — sem strict)
uv run mypy src/portifoliomaster/
```

O mypy está configurado com `check_untyped_defs`, `warn_return_any` e `no_implicit_optional`. Bibliotecas sem stubs oficiais (pandas, plotly, tqdm) são silenciadas via `[[tool.mypy.overrides]]` no `pyproject.toml`.
