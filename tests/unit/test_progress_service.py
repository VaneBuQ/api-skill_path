"""progress-service — historias 4 (progreso por tema), 5 (racha y XP) y 11 (Home)."""

import json

import pytest
from moto import mock_aws

from tests.fixtures.services import load, wire

USER = "usr_lucia"
OTRO = "usr_miguel"


@pytest.fixture
def svc(monkeypatch):
    """progress-service con flashcards-service delante, para generar repasos."""
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

        progress.flashcards = flashcards
        yield progress
        db.reset_cache()


def request(method, route, *, user=USER, path=None):
    event = {
        "routeKey": f"{method} {route}",
        "pathParameters": path or {},
        "requestContext": {"requestId": "req-test"},
    }
    if user:
        event["requestContext"]["authorizer"] = {"lambda": {"userId": user}}
    return event


def data(response):
    return json.loads(response["body"])


def sembrar_tema(svc, topic, nombre, cards, *, user=USER):
    from skillpath_common.db import table

    svc.flashcards.lambda_handler({
        "internalAction": "createCards",
        "data": {"topicId": topic, "cards": [
            {"question": f"P{i}", "answer": f"R{i}"} for i in range(1, cards + 1)
        ]},
    })
    table("USER_TOPICS_TABLE").put_item(Item={
        "userId": user, "topicId": topic, "topicName": nombre,
        "cardCount": cards, "isOwn": False, "followedAt": "2026-09-01T00:00:00Z",
    })


def repasar(svc, topic, card_id, rating="easy", *, user=USER):
    return svc.flashcards.lambda_handler({
        "routeKey": "POST /flashcards/{cardId}/review",
        "pathParameters": {"cardId": card_id},
        "body": json.dumps({"topicId": topic, "rating": rating}),
        "requestContext": {"requestId": "r", "authorizer": {"lambda": {"userId": user}}},
    })


def dominar(svc, topic, card_id, *, user=USER):
    """Cuatro «fácil» seguidas llevan la tarjeta a dominada."""
    for _ in range(4):
        repasar(svc, topic, card_id, "easy", user=user)


# =============================================================================
# Historia 4 — progreso por tema
# =============================================================================

class TestProgresoPorTema:
    def test_muestra_dominados_pendientes_y_porcentaje(self, svc):
        sembrar_tema(svc, "algebra", "Álgebra lineal", 10)
        dominar(svc, "algebra", "crd_0001")
        dominar(svc, "algebra", "crd_0002")

        r = svc.lambda_handler(request("GET", "/progress/{topicId}", path={"topicId": "algebra"}))
        p = data(r)

        assert r["statusCode"] == 200
        assert p["cardsTotal"] == 10
        assert p["cardsMastered"] == 2
        assert p["cardsPending"] == 8
        assert p["percent"] == 20

    def test_incluye_la_fecha_del_ultimo_repaso(self, svc):
        # Historia 4: «AND se muestra la fecha del último repaso realizado».
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        repasar(svc, "algebra", "crd_0001")

        assert data(svc.lambda_handler(
            request("GET", "/progress/{topicId}", path={"topicId": "algebra"})
        ))["lastStudiedAt"]

    def test_un_tema_sin_repasos_todavia_no_tiene_progreso(self, svc):
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        r = svc.lambda_handler(request("GET", "/progress/{topicId}", path={"topicId": "algebra"}))

        assert r["statusCode"] == 404
        assert data(r)["error"]["code"] == "PROGRESS_NOT_FOUND"

    def test_el_progreso_de_otro_usuario_es_inalcanzable(self, svc):
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        repasar(svc, "algebra", "crd_0001", user=USER)

        r = svc.lambda_handler(
            request("GET", "/progress/{topicId}", user=OTRO, path={"topicId": "algebra"})
        )
        assert r["statusCode"] == 404

    def test_el_item_de_estadisticas_no_se_puede_pedir_como_tema(self, svc):
        # "#STATS" es una fila interna, no un tema.
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        repasar(svc, "algebra", "crd_0001")

        r = svc.lambda_handler(request("GET", "/progress/{topicId}", path={"topicId": "#STATS"}))
        assert r["statusCode"] == 404


# =============================================================================
# Observación #2 — GET /progress alimenta el Home y «Mi progreso»
# =============================================================================

