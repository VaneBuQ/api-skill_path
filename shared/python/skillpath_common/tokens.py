"""Emisión y validación de JWT.

`auth-service` es el único que emite tokens. El resto de servicios nunca los
decodifica por su cuenta: el authorizer de API Gateway ya resolvió el userId y
lo deja en el contexto de la petición (ver `context.py`).
"""

import os

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from .dates import now
from .errors import Unauthenticated

ALGORITHM = "HS256"
TTL_SECONDS = 24 * 60 * 60


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        # Falla fuerte y temprano: un servicio sin secreto no debe arrancar.
        raise RuntimeError("Falta la variable de entorno JWT_SECRET")
    return secret


def issue(*, user_id: str, name: str, email: str) -> tuple[str, int]:
    """Devuelve (token, segundos_de_vigencia)."""
    issued_at = int(now().timestamp())
    payload = {
        "sub": user_id,
        "name": name,
        "email": email,
        "iat": issued_at,
        "exp": issued_at + TTL_SECONDS,
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM), TTL_SECONDS


def decode(token: str) -> dict:
    """Valida firma y expiración. Lanza `Unauthenticated` si algo falla."""
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except ExpiredSignatureError as exc:
        raise Unauthenticated("Tu sesión expiró. Inicia sesión otra vez.") from exc
    except InvalidTokenError as exc:
        raise Unauthenticated("El token no es válido.") from exc


def from_header(header_value: str | None) -> dict:
    """Extrae y valida el token de un header `Authorization: Bearer <token>`."""
    if not header_value:
        raise Unauthenticated()
    parts = header_value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise Unauthenticated("El header Authorization debe ser «Bearer <token>».")
    return decode(parts[1])
