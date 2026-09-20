"""Ejecuta los escenarios contra una API ya desplegada.

Los mismos escenarios que corren en memoria, ahora por HTTP de verdad. Sirve
para comprobar un despliegue recién hecho a mano en la consola.

    API_BASE_URL=https://xxx.execute-api.us-east-1.amazonaws.com/dev \\
        make test-live

Sin esa variable las pruebas se saltan, así que `make test` sigue funcionando
sin AWS ni credenciales.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

from tests.e2e.runner import capture_into, check_failures, resolve
from tests.e2e.scenarios import SCENARIOS

BASE_URL = os.environ.get("API_BASE_URL", "").rstrip("/")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL, reason="Define API_BASE_URL para ejecutar contra una API desplegada"
    ),
]


def http(method, path, *, body=None, token=None, query=None):
    url = BASE_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, (json.loads(raw) if raw else None)


@pytest.fixture(scope="module")
def variables():
    # Correo único por ejecución: el escenario crea una cuenta, y repetirlo con
    # el mismo correo chocaría contra la unicidad.
    return {"email": f"e2e-{uuid.uuid4().hex[:10]}@universidad.edu"}


def _casos():
    for scenario in SCENARIOS:
        for step in scenario.steps:
            for sufijo, extra in step.expand():
                yield pytest.param(
                    step, extra, id=f"{scenario.name} · {step.name}{sufijo}"
                )


@pytest.mark.parametrize("step,extra", list(_casos()))
def test_paso(variables, step, extra):
    contexto = {**variables, **extra}

    status, payload = http(
        step.method,
        resolve(step.path, contexto),
        body=resolve(step.body, contexto) if step.body is not None else None,
        query=resolve(step.query, contexto) if step.query else None,
        token=variables.get("token") if step.auth else None,
    )

    problemas = check_failures(step, status, payload, contexto)
    assert not problemas, "\n".join(f"  · {p}" for p in problemas)

    capture_into(step, payload, variables)
