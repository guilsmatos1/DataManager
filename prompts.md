# TradeMachine — Guia do Workspace

## Visão Geral do Projeto

TradeMachine é um monorepo Python 3.12+ para sistemas de trading financeiro, organizado com **Arquitetura Polylith** e gerenciado com `uv`.

O projeto gerencia:

- **DataManager**: Serviço centralizado de dados de mercado e macroeconomia, com ingestão e atualização de OHLCV em TimescaleDB, agregações de timeframe, séries econômicas FRED e automação de atualizações
- **TradingMonitor**: Monitoramento em tempo real de trades MT5 via TimescaleDB
- **PortfolioMaster**: Otimização de portfólios e análise de backtesting
- **BacktestEngine**: Backtesting baseado em NautilusTrader

**Projeto pessoal — decisões de design priorizam simplicidade sobre escalabilidade enterprise.**

- **Usuário único** — sem multi-usuário, sem deploy comercial
- Rate limiting em memória apenas (sem Redis) — aceitável para single uvicorn worker
- Sem requisitos de horizontal scaling ou caching distribuído
- Simplicidade sobre completude de funcionalidades em todas as decisões arquiteturais

---

## Estrutura do Projeto (Polylith)

```
bases/        → Pontos de entrada (APIs, CLIs, TCP servers, Lambdas)
components/   → Lógica de negócio pura e reutilizável (sem dependências de bases)
projects/     → Configurações de build que combinam bases + componentes em artefatos finais
```

**Namespace principal**: `trademachine` — todos os imports internos seguem `from trademachine.<componente> import ...`

Exemplos de localização típica:

- Lógica de negócio: `components/<name>/src/trademachine/...`
- Entry points: `bases/<name>/src/trademachine/...`
- Produtos executáveis: `projects/<name>/`
- Testes: `components/<name>/test/trademachine/<name>/` (ex: `components/tradingmonitor/test/trademachine/tradingmonitor/`)
- CI: `.github/workflows/ci.yml`

### Componentes

| Componente | Propósito |
|------------|-----------|
| `datamanager` | Serviço centralizado de dados: ingestão OHLCV M1-first, armazenamento em TimescaleDB, agregações contínuas, séries econômicas FRED e agendamento de atualizações |
| `tradingmonitor` | Ingestão TCP do MT5, armazenamento TimescaleDB, métricas (Sharpe, drawdown, ...) |
| `portifoliomaster` | Parsing de relatórios HTML do MT5, otimização bruta de portfólios |
| `backtestengine` | Backtesting baseado em NautilusTrader |
| `mt5` | Parsing de formato de dados do MetaTrader 5 |
| `core` | Utilitários de logger compartilhados |

### Bases (Entry Points)

| Base | Interface |
|------|-----------|
| `datamanager_api` | FastAPI REST API (porta 8686) |
| `datamanager_cli` | CLI interativa |
| `trading_monitor_ingestion` | Daemon de ingestão TCP |
| `trading_monitor_cli` | CLI do TradingMonitor |
| `trading_monitor_dashboard` | Interface de dashboard |
| `portifolio_master_cli` | CLI do PortfolioMaster |
| `backtest_engine_cli` | CLI de Backtest |

### Sub-projetos

- `projects/datamanager` — Serviço centralizado de dados de mercado e macroeconomia
  - Componente: `components/datamanager`
  - Bases: `bases/datamanager_api`, `bases/datamanager_cli`
- `projects/tradingmonitor` — Monitoramento em tempo real para MT5 via TimescaleDB e FastAPI
- `projects/portifoliomaster` — Otimização de portfólios e análise de aderência SQX/MT5
- `projects/backtestengine` — Engine de backtest baseada em NautilusTrader

---

## Regras de Isolamento de Camadas

Components (lógica de negócio) **não podem** importar de bases (entry points). Isso mantém a lógica portável e testável.

- `trademachine.datamanager` → não pode importar de nenhuma base
- `trademachine.tradingmonitor` → não pode importar de nenhuma base
- `trademachine.portifoliomaster` → não pode importar de nenhuma base
- `trademachine.backtestengine` → não pode importar de nenhuma base
- `trademachine.core` → não pode importar de nenhuma base
- `trademachine.mt5` → não pode importar de nenhuma base

> Components **podem** importar de outros components.

---

## Convenções de Desenvolvimento

1. **Novas funcionalidades**: Criar como **Components** → `poly create component --name <nome>`
2. **Novos entry points**: Criar como **Bases** → `poly create base --name <nome>`
3. **Imports**: Nunca importar de `bases` para `components`
4. **Configurações**: Usar Pydantic Settings e armazenar no `.env` na raiz do projeto

### Estilo de Código e Nomenclatura

Seguir os padrões Ruff configurados em `pyproject.toml`:

- 4 espaços de indentação
- Linhas de até 88 caracteres
- Sintaxe Python 3.12
- `snake_case` para módulos, funções e arquivos de teste
- `PascalCase` para classes
- Type hints explícitos em APIs públicas
- Lógica de domínio reutilizável em `components/`; CLIs, APIs e dashboards em `bases/`

---

## Comandos de Instalação e Desenvolvimento

```bash
# Instalar dependências do workspace e de dev
uv sync --dev
```

### Entry Points Principais

