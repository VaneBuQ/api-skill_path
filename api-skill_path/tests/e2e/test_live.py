"""Ejecuta los escenarios contra las APIs ya desplegadas en AWS.

Los mismos escenarios que corren en memoria, ahora por HTTP de verdad —
incluida la llamada al modelo, que aquí sí cuesta una fracción de céntimo.
Sirve para comprobar un despliegue recién hecho.

    AUTH_URL=https://... TOPICS_URL=https://... FLASHCARDS_URL=https://... \
    PROGRESS_URL=https://... QUIZ_URL=https://... IA_URL=https://... \
        make test-live

Sin esas variables las pruebas se saltan, así que `make test` sigue
funcionando sin AWS.
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

BASES = {
    "auth": os.environ.get("AUTH_URL", "").rstrip("/"),
    "topics": os.environ.get("TOPICS_URL", "").rstrip("/"),
    "flashcards": os.environ.get("FLASHCARDS_URL", "").rstrip("/"),
    "progress": os.environ.get("PROGRESS_URL", "").rstrip("/"),
    "quiz": os.environ.get("QUIZ_URL", "").rstrip("/"),
    "ia": os.environ.get("IA_URL", "").rstrip("/"),
}

FALTANTES = [s.upper() + "_URL" for s, url in BASES.items() if not url]

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        bool(FALTANTES),
        reason=f"Define {', '.join(FALTANTES)} para ejecutar contra AWS",
    ),
]


def http(service, method, path, *, body=None, token=None, query=None):
    url = BASES[service] + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=30) as raw:
            payload = raw.read()
            return raw.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, (json.loads(payload) if payload else None)


@pytest.fixture(scope="module")
def variables():
    # Correo único por ejecución: el primer paso crea la cuenta, y repetirlo
    # con el mismo correo chocaría contra la unicidad.
    return {"email": f"e2e-{uuid.uuid4().hex[:10]}@universidad.edu"}


def _casos():
    for scenario in SCENARIOS:
        for step in scenario.steps:
            for sufijo, extra in step.expand():
                yield pytest.param(step, extra, id=f"{scenario.name} · {step.name}{sufijo}")


@pytest.mark.parametrize("step,extra", list(_casos()))
def test_paso(variables, step, extra):
    contexto = {**variables, **extra}

    status, payload = http(
        step.service,
        step.method,
        resolve(step.path, contexto),
        body=resolve(step.body, contexto) if step.body is not None else None,
        query=resolve(step.query, contexto) if step.query else None,
        token=variables.get("token") if step.auth else None,
    )

    problemas = check_failures(step, status, payload, contexto)
    assert not problemas, "\n".join(f"  · {p}" for p in problemas)

    capture_into(step, payload, variables)
