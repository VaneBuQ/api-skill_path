"""Especificación de la infraestructura de SkillPath.

El despliegue es **manual desde la consola de AWS**, así que este archivo es la
fuente de verdad de cómo debe quedar. De aquí salen tres cosas, y por eso no
pueden desincronizarse entre sí:

1. `docs/despliegue-manual.md`  — la guía paso a paso  (scripts/generate_deploy_guide.py)
2. Las tablas de las pruebas    — `tests/fixtures/tables.py`
3. Las pruebas de arquitectura  — `tests/unit/test_infra_spec.py`

Si se cambia una clave aquí, la guía y las pruebas cambian solas.
"""

REGION = "us-east-1"
RUNTIME = "python3.11"
ARCHITECTURE = "arm64"
MEMORY_MB = 256          # el valor con el que se calculó el costo en el informe
TIMEOUT_SECONDS = 10

S = "S"  # tipo String de DynamoDB


def table_name(stage: str, short: str) -> str:
    return f"skillpath-{stage}-{short}"


def function_name(stage: str, service: str) -> str:
    return f"skillpath-{stage}-{service}"


# ---------------------------------------------------------------------------
# CAPA 4 — DATOS
# Siete tablas, todas bajo demanda. Ningún servicio accede a las de otro.
# ---------------------------------------------------------------------------

TABLES = {
    "users": {
        "owner": "auth-service",
        "pk": ("userId", S),
        "sk": None,
        "indexes": [],
        "why": (
            "Sin índice por correo: la búsqueda va por un ítem centinela "
            '"EMAIL#<correo>" en esta misma tabla, que además impone la unicidad. '
            "Un índice secundario sería de consistencia eventual y quien acaba de "
            "registrarse podría fallar al iniciar sesión."
        ),
        "attributes": "email, name, passwordHash, authProvider, createdAt",
    },
    "topics": {
        "owner": "topics-service",
        "pk": ("topicId", S),
        "sk": None,
        "indexes": [
            {
                "name": "catalog-index",
                "pk": ("visibility", S),
                "sk": ("name", S),
                "projection": "ALL",
                "why": (
                    "Devuelve el catálogo ordenado por nombre sin hacer Scan. "
                    'visibility vale "public" para el catálogo y "private" para '
                    "los mazos que crea el usuario (historia 8), que por lo tanto "
                    "nunca aparecen aquí."
                ),
            }
        ],
        "attributes": "name, description, cardCount, icon, level, visibility, ownerId, createdAt",
    },
    "user-topics": {
        "owner": "topics-service",
        "pk": ("userId", S),
        "sk": ("topicId", S),
        "indexes": [],
        "attributes": "followedAt, topicName, cardCount, icon, isOwn",
        "why": (
            "topicName, cardCount e icon van denormalizados porque DynamoDB no "
            "tiene JOIN: sin ellos, pintar «Mis temas» exigiría un GetItem por tema."
        ),
    },
    "flashcards": {
        "owner": "flashcards-service",
        "pk": ("topicId", S),
        "sk": ("cardId", S),
        "indexes": [],
        "attributes": "question, answer, hint, position, difficulty, createdAt",
        "why": (
            "La clave es compuesta, así que para leer una tarjeta hacen falta "
            "topicId Y cardId: por eso POST /flashcards/{cardId}/review exige "
            "topicId en el cuerpo (observación #5)."
        ),
    },
    "user-card-reviews": {
        "owner": "flashcards-service",
        "pk": ("userId", S),
        "sk": ("topicCardId", S),
        "indexes": [
            {
                "name": "due-index",
                "pk": ("userTopicKey", S),
                "sk": ("nextReviewDate", S),
                "projection": "ALL",
                "why": (
                    "La consulta principal de la app: tarjetas de este usuario en "
                    "este tema que vencen hoy o antes. Devuelve exactamente esas, "
                    "sin filtrar en memoria (observación #4)."
                ),
            }
        ],
        "attributes": (
            "topicId, cardId, nextReviewDate, lastReviewedAt, easeFactor, "
            "intervalDays, repetitions, lapses, lastRating, state, userTopicKey"
        ),
        "why": (
            'La SK es "topicId#cardId", no solo cardId: con la clave del informe '
            "original no se podían consultar las pendientes de UN tema sin leer "
            "las de todos (observación #4)."
        ),
    },
    "user-progress": {
        "owner": "progress-service",
        "pk": ("userId", S),
        "sk": ("topicId", S),
        "indexes": [],
        "attributes": (
            "topicName, cardsTotal, cardsMastered, cardsPending, lastStudiedAt "
            "· y en el ítem #STATS: streakDays, longestStreakDays, lastStudyDate, "
            "xpTotal. El porcentaje NO se guarda: se calcula al leer, porque un "
            "valor derivado y almacenado acaba desviándose de lo que resume."
        ),
        "why": (
            'La SK es el topicId salvo un ítem especial "#STATS" por usuario que '
            'guarda racha y XP (observación #1). Como "#" ordena antes que '
            "cualquier letra, una sola Query trae estadísticas y todos los temas."
        ),
    },
    "quiz-attempts": {
        "owner": "quiz-service",
        "pk": ("userId", S),
        "sk": ("quizId", S),
        "indexes": [
            {
                "name": "topic-attempt-index",
                "pk": ("userTopicKey", S),
                "sk": ("startedAt", S),
                "projection": "INCLUDE",
                "included": ["score", "status", "topicId"],
                "why": "Último intento por tema, sin recorrer el historial completo.",
            }
        ],
        "attributes": (
            "topicId, topicName, status, questions, answers, score, correctCount, "
            "total, startedAt, expiresAt, submittedAt, durationSeconds, xpAwarded"
        ),
        "why": (
            "quizId es un ULID, ordenable por tiempo, así que Query(userId) "
            "devuelve el historial en orden cronológico sin índice adicional."
        ),
    },
}


