"""Escenarios de extremo a extremo — fuente única de las pruebas de API.

Se declaran una sola vez y se usan de tres formas, así que no pueden
desincronizarse:

1. `tests/unit/test_escenarios.py` los ejecuta en memoria contra los seis
   handlers, sin AWS. Es lo que garantiza que la colección de Postman esté
   bien antes de desplegar nada.
2. `scripts/generate_postman.py` los convierte en la colección que pide la
   rúbrica.
3. `tests/e2e/test_live.py` los ejecuta por HTTP contra las APIs desplegadas.

Cada paso declara a qué microservicio va, porque cada uno tiene su propio API
Gateway y por lo tanto su propia URL.
"""

from dataclasses import dataclass, field

# --- comprobaciones ---------------------------------------------------------
EXISTS = "exists"
ABSENT = "absent"
EQ = "eq"
GTE = "gte"
LEN = "len"
STARTS = "starts"
IN = "in"


@dataclass
class Step:
    name: str
    service: str
    method: str
    path: str
    status: int
    body: dict | None = None
    query: dict | None = None
    auth: bool = True
    checks: list = field(default_factory=list)
    capture: dict = field(default_factory=dict)
    note: str = ""
    repeat: list | None = None
    # Los pasos que llaman al modelo se simulan al ejecutar en memoria; contra
    # una API desplegada sí llaman de verdad.
    uses_ai: bool = False

    def expand(self):
        if not self.repeat:
            return [("", {})]
        return [(" · " + " ".join(str(v) for v in extra.values()), extra)
                for extra in self.repeat]


@dataclass
class Scenario:
    name: str
    description: str
    steps: list


# =============================================================================
# 1. Cuenta y catálogo
# =============================================================================

CUENTA = Scenario(
    name="1 · Cuenta y catálogo",
    description=(
        "Crear la cuenta, iniciar sesión y agregar un tema a «Mis temas». "
        "El token que captura el primer paso lo usan todos los demás."
    ),
    steps=[
        Step(
            name="Crear cuenta",
            note="Historia 9. Devuelve el token para poder entrar directo.",
            service="auth", method="POST", path="/auth/register", auth=False, status=201,
            body={"name": "Sofía Rodríguez", "email": "{{email}}", "password": "Secreta123"},
            checks=[("userId", STARTS, "usr_"), ("token", EXISTS, None),
                    ("initials", EQ, "SR"), ("expiresIn", EQ, 86400)],
            capture={"token": "token", "userId": "userId"},
        ),
        Step(
            name="Un correo repetido da error",
            note="Historia 9: aquí sí se dice cuál es el problema.",
            service="auth", method="POST", path="/auth/register", auth=False, status=409,
            body={"name": "Otra", "email": "{{email}}", "password": "Secreta123"},
            checks=[("error.code", EQ, "EMAIL_ALREADY_EXISTS")],
        ),
        Step(
            name="Iniciar sesión",
            note="Historia 10.",
            service="auth", method="POST", path="/auth/login", auth=False, status=200,
            body={"email": "{{email}}", "password": "Secreta123"},
            checks=[("userId", EQ, "{{userId}}"), ("token", EXISTS, None)],
            capture={"token": "token"},
        ),
        Step(
            name="Contraseña incorrecta",
            note="Historia 10: el mensaje no dice si falló el correo o la contraseña.",
            service="auth", method="POST", path="/auth/login", auth=False, status=401,
            body={"email": "{{email}}", "password": "Equivocada123"},
            checks=[("error.code", EQ, "INVALID_CREDENTIALS")],
        ),
        Step(
            name="Ver mi perfil",
            service="auth", method="GET", path="/auth/me", status=200,
            checks=[("email", EQ, "{{email}}"), ("passwordHash", ABSENT, None)],
        ),
        Step(
            name="Explorar el catálogo",
            note="Ruta pública: se ve sin iniciar sesión.",
            service="topics", method="GET", path="/topics", auth=False, status=200,
            checks=[("items", LEN, 6), ("items[0].cardCount", GTE, 10)],
        ),
        Step(
            name="Buscar sin escribir tildes",
            service="topics", method="GET", path="/topics", auth=False, status=200,
            query={"search": "algebra"},
            checks=[("items", LEN, 1), ("items[0].name", EQ, "Álgebra lineal")],
        ),
        Step(
            name="Agregar el tema a «Mis temas»",
            note="Historia 1: al agregarlo se muestra el total de conceptos.",
            service="topics", method="POST", path="/topics/estructuras-de-datos/follow",
            status=201,
            checks=[("cardCount", GTE, 10), ("alreadyFollowing", EQ, False)],
        ),
        Step(
            name="Agregarlo otra vez no da error",
            service="topics", method="POST", path="/topics/estructuras-de-datos/follow",
            status=200,
            checks=[("alreadyFollowing", EQ, True)],
        ),
        Step(
            name="Ver mis temas",
            service="topics", method="GET", path="/me/topics", status=200,
            checks=[("items", LEN, 1), ("items[0].topicId", EQ, "estructuras-de-datos")],
        ),
    ],
)


