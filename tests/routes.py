"""Tabla de rutas leída de los serverless.yml.

Se lee de ahí y no de una lista escrita a mano para que las pruebas y la
colección de Postman ejerciten exactamente las rutas que se despliegan. Si
alguien cambia una ruta en el serverless.yml y no en el escenario, la prueba
falla.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("auth", "topics", "flashcards", "progress", "quiz", "ia")

_PARAM = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _load(service):
    path = ROOT / "services" / service / "serverless.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def route_table():
    """[(servicio, método, ruta, nombre_del_handler)] de los seis servicios."""
    rows = []
    for service in SERVICES:
        config = _load(service)
        for function in config["functions"].values():
            handler = function["handler"].split(".", 1)[1]
            for event in function.get("events", []):
                http = event.get("httpApi")
                if not http:
                    continue
                rows.append((service, http["method"].upper(), http["path"], handler))
    return rows


def public_routes():
    """Las rutas de la API, sin las internas."""
    return [r for r in route_table() if not r[2].startswith("/internal/")]


def pattern_for(path):
    """`/quiz/{quizId}/submit` → expresión que captura quizId."""
    return re.compile("^" + _PARAM.sub(r"(?P<\1>[^/]+)", path) + "$")


def resolve_handler(service, method, path):
    """Encuentra el handler y los parámetros de ruta de una petición concreta."""
    # Las rutas más específicas primero: /me/decks antes que /me/{algo}.
    candidates = sorted(
        (r for r in route_table() if r[0] == service and r[1] == method),
        key=lambda r: -len(r[2]),
    )
    for _, _, template, handler in candidates:
        match = pattern_for(template).match(path)
        if match:
            return handler, match.groupdict()
    raise LookupError(f"Ruta no declarada en {service}/serverless.yml: {method} {path}")
