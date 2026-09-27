"""Microservicio de autenticación — historias 9 y 10.

Tabla propia: users.

Emite el JWT que valida el resto de microservicios. El identificador del
usuario viaja en el token, nunca en la URL.
"""

import os
import re
import uuid

import boto3
from botocore.exceptions import ClientError
from common import (
    DUMMY_HASH,
    ApiError,
    authenticated,
    clean_text,
    hash_password,
    issue_token,
    parse_body,
    public,
    response,
    to_iso,
    verify_password,
)

TABLE = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"])

# Deliberadamente permisivo: validar correos con precisión quirúrgica rechaza
# direcciones legítimas. Lo que importa es que tenga forma de correo.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN = 8
NAME_MAX = 80

# El centinela de unicidad vive en la misma tabla, bajo una clave que ningún
# identificador real puede tener.
EMAIL_PREFIX = "EMAIL#"


def initials_of(name):
    """«Sofía Rodríguez» → «SR». Es el avatar que pinta el prototipo."""
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _clean_email(value):
    email = (value or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "VALIDATION_ERROR", "El correo no tiene un formato válido.",
                       {"fields": ["email"]})
    return email


def _clean_password(value):
    password = value or ""
    if len(password) < PASSWORD_MIN:
        raise ApiError(400, "VALIDATION_ERROR",
                       f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres.",
                       {"fields": ["password"], "minLength": PASSWORD_MIN})
    return password


def _find_by_email(email):
    """Busca el perfil a partir del correo.

    Va por el centinela y no por un índice secundario: los índices son de
    consistencia eventual, así que alguien recién registrado podría no poder
    entrar durante unos milisegundos. El centinela se lee por clave primaria.
    """
    pointer = TABLE.get_item(
        Key={"userId": EMAIL_PREFIX + email}, ConsistentRead=True
    ).get("Item")
    if not pointer:
        return None
    return TABLE.get_item(
        Key={"userId": pointer["ownerId"]}, ConsistentRead=True
    ).get("Item")


def _session(user):
    token, expires_in = issue_token(user["userId"], user["name"], user["email"])
    return {
        "userId": user["userId"],
        "name": user["name"],
        "email": user["email"],
        "initials": initials_of(user["name"]),
        "token": token,
        "expiresIn": expires_in,
    }


@public
def register(event):
    body = parse_body(event)
    name = clean_text(body.get("name"), "name", NAME_MAX)
    email = _clean_email(body.get("email"))
    password = _clean_password(body.get("password"))

    user = {
        "userId": f"usr_{uuid.uuid4().hex}",
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
        TABLE.meta.client.transact_write_items(
            TransactItems=[
                {"Put": {"TableName": TABLE.name, "Item": user}},
                {
                    "Put": {
                        "TableName": TABLE.name,
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
            # La historia 9 pide decirlo explícitamente: aquí el usuario
            # necesita saberlo para poder iniciar sesión en su lugar.
            raise ApiError(409, "EMAIL_ALREADY_EXISTS",
                           "Este correo ya está registrado.") from exc
        raise

    return response(201, {**_session(user), "createdAt": user["createdAt"]})


@public
def login(event):
    body = parse_body(event)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        raise ApiError(400, "VALIDATION_ERROR", "Correo y contraseña son obligatorios.",
                       {"fields": ["email", "password"]})

    user = _find_by_email(email)

    # Se verifica siempre, incluso si el correo no existe, contra un hash que
    # nadie puede acertar. Así iniciar sesión tarda lo mismo en ambos casos y
    # no se puede averiguar qué correos están registrados midiendo la respuesta.
    stored = user["passwordHash"] if user else DUMMY_HASH
    if not verify_password(password, stored) or user is None:
        # La historia 10 pide que el mensaje no diga cuál de los dos falló.
        raise ApiError(401, "INVALID_CREDENTIALS", "Correo o contraseña incorrectos.")

    return response(200, _session(user))


@authenticated
def me(event, user_id):
    user = TABLE.get_item(Key={"userId": user_id}).get("Item")
    if not user:
        raise ApiError(404, "NOT_FOUND", "La cuenta no existe.")
    return response(200, {
        "userId": user["userId"],
        "name": user["name"],
        "email": user["email"],
        "initials": initials_of(user["name"]),
        "createdAt": user["createdAt"],
    })
