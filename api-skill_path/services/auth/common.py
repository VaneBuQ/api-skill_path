"""Utilidades compartidas por los seis microservicios de SkillPath.

Este archivo es la ÚNICA fuente: `scripts/sync-common.sh` lo copia a cada
servicio antes de desplegar. En este patrón no hay Lambda Layers —cada servicio
se empaqueta solo con lo que hay en su carpeta—, así que la copia es necesaria.
Una prueba falla si alguna copia difiere de este original.

No usa más dependencias que la librería estándar y boto3, que ya viene en el
runtime de Lambda: así los `requirements.txt` quedan vacíos y no hace falta
empaquetar nada.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

# --- Zona horaria -----------------------------------------------------------
# Perú no aplica horario de verano, así que un desfase fijo es correcto y evita
# depender de la base de datos de zonas horarias dentro de Lambda.
LIMA = timezone(timedelta(hours=-5), name="America/Lima")
DATE_FMT = "%Y-%m-%d"


def now():
    return datetime.now(LIMA)


def today_str():
    return now().strftime(DATE_FMT)


def yesterday_str():
    return (now() - timedelta(days=1)).strftime(DATE_FMT)


def to_iso(moment=None):
    return (moment or now()).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(days, start=None):
    base = start or now().date()
    return (base + timedelta(days=days)).strftime(DATE_FMT)


# --- Respuestas HTTP --------------------------------------------------------

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
}


class Encoder(json.JSONEncoder):
    """DynamoDB devuelve números como Decimal; json no sabe serializarlos."""

    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


def response(status_code, body=None):
    if status_code == 204:
        return {"statusCode": 204, "headers": dict(CORS_HEADERS)}
    return {
        "statusCode": status_code,
        "headers": dict(CORS_HEADERS),
        "body": json.dumps(body or {}, cls=Encoder, ensure_ascii=False),
    }


def error(status_code, code, message, details=None):
    """Envelope único de error. `message` se muestra al usuario tal cual."""
    payload = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return response(status_code, {"error": payload})


def parse_body(event):
    if not event.get("body"):
        return {}
    try:
        parsed = json.loads(event["body"])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def path_param(event, name):
    return (event.get("pathParameters") or {}).get(name)


def query_params(event):
    return event.get("queryStringParameters") or {}


def decimal(value):
    """DynamoDB no acepta float: los decimales viajan como Decimal."""
    return Decimal(str(value))


def to_number(value, default=0):
    if value is None:
        return default
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return value


# --- Contraseñas ------------------------------------------------------------
# PBKDF2 de la librería estándar en vez de bcrypt: bcrypt trae un binario
# compilado que habría que empaquetar para Amazon Linux.

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 240_000


def hash_password(password, salt=None):
    salt = salt if salt is not None else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Hash de una contraseña que nadie conoce. Se compara contra este cuando el
# correo no existe, para que iniciar sesión tarde lo mismo exista o no la
# cuenta y no se pueda averiguar qué correos están registrados.
DUMMY_HASH = hash_password("contrasena-que-nunca-nadie-usara", salt=b"\x00" * 16)


# --- JWT --------------------------------------------------------------------
# Se firma y valida a mano con hmac: PyJWT sería otra dependencia que
# empaquetar, y HS256 son veinte líneas.

JWT_TTL_SECONDS = 24 * 60 * 60


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _jwt_secret():
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("Falta la variable de entorno JWT_SECRET")
    return secret.encode("utf-8")


def issue_token(user_id, name, email):
    issued_at = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "name": name,
        "email": email,
        "iat": issued_at,
        "exp": issued_at + JWT_TTL_SECONDS,
    }
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(_jwt_secret(), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(signature))
    return ".".join(segments), JWT_TTL_SECONDS


def decode_token(token):
    """Devuelve los claims, o None si el token no es válido o venció."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except (ValueError, AttributeError):
        return None

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(_jwt_secret(), signing_input, hashlib.sha256).digest()
    try:
        received = _b64url_decode(signature_b64)
    except Exception:
        return None
    # Comparación en tiempo constante: una comparación normal filtraría la
    # firma correcta byte a byte midiendo el tiempo de respuesta.
    if not hmac.compare_digest(expected, received):
        return None

    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None

    if claims.get("exp", 0) < int(time.time()):
        return None
    return claims


