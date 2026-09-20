"""Acceso a DynamoDB.

Los nombres de tabla llegan por variable de entorno (los inyecta SAM) para que
el mismo código sirva en dev y en prod sin cambios.
"""

import os
from decimal import Decimal
from functools import lru_cache

import boto3


@lru_cache(maxsize=1)
def _resource():
    # El recurso se cachea entre invocaciones: reusar la conexión TCP entre
    # ejecuciones en caliente es lo que mantiene la latencia baja.
    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    endpoint = os.environ.get("DYNAMODB_ENDPOINT")  # DynamoDB Local
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)


def table(env_var: str):
    """Tabla cuyo nombre vive en la variable de entorno `env_var`."""
    name = os.environ.get(env_var)
    if not name:
        raise RuntimeError(f"Falta la variable de entorno {env_var}")
    return _resource().Table(name)


def decimal(value: float | int | str) -> Decimal:
    """DynamoDB no acepta `float`: todo número decimal viaja como `Decimal`.

    Se convierte pasando por `str` para no arrastrar el error de representación
    binaria del float (2.6 guardado como 2.60000000000000008881784197001...).
    """
    return Decimal(str(value))


def reset_cache():
    """Solo para tests: fuerza a reconstruir el cliente."""
    _resource.cache_clear()
