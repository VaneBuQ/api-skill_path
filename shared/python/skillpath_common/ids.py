"""Generación de identificadores.

Los quizzes usan ULID porque la SK de `quiz-attempts` es el quizId: al ser
ordenable por tiempo, `Query(userId)` devuelve el historial en orden
cronológico sin necesidad de un índice adicional.
"""

import os
import time
from uuid import uuid4

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ULID_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def ulid() -> str:
    """ULID de 26 caracteres: 10 de timestamp + 16 de aleatoriedad."""
    timestamp = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(timestamp, 10) + _encode(randomness, 16)


def user_id() -> str:
    return f"usr_{ulid()}"


def quiz_id() -> str:
    return f"qz_{ulid()}"


def event_id() -> str:
    """Identificador de un evento entre servicios, para descartar duplicados."""
    return uuid4().hex
