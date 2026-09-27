"""Microservicio de temas — historias 1 y 8.

Tablas propias: catalog (temas) y user (los temas que sigue cada usuario).

Un mazo propio es un tema privado con dueño, no una entidad nueva: por eso el
repaso, el progreso y el quiz funcionan sobre él sin cambios. Lo único que lo
hace privado es `visibility`, y como el catálogo se consulta filtrando por ese
valor, un mazo propio no puede aparecer en él.
"""

import os
import uuid

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from common import (
    ApiError,
    authenticated,
    call_service,
    clean_text,
    parse_body,
    path_param,
    public,
    query_params,
    response,
    strip_accents,
    to_iso,
)

RESOURCE = boto3.resource("dynamodb")
TOPICS = RESOURCE.Table(os.environ["TOPICS_TABLE"])
USER_TOPICS = RESOURCE.Table(os.environ["USER_TOPICS_TABLE"])

FLASHCARDS_API = os.environ.get("FLASHCARDS_API_BASE", "")
PROGRESS_API = os.environ.get("PROGRESS_API_BASE", "")

PUBLIC_VISIBILITY = "public"
PRIVATE_VISIBILITY = "private"

NAME_MAX = 60
DESCRIPTION_MAX = 200
QUESTION_MAX = 500
ANSWER_MAX = 1000
HINT_MAX = 300
MAX_CARDS_PER_REQUEST = 50
DEFAULT_DECK_ICON = "book-open"


# --- validación de tarjetas -------------------------------------------------

def _clean_card(card, index):
    if not isinstance(card, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Cada tarjeta debe ser un objeto.",
                       {"fields": [f"cards[{index}]"]})
    try:
        question = clean_text(card.get("question"), "question", QUESTION_MAX)
        answer = clean_text(card.get("answer"), "answer", ANSWER_MAX)
    except ApiError as exc:
        campos = [f"cards[{index}].{f}" for f in (exc.details or {}).get("fields", [])]
        raise ApiError(400, "VALIDATION_ERROR", exc.message, {"fields": campos}) from exc
    return {
        "question": question,
        "answer": answer,
        "hint": clean_text(card.get("hint"), "hint", HINT_MAX, required=False),
    }


def _clean_cards(value, minimum=1):
    if not isinstance(value, list):
        raise ApiError(400, "VALIDATION_ERROR", "«cards» debe ser una lista de tarjetas.",
                       {"fields": ["cards"]})
    if len(value) < minimum:
        # Historia 8: «ingresa nombre, pregunta y respuesta de al menos una tarjeta».
        raise ApiError(400, "VALIDATION_ERROR",
                       f"El mazo necesita al menos {minimum} tarjeta.",
                       {"fields": ["cards"], "minItems": minimum})
    if len(value) > MAX_CARDS_PER_REQUEST:
        raise ApiError(400, "VALIDATION_ERROR",
                       f"Puedes agregar hasta {MAX_CARDS_PER_REQUEST} tarjetas por vez.",
                       {"fields": ["cards"], "maxItems": MAX_CARDS_PER_REQUEST})
    return [_clean_card(c, i) for i, c in enumerate(value)]


# --- acceso a datos ---------------------------------------------------------

def _topic_or_404(topic_id):
    topic = TOPICS.get_item(Key={"topicId": topic_id}).get("Item")
    if not topic or topic.get("visibility") == "deleted":
        raise ApiError(404, "TOPIC_NOT_FOUND", "El tema no existe.")
    return topic


def _own_deck_or_404(topic_id, user_id):
    """Un mazo ajeno responde 404, no 403.

    Decir «existe pero no es tuyo» revelaría qué identificadores existen. Como
    los mazos son privados, para quien no es su dueño simplemente no existen.
    """
    topic = TOPICS.get_item(Key={"topicId": topic_id}).get("Item")
    if not topic or topic.get("visibility") == "deleted" or topic.get("ownerId") != user_id:
        raise ApiError(404, "NOT_FOUND", "El mazo no existe.")
    return topic


def _sync_card_count(topic_id, user_id, count):
    """`cardCount` está denormalizado en dos sitios porque DynamoDB no tiene JOIN."""
    TOPICS.update_item(
        Key={"topicId": topic_id},
        UpdateExpression="SET cardCount = :c",
        ExpressionAttributeValues={":c": count},
    )
    USER_TOPICS.update_item(
        Key={"userId": user_id, "topicId": topic_id},
        UpdateExpression="SET cardCount = :c",
        ExpressionAttributeValues={":c": count},
    )


# =============================================================================
# Catálogo y «Mis temas» — historia 1
# =============================================================================