# ---------------------------------------------------------------------------
# CAPA 3 — API Y CÓMPUTO
# ---------------------------------------------------------------------------

PUBLIC = "NONE"   # ruta sin token
JWT = "JWT"       # ruta que exige el authorizer

SERVICES = {
    "authorizer": {
        "code": "services/authorizer",
        "description": "Valida el JWT y entrega el userId a los demás servicios",
        "tables": {},
        "invokes": [],
        "routes": [],
        "memory": 128,
        "timeout": 5,
    },
    "auth-service": {
        "code": "services/auth_service",
        "description": "Registro e inicio de sesión (historias 9 y 10)",
        "tables": {"users": "crud"},
        "invokes": [],
        "routes": [
            ("POST", "/auth/register", PUBLIC, "Crea una cuenta y devuelve el token"),
            ("POST", "/auth/login", PUBLIC, "Valida credenciales y devuelve el token"),
            ("GET", "/auth/me", JWT, "Perfil del usuario autenticado"),
        ],
    },
    "topics-service": {
        "code": "services/topics_service",
        "description": "Catálogo, «Mis temas» y mazos propios (historias 1 y 8)",
        "tables": {"topics": "crud", "user-topics": "crud"},
        # Crear un mazo escribe tarjetas, y borrarlo limpia tarjetas y progreso:
        # ambas cosas son de otros servicios, así que se les piden.
        "invokes": ["flashcards-service", "progress-service"],
        "routes": [
            ("GET", "/topics", PUBLIC, "Catálogo de temas, con búsqueda"),
            ("POST", "/topics/{topicId}/follow", JWT, "Agrega el tema a «Mis temas»"),
            ("DELETE", "/topics/{topicId}/follow", JWT, "Quita el tema de «Mis temas»"),
            ("GET", "/me/topics", JWT, "Temas que sigue el usuario"),
            ("POST", "/me/decks", JWT, "Crea un mazo propio con sus tarjetas"),
            ("GET", "/me/decks", JWT, "Lista los mazos propios del usuario"),
            ("GET", "/me/decks/{topicId}", JWT, "Detalle de un mazo propio con sus tarjetas"),
            ("PATCH", "/me/decks/{topicId}", JWT, "Renombra un mazo propio"),
            ("DELETE", "/me/decks/{topicId}", JWT, "Elimina un mazo propio"),
            ("POST", "/me/decks/{topicId}/cards", JWT, "Agrega una tarjeta al mazo"),
            ("DELETE", "/me/decks/{topicId}/cards/{cardId}", JWT, "Elimina una tarjeta"),
        ],
    },
    "flashcards-service": {
        "code": "services/flashcards_service",
        "description": "Tarjetas y repetición espaciada (historias 2 y 3)",
        "tables": {"flashcards": "crud", "user-card-reviews": "crud", "user-topics": "read"},
        "invokes": ["progress-service"],
        "routes": [
            ("GET", "/flashcards/{topicId}", JWT, "Tarjetas que tocan hoy en ese tema"),
            ("POST", "/flashcards/{cardId}/review", JWT, "Registra la calificación y reprograma"),
        ],
    },
    "progress-service": {
        "code": "services/progress_service",
        "description": "Progreso por tema, racha y XP (historias 4, 5 y 11)",
        "tables": {"user-progress": "crud"},
        "invokes": [],
        "routes": [
            ("GET", "/progress", JWT, "Resumen global (racha, XP) y progreso de todos los temas"),
            ("GET", "/progress/{topicId}", JWT, "Progreso en un tema"),
        ],
    },
    "quiz-service": {
        "code": "services/quiz_service",
        "description": "Generación y calificación de quizzes (historia 6)",
        # user-topics es de topics-service: solo lectura, para comprobar que el
        # usuario sigue el tema y obtener su nombre. Mismo caso que
        # flashcards-service.
        "tables": {"quiz-attempts": "crud", "user-topics": "read"},
        "invokes": ["flashcards-service", "progress-service"],
        "routes": [
            ("POST", "/quiz/{topicId}/start", JWT, "Genera un quiz de 10 preguntas"),
            ("POST", "/quiz/{quizId}/submit", JWT, "Califica y devuelve el puntaje"),
            ("GET", "/quiz/{quizId}", JWT, "Consulta un intento"),
        ],
        "timeout": 15,
    },
}


