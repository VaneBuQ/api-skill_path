"""flashcards-service — tarjetas y repetición espaciada (historias 2 y 3).

Tablas propias: `flashcards`, `user-card-reviews`.
Lee `user-topics` (de topics-service) solo para comprobar que el usuario sigue
el tema; nunca escribe en ella.

Calificar una tarjeta cambia el progreso del tema, que vive en la tabla de
progress-service, así que al terminar se lo comunica en vez de escribir ahí
(decisión de la observación #6).
"""

from boto3.dynamodb.conditions import Key
from skillpath_common.dates import add_days, to_iso, today_str
from skillpath_common.db import decimal, table
from skillpath_common.errors import (
    CardNotFound,
    InvalidRating,
    NotFollowingTopic,
    ValidationError,
)
from skillpath_common.http import body_of, current_user_id, path_param, query_params
from skillpath_common.invoke import call
from skillpath_common.router import Router
from skillpath_common.rules import EASE_INITIAL, RATINGS, XP_PER_CARD, schedule

router = Router("flashcards-service")

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _cards():
    return table("FLASHCARDS_TABLE")


def _reviews():
    return table("USER_CARD_REVIEWS_TABLE")


def _user_topics():
    return table("USER_TOPICS_TABLE")


def review_key(topic_id: str, card_id: str) -> str:
    """SK compuesta: permite consultar las reviews de UN tema (observación #4)."""
    return f"{topic_id}#{card_id}"


def topic_key(user_id: str, topic_id: str) -> str:
    return f"{user_id}#{topic_id}"


def card_id_for(position: int) -> str:
    """Los ceros a la izquierda hacen que la SK ordene como número."""
    return f"crd_{position:04d}"


# --- lecturas ----------------------------------------------------------------

def list_cards(topic_id: str) -> list[dict]:
    items, start = [], None
    while True:
        kwargs = {"KeyConditionExpression": Key("topicId").eq(topic_id)}
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = _cards().query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return sorted(items, key=lambda c: int(c.get("position", 0)))


