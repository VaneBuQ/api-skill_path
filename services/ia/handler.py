"""Microservicio de IA — evalúa la respuesta escrita del usuario.

Tabla propia: checks (historial de comprobaciones).

El usuario escribe con sus palabras lo que sabe del concepto y un modelo de
lenguaje decide si es correcto. Eso es lo que distingue a SkillPath de una app
de flashcards normal: en el repaso clásico el usuario se autocalifica después
de ver la respuesta, lo que mide reconocimiento y no recuerdo.

La llamada al modelo se hace por HTTPS con la librería estándar, no con el SDK
oficial: el SDK arrastra dependencias con código compilado (pydantic-core,
jiter) que en Lambda habría que empaquetar para Amazon Linux, y este patrón de
despliegue no empaqueta dependencias —los requirements.txt están vacíos, igual
que en el proyecto de ejemplo—.
"""

import json
import os
import urllib.error
import urllib.request

import boto3
from boto3.dynamodb.conditions import Key
from common import (
    AI_MAX_ANSWER_WORDS,
    AI_MAX_FEEDBACK_WORDS,
    ApiError,
    authenticated,
    call_service,
    parse_body,
    path_param,
    response,
    to_iso,
    word_count,
)

TABLE = boto3.resource("dynamodb").Table(os.environ["CHECKS_TABLE"])
FLASHCARDS_API = os.environ.get("FLASHCARDS_API_BASE", "")

# Groq, con formato de OpenAI: su capa gratuita basta para un trabajo
# académico. Cualquier proveedor compatible con OpenAI sirve cambiando estas
# dos variables de entorno, sin tocar el código.
AI_URL = os.environ.get("AI_API_URL", "https://api.groq.com/openai/v1/chat/completions")
# Comparar una respuesta con la correcta es una tarea de juez: corta, acotada
# y de bajo criterio. GPT-OSS 120B está en el plan gratuito de Groq y tiene
# precio público; Llama 3.3 70B pasó a ser solo para clientes Enterprise.
MODEL = os.environ.get("AI_MODEL", "openai/gpt-oss-120b")
# Es un modelo de razonamiento: los tokens que piensa cuentan dentro de este
# límite. Con esfuerzo bajo piensa poco, pero 300 podrían cortar el JSON antes
# de terminarlo. Las 40 palabras de la explicación se siguen imponiendo en el
# prompt y se recortan en el servicio.
MAX_TOKENS = 1000

VERDICTS = ("correcta", "parcial", "incorrecta")
RATING_BY_VERDICT = {"correcta": "easy", "parcial": "hard", "incorrecta": "forgot"}

SYSTEM_PROMPT = f"""Eres el evaluador de SkillPath, una aplicación de estudio.

Recibes la pregunta de una tarjeta, su respuesta correcta y lo que respondió un
estudiante. Decides si la respuesta del estudiante es correcta.

Reglas:
- Evalúa el CONTENIDO, no la redacción. Una respuesta correcta dicha con otras
  palabras, más corta o menos formal, es correcta.
- «parcial» es para una respuesta encaminada a la que le falta algo esencial.
- «incorrecta» es para una respuesta equivocada, vacía o sin relación.
- Fíjate en las negaciones: decir lo contrario es incorrecto, aunque se parezca.
- Escribe la retroalimentación en español, dirigida al estudiante de tú, con un
  máximo de {AI_MAX_FEEDBACK_WORDS} palabras. Si acertó, confírmalo en pocas
  palabras. Si no, dile exactamente qué le faltó.
- No reveles la respuesta correcta completa cuando el estudiante falle: señala
  qué le falta para que lo intente de nuevo.

Responde ÚNICAMENTE con un objeto JSON, sin texto alrededor y sin bloques de
código, con esta forma exacta:
{{"verdict": "correcta"|"parcial"|"incorrecta", "score": 0-100, "feedback": "..."}}"""