@public
def list_topics(event):
    search = (query_params(event).get("search") or "").strip()

    items = TOPICS.query(
        IndexName="catalog-index",
        KeyConditionExpression=Key("visibility").eq(PUBLIC_VISIBILITY),
    )["Items"]

    if search:
        # El filtro se hace aquí y no en DynamoDB porque hay que ignorar
        # tildes; el catálogo son pocas decenas de temas.
        needle = strip_accents(search)
        items = [t for t in items if needle in strip_accents(t["name"])]

    return response(200, {"items": [
        {
            "topicId": t["topicId"],
            "name": t["name"],
            "description": t.get("description"),
            "cardCount": int(t.get("cardCount", 0)),
            "icon": t.get("icon"),
            "level": t.get("level"),
            "category": t.get("category"),
        }
        for t in items
    ]})


@authenticated
def follow_topic(event, user_id):
    topic = _topic_or_404(path_param(event, "topicId"))
    if topic.get("visibility") != PUBLIC_VISIBILITY:
        # Un mazo privado de otra persona no se puede seguir.
        raise ApiError(404, "TOPIC_NOT_FOUND", "El tema no existe.")

    item = {
        "userId": user_id,
        "topicId": topic["topicId"],
        "topicName": topic["name"],
        "cardCount": int(topic.get("cardCount", 0)),
        "icon": topic.get("icon"),
        "isOwn": False,
        "followedAt": to_iso(),
    }
    try:
        USER_TOPICS.put_item(Item=item, ConditionExpression=Attr("topicId").not_exists())
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Seguir dos veces no es un error: la app queda en el mismo estado.
        return response(200, {
            "topicId": topic["topicId"], "name": topic["name"],
            "cardCount": int(topic.get("cardCount", 0)), "alreadyFollowing": True,
        })

    # Historia 1: «se muestra el número total de conceptos del mazo».
    return response(201, {
        "topicId": topic["topicId"], "name": topic["name"],
        "cardCount": int(topic.get("cardCount", 0)),
        "followedAt": item["followedAt"], "alreadyFollowing": False,
    })


@authenticated
def unfollow_topic(event, user_id):
    topic_id = path_param(event, "topicId")
    existing = USER_TOPICS.get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not existing:
        raise ApiError(404, "NOT_FOUND", "No sigues este tema.")
    if existing.get("isOwn"):
        # Quitarlo de «Mis temas» lo dejaría inaccesible para siempre, porque
        # un mazo propio no aparece en el catálogo.
        raise ApiError(409, "OWN_DECK_CANNOT_UNFOLLOW",
                       "Este es un mazo tuyo. Elimínalo desde «Mis mazos».")

    USER_TOPICS.delete_item(Key={"userId": user_id, "topicId": topic_id})
    return response(204)


@authenticated
def my_topics(event, user_id):
    items = USER_TOPICS.query(KeyConditionExpression=Key("userId").eq(user_id))["Items"]
    return response(200, {"items": [
        {
            "topicId": t["topicId"],
            "name": t.get("topicName"),
            "cardCount": int(t.get("cardCount", 0)),
            "icon": t.get("icon"),
            "isOwn": bool(t.get("isOwn")),
            "followedAt": t.get("followedAt"),
        }
        for t in sorted(items, key=lambda t: (t.get("topicName") or "").lower())
    ]})


# =============================================================================
# Mazos propios — historia 8
# =============================================================================

@authenticated
def create_deck(event, user_id):
    body = parse_body(event)
    name = clean_text(body.get("name"), "name", NAME_MAX)
    description = clean_text(body.get("description"), "description",
                             DESCRIPTION_MAX, required=False)
    cards = _clean_cards(body.get("cards"))

    topic_id = f"deck_{uuid.uuid4().hex}"

    # Las tarjetas se escriben ANTES que el tema. Si algo falla aquí, quedan
    # tarjetas que nadie referencia —invisibles e inofensivas— en vez de un
    # mazo vacío que el usuario sí vería en su lista.
    created = call_service(FLASHCARDS_API, "/internal/cards",
                           payload={"topicId": topic_id, "cards": cards})
    if created is None:
        raise ApiError(503, "DECK_CREATION_FAILED",
                       "No se pudo guardar el mazo. Inténtalo otra vez.")

    now = to_iso()
    card_count = int(created["cardCount"])

    TOPICS.put_item(Item={
        "topicId": topic_id,
        "name": name,
        "description": description,
        "cardCount": card_count,
        "icon": DEFAULT_DECK_ICON,
        "level": "propio",
        "category": "Mis mazos",
        "visibility": PRIVATE_VISIBILITY,
        "ownerId": user_id,
        "createdAt": now,
    })
    # El dueño sigue su propio mazo automáticamente: así aparece en «Mis temas»
    # y todo el flujo de repaso lo encuentra sin cambios.
    USER_TOPICS.put_item(Item={
        "userId": user_id, "topicId": topic_id, "topicName": name,
        "cardCount": card_count, "icon": DEFAULT_DECK_ICON,
        "isOwn": True, "followedAt": now,
    })

    return response(201, {
        "topicId": topic_id, "name": name, "description": description,
        "cardCount": card_count, "icon": DEFAULT_DECK_ICON,
        "isOwn": True, "createdAt": now,
    })