# =============================================================================
# 2. Repaso y comprobación con IA
# =============================================================================

REPASO = Scenario(
    name="2 · Repaso y comprobación con IA",
    description=(
        "Pedir las tarjetas del día, escribir una respuesta y dejar que la IA la "
        "evalúe, calificar y consultar el progreso."
    ),
    steps=[
        Step(
            name="Tarjetas que tocan hoy",
            note="Historia 2. Una tarjeta nunca repasada vence siempre.",
            service="flashcards", method="GET", path="/flashcards/estructuras-de-datos",
            status=200,
            checks=[("dueCount", GTE, 10), ("items[0].question", EXISTS, None),
                    ("items[0].answer", EXISTS, None), ("items[0].state", EQ, "new")],
        ),
        Step(
            name="Comprobar una respuesta escrita con IA",
            note=(
                "La respuesta correcta la toma el servicio de su propia tabla, nunca "
                "del cuerpo de la petición."
            ),
            service="ia", method="POST", path="/ia/check-answer", status=200,
            uses_ai=True,
            body={"topicId": "estructuras-de-datos", "cardId": "crd_0001",
                  "answer": "Es una estructura que asocia claves con valores."},
            checks=[("verdict", IN, ["correcta", "parcial", "incorrecta"]),
                    ("feedback", EXISTS, None), ("correctAnswer", EXISTS, None),
                    ("suggestedRating", IN, ["easy", "hard", "forgot"])],
        ),
        Step(
            name="Una respuesta de más de 60 palabras se rechaza",
            note="El límite acota el costo y la calidad de la evaluación.",
            service="ia", method="POST", path="/ia/check-answer", status=400,
            body={"topicId": "estructuras-de-datos", "cardId": "crd_0001",
                  "answer": ("palabra " * 61).strip()},
            checks=[("error.code", EQ, "ANSWER_TOO_LONG"),
                    ("error.details.maxWords", EQ, 60)],
        ),
        Step(
            name="Ver el historial de comprobaciones",
            service="ia", method="GET", path="/ia/history/estructuras-de-datos", status=200,
            checks=[("items", GTE, 1)],
        ),
        Step(
            name="Calificar una tarjeta",
            note=(
                "Historia 3. topicId va en el cuerpo porque la tabla tiene clave "
                "compuesta y con el cardId solo no se puede leer la tarjeta."
            ),
            service="flashcards", method="POST", path="/flashcards/crd_0001/review",
            status=200,
            body={"topicId": "estructuras-de-datos", "rating": "easy"},
            checks=[("intervalDays", EQ, 1), ("easeFactor", EQ, 2.6),
                    ("xpAwarded", EQ, 5), ("progress.streakDays", EQ, 1)],
        ),
        Step(
            name="Calificar sin enviar topicId",
            service="flashcards", method="POST", path="/flashcards/crd_0002/review",
            status=400, body={"rating": "easy"},
            checks=[("error.code", EQ, "VALIDATION_ERROR")],
        ),
        Step(
            name="Una calificación que no existe",
            service="flashcards", method="POST", path="/flashcards/crd_0002/review",
            status=400, body={"topicId": "estructuras-de-datos", "rating": "perfecto"},
            checks=[("error.code", EQ, "INVALID_RATING")],
        ),
        Step(
            name="Ver el progreso del tema",
            note="Historia 4.",
            service="progress", method="GET", path="/progress/estructuras-de-datos",
            status=200,
            checks=[("cardsTotal", GTE, 10), ("lastStudiedAt", EXISTS, None),
                    ("mastered", EQ, False)],
        ),
        Step(
            name="Ver el resumen de inicio",
            note="Historias 5 y 11: una sola llamada trae racha, XP y todos los temas.",
            service="progress", method="GET", path="/progress", status=200,
            checks=[("summary.streakDays", EQ, 1), ("summary.xpTotal", EQ, 5),
                    ("summary.studiedToday", EQ, True), ("items", LEN, 1)],
        ),
    ],
)


# =============================================================================
# 3. Examen de dominio
# =============================================================================

