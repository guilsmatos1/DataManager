# PortfolioMaster

PortfolioMaster usa uma CLI baseada em subcomandos para carregar relatórios MT5, otimizar portfólios, validar aderência MT5 vs SQX e operar sobre cache local.

## Contrato Atual da CLI

- `uv run portfoliomaster load reports/`
- `uv run portfoliomaster optimize --load reports/ --min 3 --max 5 --top 10`
- `uv run portfoliomaster optimize-genetic --load reports/ --min 10 --max 15 --top 10`
- `optimize-genetic --ga-loop <N>`
- `uv run portfoliomaster benchmark --load reports/ --min 3 --max 5`
- `cache save <PATH>`
- `cache load <PATH>`
- `cache merge <A> <B> <C>`
- `optimize --greedy-loops <N>`
- `optimize --prune-cache`
- `optimize --exclude-strats <L>`
- `adherence --export-passed-reports`
- `pairing --load reports/ --output pairing.csv`

## Notas Operacionais

- Use `uv sync --dev` para instalar dependências.
- Use `uv run pytest` para a suíte completa.
- Use `uv run ruff check --fix . && uv run ruff format .` para lint e formatação.
- A documentação deve permanecer alinhada entre `GEMINI.md`, `CLAUDE.md` e `AGENTS.md`.

## Restrições

- Não documente exemplos do contrato legado baseado em flags globais.
- Não documente o formato antigo de pairing aninhado em drawdown.
- Não documente o fluxo antigo de carregar e listar via flags globais.
