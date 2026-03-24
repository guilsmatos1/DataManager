# Arquivo de whitelist para o Vulture ignorar falsos positivos
# Para adicionar uma exceção, use o formato:
# my_unused_function  # unused function (vulture: ignore)

# Exceções comuns para frameworks
# app = FastAPI()\
# @app.get("/")

# Unreachable code after while True (false positives)
# vulture: ignore
"while True"

# Test mocks & lambda args (false positives from @patch decorators and SQLAlchemy shims)
"mock_open"  # noqa: used as @patch argument injected by pytest
"kw"  # noqa: lambda argument in SQLite type compiler shim
"type_"  # noqa: lambda argument in SQLite type compiler shim
