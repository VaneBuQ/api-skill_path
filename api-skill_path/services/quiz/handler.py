"""Microservicio de quiz — historia 6, examen de dominio.

Tabla propia: attempts.
Lee user-topics (de topics) para comprobar que el usuario sigue el tema.

Las preguntas salen de las tarjetas, que son de otro microservicio, así que se
le piden por HTTP. Aprobar con 7 de 10 marca el tema como dominado.
"""

import os
import random
import time
import uuid
from datetime import timedelta

import boto3
from botocore.exceptions import ClientError
from common import (
    QUIZ_MIN_STUDIED_CONCEPTS,
    QUIZ_OPTIONS_PER_QUESTION,
    QUIZ_PASS_CORRECT,
    QUIZ_QUESTION_COUNT,
    QUIZ_TIME_LIMIT_SECONDS,
    XP_PER_QUIZ,
    ApiError,
    authenticated,
    call_service,
    now,
    parse_body,
    path_param,
    response,
    to_iso,
)

RESOURCE = boto3.resource("dynamodb")
ATTEMPTS = RESOURCE.Table(os.environ["ATTEMPTS_TABLE"])
USER_TOPICS = RESOURCE.Table(os.environ["USER_TOPICS_TABLE"])

FLASHCARDS_API = os.environ.get("FLASHCARDS_API_BASE", "")
PROGRESS_API = os.environ.get("PROGRESS_API_BASE", "")

OPTION_KEYS = ["A", "B", "C", "D"]
IN_PROGRESS = "in_progress"
SUBMITTED = "submitted"

# El prototipo muestra dos formas de pregunta, y alternarlas evita que el
# usuario memorice la posición de la respuesta en lugar del concepto.
FORWARD = "concept_to_definition"
REVERSE = "definition_to_concept"


def _followed_topic(user_id, topic_id):
    item = USER_TOPICS.get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not item:
        raise ApiError(403, "NOT_FOLLOWING_TOPIC", "Primero agrega este tema a «Mis temas».")
    return item


def build_questions(cards, studied_ids, rng):
    """Arma las preguntas con las tarjetas ya estudiadas.

    Los distractores son respuestas de OTRAS tarjetas del mismo tema, también
    de las no estudiadas, para que haya más variedad.
    """
    by_id = {c["cardId"]: c for c in cards}
    studied = [by_id[cid] for cid in studied_ids if cid in by_id]
    chosen = rng.sample(studied, min(QUIZ_QUESTION_COUNT, len(studied)))

    questions = []
    for position, card in enumerate(chosen, start=1):
        # Se alternan las dos direcciones, empezando por concepto→definición.
        direction = FORWARD if position % 2 == 1 else REVERSE

        if direction == FORWARD:
            prompt = f'Dado el concepto: «{card["question"]}», elige la definición correcta:'
            correct = card["answer"]
            pool = [c["answer"] for c in cards if c["cardId"] != card["cardId"]]
        else:
            prompt = f'Dada la definición: «{card["answer"]}», elige el concepto correcto:'
            correct = card["question"]
            pool = [c["question"] for c in cards if c["cardId"] != card["cardId"]]

        # Se descartan los textos repetidos: dos opciones idénticas
        # convertirían la pregunta en una trampa sin solución única.
        pool = list({p for p in pool if p != correct})
        distractors = rng.sample(pool, min(QUIZ_OPTIONS_PER_QUESTION - 1, len(pool)))

        texts = [correct, *distractors]
        rng.shuffle(texts)
        options = [{"key": OPTION_KEYS[i], "text": t} for i, t in enumerate(texts)]

        questions.append({
            "questionId": f"q{position}",
            "position": position,
            "cardId": card["cardId"],
            "direction": direction,
            "prompt": prompt,
            "concept": card["question"],
            "options": options,
            # Se guarda con el intento y solo se revela al enviar.
            "correctKey": next(o["key"] for o in options if o["text"] == correct),
        })
    return questions


def _public_question(question):
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

