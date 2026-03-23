# TradeMachine Workspace (Polylith Architecture)

`TradeMachine` é um monorepo para gestão de dados financeiros, monitoramento de trades, otimização de portfólios e backtesting, agora seguindo a **Arquitetura Polylith**.

## Arquitetura Polylith

O projeto está organizado em:
- **`components/`**: Lógica de negócio pura e reutilizável (ex: `datamanager`).
- **`bases/`**: Pontos de entrada (APIs, CLIs, Lambdas).
- **`projects/`**: Configurações de build que combinam componentes e bases em artefatos finais.

### Namespace Principal: `trademachine`
Todos os imports internos devem seguir o padrão: `from trademachine.<componente> import ...`

---

## Estrutura do Workspace

### 1. [DataManager](./DataManager/) (Em migração para Polylith)
- **Componente:** `components/datamanager`
- **Bases:** `bases/datamanager_api`, `bases/datamanager_cli`
- **Projeto:** `projects/datamanager`

### 2. [TradingMonitor](./TradingMonitor/)
- Real-time monitoring para MT5 via TimescaleDB e FastAPI.

### 3. [PortifolioMaster](./PortifolioMaster/)
- Otimização de portfólios e análise de aderência SQX/MT5.

### 4. [BacktestEngine](./BacktestEngine/)
- Engine de backtest baseada em NautilusTrader.

---

## Desenvolvimento e Comandos

Este workspace utiliza [uv](https://docs.astral.sh/uv/) e [polylith-cli](https://github.com/DavidVujic/python-polylith).

### Instalação
```bash
uv sync --dev
```

### Verificação Arquitetural (Polylith & Imports)
Sempre rode estas verificações antes de commitar para garantir que não há violações de arquitetura (imports cruzados inválidos ou dependências faltando):

```bash
uv tool run --from polylith-cli poly info   # Visão geral do workspace
uv tool run --from polylith-cli poly check  # Valida integridade e imports (Polylith)
uv run lint-imports                         # Valida contratos de camadas e proibição de bases
uv run deptry .                             # Valida dependências não utilizadas, faltantes ou transitivas
uv tool run --from polylith-cli poly libs   # Valida consistência de bibliotecas
```

### Testes e Qualidade
```bash
# Executar todos os testes
uv run pytest

# Linting e Formatação
uv run ruff check .
uv run ruff format .

# Type Checking
uv run mypy .
```

---

## Convenções de Desenvolvimento

1. **Novas Funcionalidades:** Devem ser criadas como **Components** (`poly create component --name <nome>`).
2. **Novos Entry Points:** Devem ser criados como **Bases** (`poly create base --name <nome>`).
3. **Imports:** Nunca importe de `bases` para `components`. Components podem importar de outros components.
4. **Configurações:** Use Pydantic Settings e armazene no `.env` na raiz.

### Hierarquia de Contexto
Este arquivo é a fonte da verdade para a arquitetura do monorepo. Instruções específicas de sub-projetos nos arquivos `GEMINI.md` locais (ex: `DataManager/GEMINI.md`) complementam este documento.