class Unauthorized(Exception):
    """El handler no pudo identificar al usuario."""


def current_user(event):
    """userId del token.

    En este patrón no hay autorizador en el borde —cada API Gateway es de su
    microservicio—, así que la identidad se resuelve aquí. El userId sale
    siempre del token, nunca de la ruta: así no hay forma de pedir los datos de
    otra persona cambiando la URL.
    """
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    authorization = headers.get("authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise Unauthorized()
    claims = decode_token(parts[1])
    if not claims:
        raise Unauthorized()
    return claims["sub"]


def authenticated(func):
    """Envuelve un handler: resuelve el userId y captura los errores.

    Reemplaza al autorizador de API Gateway del diseño anterior.
    """

    def wrapper(event, context=None):
        try:
            user_id = current_user(event)
        except Unauthorized:
            return error(401, "UNAUTHENTICATED", "Necesitas iniciar sesión.")
        except RuntimeError as exc:
            print(f"ERROR configuracion: {exc}")
            return error(500, "INTERNAL_ERROR", "Ocurrió un error inesperado.")

        try:
            return func(event, user_id)
        except ApiError as exc:
            return error(exc.status, exc.code, exc.message, exc.details)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR no controlado en {func.__name__}: {exc!r}")
            return error(500, "INTERNAL_ERROR", "Ocurrió un error inesperado.")

    return wrapper


def public(func):
    """Igual que `authenticated`, pero sin exigir token."""

    def wrapper(event, context=None):
        try:
            return func(event)
        except ApiError as exc:
            return error(exc.status, exc.code, exc.message, exc.details)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR no controlado en {func.__name__}: {exc!r}")
            return error(500, "INTERNAL_ERROR", "Ocurrió un error inesperado.")

    return wrapper


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


# --- Texto ------------------------------------------------------------------

def strip_accents(value):
    """«Álgebra» → «algebra», para que el buscador no exija tildes."""
    normalized = unicodedata.normalize("NFD", value)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower()


def word_count(text):
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def clean_text(value, field, max_length, required=True):
    text = (value or "").strip()
    if not text:
        if required:
            raise ApiError(400, "VALIDATION_ERROR", f"El campo «{field}» es obligatorio.",
                           {"fields": [field]})
        return None
    if len(text) > max_length:
        raise ApiError(400, "VALIDATION_ERROR",
                       f"El campo «{field}» no puede superar los {max_length} caracteres.",
                       {"fields": [field], "maxLength": max_length})
    return text


# --- Reglas de negocio ------------------------------------------------------
# Viven aquí porque varios servicios necesitan la misma definición: flashcards
# decide cuándo una tarjeta pasa a dominada y progress cuenta cuántas lo están.
# Si cada uno tuviera su copia, los porcentajes dejarían de cuadrar.

EASE_INITIAL = 2.5
EASE_MIN = 1.3
EASE_MAX = 2.8
RATINGS = ("forgot", "hard", "easy")

MASTERED_MIN_REPETITIONS = 3
MASTERED_MIN_INTERVAL_DAYS = 21

XP_PER_CARD = 5
XP_PER_QUIZ = 120

QUIZ_QUESTION_COUNT = 10
QUIZ_OPTIONS_PER_QUESTION = 4
QUIZ_MIN_STUDIED_CONCEPTS = 10
QUIZ_TIME_LIMIT_SECONDS = 360
QUIZ_PASS_CORRECT = 7

# Límites de la comprobación con IA. Acotan el costo y, sobre todo, la calidad:
# una respuesta larga se vuelve imposible de evaluar y una explicación larga
# nadie la lee.
AI_MAX_ANSWER_WORDS = 60
AI_MAX_FEEDBACK_WORDS = 40


def clamp_ease(ease):
    return max(EASE_MIN, min(EASE_MAX, round(ease, 2)))


def is_mastered(repetitions, interval_days):
    return repetitions >= MASTERED_MIN_REPETITIONS and interval_days >= MASTERED_MIN_INTERVAL_DAYS


def state_for(repetitions, interval_days, reviewed=True):
    if not reviewed:
        return "new"
    return "mastered" if is_mastered(repetitions, interval_days) else "learning"


def schedule(rating, repetitions, interval_days, ease):
    """SM-2 simplificado. No toca la base de datos ni conoce fechas."""
    if rating not in RATINGS:
        raise ValueError(f"Calificación desconocida: {rating!r}")

    if rating == "forgot":
        repetitions, interval_days = 0, 0
        ease = clamp_ease(ease - 0.20)
        lapse = 1
    elif rating == "hard":
        repetitions += 1
        interval_days = max(1, round(interval_days * 1.2))
        ease = clamp_ease(ease - 0.15)
        lapse = 0
    else:
        repetitions += 1
        if repetitions == 1:
            interval_days = 1
        elif repetitions == 2:
            interval_days = 3
        else:
            interval_days = round(interval_days * ease)
        ease = clamp_ease(ease + 0.10)
        lapse = 0

    return {
        "repetitions": repetitions,
        "intervalDays": interval_days,
        "easeFactor": ease,
        "state": state_for(repetitions, interval_days),
        "lapseIncrement": lapse,
    }


def next_streak(current, last_study_date, today, yesterday):
    if last_study_date == today:
        return current or 1
    if last_study_date == yesterday:
        return current + 1
    return 1


def streak_as_read(current, last_study_date, today, yesterday):
    """La racha se muestra en 0 si no se estudió ayer ni hoy.

    Calcularlo al leer evita un proceso nocturno sobre todos los usuarios.
    """
    if not last_study_date:
        return 0
    return current if last_study_date in (today, yesterday) else 0


# --- Llamadas entre microservicios ------------------------------------------

def call_service(base_url, path, method="POST", payload=None, timeout=8):
    """Llama a otro microservicio por HTTPS.

    Cada servicio tiene su propio API Gateway, así que se hablan por HTTP y no
    por invocación Lambda directa. Es la misma técnica del ejemplo de la
    clínica, donde pacientes consulta a triajes antes de borrar.

    Devuelve None si falla: quien llama decide qué hacer. En el flujo de repaso
    la calificación ya está guardada antes de llegar aquí, así que un fallo solo
    retrasa la actualización del progreso.
    """
    import urllib.error
    import urllib.request

    if not base_url:
        print("AVISO: falta la URL del servicio destino")
        return None

    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    # Secreto compartido: marca la llamada como interna, para que estos
    # endpoints no queden expuestos a cualquiera que conozca la URL.
    request.add_header("X-Internal-Key", os.environ.get("INTERNAL_KEY", ""))

    try:
        with urllib.request.urlopen(request, timeout=timeout) as raw:
            body = raw.read()
            return json.loads(body) if body else {}
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR llamando a {url}: {exc!r}")
        return None


def internal_only(func):
    """Protege un endpoint interno con el secreto compartido."""

    def wrapper(event, context=None):
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        expected = os.environ.get("INTERNAL_KEY", "")
        if not expected or headers.get("x-internal-key") != expected:
            return error(403, "FORBIDDEN", "Llamada interna no autorizada.")
        try:
            return func(event)
        except ApiError as exc:
            return error(exc.status, exc.code, exc.message, exc.details)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR no controlado en {func.__name__}: {exc!r}")
            return error(500, "INTERNAL_ERROR", "Ocurrió un error inesperado.")

    return wrapper