@authenticated
def start_quiz(event, user_id):
    topic_id = path_param(event, "topicId")
    followed = _followed_topic(user_id, topic_id)
    topic_name = followed.get("topicName") or topic_id

    studied = call_service(FLASHCARDS_API, "/internal/reviews/studied",
                           payload={"userId": user_id, "topicId": topic_id})
    if studied is None:
        raise ApiError(503, "QUIZ_GENERATION_FAILED",
                       "No se pudo preparar el quiz. Inténtalo otra vez.")

    # El umbral cuenta conceptos ESTUDIADOS, no tarjetas del mazo: es lo que
    # muestra el prototipo («Llevas 6 de 10»).
    if studied["studied"] < QUIZ_MIN_STUDIED_CONCEPTS:
        raise ApiError(
            409, "NOT_ENOUGH_CONCEPTS",
            f"Necesitas al menos {QUIZ_MIN_STUDIED_CONCEPTS} conceptos estudiados para "
            f"iniciar el quiz de {topic_name}. Llevas {studied['studied']} de "
            f"{QUIZ_MIN_STUDIED_CONCEPTS}.",
            {"studied": studied["studied"], "required": QUIZ_MIN_STUDIED_CONCEPTS,
             "topicName": topic_name},
        )

    cards = call_service(FLASHCARDS_API, "/internal/cards/list", payload={"topicId": topic_id})
    if cards is None:
        raise ApiError(503, "QUIZ_GENERATION_FAILED",
                       "No se pudo preparar el quiz. Inténtalo otra vez.")

    questions = build_questions(cards["items"], studied["studiedCardIds"], random.Random())
    started = now()
    quiz_id = f"qz_{int(time.time() * 1000):013d}_{uuid.uuid4().hex[:8]}"

    ATTEMPTS.put_item(Item={
        "userId": user_id,
        "quizId": quiz_id,
        "topicId": topic_id,
        "topicName": topic_name,
        "status": IN_PROGRESS,
        "questions": questions,
        "total": len(questions),
        "startedAt": to_iso(started),
        # Se valida en el servidor para que el límite no dependa del reloj
        # del navegador.
        "expiresAt": to_iso(started + timedelta(seconds=QUIZ_TIME_LIMIT_SECONDS)),
    })

    return response(201, {
        "quizId": quiz_id,
        "topicId": topic_id,
        "topicName": topic_name,
        "questionCount": len(questions),
        "timeLimitSeconds": QUIZ_TIME_LIMIT_SECONDS,
        "passCorrect": QUIZ_PASS_CORRECT,
        "xpReward": XP_PER_QUIZ,
        "basedOnConcepts": studied["studied"],
        "startedAt": to_iso(started),
        "questions": [_public_question(q) for q in questions],
    })


# =============================================================================
# POST /quiz/{quizId}/submit
# =============================================================================

