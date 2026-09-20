"""quiz-service — historia 6 (quiz de autoevaluación)."""

import json

import pytest
from moto import mock_aws

from tests.fixtures.services import load, wire

USER = "usr_lucia"
OTRO = "usr_miguel"
TOPIC = "estructuras-de-datos"


@pytest.fixture
def svc(monkeypatch):
    """quiz-service con flashcards-service y progress-service conectados."""
    from skillpath_common import db

    with mock_aws():
        from tests.fixtures.tables import create_all

        names = create_all()
        for short, full in names.items():
            monkeypatch.setenv(short.upper().replace("-", "_") + "_TABLE", full)
        monkeypatch.setenv("FLASHCARDS_FUNCTION", "flashcards")
        monkeypatch.setenv("PROGRESS_FUNCTION", "progress")
        db.reset_cache()

        progress = load("progress_service")
        flashcards = load("flashcards_service")
        quiz = load("quiz_service")

        fake_call = wire(
            monkeypatch, FLASHCARDS_FUNCTION=flashcards, PROGRESS_FUNCTION=progress
        )
        monkeypatch.setattr(quiz, "call", fake_call)
        monkeypatch.setattr(flashcards, "call", fake_call)

        # Semilla fija: los quizzes salen reproducibles sin tocar el generador
        # global del proceso.
        quiz._rng.seed(20260921)

        quiz.flashcards = flashcards
        quiz.progress = progress
        yield quiz
        db.reset_cache()


