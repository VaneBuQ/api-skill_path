"""topics-service — catálogo, «Mis temas» y mazos propios (historias 1 y 8).

Tablas propias: `topics`, `user-topics`.

Un **mazo propio es un tema privado con dueño**. Modelarlo así hace que el
repaso, el progreso y el quiz funcionen sobre él sin cambiar una línea, que es
justo lo que pide la historia 8: «queda disponible para repasar junto a los
demás temas».

Las tarjetas son de flashcards-service y el progreso de progress-service, así
que crear o borrar un mazo se los pide a ellos en vez de tocar sus tablas.
"""

import unicodedata

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from skillpath_common.dates import to_iso
from skillpath_common.db import table
from skillpath_common.errors import (
    Conflict,
    NotFound,
    TopicNotFound,
    ValidationError,
)
from skillpath_common.http import body_of, current_user_id, path_param, query_params
from skillpath_common.ids import ulid
from skillpath_common.invoke import call
from skillpath_common.router import Router

router = Router("topics-service")

PUBLIC = "public"
PRIVATE = "private"

NAME_MAX = 60
DESCRIPTION_MAX = 200
QUESTION_MAX = 500
ANSWER_MAX = 1000
HINT_MAX = 300
MAX_CARDS_PER_REQUEST = 50
DEFAULT_DECK_ICON = "book-open"


def _topics():
    return table("TOPICS_TABLE")


def _user_topics():
    return table("USER_TOPICS_TABLE")


# --- utilidades --------------------------------------------------------------

def strip_accents(value: str) -> str:
    """«Álgebra» → «algebra», para que el buscador no exija tildes."""
    normalized = unicodedata.normalize("NFD", value)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower()


def _text(value, field: str, *, max_length: int, required: bool = True) -> str | None:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValidationError(f"El campo «{field}» es obligatorio.",
                                  details={"fields": [field]})
        return None
    if len(text) > max_length:
        raise ValidationError(
            f"El campo «{field}» no puede superar los {max_length} caracteres.",
            details={"fields": [field], "maxLength": max_length},
        )
    return text


def _clean_card(card, index: int) -> dict:
    if not isinstance(card, dict):
        raise ValidationError("Cada tarjeta debe ser un objeto.",
                              details={"fields": [f"cards[{index}]"]})
    try:
        question = _text(card.get("question"), "question", max_length=QUESTION_MAX)
        answer = _text(card.get("answer"), "answer", max_length=ANSWER_MAX)
    except ValidationError as exc:
        campos = [f"cards[{index}].{f}" for f in (exc.details or {}).get("fields", [])]
        raise ValidationError(exc.message, details={"fields": campos}) from exc
    return {
        "question": question,
        "answer": answer,
        "hint": _text(card.get("hint"), "hint", max_length=HINT_MAX, required=False),
    }


def _clean_cards(value, *, minimum: int) -> list[dict]:
    if not isinstance(value, list):
        raise ValidationError("«cards» debe ser una lista de tarjetas.",
                              details={"fields": ["cards"]})
    if len(value) < minimum:
        # Historia 8: «ingresa nombre, pregunta y respuesta de al menos una tarjeta».
        raise ValidationError(
            f"El mazo necesita al menos {minimum} tarjeta.",
            details={"fields": ["cards"], "minItems": minimum},
        )
    if len(value) > MAX_CARDS_PER_REQUEST:
        raise ValidationError(
            f"Puedes agregar hasta {MAX_CARDS_PER_REQUEST} tarjetas por vez.",
            details={"fields": ["cards"], "maxItems": MAX_CARDS_PER_REQUEST},
        )
    return [_clean_card(card, i) for i, card in enumerate(value)]


def _topic_or_404(topic_id: str) -> dict:
    topic = _topics().get_item(Key={"topicId": topic_id}).get("Item")
    if not topic or topic.get("visibility") == "deleted":
        raise TopicNotFound()
    return topic


