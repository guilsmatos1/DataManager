from trademachine.datamanager.client import DataManagerClient as public_client
from trademachine.datamanager.db.database import engine as public_engine
from trademachine.datamanager.infrastructure.client import (
    DataManagerClient as internal_client,
)
from trademachine.datamanager.infrastructure.config import (
    settings as internal_settings,
)
from trademachine.datamanager.infrastructure.database import (
    engine as internal_engine,
)
from trademachine.datamanager.public import settings as public_settings


def test_client_facade_exposes_same_class():
    assert public_client is internal_client


def test_config_facade_exposes_same_settings_instance():
    assert public_settings is internal_settings


def test_database_facade_exposes_same_engine_instance():
    assert public_engine is internal_engine
