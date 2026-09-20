"""Carga los handlers de varios microservicios dentro de una misma prueba.

Cada servicio tiene su propio `app.py`, así que un `import app` normal
devolvería siempre el mismo módulo cacheado para los tres. Aquí se cargan por
ruta y con un nombre de módulo distinto cada uno, tal como ocurre en AWS, donde
cada función vive en su propio proceso.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(service_dir: str):
    """Carga `services/<service_dir>/app.py` como un módulo independiente."""
    module_name = f"skillpath_svc_{service_dir}"
    path = ROOT / "services" / service_dir / "app.py"

    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Se registra antes de ejecutarlo para que un reimport dentro del propio
    # módulo encuentre esta instancia y no cree otra.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def wire(monkeypatch, **targets):
    """Redirige `call(env_var, payload)` al handler del servicio destino.

    En AWS esto es una invocación Lambda real; aquí se salta solo la red: el
    payload, el router y la acción interna son los mismos.

        wire(monkeypatch, FLASHCARDS_FUNCTION=flashcards, PROGRESS_FUNCTION=progress)
    """
    from skillpath_common import invoke

    def fake_call(env_var, payload):
        module = targets.get(env_var)
        if module is None:
            raise AssertionError(f"Llamada inesperada a {env_var}: {payload}")
        return module.lambda_handler(payload)

    monkeypatch.setattr(invoke, "call", fake_call)
    return fake_call
