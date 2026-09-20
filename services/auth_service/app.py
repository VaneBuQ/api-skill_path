"""auth-service — registro e inicio de sesión (historias 9 y 10).

Tabla propia: `users`.

El userId se genera aquí y viaja en el JWT. Ningún otro servicio vuelve a
consultar esta tabla: reciben la identidad ya resuelta por el authorizer.
"""

import re

from botocore.exceptions import ClientError
from skillpath_common.dates import to_iso
from skillpath_common.db import table
from skillpath_common.errors import (
    EmailAlreadyExists,
    InvalidCredentials,
    NotFound,
    ValidationError,
)
from skillpath_common.http import body_of, current_user_id
from skillpath_common.ids import user_id as new_user_id
from skillpath_common.passwords import DUMMY_HASH, hash_password, verify_password
from skillpath_common.router import Router
from skillpath_common.tokens import issue

router = Router("auth-service")

# Deliberadamente permisivo: validar correos con precisión quirúrgica rechaza
# direcciones legítimas. Lo que importa es que tenga forma de correo.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN = 8
NAME_MAX = 80

# El centinela de unicidad vive en la misma tabla que los perfiles, bajo una
# clave que ningún userId real puede tener.
EMAIL_PREFIX = "EMAIL#"


# --- validación --------------------------------------------------------------

def _clean_email(value) -> str:
    email = (value or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValidationError(
            "El correo no tiene un formato válido.", details={"fields": ["email"]}
        )
    return email


def _clean_password(value) -> str:
    password = value or ""
    if len(password) < PASSWORD_MIN:
        raise ValidationError(
            f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres.",
            details={"fields": ["password"], "minLength": PASSWORD_MIN},
        )
    return password


def _clean_name(value) -> str:
    name = (value or "").strip()
    if not name:
        raise ValidationError("El nombre es obligatorio.", details={"fields": ["name"]})
    return name[:NAME_MAX]


def initials_of(name: str) -> str:
    """«Lucía Mendoza» → «LM». Es el avatar que pinta el prototipo."""
    partes = [p for p in name.split() if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()


# --- acceso a datos ----------------------------------------------------------

def _users():
    return table("USERS_TABLE")


def _find_by_email(email: str) -> dict | None:
    """Busca el perfil a partir del correo.

    Va por el centinela en vez de por un índice secundario: los GSI son de
    consistencia eventual, así que alguien que acaba de registrarse podría no
    poder iniciar sesión durante unos milisegundos. El centinela es una lectura
    por clave primaria, fuertemente consistente.
    """
    pointer = _users().get_item(
        Key={"userId": EMAIL_PREFIX + email}, ConsistentRead=True
    ).get("Item")
    if not pointer:
        return None
    return _users().get_item(
        Key={"userId": pointer["ownerId"]}, ConsistentRead=True
    ).get("Item")


def _session_payload(user: dict) -> dict:
    token, expires_in = issue(
        user_id=user["userId"], name=user["name"], email=user["email"]
    )
    return {
        "userId": user["userId"],
        "name": user["name"],
        "email": user["email"],
        "initials": initials_of(user["name"]),
        "token": token,
        "expiresIn": expires_in,
    }


# --- POST /auth/register -----------------------------------------------------

@router.route("POST", "/auth/register")
def register(event, context):
    body = body_of(event)
    name = _clean_name(body.get("name"))
    email = _clean_email(body.get("email"))
    password = _clean_password(body.get("password"))

    user = {
        "userId": new_user_id(),
        "email": email,
        "name": name,
        "passwordHash": hash_password(password),
        "authProvider": "password",
        "createdAt": to_iso(),
    }

    # Las dos escrituras van en una transacción: o se crean el perfil y el
    # centinela, o no se crea ninguno. Sin esto, dos registros simultáneos con
    # el mismo correo podrían pasar ambos.
    try:
        _users().meta.client.transact_write_items(
            TransactItems=[
                {"Put": {"TableName": _users().name, "Item": user}},
                {
                    "Put": {
                        "TableName": _users().name,
                        "Item": {
                            "userId": EMAIL_PREFIX + email,
                            "ownerId": user["userId"],
                            "createdAt": user["createdAt"],
                        },
                        "ConditionExpression": "attribute_not_exists(userId)",
                    }
                },
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            # HU9 pide decir explícitamente que el correo ya existe. Aquí sí se
            # revela, a diferencia del login: en el registro el usuario necesita
            # saberlo para poder iniciar sesión en su lugar.
            raise EmailAlreadyExists() from exc
        raise

    return 201, {**_session_payload(user), "createdAt": user["createdAt"]}


# --- POST /auth/login --------------------------------------------------------

@router.route("POST", "/auth/login")
def login(event, context):
    body = body_of(event)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        raise ValidationError(
            "Correo y contraseña son obligatorios.", details={"fields": ["email", "password"]}
        )

    user = _find_by_email(email)

    # Se verifica siempre, incluso si el correo no existe, contra un hash que
    # nadie puede acertar. Así el login tarda lo mismo en ambos casos y no se
    # puede averiguar qué correos están registrados midiendo la respuesta.
    stored = user["passwordHash"] if user else DUMMY_HASH
    if not verify_password(password, stored) or user is None:
        # HU10: el mensaje no dice si falló el correo o la contraseña.
        raise InvalidCredentials()

    return 200, _session_payload(user)


# --- GET /auth/me ------------------------------------------------------------

@router.route("GET", "/auth/me")
def me(event, context):
    user = _users().get_item(Key={"userId": current_user_id(event)}).get("Item")
    if not user:
        # El token es válido pero la cuenta ya no existe.
        raise NotFound("La cuenta no existe.")
    return 200, {
        "userId": user["userId"],
        "name": user["name"],
        "email": user["email"],
        "initials": initials_of(user["name"]),
        "createdAt": user["createdAt"],
    }


lambda_handler = router.as_handler()
