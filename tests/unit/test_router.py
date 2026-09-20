"""Router compartido: despacho de rutas HTTP y de llamadas entre servicios."""

import json

import pytest
from skillpath_common.errors import Conflict, NotFound
from skillpath_common.router import Router


@pytest.fixture
def router():
    r = Router("pruebas")

    @r.route("GET", "/cosas/{id}")
    def get_cosa(event, context):
        return 200, {"id": event["pathParameters"]["id"]}

    @r.route("POST", "/cosas")
    def crear(event, context):
        raise Conflict("Ya existe.", details={"campo": "nombre"})

    @r.route("GET", "/explota")
    def explota(event, context):
        raise RuntimeError("fallo interno con detalles sensibles")

    @r.internal("sumar")
    def sumar(data):
        return {"total": data["a"] + data["b"]}

    return r.as_handler()


def http(route_key, path_params=None):
    return {
        "routeKey": route_key,
        "pathParameters": path_params or {},
        "requestContext": {"requestId": "req-1"},
    }


class TestRutasHttp:
    def test_despacha_por_routekey(self, router):
        r = router(http("GET /cosas/{id}", {"id": "abc"}))
        assert r["statusCode"] == 200
        assert json.loads(r["body"]) == {"id": "abc"}

    def test_ruta_desconocida_da_404(self, router):
        assert router(http("GET /no-existe"))["statusCode"] == 404

    def test_los_errores_de_negocio_llevan_codigo_mensaje_y_detalles(self, router):
        r = router(http("POST /cosas"))
        body = json.loads(r["body"])
        assert r["statusCode"] == 409
        assert body["error"]["code"] == "CONFLICT"
        assert body["error"]["message"] == "Ya existe."
        assert body["error"]["details"] == {"campo": "nombre"}
        assert body["requestId"] == "req-1"

    def test_un_error_inesperado_no_filtra_el_detalle(self, router):
        r = router(http("GET /explota"))
        assert r["statusCode"] == 500
        assert "sensibles" not in r["body"]
        assert json.loads(r["body"])["error"]["code"] == "INTERNAL_ERROR"

    def test_toda_respuesta_lleva_cabeceras_cors(self, router):
        r = router(http("GET /cosas/{id}", {"id": "x"}))
        assert "Access-Control-Allow-Origin" in r["headers"]

    def test_los_acentos_no_se_escapan(self, router):
        r = router(http("POST /cosas"))
        assert "existe" in r["body"]
        assert "\\u" not in r["body"]


class TestLlamadasInternas:
    def test_devuelve_el_dato_crudo_sin_envelope(self, router):
        # Quien llama es otro microservicio, no un navegador.
        assert router({"internalAction": "sumar", "data": {"a": 2, "b": 3}}) == {"total": 5}

    def test_una_accion_desconocida_propaga_la_excepcion(self, router):
        # Debe llegar como FunctionError para que el servicio que llamó lo note.
        with pytest.raises(NotFound):
            router({"internalAction": "restar", "data": {}})
