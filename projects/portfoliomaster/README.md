# PortfolioMaster

Ferramenta de alta performance para análise e otimização de combinações de estratégias de trading do MetaTrader 5. Trabalha com parsing de HTML, cache em Parquet, cálculo vetorizado em NumPy/Polars, três modos de otimização (brute-force, greedy e algoritmo genético), relatório HTML, simulação Monte Carlo, validação de aderência SQX/MT5 e shell interativo.

> **Python:** 3.12+ | **Foco atual:** CLI local — não há API web/FastAPI neste repositório.

## O que o projeto faz

- Lê relatórios HTML do MT5 em PT/EN e normaliza os trades.
- Monta uma base consolidada de estratégias com cache em `cache.parquet`.
- Otimiza combinações de estratégias por `RetDD` ou `NetProfit`.
- Aplica filtro de correlação máxima por par (não média) por período `H`, `D`, `W` ou `M`.
- Exporta resultados, trades e portfólios em JSON, CSV e Parquet.
- Gera relatórios HTML interativos com equity curves.
- Executa simulação Monte Carlo sobre o melhor portfólio.
- Valida a aderência entre backtests do StrategyQuant X (SQX) e MetaTrader 5.
- Oferece CLI direta e shell interativo para uso diário.

---

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
cd PortfolioMaster
uv sync --dev
```

`uv` cria um ambiente virtual isolado e instala todas as dependências (lxml, polars, numpy, etc.) fixadas no `uv.lock`. O resultado é um ambiente idêntico em qualquer máquina — sem necessidade de Docker.

> **Por que não Docker?** Esta ferramenta é uma CLI que lê arquivos locais, abre relatórios no navegador e usa o modo interativo no terminal. Dentro de um container, o acesso a arquivos locais exigiria mapeamento de volumes, a abertura de HTML no browser precisaria de configuração de DISPLAY/X11, e o motor de otimização multiprocessado perderia performance na camada de virtualização do Docker no macOS. O `uv` já resolve o problema de reprodutibilidade de ambiente sem esse custo.

---

## Tecnologias Principais

- **Linguagem:** Python 3.12+
- **Processamento de Dados:** `polars`, `numpy`, `pandas`
- **Configuração:** `pydantic`, `pydantic-settings`
- **Parsing:** `beautifulsoup4`, `lxml`
- **Visualização:** `plotly`
- **Caching:** `pyarrow` (Parquet)
- **Testes:** `pytest`
- **Linting/Formatação:** `ruff`
- **Gerenciamento de dependências:** `uv`

---

## Uso rápido

### Shell interativo (recomendado)

```bash
uv run portfoliomaster -i
```

No shell interativo, os dados persistem em memória entre comandos. Isso é útil para carregar uma vez e inspecionar várias vezes, otimizar e depois exportar/plotar sem reprocessar, e comparar estratégias sem sair do processo. Os comandos `help`, `inspect`, `cache` e `config` ficam disponíveis para exploração rápida.

### Fluxo típico

```bash
uv run portfoliomaster load tests/reports --list
uv run portfoliomaster optimize --load tests/reports --min 5 --max 5 --corr 0.3 --print
uv run portfoliomaster optimize --load tests/reports --min 5 --max 5 --montecarlo 2000 --output ./results
uv run portfoliomaster adherence --mt5-dir tests/reports --sqx-dir tests/reports-sqx
```

---

## Comandos principais

### `--load <dir>`

Carrega relatórios HTML de uma pasta. Se `cache.parquet` existir e for compatível, ele é usado antes do reparse dos HTMLs.

### `--list`

Lista as estratégias carregadas com métricas básicas.

### `optimize`

Executa a otimização brute force do portfólio. Quando combinado com `--greedy`, usa crescimento incremental a partir do melhor seed, mas continua dentro da família de busca do comando `optimize`.

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

Exemplos:

```bash
# Brute-force padrão
uv run portfoliomaster optimize --load tests/reports --min 3 --max 5 --corr 0.3 --print

# Greedy
uv run portfoliomaster optimize --load tests/reports --greedy --min 5 --corr 0.3 --print

# Genetic Algorithm (ideal para grande número de estratégias)
uv run portfoliomaster optimize-genetic --load tests/reports --min 10 --max 15 --corr 0.2 --print --ga-population 300 --ga-generations 100

# Suprimir mensagens INFO (exibir apenas resultados e erros)
uv run portfoliomaster optimize --load tests/reports --min 5 --quiet --print

# Salvar resultados em CSV
uv run portfoliomaster optimize --min 3 --max 5 --save results.csv

# Exportar histórico de trades do melhor portfólio
uv run portfoliomaster optimize --min 5 --save-trades trades.parquet