def _call_model(question, correct_answer, user_answer):
    """Llama a la API del modelo. Devuelve el texto de la respuesta."""
    api_key = os.environ.get("AI_API_KEY", "")
    if not api_key:
        raise ApiError(503, "AI_NOT_CONFIGURED",
                       "La comprobación con IA no está configurada.")

    payload = {
        "model": MODEL,
        "max_completion_tokens": MAX_TOKENS,
        # Obliga al modelo a devolver un objeto JSON válido.
        "response_format": {"type": "json_object"},
        # Evaluar una respuesta corta no necesita pensar mucho, y el
        # razonamiento no se devuelve porque nadie lo lee.
        "reasoning_effort": "low",
        "include_reasoning": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Pregunta: {question}\n\n"
                    f"Respuesta correcta: {correct_answer}\n\n"
                    f"Respuesta del estudiante: {user_answer}"
                ),
            },
        ],
    }

    request = urllib.request.Request(
        AI_URL, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(request, timeout=20) as raw:
            body = json.loads(raw.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        print(f"ERROR de la API de IA ({exc.code}): {detail}")
        raise ApiError(503, "AI_UNAVAILABLE",
                       "No pudimos evaluar tu respuesta. Inténtalo otra vez.") from exc
    except Exception as exc:
        print(f"ERROR llamando a la API de IA: {exc!r}")
        raise ApiError(503, "AI_UNAVAILABLE",
                       "No pudimos evaluar tu respuesta. Inténtalo otra vez.") from exc

    # Formato de OpenAI: el texto está en la primera opción.
    try:
        return (body["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        print(f"ERROR: respuesta inesperada de la API de IA: {str(body)[:300]}")
        raise ApiError(503, "AI_UNAVAILABLE",
                       "No pudimos evaluar tu respuesta. Inténtalo otra vez.") from exc


def _parse_verdict(text):
    """Convierte la respuesta del modelo en el veredicto.

    Se valida en lugar de confiar: si el modelo devolviera algo inesperado, la
    pantalla no debe romperse.
    """
    cleaned = text.strip()
    # Por si devolviera el JSON dentro de un bloque de código.
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
        cleaned = cleaned.removeprefix("json").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"AVISO: el modelo no devolvió JSON: {text[:200]!r}")
        raise ApiError(503, "AI_UNAVAILABLE",
                       "No pudimos evaluar tu respuesta. Inténtalo otra vez.") from None

    verdict = data.get("verdict")
    if verdict not in VERDICTS:
        verdict = "parcial"

    try:
        score = max(0, min(100, int(data.get("score", 0))))
    except (TypeError, ValueError):
        score = {"correcta": 100, "parcial": 50, "incorrecta": 0}[verdict]

    feedback = str(data.get("feedback") or "").strip()
    # El límite se pide en el prompt y se impone aquí: un párrafo largo no se
    # lee, y encima cuesta más.
    words = feedback.split()
    if len(words) > AI_MAX_FEEDBACK_WORDS:
        feedback = " ".join(words[:AI_MAX_FEEDBACK_WORDS]) + "…"

    return {
        "verdict": verdict,
        "score": score,
        "feedback": feedback,
        # La IA sugiere la calificación; decide el usuario. Calificar solo
        # sería frágil: una respuesta correcta expresada de forma rara se
        # penalizaría y el usuario perdería la confianza en la aplicación.
        "suggestedRating": RATING_BY_VERDICT[verdict],
    }


# =============================================================================
# POST /ia/check-answer
# =============================================================================

@authenticated
def check_answer(event, user_id):
    body = parse_body(event)
    topic_id = (body.get("topicId") or "").strip()
    card_id = (body.get("cardId") or "").strip()
    answer = (body.get("answer") or "").strip()

    if not topic_id or not card_id:
        raise ApiError(400, "VALIDATION_ERROR", "Faltan «topicId» y «cardId».",
                       {"fields": ["topicId", "cardId"]})
    if not answer:
        raise ApiError(400, "VALIDATION_ERROR", "Escribe tu respuesta antes de comprobarla.",
                       {"fields": ["answer"]})

    words = word_count(answer)
    if words > AI_MAX_ANSWER_WORDS:
        raise ApiError(400, "ANSWER_TOO_LONG",
                       f"Tu respuesta no puede superar las {AI_MAX_ANSWER_WORDS} palabras. "
                       f"Llevas {words}.",
                       {"words": words, "maxWords": AI_MAX_ANSWER_WORDS})

    # La respuesta correcta se toma del servicio dueño de las tarjetas, nunca
    # de lo que envíe el navegador: si no, cualquiera podría mandar la suya.
    card = call_service(FLASHCARDS_API, "/internal/cards/get",
                        payload={"topicId": topic_id, "cardId": card_id})
    if card is None:
        raise ApiError(503, "AI_UNAVAILABLE",
                       "No pudimos evaluar tu respuesta. Inténtalo otra vez.")
    if card.get("error") or not card.get("question"):
        raise ApiError(404, "CARD_NOT_FOUND", "La tarjeta no existe.")

    result = _parse_verdict(_call_model(card["question"], card["answer"], answer))

    checked_at = to_iso()
    TABLE.put_item(Item={
        "userId": user_id,
        "checkId": f"{topic_id}#{card_id}#{checked_at}",
        "topicId": topic_id,
        "cardId": card_id,
        "answer": answer,
        "verdict": result["verdict"],
        "score": result["score"],
        "feedback": result["feedback"],
        "checkedAt": checked_at,
    })

    return response(200, {
        "cardId": card_id,
        "topicId": topic_id,
        "yourAnswer": answer,
        "correctAnswer": card["answer"],
        **result,
        "checkedAt": checked_at,
    })


# =============================================================================
# GET /ia/history/{topicId}
# =============================================================================

@authenticated
def history(event, user_id):
    topic_id = path_param(event, "topicId")
    items = TABLE.query(
        KeyConditionExpression=Key("userId").eq(user_id)
        & Key("checkId").begins_with(f"{topic_id}#"),
        ScanIndexForward=False,
        Limit=50,
    )["Items"]

    return response(200, {"topicId": topic_id, "items": [
        {
            "cardId": i["cardId"], "answer": i["answer"],
            "verdict": i["verdict"], "score": int(i.get("score", 0)),
            "feedback": i.get("feedback"), "checkedAt": i["checkedAt"],
        }
        for i in items
    ]})