@authenticated
def submit_quiz(event, user_id):
    quiz_id = path_param(event, "quizId")
    body = parse_body(event)

    attempt = ATTEMPTS.get_item(Key={"userId": user_id, "quizId": quiz_id}).get("Item")
    if not attempt:
        raise ApiError(404, "QUIZ_NOT_FOUND", "El quiz no existe.")
    if attempt["status"] == SUBMITTED:
        raise ApiError(409, "QUIZ_ALREADY_SUBMITTED", "Este quiz ya fue enviado.")

    answers = body.get("answers")
    if not isinstance(answers, list):
        raise ApiError(400, "VALIDATION_ERROR", "«answers» debe ser una lista.",
                       {"fields": ["answers"]})

    known = {q["questionId"] for q in attempt["questions"]}
    chosen = {}
    for answer in answers:
        question_id = (answer or {}).get("questionId")
        if question_id not in known:
            raise ApiError(400, "UNKNOWN_QUESTION",
                           f"La pregunta «{question_id}» no pertenece a este quiz.")
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
            # Las no respondidas cuentan como incorrectas: el quiz se autoenvía
            # al vencer el tiempo en vez de invalidarse.
            to_review.append({"cardId": question["cardId"],
                              "concept": question.get("concept", question["prompt"])})

    total = len(attempt["questions"])
    correct_count = sum(1 for r in results if r["correct"])
    score = round(correct_count * 100 / total) if total else 0
    passed = correct_count >= QUIZ_PASS_CORRECT
    submitted_at = to_iso()
    timed_out = submitted_at > str(attempt.get("expiresAt", ""))

    try:
        ATTEMPTS.update_item(
            Key={"userId": user_id, "quizId": quiz_id},
            UpdateExpression=(
                "SET #s = :s, answers = :a, score = :sc, correctCount = :cc, "
                "passed = :p, submittedAt = :t, durationSeconds = :d, "
                "xpAwarded = :xp, timedOut = :to, conceptsToReview = :cr"
            ),
            # Si dos envíos llegan a la vez, solo el primero pasa.
            ConditionExpression="#s = :in_progress",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": SUBMITTED, ":in_progress": IN_PROGRESS, ":a": results,
                ":sc": score, ":cc": correct_count, ":p": passed,
                ":t": submitted_at, ":d": int(body.get("durationSeconds") or 0),
                ":xp": XP_PER_QUIZ, ":to": timed_out, ":cr": to_review,
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ApiError(409, "QUIZ_ALREADY_SUBMITTED",
                           "Este quiz ya fue enviado.") from exc
        raise

    # Aprobar marca el tema como dominado; ese estado lo guarda progress.
    call_service(PROGRESS_API, "/internal/progress/quiz-completed", payload={
        "userId": user_id, "topicId": attempt["topicId"], "quizId": quiz_id,
        "passed": passed, "score": score, "xp": XP_PER_QUIZ,
        "completedAt": submitted_at,
    })

    return response(200, {
        "quizId": quiz_id,
        "topicId": attempt["topicId"],
        "topicName": attempt.get("topicName"),
        "score": score,
        "correctCount": correct_count,
        "total": total,
        "passed": passed,
        "passCorrect": QUIZ_PASS_CORRECT,
        "xpAwarded": XP_PER_QUIZ,
        "timedOut": timed_out,
        "submittedAt": submitted_at,
        "results": results,
        # Alimenta «Conceptos fallados» y el botón «Repasar errores».
        "conceptsToReview": to_review,
    })


# =============================================================================
# GET /quiz/{quizId}
# =============================================================================

@authenticated
def get_quiz(event, user_id):
    attempt = ATTEMPTS.get_item(
        Key={"userId": user_id, "quizId": path_param(event, "quizId")}
    ).get("Item")
    if not attempt:
        # La clave incluye el userId, así que el intento de otra persona
        # sencillamente no aparece.
        raise ApiError(404, "QUIZ_NOT_FOUND", "El quiz no existe.")

    base = {
        "quizId": attempt["quizId"], "topicId": attempt["topicId"],
        "topicName": attempt.get("topicName"), "status": attempt["status"],
        "total": int(attempt.get("total", 0)),
        "startedAt": attempt.get("startedAt"), "expiresAt": attempt.get("expiresAt"),
        "timeLimitSeconds": QUIZ_TIME_LIMIT_SECONDS, "passCorrect": QUIZ_PASS_CORRECT,
    }

    if attempt["status"] == IN_PROGRESS:
        # Permite recargar la página sin perder el quiz, y sigue sin revelar
        # las respuestas correctas.
        return response(200, {**base,
                              "questions": [_public_question(q) for q in attempt["questions"]]})

    return response(200, {
        **base,
        "score": int(attempt.get("score", 0)),
        "correctCount": int(attempt.get("correctCount", 0)),
        "passed": bool(attempt.get("passed")),
        "xpAwarded": int(attempt.get("xpAwarded", 0)),
        "timedOut": bool(attempt.get("timedOut")),
        "submittedAt": attempt.get("submittedAt"),
        "results": attempt.get("answers", []),
        "conceptsToReview": attempt.get("conceptsToReview", []),
    })