def request(method, route, *, user=USER, path=None, body=None):
    event = {
        "routeKey": f"{method} {route}",
        "pathParameters": path or {},
        "requestContext": {"requestId": "req-test"},
    }
    if user:
        event["requestContext"]["authorizer"] = {"lambda": {"userId": user}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def data(response):
    return json.loads(response["body"])


def sembrar(svc, *, cards=15, estudiadas=12, user=USER, topic=TOPIC):
    """Un tema seguido, con `cards` tarjetas y `estudiadas` ya repasadas."""
    from skillpath_common.db import table

    svc.flashcards.lambda_handler({
        "internalAction": "createCards",
        "data": {"topicId": topic, "cards": [
            {"question": f"¿Pregunta número {i}?", "answer": f"Respuesta número {i}."}
            for i in range(1, cards + 1)
        ]},
    })
    table("USER_TOPICS_TABLE").put_item(Item={
        "userId": user, "topicId": topic, "topicName": "Estructuras de Datos",
        "cardCount": cards, "isOwn": False, "followedAt": "2026-09-01T00:00:00Z",
    })
    for i in range(1, estudiadas + 1):
        svc.flashcards.lambda_handler({
            "routeKey": "POST /flashcards/{cardId}/review",
            "pathParameters": {"cardId": f"crd_{i:04d}"},
            "body": json.dumps({"topicId": topic, "rating": "easy"}),
            "requestContext": {"requestId": "r", "authorizer": {"lambda": {"userId": user}}},
        })


def iniciar(svc, *, user=USER, topic=TOPIC):
    return svc.lambda_handler(
        request("POST", "/quiz/{topicId}/start", user=user, path={"topicId": topic})
    )


def enviar(svc, quiz_id, answers, *, user=USER, duration=214):
    return svc.lambda_handler(request(
        "POST", "/quiz/{quizId}/submit", user=user, path={"quizId": quiz_id},
        body={"answers": answers, "durationSeconds": duration},
    ))


def responder_todo_bien(svc, quiz_id, *, user=USER):
    from skillpath_common.db import table

    attempt = table("QUIZ_ATTEMPTS_TABLE").get_item(
        Key={"userId": user, "quizId": quiz_id}
    )["Item"]
    return [
        {"questionId": q["questionId"], "selected": q["correctKey"]}
        for q in attempt["questions"]
    ]


# =============================================================================
# Generación del quiz
# =============================================================================

class TestIniciarQuiz:
    def test_genera_diez_preguntas_de_opcion_multiple(self, svc):
        sembrar(svc)
        r = iniciar(svc)
        q = data(r)

        assert r["statusCode"] == 201
        assert q["questionCount"] == 10
        assert len(q["questions"]) == 10
        assert q["xpReward"] == 120

    def test_cada_pregunta_tiene_cuatro_opciones(self, svc):
        sembrar(svc)
        for pregunta in data(iniciar(svc))["questions"]:
            assert [o["key"] for o in pregunta["options"]] == ["A", "B", "C", "D"]

    def test_las_opciones_de_una_pregunta_no_se_repiten(self, svc):
        # Dos opciones idénticas dejarían la pregunta sin solución única.
        sembrar(svc)
        for pregunta in data(iniciar(svc))["questions"]:
            textos = [o["text"] for o in pregunta["options"]]
            assert len(set(textos)) == 4

    def test_la_respuesta_correcta_nunca_viaja_al_cliente(self, svc):
        sembrar(svc)
        r = iniciar(svc)

        assert "correctKey" not in r["body"]
        for pregunta in data(r)["questions"]:
            assert "correctKey" not in pregunta
            assert "cardId" not in pregunta

    def test_la_respuesta_correcta_esta_entre_las_opciones(self, svc):
        from skillpath_common.db import table

        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        attempt = table("QUIZ_ATTEMPTS_TABLE").get_item(
            Key={"userId": USER, "quizId": quiz_id}
        )["Item"]

        for pregunta in attempt["questions"]:
            correcta = next(
                o for o in pregunta["options"] if o["key"] == pregunta["correctKey"]
            )
            assert correcta["text"].startswith("Respuesta número")

    def test_las_preguntas_salen_de_las_tarjetas_estudiadas(self, svc):
        from skillpath_common.db import table

        # Solo se estudiaron las 12 primeras de 15.
        sembrar(svc, cards=15, estudiadas=12)
        quiz_id = data(iniciar(svc))["quizId"]
        attempt = table("QUIZ_ATTEMPTS_TABLE").get_item(
            Key={"userId": USER, "quizId": quiz_id}
        )["Item"]

        usados = [q["cardId"] for q in attempt["questions"]]
        estudiadas = {f"crd_{i:04d}" for i in range(1, 13)}
        assert set(usados) <= estudiadas

    def test_informa_en_cuantos_conceptos_se_basa(self, svc):
        # «10 preguntas basadas en tus 24 conceptos estudiados» (prototipo p.12).
        sembrar(svc, cards=15, estudiadas=12)
        assert data(iniciar(svc))["basedOnConcepts"] == 12

    def test_el_limite_de_tiempo_es_de_seis_minutos(self, svc):
        sembrar(svc)
        assert data(iniciar(svc))["timeLimitSeconds"] == 360

    def test_dos_quizzes_del_mismo_tema_no_son_identicos(self, svc):
        sembrar(svc, cards=20, estudiadas=20)
        primero = [q["prompt"] for q in data(iniciar(svc))["questions"]]
        segundo = [q["prompt"] for q in data(iniciar(svc))["questions"]]
        assert primero != segundo


class TestUmbralDeConceptos:
    def test_con_menos_de_diez_estudiados_se_bloquea(self, svc):
        # Prototipo p.15: «Necesitas estudiar al menos 10 conceptos.
        # Llevas 7 en Estructuras de Datos».
        sembrar(svc, cards=52, estudiadas=7)
        r = iniciar(svc)
        error = data(r)["error"]

        assert r["statusCode"] == 409
        assert error["code"] == "NOT_ENOUGH_CONCEPTS"
        assert error["details"] == {
            "studied": 7, "required": 10, "topicName": "Estructuras de Datos",
        }

    def test_el_mensaje_dice_cuantos_lleva_y_en_que_tema(self, svc):
        sembrar(svc, cards=52, estudiadas=7)
        mensaje = data(iniciar(svc))["error"]["message"]
        assert "7" in mensaje
        assert "Estructuras de Datos" in mensaje

    def test_un_mazo_grande_sin_estudiar_tambien_se_bloquea(self, svc):
        # Observación #8: con la lectura del informe («10 conceptos del mazo»),
        # un tema de 52 tarjetas nunca se bloquearía y esa pantalla sería
        # inalcanzable.
        sembrar(svc, cards=52, estudiadas=0)
        assert iniciar(svc)["statusCode"] == 409

    def test_con_exactamente_diez_estudiados_ya_se_puede(self, svc):
        sembrar(svc, cards=20, estudiadas=10)
        assert iniciar(svc)["statusCode"] == 201

    def test_un_tema_que_no_sigue(self, svc):
        sembrar(svc)
        r = iniciar(svc, user=OTRO)
        assert r["statusCode"] == 403
        assert data(r)["error"]["code"] == "NOT_FOLLOWING_TOPIC"


# =============================================================================
# Calificación
# =============================================================================

class TestEnviarQuiz:
    def test_todas_correctas_dan_cien(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = data(enviar(svc, quiz_id, responder_todo_bien(svc, quiz_id)))

        assert r["score"] == 100
        assert r["correctCount"] == 10
        assert r["conceptsToReview"] == []

    def test_ocho_de_diez(self, svc):
        # El resultado que pinta el prototipo (p.14).
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        answers = responder_todo_bien(svc, quiz_id)
        for answer in answers[:2]:
            answer["selected"] = "A" if answer["selected"] != "A" else "B"

        r = data(enviar(svc, quiz_id, answers))
        assert r["correctCount"] == 8
        assert r["score"] == 80
        assert r["xpAwarded"] == 120

    def test_devuelve_los_conceptos_fallados_con_su_tarjeta(self, svc):
        # Alimenta «Conceptos para repasar» y el botón «Repasar errores».
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        answers = responder_todo_bien(svc, quiz_id)
        answers[0]["selected"] = "A" if answers[0]["selected"] != "A" else "B"

        fallados = data(enviar(svc, quiz_id, answers))["conceptsToReview"]
        assert len(fallados) == 1
        assert fallados[0]["cardId"].startswith("crd_")
        assert fallados[0]["concept"].startswith("¿Pregunta")

    def test_las_preguntas_sin_responder_cuentan_como_incorrectas(self, svc):
        # Decisión sobre el límite de tiempo: el quiz se autoenvía en vez de
        # invalidarse, y lo que falte se cuenta mal.
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = data(enviar(svc, quiz_id, responder_todo_bien(svc, quiz_id)[:6]))

        assert r["correctCount"] == 6
        assert r["score"] == 60
        assert len(r["conceptsToReview"]) == 4

    def test_enviar_sin_responder_nada(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = data(enviar(svc, quiz_id, []))
        assert r["score"] == 0
        assert len(r["conceptsToReview"]) == 10

    def test_el_resultado_revela_la_respuesta_correcta(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = data(enviar(svc, quiz_id, responder_todo_bien(svc, quiz_id)))

        for resultado in r["results"]:
            assert resultado["correctKey"] in ["A", "B", "C", "D"]
            assert resultado["correct"] is True

    def test_no_se_puede_enviar_dos_veces(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        answers = responder_todo_bien(svc, quiz_id)
        enviar(svc, quiz_id, answers)

        r = enviar(svc, quiz_id, answers)
        assert r["statusCode"] == 409
        assert data(r)["error"]["code"] == "QUIZ_ALREADY_SUBMITTED"

    def test_un_quiz_inexistente(self, svc):
        r = enviar(svc, "qz_noexiste", [])
        assert r["statusCode"] == 404
        assert data(r)["error"]["code"] == "QUIZ_NOT_FOUND"

    def test_el_quiz_de_otro_usuario_es_inalcanzable(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        # La clave incluye el userId, así que para otro sencillamente no existe.
        assert enviar(svc, quiz_id, [], user=OTRO)["statusCode"] == 404

    def test_una_pregunta_que_no_es_del_quiz(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = enviar(svc, quiz_id, [{"questionId": "q99", "selected": "A"}])

        assert r["statusCode"] == 400
        assert data(r)["error"]["code"] == "UNKNOWN_QUESTION"

    def test_answers_debe_ser_una_lista(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = svc.lambda_handler(request(
            "POST", "/quiz/{quizId}/submit", path={"quizId": quiz_id},
            body={"answers": "todas"},
        ))
        assert r["statusCode"] == 400


class TestExperienciaDelQuiz:
    def test_completar_el_quiz_suma_ciento_veinte_xp(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        enviar(svc, quiz_id, responder_todo_bien(svc, quiz_id))

        resumen = data(svc.progress.lambda_handler({
            "routeKey": "GET /progress",
            "pathParameters": {},
            "requestContext": {"requestId": "r", "authorizer": {"lambda": {"userId": USER}}},
        }))["summary"]
        # 12 repasos × 5 XP + 120 del quiz.
        assert resumen["xpTotal"] == 60 + 120

    def test_el_xp_es_fijo_aunque_se_falle(self, svc):
        # El prototipo anuncia «+120 XP al completar», no proporcional al acierto.
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        assert data(enviar(svc, quiz_id, []))["xpAwarded"] == 120


class TestConsultarQuiz:
    def test_un_quiz_en_curso_no_revela_las_respuestas(self, svc):
        # Permite recargar la página sin perder el intento.
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = svc.lambda_handler(request("GET", "/quiz/{quizId}", path={"quizId": quiz_id}))

        assert data(r)["status"] == "in_progress"
        assert len(data(r)["questions"]) == 10
        assert "correctKey" not in r["body"]

    def test_un_quiz_enviado_devuelve_el_resultado_completo(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        enviar(svc, quiz_id, responder_todo_bien(svc, quiz_id))

        r = data(svc.lambda_handler(
            request("GET", "/quiz/{quizId}", path={"quizId": quiz_id})
        ))
        assert r["status"] == "submitted"
        assert r["score"] == 100
        assert r["xpAwarded"] == 120
        assert len(r["results"]) == 10

    def test_el_intento_de_otro_usuario(self, svc):
        sembrar(svc)
        quiz_id = data(iniciar(svc))["quizId"]
        r = svc.lambda_handler(
            request("GET", "/quiz/{quizId}", user=OTRO, path={"quizId": quiz_id})
        )
        assert r["statusCode"] == 404