EXAMEN = Scenario(
    name="3 · Examen de dominio",
    description=(
        "Intentar el examen sin conceptos suficientes, estudiar los que faltan y "
        "rendirlo. Continúa la sesión del escenario anterior."
    ),
    steps=[
        Step(
            name="Sin 10 conceptos estudiados se bloquea",
            note=(
                "Historia 6. El umbral cuenta conceptos ESTUDIADOS, no tarjetas del "
                "mazo: es lo que muestra el prototipo, «Llevas 1 de 10»."
            ),
            service="quiz", method="POST", path="/quiz/estructuras-de-datos/start",
            status=409,
            checks=[("error.code", EQ, "NOT_ENOUGH_CONCEPTS"),
                    ("error.details.required", EQ, 10),
                    ("error.details.topicName", EQ, "Estructuras de Datos")],
        ),
        Step(
            name="Estudiar un concepto más",
            note=(
                "El examen exige 10 conceptos estudiados y solo hay 1, así que faltan "
                "9. Se repite la misma petición cambiando el cardId."
            ),
            service="flashcards", method="POST", path="/flashcards/{{card}}/review",
            status=200,
            body={"topicId": "estructuras-de-datos", "rating": "easy"},
            checks=[("state", EQ, "learning")],
            repeat=[{"card": f"crd_{i:04d}"} for i in range(2, 11)],
        ),
        Step(
            name="Iniciar el examen",
            note="Diez preguntas de cuatro opciones, con los conceptos ya estudiados.",
            service="quiz", method="POST", path="/quiz/estructuras-de-datos/start",
            status=201,
            checks=[("quizId", STARTS, "qz_"), ("questionCount", EQ, 10),
                    ("passCorrect", EQ, 7), ("timeLimitSeconds", EQ, 360),
                    ("questions[0].options", LEN, 4),
                    ("questions[0].correctKey", ABSENT, None)],
            capture={"quizId": "quizId", "q1": "questions[0].questionId"},
        ),
        Step(
            name="Consultar el examen en curso",
            note="Permite recargar la página sin perder el intento.",
            service="quiz", method="GET", path="/quiz/{{quizId}}", status=200,
            checks=[("status", EQ, "in_progress"), ("total", EQ, 10)],
        ),
        Step(
            name="Enviarlo sin responder nada",
            note=(
                "Las preguntas sin responder cuentan como incorrectas: el examen se "
                "autoenvía al vencer el tiempo en vez de invalidarse."
            ),
            service="quiz", method="POST", path="/quiz/{{quizId}}/submit", status=200,
            body={"answers": [], "durationSeconds": 200},
            checks=[("score", EQ, 0), ("total", EQ, 10), ("passed", EQ, False),
                    ("conceptsToReview", LEN, 10),
                    ("results[0].correctKey", EXISTS, None)],
        ),
        Step(
            name="Enviarlo otra vez da conflicto",
            service="quiz", method="POST", path="/quiz/{{quizId}}/submit", status=409,
            body={"answers": []},
            checks=[("error.code", EQ, "QUIZ_ALREADY_SUBMITTED")],
        ),
        Step(
            name="Reprobar no marca el tema como dominado",
            service="progress", method="GET", path="/progress/estructuras-de-datos",
            status=200,
            checks=[("mastered", EQ, False), ("lastExamScore", EQ, 0)],
        ),
    ],
)


# =============================================================================
# 4. Mazos propios
# =============================================================================

