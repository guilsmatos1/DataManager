# Arquivo de whitelist para o Vulture ignorar falsos positivos
# Para adicionar uma exceção, use o formato:
# my_unused_function  # unused function (vulture: ignore)

# Exceções comuns para frameworks
# app = FastAPI()
# @app.get("/")

# Unreachable code after while True (false positives)
# vulture: ignore
"while True"

# Test mocks & lambda args (false positives from @patch decorators and SQLAlchemy shims)
"mock_open"  # injected by @patch — used as positional arg by pytest
"kw"  # lambda arg in SQLite BigInteger type compiler shim
"type_"  # lambda arg in SQLite BigInteger type compiler shim
