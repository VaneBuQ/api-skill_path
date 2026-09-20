"""flashcards-service — historias 2 (repasar) y 3 (calificar)."""

import json

import pytest
from moto import mock_aws

from tests.fixtures.services import load, wire

USER = "usr_lucia"
OTRO = "usr_miguel"
TOPIC = "algebra-lineal"


@pytest.fixture
def svc(monkeypatch):
    """flashcards-service con progress-service conectado."""
    from skillpath_common import db

    with mock_aws():
        from tests.fixtures.tables import create_all

        names = create_all()
        for short, full in names.items():
            monkeypatch.setenv(short.upper().replace("-", "_") + "_TABLE", full)
        monkeypatch.setenv("PROGRESS_FUNCTION", "progress")
        db.reset_cache()

        progress = load("progress_service")
        flashcards = load("flashcards_service")

        fake_call = wire(monkeypatch, PROGRESS_FUNCTION=progress)
        monkeypatch.setattr(flashcards, "call", fake_call)

        flashcards.progress = progress
        yield flashcards
        db.reset_cache()


def request(method, route, *, user=USER, path=None, body=None, query=None):
    event = {
        "routeKey": f"{method} {route}",
        "pathParameters": path or {},
        "queryStringParameters": query,
        "requestContext": {"requestId": "req-test"},
    }
    if user:
        event["requestContext"]["authorizer"] = {"lambda": {"userId": user}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def data(response):
    return json.loads(response["body"])


def sembrar(svc, *, cards=12, user=USER, topic=TOPIC):
    """Un tema seguido por el usuario, con `cards` tarjetas."""
    from skillpath_common.db import table

    svc.lambda_handler({
        "internalAction": "createCards",
        "data": {
            "topicId": topic,
            "cards": [
                {"question": f"Pregunta {i}", "answer": f"Respuesta {i}",
                 "hint": f"Pista {i}" if i % 2 == 0 else None}
                for i in range(1, cards + 1)
            ],
        },
    })
    table("USER_TOPICS_TABLE").put_item(Item={
        "userId": user, "topicId": topic, "topicName": "Álgebra lineal",
        "cardCount": cards, "icon": "atom", "isOwn": False,
        "followedAt": "2026-09-01T00:00:00Z",
    })


def repasar(svc, card_id, rating, *, user=USER, topic=TOPIC):
    return svc.lambda_handler(request(
        "POST", "/flashcards/{cardId}/review", user=user,
        path={"cardId": card_id}, body={"topicId": topic, "rating": rating},
    ))


def pendientes(svc, *, user=USER, topic=TOPIC, query=None):
    return data(svc.lambda_handler(request(
        "GET", "/flashcards/{topicId}", user=user, path={"topicId": topic}, query=query,
    )))


# =============================================================================
# Historia 2 — estudiar tarjetas
# =============================================================================

class TestTarjetasPendientes:
    def test_una_tarjeta_nunca_repasada_toca_hoy(self, svc):
        sembrar(svc, cards=12)
        r = pendientes(svc)

        assert r["dueCount"] == 12
        assert r["cardsTotal"] == 12
        assert r["cardsMastered"] == 0

    def test_trae_la_respuesta_junto_a_la_pregunta(self, svc):
        # El prototipo voltea la tarjeta al instante; un segundo viaje al
        # servidor para ver el reverso se sentiría lento.
        sembrar(svc, cards=3)
        primera = pendientes(svc)["items"][0]

        assert primera["question"]
        assert primera["answer"]
        assert primera["state"] == "new"

    def test_incluye_la_pista_del_prototipo(self, svc):
        sembrar(svc, cards=4)
        pistas = [c["hint"] for c in pendientes(svc)["items"]]
        assert any(pistas)

    def test_sin_pendientes_devuelve_lista_vacia_no_un_error(self, svc):
        # Historia 2: «THEN se muestra un mensaje indicando que no hay tarjetas
        # pendientes por hoy». Es un estado normal, no un error.
        sembrar(svc, cards=2)
        for card in pendientes(svc)["items"]:
            repasar(svc, card["cardId"], "easy")

        r = pendientes(svc)
        assert r["dueCount"] == 0
        assert r["items"] == []

    def test_el_encabezado_sabe_cuantas_faltan(self, svc):
        # «ÁLGEBRA LINEAL · 4 DE 12» sale de dueCount.
        sembrar(svc, cards=12)
        assert pendientes(svc)["dueCount"] == 12

        items = pendientes(svc)["items"]
        for card in items[:3]:
            repasar(svc, card["cardId"], "easy")
        assert pendientes(svc)["dueCount"] == 9

    def test_respeta_el_limite_pero_informa_el_total(self, svc):
        sembrar(svc, cards=12)
        r = pendientes(svc, query={"limit": "5"})

        assert len(r["items"]) == 5
        assert r["dueCount"] == 12

    def test_el_xp_disponible_sale_de_las_pendientes(self, svc):
        # «+40 XP disponibles hoy» del prototipo: 8 tarjetas × 5 XP.
        sembrar(svc, cards=8)
        assert pendientes(svc)["xpAvailable"] == 40

    def test_un_tema_que_no_sigue_da_403(self, svc):
        sembrar(svc, cards=3)
        r = svc.lambda_handler(request(
            "GET", "/flashcards/{topicId}", user=OTRO, path={"topicId": TOPIC}
        ))
        assert r["statusCode"] == 403
        assert data(r)["error"]["code"] == "NOT_FOLLOWING_TOPIC"

    def test_las_tarjetas_atrasadas_van_primero(self, svc):
        sembrar(svc, cards=5)
        items = pendientes(svc)["items"]
        # Se repasa una: deja de vencer hoy y baja en la lista.
        repasar(svc, items[0]["cardId"], "easy")
        restantes = [c["cardId"] for c in pendientes(svc)["items"]]
        assert items[0]["cardId"] not in restantes


class TestRepasarErrores:
    def test_una_sesion_limitada_a_las_tarjetas_falladas(self, svc):
        # Observación #11: el botón «Repasar errores» del resultado del quiz.
        sembrar(svc, cards=10)
        for card in pendientes(svc)["items"]:
            repasar(svc, card["cardId"], "easy")
        assert pendientes(svc)["dueCount"] == 0

        r = pendientes(svc, query={"cardIds": "crd_0003,crd_0007"})
        assert [c["cardId"] for c in r["items"]] == ["crd_0003", "crd_0007"]


# =============================================================================
# Historia 3 — calificar el repaso
# =============================================================================

class TestCalificar:
    @pytest.mark.parametrize("rating", ["forgot", "hard", "easy"])
    def test_acepta_las_tres_calificaciones(self, svc, rating):
        sembrar(svc, cards=3)
        r = repasar(svc, "crd_0001", rating)

        assert r["statusCode"] == 200
        assert data(r)["rating"] == rating

    def test_reprograma_la_proxima_fecha(self, svc):
        sembrar(svc, cards=3)
        # Historia 3: «THEN el sistema reprograma la próxima fecha de repaso».
        from skillpath_common.dates import add_days

        r = data(repasar(svc, "crd_0001", "easy"))
        assert r["intervalDays"] == 1
        assert r["nextReviewDate"] == add_days(1)

    def test_olvide_la_devuelve_hoy_mismo(self, svc):
        from skillpath_common.dates import today_str

        sembrar(svc, cards=3)
        r = data(repasar(svc, "crd_0001", "forgot"))
        assert r["intervalDays"] == 0
        assert r["nextReviewDate"] == today_str()
        # Y por eso sigue apareciendo entre las pendientes.
        assert "crd_0001" in [c["cardId"] for c in pendientes(svc)["items"]]

    def test_cuatro_faciles_seguidas_dominan_la_tarjeta(self, svc):
        sembrar(svc, cards=3)
        for _ in range(4):
            r = data(repasar(svc, "crd_0001", "easy"))
        assert r["state"] == "mastered"
        assert r["progress"]["cardsMastered"] == 1

    def test_el_factor_de_facilidad_persiste_entre_repasos(self, svc):
        sembrar(svc, cards=3)
        primero = data(repasar(svc, "crd_0001", "easy"))
        segundo = data(repasar(svc, "crd_0001", "easy"))

        assert primero["easeFactor"] == 2.6
        assert segundo["easeFactor"] == 2.7

    def test_informa_cuantas_quedan(self, svc):
        sembrar(svc, cards=5)
        assert data(repasar(svc, "crd_0001", "easy"))["remainingDue"] == 4

    def test_falta_el_topicid(self, svc):
        # Observación #5: `flashcards` tiene clave compuesta, así que con el
        # cardId solo no se puede leer la tarjeta.
        sembrar(svc, cards=3)
        r = svc.lambda_handler(request(
            "POST", "/flashcards/{cardId}/review",
            path={"cardId": "crd_0001"}, body={"rating": "easy"},
        ))
        assert r["statusCode"] == 400
        assert "topicId" in data(r)["error"]["details"]["fields"]

    def test_calificacion_invalida(self, svc):
        sembrar(svc, cards=3)
        r = repasar(svc, "crd_0001", "perfecto")
        assert r["statusCode"] == 400
        assert data(r)["error"]["code"] == "INVALID_RATING"

    def test_una_tarjeta_inexistente_da_404(self, svc):
        sembrar(svc, cards=3)
        r = repasar(svc, "crd_9999", "easy")
        assert r["statusCode"] == 404
        assert data(r)["error"]["code"] == "CARD_NOT_FOUND"

    def test_no_se_puede_calificar_en_un_tema_ajeno(self, svc):
        sembrar(svc, cards=3)
        r = repasar(svc, "crd_0001", "easy", user=OTRO)
        assert r["statusCode"] == 403

    def test_dos_usuarios_llevan_historiales_independientes(self, svc):
        from skillpath_common.db import table

        sembrar(svc, cards=5)
        table("USER_TOPICS_TABLE").put_item(Item={
            "userId": OTRO, "topicId": TOPIC, "topicName": "Álgebra lineal",
            "cardCount": 5, "isOwn": False, "followedAt": "2026-09-01T00:00:00Z",
        })
        repasar(svc, "crd_0001", "easy", user=USER)

        assert pendientes(svc, user=USER)["dueCount"] == 4
        assert pendientes(svc, user=OTRO)["dueCount"] == 5


class TestExperiencia:
    def test_cada_tarjeta_da_cinco_xp(self, svc):
        sembrar(svc, cards=3)
        assert data(repasar(svc, "crd_0001", "easy"))["xpAwarded"] == 5

    def test_repasar_la_misma_tarjeta_otra_vez_hoy_no_da_mas_xp(self, svc):
        # Si no, repasar 20 veces la misma tarjeta multiplicaría la experiencia.
        sembrar(svc, cards=3)
        repasar(svc, "crd_0001", "forgot")
        assert data(repasar(svc, "crd_0001", "easy"))["xpAwarded"] == 0

    def test_el_xp_se_acumula_en_el_total(self, svc):
        sembrar(svc, cards=5)
        for card in ["crd_0001", "crd_0002", "crd_0003"]:
            r = data(repasar(svc, card, "easy"))
        assert r["progress"]["xpTotal"] == 15


class TestProgresoYRacha:
    def test_el_repaso_actualiza_el_progreso_del_tema(self, svc):
        sembrar(svc, cards=10)
        for _ in range(4):
            r = data(repasar(svc, "crd_0001", "easy"))

        progreso = r["progress"]
        assert progreso["cardsTotal"] == 10
        assert progreso["cardsMastered"] == 1
        assert progreso["cardsPending"] == 9
        assert progreso["percent"] == 10

    def test_el_primer_repaso_arranca_la_racha(self, svc):
        sembrar(svc, cards=3)
        assert data(repasar(svc, "crd_0001", "easy"))["progress"]["streakDays"] == 1

    def test_varios_repasos_el_mismo_dia_son_una_sola_racha(self, svc):
        sembrar(svc, cards=5)
        for card in ["crd_0001", "crd_0002", "crd_0003"]:
            r = data(repasar(svc, card, "easy"))
        assert r["progress"]["streakDays"] == 1

    def test_el_progreso_se_escribe_en_la_tabla_de_progress_service(self, svc):
        from skillpath_common.db import table

        sembrar(svc, cards=4)
        repasar(svc, "crd_0001", "easy")

        fila = table("USER_PROGRESS_TABLE").get_item(
            Key={"userId": USER, "topicId": TOPIC}
        ).get("Item")
        assert fila is not None
        assert fila["topicName"] == "Álgebra lineal"

    def test_si_progress_service_falla_el_repaso_igual_se_guarda(self, svc, monkeypatch):
        # La review ya está escrita antes de la llamada: perderla sería peor
        # que quedarse sin actualizar un porcentaje recalculable.
        sembrar(svc, cards=3)
        monkeypatch.setattr(svc, "call", lambda env, payload: None)

        r = repasar(svc, "crd_0001", "easy")
        assert r["statusCode"] == 200
        assert data(r)["progress"] is None
        assert pendientes(svc)["dueCount"] == 2


class TestAccionesInternas:
    def test_cuenta_los_conceptos_estudiados(self, svc):
        # Umbral del quiz (observación #8): cuenta estudiados, no del mazo.
        sembrar(svc, cards=12)
        for i in range(1, 8):
            repasar(svc, f"crd_{i:04d}", "easy")

        r = svc.lambda_handler({
            "internalAction": "getStudiedCount",
            "data": {"userId": USER, "topicId": TOPIC},
        })
        assert r["studied"] == 7

    def test_borrar_las_reviews_de_un_tema(self, svc):
        sembrar(svc, cards=5)
        repasar(svc, "crd_0001", "easy")
        repasar(svc, "crd_0002", "easy")

        r = svc.lambda_handler({
            "internalAction": "deleteUserTopicReviews",
            "data": {"userId": USER, "topicId": TOPIC},
        })
        assert r["deleted"] == 2
        assert pendientes(svc)["dueCount"] == 5
