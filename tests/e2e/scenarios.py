"""Escenarios de extremo a extremo — la fuente única de las pruebas de API.

Se declaran una sola vez y se usan de tres formas, así que no pueden
desincronizarse entre sí:

1. `tests/unit/test_scenarios.py` los ejecuta en memoria contra los handlers,
   sin AWS: es lo que garantiza que la colección de Postman esté bien antes de
   desplegar nada.
2. `tests/e2e/test_live.py` los ejecuta contra una API ya desplegada.
3. `scripts/generate_postman.py` los convierte en la colección de Postman que
   pide la rúbrica.

Cada paso declara qué espera; las comprobaciones se traducen a `assert` en
pytest y a `pm.test(...)` en Postman.
"""

from dataclasses import dataclass, field

# --- comprobaciones ----------------------------------------------------------
# (ruta, operador, valor). La ruta usa puntos y corchetes: "items[0].topicId"

EXISTS = "exists"
ABSENT = "absent"
EQ = "eq"
GTE = "gte"
LEN = "len"
STARTS = "starts"


@dataclass
class Step:
    name: str
    method: str
    path: str
    status: int
    body: dict | None = None
    query: dict | None = None
    auth: bool = True
    checks: list = field(default_factory=list)
    capture: dict = field(default_factory=dict)
    note: str = ""
    # Ejecuta el paso una vez por cada diccionario de variables. Tanto pytest
    # como el generador de Postman lo expanden, así que la colección queda con
    # una petición por repetición y se puede ejecutar de corrido.
    repeat: list | None = None

    def expand(self):
        """[(sufijo_del_nombre, variables_extra)] — una entrada por ejecución."""
        if not self.repeat:
            return [("", {})]
        return [
            (" · " + " ".join(str(v) for v in extra.values()), extra)
            for extra in self.repeat
        ]


@dataclass
class Scenario:
    name: str
    description: str
    steps: list


# =============================================================================
# 1. Camino completo del MVP
# =============================================================================

