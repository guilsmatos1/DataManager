# Commands
uv sync --dev                                           # install deps
uv run pytest                                           # all tests
uv run pytest -m "not integration"                      # skip integration
uv run lint-imports                                     # validate layers
uv run xenon --max-absolute D .                         # complexity
uv run vulture . --min-confidence 80                    # dead code
uv run pre-commit run --all-files                       # full gate

# Code Standards
Explicit type hints on public APIs.
Tests: Pytest, test_*.py files, fixtures in conftest.py.
Settings via Pydantic Settings + .env at project root.
Conventional Commits: fix:, chore:, refactor(component):
Never commit .env, secrets, or large fixtures.
Simplicity > enterprise scalability (personal project, single user).

# Architecture
Polylith: bases/ (entry points) | components/ (logic) | projects/ (build).
Namespace: from trademachine.<component> import ...
Components NEVER import from bases. Components may import each other.
New component: poly create component --name <name>
New entry point: poly create base --name <name>
Domain logic in components/; CLIs, APIs, dashboards in bases/.
Migrations in project dir: cd projects/<name> && uv run alembic upgrade head
Per-subproject docs: projects/{name}/{CLAUDE,GEMINI,AGENTS}.md
Validate architecture: poly check, lint-imports, poly libs.
Each component exposes a public.py as its public API. Bases import from public.py, not internals.
Component naming: single-domain → no separator (portfoliomaster, datamanager); sub-domain → underscore (tradingmonitor_storage, tradingmonitor_analytics).

# Workflow
1. Implement the requested functionality.
2. Run relevant tests: uv run pytest components/<changed>/test/
3. Validate layers: uv run lint-imports
4. Validate complexity: uv run xenon --max-absolute E .
5. Validate dead code: uv run vulture . --min-confidence 80
6. Check subproject docs if applicable.

# Common Mistakes
- Importing from bases inside components (violates Polylith isolation).
- Importing component internals directly in bases instead of using public.py.
- Not reading the subproject's CLAUDE.md before editing its code.
- Running migrations outside the project directory (cd projects/<name>).
- Using Redis/distributed infra — everything is in-memory, single-worker.
- Adding large fixtures or reports without proven need.
- Ignoring xenon/vulture — high complexity and dead code block CI.
- Writing business logic directly in bases instead of components.

# Do Nots
- DO NOT import from bases into components, ever.
- DO NOT design for multi-user, horizontal scaling, or Redis.
- DO NOT create entry points as components or logic in bases.
- DO NOT ignore pre-commit hooks (ruff, lint-imports, xenon, vulture).
- DO NOT add deps without checking with deptry and poly libs.
- DO NOT edit a subproject without consulting its CLAUDE.md first.

## Coding Standards & Clean Code
When writing code, STRICTLY adhere to these Clean Code principles:
- **Meaningful Names:** Use variable, function, and class names that reveal intent (e.g., `isUserAuthenticated` instead of `auth`).
- **Small Functions:** Functions should do one thing and remain concise.
- **DRY (Don't Repeat Yourself):** Eliminate redundancies by extracting logic into reusable components or utility functions.
- **Self-Explanatory:** Code must be readable enough to render "what" comments unnecessary; use comments only to explain the "why".
- **SOLID:** Apply SOLID principles, with a strong focus on Single Responsibility (SRP) and Open/Closed (OCP).
- **Error Handling:** Implement clear logging and predictable exception handling; never leave empty catch blocks.
