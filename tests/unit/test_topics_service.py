"""topics-service — historia 1 (seguir temas) e historia 8 (mazos propios)."""

import json

import pytest
from moto import mock_aws

from tests.fixtures.services import load, wire


@pytest.fixture
def svc(monkeypatch):
    """topics-service con flashcards-service y progress-service conectados."""
    from skillpath_common import db

    with mock_aws():
        from tests.fixtures.tables import create_all

        names = create_all()
        for short, full in names.items():
            monkeypatch.setenv(short.upper().replace("-", "_") + "_TABLE", full)
        monkeypatch.setenv("FLASHCARDS_FUNCTION", "flashcards")
        monkeypatch.setenv("PROGRESS_FUNCTION", "progress")
        db.reset_cache()

        flashcards = load("flashcards_service")
        progress = load("progress_service")
        topics = load("topics_service")

        fake_call = wire(
            monkeypatch, FLASHCARDS_FUNCTION=flashcards, PROGRESS_FUNCTION=progress
        )
        # topics-service importó `call` por nombre, así que hay que sustituir
        # también la referencia que guardó al importarlo.
        monkeypatch.setattr(topics, "call", fake_call)

        topics.flashcards = flashcards
        topics.progress = progress
        yield topics
        db.reset_cache()


USER = "usr_lucia"
OTRO = "usr_miguel"


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


MAZO = {
    "name": "Apuntes de Cloud Computing",
    "description": "Lo que dijo el profe en clase",
    "cards": [
        {"question": "¿Qué es IaC?", "answer": "Infraestructura como código.",
         "hint": "No es la Parte C."},
        {"question": "¿Qué garantiza ACID?",
         "answer": "Atomicidad, consistencia, aislamiento y durabilidad."},
    ],
}


def crear_mazo(svc, user=USER, **overrides):
    return svc.lambda_handler(
        request("POST", "/me/decks", user=user, body={**MAZO, **overrides})
    )


def sembrar_catalogo(svc):
    from skillpath_common.db import table

    table("TOPICS_TABLE").put_item(Item={
        "topicId": "algebra-lineal", "name": "Álgebra lineal",
        "description": "Matrices", "cardCount": 12, "icon": "atom",
        "level": "intermedio", "visibility": "public", "createdAt": "2026-09-01T00:00:00Z",
    })
    table("TOPICS_TABLE").put_item(Item={
        "topicId": "estadistica", "name": "Estadística",
        "description": "Inferencia", "cardCount": 12, "icon": "bar-chart",
        "level": "intermedio", "visibility": "public", "createdAt": "2026-09-01T00:00:00Z",
    })


# =============================================================================
# Historia 1 — catálogo y «Mis temas»
# =============================================================================

class TestCatalogo:
    def test_lista_los_temas_publicos_ordenados(self, svc):
        sembrar_catalogo(svc)
        r = svc.lambda_handler(request("GET", "/topics", user=None))
        nombres = [t["name"] for t in data(r)["items"]]

        assert r["statusCode"] == 200
        assert nombres == sorted(nombres)

    def test_el_buscador_ignora_las_tildes(self, svc):
        sembrar_catalogo(svc)
        r = svc.lambda_handler(
            request("GET", "/topics", user=None, query={"search": "algebra"})
        )
        assert [t["name"] for t in data(r)["items"]] == ["Álgebra lineal"]

    def test_el_buscador_ignora_mayusculas(self, svc):
        sembrar_catalogo(svc)
        r = svc.lambda_handler(
            request("GET", "/topics", user=None, query={"search": "ESTADÍSTICA"})
        )
        assert len(data(r)["items"]) == 1

    def test_los_mazos_propios_no_aparecen_en_el_catalogo(self, svc):
        sembrar_catalogo(svc)
        crear_mazo(svc)

        r = svc.lambda_handler(request("GET", "/topics", user=None))
        ids = [t["topicId"] for t in data(r)["items"]]
        assert not any(i.startswith("deck_") for i in ids)
        assert len(ids) == 2


