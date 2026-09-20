"""Envoltura de los handlers Lambda para API Gateway HTTP API (payload v2).

Se usan handlers planos en vez de FastAPI/Flask (observación #22): API Gateway
ya resuelve el routing, así que un framework web dentro de Lambda solo añade
cold start y peso.
"""

import functools
import json
import logging
import os
from decimal import Decimal

from .errors import ApiError, Unauthenticated, ValidationError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

CORS_HEADERS = {
    "Access-Control-Allow-Origin": os.environ.get("CORS_ORIGIN", "*"),
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
}


class _Encoder(json.JSONEncoder):
    """DynamoDB devuelve números como Decimal; JSON no sabe serializarlos."""

    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


def response(status: int, body: dict | None = None, request_id: str = "") -> dict:
    payload = dict(body or {})
    if status >= 400 and request_id:
        payload["requestId"] = request_id
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": json.dumps(payload, cls=_Encoder, ensure_ascii=False),
    }


def body_of(event: dict) -> dict:
    """Parsea el body JSON. Un body ausente se trata como objeto vacío."""
    raw = event.get("body")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("El cuerpo de la petición no es JSON válido.") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("El cuerpo de la petición debe ser un objeto JSON.")
    return parsed


def path_param(event: dict, name: str) -> str:
    value = (event.get("pathParameters") or {}).get(name)
    if not value:
        raise ValidationError(f"Falta el parámetro «{name}» en la ruta.")
    return value


def query_params(event: dict) -> dict:
    return event.get("queryStringParameters") or {}


def current_user_id(event: dict) -> str:
    """userId resuelto por el authorizer.

    Nunca se lee de la ruta ni del body (observación #3): el token es la única
    fuente de identidad, así que no existe forma de pedir datos de otro usuario.
    """
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    user_id = (authorizer.get("lambda") or authorizer).get("userId")
    if not user_id:
        raise Unauthenticated()
    return user_id


def handler(func):
    """Convierte excepciones en respuestas y registra logs estructurados."""

    @functools.wraps(func)
    def wrapper(event, context):
        request_id = (event.get("requestContext") or {}).get("requestId", "")
        try:
            status, body = func(event, context)
            return response(status, body, request_id)
        except ApiError as exc:
            logger.warning(
                "api_error",
                extra={"code": exc.code, "status": exc.status, "requestId": request_id},
            )
            return response(exc.status, exc.to_dict(), request_id)
        except Exception:
            logger.exception("unhandled_error requestId=%s", request_id)
            return response(500, ApiError().to_dict(), request_id)

    return wrapper