# Importar e visualizar um JSON de portfólio salvo
uv run portfoliomaster optimize --import-p my_portfolio.json --report
```

### `optimize-genetic`

Executa a otimização via algoritmo genético. Esse comando existe separado para deixar explícito quando estamos saindo da busca exaustiva e entrando em um motor heurístico/estocástico com parâmetros próprios.

Quando usado com `--ga-loop <N>`, o comando roda o GA `N` vezes com seeds diferentes e mantém um rank global acumulado dos melhores portfólios encontrados entre todos os loops. O universo de estratégias não é podado entre iterações; o que se acumula é o ranking de combos.

Flags específicas mais usadas:

| Flag | Descrição |
|---|---|
| `--ga-loop <N>` | Roda o algoritmo genético em `N` loops e mantém um rank global acumulado |
| `--ga-population <N>` | Tamanho da população (padrão: 300) |
| `--ga-generations <N>` | Número de gerações (padrão: 100) |
| `--ga-crossover <F>` | Probabilidade de crossover (padrão: 0.7) |
| `--ga-mutation <F>` | Probabilidade de mutação (padrão: 0.2) |

Também aceita as mesmas flags gerais de `optimize` para carga, filtro, ranking, correlação, exportação e Monte Carlo.

No modo `--ga-loop`, quando `--output <dir>` é informado, o comando gera:
- um `rank.json` final consolidado
- um `report.html` final consolidado
- subpastas `loop_01`, `loop_02`, ... com os artefatos de cada execução
- `multi_ga_summary.json` com o resumo das iterações

Exemplos:

```bash
# Genetic Algorithm com parâmetros padrão
uv run portfoliomaster optimize-genetic --load tests/reports --min 10 --max 15 --corr 0.2 --print

# Genetic Algorithm em múltiplos loops com rank global acumulado
uv run portfoliomaster optimize-genetic --load tests/reports --min 10 --max 15 --corr 0.2 --ga-loop 5 --top 10

# Genetic Algorithm em múltiplos loops com artefatos por loop + consolidado final
uv run portfoliomaster optimize-genetic --load tests/reports --min 10 --max 15 --corr 0.2 --ga-loop 5 --top 10 --output ./results/ga_loop_run