CAMINO_FELIZ = Scenario(
    name="Camino completo del MVP",
    description=(
        "Recorre las nueve historias del MVP en orden: crear cuenta, explorar "
        "temas, seguir uno, repasar tarjetas, consultar el progreso, intentar un "
        "quiz sin conceptos suficientes y aprobarlo después de estudiar."
    ),
    steps=[
        Step(
            name="Crear cuenta",
            note="Historia 9. Devuelve el token para poder redirigir al Home.",
            method="POST", path="/auth/register", auth=False, status=201,
            body={"name": "Lucía Mendoza", "email": "{{email}}", "password": "Secreta123"},
            checks=[
                ("userId", STARTS, "usr_"),
                ("token", EXISTS, None),
                ("expiresIn", EQ, 86400),
                ("initials", EQ, "LM"),
            ],
            capture={"token": "token", "userId": "userId"},
        ),
        Step(
            name="Iniciar sesión",
            note="Historia 10.",
            method="POST", path="/auth/login", auth=False, status=200,
            body={"email": "{{email}}", "password": "Secreta123"},
            checks=[("userId", EQ, "{{userId}}"), ("token", EXISTS, None)],
            capture={"token": "token"},
        ),
        Step(
            name="Ver mi perfil",
            method="GET", path="/auth/me", status=200,
            checks=[("email", EQ, "{{email}}"), ("passwordHash", ABSENT, None)],
        ),
        Step(
            name="Explorar el catálogo de temas",
            note="Historia 1. Ruta pública: se puede ver sin iniciar sesión.",
            method="GET", path="/topics", auth=False, status=200,
            checks=[("items", LEN, 6), ("items[0].cardCount", GTE, 10)],
        ),
        Step(
            name="Buscar un tema sin escribir tildes",
            method="GET", path="/topics", auth=False, status=200,
            query={"search": "algebra"},
            checks=[("items", LEN, 1), ("items[0].name", EQ, "Álgebra lineal")],
        ),
        Step(
            name="Agregar el tema a «Mis temas»",
            note="Historia 1: al agregarlo se muestra el total de conceptos.",
            method="POST", path="/topics/algebra-lineal/follow", status=201,
            checks=[("cardCount", GTE, 10), ("alreadyFollowing", EQ, False)],
        ),
        Step(
            name="Agregarlo otra vez no da error",
            note="La operación es idempotente: la app queda en el mismo estado.",
            method="POST", path="/topics/algebra-lineal/follow", status=200,
            checks=[("alreadyFollowing", EQ, True)],
        ),
        Step(
            name="Ver mis temas",
            method="GET", path="/me/topics", status=200,
            checks=[("items", LEN, 1), ("items[0].topicId", EQ, "algebra-lineal")],
        ),
        Step(
            name="Pedir las tarjetas que tocan hoy",
            note="Historia 2. Una tarjeta nunca repasada vence siempre.",
            method="GET", path="/flashcards/algebra-lineal", status=200,
            checks=[
                ("dueCount", GTE, 10),
                ("items[0].question", EXISTS, None),
                ("items[0].answer", EXISTS, None),
                ("items[0].state", EQ, "new"),
            ],
        ),
        Step(
            name="Calificar una tarjeta como «Fácil»",
            note=(
                "Historia 3. topicId va en el cuerpo porque la tabla tiene clave "
                "compuesta y con el cardId solo no se puede leer la tarjeta."
            ),
            method="POST", path="/flashcards/crd_0001/review", status=200,
            body={"topicId": "algebra-lineal", "rating": "easy"},
            checks=[
                ("intervalDays", EQ, 1),
                ("easeFactor", EQ, 2.6),
                ("xpAwarded", EQ, 5),
                ("progress.streakDays", EQ, 1),
            ],
        ),
        Step(
            name="Calificar otra como «Olvidé»",
            note="Vuelve a vencer hoy mismo, así que sigue entre las pendientes.",
            method="POST", path="/flashcards/crd_0002/review", status=200,
            body={"topicId": "algebra-lineal", "rating": "forgot"},
            checks=[("intervalDays", EQ, 0), ("state", EQ, "learning")],
        ),
        Step(
            name="Ver el progreso del tema",
            note="Historia 4: dominados vs. pendientes y fecha del último repaso.",
            method="GET", path="/progress/algebra-lineal", status=200,
            checks=[
                ("cardsTotal", GTE, 10),
                ("cardsMastered", EQ, 0),
                ("lastStudiedAt", EXISTS, None),
            ],
        ),
        Step(
            name="Ver el resumen del Home",
            note=(
                "Historias 5 y 11. Una sola llamada trae racha, XP y todos los "
                "temas: es el endpoint que faltaba en el informe."
            ),
            method="GET", path="/progress", status=200,
            checks=[
                ("summary.streakDays", EQ, 1),
                ("summary.xpTotal", EQ, 10),
                ("summary.studiedToday", EQ, True),
                ("items", LEN, 1),
            ],
        ),
        Step(
            name="Intentar el quiz sin conceptos suficientes",
            note=(
                "Historia 6. El umbral cuenta conceptos ESTUDIADOS, no tarjetas "
                "del mazo: por eso un tema con 12 tarjetas y 2 repasos se bloquea."
            ),
            method="POST", path="/quiz/algebra-lineal/start", status=409,
            checks=[
                ("error.code", EQ, "NOT_ENOUGH_CONCEPTS"),
                ("error.details.studied", EQ, 2),
                ("error.details.required", EQ, 10),
            ],
        ),
    ],
)


# =============================================================================
# 2. Quiz completo
# =============================================================================

