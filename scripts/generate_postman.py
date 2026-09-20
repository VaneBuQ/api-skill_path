#!/usr/bin/env python3
"""Genera la colección de Postman desde los escenarios de `tests/e2e/scenarios.py`.

Los mismos escenarios que ejecuta `pytest` se convierten aquí en peticiones con
sus pruebas, así que la colección no puede quedarse atrás del código: si un
endpoint cambia, la prueba falla antes de que nadie abra Postman.

    python scripts/generate_postman.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.e2e.runner import resolve  # noqa: E402
from tests.e2e.scenarios import (  # noqa: E402
    ABSENT,
    EQ,
    EXISTS,
    GTE,
    LEN,
    SCENARIOS,
    STARTS,
)

OUT = ROOT / "docs" / "postman" / "SkillPath.postman_collection.json"

# En Postman las variables son {{nombre}}, igual que en los escenarios, así que
# las rutas y los cuerpos se copian tal cual.


def js_path(path: str) -> str:
    """`items[0].topicId` → `body.items[0].topicId`, apto para JavaScript."""
    return "body." + path


def tests_for(step) -> list[str]:
    lines = [
        "const body = pm.response.code === 204 ? {} : pm.response.json();",
        "",
        f'pm.test("Responde {step.status}", function () {{',
        f"    pm.response.to.have.status({step.status});",
        "});",
    ]

    for path, operator, expected in step.checks:
        target = js_path(path)
        if operator == EXISTS:
            titulo = f"{path} viene en la respuesta"
            assertion = f"pm.expect({target}).to.not.be.undefined;"
        elif operator == ABSENT:
            titulo = f"{path} NO viene en la respuesta"
            assertion = f"pm.expect({target}).to.be.undefined;"
        elif operator == EQ:
            titulo = f"{path} es {expected}"
            assertion = f"pm.expect({target}).to.eql({json.dumps(expected, ensure_ascii=False)});"
        elif operator == GTE:
            titulo = f"{path} es al menos {expected}"
            assertion = f"pm.expect({target}).to.be.at.least({json.dumps(expected)});"
        elif operator == LEN:
            titulo = f"{path} tiene {expected} elementos"
            assertion = f"pm.expect({target}).to.have.lengthOf({expected});"
        elif operator == STARTS:
            titulo = f"{path} empieza por {expected}"
            assertion = (
                f"pm.expect({target}).to.be.a('string');\n"
                f"    pm.expect({target}.startsWith({json.dumps(expected)})).to.be.true;"
            )
        else:
            raise AssertionError(f"Operador desconocido: {operator}")

        lines += ["", f'pm.test("{titulo}", function () {{', f"    {assertion}", "});"]

    if step.capture:
        lines += ["", "// Deja estos valores para los siguientes pasos"]
        for name, path in step.capture.items():
            lines.append(f'pm.collectionVariables.set("{name}", {js_path(path)});')

    return lines


def request_for(step, extra: dict, nombre: str) -> dict:
    # `extra` trae solo las variables de la repetición, que sí se sustituyen.
    # Las demás ({{token}}, {{quizId}}, {{deckId}}...) se dejan intactas: en
    # Postman son variables de colección que se rellenan al ejecutar.
    path = resolve(step.path, extra)
    raw = "{{baseUrl}}" + path

    request = {
        "method": step.method,
        "header": [],
        "url": {
            "raw": raw,
            "host": ["{{baseUrl}}"],
            "path": [p for p in path.split("/") if p],
        },
        "description": step.note or "",
    }

    if step.query:
        request["url"]["query"] = [
            {"key": k, "value": str(v)} for k, v in step.query.items()
        ]
        request["url"]["raw"] = raw + "?" + "&".join(
            f"{k}={v}" for k, v in step.query.items()
        )

    if step.auth:
        request["header"].append(
            {"key": "Authorization", "value": "Bearer {{token}}", "type": "text"}
        )

    if step.body is not None:
        request["header"].append(
            {"key": "Content-Type", "value": "application/json", "type": "text"}
        )
        body = resolve(step.body, extra) if extra else step.body
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, ensure_ascii=False, indent=2),
            "options": {"raw": {"language": "json"}},
        }

    return {
        "name": nombre,
        "request": request,
        "event": [
            {
                "listen": "test",
                "script": {"type": "text/javascript", "exec": tests_for(step)},
            }
        ],
        "response": [],
    }


def main() -> int:
    items, total = [], 0

    for scenario in SCENARIOS:
        peticiones = []
        for step in scenario.steps:
            for sufijo, extra in step.expand():
                peticiones.append(request_for(step, extra, step.name + sufijo))
                total += 1
        items.append({
            "name": scenario.name,
            "description": scenario.description,
            "item": peticiones,
        })

    collection = {
        "info": {
            "name": "SkillPath — API",
            "description": (
                "Generada desde tests/e2e/scenarios.py con "
                "`make postman`. No editar a mano: los cambios se pierden al "
                "regenerarla, y las mismas comprobaciones corren en pytest.\n\n"
                "Antes de ejecutarla, define la variable `baseUrl` con la URL de "
                "invocación de la etapa en API Gateway. El `token` se captura "
                "solo en el primer paso.\n\n"
                "Los escenarios se ejecutan **en orden**: cada uno continúa la "
                "sesión del anterior. Usa Collection Runner, no peticiones sueltas."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {
                "key": "baseUrl",
                "value": "https://TU-API.execute-api.us-east-1.amazonaws.com/dev",
                "type": "string",
            },
            {"key": "email", "value": "lucia.postman@universidad.edu", "type": "string"},
            {"key": "token", "value": "", "type": "string"},
            {"key": "userId", "value": "", "type": "string"},
            {"key": "quizId", "value": "", "type": "string"},
            {"key": "deckId", "value": "", "type": "string"},
        ],
        "item": items,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Escrito {OUT.relative_to(ROOT)}")
    print(f"   {len(SCENARIOS)} escenarios · {total} peticiones")
    print("\n   Importa el archivo en Postman, ajusta `baseUrl` y ejecútalo")
    print("   con Collection Runner: los pasos dependen unos de otros.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
