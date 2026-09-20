"""Authorizer de API Gateway.

Es la única pieza que valida tokens, así que es la que impide que un usuario
acceda a los datos de otro (observación #3).
"""

import importlib
import sys

import pytest


@pytest.fixture
def authorizer():
    sys.path.insert(0, "services/authorizer")
    import app

    return importlib.reload(app)


def evento(authorization=None, header_name="authorization"):
    headers = {header_name: authorization} if authorization is not None else {}
    return {"headers": headers, "routeKey": "GET /me/topics"}


def test_acepta_un_token_valido_y_entrega_el_userid(authorizer):
    from skillpath_common.tokens import issue

    token, _ = issue(user_id="usr_123", name="Lucía Mendoza", email="lucia@uni.edu")
    result = authorizer.lambda_handler(evento(f"Bearer {token}"))

    assert result["isAuthorized"] is True
    assert result["context"]["userId"] == "usr_123"
    assert result["context"]["email"] == "lucia@uni.edu"


def test_funciona_con_el_header_capitalizado(authorizer):
    from skillpath_common.tokens import issue

    token, _ = issue(user_id="usr_123", name="L", email="l@u.edu")
    result = authorizer.lambda_handler(evento(f"Bearer {token}", header_name="Authorization"))
    assert result["isAuthorized"] is True


@pytest.mark.parametrize(
    "valor",
    [None, "", "Bearer ", "Bearer no-es-un-token", "Basic dXNlcjpwYXNz", "abc.def.ghi"],
)
def test_deniega_credenciales_invalidas(authorizer, valor):
    assert authorizer.lambda_handler(evento(valor))["isAuthorized"] is False


def test_deniega_un_token_de_otro_secreto(authorizer):
    import jwt

    ajeno = jwt.encode({"sub": "usr_impostor"}, "secreto-del-atacante", algorithm="HS256")
    assert authorizer.lambda_handler(evento(f"Bearer {ajeno}"))["isAuthorized"] is False


def test_la_denegacion_no_filtra_informacion(authorizer):
    # La respuesta de rechazo no debe explicar por qué falló: eso ayudaría a
    # un atacante a distinguir "token vencido" de "token inválido".
    result = authorizer.lambda_handler(evento("Bearer basura"))
    assert result == {"isAuthorized": False}
