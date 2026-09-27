"""Ejecuta los escenarios en memoria, contra los seis microservicios.

Sin AWS y sin desplegar: los handlers reales, DynamoDB simulado y las rutas
tomadas de los serverless.yml. Es lo que garantiza que la colección de Postman
generada a partir de estos mismos escenarios esté bien antes de subir nada.
"""

import json

import pytest
from moto import mock_aws

from tests.e2e.runner import capture_into, check_failures, resolve
from tests.e2e.scenarios import SCENARIOS
from tests.harness import Cluster, create_tables


def sembrar_catalogo(cluster):
    """Catálogo completo, igual que lo deja `make seed` en un despliegue real."""
    import os
    import pathlib

    import boto3

    seed_dir = pathlib.Path(__file__).resolve().parents[2] / "seed"
    topics = boto3.resource("dynamodb", region_name="us-east-1").Table(
        os.environ["TOPICS_TABLE"]
    )

    for topic in json.loads((seed_dir / "topics.json").read_text(encoding="utf-8")):
        cards = json.loads(
            (seed_dir / f"flashcards-{topic['topicId']}.json").read_text(encoding="utf-8")
        )
        cluster.services["flashcards"].internal_create_cards({
            "headers": {"x-internal-key": os.environ["INTERNAL_KEY"]},
            "body": json.dumps({"topicId": topic["topicId"], "cards": cards}),
        })
        topics.put_item(Item={
            **topic, "cardCount": len(cards), "visibility": "public",
            "createdAt": "2026-09-01T00:00:00Z",
        })


@pytest.fixture(scope="module")
def entorno(request):
    """Una sola sesión compartida: los escenarios continúan uno del otro."""
    from _pytest.monkeypatch import MonkeyPatch

    patch = MonkeyPatch()
    request.addfinalizer(patch.undo)

    with mock_aws():
        create_tables()
        cluster = Cluster(patch)
        sembrar_catalogo(cluster)

        # La llamada al modelo se simula: llamarla de verdad costaría dinero y
        # daría un veredicto distinto en cada ejecución. Contra una API
        # desplegada (test_live.py) sí se llama al modelo real.
        patch.setattr(
            cluster.services["ia"], "_call_model",
            lambda question, correct, user: json.dumps({
                "verdict": "correcta", "score": 90,
                "feedback": "Bien, mencionaste lo esencial del concepto.",
            }),
        )
        yield cluster


@pytest.fixture(scope="module")
def variables():
    return {"email": "sofia.escenarios@universidad.edu"}


def _casos():
    for scenario in SCENARIOS:
        for step in scenario.steps:
            for sufijo, extra in step.expand():
                yield pytest.param(step, extra, id=f"{scenario.name} · {step.name}{sufijo}")


@pytest.mark.parametrize("step,extra", list(_casos()))
def test_paso(entorno, variables, step, extra):
    contexto = {**variables, **extra}

    status, payload = entorno.request(
        step.service,
        step.method,
        resolve(step.path, contexto),
        body=resolve(step.body, contexto) if step.body is not None else None,
        query=resolve(step.query, contexto) if step.query else None,
        token=variables.get("token") if step.auth else None,
    )

    problemas = check_failures(step, status, payload, contexto)
    assert not problemas, "\n".join(f"  · {p}" for p in problemas)

    # Lo capturado persiste entre pasos: el token, los identificadores, etc.
    capture_into(step, payload, variables)