# Genetic Algorithm com ajuste explícito da busca
uv run portfoliomaster optimize-genetic --load tests/reports --min 10 --max 15 --corr 0.2 --ga-population 300 --ga-generations 100 --ga-crossover 0.7 --ga-mutation 0.2
```

---

## Subcomandos auxiliares

```bash
uv run portfoliomaster inspect correlations
uv run portfoliomaster inspect strategy EA_Momentum_v2 --chart
uv run portfoliomaster cache info
uv run portfoliomaster cache list
uv run portfoliomaster cache rebuild tests/reports
uv run portfoliomaster cache clear
uv run portfoliomaster cache delete "EstrategiaA,EstrategiaB"
uv run portfoliomaster cache add "EstrategiaA,EstrategiaB" --dir tests/reports
uv run portfoliomaster cache save backup.parquet
uv run portfoliomaster cache load backup.parquet
uv run portfoliomaster cache merge cache_a.parquet cache_b.parquet merged.parquet
uv run portfoliomaster adherence --mt5-dir tests/reports --sqx-dir tests/reports-sqx
uv run portfoliomaster drawdown pairing --target 4000 --tick 0.1
uv run portfoliomaster config show
uv run portfoliomaster config validate
```

### `inspect correlations`

Mostra a matriz/pairs de correlação entre estratégias carregadas.

### `inspect strategy <name>`

Mostra métricas detalhadas de uma estratégia, com matching exato ou parcial.

### `cache info | list | rebuild | clear | delete | add | save | load | merge`

- `info` exibe tamanho, número de estratégias e intervalo de datas.
- `list` lista todas as estratégias armazenadas no cache com métricas (mesmo layout do `--list`).
- `rebuild` reprocessa os HTMLs e recria o cache.
- `clear` remove o arquivo de cache.
- `delete <nomes>` remove estratégias específicas do cache (suporta lista separada por vírgula).
- `add <nomes> --dir <path>` adiciona estratégias específicas ao cache buscando em um diretório.
- `save <destino>` salva um snapshot do cache em um arquivo externo.
- `load <origem>` carrega um snapshot salvo para o cache ativo.
- `merge <left> <right> <destino>` mescla dois snapshots em um único arquivo (estratégias duplicadas são sobrescritas pelo `right`).

**Nota:** O cache é composto por dois arquivos: `cache.parquet` (dados de trade) e `cache_lots.json` (tamanhos de lote representativos extraídos automaticamente dos relatórios). Os comandos `save`, `load` e `merge` gerenciam ambos os arquivos automaticamente.

### `config show | validate`

- `show` exibe a configuração efetiva.
- `validate` valida o JSON e os tipos dos campos.

### `adherence`

Compara relatórios do StrategyQuant X (SQX) com os do MetaTrader 5 (MT5). Valida se a estratégia foi exportada corretamente, comparando o número de trades, o RetDD e a correlação de Pearson entre as curvas de equity. Os arquivos são pareados pelo **stem** (nome base) do arquivo.

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

---

## Modos de Otimização

O PortfolioMaster oferece três engines de otimização, cada um adequado para cenários diferentes.

### Brute-Force (padrão)

Testa exaustivamente toda combinação possível de estratégias dentro dos limites `--min` e `--max`. Garante encontrar o portfólio matematicamente ótimo, mas torna-se computacionalmente inviável (dias/semanas de processamento) e intensivo em memória rapidamente à medida que o número de estratégias cresce. Recomendado para até 25–30 estratégias.

### Greedy (`--greedy`)

Começa com a melhor estratégia individual e iterativamente adiciona a próxima melhor estratégia não-correlacionada até atingir o tamanho do portfólio. É uma abordagem heurística rápida, ideal para quando se precisa de um portfólio "bom o suficiente" a partir de um conjunto grande. Pode levar a uma solução localmente ótima, não o ótimo global.

### Algoritmo Genético (`optimize-genetic`)

Usa princípios de computação evolutiva (seleção, crossover, mutação) para explorar o espaço de busca. Ideal para encontrar soluções de alta qualidade em vastos espaços de busca onde brute-force é impossível. Recomendado para 30+ estratégias. É um processo estocástico — duas execuções idênticas podem produzir resultados ligeiramente diferentes, mas ainda de alta qualidade.

---

## Pipeline de Otimização (BruteForceEngine)

O núcleo em `services/optimization.py` segue este fluxo:

1. Constrói matriz de trades ampla `(timestamps × strategies)` float64
2. Computa matriz de correlação par a par filtrada por período (H/D/W/M)
3. Gera todas as combinações de k ativos via `itertools.combinations`
4. Filtra batches por correlação máxima par a par ≤ `max_corr`
5. Cálculo vetorizado de métricas via NumPy: `trade_matrix @ strategy_mask`
6. Rastreia top-N resultados com um min-heap (inserções O(log N))
7. Computa métricas no estilo MT5 completas apenas para os top portfólios

**Modo Greedy:** executa brute-force para o tamanho semente (`--min`), depois iterativamente adiciona a estratégia que mais melhora a métrica de ranking respeitando o threshold de correlação.

**Técnicas de performance preservadas:**
- Vetorização em NumPy para calcular portfólios em lote
- `np.maximum.accumulate` para drawdown sem loop Python
- Batching em filtro de correlação e álgebra matricial
- `multiprocessing` no motor de otimização quando `num_workers > 1`
- `tqdm` para feedback de execução

---

## Monte Carlo

`services/montecarlo.py` implementa uma simulação por permutação da ordem dos trades. Objetivo:

- Medir a sensibilidade da curva de equity à ordem dos trades
- Comparar drawdown original com distribuição de drawdowns simulados
- Gerar uma leitura mais robusta de risco

Saída:
- Distribuição de `MaxDD`
- Distribuição de `RetDD`
- Resumo estatístico
- Gráfico HTML com equity curves e histogramas

---

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

---

## Parser MT5 e Portfolio Manager

`utils/mt5_parser.py` e `services/portfolio.py` fazem a ponte entre HTML e o motor de cálculo. Características principais:

- Suporta encodings UTF-8, UTF-16 e Latin-1
- Reconhece relatórios em PT e EN
- Extrai o **Lote Representativo** (mediana da coluna Volume) de cada estratégia automaticamente
- Padroniza nomes de colunas para o formato interno
- Centraliza a lógica de correlação periódica (H, D, W, M) para consistência entre CLI e motor de otimização

**Princípio central:** toda a otimização roda sobre **100% do histórico de trades** (trade a trade, não barra a barra). O filtro de correlação usa **correlação máxima por par** (não média) — cada par deve satisfazer independentemente o threshold.

---

## Cache

O cache é composto por dois arquivos para garantir reuso total do estado processado:

- `cache.parquet`: Trades consolidados com uma coluna de tempo e uma coluna por estratégia. Carrega em <1s vs 30–60s para parsing HTML bruto.
- `cache_lots.json`: Sidecar contendo os lotes representativos extraídos dos relatórios.

Ambos são lidos do diretório de trabalho atual. O cache é sensível ao contexto do diretório e ao formato esperado das colunas; cai para re-parsing HTML se inválido ou ausente.

---

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

`AppConfig` (Pydantic BaseSettings) aplica a seguinte ordem de precedência:

1. Argumentos CLI
2. `config.json`
3. Variáveis de ambiente / `.env`
4. Defaults embutidos

---

## Estrutura do projeto

```text
src/portfoliomaster/
├── main.py                     # Parsing de argumentos e roteamento principal
├── api/
│   └── cli.py                  # PortfolioCLI: orquestrador da aplicação e shell interativo
├── core/
│   ├── config.py               # AppConfig (Pydantic BaseSettings)
│   └── exceptions.py           # Hierarquia de exceções customizadas
├── services/
│   ├── adherence.py            # Validação SQX vs MT5 e geração de relatórios
│   ├── metrics.py              # compute_vector_metrics(), calculate_metrics_from_deals()
│   ├── montecarlo.py           # Simulação Monte Carlo
│   ├── optimization.py         # BruteForceEngine: brute-force + greedy + multiprocessing
│   └── portfolio.py            # PortfolioManager: armazenamento e métricas por estratégia
└── utils/
    ├── help.py                 # Texto de ajuda unificado para CLI e shell interativo
    ├── logger.py               # setup_logger(): console + file handler (log.log)
    ├── mt5_parser.py           # MT5ReportParser: parsing HTML (multi-encoding)
    ├── sqx_parser.py           # Parsing de CSV do SQX para fluxos de aderência
    └── visualizer.py           # plot_portfolio_equity(), generate_portfolio_report_html()