QUIZ = Scenario(
    name="Quiz de autoevaluación",
    description=(
        "Estudia los conceptos suficientes, genera el quiz, lo envía y comprueba "
        "el puntaje y el XP. Continúa la sesión del escenario anterior."
    ),
    steps=[
        Step(
            name="Estudiar un concepto más",
            note=(
                "El quiz exige 10 conceptos estudiados y el escenario anterior "
                "dejó 2, así que faltan 8. Se repite la misma petición cambiando "
                "el cardId."
            ),
            method="POST", path="/flashcards/{{card}}/review", status=200,
            body={"topicId": "algebra-lineal", "rating": "easy"},
            checks=[("state", EQ, "learning")],
            repeat=[{"card": f"crd_{i:04d}"} for i in range(3, 11)],
        ),
        Step(
            name="Iniciar el quiz",
            note="Diez preguntas armadas con los conceptos ya estudiados.",
            method="POST", path="/quiz/algebra-lineal/start", status=201,
            checks=[
                ("quizId", STARTS, "qz_"),
                ("questionCount", EQ, 10),
                ("timeLimitSeconds", EQ, 360),
                ("xpReward", EQ, 120),
                ("questions[0].options", LEN, 4),
                ("questions[0].correctKey", ABSENT, None),
            ],
            capture={"quizId": "quizId", "q1": "questions[0].questionId"},
        ),
        Step(
            name="Consultar el quiz en curso",
            note="Permite recargar la página sin perder el intento.",
            method="GET", path="/quiz/{{quizId}}", status=200,
            checks=[("status", EQ, "in_progress"), ("total", EQ, 10)],
        ),
        Step(
            name="Enviar el quiz sin responder nada",
            note=(
                "Las preguntas sin responder cuentan como incorrectas: el quiz se "
                "autoenvía al vencer el tiempo en vez de invalidarse."
            ),
            method="POST", path="/quiz/{{quizId}}/submit", status=200,
            body={"answers": [], "durationSeconds": 214},
            checks=[
                ("score", EQ, 0),
                ("total", EQ, 10),
                ("xpAwarded", EQ, 120),
                ("conceptsToReview", LEN, 10),
                ("results[0].correctKey", EXISTS, None),
            ],
        ),
        Step(
            name="Enviarlo otra vez da conflicto",
            method="POST", path="/quiz/{{quizId}}/submit", status=409,
            body={"answers": []},
            checks=[("error.code", EQ, "QUIZ_ALREADY_SUBMITTED")],
        ),
        Step(
            name="El XP del quiz se suma al de los repasos",
            note="10 tarjetas × 5 XP + 120 del quiz.",
            method="GET", path="/progress", status=200,
            checks=[("summary.xpTotal", EQ, 170)],
        ),
    ],
)


# =============================================================================
# 3. Mazos propios — historia 8
# =============================================================================

MAZOS_PROPIOS = Scenario(
    name="Mazos propios",
    description=(
        "Historia 8: crear un mazo con los apuntes de clase, agregarle tarjetas, "
        "repasarlo como cualquier otro tema y eliminarlo con toda su huella."
    ),
    steps=[
        Step(
            name="Crear un mazo con dos tarjetas",
            method="POST", path="/me/decks", status=201,
            body={
                "name": "Apuntes de Cloud Computing",
                "description": "Lo que entró en el parcial",
                "cards": [
                    {"question": "¿Qué es infraestructura como código?",
                     "answer": "Definir los recursos de la nube en archivos versionados.",
                     "hint": "No tiene que ver con la Parte C."},
                    {"question": "¿Qué garantizan las propiedades ACID?",
                     "answer": "Atomicidad, consistencia, aislamiento y durabilidad."},
                ],
            },
            checks=[
                ("topicId", STARTS, "deck_"),
                ("cardCount", EQ, 2),
                ("isOwn", EQ, True),
            ],
            capture={"deckId": "topicId"},
        ),
        Step(
            name="Un mazo sin tarjetas no se puede crear",
            note="Criterio de aceptación: al menos una tarjeta.",
            method="POST", path="/me/decks", status=400,
            body={"name": "Mazo vacío", "cards": []},
            checks=[("error.code", EQ, "VALIDATION_ERROR")],
        ),
        Step(
            name="El mazo NO aparece en el catálogo público",
            note="Es privado: el catálogo se consulta filtrando visibility=public.",
            method="GET", path="/topics", auth=False, status=200,
            checks=[("items", LEN, 6)],
        ),
        Step(
            name="Pero sí en «Mis mazos»",
            method="GET", path="/me/decks", status=200,
            checks=[("items", LEN, 1), ("items[0].topicId", EQ, "{{deckId}}")],
        ),
        Step(
            name="Y en «Mis temas», junto a los demás",
            note="Criterio: «queda disponible para repasar junto a los demás temas».",
            method="GET", path="/me/topics", status=200,
            checks=[("items", LEN, 2)],
        ),
        Step(
            name="Agregar una tarjeta al mazo",
            method="POST", path="/me/decks/{{deckId}}/cards", status=201,
            body={"question": "¿Qué es un GSI?", "answer": "Un índice secundario global."},
            checks=[("cardCount", EQ, 3)],
        ),
        Step(
            name="Ver el detalle del mazo",
            method="GET", path="/me/decks/{{deckId}}", status=200,
            checks=[("cards", LEN, 3), ("cards[0].hint", EXISTS, None)],
        ),
        Step(
            name="Renombrar el mazo",
            method="PATCH", path="/me/decks/{{deckId}}", status=200,
            body={"name": "Cloud Computing — parcial"},
            checks=[("name", EQ, "Cloud Computing — parcial")],
        ),
        Step(
            name="Repasar el mazo propio como cualquier tema",
            method="GET", path="/flashcards/{{deckId}}", status=200,
            checks=[("dueCount", EQ, 3), ("cardsTotal", EQ, 3)],
        ),
        Step(
            name="Calificar una tarjeta del mazo propio",
            method="POST", path="/flashcards/crd_0001/review", status=200,
            body={"topicId": "{{deckId}}", "rating": "easy"},
            checks=[("xpAwarded", EQ, 5)],
        ),
        Step(
            name="Un mazo propio no se puede «dejar de seguir»",
            note="Quitarlo de «Mis temas» lo dejaría inaccesible para siempre.",
            method="DELETE", path="/topics/{{deckId}}/follow", status=409,
            checks=[("error.code", EQ, "OWN_DECK_CANNOT_UNFOLLOW")],
        ),
        Step(
            name="Eliminar el mazo",
            note="Arrastra tarjetas, historial de repaso y progreso.",
            method="DELETE", path="/me/decks/{{deckId}}", status=204,
        ),
        Step(
            name="Ya no está en «Mis mazos»",
            method="GET", path="/me/decks", status=200,
            checks=[("items", LEN, 0)],
        ),
        Step(
            name="Ni deja rastro en «Mi progreso»",
            note="Sin la limpieza, el mazo borrado seguiría apareciendo aquí.",
            method="GET", path="/progress", status=200,
            checks=[("items", LEN, 1)],
        ),
    ],
)