def list_reviews(user_id: str, topic_id: str) -> dict[str, dict]:
    """Reviews del usuario en un tema, indexadas por cardId.

    Es la consulta que el informe original no permitía: con `SK: cardId` habría
    que leer las reviews de todos los temas y filtrar en memoria.
    """
    items, start = [], None
    while True:
        kwargs = {
            "KeyConditionExpression": Key("userId").eq(user_id)
            & Key("topicCardId").begins_with(f"{topic_id}#")
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = _reviews().query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            break
    return {r["cardId"]: r for r in items}


def _followed_topic(user_id: str, topic_id: str) -> dict:
    item = _user_topics().get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not item:
        raise NotFollowingTopic()
    return item


def count_mastered(reviews: dict[str, dict]) -> int:
    return sum(1 for r in reviews.values() if r.get("state") == "mastered")


def is_due(review: dict | None) -> bool:
    """Una tarjeta sin review nunca se estudió, así que toca hoy."""
    if review is None:
        return True
    return str(review.get("nextReviewDate", "")) <= today_str()


# =============================================================================
# GET /flashcards/{topicId}
# =============================================================================

@router.route("GET", "/flashcards/{topicId}")
def due_cards(event, context):
    user_id = current_user_id(event)
    topic_id = path_param(event, "topicId")
    params = query_params(event)

    followed = _followed_topic(user_id, topic_id)
    cards = list_cards(topic_id)
    reviews = list_reviews(user_id, topic_id)

    # «Repasar errores» del quiz: una sesión limitada a las tarjetas falladas
    # (observación #11). Se piden explícitamente, así que no se filtran por fecha.
    only = params.get("cardIds")
    if only:
        wanted = {c.strip() for c in only.split(",") if c.strip()}
        selected = [c for c in cards if c["cardId"] in wanted]
    else:
        selected = [c for c in cards if is_due(reviews.get(c["cardId"]))]
        # Primero lo más atrasado; las tarjetas nuevas van al final, en su orden.
        selected.sort(key=lambda c: (
            str(reviews.get(c["cardId"], {}).get("nextReviewDate", "9999-12-31")),
            int(c.get("position", 0)),
        ))

    limit = min(int(params.get("limit") or DEFAULT_LIMIT), MAX_LIMIT)
    page = selected[:limit]

    return 200, {
        "topicId": topic_id,
        "topicName": followed.get("topicName"),
        # El encabezado «4 DE 12» del prototipo sale de aquí.
        "dueCount": len(selected),
        "cardsTotal": len(cards),
        "cardsMastered": count_mastered(reviews),
        "xpAvailable": len(selected) * XP_PER_CARD,
        "items": [
            {
                "cardId": c["cardId"],
                "question": c["question"],
                # La respuesta viaja con la pregunta: el prototipo voltea la
                # tarjeta al instante y el contenido no es secreto.
                "answer": c["answer"],
                "hint": c.get("hint"),
                "position": int(c.get("position", 0)),
                "state": reviews.get(c["cardId"], {}).get("state", "new"),
            }
            for c in page
        ],
    }


# =============================================================================
# POST /flashcards/{cardId}/review
# =============================================================================

@router.route("POST", "/flashcards/{cardId}/review")
def review_card(event, context):
    user_id = current_user_id(event)
    card_id = path_param(event, "cardId")
    body = body_of(event)

    # `flashcards` tiene clave compuesta, así que con el cardId solo no se
    # puede leer la tarjeta (observación #5).
    topic_id = (body.get("topicId") or "").strip()
    if not topic_id:
        raise ValidationError(
            "Falta «topicId»: es parte de la clave de la tarjeta.",
            details={"fields": ["topicId"]},
        )

    rating = body.get("rating")
    if rating not in RATINGS:
        raise InvalidRating(details={"allowed": list(RATINGS)})

    followed = _followed_topic(user_id, topic_id)
    card = _cards().get_item(Key={"topicId": topic_id, "cardId": card_id}).get("Item")
    if not card:
        raise CardNotFound()

    sort_key = review_key(topic_id, card_id)
    previous = _reviews().get_item(
        Key={"userId": user_id, "topicCardId": sort_key}
    ).get("Item")

    result = schedule(
        rating,
        repetitions=int(previous.get("repetitions", 0)) if previous else 0,
        interval_days=int(previous.get("intervalDays", 0)) if previous else 0,
        ease=float(previous.get("easeFactor", EASE_INITIAL)) if previous else EASE_INITIAL,
    )

    now = to_iso()
    today = today_str()
    # El XP se gana una vez al día por tarjeta: repasar la misma 20 veces no
    # debe multiplicar la experiencia.
    already_today = bool(previous) and str(previous.get("lastReviewedAt", ""))[:10] == today
    xp = 0 if already_today else XP_PER_CARD

    updated = {
        "userId": user_id,
        "topicCardId": sort_key,
        "topicId": topic_id,
        "cardId": card_id,
        "userTopicKey": topic_key(user_id, topic_id),
        "nextReviewDate": add_days(result["intervalDays"]),
        "lastReviewedAt": now,
        "easeFactor": decimal(result["easeFactor"]),
        "intervalDays": result["intervalDays"],
        "repetitions": result["repetitions"],
        "lapses": int(previous.get("lapses", 0) if previous else 0) + result["lapseIncrement"],
        "lastRating": rating,
        "state": result["state"],
    }
    _reviews().put_item(Item=updated)

    # Se vuelven a leer para enviar totales absolutos a progress-service: si una
    # invocación se pierde, el siguiente repaso corrige los números solo.
    reviews = list_reviews(user_id, topic_id)
    cards_total = int(followed.get("cardCount", 0)) or len(list_cards(topic_id))
    cards_mastered = count_mastered(reviews)

    progress = call("PROGRESS_FUNCTION", {
        "internalAction": "cardReviewed",
        "data": {
            "userId": user_id,
            "topicId": topic_id,
            "topicName": followed.get("topicName"),
            "cardsTotal": cards_total,
            "cardsMastered": cards_mastered,
            "reviewedAt": now,
            "xp": xp,
        },
    })
    # Si la llamada falla, la review ya quedó guardada: se responde igual y el
    # progreso se corregirá en el siguiente repaso.

    remaining = sum(
        1 for c in list_cards(topic_id) if is_due(reviews.get(c["cardId"]))
    )

    return 200, {
        "cardId": card_id,
        "topicId": topic_id,
        "rating": rating,
        "repetitions": result["repetitions"],
        "easeFactor": result["easeFactor"],
        "intervalDays": result["intervalDays"],
        "nextReviewDate": updated["nextReviewDate"],
        "state": result["state"],
        "xpAwarded": xp,
        "remainingDue": remaining,
        "progress": progress,
    }


# =============================================================================
# Acciones internas — las invoca otro microservicio
# =============================================================================

@router.internal("getTopicCards")
def get_topic_cards(data):
    """Tarjetas de un tema. Lo usa quiz-service para generar preguntas."""
    return {"topicId": data["topicId"], "items": list_cards(data["topicId"])}


@router.internal("getStudiedCount")
def get_studied_count(data):
    """Cuántas tarjetas ha estudiado el usuario en un tema.

    Es el umbral del quiz (observación #8): manda el prototipo, que cuenta
    conceptos **estudiados**, no tarjetas del mazo.
    """
    reviews = list_reviews(data["userId"], data["topicId"])
    return {
        "topicId": data["topicId"],
        "studied": sum(1 for r in reviews.values() if r.get("state") != "new"),
        "mastered": count_mastered(reviews),
    }


@router.internal("countCards")
def count_cards(data):
    return {"topicId": data["topicId"], "count": len(list_cards(data["topicId"]))}


@router.internal("createCards")
def create_cards(data):
    """Escribe tarjetas en un mazo. Lo usa topics-service (historia 8)."""
    topic_id = data["topicId"]
    existing = list_cards(topic_id)
    # Se numera tras la última posición para no pisar tarjetas previas.
    next_position = max((int(c.get("position", 0)) for c in existing), default=0) + 1

    now = to_iso()
    created = []
    with _cards().batch_writer() as batch:
        for offset, card in enumerate(data["cards"]):
            position = next_position + offset
            item = {
                "topicId": topic_id,
                "cardId": card_id_for(position),
                "question": card["question"],
                "answer": card["answer"],
                "hint": card.get("hint"),
                "position": position,
                "difficulty": card.get("difficulty", "media"),
                "createdAt": now,
            }
            batch.put_item(Item=item)
            created.append(item)

    return {"items": created, "cardCount": len(existing) + len(created)}


@router.internal("deleteCard")
def delete_card(data):
    topic_id, card_id = data["topicId"], data["cardId"]
    existing = list_cards(topic_id)
    if not any(c["cardId"] == card_id for c in existing):
        return {"deleted": False, "cardCount": len(existing)}

    _cards().delete_item(Key={"topicId": topic_id, "cardId": card_id})
    return {"deleted": True, "cardCount": len(existing) - 1}


@router.internal("deleteTopicCards")
def delete_topic_cards(data):
    """Borra todas las tarjetas de un mazo eliminado."""
    topic_id = data["topicId"]
    cards = list_cards(topic_id)
    with _cards().batch_writer() as batch:
        for card in cards:
            batch.delete_item(Key={"topicId": topic_id, "cardId": card["cardId"]})
    return {"deleted": len(cards)}


@router.internal("deleteUserTopicReviews")
def delete_user_topic_reviews(data):
    """Borra el historial de repaso de un usuario en un tema."""
    user_id, topic_id = data["userId"], data["topicId"]
    reviews = list_reviews(user_id, topic_id)
    with _reviews().batch_writer() as batch:
        for card_id in reviews:
            batch.delete_item(
                Key={"userId": user_id, "topicCardId": review_key(topic_id, card_id)}
            )
    return {"deleted": len(reviews)}


lambda_handler = router.as_handler()
