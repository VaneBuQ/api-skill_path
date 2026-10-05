"""Microservicio de progreso — historias 4, 5 y 11.

Tabla propia: progress.

Guarda dos tipos de ítem bajo la misma clave de usuario:

    topicId = "#STATS"      racha, XP y totales
    topicId = "<tema>"      progreso en ese tema

Como «#» ordena antes que cualquier letra, una sola consulta devuelve las
estadísticas globales y todos los temas: es lo que pinta la pantalla de inicio
y la de progreso enteras con una sola llamada.

Este servicio nunca calcula el progreso por su cuenta —no puede, porque las
tarjetas son de otro microservicio—: recibe los totales ya calculados.
"""

import os

import boto3
from boto3.dynamodb.conditions import Key
from common import (
    ApiError,
    authenticated,
    internal_only,
    next_streak,
    parse_body,
    path_param,
    response,
    streak_as_read,
    to_iso,
    today_str,
    yesterday_str,
)

TABLE = boto3.resource("dynamodb").Table(os.environ["PROGRESS_TABLE"])
STATS_KEY = "#STATS"


def _num(value, default=0):
    return int(value) if value is not None else default


def percent_of(mastered, total):
    return round(mastered * 100 / total) if total else 0


def _as_topic(item):
    total = _num(item.get("cardsTotal"))
    mastered = _num(item.get("cardsMastered"))
    return {
        "topicId": item["topicId"],
        "topicName": item.get("topicName"),
        "cardsTotal": total,
        "cardsMastered": mastered,
        "cardsPending": max(0, total - mastered),
        # El porcentaje se calcula al leer en vez de guardarse: un valor
        # derivado y almacenado acaba desviándose de lo que resume.
        "percent": percent_of(mastered, total),
        "lastStudiedAt": item.get("lastStudiedAt"),
        # Tema dominado: se consigue aprobando el examen, no repasando.
        "mastered": bool(item.get("mastered")),
        "masteredAt": item.get("masteredAt"),
        "lastExamScore": _num(item.get("lastExamScore"), None),
    }


def _stats_from(item):
    return {
        "streakDays": streak_as_read(
            _num(item.get("streakDays")), item.get("lastStudyDate"),
            today_str(), yesterday_str(),
        ),
        "longestStreakDays": _num(item.get("longestStreakDays")),
        "xpTotal": _num(item.get("xpTotal")),
        "lastStudiedAt": item.get("lastStudiedAt"),
        "studiedToday": item.get("lastStudyDate") == today_str(),
    }


def _touch_stats(user_id, reviewed_at, xp):
    """Actualiza el ítem #STATS tras una actividad de estudio."""
    stats = TABLE.get_item(Key={"userId": user_id, "topicId": STATS_KEY}).get("Item") or {}

    today = today_str()
    streak = next_streak(_num(stats.get("streakDays")), stats.get("lastStudyDate"),
                         today, yesterday_str())
    updated = {
        "userId": user_id,
        "topicId": STATS_KEY,
        "streakDays": streak,
        "longestStreakDays": max(streak, _num(stats.get("longestStreakDays"))),
        "lastStudyDate": today,
        "lastStudiedAt": reviewed_at,
        # El XP sí es acumulativo: es lo único que no se puede recalcular.
        "xpTotal": _num(stats.get("xpTotal")) + xp,
        "updatedAt": to_iso(),
    }
    TABLE.put_item(Item=updated)
    return updated


# =============================================================================
# GET /progress
# =============================================================================

@authenticated
def all_progress(event, user_id):
    """Resumen global y progreso de todos los temas, en una sola consulta."""
    items = TABLE.query(KeyConditionExpression=Key("userId").eq(user_id))["Items"]

    stats_item = next((i for i in items if i["topicId"] == STATS_KEY), {})
    topics = [_as_topic(i) for i in items if i["topicId"] != STATS_KEY]
    topics.sort(key=lambda t: (t["topicName"] or "").lower())

    cards_total = sum(t["cardsTotal"] for t in topics)
    cards_mastered = sum(t["cardsMastered"] for t in topics)

    return response(200, {
        "summary": {
            **_stats_from(stats_item),
            "masteryPercent": percent_of(cards_mastered, cards_total),
            "cardsMastered": cards_mastered,
            "cardsTotal": cards_total,
            "topicsMastered": sum(1 for t in topics if t["mastered"]),
        },
        "items": topics,
    })


