"""auth-service — historias 9 (registro) y 10 (inicio de sesión)."""

import importlib
import json
import sys

import pytest
from moto import mock_aws


@pytest.fixture
def auth(monkeypatch):
    from skillpath_common import db

    with mock_aws():
        from tests.fixtures.tables import create_all

        names = create_all()
        monkeypatch.setenv("USERS_TABLE", names["users"])
        db.reset_cache()

        sys.path.insert(0, "services/auth_service")
        import app

        yield importlib.reload(app)
        db.reset_cache()


def post(path, body, user_id=None):
    event = {
        "routeKey": f"POST {path}",
        "body": json.dumps(body),
        "requestContext": {"requestId": "req-test"},
    }
    if user_id:
        event["requestContext"]["authorizer"] = {"lambda": {"userId": user_id}}
    return event


def get(path, user_id=None):
    event = {"routeKey": f"GET {path}", "requestContext": {"requestId": "req-test"}}
    if user_id:
        event["requestContext"]["authorizer"] = {"lambda": {"userId": user_id}}
    return event


def body(response):
    return json.loads(response["body"])


CUENTA = {"name": "Lucía Mendoza", "email": "lucia@universidad.edu", "password": "Secreta123"}


def registrar(auth, **overrides):
    return auth.lambda_handler(post("/auth/register", {**CUENTA, **overrides}))


class TestRegistro:
    def test_crea_la_cuenta_y_devuelve_la_sesion(self, auth):
        r = registrar(auth)
        datos = body(r)

        assert r["statusCode"] == 201
        assert datos["userId"].startswith("usr_")
        assert datos["email"] == "lucia@universidad.edu"
        assert datos["name"] == "Lucía Mendoza"
        # HU9 pide redirigir a la página principal tras crear la cuenta:
        # sin token habría que pedir login otra vez.
        assert datos["token"]
        assert datos["expiresIn"] == 86400

    def test_el_avatar_del_prototipo_sale_del_nombre(self, auth):
        assert body(registrar(auth))["initials"] == "LM"

    def test_la_contrasena_no_viaja_en_la_respuesta(self, auth):
        assert "Secreta123" not in registrar(auth)["body"]
        assert "passwordHash" not in body(registrar(auth, email="otra@uni.edu"))

    def test_un_correo_repetido_da_error_explicito(self, auth):
        registrar(auth)
        r = registrar(auth, name="Otra Persona")

        # HU9: "THEN se muestra un mensaje de error indicando que el correo ya existe"
        assert r["statusCode"] == 409
        assert body(r)["error"]["code"] == "EMAIL_ALREADY_EXISTS"

    def test_el_correo_se_normaliza_a_minusculas(self, auth):
        registrar(auth, email="Lucia@Universidad.EDU")
        # Y por lo tanto un segundo registro con otra capitalización choca.
        assert registrar(auth, email="lucia@universidad.edu")["statusCode"] == 409

    def test_el_correo_se_recorta(self, auth):
        assert body(registrar(auth, email="  lucia@uni.edu  "))["email"] == "lucia@uni.edu"

    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("email", "no-es-un-correo"),
            ("email", "sin@dominio"),
            ("email", ""),
            ("email", None),
            ("password", "corta"),
            ("password", ""),
            ("name", "   "),
            ("name", ""),
        ],
    )
    def test_rechaza_datos_invalidos(self, auth, campo, valor):
        r = registrar(auth, **{campo: valor})
        assert r["statusCode"] == 400
        assert body(r)["error"]["code"] == "VALIDATION_ERROR"
        assert campo in body(r)["error"]["details"]["fields"]

    def test_el_token_emitido_identifica_al_usuario(self, auth):
        datos = body(registrar(auth))
        from skillpath_common.tokens import decode

        assert decode(datos["token"])["sub"] == datos["userId"]