class TestSeguirTema:
    def test_agrega_el_tema_y_devuelve_el_total_de_conceptos(self, svc):
        sembrar_catalogo(svc)
        r = svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", path={"topicId": "algebra-lineal"})
        )
        # Historia 1: «se muestra el número total de conceptos del mazo».
        assert r["statusCode"] == 201
        assert data(r)["cardCount"] == 12
        assert data(r)["alreadyFollowing"] is False

    def test_seguir_dos_veces_es_idempotente(self, svc):
        sembrar_catalogo(svc)
        evento = request("POST", "/topics/{topicId}/follow", path={"topicId": "algebra-lineal"})
        svc.lambda_handler(evento)
        r = svc.lambda_handler(evento)

        assert r["statusCode"] == 200
        assert data(r)["alreadyFollowing"] is True

    def test_un_tema_inexistente_da_404(self, svc):
        r = svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", path={"topicId": "no-existe"})
        )
        assert r["statusCode"] == 404
        assert data(r)["error"]["code"] == "TOPIC_NOT_FOUND"

    def test_dejar_de_seguir(self, svc):
        sembrar_catalogo(svc)
        svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", path={"topicId": "algebra-lineal"})
        )
        r = svc.lambda_handler(
            request("DELETE", "/topics/{topicId}/follow", path={"topicId": "algebra-lineal"})
        )
        assert r["statusCode"] == 204
        assert "body" not in r

    def test_mis_temas_solo_muestra_los_del_usuario(self, svc):
        sembrar_catalogo(svc)
        svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", path={"topicId": "algebra-lineal"})
        )
        svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", user=OTRO,
                    path={"topicId": "estadistica"})
        )

        mios = data(svc.lambda_handler(request("GET", "/me/topics")))["items"]
        assert [t["topicId"] for t in mios] == ["algebra-lineal"]


# =============================================================================
# Historia 8 — mazos propios
# =============================================================================

class TestCrearMazo:
    def test_crea_el_mazo_con_sus_tarjetas(self, svc):
        r = crear_mazo(svc)
        mazo = data(r)

        assert r["statusCode"] == 201
        assert mazo["topicId"].startswith("deck_")
        assert mazo["name"] == "Apuntes de Cloud Computing"
        assert mazo["cardCount"] == 2
        assert mazo["isOwn"] is True

    def test_queda_disponible_para_repasar_junto_a_los_demas(self, svc):
        # Criterio de aceptación de la historia 8.
        sembrar_catalogo(svc)
        svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", path={"topicId": "algebra-lineal"})
        )
        creado = data(crear_mazo(svc))

        mis_temas = data(svc.lambda_handler(request("GET", "/me/topics")))["items"]
        ids = [t["topicId"] for t in mis_temas]
        assert creado["topicId"] in ids
        assert "algebra-lineal" in ids

    def test_exige_al_menos_una_tarjeta(self, svc):
        r = crear_mazo(svc, cards=[])
        assert r["statusCode"] == 400
        assert "cards" in data(r)["error"]["details"]["fields"]

    def test_exige_nombre(self, svc):
        r = crear_mazo(svc, name="   ")
        assert r["statusCode"] == 400
        assert "name" in data(r)["error"]["details"]["fields"]

    @pytest.mark.parametrize("campo", ["question", "answer"])
    def test_cada_tarjeta_necesita_pregunta_y_respuesta(self, svc, campo):
        tarjeta = {"question": "¿Qué?", "answer": "Eso", **{campo: ""}}
        r = crear_mazo(svc, cards=[tarjeta])
        assert r["statusCode"] == 400
        # El error señala exactamente qué tarjeta y qué campo.
        assert f"cards[0].{campo}" in data(r)["error"]["details"]["fields"]

    def test_la_pista_es_opcional(self, svc):
        r = crear_mazo(svc, cards=[{"question": "¿Qué?", "answer": "Eso"}])
        assert r["statusCode"] == 201

    def test_rechaza_nombres_demasiado_largos(self, svc):
        r = crear_mazo(svc, name="x" * 200)
        assert r["statusCode"] == 400

    def test_limita_cuantas_tarjetas_se_crean_de_una_vez(self, svc):
        muchas = [{"question": f"P{i}", "answer": f"R{i}"} for i in range(60)]
        r = crear_mazo(svc, cards=muchas)
        assert r["statusCode"] == 400
        assert data(r)["error"]["details"]["maxItems"] == 50

    def test_sin_sesion_no_se_puede_crear(self, svc):
        r = svc.lambda_handler(request("POST", "/me/decks", user=None, body=MAZO))
        assert r["statusCode"] == 401


