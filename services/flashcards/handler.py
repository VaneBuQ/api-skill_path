"""Microservicio de tarjetas — historias 2 y 3.

Tablas propias: cards y reviews.
Lee user-topics (de topics) solo para comprobar que el usuario sigue el tema.

Calificar una tarjeta cambia el progreso del tema, que vive en la tabla de
progress, así que al terminar se le comunica por HTTP en vez de escribir ahí.
"""

import os

import boto3
from boto3.dynamodb.conditions import Key
from common import (
    EASE_INITIAL,
    RATINGS,
    XP_PER_CARD,
    ApiError,
    add_days,
    authenticated,
    call_service,
    decimal,
    internal_only,
    parse_body,
    path_param,
    query_params,
    response,
    schedule,
    to_iso,
    today_str,
)

RESOURCE = boto3.resource("dynamodb")
CARDS = RESOURCE.Table(os.environ["CARDS_TABLE"])
REVIEWS = RESOURCE.Table(os.environ["REVIEWS_TABLE"])
USER_TOPICS = RESOURCE.Table(os.environ["USER_TOPICS_TABLE"])

PROGRESS_API = os.environ.get("PROGRESS_API_BASE", "")

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def review_key(topic_id, card_id):
    return f"{topic_id}#{card_id}"


def card_id_for(position):
    """Los ceros a la izquierda hacen que la clave ordene como número."""
    return f"crd_{position:04d}"


def list_cards(topic_id):
    items, start = [], None
    while True:
        kwargs = {"KeyConditionExpression": Key("topicId").eq(topic_id)}
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = CARDS.query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return sorted(items, key=lambda c: int(c.get("position", 0)))


