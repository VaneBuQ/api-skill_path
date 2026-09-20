#!/usr/bin/env python3
"""Genera `docs/catalogo-apis.md` desde `infra/spec.py`.

La rúbrica pide «un Catálogo de Apis documentando todos los microservicios de su
Diagrama de Arquitectura». Se genera para que no pueda quedarse atrás del código.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infra.spec import SERVICES, TABLES, all_routes  # noqa: E402

OUT = ROOT / "docs" / "catalogo-apis.md"

# Historias de usuario que cubre cada servicio.
HISTORIAS = {
    "auth-service": "9, 10",
    "topics-service": "1, 8",
    "flashcards-service": "2, 3",
    "progress-service": "4, 5, 11",
    "quiz-service": "6",
}

# Errores propios de cada ruta, más allá de los transversales.
ERRORES = {
    ("POST", "/auth/register"): [
        ("400", "VALIDATION_ERROR", "Correo mal formado, contraseña de menos de 8 caracteres o nombre vacío"),
        ("409", "EMAIL_ALREADY_EXISTS", "Ese correo ya está registrado"),
    ],
    ("POST", "/auth/login"): [
        ("400", "VALIDATION_ERROR", "Falta el correo o la contraseña"),
        ("401", "INVALID_CREDENTIALS", "Mensaje genérico: no revela si falló el correo o la contraseña"),
    ],
    ("GET", "/auth/me"): [("404", "NOT_FOUND", "El token es válido pero la cuenta ya no existe")],
    ("POST", "/topics/{topicId}/follow"): [
        ("404", "TOPIC_NOT_FOUND", "El tema no existe, o es un mazo privado de otra persona"),
    ],
    ("DELETE", "/topics/{topicId}/follow"): [
        ("404", "NOT_FOUND", "El usuario no sigue ese tema"),
        ("409", "OWN_DECK_CANNOT_UNFOLLOW", "Un mazo propio se elimina, no se deja de seguir"),
    ],
    ("POST", "/me/decks"): [
        ("400", "VALIDATION_ERROR", "Falta el nombre o no hay ninguna tarjeta completa"),
        ("503", "DECK_CREATION_FAILED", "No se pudieron guardar las tarjetas"),
    ],
    ("GET", "/me/decks/{topicId}"): [("404", "NOT_FOUND", "El mazo no existe o no es del usuario")],
    ("PATCH", "/me/decks/{topicId}"): [
        ("400", "VALIDATION_ERROR", "Nombre vacío o demasiado largo"),
        ("404", "NOT_FOUND", "El mazo no existe o no es del usuario"),
    ],
    ("DELETE", "/me/decks/{topicId}"): [("404", "NOT_FOUND", "El mazo no existe o no es del usuario")],
    ("POST", "/me/decks/{topicId}/cards"): [
        ("400", "VALIDATION_ERROR", "Tarjeta sin pregunta o sin respuesta"),
        ("404", "NOT_FOUND", "El mazo no existe o no es del usuario"),
        ("503", "CARD_CREATION_FAILED", "No se pudieron guardar las tarjetas"),
    ],
    ("DELETE", "/me/decks/{topicId}/cards/{cardId}"): [
        ("404", "NOT_FOUND", "El mazo o la tarjeta no existen"),
    ],
    ("GET", "/flashcards/{topicId}"): [
        ("403", "NOT_FOLLOWING_TOPIC", "El usuario no sigue ese tema"),
    ],
    ("POST", "/flashcards/{cardId}/review"): [
        ("400", "VALIDATION_ERROR", "Falta `topicId`, que es parte de la clave de la tarjeta"),
        ("400", "INVALID_RATING", "La calificación no es forgot, hard ni easy"),
        ("403", "NOT_FOLLOWING_TOPIC", "El usuario no sigue ese tema"),
        ("404", "CARD_NOT_FOUND", "La tarjeta no existe en ese tema"),
    ],
    ("GET", "/progress/{topicId}"): [
        ("404", "PROGRESS_NOT_FOUND", "El usuario aún no ha repasado nada en ese tema"),
    ],
    ("POST", "/quiz/{topicId}/start"): [
        ("403", "NOT_FOLLOWING_TOPIC", "El usuario no sigue ese tema"),
        ("409", "NOT_ENOUGH_CONCEPTS", "Menos de 10 conceptos estudiados; `details` trae `studied`, `required` y `topicName`"),
    ],
    ("POST", "/quiz/{quizId}/submit"): [
        ("400", "UNKNOWN_QUESTION", "Una respuesta no pertenece a este quiz"),
        ("404", "QUIZ_NOT_FOUND", "El quiz no existe o es de otro usuario"),
        ("409", "QUIZ_ALREADY_SUBMITTED", "El quiz ya fue enviado"),
    ],
    ("GET", "/quiz/{quizId}"): [("404", "QUIZ_NOT_FOUND", "El quiz no existe o es de otro usuario")],
}

# Código de estado de las respuestas correctas, cuando no es 200.
ESTADOS = {
    ("POST", "/auth/register"): "201",
    ("POST", "/topics/{topicId}/follow"): "201 · 200 si ya lo seguía",
    ("POST", "/me/decks"): "201",
    ("POST", "/me/decks/{topicId}/cards"): "201",
    ("POST", "/quiz/{topicId}/start"): "201",
}

# Ejemplos de petición y respuesta.
EJEMPLOS = {
    ("POST", "/auth/register"): (
        '{\n  "name": "Lucía Mendoza",\n  "email": "lucia@universidad.edu",\n  "password": "Secreta123"\n}',
        '{\n  "userId": "usr_01J9X...",\n  "name": "Lucía Mendoza",\n  "email": "lucia@universidad.edu",\n'
        '  "initials": "LM",\n  "token": "eyJhbGciOi...",\n  "expiresIn": 86400,\n'
        '  "createdAt": "2026-09-21T14:30:00Z"\n}',
    ),
    ("POST", "/auth/login"): (
        '{\n  "email": "lucia@universidad.edu",\n  "password": "Secreta123"\n}',
        '{\n  "userId": "usr_01J9X...",\n  "name": "Lucía Mendoza",\n  "email": "lucia@universidad.edu",\n'
        '  "initials": "LM",\n  "token": "eyJhbGciOi...",\n  "expiresIn": 86400\n}',
    ),
    ("GET", "/topics"): (
        None,
        '{\n  "items": [\n    {\n      "topicId": "algebra-lineal",\n      "name": "Álgebra lineal",\n'
        '      "description": "Matrices, determinantes...",\n      "cardCount": 12,\n'
        '      "icon": "atom",\n      "level": "intermedio"\n    }\n  ]\n}',
    ),
    ("POST", "/topics/{topicId}/follow"): (
        None,
        '{\n  "topicId": "algebra-lineal",\n  "name": "Álgebra lineal",\n  "cardCount": 12,\n'
        '  "followedAt": "2026-09-21T14:31:00Z",\n  "alreadyFollowing": false\n}',
    ),
    ("GET", "/me/topics"): (
        None,
        '{\n  "items": [\n    {\n      "topicId": "algebra-lineal",\n      "name": "Álgebra lineal",\n'
        '      "cardCount": 12,\n      "icon": "atom",\n      "isOwn": false,\n'
        '      "followedAt": "2026-09-12T10:00:00Z"\n    }\n  ]\n}',
    ),
    ("POST", "/me/decks"): (
        '{\n  "name": "Apuntes de Cloud Computing",\n  "description": "Lo que entró en el parcial",\n'
        '  "cards": [\n    {\n      "question": "¿Qué es IaC?",\n'
        '      "answer": "Definir la infraestructura en archivos versionados.",\n'
        '      "hint": "No tiene que ver con la Parte C."\n    }\n  ]\n}',
        '{\n  "topicId": "deck_01J9XYZ...",\n  "name": "Apuntes de Cloud Computing",\n'
        '  "description": "Lo que entró en el parcial",\n  "cardCount": 1,\n'
        '  "icon": "book-open",\n  "isOwn": true,\n  "createdAt": "2026-09-21T19:00:00Z"\n}',
    ),
    ("GET", "/me/decks/{topicId}"): (
        None,
        '{\n  "topicId": "deck_01J9XYZ...",\n  "name": "Apuntes de Cloud Computing",\n'
        '  "cardCount": 3,\n  "cards": [\n    {\n      "cardId": "crd_0001",\n'
        '      "question": "¿Qué es IaC?",\n      "answer": "Definir la infraestructura...",\n'
        '      "hint": "No tiene que ver con la Parte C."\n    }\n  ]\n}',
    ),
    ("GET", "/flashcards/{topicId}"): (
        None,
        '{\n  "topicId": "algebra-lineal",\n  "topicName": "Álgebra lineal",\n  "dueCount": 12,\n'
        '  "cardsTotal": 12,\n  "cardsMastered": 0,\n  "xpAvailable": 60,\n  "items": [\n    {\n'
        '      "cardId": "crd_0001",\n      "question": "¿Cuándo una matriz es invertible?",\n'
        '      "answer": "Cuando su determinante es distinto de cero.",\n'
        '      "hint": "determinante ≠ 0...",\n      "position": 1,\n      "state": "new"\n    }\n  ]\n}',
    ),
    ("POST", "/flashcards/{cardId}/review"): (
        '{\n  "topicId": "algebra-lineal",\n  "rating": "easy"\n}',
        '{\n  "cardId": "crd_0001",\n  "topicId": "algebra-lineal",\n  "rating": "easy",\n'
        '  "repetitions": 1,\n  "easeFactor": 2.6,\n  "intervalDays": 1,\n'
        '  "nextReviewDate": "2026-09-22",\n  "state": "learning",\n  "xpAwarded": 5,\n'
        '  "remainingDue": 11,\n  "progress": {\n    "cardsTotal": 12,\n    "cardsMastered": 0,\n'
        '    "percent": 0,\n    "xpTotal": 5,\n    "streakDays": 1\n  }\n}',
    ),
    ("GET", "/progress"): (
        None,
        '{\n  "summary": {\n    "streakDays": 12,\n    "longestStreakDays": 19,\n'
        '    "xpTotal": 2480,\n    "studiedToday": true,\n    "masteryPercent": 58,\n'
        '    "cardsMastered": 73,\n    "cardsTotal": 124\n  },\n  "items": [\n    {\n'
        '      "topicId": "algebra-lineal",\n      "topicName": "Álgebra lineal",\n'
        '      "cardsTotal": 36,\n      "cardsMastered": 24,\n      "cardsPending": 12,\n'
        '      "percent": 67,\n      "lastStudiedAt": "2026-09-12T18:20:00Z"\n    }\n  ]\n}',
    ),
    ("GET", "/progress/{topicId}"): (
        None,
        '{\n  "topicId": "algebra-lineal",\n  "topicName": "Álgebra lineal",\n  "cardsTotal": 36,\n'
        '  "cardsMastered": 24,\n  "cardsPending": 12,\n  "percent": 67,\n'
        '  "lastStudiedAt": "2026-09-12T18:20:00Z"\n}',
    ),
    ("POST", "/quiz/{topicId}/start"): (
        None,
        '{\n  "quizId": "qz_01J9XYZ...",\n  "topicId": "estructuras-de-datos",\n'
        '  "topicName": "Estructuras de Datos",\n  "questionCount": 10,\n'
        '  "timeLimitSeconds": 360,\n  "xpReward": 120,\n  "basedOnConcepts": 24,\n'
        '  "startedAt": "2026-09-21T15:00:00Z",\n  "questions": [\n    {\n'
        '      "questionId": "q1",\n      "position": 1,\n'
        '      "prompt": "¿Qué estructura sigue el principio LIFO?",\n      "options": [\n'
        '        { "key": "A", "text": "La cola..." },\n        { "key": "B", "text": "La pila..." }\n'
        "      ]\n    }\n  ]\n}",
    ),
    ("POST", "/quiz/{quizId}/submit"): (
        '{\n  "answers": [\n    { "questionId": "q1", "selected": "B" }\n  ],\n'
        '  "durationSeconds": 214\n}',
        '{\n  "quizId": "qz_01J9XYZ...",\n  "score": 80,\n  "correctCount": 8,\n  "total": 10,\n'
        '  "xpAwarded": 120,\n  "timedOut": false,\n  "submittedAt": "2026-09-21T15:06:00Z",\n'
        '  "results": [\n    {\n      "questionId": "q1",\n      "cardId": "crd_0031",\n'
        '      "selected": "B",\n      "correctKey": "B",\n      "correct": true\n    }\n  ],\n'
        '  "conceptsToReview": [\n    {\n      "cardId": "crd_0044",\n'
        '      "concept": "Complejidad de tablas hash"\n    }\n  ]\n}',
    ),
}


def main() -> int:
    doc = [
        "# SkillPath — Catálogo de APIs",
        "",
        "> **Este archivo se genera.** No lo edites a mano: cambia `infra/spec.py`",
        "> o `scripts/generate_api_catalog.py` y ejecuta `make api-catalog`.",
        "",
        f"{len(all_routes())} endpoints repartidos en {len(SERVICES) - 1} microservicios.",
        "",
        "---",
        "",
        "## Convenciones",
        "",
        "**Base URL.** La URL de invocación de la etapa en API Gateway:",
        "`https://{apiId}.execute-api.us-east-1.amazonaws.com/{stage}`",
        "",
        "**Autenticación.** `auth-service` emite un JWT (HS256, 24 h) con el `userId`",
        "en el claim `sub`. Salvo tres rutas públicas, todas exigen la cabecera",
        "`Authorization: Bearer <token>`, que valida un autorizador de API Gateway",
        "antes de llegar al servicio.",
        "",
        "**El `userId` nunca viaja en la URL.** Todo recurso del usuario cuelga de",
        "`/me`, y el identificador sale del token. Así no existe forma de pedir los",
        "datos de otra persona cambiando la ruta.",
        "",
        "**Formato de error.** Todos los códigos ≥400 devuelven el mismo envelope:",
        "",
        "```json",
        "{",
        '  "error": {',
        '    "code": "NOT_ENOUGH_CONCEPTS",',
        '    "message": "Necesitas estudiar al menos 10 conceptos. Llevas 7 en Estructuras de Datos.",',
        '    "details": { "studied": 7, "required": 10, "topicName": "Estructuras de Datos" }',
        "  },",
        '  "requestId": "b3f1e0c2-..."',
        "}",
        "```",
        "",
        "`message` está en español y es apto para mostrarse al usuario tal cual, así",
        "que el frontend no traduce códigos. `requestId` es el de API Gateway y sirve",
        "para encontrar la petición en CloudWatch.",
        "",
        "**Errores transversales**, posibles en cualquier ruta:",
        "",
        "| HTTP | `code` | Cuándo |",
        "|---|---|---|",
        "| 400 | `VALIDATION_ERROR` | Cuerpo o parámetros inválidos; `details.fields` los enumera |",
        "| 401 | `UNAUTHENTICATED` | Falta el token, o está vencido o manipulado |",
        "| 403 | `FORBIDDEN` | El recurso no pertenece al usuario |",
        "| 404 | `NOT_FOUND` | El recurso no existe |",
        "| 429 | `RATE_LIMITED` | Límite de peticiones de API Gateway |",
        "| 500 | `INTERNAL_ERROR` | Error inesperado; no filtra detalles al cliente |",
        "",
        "**Formatos.** Instantes en ISO-8601 UTC (`2026-09-21T14:30:00Z`); fechas de",
        "calendario como `YYYY-MM-DD`. Los identificadores llevan prefijo: `usr_`,",
        "`crd_`, `qz_`, `deck_`. La racha y el «repaso de hoy» se calculan en",
        "**America/Lima (UTC-5)**: con UTC, la racha se rompería a las 19:00 hora local.",
        "",
        "---",
        "",
        "## Resumen",
        "",
        "| Servicio | Endpoints | Tablas propias | Historias |",
        "|---|---|---|---|",
    ]

    for service, spec in SERVICES.items():
        if service == "authorizer":
            continue
        propias = [s for s, m in spec["tables"].items() if m == "crud"]
        doc.append(
            f"| `{service}` | {len(spec['routes'])} | "
            f"{', '.join(f'`{t}`' for t in propias)} | {HISTORIAS.get(service, '—')} |"
        )

    doc += [
        "",
        "Los servicios que necesitan datos de otro **no leen su tabla: invocan al",
        "servicio dueño**. Ningún rol de IAM da acceso de escritura a una tabla ajena.",
        "",
        "| Origen | Destino | Para qué |",
        "|---|---|---|",
        "| `flashcards-service` | `progress-service` | Actualizar el progreso tras un repaso |",
        "| `quiz-service` | `flashcards-service` | Obtener las tarjetas y generar las preguntas |",
        "| `quiz-service` | `progress-service` | Sumar el XP del quiz |",
        "| `topics-service` | `flashcards-service` | Crear y borrar las tarjetas de un mazo propio |",
        "| `topics-service` | `progress-service` | Limpiar el progreso de un mazo eliminado |",
        "",
        "---",
        "",
    ]

    # --- Una sección por servicio --------------------------------------------
    for service, spec in SERVICES.items():
        if service == "authorizer":
            continue

        doc += [
            f"## `{service}`",
            "",
            f"{spec['description']}",
            "",
        ]
        for short in spec["tables"]:
            propia = TABLES[short]["owner"] == service
            etiqueta = "tabla propia" if propia else "solo lectura, es de " + TABLES[short]["owner"]
            pk = TABLES[short]["pk"][0]
            sk = TABLES[short]["sk"][0] if TABLES[short]["sk"] else None
            clave = f"PK `{pk}`" + (f" · SK `{sk}`" if sk else "")
            doc.append(f"- **`{short}`** — {etiqueta}. {clave}")
        doc.append("")

        for method, path, auth, description in spec["routes"]:
            publica = " · **público**" if auth == "NONE" else ""
            doc += [f"### `{method} {path}`{publica}", "", description, ""]

            peticion, respuesta = EJEMPLOS.get((method, path), (None, None))
            if peticion:
                doc += ["**Petición**", "", "```json", peticion, "```", ""]
            if respuesta:
                estado = ESTADOS.get((method, path), "200")
                doc += [f"**Respuesta {estado}**", "", "```json", respuesta, "```", ""]
            elif method == "DELETE":
                doc += ["**Respuesta 204** — sin contenido.", ""]

            errores = ERRORES.get((method, path))
            if errores:
                doc += ["| HTTP | `code` | Cuándo |", "|---|---|---|"]
                for http, code, cuando in errores:
                    doc.append(f"| {http} | `{code}` | {cuando} |")
                doc.append("")

        doc += ["---", ""]

    doc += [
        "## Todos los endpoints",
        "",
        "| Método | Ruta | Servicio | Auth |",
        "|---|---|---|---|",
    ]
    for method, path, auth, _, service in all_routes():
        doc.append(
            f"| `{method}` | `{path}` | `{service}` | "
            f"{'—' if auth == 'NONE' else 'JWT'} |"
        )
    doc.append("")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print(f"Escrito {OUT.relative_to(ROOT)} ({len(doc)} líneas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