MAZOS = Scenario(
    name="4 · Mazos propios",
    description=(
        "Historia 8: crear un mazo con los apuntes de clase, agregarle tarjetas, "
        "repasarlo como cualquier tema y eliminarlo con toda su huella."
    ),
    steps=[
        Step(
            name="Crear un mazo con dos tarjetas",
            service="topics", method="POST", path="/me/decks", status=201,
            body={
                "name": "Resumen Parcial 2",
                "description": "Lo que entró en el parcial",
                "cards": [
                    {"question": "¿Qué es una integral definida?",
                     "answer": "El área acumulada bajo una curva entre dos límites.",
                     "hint": "Piensa en el área."},
                    {"question": "¿Qué es una derivada?",
                     "answer": "La tasa de cambio instantánea de una función."},
                ],
            },
            checks=[("topicId", STARTS, "deck_"), ("cardCount", EQ, 2),
                    ("isOwn", EQ, True)],
            capture={"deckId": "topicId"},
        ),
        Step(
            name="Un mazo sin tarjetas no se crea",
            note="Criterio de aceptación: al menos una tarjeta.",
            service="topics", method="POST", path="/me/decks", status=400,
            body={"name": "Mazo vacío", "cards": []},
            checks=[("error.code", EQ, "VALIDATION_ERROR")],
        ),
        Step(
            name="El mazo NO aparece en el catálogo público",
            note="Es privado: el catálogo se consulta filtrando visibility=public.",
            service="topics", method="GET", path="/topics", auth=False, status=200,
            checks=[("items", LEN, 6)],
        ),
        Step(
            name="Pero sí en «Mis mazos»",
            service="topics", method="GET", path="/me/decks", status=200,
            checks=[("items", LEN, 1), ("items[0].topicId", EQ, "{{deckId}}")],
        ),
        Step(
            name="Y en «Mis temas», junto a los demás",
            note="Criterio: «queda disponible para repasar junto a los demás temas».",
            service="topics", method="GET", path="/me/topics", status=200,
            checks=[("items", LEN, 2)],
        ),
        Step(
            name="Agregar una tarjeta al mazo",
            service="topics", method="POST", path="/me/decks/{{deckId}}/cards", status=201,
            body={"question": "¿Qué es un límite?",
                  "answer": "El valor al que tiende una función."},
            checks=[("cardCount", EQ, 3)],
        ),
        Step(
            name="Ver el detalle del mazo",
            service="topics", method="GET", path="/me/decks/{{deckId}}", status=200,
            checks=[("cards", LEN, 3), ("cards[0].hint", EXISTS, None)],
        ),
        Step(
            name="Renombrar el mazo",
            service="topics", method="PATCH", path="/me/decks/{{deckId}}", status=200,
            body={"name": "Repaso Final Cálculo"},
            checks=[("name", EQ, "Repaso Final Cálculo")],
        ),
        Step(
            name="Repasarlo como cualquier tema",
            service="flashcards", method="GET", path="/flashcards/{{deckId}}", status=200,
            checks=[("dueCount", EQ, 3), ("cardsTotal", EQ, 3)],
        ),
        Step(
            name="Un mazo propio no se puede «dejar de seguir»",
            note="Quitarlo de «Mis temas» lo dejaría inaccesible para siempre.",
            service="topics", method="DELETE", path="/topics/{{deckId}}/follow", status=409,
            checks=[("error.code", EQ, "OWN_DECK_CANNOT_UNFOLLOW")],
        ),
        Step(
            name="Eliminar el mazo",
            note="Arrastra tarjetas, historial de repaso y progreso.",
            service="topics", method="DELETE", path="/me/decks/{{deckId}}", status=204,
        ),
        Step(
            name="Ya no está en «Mis mazos»",
            service="topics", method="GET", path="/me/decks", status=200,
            checks=[("items", LEN, 0)],
        ),
        Step(
            name="Ni deja rastro en «Mi progreso»",
            note="Sin la limpieza, el mazo borrado seguiría apareciendo aquí.",
            service="progress", method="GET", path="/progress", status=200,
            checks=[("items", LEN, 1)],
        ),
    ],
)


# =============================================================================
# 5. Seguridad
# =============================================================================

SEGURIDAD = Scenario(
    name="5 · Seguridad",
    description=(
        "Comprueba que las rutas protegidas exigen token y que los datos de un "
        "usuario son inalcanzables para otro."
    ),
    steps=[
        Step(
            name="Sin token no se accede a «Mis temas»",
            service="topics", method="GET", path="/me/topics", auth=False, status=401,
        ),
        Step(
            name="Sin token no se accede al progreso",
            service="progress", method="GET", path="/progress", auth=False, status=401,
        ),
        Step(
            name="Sin token no se puede comprobar con IA",
            service="ia", method="POST", path="/ia/check-answer", auth=False, status=401,
            body={"topicId": "estructuras-de-datos", "cardId": "crd_0001",
                  "answer": "Algo."},
        ),
        Step(
            name="Un tema que no se sigue no se puede repasar",
            service="flashcards", method="GET", path="/flashcards/estadistica", status=403,
            checks=[("error.code", EQ, "NOT_FOLLOWING_TOPIC")],
        ),
        Step(
            name="Un tema inexistente",
            service="topics", method="POST", path="/topics/no-existe/follow", status=404,
            checks=[("error.code", EQ, "TOPIC_NOT_FOUND")],
        ),
        Step(
            name="Un mazo que no es mío no existe",
            note="404 y no 403: decir «existe pero no es tuyo» revelaría los ids.",
            service="topics", method="GET", path="/me/decks/deck_inventado", status=404,
        ),
    ],
)


SCENARIOS = [CUENTA, REPASO, EXAMEN, MAZOS, SEGURIDAD]