def list_reviews(user_id, topic_id):
    """Reviews del usuario en un tema, indexadas por cardId."""
    items, start = [], None
    while True:
        kwargs = {
            "KeyConditionExpression": Key("userId").eq(user_id)
            & Key("topicCardId").begins_with(f"{topic_id}#")
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = REVIEWS.query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            break
    return {r["cardId"]: r for r in items}


def _followed_topic(user_id, topic_id):
    item = USER_TOPICS.get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not item:
        raise ApiError(403, "NOT_FOLLOWING_TOPIC", "Primero agrega este tema a «Mis temas».")
    return item


def count_mastered(reviews):
    return sum(1 for r in reviews.values() if r.get("state") == "mastered")


def is_due(review):
    """Una tarjeta sin review nunca se estudió, así que toca hoy."""
    return True if review is None else str(review.get("nextReviewDate", "")) <= today_str()


# =============================================================================
# GET /flashcards/{topicId}
# =============================================================================

@authenticated
def due_cards(event, user_id):
    topic_id = path_param(event, "topicId")
    params = query_params(event)

    followed = _followed_topic(user_id, topic_id)
    cards = list_cards(topic_id)
    reviews = list_reviews(user_id, topic_id)

    # «Repasar errores» del quiz: una sesión limitada a las tarjetas falladas.
    # Se piden explícitamente, así que no se filtran por fecha.
    only = params.get("cardIds")
    if only:
        wanted = {c.strip() for c in only.split(",") if c.strip()}
        selected = [c for c in cards if c["cardId"] in wanted]
    else:
        selected = [c for c in cards if is_due(reviews.get(c["cardId"]))]
        # Primero lo más atrasado; las nuevas al final, en su orden.
        selected.sort(key=lambda c: (
            str(reviews.get(c["cardId"], {}).get("nextReviewDate", "9999-12-31")),
            int(c.get("position", 0)),
        ))

    limit = min(int(params.get("limit") or DEFAULT_LIMIT), MAX_LIMIT)

    return response(200, {
        "topicId": topic_id,
        "topicName": followed.get("topicName"),
        # El encabezado «Tarjeta 3 de 8» del prototipo sale de aquí.
        "dueCount": len(selected),
        "cardsTotal": len(cards),
        "cardsMastered": count_mastered(reviews),
        "xpAvailable": len(selected) * XP_PER_CARD,
        "items": [
            {
                "cardId": c["cardId"],
                "question": c["question"],
                # La respuesta viaja con la pregunta: el prototipo la muestra
                # al instante tras responder, y el contenido no es secreto.
                "answer": c["answer"],
                "hint": c.get("hint"),
                "position": int(c.get("position", 0)),
                "state": reviews.get(c["cardId"], {}).get("state", "new"),
            }
            for c in selected[:limit]
        ],
    })


# =============================================================================
# POST /flashcards/{cardId}/review
# =============================================================================

@authenticated
def review_card(event, user_id):
    card_id = path_param(event, "cardId")
    body = parse_body(event)

    # La tabla de tarjetas tiene clave compuesta, así que con el cardId solo
    # no se puede leer la tarjeta.
    topic_id = (body.get("topicId") or "").strip()
    if not topic_id:
        raise ApiError(400, "VALIDATION_ERROR",
                       "Falta «topicId»: es parte de la clave de la tarjeta.",
                       {"fields": ["topicId"]})

    rating = body.get("rating")
    if rating not in RATINGS:
        raise ApiError(400, "INVALID_RATING",
                       "La calificación debe ser «forgot», «hard» o «easy».",
                       {"allowed": list(RATINGS)})

    followed = _followed_topic(user_id, topic_id)
    card = CARDS.get_item(Key={"topicId": topic_id, "cardId": card_id}).get("Item")
    if not card:
        raise ApiError(404, "CARD_NOT_FOUND", "La tarjeta no existe.")

    sort_key = review_key(topic_id, card_id)
    previous = REVIEWS.get_item(Key={"userId": user_id, "topicCardId": sort_key}).get("Item")

    result = schedule(
        rating,
        repetitions=int(previous.get("repetitions", 0)) if previous else 0,
        interval_days=int(previous.get("intervalDays", 0)) if previous else 0,
        ease=float(previous.get("easeFactor", EASE_INITIAL)) if previous else EASE_INITIAL,
    )

    now = to_iso()
    # El XP se gana una vez al día por tarjeta: repasar la misma veinte veces
    # no debe multiplicar la experiencia.
    already_today = bool(previous) and str(previous.get("lastReviewedAt", ""))[:10] == today_str()
    xp = 0 if already_today else XP_PER_CARD

    REVIEWS.put_item(Item={
        "userId": user_id,
        "topicCardId": sort_key,
        "topicId": topic_id,
        "cardId": card_id,
        "nextReviewDate": add_days(result["intervalDays"]),
        "lastReviewedAt": now,
        "easeFactor": decimal(result["easeFactor"]),
        "intervalDays": result["intervalDays"],
        "repetitions": result["repetitions"],
        "lapses": int(previous.get("lapses", 0) if previous else 0) + result["lapseIncrement"],
        "lastRating": rating,
        "state": result["state"],
    })

    # Se releen para enviar totales absolutos a progress: si una llamada se
    # pierde, el siguiente repaso corrige los números solo.
    reviews = list_reviews(user_id, topic_id)
    cards_total = int(followed.get("cardCount", 0)) or len(list_cards(topic_id))

    progress = call_service(PROGRESS_API, "/internal/progress/card-reviewed", payload={
        "userId": user_id,
        "topicId": topic_id,
        "topicName": followed.get("topicName"),
        "cardsTotal": cards_total,
        "cardsMastered": count_mastered(reviews),
        "reviewedAt": now,
        "xp": xp,
    })
    # Si la llamada falla, la review ya quedó guardada: se responde igual y el
    # progreso se corrige en el siguiente repaso.

    remaining = sum(1 for c in list_cards(topic_id) if is_due(reviews.get(c["cardId"])))

    return response(200, {
        "cardId": card_id, "topicId": topic_id, "rating": rating,
        "repetitions": result["repetitions"], "easeFactor": result["easeFactor"],
        "intervalDays": result["intervalDays"],
        "nextReviewDate": add_days(result["intervalDays"]),
        "state": result["state"], "xpAwarded": xp,
        "remainingDue": remaining, "progress": progress,
    })


# =============================================================================
# Endpoints internos
# =============================================================================

@internal_only
def internal_create_cards(event):
    data = parse_body(event)
    topic_id = data["topicId"]
    existing = list_cards(topic_id)
    # Se numera tras la última posición para no pisar tarjetas previas.
    next_position = max((int(c.get("position", 0)) for c in existing), default=0) + 1

    now = to_iso()
    created = []
    with CARDS.batch_writer() as batch:
        for offset, card in enumerate(data["cards"]):
            position = next_position + offset
            item = {
                "topicId": topic_id, "cardId": card_id_for(position),
                "question": card["question"], "answer": card["answer"],
                "hint": card.get("hint"), "position": position,
                "createdAt": now,
            }
            batch.put_item(Item=item)
            created.append(item)

    return response(200, {"items": created, "cardCount": len(existing) + len(created)})


@internal_only
def internal_list_cards(event):
    topic_id = parse_body(event)["topicId"]
    return response(200, {"topicId": topic_id, "items": list_cards(topic_id)})


@internal_only
def internal_get_card(event):
    """Una tarjeta concreta. La usa el servicio de IA para evaluar.

    La respuesta correcta se toma siempre de aquí y nunca de lo que envíe el
    navegador: si no, cualquiera podría mandar una respuesta correcta falsa.
    """
    data = parse_body(event)
    card = CARDS.get_item(
        Key={"topicId": data["topicId"], "cardId": data["cardId"]}
    ).get("Item")
    if not card:
        return response(404, {"error": {"code": "CARD_NOT_FOUND",
                                        "message": "La tarjeta no existe."}})
    return response(200, card)


@internal_only
def internal_delete_card(event):
    data = parse_body(event)
    topic_id, card_id = data["topicId"], data["cardId"]
    existing = list_cards(topic_id)
    if not any(c["cardId"] == card_id for c in existing):
        return response(200, {"deleted": False, "cardCount": len(existing)})

    CARDS.delete_item(Key={"topicId": topic_id, "cardId": card_id})
    return response(200, {"deleted": True, "cardCount": len(existing) - 1})


@internal_only
def internal_delete_topic_cards(event):
    topic_id = parse_body(event)["topicId"]
    cards = list_cards(topic_id)
    with CARDS.batch_writer() as batch:
        for card in cards:
            batch.delete_item(Key={"topicId": topic_id, "cardId": card["cardId"]})
    return response(200, {"deleted": len(cards)})


@internal_only
def internal_delete_topic_reviews(event):
    data = parse_body(event)
    user_id, topic_id = data["userId"], data["topicId"]
    reviews = list_reviews(user_id, topic_id)
    with REVIEWS.batch_writer() as batch:
        for card_id in reviews:
            batch.delete_item(
                Key={"userId": user_id, "topicCardId": review_key(topic_id, card_id)}
            )
    return response(200, {"deleted": len(reviews)})


@internal_only
def internal_studied_count(event):
    """Cuántas tarjetas estudió el usuario en un tema, y cuáles.

    Es el umbral del quiz: el prototipo cuenta conceptos ESTUDIADOS, no
    tarjetas del mazo.
    """
    data = parse_body(event)
    reviews = list_reviews(data["userId"], data["topicId"])
    studied = [cid for cid, r in reviews.items() if r.get("state") != "new"]
    return response(200, {
        "topicId": data["topicId"],
        "studied": len(studied),
        "mastered": count_mastered(reviews),
        "studiedCardIds": sorted(studied),
    })