@authenticated
def my_decks(event, user_id):
    items = USER_TOPICS.query(
        KeyConditionExpression=Key("userId").eq(user_id),
        FilterExpression=Attr("isOwn").eq(True),
    )["Items"]
    return response(200, {"items": [
        {
            "topicId": t["topicId"], "name": t.get("topicName"),
            "cardCount": int(t.get("cardCount", 0)), "icon": t.get("icon"),
            "createdAt": t.get("followedAt"),
        }
        for t in sorted(items, key=lambda t: t.get("followedAt") or "", reverse=True)
    ]})


@authenticated
def deck_detail(event, user_id):
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    cards = call_service(FLASHCARDS_API, "/internal/cards/list",
                         payload={"topicId": topic["topicId"]})
    items = (cards or {}).get("items", [])

    return response(200, {
        "topicId": topic["topicId"], "name": topic["name"],
        "description": topic.get("description"),
        "cardCount": int(topic.get("cardCount", 0)),
        "icon": topic.get("icon"), "createdAt": topic.get("createdAt"),
        "cards": [
            {"cardId": c["cardId"], "question": c["question"],
             "answer": c["answer"], "hint": c.get("hint")}
            for c in items
        ],
    })


@authenticated
def rename_deck(event, user_id):
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    body = parse_body(event)
    name = clean_text(body.get("name"), "name", NAME_MAX)
    description = clean_text(body.get("description"), "description",
                             DESCRIPTION_MAX, required=False)

    TOPICS.update_item(
        Key={"topicId": topic["topicId"]},
        UpdateExpression="SET #n = :n, description = :d",
        ExpressionAttributeNames={"#n": "name"},
        ExpressionAttributeValues={":n": name, ":d": description},
    )
    # El nombre está duplicado en user-topics para poder pintar «Mis temas»
    # con una sola consulta; hay que mantenerlo al día.
    USER_TOPICS.update_item(
        Key={"userId": user_id, "topicId": topic["topicId"]},
        UpdateExpression="SET topicName = :n",
        ExpressionAttributeValues={":n": name},
    )
    return response(200, {
        "topicId": topic["topicId"], "name": name, "description": description,
        "cardCount": int(topic.get("cardCount", 0)),
    })


@authenticated
def delete_deck(event, user_id):
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    topic_id = topic["topicId"]

    # Primero desaparece de la vista del usuario; la limpieza va después.
    USER_TOPICS.delete_item(Key={"userId": user_id, "topicId": topic_id})
    TOPICS.update_item(
        Key={"topicId": topic_id},
        UpdateExpression="SET visibility = :v, deletedAt = :t",
        ExpressionAttributeValues={":v": "deleted", ":t": to_iso()},
    )

    # Los datos derivados son de otros servicios. Si alguna de estas llamadas
    # falla, el mazo ya no se ve; solo quedarían filas huérfanas inalcanzables.
    call_service(FLASHCARDS_API, "/internal/cards/delete-topic",
                 payload={"topicId": topic_id})
    call_service(FLASHCARDS_API, "/internal/reviews/delete-topic",
                 payload={"userId": user_id, "topicId": topic_id})
    # Sin esto, el mazo borrado seguiría apareciendo en «Mi progreso».
    call_service(PROGRESS_API, "/internal/progress/remove-topic",
                 payload={"userId": user_id, "topicId": topic_id})

    return response(204)


@authenticated
def add_cards(event, user_id):
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    body = parse_body(event)
    # Acepta una tarjeta suelta o una lista, que es como la usa el formulario.
    payload = body.get("cards") if "cards" in body else [body]
    cards = _clean_cards(payload)

    created = call_service(FLASHCARDS_API, "/internal/cards",
                           payload={"topicId": topic["topicId"], "cards": cards})
    if created is None:
        raise ApiError(503, "CARD_CREATION_FAILED",
                       "No se pudieron guardar las tarjetas. Inténtalo otra vez.")

    card_count = int(created["cardCount"])
    _sync_card_count(topic["topicId"], user_id, card_count)

    return response(201, {
        "topicId": topic["topicId"], "cardCount": card_count,
        "items": [
            {"cardId": c["cardId"], "question": c["question"],
             "answer": c["answer"], "hint": c.get("hint")}
            for c in created["items"]
        ],
    })


@authenticated
def remove_card(event, user_id):
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    card_id = path_param(event, "cardId")

    result = call_service(FLASHCARDS_API, "/internal/cards/delete",
                          payload={"topicId": topic["topicId"], "cardId": card_id})
    if result is None:
        raise ApiError(503, "CARD_DELETION_FAILED",
                       "No se pudo eliminar la tarjeta. Inténtalo otra vez.")
    if not result["deleted"]:
        raise ApiError(404, "NOT_FOUND", "La tarjeta no existe en este mazo.")

    _sync_card_count(topic["topicId"], user_id, int(result["cardCount"]))
    return response(204)
