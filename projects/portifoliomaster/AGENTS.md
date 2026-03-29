# AGENTS.md

Guia operacional para agentes que trabalham neste repositório.

## Resumo do Projeto

- Nome do pacote: `portifoliomaster`
- Stack principal: Python 3.12, `uv`, NumPy, Polars, Pandas, Plotly, Pydantic, BeautifulSoup, lxml
- Tipo de aplicação: CLI local para parsing de relatórios HTML do MetaTrader 5, otimização de portfólios, relatório HTML, Monte Carlo e aderência MT5 vs SQX
- Entrypoints:
  - `uv run portifoliomaster`
  - Entry point em `bases/portifolio_master_cli/pyproject.toml`:
    `portifoliomaster = "trademachine.portifolio_master_cli.main:main"`

Não assuma API web/FastAPI neste repositório. A documentação legada menciona isso, mas o código atual versionado é centrado em CLI.

## Estrutura Real

- `src/portifoliomaster/main.py`: parser de argumentos, subcomandos e validação inicial
- `src/portifoliomaster/api/cli.py`: orquestração principal (`PortifolioCLI`)
- `src/portifoliomaster/core/config.py`: `AppConfig`, leitura de `config.json`, `.env` e defaults
- `src/portifoliomaster/services/optimization.py`: brute-force, greedy e multiprocessing
- `src/portifoliomaster/services/portfolio.py`: armazenamento e consolidação das estratégias
- `src/portifoliomaster/services/metrics.py`: métricas vetorizadas
- `src/portifoliomaster/services/montecarlo.py`: simulação Monte Carlo
- `src/portifoliomaster/services/adherence.py`: aderência MT5 vs SQX
- `src/portifoliomaster/utils/mt5_parser.py`: parsing de HTML MT5
- `src/portifoliomaster/utils/sqx_parser.py`: parsing de CSV do SQX
- `src/portifoliomaster/utils/visualizer.py`: geração de relatórios e gráficos HTML
- `tests/`: suíte pytest com dados reais em `tests/reports/`

## Ambiente e Comandos

Instalação:

```bash
uv sync --dev
```

Comandos comuns:

```bash
uv run portifoliomaster -i
uv run portifoliomaster --load tests/reports --list
uv run portifoliomaster --load tests/reports --optimize --min 5 --max 5 --corr 0.3 --print
uv run portifoliomaster adherence --mt5-dir tests/reports --sqx-dir tests/reports-sqx
uv run pytest tests/ -v
uv run ruff check --fix .
uv run ruff format .
```

Comandos rápidos para validação localizada:

```bash
uv run pytest tests/test_config.py tests/test_cli.py tests/test_engine.py -q
uv run pytest tests/test_main_validation.py -q
```

## Convenções Operacionais

- Sempre execute a partir da raiz do repositório.
- Prefira `uv run ...` em vez de chamar o Python da `.venv` diretamente.
- O projeto usa layout `src/`; os testes já dependem disso via `pyproject.toml`.
- O cache padrão fica no diretório de trabalho atual:
  - `cache.parquet`
  - `cache_lots.json`
- O log padrão vai para `log.log`.
- `config.json` é opcional; `AppConfig.from_json()` cai para `.env` e defaults.

## Regras de Implementação

- Preserve a abordagem vetorizada. Evite loops Python em caminhos quentes se NumPy/Polars resolverem.
- Mudanças em parsing devem considerar relatórios MT5 em PT e EN.
- Mudanças em otimização devem respeitar a regra atual de correlação máxima por par, não média.
- Não trate `README.md`, `CLAUDE.md` ou `GEMINI.md` como fonte de verdade sem conferir o código.
- Ao tocar CLI, valide `main.py` e `tests/test_main_validation.py` junto com `tests/test_cli.py`.
- Ao tocar otimização, valide no mínimo `tests/test_engine.py` e os testes específicos de brute-force/greedy correlatos.
- Ao tocar parsing ou normalização, valide com dados reais em `tests/reports/`.

## Artefatos e Cuidado com o Worktree

- Este repositório pode estar intencionalmente sujo. Não reverta mudanças existentes sem pedido explícito.
- Não apague caches, logs, outputs ou arquivos de relatório só para “limpar” o ambiente.
- Arquivos como `cache.parquet`, `cache_lots.json`, `log.log` e diretórios de saída podem refletir uso local do usuário.
- Se criar artefatos temporários para teste, prefira `tmp_path` nos testes ou caminhos temporários fora do fluxo principal.

## Estratégia de Verificação

Após editar Python:

```bash
uv run ruff check --fix .
uv run ruff format .
```

Depois rode o menor subconjunto relevante de testes. Se a mudança for transversal, rode:

```bash
uv run pytest tests/ -v
```

Observação: parte da suíte usa datasets reais e pode ser mais lenta que testes unitários puros.

## Estado Validado ao Criar Este Arquivo

- `pyproject.toml` confirma Python `>=3.12`
- o entrypoint publicado é `portifoliomaster = "trademachine.portifolio_master_cli.main:main"`
- a suíte `tests/test_config.py tests/test_cli.py tests/test_engine.py` passou localmente
- resultado observado: `44 passed`
