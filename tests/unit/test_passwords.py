"""Hashing de contraseñas con PBKDF2 (observación #17)."""

from skillpath_common.passwords import (
    DUMMY_HASH,
    ITERATIONS,
    hash_password,
    verify_password,
)


def test_la_contrasena_nunca_se_guarda_en_claro():
    hashed = hash_password("Secreta123")
    assert "Secreta123" not in hashed


def test_verifica_la_contrasena_correcta():
    assert verify_password("Secreta123", hash_password("Secreta123"))


def test_rechaza_la_contrasena_incorrecta():
    assert not verify_password("Secreta124", hash_password("Secreta123"))


def test_dos_usuarios_con_la_misma_contrasena_tienen_hashes_distintos():
    # Cada uno lleva su propio salt: sin esto, una tabla arcoíris revelaría
    # de golpe a todos los que usan la misma contraseña.
    assert hash_password("Secreta123") != hash_password("Secreta123")


def test_el_formato_incluye_algoritmo_iteraciones_y_salt():
    algorithm, iterations, salt, digest = hash_password("x").split("$")
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) == ITERATIONS
    assert len(salt) == 32   # 16 bytes en hexadecimal
    assert len(digest) == 64  # sha256


def test_un_hash_corrupto_no_revienta():
    for basura in ["", "abc", "bcrypt$1$2$3", "pbkdf2_sha256$no-es-numero$aa$bb"]:
        assert verify_password("Secreta123", basura) is False


def test_existe_un_hash_dummy_para_igualar_tiempos():
    # HU10: el login debe tardar lo mismo exista o no el correo, para que no se
    # pueda averiguar qué correos están registrados midiendo la respuesta.
    assert DUMMY_HASH.startswith("pbkdf2_sha256$")
    assert not verify_password("cualquier-cosa", DUMMY_HASH)
