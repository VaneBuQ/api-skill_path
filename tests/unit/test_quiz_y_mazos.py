"""Examen de dominio (historia 6) y mazos propios (historia 8)."""

import json
import os

import pytest
from moto import mock_aws

from tests.harness import Cluster, create_tables
from tests.unit.test_flujo_completo import registrar, sembrar_tema


@pytest.fixture
def app(monkeypatch):
    with mock_aws():
        create_tables()
        yield Cluster(monkeypatch)


def estudiar(app, token, topic_id, cuantas):
    for i in range(1, cuantas + 1):
        status, _ = app.call("flashcards", "review_card", token=token,
                             path={"cardId": f"crd_{i:04d}"},
                             body={"topicId": topic_id, "rating": "easy"})
        assert status == 200


def preparar(app, cards=15, estudiadas=12):
    token, _ = registrar(app)
    sembrar_tema(app, cards=cards)
    app.call("topics", "follow_topic", token=token, path={"topicId": "estructuras-de-datos"})
    estudiar(app, token, "estructuras-de-datos", estudiadas)
    return token


def respuestas_correctas(app, user_id, quiz_id):
    import boto3
    attempt = boto3.resource("dynamodb", region_name="us-east-1").Table(
        os.environ["ATTEMPTS_TABLE"]
    ).get_item(Key={"userId": user_id, "quizId": quiz_id})["Item"]
    return [{"questionId": q["questionId"], "selected": q["correctKey"]}
            for q in attempt["questions"]]


class TestExamen:
    def test_genera_diez_preguntas_con_cuatro_opciones(self, app):
        token = preparar(app)
        status, quiz = app.call("quiz", "start_quiz", token=token,
                                path={"topicId": "estructuras-de-datos"})
        assert status == 201
        assert quiz["questionCount"] == 10
        assert quiz["passCorrect"] == 7
        for pregunta in quiz["questions"]:
            assert [o["key"] for o in pregunta["options"]] == ["A", "B", "C", "D"]

    def test_alterna_las_dos_direcciones_del_prototipo(self, app):
        token = preparar(app)
        _, quiz = app.call("quiz", "start_quiz", token=token,
                           path={"topicId": "estructuras-de-datos"})
        enunciados = [q["prompt"] for q in quiz["questions"]]
        assert any(e.startswith("Dado el concepto") for e in enunciados)
        assert any(e.startswith("Dada la definición") for e in enunciados)

    def test_la_respuesta_correcta_no_viaja_al_cliente(self, app):
        token = preparar(app)
        _, quiz = app.call("quiz", "start_quiz", token=token,
                           path={"topicId": "estructuras-de-datos"})
        assert "correctKey" not in json.dumps(quiz)

    def test_con_menos_de_diez_estudiados_se_bloquea(self, app):
        token = preparar(app, cards=52, estudiadas=6)
        status, data = app.call("quiz", "start_quiz", token=token,
                                path={"topicId": "estructuras-de-datos"})
        assert status == 409
        assert data["error"]["code"] == "NOT_ENOUGH_CONCEPTS"
        assert data["error"]["details"] == {
            "studied": 6, "required": 10, "topicName": "Estructuras de Datos",
        }
        # El texto que pinta el prototipo: «Llevas 6 de 10».
        assert "Llevas 6 de 10" in data["error"]["message"]

    def test_siete_de_diez_aprueba_y_domina_el_tema(self, app):
        token, user_id = registrar(app)
        sembrar_tema(app, cards=15)
        app.call("topics", "follow_topic", token=token, path={"topicId": "estructuras-de-datos"})
        estudiar(app, token, "estructuras-de-datos", 12)

        _, quiz = app.call("quiz", "start_quiz", token=token,
                           path={"topicId": "estructuras-de-datos"})
        answers = respuestas_correctas(app, user_id, quiz["quizId"])
        # Se fallan tres a propósito: quedan 7 aciertos, el mínimo para aprobar.
        for answer in answers[:3]:
            answer["selected"] = "A" if answer["selected"] != "A" else "B"

        status, resultado = app.call("quiz", "submit_quiz", token=token,
                                     path={"quizId": quiz["quizId"]},
                                     body={"answers": answers, "durationSeconds": 200})
        assert status == 200
        assert resultado["correctCount"] == 7
        assert resultado["score"] == 70
        assert resultado["passed"] is True
        assert len(resultado["conceptsToReview"]) == 3

        # El tema queda marcado como dominado en progreso.
        _, progreso = app.call("progress", "topic_progress", token=token,
                               path={"topicId": "estructuras-de-datos"})
        assert progreso["mastered"] is True
        assert progreso["lastExamScore"] == 70

    def test_seis_de_diez_no_aprueba(self, app):
        token, user_id = registrar(app)
        sembrar_tema(app, cards=15)
        app.call("topics", "follow_topic", token=token, path={"topicId": "estructuras-de-datos"})
        estudiar(app, token, "estructuras-de-datos", 12)

        _, quiz = app.call("quiz", "start_quiz", token=token,
                           path={"topicId": "estructuras-de-datos"})
        answers = respuestas_correctas(app, user_id, quiz["quizId"])
        for answer in answers[:4]:
            answer["selected"] = "A" if answer["selected"] != "A" else "B"

        _, resultado = app.call("quiz", "submit_quiz", token=token,
                                path={"quizId": quiz["quizId"]}, body={"answers": answers})
        assert resultado["correctCount"] == 6
        assert resultado["passed"] is False

        _, progreso = app.call("progress", "topic_progress", token=token,
                               path={"topicId": "estructuras-de-datos"})
        assert progreso["mastered"] is False

    def test_no_se_puede_enviar_dos_veces(self, app):
        token, user_id = registrar(app)
        sembrar_tema(app, cards=15)
        app.call("topics", "follow_topic", token=token, path={"topicId": "estructuras-de-datos"})
        estudiar(app, token, "estructuras-de-datos", 12)

        _, quiz = app.call("quiz", "start_quiz", token=token,
                           path={"topicId": "estructuras-de-datos"})
        answers = respuestas_correctas(app, user_id, quiz["quizId"])
        app.call("quiz", "submit_quiz", token=token,
                 path={"quizId": quiz["quizId"]}, body={"answers": answers})

        status, data = app.call("quiz", "submit_quiz", token=token,
                                path={"quizId": quiz["quizId"]}, body={"answers": answers})
        assert status == 409
        assert data["error"]["code"] == "QUIZ_ALREADY_SUBMITTED"

    def test_el_quiz_de_otro_usuario_no_existe(self, app):
        token, user_id = registrar(app)
        sembrar_tema(app, cards=15)
        app.call("topics", "follow_topic", token=token, path={"topicId": "estructuras-de-datos"})
        estudiar(app, token, "estructuras-de-datos", 12)
        _, quiz = app.call("quiz", "start_quiz", token=token,
                           path={"topicId": "estructuras-de-datos"})

        otro, _ = registrar(app, email="miguel@universidad.edu")
        status, _ = app.call("quiz", "get_quiz", token=otro, path={"quizId": quiz["quizId"]})
        assert status == 404