# =============================================================================
# 4. Seguridad
# =============================================================================

SEGURIDAD = Scenario(
    name="Seguridad y errores",
    description=(
        "Comprueba que las rutas protegidas exigen token, que el login no revela "
        "qué correos existen y que los datos de un usuario son inalcanzables para otro."
    ),
    steps=[
        Step(
            name="Sin token no se accede a «Mis temas»",
            method="GET", path="/me/topics", auth=False, status=401,
        ),
        Step(
            name="Sin token no se accede al progreso",
            method="GET", path="/progress", auth=False, status=401,
        ),
        Step(
            name="Un correo que no existe da el mismo error que una contraseña mala",
            note=(
                "Historia 10: el mensaje no debe decir si falló el correo o la "
                "contraseña, para no revelar qué cuentas están registradas."
            ),
            method="POST", path="/auth/login", auth=False, status=401,
            body={"email": "nadie@universidad.edu", "password": "Secreta123"},
            checks=[("error.code", EQ, "INVALID_CREDENTIALS")],
        ),
        Step(
            name="Contraseña incorrecta, error idéntico",
            method="POST", path="/auth/login", auth=False, status=401,
            body={"email": "{{email}}", "password": "Equivocada123"},
            checks=[("error.code", EQ, "INVALID_CREDENTIALS")],
        ),
        Step(
            name="Un correo repetido sí se informa explícitamente",
            note="Historia 9: aquí el usuario necesita saberlo para iniciar sesión.",
            method="POST", path="/auth/register", auth=False, status=409,
            body={"name": "Otra Persona", "email": "{{email}}", "password": "Secreta123"},
            checks=[("error.code", EQ, "EMAIL_ALREADY_EXISTS")],
        ),
        Step(
            name="Un tema que no se sigue no se puede repasar",
            method="GET", path="/flashcards/estadistica", status=403,
            checks=[("error.code", EQ, "NOT_FOLLOWING_TOPIC")],
        ),
        Step(
            name="Un tema inexistente",
            method="POST", path="/topics/no-existe/follow", status=404,
            checks=[("error.code", EQ, "TOPIC_NOT_FOUND")],
        ),
        Step(
            name="Calificar sin enviar topicId",
            note="La tabla tiene clave compuesta: con el cardId solo no basta.",
            method="POST", path="/flashcards/crd_0001/review", status=400,
            body={"rating": "easy"},
            checks=[("error.code", EQ, "VALIDATION_ERROR")],
        ),
        Step(
            name="Una calificación que no existe",
            method="POST", path="/flashcards/crd_0001/review", status=400,
            body={"topicId": "algebra-lineal", "rating": "perfecto"},
            checks=[("error.code", EQ, "INVALID_RATING")],
        ),
    ],
)


SCENARIOS = [CAMINO_FELIZ, QUIZ, MAZOS_PROPIOS, SEGURIDAD]
