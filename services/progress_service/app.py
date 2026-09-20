"""progress-service — progreso por tema, racha y XP (historias 4, 5 y 11).

Tabla propia: `user-progress`.

Guarda dos tipos de ítem bajo la misma clave `userId`:

    SK = "#STATS"          racha, XP y totales del usuario
    SK = "<topicId>"       progreso en ese tema

Como «#» ordena antes que cualquier letra, una sola Query devuelve las
estadísticas globales y todos los temas de golpe: es la consulta que pinta el
Home y «Mi progreso» enteros.

Este servicio nunca calcula el progreso por su cuenta — no puede, porque las
tarjetas y las reviews son de flashcards-service. Recibe los totales ya
calculados y los guarda.
"""

from boto3.dynamodb.conditions import Key
from skillpath_common.dates import to_iso, today_str, yesterday_str
from skillpath_common.db import table
from skillpath_common.errors import ProgressNotFound
from skillpath_common.http import current_user_id, path_param
from skillpath_common.router import Router
from skillpath_common.rules import next_streak, streak_as_read

router = Router("progress-service")

STATS_KEY = "#STATS"


def _progress():
    return table("USER_PROGRESS_TABLE")


def _num(value, default=0):
    return int(value) if value is not None else default


def percent_of(mastered: int, total: int) -> int:
    return round(mastered * 100 / total) if total else 0


# --- acciones internas -------------------------------------------------------

@router.internal("cardReviewed")
def card_reviewed(data):
    """Registra un repaso: actualiza el tema, la racha y el XP.

    Los contadores llegan como **valores absolutos**, no como incrementos. Así,
    si una invocación se pierde, el siguiente repaso deja los números
    correctos: no hay deriva acumulada.
    """
    user_id = data["userId"]
    topic_id = data["topicId"]
    cards_total = _num(data.get("cardsTotal"))
    cards_mastered = _num(data.get("cardsMastered"))
    reviewed_at = data.get("reviewedAt") or to_iso()
    xp = _num(data.get("xp"))

    _progress().put_item(Item={
        "userId": user_id,
        "topicId": topic_id,
        "topicName": data.get("topicName"),
        "cardsTotal": cards_total,
        "cardsMastered": cards_mastered,
        "cardsPending": max(0, cards_total - cards_mastered),
        "lastStudiedAt": reviewed_at,
        "updatedAt": to_iso(),
    })

    stats = _touch_stats(user_id, reviewed_at=reviewed_at, xp=xp)
    return {
        "topicId": topic_id,
        "cardsTotal": cards_total,
        "cardsMastered": cards_mastered,
        "cardsPending": max(0, cards_total - cards_mastered),
        "percent": percent_of(cards_mastered, cards_total),
        "xpTotal": _num(stats.get("xpTotal")),
        "streakDays": _num(stats.get("streakDays")),
    }


@router.internal("quizCompleted")
def quiz_completed(data):
    """Suma el XP de un quiz terminado y cuenta el día para la racha."""
    stats = _touch_stats(
        data["userId"],
        reviewed_at=data.get("completedAt") or to_iso(),
        xp=_num(data.get("xp")),
    )
    return {"xpTotal": _num(stats.get("xpTotal")), "streakDays": _num(stats.get("streakDays"))}


@router.internal("removeTopic")
def remove_topic(data):
    """Elimina el progreso de un usuario en un tema.

    Se invoca al borrar un mazo propio (historia 8). Sin esto, el mazo
    eliminado seguiría apareciendo en la pantalla «Mi progreso».
    """
    _progress().delete_item(Key={"userId": data["userId"], "topicId": data["topicId"]})
    return {"removed": True}


# --- racha y XP --------------------------------------------------------------

def _touch_stats(user_id: str, *, reviewed_at: str, xp: int) -> dict:
    """Actualiza el ítem #STATS tras una actividad de estudio."""
    stats = _progress().get_item(
        Key={"userId": user_id, "topicId": STATS_KEY}
    ).get("Item") or {}

    today = today_str()
    last_study = stats.get("lastStudyDate")
    streak = next_streak(_num(stats.get("streakDays")), last_study, today, yesterday_str())
    longest = max(streak, _num(stats.get("longestStreakDays")))

    updated = {
        "userId": user_id,
        "topicId": STATS_KEY,
        "streakDays": streak,
        "longestStreakDays": longest,
        "lastStudyDate": today,
        "lastStudiedAt": reviewed_at,
        # El XP sí es acumulativo: es lo único que no se puede recalcular.
        "xpTotal": _num(stats.get("xpTotal")) + xp,
        "updatedAt": to_iso(),
    }
    _progress().put_item(Item=updated)
    return updated


def _as_topic(item: dict) -> dict:
    total = _num(item.get("cardsTotal"))
    mastered = _num(item.get("cardsMastered"))
    return {
        "topicId": item["topicId"],
        "topicName": item.get("topicName"),
        "cardsTotal": total,
        "cardsMastered": mastered,
        "cardsPending": max(0, total - mastered),
        # El porcentaje se calcula al leer en vez de guardarse: un valor
        # derivado y almacenado acaba desviándose de los números que resume.
        "percent": percent_of(mastered, total),
        "lastStudiedAt": item.get("lastStudiedAt"),
    }


def _stats_from(item: dict) -> dict:
    """Estadísticas tal como deben mostrarse."""
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


# =============================================================================
# GET /progress  ·  observación #2
# =============================================================================

@router.route("GET", "/progress")
def all_progress(event, context):
    """Resumen global y progreso de todos los temas, en una sola consulta.

    Es el endpoint que faltaba en el informe: con solo `GET /progress/{topicId}`,
    pintar el Home con tres temas costaba tres llamadas HTTP, cuando una única
    Query de DynamoDB ya devuelve todas las filas del usuario.
    """
    user_id = current_user_id(event)
    items = read_all(user_id)

    stats_item = next((i for i in items if i["topicId"] == STATS_KEY), {})
    topics = [_as_topic(i) for i in items if i["topicId"] != STATS_KEY]
    topics.sort(key=lambda t: (t["topicName"] or "").lower())

    cards_total = sum(t["cardsTotal"] for t in topics)
    cards_mastered = sum(t["cardsMastered"] for t in topics)

    return 200, {
        "summary": {
            **_stats_from(stats_item),
            # «58% dominio global» y «73 conceptos dominados» del prototipo.
            "masteryPercent": percent_of(cards_mastered, cards_total),
            "cardsMastered": cards_mastered,
            "cardsTotal": cards_total,
        },
        "items": topics,
    }


# =============================================================================
# GET /progress/{topicId}  ·  historia 4
# =============================================================================

@router.route("GET", "/progress/{topicId}")
def topic_progress(event, context):
    user_id = current_user_id(event)
    topic_id = path_param(event, "topicId")

    item = _progress().get_item(Key={"userId": user_id, "topicId": topic_id}).get("Item")
    if not item or topic_id == STATS_KEY:
        raise ProgressNotFound()

    # Historia 4: «THEN se muestra el porcentaje de conceptos dominados vs.
    # pendientes AND se muestra la fecha del último repaso realizado».
    return 200, _as_topic(item)


def read_stats(user_id: str) -> dict:
    return _stats_from(_progress().get_item(
        Key={"userId": user_id, "topicId": STATS_KEY}
    ).get("Item") or {})


def read_all(user_id: str) -> list[dict]:
    """Todas las filas del usuario: el ítem #STATS y un ítem por tema."""
    return _progress().query(KeyConditionExpression=Key("userId").eq(user_id))["Items"]


lambda_handler = router.as_handler()
