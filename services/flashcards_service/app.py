"""flashcards-service — tarjetas y repetición espaciada (historias 2 y 3).

Tablas propias: `flashcards`, `user-card-reviews`.

Por ahora solo expone las acciones internas que consumen otros servicios.
Las rutas HTTP de repaso llegan en la siguiente etapa.
"""

from boto3.dynamodb.conditions import Key
from skillpath_common.dates import to_iso
from skillpath_common.db import table
from skillpath_common.router import Router

router = Router("flashcards-service")


def _cards():
    return table("FLASHCARDS_TABLE")


def _reviews():
    return table("USER_CARD_REVIEWS_TABLE")


def card_id_for(position: int) -> str:
    """Los ceros a la izquierda hacen que la SK ordene como número."""
    return f"crd_{position:04d}"


def list_cards(topic_id: str) -> list[dict]:
    """Todas las tarjetas de un tema, en orden."""
    items, start = [], None
    while True:
        kwargs = {"KeyConditionExpression": Key("topicId").eq(topic_id)}
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = _cards().query(**kwargs)
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


# --- acciones internas -------------------------------------------------------
# Las invoca otro microservicio; no se exponen en API Gateway.

@router.internal("getTopicCards")
def get_topic_cards(data):
    """Tarjetas de un tema. Lo usa quiz-service para generar preguntas."""
    return {"topicId": data["topicId"], "items": list_cards(data["topicId"])}


@router.internal("countCards")
def count_cards(data):
    """Cuántas tarjetas tiene un tema, para derivar `cardCount`."""
    return {"topicId": data["topicId"], "count": len(list_cards(data["topicId"]))}


@router.internal("createCards")
def create_cards(data):
    """Escribe tarjetas en un mazo. Lo usa topics-service (historia 8).

    Devuelve el total de tarjetas del mazo tras la escritura, para que
    topics-service actualice `cardCount` sin tener que contar por su cuenta.
    """
    topic_id = data["topicId"]
    existing = list_cards(topic_id)
    # Se numera a partir de la última posición para no pisar tarjetas previas
    # al agregar al mazo más adelante.
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
    """Elimina una tarjeta y devuelve cuántas quedan en el mazo."""
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
    """Borra el historial de repaso de un usuario en un tema.

    Sin esto, eliminar un mazo dejaría reviews huérfanas que nadie puede
    alcanzar pero que siguen ocupando espacio.
    """
    user_id, topic_id = data["userId"], data["topicId"]
    items = _reviews().query(
        KeyConditionExpression=Key("userId").eq(user_id)
        & Key("topicCardId").begins_with(f"{topic_id}#")
    )["Items"]
    with _reviews().batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"userId": user_id, "topicCardId": item["topicCardId"]})
    return {"deleted": len(items)}


lambda_handler = router.as_handler()