class TestInicioDeSesion:
    def test_entra_con_credenciales_correctas(self, auth):
        creado = body(registrar(auth))
        r = auth.lambda_handler(
            post("/auth/login", {"email": CUENTA["email"], "password": CUENTA["password"]})
        )

        assert r["statusCode"] == 200
        assert body(r)["userId"] == creado["userId"]
        assert body(r)["token"]

    def test_puede_entrar_inmediatamente_despues_de_registrarse(self, auth):
        # El motivo de buscar por centinela y no por GSI: un índice secundario
        # es de consistencia eventual y este caso podría fallar.
        registrar(auth)
        r = auth.lambda_handler(post("/auth/login", CUENTA))
        assert r["statusCode"] == 200

    def test_entra_aunque_escriba_el_correo_en_mayusculas(self, auth):
        registrar(auth)
        r = auth.lambda_handler(
            post("/auth/login", {"email": "LUCIA@UNIVERSIDAD.EDU", "password": "Secreta123"})
        )
        assert r["statusCode"] == 200

    def test_contrasena_incorrecta_da_error_generico(self, auth):
        registrar(auth)
        r = auth.lambda_handler(
            post("/auth/login", {"email": CUENTA["email"], "password": "Equivocada1"})
        )
        assert r["statusCode"] == 401
        assert body(r)["error"]["code"] == "INVALID_CREDENTIALS"

    def test_correo_inexistente_da_el_mismo_error_que_contrasena_mala(self, auth):
        registrar(auth)
        sin_cuenta = auth.lambda_handler(
            post("/auth/login", {"email": "nadie@uni.edu", "password": "Secreta123"})
        )
        mal_pass = auth.lambda_handler(
            post("/auth/login", {"email": CUENTA["email"], "password": "Equivocada1"})
        )

        # HU10: "THEN se muestra un mensaje de error sin especificar si el
        # correo o la contraseña fue el fallo".
        assert sin_cuenta["statusCode"] == mal_pass["statusCode"] == 401
        assert body(sin_cuenta)["error"] == body(mal_pass)["error"]

    def test_el_mensaje_no_menciona_cual_campo_fallo(self, auth):
        r = auth.lambda_handler(post("/auth/login", {"email": "x@y.edu", "password": "abcd1234"}))
        mensaje = body(r)["error"]["message"].lower()
        assert "no existe" not in mensaje
        assert "no está registrado" not in mensaje

    @pytest.mark.parametrize("cuerpo", [{}, {"email": "a@b.edu"}, {"password": "abcd1234"}])
    def test_faltan_campos(self, auth, cuerpo):
        r = auth.lambda_handler(post("/auth/login", cuerpo))
        assert r["statusCode"] == 400


class TestPerfil:
    def test_devuelve_el_perfil_del_token(self, auth):
        creado = body(registrar(auth))
        r = auth.lambda_handler(get("/auth/me", user_id=creado["userId"]))

        assert r["statusCode"] == 200
        assert body(r)["email"] == CUENTA["email"]
        assert body(r)["initials"] == "LM"
        assert "passwordHash" not in body(r)

    def test_sin_token_no_hay_perfil(self, auth):
        assert auth.lambda_handler(get("/auth/me"))["statusCode"] == 401

    def test_token_valido_de_una_cuenta_borrada(self, auth):
        r = auth.lambda_handler(get("/auth/me", user_id="usr_que_no_existe"))
        assert r["statusCode"] == 404

    def test_un_usuario_no_puede_ver_el_perfil_de_otro(self, auth):
        # No hay forma de intentarlo: la ruta no acepta un userId. El único
        # origen de identidad es el token (observación #3).
        primero = body(registrar(auth))
        segundo = body(registrar(auth, email="otro@uni.edu", name="Otro Usuario"))

        r = auth.lambda_handler(get("/auth/me", user_id=primero["userId"]))
        assert body(r)["userId"] == primero["userId"] != segundo["userId"]


class TestIniciales:
    @pytest.mark.parametrize(
        "nombre,esperado",
        [
            ("Lucía Mendoza", "LM"),
            ("Débora Elsa Jerónimo Balcázar", "DB"),
            ("Ana", "AN"),
            ("  Grace   Moscosso  ", "GM"),
        ],
    )
    def test_calcula_el_avatar(self, auth, nombre, esperado):
        assert auth.initials_of(nombre) == esperado