class TestResumenGlobal:
    def test_una_sola_llamada_trae_resumen_y_todos_los_temas(self, svc):
        sembrar_tema(svc, "algebra", "Álgebra lineal", 10)
        sembrar_tema(svc, "estadistica", "Estadística", 10)
        dominar(svc, "algebra", "crd_0001")
        repasar(svc, "estadistica", "crd_0001")

        r = data(svc.lambda_handler(request("GET", "/progress")))

        assert len(r["items"]) == 2
        assert r["summary"]["cardsTotal"] == 20
        assert r["summary"]["cardsMastered"] == 1

    def test_los_temas_salen_ordenados_por_nombre(self, svc):
        sembrar_tema(svc, "python", "Programación en Python", 5)
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        sembrar_tema(svc, "estadistica", "Estadística", 5)
        for topic in ["python", "algebra", "estadistica"]:
            repasar(svc, topic, "crd_0001")

        r = data(svc.lambda_handler(request("GET", "/progress")))
        nombres = [t["topicName"] for t in r["items"]]
        assert nombres == sorted(nombres, key=str.lower)

    def test_el_dominio_global_pondera_todos_los_temas(self, svc):
        # «58% dominio global» del prototipo.
        sembrar_tema(svc, "algebra", "Álgebra lineal", 4)
        sembrar_tema(svc, "estadistica", "Estadística", 4)
        for card in ["crd_0001", "crd_0002"]:
            dominar(svc, "algebra", card)
        dominar(svc, "estadistica", "crd_0001")

        resumen = data(svc.lambda_handler(request("GET", "/progress")))["summary"]
        assert resumen["cardsMastered"] == 3
        assert resumen["cardsTotal"] == 8
        assert resumen["masteryPercent"] == 38

    def test_las_estadisticas_no_aparecen_como_un_tema_mas(self, svc):
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        repasar(svc, "algebra", "crd_0001")

        r = data(svc.lambda_handler(request("GET", "/progress")))
        assert "#STATS" not in [t["topicId"] for t in r["items"]]

    def test_un_usuario_nuevo_no_falla(self, svc):
        # El Home se pinta antes de que el usuario haya estudiado nada.
        r = svc.lambda_handler(request("GET", "/progress"))
        resumen = data(r)["summary"]

        assert r["statusCode"] == 200
        assert data(r)["items"] == []
        assert resumen["streakDays"] == 0
        assert resumen["xpTotal"] == 0
        assert resumen["masteryPercent"] == 0


# =============================================================================
# Historia 5 — racha y XP
# =============================================================================

class TestRachaYExperiencia:
    def test_el_home_muestra_racha_y_xp(self, svc):
        # Historia 11: «THEN ve un resumen de su racha/XP».
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        for card in ["crd_0001", "crd_0002", "crd_0003"]:
            repasar(svc, "algebra", card)

        resumen = data(svc.lambda_handler(request("GET", "/progress")))["summary"]
        assert resumen["streakDays"] == 1
        assert resumen["xpTotal"] == 15
        assert resumen["studiedToday"] is True

    def test_la_racha_se_reinicia_a_cero_si_no_estudio_ayer(self, svc):
        # Historia 5: «GIVEN el usuario no repasó el día anterior THEN la racha
        # se reinicia a 0». Se calcula al leer, sin proceso nocturno.
        from skillpath_common.db import table

        table("USER_PROGRESS_TABLE").put_item(Item={
            "userId": USER, "topicId": "#STATS",
            "streakDays": 12, "longestStreakDays": 19,
            "lastStudyDate": "2026-01-05", "xpTotal": 2480,
        })

        resumen = data(svc.lambda_handler(request("GET", "/progress")))["summary"]
        assert resumen["streakDays"] == 0
        # Pero ni el XP ni el récord se pierden.
        assert resumen["xpTotal"] == 2480
        assert resumen["longestStreakDays"] == 19
        assert resumen["studiedToday"] is False

    def test_el_quiz_tambien_suma_xp_y_cuenta_para_la_racha(self, svc):
        r = svc.lambda_handler({
            "internalAction": "quizCompleted",
            "data": {"userId": USER, "topicId": "algebra", "xp": 120},
        })
        assert r["xpTotal"] == 120
        assert r["streakDays"] == 1

    def test_el_xp_del_quiz_se_suma_al_de_los_repasos(self, svc):
        sembrar_tema(svc, "algebra", "Álgebra lineal", 5)
        repasar(svc, "algebra", "crd_0001")
        svc.lambda_handler({
            "internalAction": "quizCompleted",
            "data": {"userId": USER, "topicId": "algebra", "xp": 120},
        })

        assert data(svc.lambda_handler(request("GET", "/progress")))["summary"]["xpTotal"] == 125


class TestTotalesAbsolutos:
    def test_reprocesar_el_mismo_evento_no_desvia_los_contadores(self, svc):
        # Los totales viajan como valores absolutos, no como incrementos: si una
        # invocación se pierde o se repite, los números siguen siendo correctos.
        evento = {
            "internalAction": "cardReviewed",
            "data": {"userId": USER, "topicId": "algebra", "topicName": "Álgebra",
                     "cardsTotal": 10, "cardsMastered": 3, "xp": 0},
        }
        svc.lambda_handler(evento)
        svc.lambda_handler(evento)

        p = data(svc.lambda_handler(
            request("GET", "/progress/{topicId}", path={"topicId": "algebra"})
        ))
        assert p["cardsMastered"] == 3
        assert p["percent"] == 30


class TestEliminarTema:
    def test_borrar_un_mazo_quita_su_progreso(self, svc):
        # Historia 8: sin esto, el mazo eliminado seguiría en «Mi progreso».
        sembrar_tema(svc, "deck_propio", "Mis apuntes", 5)
        repasar(svc, "deck_propio", "crd_0001")
        assert len(data(svc.lambda_handler(request("GET", "/progress")))["items"]) == 1

        svc.lambda_handler({
            "internalAction": "removeTopic",
            "data": {"userId": USER, "topicId": "deck_propio"},
        })
        assert data(svc.lambda_handler(request("GET", "/progress")))["items"] == []
