"""API Gateway simulado, construido desde `infra/spec.py`.

Recibe método y ruta, los empareja contra la tabla de rutas real, arma el
evento que enviaría API Gateway y llama al handler del servicio que
corresponde. Incluye el authorizer: valida el token y deja el `userId` en el
contexto, igual que en AWS.

Así los escenarios de extremo a extremo se pueden ejecutar sin desplegar nada,
y lo que verifican es la misma tabla de rutas que se teclea en la consola.
"""

import json
import re

from infra.spec import SERVICES
from tests.fixtures.services import load

# Nombre de la variable de entorno → servicio al que apunta.
INVOKE_TARGETS = {
    "FLASHCARDS_FUNCTION": "flashcards-service",
    "PROGRESS_FUNCTION": "progress-service",
}

_PARAM = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _pattern(path: str) -> re.Pattern:
    """`/quiz/{quizId}/submit` → expresión que captura quizId."""
    return re.compile("^" + _PARAM.sub(r"(?P<\1>[^/]+)", path) + "$")


def _routing_table():
    table = []
    for service, spec in SERVICES.items():
        for method, path, auth, _ in spec["routes"]:
            table.append((method, _pattern(path), path, auth, service))
    # Las rutas más específicas primero: /me/decks antes que /me/{algo}.
    return sorted(table, key=lambda r: -len(r[2]))


class Gateway:
    """Cliente HTTP falso contra los handlers cargados en memoria."""

    def __init__(self, monkeypatch):
        from skillpath_common import invoke

        self.routes = _routing_table()
        self.modules = {
            service: load(spec["code"].split("/")[-1])
            for service, spec in SERVICES.items()
            if service != "authorizer"
        }

        def fake_call(env_var, payload):
            target = INVOKE_TARGETS.get(env_var)
            if target is None:
                raise AssertionError(f"Invocación a un servicio desconocido: {env_var}")
            return self.modules[target].lambda_handler(payload)

        monkeypatch.setattr(invoke, "call", fake_call)
        for module in self.modules.values():
            if hasattr(module, "call"):
                monkeypatch.setattr(module, "call", fake_call)

    def request(self, method, path, *, body=None, token=None, query=None):
        """Devuelve (status, cuerpo decodificado)."""
        for route_method, pattern, template, auth, service in self.routes:
            if route_method != method:
                continue
            match = pattern.match(path)
            if not match:
                continue

            context = {"requestId": "e2e"}
            if auth != "NONE":
                claims = self._authorize(token)
                if claims is None:
                    # Lo que devuelve API Gateway cuando el authorizer deniega.
                    return 401, {"message": "Unauthorized"}
                context["authorizer"] = {"lambda": {"userId": claims["sub"]}}

            event = {
                "routeKey": f"{method} {template}",
                "rawPath": path,
                "pathParameters": match.groupdict(),
                "queryStringParameters": query,
                "requestContext": context,
            }
            if body is not None:
                event["body"] = json.dumps(body)

            response = self.modules[service].lambda_handler(event)
            payload = json.loads(response["body"]) if response.get("body") else None
            return response["statusCode"], payload

        return 404, {"message": "Not Found"}

    @staticmethod
    def _authorize(token):
        from skillpath_common.errors import Unauthenticated
        from skillpath_common.tokens import from_header

        if not token:
            return None
        try:
            return from_header(f"Bearer {token}")
        except Unauthenticated:
            return None
