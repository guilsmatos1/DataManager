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

### Verificação Arquitetural e de Qualidade
Sempre rode estas verificações antes de commitar para garantir que não há violações de arquitetura ou degradação da qualidade:

```bash
uv tool run --from polylith-cli poly info   # Visão geral do workspace
uv tool run --from polylith-cli poly check  # Valida integridade e imports (Polylith)
uv run lint-imports                         # Valida contratos de camadas e proibição de bases
uv run deptry .                             # Valida dependências não utilizadas/faltantes
uv run radon cc . -a                        # Relatório de Complexidade Ciclomática (Radon)
uv run radon mi .                           # Relatório de Índice de Manutenibilidade (Radon)
uv run xenon --max-absolute B .             # Bloqueio por alta complexidade (Xenon)
uv tool run --from polylith-cli poly libs   # Valida consistência de bibliotecas
```

### Testes e Qualidade
Sempre execute as validações antes de qualquer alteração significativa.

**1. Linting e Formatação (Ruff):**
```bash
uv run ruff check .   # Verifica erros e estilo
uv run ruff format .  # Formata o código automaticamente
```

**2. Checagem de Tipos (Mypy):**
```bash
uv run mypy .         # Valida a integridade dos tipos (Pydantic plugin ativo)
```

**3. Testes de Mutação (Mutmut):**
> Valida a eficácia dos seus testes. Se o teste não "matar" a mutação, o teste é fraco.
```bash
uv run mutmut run      # Executa as mutações
uv run mutmut results  # Mostra o sumário dos sobreviventes
```

**4. Testes Automatizados (Pytest):**
```bash
uv run pytest          # Executa a suíte de testes
```

---

## Limpeza e Manutenção
Para manter o código limpo e livre de artefatos desnecessários:

**1. Correções Automáticas (Ruff):**
> Aplica correções automáticas (imports não usados, sintaxe obsoleta).
```bash
uv run ruff check --fix .
```

**2. Análise de Código Morto (Vulture):**
> Encontra funções, classes e variáveis que nunca são utilizadas.
```bash
uv run vulture . --min-confidence 80
```

**3. Limpeza de Dependências (Deptry):**
> Identifica dependências instaladas mas não utilizadas no código.
```bash
uv run deptry .
```

**4. Sincronização Polylith:**
> Sincroniza o `catalog.json` e a estrutura do Polylith.
```bash
uv tool run --from polylith-cli poly check
```

**5. Limpeza de Cache e Artefatos:**
> Remove caches de ferramentas e arquivos compilados.
```bash
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type d -name ".pytest_cache" -exec rm -rf {} +
find . -type d -name ".ruff_cache" -exec rm -rf {} +
find . -type d -name ".mypy_cache" -exec rm -rf {} +
```

---

## Convenções de Desenvolvimento

1. **Novas Funcionalidades:** Devem ser criadas como **Components** (`poly create component --name <nome>`).
2. **Novos Entry Points:** Devem ser criados como **Bases** (`poly create base --name <nome>`).
3. **Imports:** Nunca importe de `bases` para `components`. Components podem importar de outros components.
4. **Configurações:** Use Pydantic Settings e armazene no `.env` na raiz.

### Hierarquia de Contexto
Este arquivo é a fonte da verdade para a arquitetura do monorepo. Instruções específicas de sub-projetos nos arquivos `GEMINI.md` locais (ex: `DataManager/GEMINI.md`) complementam este documento.
