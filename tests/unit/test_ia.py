"""Comprobación de la respuesta escrita con IA.

La llamada al modelo se simula: las pruebas verifican la validación, los
límites de palabras, la protección de la respuesta correcta y qué pasa cuando
el modelo devuelve algo inesperado. Llamar al modelo de verdad costaría dinero
y daría resultados distintos en cada ejecución.
"""

import json

import pytest
from moto import mock_aws

from tests.harness import Cluster, create_tables
from tests.unit.test_flujo_completo import registrar, sembrar_tema

TOPIC = "estructuras-de-datos"


@pytest.fixture
def app(monkeypatch):
    with mock_aws():
        create_tables()
        cluster = Cluster(monkeypatch)
        cluster.monkeypatch = monkeypatch
        yield cluster


@pytest.fixture
def modelo(app):
    """Sustituye la llamada HTTP al modelo por una respuesta fija."""
    ia = app.services["ia"]
    estado = {"respuesta": json.dumps({
        "verdict": "correcta", "score": 95,
        "feedback": "Bien, mencionaste la función hash y el par llave-valor.",
    })}

    def fake(question, correct_answer, user_answer):
        estado["ultima_llamada"] = {
            "question": question, "correct": correct_answer, "user": user_answer,
        }
        return estado["respuesta"]

    app.monkeypatch.setattr(ia, "_call_model", fake)
    return estado


def preparar(app):
    token, _ = registrar(app)
    sembrar_tema(app, cards=3)
    app.call("topics", "follow_topic", token=token, path={"topicId": TOPIC})
    return token


class TestComprobacion:
    def test_devuelve_veredicto_y_respuesta_correcta(self, app, modelo):
        token = preparar(app)
        status, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001",
            "answer": "Es una estructura que asocia claves con valores.",
        })

        assert status == 200
        assert data["verdict"] == "correcta"
        assert data["score"] == 95
        assert data["suggestedRating"] == "easy"
        assert data["correctAnswer"] == "Definición número 1."

    def test_la_respuesta_correcta_se_toma_del_servicio_de_tarjetas(self, app, modelo):
        # Si viniera del navegador, cualquiera podría mandar la suya.
        token = preparar(app)
        app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0002",
            "answer": "Mi intento.",
            "correctAnswer": "Una respuesta falsa que envía el cliente",
        })
        assert modelo["ultima_llamada"]["correct"] == "Definición número 2."

    @pytest.mark.parametrize("veredicto,rating", [
        ("correcta", "easy"), ("parcial", "hard"), ("incorrecta", "forgot"),
    ])
    def test_cada_veredicto_sugiere_una_calificacion(self, app, modelo, veredicto, rating):
        token = preparar(app)
        modelo["respuesta"] = json.dumps({
            "verdict": veredicto, "score": 50, "feedback": "Comentario.",
        })
        _, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "Algo.",
        })
        assert data["suggestedRating"] == rating

    def test_queda_registrado_en_el_historial(self, app, modelo):
        token = preparar(app)
        app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "Mi respuesta.",
        })
        status, data = app.call("ia", "history", token=token, path={"topicId": TOPIC})
        assert status == 200
        assert len(data["items"]) == 1
        assert data["items"][0]["answer"] == "Mi respuesta."


class TestLimitesDePalabras:
    def test_rechaza_una_respuesta_demasiado_larga(self, app, modelo):
        token = preparar(app)
        status, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001",
            "answer": " ".join(["palabra"] * 61),
        })
        assert status == 400
        assert data["error"]["code"] == "ANSWER_TOO_LONG"
        assert data["error"]["details"] == {"words": 61, "maxWords": 60}

    def test_acepta_justo_el_limite(self, app, modelo):
        token = preparar(app)
        status, _ = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001",
            "answer": " ".join(["palabra"] * 60),
        })
        assert status == 200

    def test_recorta_una_explicacion_demasiado_larga(self, app, modelo):
        # El límite se pide en el prompt, pero se impone aquí por si acaso.
        token = preparar(app)
        modelo["respuesta"] = json.dumps({
            "verdict": "parcial", "score": 50,
            "feedback": " ".join(["explicacion"] * 100),
        })
        _, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "Algo.",
        })
        assert len(data["feedback"].split()) <= 41  # 40 palabras más el puntito
        assert data["feedback"].endswith("…")

    def test_respuesta_vacia(self, app, modelo):
        token = preparar(app)
        status, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "   ",
        })
        assert status == 400
        assert "answer" in data["error"]["details"]["fields"]


class TestRespuestasInesperadas:
    def test_json_dentro_de_un_bloque_de_codigo(self, app, modelo):
        token = preparar(app)
        modelo["respuesta"] = (
            '```json\n{"verdict": "correcta", "score": 90, "feedback": "Bien."}\n```'
        )
        status, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "Algo.",
        })
        assert status == 200
        assert data["verdict"] == "correcta"

    def test_si_no_devuelve_json_la_pantalla_no_se_rompe(self, app, modelo):
        token = preparar(app)
        modelo["respuesta"] = "Creo que tu respuesta está bastante bien."
        status, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "Algo.",
        })
        assert status == 503
        assert data["error"]["code"] == "AI_UNAVAILABLE"

    def test_un_veredicto_desconocido_cae_en_parcial(self, app, modelo):
        token = preparar(app)
        modelo["respuesta"] = json.dumps({
            "verdict": "excelente", "score": 88, "feedback": "Muy bien.",
        })
        _, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "Algo.",
        })
        assert data["verdict"] == "parcial"

    def test_una_tarjeta_inexistente(self, app, modelo):
        token = preparar(app)
        status, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_9999", "answer": "Algo.",
        })
        assert status == 404
        assert data["error"]["code"] == "CARD_NOT_FOUND"


class TestSinConfigurar:
    def test_si_falta_la_clave_lo_dice_claramente(self, app, monkeypatch):
        token = preparar(app)
        monkeypatch.setenv("AI_API_KEY", "")
        status, data = app.call("ia", "check_answer", token=token, body={
            "topicId": TOPIC, "cardId": "crd_0001", "answer": "Algo.",
        })
        assert status == 503
        assert data["error"]["code"] == "AI_NOT_CONFIGURED"