def _own_deck_or_404(topic_id: str, user_id: str) -> dict:
    """Un mazo ajeno responde 404, no 403.

    Decir «existe pero no es tuyo» revelaría qué identificadores existen. Como
    los mazos son privados, para quien no es su dueño simplemente no existen.
    """
    topic = _topics().get_item(Key={"topicId": topic_id}).get("Item")
    if not topic or topic.get("visibility") == "deleted" or topic.get("ownerId") != user_id:
        raise NotFound("El mazo no existe.")
    return topic


def _as_catalog_item(topic: dict) -> dict:
    return {
        "topicId": topic["topicId"],
        "name": topic["name"],
        "description": topic.get("description"),
        "cardCount": int(topic.get("cardCount", 0)),
        "icon": topic.get("icon"),
        "level": topic.get("level"),
    }


def _sync_card_count(topic: dict, count: int, user_id: str) -> None:
    """Mantiene `cardCount` igual en el tema y en la fila de «Mis temas».

    Está denormalizado en dos sitios porque DynamoDB no tiene JOIN; el precio
    es tener que actualizarlo en ambos.
    """
    _topics().update_item(
        Key={"topicId": topic["topicId"]},
        UpdateExpression="SET cardCount = :c",
        ExpressionAttributeValues={":c": count},
    )
    _user_topics().update_item(
        Key={"userId": user_id, "topicId": topic["topicId"]},
        UpdateExpression="SET cardCount = :c",
        ExpressionAttributeValues={":c": count},
    )


# =============================================================================
# Catálogo y «Mis temas» — historia 1
# =============================================================================

@router.route("GET", "/topics")
def list_topics(event, context):
    search = (query_params(event).get("search") or "").strip()

    # El índice devuelve el catálogo ya ordenado por nombre, sin hacer Scan.
    items = _topics().query(
        IndexName="catalog-index",
        KeyConditionExpression=Key("visibility").eq(PUBLIC),
    )["Items"]

    if search:
        # El filtro se hace aquí y no en DynamoDB porque hay que ignorar
        # tildes: el catálogo son pocas decenas de temas.
        needle = strip_accents(search)
        items = [t for t in items if needle in strip_accents(t["name"])]

    return 200, {"items": [_as_catalog_item(t) for t in items]}


