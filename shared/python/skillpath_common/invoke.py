"""Llamadas entre microservicios (Lambda → Lambda).

Decisión de la observación #6: en vez de DynamoDB Streams, los servicios se
llaman entre sí de forma síncrona. Es más simple de operar y tiene una ventaja
real: cuando la API responde, el progreso ya está actualizado, así que
`POST /review` puede devolver el porcentaje nuevo en la misma respuesta.

Ningún servicio toca tablas ajenas; solo invoca funciones ajenas.
"""

import json
import logging
import os
from functools import lru_cache

import boto3
from botocore.config import Config

logger = logging.getLogger()


@lru_cache(maxsize=1)
def _client():
    return boto3.client(
        "lambda",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        # Timeout corto: si el servicio destino no responde rápido preferimos
        # seguir adelante antes que hacer esperar al usuario.
        #
        # Y sin reintentos: una invocación puede haberse ejecutado aunque la
        # respuesta no llegue, así que reintentar aplicaría el efecto dos veces.
        # Perder la actualización es preferible a duplicar el XP de un repaso;
        # los contadores se envían como valores absolutos justamente para que
        # una pérdida se corrija sola en el siguiente repaso.
        config=Config(connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 1}),
    )


def call(env_var: str, payload: dict) -> dict | None:
    """Invoca la función nombrada en `env_var` y devuelve su respuesta.

    Devuelve None si la llamada falla. Quien llama decide qué hacer: en el flujo
    de repaso, la review ya quedó guardada antes de llegar aquí, así que un
    fallo se registra y se responde igual (el progreso es recalculable).
    """
    function_name = os.environ.get(env_var)
    if not function_name:
        raise RuntimeError(f"Falta la variable de entorno {env_var}")
    try:
        result = _client().invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        body = json.loads(result["Payload"].read() or b"null")
        if result.get("FunctionError"):
            logger.error("invoke_failed target=%s error=%s", function_name, body)
            return None
        return body
    except Exception:
        logger.exception("invoke_error target=%s", function_name)
        return None


def reset_cache():
    """Solo para tests."""
    _client.cache_clear()
