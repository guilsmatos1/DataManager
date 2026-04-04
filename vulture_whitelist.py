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


# PortifolioMaster False Positives
class Ignored:
    model_config = 1
    side_effect = 1


Ignored.model_config
Ignored.side_effect


def global_callback():
    pass


global_callback


def pairing():
    pass


pairing


def adherence():
    pass


adherence


def interactive():
    pass


interactive


def validate_corr_period():
    pass


validate_corr_period


def validate_rank_by():
    pass


validate_rank_by