class TestVerMazo:
    def test_lista_solo_los_mazos_propios(self, svc):
        sembrar_catalogo(svc)
        svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", path={"topicId": "algebra-lineal"})
        )
        creado = data(crear_mazo(svc))

        mazos = data(svc.lambda_handler(request("GET", "/me/decks")))["items"]
        assert [m["topicId"] for m in mazos] == [creado["topicId"]]

    def test_el_detalle_trae_las_tarjetas(self, svc):
        creado = data(crear_mazo(svc))
        r = svc.lambda_handler(
            request("GET", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        )
        detalle = data(r)

        assert r["statusCode"] == 200
        assert len(detalle["cards"]) == 2
        assert detalle["cards"][0]["question"] == "¿Qué es IaC?"
        assert detalle["cards"][0]["hint"] == "No es la Parte C."

    def test_el_mazo_de_otro_usuario_no_existe(self, svc):
        creado = data(crear_mazo(svc, user=USER))
        r = svc.lambda_handler(
            request("GET", "/me/decks/{topicId}", user=OTRO,
                    path={"topicId": creado["topicId"]})
        )
        # 404 y no 403: decir «existe pero no es tuyo» revelaría qué
        # identificadores existen.
        assert r["statusCode"] == 404

    def test_otro_usuario_no_puede_seguir_un_mazo_ajeno(self, svc):
        creado = data(crear_mazo(svc, user=USER))
        r = svc.lambda_handler(
            request("POST", "/topics/{topicId}/follow", user=OTRO,
                    path={"topicId": creado["topicId"]})
        )
        assert r["statusCode"] == 404


class TestEditarMazo:
    def test_renombra_el_mazo_en_los_dos_sitios(self, svc):
        creado = data(crear_mazo(svc))
        svc.lambda_handler(
            request("PATCH", "/me/decks/{topicId}", path={"topicId": creado["topicId"]},
                    body={"name": "Cloud Computing — parcial"})
        )

        # El nombre está denormalizado en user-topics para poder pintar
        # «Mis temas» con una sola consulta: debe quedar sincronizado.
        mis_temas = data(svc.lambda_handler(request("GET", "/me/topics")))["items"]
        assert mis_temas[0]["name"] == "Cloud Computing — parcial"

    def test_agrega_una_tarjeta_y_actualiza_el_contador(self, svc):
        creado = data(crear_mazo(svc))
        r = svc.lambda_handler(
            request("POST", "/me/decks/{topicId}/cards", path={"topicId": creado["topicId"]},
                    body={"question": "¿Qué es un GSI?", "answer": "Un índice secundario global."})
        )

        assert r["statusCode"] == 201
        assert data(r)["cardCount"] == 3
        detalle = data(svc.lambda_handler(
            request("GET", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        ))
        assert detalle["cardCount"] == 3
        assert len(detalle["cards"]) == 3

    def test_agregar_no_pisa_las_tarjetas_existentes(self, svc):
        creado = data(crear_mazo(svc))
        svc.lambda_handler(
            request("POST", "/me/decks/{topicId}/cards", path={"topicId": creado["topicId"]},
                    body={"question": "Nueva", "answer": "Respuesta"})
        )
        detalle = data(svc.lambda_handler(
            request("GET", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        ))
        ids = [c["cardId"] for c in detalle["cards"]]
        assert len(set(ids)) == 3
        assert detalle["cards"][0]["question"] == "¿Qué es IaC?"

    def test_elimina_una_tarjeta_y_actualiza_el_contador(self, svc):
        creado = data(crear_mazo(svc))
        detalle = data(svc.lambda_handler(
            request("GET", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        ))
        card_id = detalle["cards"][0]["cardId"]

        r = svc.lambda_handler(request(
            "DELETE", "/me/decks/{topicId}/cards/{cardId}",
            path={"topicId": creado["topicId"], "cardId": card_id},
        ))
        assert r["statusCode"] == 204

        despues = data(svc.lambda_handler(
            request("GET", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        ))
        assert despues["cardCount"] == 1

    def test_eliminar_una_tarjeta_inexistente_da_404(self, svc):
        creado = data(crear_mazo(svc))
        r = svc.lambda_handler(request(
            "DELETE", "/me/decks/{topicId}/cards/{cardId}",
            path={"topicId": creado["topicId"], "cardId": "crd_9999"},
        ))
        assert r["statusCode"] == 404

    def test_otro_usuario_no_puede_agregar_tarjetas(self, svc):
        creado = data(crear_mazo(svc, user=USER))
        r = svc.lambda_handler(request(
            "POST", "/me/decks/{topicId}/cards", user=OTRO,
            path={"topicId": creado["topicId"]},
            body={"question": "Intruso", "answer": "No debería"},
        ))
        assert r["statusCode"] == 404


class TestEliminarMazo:
    def test_desaparece_de_mis_temas_y_de_mis_mazos(self, svc):
        creado = data(crear_mazo(svc))
        r = svc.lambda_handler(
            request("DELETE", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        )
        assert r["statusCode"] == 204

        assert data(svc.lambda_handler(request("GET", "/me/decks")))["items"] == []
        assert data(svc.lambda_handler(request("GET", "/me/topics")))["items"] == []

    def test_borra_tambien_las_tarjetas(self, svc):
        creado = data(crear_mazo(svc))
        svc.lambda_handler(
            request("DELETE", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        )
        restantes = svc.flashcards.lambda_handler({
            "internalAction": "getTopicCards", "data": {"topicId": creado["topicId"]},
        })
        assert restantes["items"] == []

    def test_borra_tambien_el_progreso(self, svc):
        # Sin esto, el mazo eliminado seguiría apareciendo en «Mi progreso».
        from skillpath_common.db import table

        creado = data(crear_mazo(svc))
        table("USER_PROGRESS_TABLE").put_item(Item={
            "userId": USER, "topicId": creado["topicId"], "percent": 40,
        })
        svc.lambda_handler(
            request("DELETE", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        )
        restante = table("USER_PROGRESS_TABLE").get_item(
            Key={"userId": USER, "topicId": creado["topicId"]}
        ).get("Item")
        assert restante is None

    def test_el_detalle_deja_de_responder(self, svc):
        creado = data(crear_mazo(svc))
        svc.lambda_handler(
            request("DELETE", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        )
        r = svc.lambda_handler(
            request("GET", "/me/decks/{topicId}", path={"topicId": creado["topicId"]})
        )
        assert r["statusCode"] == 404

    def test_otro_usuario_no_puede_borrarlo(self, svc):
        creado = data(crear_mazo(svc, user=USER))
        r = svc.lambda_handler(
            request("DELETE", "/me/decks/{topicId}", user=OTRO,
                    path={"topicId": creado["topicId"]})
        )
        assert r["statusCode"] == 404
        assert data(svc.lambda_handler(request("GET", "/me/decks")))["items"] != []

    def test_un_mazo_propio_no_se_deja_de_seguir_se_elimina(self, svc):
        creado = data(crear_mazo(svc))
        r = svc.lambda_handler(
            request("DELETE", "/topics/{topicId}/follow", path={"topicId": creado["topicId"]})
        )
        # Quitarlo de «Mis temas» lo dejaría inaccesible para siempre.
        assert r["statusCode"] == 409
        assert data(r)["error"]["code"] == "OWN_DECK_CANNOT_UNFOLLOW"
