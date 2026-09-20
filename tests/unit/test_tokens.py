"""Emisión y validación de JWT."""

import time

import jwt
import pytest
from skillpath_common.errors import Unauthenticated
from skillpath_common.tokens import ALGORITHM, TTL_SECONDS, decode, from_header, issue

USUARIO = {"user_id": "usr_123", "name": "Lucía Mendoza", "email": "lucia@uni.edu"}


def test_el_token_lleva_el_usuario_y_dura_un_dia():
    token, expires_in = issue(**USUARIO)
    claims = decode(token)
    assert claims["sub"] == "usr_123"
    assert claims["email"] == "lucia@uni.edu"
    assert expires_in == TTL_SECONDS == 86400


def test_rechaza_un_token_firmado_con_otro_secreto():
    ajeno = jwt.encode({"sub": "usr_impostor"}, "otro-secreto", algorithm=ALGORITHM)
    with pytest.raises(Unauthenticated):
        decode(ajeno)


def test_rechaza_un_token_manipulado():
    token, _ = issue(**USUARIO)
    cabecera, carga, firma = token.split(".")
    with pytest.raises(Unauthenticated):
        decode(f"{cabecera}.{carga}.{firma[:-4]}xxxx")


def test_rechaza_un_token_vencido(monkeypatch):
    import skillpath_common.tokens as modulo

    class Pasado:
        @staticmethod
        def timestamp():
            return time.time() - TTL_SECONDS - 60

    monkeypatch.setattr(modulo, "now", lambda: Pasado())
    token, _ = issue(**USUARIO)
    with pytest.raises(Unauthenticated) as exc:
        decode(token)
    assert "expiró" in str(exc.value)


def test_rechaza_el_algoritmo_none():
    # Ataque clásico contra JWT: cambiar alg a "none" para saltarse la firma.
    inseguro = jwt.encode({"sub": "usr_impostor"}, key="", algorithm="none")
    with pytest.raises(Unauthenticated):
        decode(inseguro)


class TestHeaderAuthorization:
    def test_extrae_el_token_del_header(self):
        token, _ = issue(**USUARIO)
        assert from_header(f"Bearer {token}")["sub"] == "usr_123"

    def test_acepta_bearer_en_cualquier_capitalizacion(self):
        token, _ = issue(**USUARIO)
        assert from_header(f"bearer {token}")["sub"] == "usr_123"

    @pytest.mark.parametrize("valor", [None, "", "Token abc", "Bearer", "abc"])
    def test_rechaza_headers_mal_formados(self, valor):
        with pytest.raises(Unauthenticated):
            from_header(valor)
