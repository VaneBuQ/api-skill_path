"""quiz-service — generación y calificación de quizzes (historia 6).

Tabla propia: `quiz-attempts`.
Lee `user-topics` (de topics-service) solo para comprobar que el usuario sigue
el tema y conocer su nombre.

Las preguntas salen de las tarjetas, que son de flashcards-service, así que se
las pide en vez de leer su tabla (observación #7).
"""

import random
from datetime import timedelta

from skillpath_common.dates import now, to_iso
from skillpath_common.db import table
from skillpath_common.errors import (
    IncompleteAnswers,
    NotEnoughConcepts,
    NotFollowingTopic,
    QuizAlreadySubmitted,
    QuizNotFound,
    ValidationError,
)
from skillpath_common.http import body_of, current_user_id, path_param
from skillpath_common.ids import quiz_id as new_quiz_id
from skillpath_common.invoke import call
from skillpath_common.router import Router
from skillpath_common.rules import (
    QUIZ_MIN_STUDIED_CONCEPTS,
    QUIZ_OPTIONS_PER_QUESTION,
    QUIZ_QUESTION_COUNT,
    QUIZ_TIME_LIMIT_SECONDS,
    XP_PER_QUIZ,
)

router = Router("quiz-service")

OPTION_KEYS = ["A", "B", "C", "D"]
IN_PROGRESS = "in_progress"
SUBMITTED = "submitted"

# Instancia propia para que las pruebas puedan fijar la semilla y obtener
# quizzes reproducibles sin tocar el generador global del proceso.
_rng = random.Random()


def _attempts():
    return table("QUIZ_ATTEMPTS_TABLE")


def _user_topics():
    return table("USER_TOPICS_TABLE")


def _followed_topic(user_id: str, topic_id: str) -> dict:
    item = _user_topics().get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not item:
        raise NotFollowingTopic()
    return item


# --- generación de preguntas -------------------------------------------------

def build_questions(cards: list[dict], studied_ids: list[str]) -> list[dict]:
    """Arma las preguntas a partir de las tarjetas ya estudiadas.

    El enunciado es la pregunta de la tarjeta, la opción correcta es su
    respuesta, y los distractores son respuestas de OTRAS tarjetas del mismo
    tema — también de las no estudiadas, para que haya más variedad.
    """
    by_id = {c["cardId"]: c for c in cards}
    studied = [by_id[cid] for cid in studied_ids if cid in by_id]
    chosen = _rng.sample(studied, min(QUIZ_QUESTION_COUNT, len(studied)))

    questions = []
    for position, card in enumerate(chosen, start=1):
        correct = card["answer"]
        # Se descartan las respuestas repetidas: dos opciones idénticas
        # convertirían la pregunta en una trampa sin solución única.
        pool = list({
            c["answer"] for c in cards
            if c["cardId"] != card["cardId"] and c["answer"] != correct
        })
        distractors = _rng.sample(pool, min(QUIZ_OPTIONS_PER_QUESTION - 1, len(pool)))

        texts = [correct, *distractors]
        _rng.shuffle(texts)
        options = [{"key": OPTION_KEYS[i], "text": t} for i, t in enumerate(texts)]

        questions.append({
            "questionId": f"q{position}",
            "position": position,
            "cardId": card["cardId"],
            "prompt": card["question"],
            "options": options,
            # Se guarda con el intento y solo se revela al enviar.
            "correctKey": next(o["key"] for o in options if o["text"] == correct),
        })
    return questions


def _public_question(question: dict) -> dict:
    """La misma pregunta, sin la respuesta correcta."""
    return {
        "questionId": question["questionId"],
        "position": int(question["position"]),
        "prompt": question["prompt"],
        "options": [{"key": o["key"], "text": o["text"]} for o in question["options"]],
    }


# =============================================================================
# POST /quiz/{topicId}/start
# =============================================================================