```bash
# DataManager
uv run datamanager -i                         # CLI interativa
uv run uvicorn trademachine.datamanager_api.router:app  # REST API

# TradingMonitor
uv run trading-monitor start-ingestion        # Daemon de ingestão TCP
uv run trading-monitor setup-db               # Inicializar TimescaleDB

# PortfolioMaster
uv run portifoliomaster -i                    # CLI interativa
```

---

## Comandos de Teste

```bash
# Executar todos os testes
uv run pytest

# Arquivo específico
uv run pytest tests/unit/test_file.py -v

# Pacote específico
uv run pytest components/datamanager/test/

# Pular testes de integração
uv run pytest -m "not integration"
uv run pytest -m not integration
```

### Diretrizes de Testes

- Framework: **Pytest**, com coverage habilitado para `components/`
- Nomear arquivos de teste como `test_*.py`
- Fixtures em `conftest.py`
- O repositório define um marker `integration` para testes que precisam de banco de dados real; excluir com `-m "not integration"` quando necessário
- Adicionar testes na mesma área de pacote alterada para manter o comportamento do componente isolado

---

## Comandos de Linting e Formatação

```bash
# Verificar erros e estilo
uv run ruff check .

# Verificar formatação (sem aplicar)
uv run ruff format --check .

# Aplicar correções automáticas e formatar
uv run ruff check --fix . && uv run ruff format .

# Workflow pós-implementação (sempre rodar após editar arquivos Python)
uv run ruff check --fix . && uv run ruff format .
```

---

## Checagem de Tipos

```bash
# Validar integridade dos tipos (Pydantic plugin ativo)
uv run mypy .

# Alvo específico
uv run mypy components/datamanager/src/
```

---

## Verificação Arquitetural e de Qualidade

Sempre rodar antes de commitar para garantir que não há violações de arquitetura ou degradação de qualidade:

```bash
# Visão geral do workspace
uv tool run --from polylith-cli poly info

# Validar integridade e imports (Polylith)
uv tool run --from polylith-cli poly check

# Validar contratos de camadas e proibição de imports entre bases
uv run lint-imports

# Validar consistência de bibliotecas
uv tool run --from polylith-cli poly libs

# Validar dependências não utilizadas/faltantes
uv run deptry .

# Complexidade Ciclomática (Radon)
uv run radon cc . -a

# Índice de Manutenibilidade (Radon)
uv run radon mi .

# Bloqueio por alta complexidade — CLAUDE.md usa E, GEMINI.md usa B (verificar pyproject.toml)
uv run xenon --max-absolute E .

# Detecção de código morto
uv run vulture . --min-confidence 80

# Testes de mutação — valida eficácia dos testes
uv run mutmut run && uv run mutmut results
```

### Gate de Qualidade Completo (Local)

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

---

## Banco de Dados

Para projetos com banco de dados, rodar migrations a partir do diretório do projeto relevante:

```bash
# Exemplo para o DataManager
cd projects/datamanager
uv run alembic upgrade head
```

---

## Pre-commit Hooks

Hooks configurados em `.pre-commit-config.yaml`, executados automaticamente:

- `ruff` (lint + format)
- `import-linter` (isolamento de camadas)
- `polylith-check`
- `xenon` (complexidade)
- `vulture` (código morto)
- `gitleaks` (secrets)

```bash
# Executar manualmente
uv run pre-commit run --all-files
```

---

## Limpeza e Manutenção

```bash
# Análise de código morto
uv run vulture . --min-confidence 80

# Limpeza de dependências não utilizadas
uv run deptry .

# Sincronização Polylith
uv tool run --from polylith-cli poly check

# Limpeza de cache e artefatos
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type d -name ".pytest_cache" -exec rm -rf {} +
find . -type d -name ".ruff_cache" -exec rm -rf {} +
find . -type d -name ".mypy_cache" -exec rm -rf {} +
```

---

## Convenções de Commit e Pull Request

Histórico recente favorece **Conventional Commits** curtos:

- `fix: ...`
- `chore: ...`
- `refactor(portifoliomaster): ...`

Manter mensagens no imperativo e escopadas ao pacote afetado quando útil.

PRs devem:

- Resumir as mudanças de comportamento
- Listar componentes/bases/projetos impactados
- Linkar issues relacionadas
- Incluir screenshots ou saída de CLI/API quando UI ou workflows de operador mudarem

---

## Configuração de Ambiente

Copiar `.env.example` para `.env` e configurar:

- `DATAMANAGER_API_KEY` — autenticação da REST API
- `DATABASE_URL` — conexão TimescaleDB usada pelos projetos com persistência, incluindo DataManager e TradingMonitor
- `FRED_API_KEY` — chave necessária para busca e ingestão de séries econômicas FRED no DataManager
- Token do bot Telegram para notificações

> **Não commitar secrets ou arquivos `.env` locais.**
> Fixtures de teste grandes e relatórios gerados já existem em alguns diretórios `test/`; evitar adicionar novos artefatos volumosos a menos que sejam necessários para reproduzir comportamento.

---

## Documentação Específica por Projeto

Cada projeto possui documentação detalhada:

- `projects/datamanager/CLAUDE.md` — Arquitetura e workflows do DataManager
- `projects/tradingmonitor/CLAUDE.md` — Arquitetura do TradingMonitor
- `projects/portifoliomaster/CLAUDE.md` — Arquitetura do PortfolioMaster

> Este arquivo (`prompts.md`) é a fonte da verdade para a arquitetura do monorepo. Instruções específicas de sub-projetos nos arquivos de contexto complementam este documento.
