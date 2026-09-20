"""Crea las 7 tablas en DynamoDB simulado, a partir de `infra/spec.py`.

Se generan desde la misma especificación que produce la guía de despliegue,
así que las pruebas corren contra exactamente la estructura que se va a crear
a mano en la consola de AWS. Si las claves divergieran, no habría forma de
notarlo hasta producción.
"""

import boto3

from infra.spec import TABLES, table_name

STAGE = "test"


def _key_schema(pk, sk):
    schema = [{"AttributeName": pk[0], "KeyType": "HASH"}]
    if sk:
        schema.append({"AttributeName": sk[0], "KeyType": "RANGE"})
    return schema


def _definition(short: str) -> dict:
    spec = TABLES[short]
    attributes = {spec["pk"]}
    if spec["sk"]:
        attributes.add(spec["sk"])

    indexes = []
    for index in spec["indexes"]:
        attributes.add(index["pk"])
        if index.get("sk"):
            attributes.add(index["sk"])
        projection = {"ProjectionType": index["projection"]}
        if index["projection"] == "INCLUDE":
            projection["NonKeyAttributes"] = index["included"]
        indexes.append(
            {
                "IndexName": index["name"],
                "KeySchema": _key_schema(index["pk"], index.get("sk")),
                "Projection": projection,
            }
        )

    definition = {
        "KeySchema": _key_schema(spec["pk"], spec["sk"]),
        "AttributeDefinitions": [
            {"AttributeName": name, "AttributeType": kind}
            for name, kind in sorted(attributes)
        ],
    }
    if indexes:
        definition["GlobalSecondaryIndexes"] = indexes
    return definition


def create_all() -> dict:
    """Crea las 7 tablas y devuelve {nombre_corto: nombre_completo}."""
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    names = {}
    for short in TABLES:
        full = table_name(STAGE, short)
        ddb.create_table(TableName=full, BillingMode="PAY_PER_REQUEST", **_definition(short))
        names[short] = full
    return names
