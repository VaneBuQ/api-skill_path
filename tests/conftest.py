"""Configuración común de las pruebas.

Las pruebas unitarias no tocan AWS: la lógica de negocio vive en módulos puros
y DynamoDB se simula con moto. Eso permite correr `make test` sin credenciales
ni conexión.
"""

import os

import pytest

# Debe fijarse antes de importar cualquier módulo que lea la configuración.
os.environ.setdefault("JWT_SECRET", "secreto-solo-para-pruebas")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


@pytest.fixture
def frozen_today(monkeypatch):
    """Fija la fecha «de hoy» para que las pruebas de racha sean deterministas."""
    from skillpath_common import dates

    def _freeze(value: str):
        from datetime import datetime

        fixed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=dates.LIMA)
        monkeypatch.setattr(dates, "now", lambda: fixed)
        return value

    return _freeze
