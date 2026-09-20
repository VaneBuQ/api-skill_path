"""Router mínimo para los handlers Lambda.

Cada microservicio es una sola función Lambda que atiende dos tipos de entrada:

1. Peticiones de API Gateway (HTTP API, payload v2). Se despachan por
   `routeKey`, que llega con la forma `"GET /flashcards/{topicId}"` — o sea,
   API Gateway ya hizo el trabajo de emparejar la ruta y no hace falta ningún
   framework web dentro de la Lambda (observación #22).

2. Llamadas de otro microservicio (observación #6), que llegan como
   `{"internalAction": "...", "data": {...}}`.

Mantener ambos en la misma función es lo que permite que el diagrama siga
mostrando cinco microservicios y que las flechas nuevas sean de servicio a
servicio, no a cajas auxiliares.
"""

import json
import logging
import os
from decimal import Decimal

from .errors import ApiError, NotFound
from .http import CORS_HEADERS, _Encoder

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


class Router:
    def __init__(self, name: str = ""):
        self.name = name
        self._http: dict[str, callable] = {}
        self._internal: dict[str, callable] = {}

    def route(self, method: str, path: str):
        """Registra un handler HTTP. `path` es la ruta tal como la declara SAM."""
        key = f"{method.upper()} {path}"

        def decorator(func):
            self._http[key] = func
            return func

        return decorator

    def internal(self, action: str):
        """Registra una acción invocable por otro microservicio."""

        def decorator(func):
            self._internal[action] = func
            return func

        return decorator

    # -- despacho -------------------------------------------------------------

    def _handle_internal(self, event):
        action = event["internalAction"]
        func = self._internal.get(action)
        if func is None:
            raise NotFound(f"Acción interna desconocida: {action}")
        # Las llamadas internas devuelven el dato crudo, sin envelope HTTP:
        # quien llama es otro servicio, no un navegador.
        return func(event.get("data") or {})

    def _handle_http(self, event, context):
        route_key = event.get("routeKey", "")
        func = self._http.get(route_key)
        if func is None:
            raise NotFound(f"Ruta no encontrada: {route_key}")
        return func(event, context)

    def _response(self, status, body, request_id):
        payload = dict(body or {})
        if status >= 400 and request_id:
            payload["requestId"] = request_id
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": json.dumps(payload, cls=_Encoder, ensure_ascii=False),
        }

    def as_handler(self):
        """Devuelve la función que SAM registra como `Handler`."""

        def lambda_handler(event, context=None):
            if "internalAction" in event:
                # Un fallo aquí debe propagarse para que el servicio que llamó
                # lo vea como FunctionError y decida qué hacer.
                return self._handle_internal(event)

            request_id = (event.get("requestContext") or {}).get("requestId", "")
            try:
                status, body = self._handle_http(event, context)
                return self._response(status, body, request_id)
            except ApiError as exc:
                logger.warning(
                    "api_error service=%s code=%s status=%s requestId=%s",
                    self.name, exc.code, exc.status, request_id,
                )
                return self._response(exc.status, exc.to_dict(), request_id)
            except Exception:
                logger.exception("unhandled_error service=%s requestId=%s", self.name, request_id)
                return self._response(500, ApiError().to_dict(), request_id)

        return lambda_handler


def to_number(value):
    """Convierte Decimal de DynamoDB a int/float de Python."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value
