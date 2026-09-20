"""Ejecuta los escenarios de extremo a extremo en memoria.

Sin AWS y sin desplegar: la tabla de rutas de `infra/spec.py` y los handlers
reales, con DynamoDB simulado. Es lo que garantiza que la colección de Postman
generada a partir de estos mismos escenarios esté bien antes de subir nada.
"""

import pytest
from moto import mock_aws

from tests.e2e.runner import capture_into, check_failures, resolve
from tests.e2e.scenarios import SCENARIOS


@pytest.fixture(scope="module")
def _entorno():
    """Una sola sesión compartida: los escenarios continúan uno del otro."""
    import os

    from skillpath_common import db

    with mock_aws():
        from tests.fixtures.tables import create_all

        names = create_all()
        anterior = {}
        for short, full in names.items():
            var = short.upper().replace("-", "_") + "_TABLE"
            anterior[var] = os.environ.get(var)
            os.environ[var] = full
        os.environ["FLASHCARDS_FUNCTION"] = "flashcards"
        os.environ["PROGRESS_FUNCTION"] = "progress"
        db.reset_cache()

        yield names

        for var, valor in anterior.items():
            if valor is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = valor
        db.reset_cache()


@pytest.fixture(scope="module")
def gateway(_entorno, request):
    from _pytest.monkeypatch import MonkeyPatch

    from tests.fixtures.gateway import Gateway

    patch = MonkeyPatch()
    request.addfinalizer(patch.undo)
    gw = Gateway(patch)

    # Catálogo de temas, igual que lo deja `make seed` en un despliegue real.
    sembrar_catalogo(gw)
    return gw


def sembrar_catalogo(gateway):
    import json
    import pathlib

    from skillpath_common.db import table

    seed_dir = pathlib.Path(__file__).resolve().parents[2] / "seed"
    flashcards = gateway.modules["flashcards-service"]

    for topic in json.loads((seed_dir / "topics.json").read_text(encoding="utf-8")):
        cards = json.loads(
            (seed_dir / f"flashcards-{topic['topicId']}.json").read_text(encoding="utf-8")
        )
        flashcards.lambda_handler({
            "internalAction": "createCards",
            "data": {"topicId": topic["topicId"], "cards": cards},
        })
        table("TOPICS_TABLE").put_item(Item={
            **topic, "cardCount": len(cards), "visibility": "public",
            "createdAt": "2026-09-01T00:00:00Z",
        })


@pytest.fixture(scope="module")
def variables():
    """Token, ids y demás datos que un paso deja para los siguientes."""
    return {"email": "lucia.e2e@universidad.edu"}


def _casos():
    """Un caso de prueba por ejecución, expandiendo las repeticiones."""
    for scenario in SCENARIOS:
        for step in scenario.steps:
            for sufijo, extra in step.expand():
                yield pytest.param(
                    step, extra, id=f"{scenario.name} · {step.name}{sufijo}"
                )


@pytest.mark.parametrize("step,extra", list(_casos()))
def test_paso(gateway, variables, step, extra):
    contexto = {**variables, **extra}

    status, payload = gateway.request(
        step.method,
        resolve(step.path, contexto),
        body=resolve(step.body, contexto) if step.body is not None else None,
        query=resolve(step.query, contexto) if step.query else None,
        token=variables.get("token") if step.auth else None,
    )

    problemas = check_failures(step, status, payload, contexto)
    assert not problemas, "\n".join(f"  · {p}" for p in problemas)

    # Lo capturado sí persiste entre pasos: es el token, los ids, etc.
    capture_into(step, payload, variables)