@router.route("POST", "/topics/{topicId}/follow")
def follow_topic(event, context):
    user_id = current_user_id(event)
    topic = _topic_or_404(path_param(event, "topicId"))

    if topic.get("visibility") != PUBLIC:
        # Un mazo privado de otra persona no se puede seguir.
        raise TopicNotFound()

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
        _user_topics().put_item(
            Item=item, ConditionExpression=Attr("topicId").not_exists()
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Seguir dos veces no es un error: la app queda en el mismo estado.
        return 200, {
            "topicId": topic["topicId"],
            "name": topic["name"],
            # Historia 1: «se muestra el número total de conceptos del mazo».
            "cardCount": int(topic.get("cardCount", 0)),
            "alreadyFollowing": True,
        }

    return 201, {
        "topicId": topic["topicId"],
        "name": topic["name"],
        "cardCount": int(topic.get("cardCount", 0)),
        "followedAt": item["followedAt"],
        "alreadyFollowing": False,
    }


@router.route("DELETE", "/topics/{topicId}/follow")
def unfollow_topic(event, context):
    user_id = current_user_id(event)
    topic_id = path_param(event, "topicId")

    existing = _user_topics().get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not existing:
        raise NotFound("No sigues este tema.")
    if existing.get("isOwn"):
        # Un mazo propio se elimina, no se deja de seguir: si solo se quitara
        # de la lista, quedaría inaccesible para siempre.
        raise Conflict(
            "Este es un mazo tuyo. Elimínalo desde «Mis mazos».",
            code="OWN_DECK_CANNOT_UNFOLLOW",
        )

    _user_topics().delete_item(Key={"userId": user_id, "topicId": topic_id})
    return 204, None


@router.route("GET", "/me/topics")
def my_topics(event, context):
    items = _user_topics().query(
        KeyConditionExpression=Key("userId").eq(current_user_id(event))
    )["Items"]
    return 200, {
        "items": [
            {
                "topicId": t["topicId"],
                "name": t.get("topicName"),
                "cardCount": int(t.get("cardCount", 0)),
                "icon": t.get("icon"),
                "isOwn": bool(t.get("isOwn")),
                "followedAt": t.get("followedAt"),
            }
            for t in sorted(items, key=lambda t: (t.get("topicName") or "").lower())
        ]
    }


# =============================================================================
# Mazos propios — historia 8
# =============================================================================

@router.route("POST", "/me/decks")
def create_deck(event, context):
    user_id = current_user_id(event)
    body = body_of(event)

    name = _text(body.get("name"), "name", max_length=NAME_MAX)
    description = _text(
        body.get("description"), "description", max_length=DESCRIPTION_MAX, required=False
    )
    cards = _clean_cards(body.get("cards"), minimum=1)

    topic_id = f"deck_{ulid()}"

    # Las tarjetas se escriben ANTES que el tema. Si algo falla aquí, quedan
    # tarjetas que nadie referencia (invisibles e inofensivas) en vez de un
    # mazo vacío que el usuario sí vería.
    created = call("FLASHCARDS_FUNCTION", {
        "internalAction": "createCards",
        "data": {"topicId": topic_id, "cards": cards},
    })
    if created is None:
        raise Conflict(
            "No se pudo guardar el mazo. Inténtalo otra vez.",
            code="DECK_CREATION_FAILED",
            status=503,
        )

    now = to_iso()
    card_count = int(created["cardCount"])

    _topics().put_item(Item={
        "topicId": topic_id,
        "name": name,
        "description": description,
        "cardCount": card_count,
        "icon": DEFAULT_DECK_ICON,
        "level": "propio",
        # Privado: nunca aparece en el catálogo, porque ese se consulta
        # filtrando visibility = "public".
        "visibility": PRIVATE,
        "ownerId": user_id,
        "createdAt": now,
    })

    # El dueño sigue su propio mazo automáticamente. Así aparece en «Mis temas»
    # y todo el flujo de repaso lo encuentra sin cambios.
    _user_topics().put_item(Item={
        "userId": user_id,
        "topicId": topic_id,
        "topicName": name,
        "cardCount": card_count,
        "icon": DEFAULT_DECK_ICON,
        "isOwn": True,
        "followedAt": now,
    })

    return 201, {
        "topicId": topic_id,
        "name": name,
        "description": description,
        "cardCount": card_count,
        "icon": DEFAULT_DECK_ICON,
        "isOwn": True,
        "createdAt": now,
    }


@router.route("GET", "/me/decks")
def my_decks(event, context):
    items = _user_topics().query(
        KeyConditionExpression=Key("userId").eq(current_user_id(event)),
        FilterExpression=Attr("isOwn").eq(True),
    )["Items"]
    return 200, {
        "items": [
            {
                "topicId": t["topicId"],
                "name": t.get("topicName"),
                "cardCount": int(t.get("cardCount", 0)),
                "icon": t.get("icon"),
                "createdAt": t.get("followedAt"),
            }
            for t in sorted(items, key=lambda t: t.get("followedAt") or "", reverse=True)
        ]
    }


@router.route("GET", "/me/decks/{topicId}")
def deck_detail(event, context):
    user_id = current_user_id(event)
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)

    cards = call("FLASHCARDS_FUNCTION", {
        "internalAction": "getTopicCards",
        "data": {"topicId": topic["topicId"]},
    })
    items = (cards or {}).get("items", [])

    return 200, {
        "topicId": topic["topicId"],
        "name": topic["name"],
        "description": topic.get("description"),
        "cardCount": int(topic.get("cardCount", 0)),
        "icon": topic.get("icon"),
        "createdAt": topic.get("createdAt"),
        "cards": [
            {
                "cardId": c["cardId"],
                "question": c["question"],
                "answer": c["answer"],
                "hint": c.get("hint"),
            }
            for c in items
        ],
    }


