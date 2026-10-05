"""Recorre el MVP completo sobre los seis microservicios."""

import pytest
from moto import mock_aws

from tests.harness import Cluster, create_tables

CORREO = "sofia@universidad.edu"


@pytest.fixture
def app(monkeypatch):
    with mock_aws():
        create_tables()
        yield Cluster(monkeypatch)


def sembrar_tema(app, topic_id="estructuras-de-datos", nombre="Estructuras de Datos", cards=12):
    """Un tema del catálogo con sus tarjetas, como lo dejaría el seed."""
    import os

    import boto3
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.Table(os.environ["TOPICS_TABLE"]).put_item(Item={
        "topicId": topic_id, "name": nombre, "description": "Pilas, colas, árboles",
        "cardCount": cards, "icon": "database", "level": "intermedio",
        "category": "Ingeniería", "visibility": "public",
        "createdAt": "2026-09-01T00:00:00Z",
    })
    app.services["flashcards"].internal_create_cards({
        "headers": {"x-internal-key": os.environ["INTERNAL_KEY"]},
        "body": __import__("json").dumps({
            "topicId": topic_id,
            "cards": [
                {"question": f"¿Concepto número {i}?", "answer": f"Definición número {i}."}
                for i in range(1, cards + 1)
            ],
        }),
    })


def registrar(app, email=CORREO):
    status, data = app.call("auth", "register", body={
        "name": "Sofía Rodríguez", "email": email, "password": "Secreta123",
    })
    assert status == 201, data
    return data["token"], data["userId"]


class TestAutenticacion:
    def test_registro_devuelve_token_e_iniciales(self, app):
        status, data = app.call("auth", "register", body={
            "name": "Sofía Rodríguez", "email": CORREO, "password": "Secreta123",
        })
        assert status == 201
        assert data["initials"] == "SR"
        assert data["token"]
        assert data["expiresIn"] == 86400

    def test_correo_repetido(self, app):
        registrar(app)
        status, data = app.call("auth", "register", body={
            "name": "Otra", "email": CORREO, "password": "Secreta123",
        })
        assert status == 409
        assert data["error"]["code"] == "EMAIL_ALREADY_EXISTS"

    def test_login_y_perfil(self, app):
        registrar(app)
        status, data = app.call("auth", "login",
                                body={"email": CORREO, "password": "Secreta123"})
        assert status == 200

        status, perfil = app.call("auth", "me", token=data["token"])
        assert status == 200
        assert perfil["email"] == CORREO

    def test_credenciales_malas_dan_error_generico(self, app):
        registrar(app)
        _, sin_cuenta = app.call("auth", "login",
                                 body={"email": "nadie@uni.edu", "password": "Secreta123"})
        _, mal_pass = app.call("auth", "login",
                               body={"email": CORREO, "password": "Equivocada1"})
        assert sin_cuenta["error"] == mal_pass["error"]

    def test_sin_token_no_se_accede(self, app):
        status, _ = app.call("topics", "my_topics")
        assert status == 401

    def test_token_invalido(self, app):
        status, _ = app.call("topics", "my_topics", token="no-es-un-token")
        assert status == 401


class TestTemas:
    def test_catalogo_y_busqueda_sin_tildes(self, app):
        sembrar_tema(app, "algebra-lineal", "Álgebra lineal", cards=5)
        status, data = app.call("topics", "list_topics")
        assert status == 200
        assert len(data["items"]) == 1

        _, encontrado = app.call("topics", "list_topics", query={"search": "algebra"})
        assert encontrado["items"][0]["name"] == "Álgebra lineal"

    def test_seguir_tema_es_idempotente(self, app):
        token, _ = registrar(app)
        sembrar_tema(app)

        status, data = app.call("topics", "follow_topic", token=token,
                                path={"topicId": "estructuras-de-datos"})
        assert status == 201
        assert data["cardCount"] == 12

        status, data = app.call("topics", "follow_topic", token=token,
                                path={"topicId": "estructuras-de-datos"})
        assert status == 200
        assert data["alreadyFollowing"] is True


class TestRepaso:
    def test_tarjetas_pendientes_y_calificacion(self, app):
        token, _ = registrar(app)
        sembrar_tema(app)
        app.call("topics", "follow_topic", token=token,
                 path={"topicId": "estructuras-de-datos"})

        status, data = app.call("flashcards", "due_cards", token=token,
                                path={"topicId": "estructuras-de-datos"})
        assert status == 200
        assert data["dueCount"] == 12
        assert data["items"][0]["state"] == "new"
        assert data["items"][0]["answer"]

        status, review = app.call("flashcards", "review_card", token=token,
                                  path={"cardId": "crd_0001"},
                                  body={"topicId": "estructuras-de-datos", "rating": "easy"})
        assert status == 200
        assert review["intervalDays"] == 1
        assert review["xpAwarded"] == 5
        # El progreso viaja en la misma respuesta porque la llamada es síncrona.
        assert review["progress"]["streakDays"] == 1

    def test_falta_topicid(self, app):
        token, _ = registrar(app)
        sembrar_tema(app)
        app.call("topics", "follow_topic", token=token,
                 path={"topicId": "estructuras-de-datos"})
        status, data = app.call("flashcards", "review_card", token=token,
                                path={"cardId": "crd_0001"}, body={"rating": "easy"})
        assert status == 400
        assert "topicId" in data["error"]["details"]["fields"]

    def test_tema_que_no_sigue(self, app):
        token, _ = registrar(app)
        sembrar_tema(app)
        status, data = app.call("flashcards", "due_cards", token=token,
                                path={"topicId": "estructuras-de-datos"})
        assert status == 403
        assert data["error"]["code"] == "NOT_FOLLOWING_TOPIC"


class TestProgreso:
    def test_resumen_global(self, app):
        token, _ = registrar(app)
        sembrar_tema(app)
        app.call("topics", "follow_topic", token=token,
                 path={"topicId": "estructuras-de-datos"})
        for i in (1, 2, 3):
            app.call("flashcards", "review_card", token=token,
                     path={"cardId": f"crd_{i:04d}"},
                     body={"topicId": "estructuras-de-datos", "rating": "easy"})

        status, data = app.call("progress", "all_progress", token=token)
        assert status == 200
        assert data["summary"]["xpTotal"] == 15
        assert data["summary"]["streakDays"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["cardsTotal"] == 12

    def test_usuario_nuevo_no_falla(self, app):
        token, _ = registrar(app)
        status, data = app.call("progress", "all_progress", token=token)
        assert status == 200
        assert data["items"] == []
        assert data["summary"]["streakDays"] == 0
