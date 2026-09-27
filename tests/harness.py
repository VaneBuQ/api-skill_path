"""Monta los seis microservicios en memoria, con DynamoDB simulado.

Cada servicio se carga como un módulo independiente —igual que en AWS, donde
cada función vive en su propio proceso— y las llamadas HTTP entre servicios se
redirigen al handler correspondiente. Lo único que se salta es la red.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
STAGE = "test"

# Nombre de tabla por variable de entorno, igual que los serverless.yml.
TABLES = {
    "USERS_TABLE": ("auth-table", "userId", None),
    "TOPICS_TABLE": ("topics-catalog", "topicId", None),
    "USER_TOPICS_TABLE": ("topics-user", "userId", "topicId"),
    "CARDS_TABLE": ("flashcards-cards", "topicId", "cardId"),
    "REVIEWS_TABLE": ("flashcards-reviews", "userId", "topicCardId"),
    "PROGRESS_TABLE": ("progress-table", "userId", "topicId"),
    "ATTEMPTS_TABLE": ("quiz-attempts", "userId", "quizId"),
    "CHECKS_TABLE": ("ia-checks", "userId", "checkId"),
}

CATALOG_INDEX = {
    "IndexName": "catalog-index",
    "KeySchema": [
        {"AttributeName": "visibility", "KeyType": "HASH"},
        {"AttributeName": "name", "KeyType": "RANGE"},
    ],
    "Projection": {"ProjectionType": "ALL"},
}


def create_tables():
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    for env_var, (short, pk, sk) in TABLES.items():
        name = f"{short}-{STAGE}"
        attributes = [{"AttributeName": pk, "AttributeType": "S"}]
        keys = [{"AttributeName": pk, "KeyType": "HASH"}]
        if sk:
            attributes.append({"AttributeName": sk, "AttributeType": "S"})
            keys.append({"AttributeName": sk, "KeyType": "RANGE"})

        extra = {}
        if env_var == "TOPICS_TABLE":
            attributes += [
                {"AttributeName": "visibility", "AttributeType": "S"},
                {"AttributeName": "name", "AttributeType": "S"},
            ]
            extra["GlobalSecondaryIndexes"] = [CATALOG_INDEX]

        ddb.create_table(
            TableName=name, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=attributes, KeySchema=keys, **extra,
        )
        os.environ[env_var] = name


def load_service(name):
    """Carga services/<name>/handler.py como un módulo con nombre propio."""
    module_name = f"skillpath_{name}_handler"
    sys.modules.pop(module_name, None)
    path = ROOT / "services" / name / "handler.py"

    # El handler hace `from common import ...`; se resuelve desde su carpeta.
    service_dir = str(path.parent)
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)
    sys.modules.pop("common", None)

    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Ruta interna → (servicio, nombre del handler)
INTERNAL_ROUTES = {
    "/internal/cards": ("flashcards", "internal_create_cards"),
    "/internal/cards/list": ("flashcards", "internal_list_cards"),
    "/internal/cards/get": ("flashcards", "internal_get_card"),
    "/internal/cards/delete": ("flashcards", "internal_delete_card"),
    "/internal/cards/delete-topic": ("flashcards", "internal_delete_topic_cards"),
    "/internal/reviews/delete-topic": ("flashcards", "internal_delete_topic_reviews"),
    "/internal/reviews/studied": ("flashcards", "internal_studied_count"),
    "/internal/progress/card-reviewed": ("progress", "internal_card_reviewed"),
    "/internal/progress/quiz-completed": ("progress", "internal_quiz_completed"),
    "/internal/progress/remove-topic": ("progress", "internal_remove_topic"),
}


class Cluster:
    """Los seis servicios, con las llamadas entre ellos conectadas."""

    def __init__(self, monkeypatch):
        for env_var in ("FLASHCARDS_API_BASE", "PROGRESS_API_BASE"):
            os.environ[env_var] = "https://interno.test"

        self.services = {
            name: load_service(name)
            for name in ("auth", "topics", "flashcards", "progress", "quiz", "ia")
        }

        def fake_call(base_url, path, method="POST", payload=None, timeout=8):
            target = INTERNAL_ROUTES.get(path)
            if target is None:
                raise AssertionError(f"Ruta interna desconocida: {path}")
            service, handler_name = target
            module = self.services[service]
            result = getattr(module, handler_name)({
                "body": json.dumps(payload or {}),
                "headers": {"x-internal-key": os.environ["INTERNAL_KEY"]},
            })
            body = json.loads(result["body"]) if result.get("body") else {}
            return body if result["statusCode"] < 400 else {"error": body.get("error")}

        # Cada handler importó `call_service` por nombre, así que hay que
        # sustituir la referencia que guardó cada módulo.
        for module in self.services.values():
            if hasattr(module, "call_service"):
                monkeypatch.setattr(module, "call_service", fake_call)

    def call(self, service, handler_name, *, token=None, path=None,
             body=None, query=None):
        event = {
            "pathParameters": path or {},
            "queryStringParameters": query,
            "headers": {"authorization": f"Bearer {token}"} if token else {},
        }
        if body is not None:
            event["body"] = json.dumps(body)
        result = getattr(self.services[service], handler_name)(event)
        payload = json.loads(result["body"]) if result.get("body") else None
        return result["statusCode"], payload