@router.route("PATCH", "/me/decks/{topicId}")
def rename_deck(event, context):
    user_id = current_user_id(event)
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    body = body_of(event)

    name = _text(body.get("name"), "name", max_length=NAME_MAX)
    description = _text(
        body.get("description"), "description", max_length=DESCRIPTION_MAX, required=False
    )

    _topics().update_item(
        Key={"topicId": topic["topicId"]},
        UpdateExpression="SET #n = :n, description = :d",
        ExpressionAttributeNames={"#n": "name"},
        ExpressionAttributeValues={":n": name, ":d": description},
    )
    # El nombre está duplicado en user-topics para poder pintar «Mis temas»
    # con una sola consulta; hay que mantenerlo al día.
    _user_topics().update_item(
        Key={"userId": user_id, "topicId": topic["topicId"]},
        UpdateExpression="SET topicName = :n",
        ExpressionAttributeValues={":n": name},
    )

    return 200, {
        "topicId": topic["topicId"],
        "name": name,
        "description": description,
        "cardCount": int(topic.get("cardCount", 0)),
    }


@router.route("DELETE", "/me/decks/{topicId}")
def delete_deck(event, context):
    user_id = current_user_id(event)
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    topic_id = topic["topicId"]

    # Primero desaparece de la vista del usuario; la limpieza va después.
    _user_topics().delete_item(Key={"userId": user_id, "topicId": topic_id})
    _topics().update_item(
        Key={"topicId": topic_id},
        UpdateExpression="SET visibility = :v, deletedAt = :t",
        ExpressionAttributeValues={":v": "deleted", ":t": to_iso()},
    )

    # Los datos derivados son de otros servicios. Si alguna de estas llamadas
    # falla, el mazo ya no se ve; solo quedarían filas huérfanas inalcanzables.
    call("FLASHCARDS_FUNCTION", {
        "internalAction": "deleteTopicCards", "data": {"topicId": topic_id},
    })
    call("FLASHCARDS_FUNCTION", {
        "internalAction": "deleteUserTopicReviews",
        "data": {"userId": user_id, "topicId": topic_id},
    })
    # Sin esto, el mazo borrado seguiría apareciendo en «Mi progreso».
    call("PROGRESS_FUNCTION", {
        "internalAction": "removeTopic", "data": {"userId": user_id, "topicId": topic_id},
    })

    return 204, None


@router.route("POST", "/me/decks/{topicId}/cards")
def add_cards(event, context):
    user_id = current_user_id(event)
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    body = body_of(event)

    # Acepta una tarjeta suelta o una lista, que es como la usará el formulario.
    payload = body.get("cards") if "cards" in body else [body]
    cards = _clean_cards(payload, minimum=1)

    created = call("FLASHCARDS_FUNCTION", {
        "internalAction": "createCards",
        "data": {"topicId": topic["topicId"], "cards": cards},
    })
    if created is None:
        raise Conflict(
            "No se pudieron guardar las tarjetas. Inténtalo otra vez.",
            code="CARD_CREATION_FAILED",
            status=503,
        )

    card_count = int(created["cardCount"])
    _sync_card_count(topic, card_count, user_id)

    return 201, {
        "topicId": topic["topicId"],
        "cardCount": card_count,
        "items": [
            {
                "cardId": c["cardId"],
                "question": c["question"],
                "answer": c["answer"],
                "hint": c.get("hint"),
            }
            for c in created["items"]
        ],
    }


@router.route("DELETE", "/me/decks/{topicId}/cards/{cardId}")
def remove_card(event, context):
    user_id = current_user_id(event)
    topic = _own_deck_or_404(path_param(event, "topicId"), user_id)
    card_id = path_param(event, "cardId")

    result = call("FLASHCARDS_FUNCTION", {
        "internalAction": "deleteCard",
        "data": {"topicId": topic["topicId"], "cardId": card_id},
    })
    if result is None:
        raise Conflict(
            "No se pudo eliminar la tarjeta. Inténtalo otra vez.",
            code="CARD_DELETION_FAILED",
            status=503,
        )
    if not result["deleted"]:
        raise NotFound("La tarjeta no existe en este mazo.")

    _sync_card_count(topic, int(result["cardCount"]), user_id)
    return 204, None


lambda_handler = router.as_handler()