ENV_VAR_FOR_TABLE = {
    "users": "USERS_TABLE",
    "topics": "TOPICS_TABLE",
    "user-topics": "USER_TOPICS_TABLE",
    "flashcards": "FLASHCARDS_TABLE",
    "user-card-reviews": "USER_CARD_REVIEWS_TABLE",
    "user-progress": "USER_PROGRESS_TABLE",
    "quiz-attempts": "QUIZ_ATTEMPTS_TABLE",
}

ENV_VAR_FOR_FUNCTION = {
    "flashcards-service": "FLASHCARDS_FUNCTION",
    "progress-service": "PROGRESS_FUNCTION",
}


def env_for(stage: str, service: str) -> dict:
    """Variables de entorno que debe tener configuradas una función."""
    spec = SERVICES[service]
    env = {
        "STAGE": stage,
        "LOG_LEVEL": "INFO",
        "CORS_ORIGIN": "<dominio de CloudFront, o http://localhost:5173 en dev>",
        "JWT_SECRET": "<el mismo secreto en todas las funciones>",
    }
    for short in spec["tables"]:
        env[ENV_VAR_FOR_TABLE[short]] = table_name(stage, short)
    for target in spec["invokes"]:
        env[ENV_VAR_FOR_FUNCTION[target]] = function_name(stage, target)
    return env


def all_routes():
    """[(método, ruta, auth, descripción, servicio)] ordenadas por ruta."""
    rows = []
    for service, spec in SERVICES.items():
        for method, path, auth, description in spec["routes"]:
            rows.append((method, path, auth, description, service))
    return sorted(rows, key=lambda r: (r[1], r[0]))