@router.route("POST", "/quiz/{topicId}/start")
def start_quiz(event, context):
    user_id = current_user_id(event)
    topic_id = path_param(event, "topicId")
    followed = _followed_topic(user_id, topic_id)
    topic_name = followed.get("topicName") or topic_id

    studied = call("FLASHCARDS_FUNCTION", {
        "internalAction": "getStudiedCount",
        "data": {"userId": user_id, "topicId": topic_id},
    })
    if studied is None:
        raise ValidationError(
            "No se pudo preparar el quiz. Inténtalo otra vez.",
            code="QUIZ_GENERATION_FAILED", status=503,
        )

    # Observación #8: el umbral cuenta conceptos ESTUDIADOS, no tarjetas del
    # mazo. Con la lectura del informe, un tema de 52 tarjetas nunca se
    # bloquearía y la pantalla «Aún no está listo» sería inalcanzable.
    if studied["studied"] < QUIZ_MIN_STUDIED_CONCEPTS:
        raise NotEnoughConcepts(
            f"Necesitas estudiar al menos {QUIZ_MIN_STUDIED_CONCEPTS} conceptos. "
            f"Llevas {studied['studied']} en {topic_name}.",
            details={
                "studied": studied["studied"],
                "required": QUIZ_MIN_STUDIED_CONCEPTS,
                "topicName": topic_name,
            },
        )

    cards = call("FLASHCARDS_FUNCTION", {
        "internalAction": "getTopicCards", "data": {"topicId": topic_id},
    })
    if cards is None:
        raise ValidationError(
            "No se pudo preparar el quiz. Inténtalo otra vez.",
            code="QUIZ_GENERATION_FAILED", status=503,
        )

    questions = build_questions(cards["items"], studied["studiedCardIds"])
    started = now()
    quiz_id = new_quiz_id()

    _attempts().put_item(Item={
        "userId": user_id,
        "quizId": quiz_id,
        "topicId": topic_id,
        "topicName": topic_name,
        "status": IN_PROGRESS,
        "questions": questions,
        "total": len(questions),
        "startedAt": to_iso(started),
        # Se valida en el servidor para que el límite no dependa del reloj del
        # navegador.
        "expiresAt": to_iso(started + timedelta(seconds=QUIZ_TIME_LIMIT_SECONDS)),
    })

    return 201, {
        "quizId": quiz_id,
        "topicId": topic_id,
        "topicName": topic_name,
        "questionCount": len(questions),
        "timeLimitSeconds": QUIZ_TIME_LIMIT_SECONDS,
        "xpReward": XP_PER_QUIZ,
        # «10 preguntas basadas en tus 24 conceptos estudiados» (prototipo p.12).
        "basedOnConcepts": studied["studied"],
        "startedAt": to_iso(started),
        "questions": [_public_question(q) for q in questions],
    }


# =============================================================================
# POST /quiz/{quizId}/submit
# =============================================================================