@authenticated
def topic_progress(event, user_id):
    topic_id = path_param(event, "topicId")
    item = TABLE.get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not item or topic_id == STATS_KEY:
        raise ApiError(404, "PROGRESS_NOT_FOUND", "Todavía no tienes progreso en este tema.")
    return response(200, _as_topic(item))


# =============================================================================
# Endpoints internos
# =============================================================================

@internal_only
def internal_card_reviewed(event):
    """Registra un repaso: actualiza el tema, la racha y el XP.

    Los contadores llegan como valores absolutos, no como incrementos: si una
    llamada se pierde, el siguiente repaso deja los números correctos.
    """
    data = parse_body(event)
    user_id = data["userId"]
    topic_id = data["topicId"]
    cards_total = _num(data.get("cardsTotal"))
    cards_mastered = _num(data.get("cardsMastered"))
    reviewed_at = data.get("reviewedAt") or to_iso()

    previous = TABLE.get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item") or {}

    TABLE.put_item(Item={
        "userId": user_id,
        "topicId": topic_id,
        "topicName": data.get("topicName"),
        "cardsTotal": cards_total,
        "cardsMastered": cards_mastered,
        "cardsPending": max(0, cards_total - cards_mastered),
        "lastStudiedAt": reviewed_at,
        "updatedAt": to_iso(),
        # El estado de tema dominado lo fija el examen; repasar no lo toca.
        "mastered": previous.get("mastered", False),
        "masteredAt": previous.get("masteredAt"),
        "lastExamScore": previous.get("lastExamScore"),
    })

    stats = _touch_stats(user_id, reviewed_at, _num(data.get("xp")))
    return response(200, {
        "topicId": topic_id,
        "cardsTotal": cards_total,
        "cardsMastered": cards_mastered,
        "cardsPending": max(0, cards_total - cards_mastered),
        "percent": percent_of(cards_mastered, cards_total),
        "xpTotal": _num(stats.get("xpTotal")),
        "streakDays": _num(stats.get("streakDays")),
    })


@internal_only
def internal_quiz_completed(event):
    """Suma el XP del examen y, si aprobó, marca el tema como dominado."""
    data = parse_body(event)
    user_id = data["userId"]
    topic_id = data["topicId"]
    passed = bool(data.get("passed"))
    score = _num(data.get("score"))
    completed_at = data.get("completedAt") or to_iso()

    existing = TABLE.get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if existing:
        # Vale el último examen: si antes aprobó y ahora no, deja de estar
        # dominado. Medir el conocimiento de hoy, no el de la mejor racha.
        TABLE.update_item(
            Key={"userId": user_id, "topicId": topic_id},
            UpdateExpression=(
                "SET mastered = :m, lastExamScore = :s, lastExamAt = :t"
                + (", masteredAt = :t" if passed else "")
            ),
            ExpressionAttributeValues={":m": passed, ":s": score, ":t": completed_at},
        )

    stats = _touch_stats(user_id, completed_at, _num(data.get("xp")))
    return response(200, {
        "topicId": topic_id, "mastered": passed, "score": score,
        "xpTotal": _num(stats.get("xpTotal")),
        "streakDays": _num(stats.get("streakDays")),
    })


@internal_only
def internal_remove_topic(event):
    """Elimina el progreso de un usuario en un tema.

    Se invoca al borrar un mazo propio. Sin esto, el mazo eliminado seguiría
    apareciendo en la pantalla de progreso.
    """
    data = parse_body(event)
    TABLE.delete_item(Key={"userId": data["userId"], "topicId": data["topicId"]})
    return response(200, {"removed": True})