```

### Fluxo de dados

```
User (CLI / -i shell)
  → PortfolioCLI (src/portfoliomaster/api/cli.py)
    → MT5ReportParser.parse_report()     → deals DataFrame (ou cache.parquet)
    → PortfolioManager.add_strategy()    → Polars DataFrames por estratégia
    → BruteForceEngine.run()             → lista de portfólios ranqueados
    → visualizer / CSV / JSON export
```

---

## Desenvolvimento

```bash
# Rodar todos os testes
uv run pytest tests/ -v

# Arquivo de teste específico
uv run pytest tests/test_engine.py -v

# Comandos rápidos para validação localizada
uv run pytest tests/test_config.py tests/test_cli.py tests/test_engine.py -q
uv run pytest tests/test_main_validation.py -q

# Lint (com auto-fix) e formatação
uv run ruff check --fix . && uv run ruff format .

# Type checking (sem strict)
uv run mypy src/portfoliomaster/
```

O mypy está configurado com `check_untyped_defs`, `warn_return_any` e `no_implicit_optional`. Bibliotecas sem stubs oficiais (pandas, plotly, tqdm) são silenciadas via `[[tool.mypy.overrides]]` no `pyproject.toml`.

### Convenções de desenvolvimento

- **Vetorização primeiro:** Sempre prefira operações vetorizadas NumPy/Polars em vez de loops Python.
- **Processamento em lotes:** Use batching para filtragem de correlação e álgebra de matrizes para gerenciar memória.
- **Normalização MT5:** Relatórios MT5 usam locales inconsistentes (PT/EN). Use `MT5ReportParser` e `services.metrics.clean_mt5_numeric_string()` para normalização.
- Ao tocar CLI, valide `main.py` e `tests/test_main_validation.py` junto com `tests/test_cli.py`.
- Ao tocar otimização, valide no mínimo `tests/test_engine.py` e os testes específicos de brute-force/greedy.
- Ao tocar parsing ou normalização, valide com dados reais em `tests/reports/`.
- `tests/test_brute_force_consistency.py` é o teste de regressão principal do motor.

### Dívida técnica e ressalvas

- **Parsing HTML:** Relatórios MT5 são frágeis; atualizações no MT5 podem requerer ajustes no parser em `utils/mt5_parser.py`.
- **Multiprocessing:** Habilitado em execuções de otimização via CLI; o comportamento depende da plataforma e da contagem de estratégias.
- **Limites de memória:** Brute-force pode ficar sem memória para grandes conjuntos de ativos (>25-30). Use `--greedy` ou `optimize-genetic` para esses casos.

### Pontos de evolução naturais

- Versionar execuções com um manifesto de parâmetros
- Adicionar `results --format json` no CLI
- Separar melhor "casos de uso" em vez de concentrar lógica na classe `PortfolioCLI`
- Fortalecer o cache com fingerprint de arquivos
- Ampliar validação de robustez com Monte Carlo e walk-forward