class TestMazosPropios:
    MAZO = {
        "name": "Resumen Parcial 2",
        "description": "Lo que entró en el parcial",
        "cards": [
            {"question": "¿Qué es una integral definida?",
             "answer": "El área acumulada bajo una curva entre dos límites.",
             "hint": "Piensa en el área."},
            {"question": "¿Qué es una derivada?",
             "answer": "La tasa de cambio instantánea de una función."},
        ],
    }

    def test_crear_mazo_y_aparece_en_mis_temas(self, app):
        token, _ = registrar(app)
        status, mazo = app.call("topics", "create_deck", token=token, body=self.MAZO)
        assert status == 201
        assert mazo["topicId"].startswith("deck_")
        assert mazo["cardCount"] == 2
        assert mazo["isOwn"] is True

        # Criterio: «queda disponible para repasar junto a los demás temas».
        _, temas = app.call("topics", "my_topics", token=token)
        assert [t["topicId"] for t in temas["items"]] == [mazo["topicId"]]

    def test_el_mazo_propio_no_sale_en_el_catalogo(self, app):
        token, _ = registrar(app)
        sembrar_tema(app)
        app.call("topics", "create_deck", token=token, body=self.MAZO)

        _, catalogo = app.call("topics", "list_topics")
        assert [t["topicId"] for t in catalogo["items"]] == ["estructuras-de-datos"]

    def test_sin_tarjetas_no_se_crea(self, app):
        token, _ = registrar(app)
        status, data = app.call("topics", "create_deck", token=token,
                                body={"name": "Vacío", "cards": []})
        assert status == 400
        assert "cards" in data["error"]["details"]["fields"]

    def test_se_puede_repasar_como_cualquier_tema(self, app):
        token, _ = registrar(app)
        _, mazo = app.call("topics", "create_deck", token=token, body=self.MAZO)

        status, sesion = app.call("flashcards", "due_cards", token=token,
                                  path={"topicId": mazo["topicId"]})
        assert status == 200
        assert sesion["dueCount"] == 2

    def test_agregar_tarjeta_actualiza_el_contador(self, app):
        token, _ = registrar(app)
        _, mazo = app.call("topics", "create_deck", token=token, body=self.MAZO)

        status, data = app.call("topics", "add_cards", token=token,
                                path={"topicId": mazo["topicId"]},
                                body={"question": "¿Qué es un límite?",
                                      "answer": "El valor al que tiende una función."})
        assert status == 201
        assert data["cardCount"] == 3

        _, detalle = app.call("topics", "deck_detail", token=token,
                              path={"topicId": mazo["topicId"]})
        assert len(detalle["cards"]) == 3

    def test_el_mazo_de_otro_no_existe(self, app):
        token, _ = registrar(app)
        _, mazo = app.call("topics", "create_deck", token=token, body=self.MAZO)

        otro, _ = registrar(app, email="miguel@universidad.edu")
        status, _ = app.call("topics", "deck_detail", token=otro,
                             path={"topicId": mazo["topicId"]})
        assert status == 404

    def test_eliminar_borra_tarjetas_y_progreso(self, app):
        token, _ = registrar(app)
        _, mazo = app.call("topics", "create_deck", token=token, body=self.MAZO)
        app.call("flashcards", "review_card", token=token, path={"cardId": "crd_0001"},
                 body={"topicId": mazo["topicId"], "rating": "easy"})

        _, progreso = app.call("progress", "all_progress", token=token)
        assert len(progreso["items"]) == 1

        status, _ = app.call("topics", "delete_deck", token=token,
                             path={"topicId": mazo["topicId"]})
        assert status == 204

        _, mazos = app.call("topics", "my_decks", token=token)
        assert mazos["items"] == []
        # Sin la limpieza, el mazo borrado seguiría en «Mi progreso».
        _, progreso = app.call("progress", "all_progress", token=token)
        assert progreso["items"] == []

    def test_un_mazo_propio_no_se_deja_de_seguir(self, app):
        token, _ = registrar(app)
        _, mazo = app.call("topics", "create_deck", token=token, body=self.MAZO)
        status, data = app.call("topics", "unfollow_topic", token=token,
                                path={"topicId": mazo["topicId"]})
        assert status == 409
        assert data["error"]["code"] == "OWN_DECK_CANNOT_UNFOLLOW"