@router.route("POST", "/quiz/{quizId}/submit")
def submit_quiz(event, context):
    user_id = current_user_id(event)
    quiz_id = path_param(event, "quizId")
    body = body_of(event)

    attempt = _attempts().get_item(Key={"userId": user_id, "quizId": quiz_id}).get("Item")
    if not attempt:
        raise QuizNotFound()
    if attempt["status"] == SUBMITTED:
        raise QuizAlreadySubmitted()

    answers = body.get("answers")
    if not isinstance(answers, list):
        raise ValidationError("«answers» debe ser una lista.", details={"fields": ["answers"]})

    questions = {q["questionId"]: q for q in attempt["questions"]}
    chosen = {}
    for answer in answers:
        question_id = (answer or {}).get("questionId")
        if question_id not in questions:
            raise IncompleteAnswers(
                f"La pregunta «{question_id}» no pertenece a este quiz.",
                code="UNKNOWN_QUESTION",
            )
        chosen[question_id] = (answer or {}).get("selected")

    results, to_review = [], []
    for question in attempt["questions"]:
        selected = chosen.get(question["questionId"])
        correct = selected == question["correctKey"]
        results.append({
            "questionId": question["questionId"],
            "cardId": question["cardId"],
            "prompt": question["prompt"],
            "selected": selected,
            "correctKey": question["correctKey"],
            "correct": correct,
        })
        if not correct:
            # Las no respondidas cuentan como incorrectas: el quiz se
            # autoenvía al vencer el tiempo en vez de invalidarse.
            to_review.append({"cardId": question["cardId"], "concept": question["prompt"]})

    total = len(attempt["questions"])
    correct_count = sum(1 for r in results if r["correct"])
    submitted_at = to_iso()
    timed_out = submitted_at > str(attempt.get("expiresAt", ""))

    _attempts().update_item(
        Key={"userId": user_id, "quizId": quiz_id},
        UpdateExpression=(
            "SET #s = :s, answers = :a, score = :sc, correctCount = :cc, "
            "submittedAt = :t, durationSeconds = :d, xpAwarded = :xp, "
            "timedOut = :to, conceptsToReview = :cr"
        ),
        # Si dos envíos llegan a la vez, solo el primero pasa.
        ConditionExpression="#s = :in_progress",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": SUBMITTED,
            ":in_progress": IN_PROGRESS,
            ":a": results,
            ":sc": round(correct_count * 100 / total) if total else 0,
            ":cc": correct_count,
            ":t": submitted_at,
            ":d": int(body.get("durationSeconds") or 0),
            ":xp": XP_PER_QUIZ,
            ":to": timed_out,
            ":cr": to_review,
        },
    )

    call("PROGRESS_FUNCTION", {
        "internalAction": "quizCompleted",
        "data": {
            "userId": user_id, "topicId": attempt["topicId"],
            "quizId": quiz_id, "xp": XP_PER_QUIZ, "completedAt": submitted_at,
        },
    })

    return 200, {
        "quizId": quiz_id,
        "topicId": attempt["topicId"],
        "topicName": attempt.get("topicName"),
        "score": round(correct_count * 100 / total) if total else 0,
        "correctCount": correct_count,
        "total": total,
        "xpAwarded": XP_PER_QUIZ,
        "timedOut": timed_out,
        "submittedAt": submitted_at,
        "results": results,
        # Alimenta «Conceptos para repasar» y el botón «Repasar errores» (p.14).
        "conceptsToReview": to_review,
    }


# =============================================================================
# GET /quiz/{quizId}
# =============================================================================

@router.route("GET", "/quiz/{quizId}")
def get_quiz(event, context):
    user_id = current_user_id(event)
    attempt = _attempts().get_item(
        Key={"userId": user_id, "quizId": path_param(event, "quizId")}
    ).get("Item")
    if not attempt:
        # La clave incluye el userId, así que el intento de otra persona
        # sencillamente no aparece.
        raise QuizNotFound()

    base = {
        "quizId": attempt["quizId"],
        "topicId": attempt["topicId"],
        "topicName": attempt.get("topicName"),
        "status": attempt["status"],
        "total": int(attempt.get("total", 0)),
        "startedAt": attempt.get("startedAt"),
        "expiresAt": attempt.get("expiresAt"),
        "timeLimitSeconds": QUIZ_TIME_LIMIT_SECONDS,
    }

    if attempt["status"] == IN_PROGRESS:
        # Permite recargar la página sin perder el quiz, y sigue sin revelar
        # las respuestas correctas.
        return 200, {**base, "questions": [_public_question(q) for q in attempt["questions"]]}

    return 200, {
        **base,
        "score": int(attempt.get("score", 0)),
        "correctCount": int(attempt.get("correctCount", 0)),
        "xpAwarded": int(attempt.get("xpAwarded", 0)),
        "timedOut": bool(attempt.get("timedOut")),
        "submittedAt": attempt.get("submittedAt"),
        "results": attempt.get("answers", []),
        "conceptsToReview": attempt.get("conceptsToReview", []),
    }


lambda_handler = router.as_handler()
