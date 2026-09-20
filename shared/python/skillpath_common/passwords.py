"""Hashing de contraseñas con PBKDF2-SHA256.

Se usa `hashlib` de la librería estándar en lugar de bcrypt a propósito
(observación #17): el paquete `bcrypt` incluye un binario compilado que debe
coincidir con el sistema de Lambda (Amazon Linux). Compilado en macOS, Lambda
falla al importarlo, y resolverlo exige una layer o compilar en Docker.

PBKDF2 ya viene en el runtime de Lambda, no hay nada que empaquetar, y es un
algoritmo legítimo de hashing de contraseñas (es el que Django usa por defecto).
"""

import hashlib
import hmac
import os

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 240_000
SALT_BYTES = 16


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Devuelve `pbkdf2_sha256$<iteraciones>$<salt hex>$<hash hex>`."""
    if not password:
        raise ValueError("La contraseña no puede estar vacía")
    salt = salt if salt is not None else os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Compara en tiempo constante para no filtrar información por latencia."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Hash de una contraseña que nadie conoce. Se verifica contra este cuando el
# correo no existe, para que login tarde lo mismo exista o no el usuario y no
# se pueda averiguar qué correos están registrados midiendo el tiempo (HU10).
DUMMY_HASH = hash_password("contraseña-que-nunca-nadie-usara", salt=b"\x00" * SALT_BYTES)
