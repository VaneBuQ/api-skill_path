"""Creación de las 7 tablas en DynamoDB simulado.

Las definiciones espejan `template.yaml`: si una clave o un índice cambian allí
y no aquí, las pruebas dejan de representar la realidad. Por eso hay una prueba
(`test_infra_template.py`) que compara ambos.
"""

import boto3

TABLE_DEFS = {
    "users": {
        "KeySchema": [{"AttributeName": "userId", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "userId", "AttributeType": "S"}],
    },
    "topics": {
        "KeySchema": [{"AttributeName": "topicId", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "topicId", "AttributeType": "S"},
            {"AttributeName": "isActive", "AttributeType": "S"},
            {"AttributeName": "name", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "active-name-index",
                "KeySchema": [
                    {"AttributeName": "isActive", "KeyType": "HASH"},
                    {"AttributeName": "name", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    },
    "user-topics": {
        "KeySchema": [
            {"AttributeName": "userId", "KeyType": "HASH"},
            {"AttributeName": "topicId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "userId", "AttributeType": "S"},
            {"AttributeName": "topicId", "AttributeType": "S"},
        ],
    },
    "flashcards": {
        "KeySchema": [
            {"AttributeName": "topicId", "KeyType": "HASH"},
            {"AttributeName": "cardId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "topicId", "AttributeType": "S"},
            {"AttributeName": "cardId", "AttributeType": "S"},
        ],
    },
    "user-card-reviews": {
        "KeySchema": [
            {"AttributeName": "userId", "KeyType": "HASH"},
            {"AttributeName": "topicCardId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "userId", "AttributeType": "S"},
            {"AttributeName": "topicCardId", "AttributeType": "S"},
            {"AttributeName": "userTopicKey", "AttributeType": "S"},
            {"AttributeName": "nextReviewDate", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "due-index",
                "KeySchema": [
                    {"AttributeName": "userTopicKey", "KeyType": "HASH"},
                    {"AttributeName": "nextReviewDate", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    },
    "user-progress": {
        "KeySchema": [
            {"AttributeName": "userId", "KeyType": "HASH"},
            {"AttributeName": "topicId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "userId", "AttributeType": "S"},
            {"AttributeName": "topicId", "AttributeType": "S"},
        ],
    },
    "quiz-attempts": {
        "KeySchema": [
            {"AttributeName": "userId", "KeyType": "HASH"},
            {"AttributeName": "quizId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "userId", "AttributeType": "S"},
            {"AttributeName": "quizId", "AttributeType": "S"},
            {"AttributeName": "userTopicKey", "AttributeType": "S"},
            {"AttributeName": "startedAt", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "topic-attempt-index",
                "KeySchema": [
                    {"AttributeName": "userTopicKey", "KeyType": "HASH"},
                    {"AttributeName": "startedAt", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": ["score", "status", "topicId"],
                },
            }
        ],
    },
}

STAGE = "test"


def table_name(short: str) -> str:
    return f"skillpath-{STAGE}-{short}"


def create_all():
    """Crea las 7 tablas y devuelve {nombre_corto: nombre_completo}."""
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    names = {}
    for short, definition in TABLE_DEFS.items():
        full = table_name(short)
        ddb.create_table(
            TableName=full,
            BillingMode="PAY_PER_REQUEST",
            **definition,
        )
        names[short] = full
    return names
