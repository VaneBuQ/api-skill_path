"""Authorizer de API Gateway.

Valida el JWT una sola vez, en el borde, y entrega el `userId` ya resuelto a
todos los microservicios. Es lo que permite que ninguna ruta lleve el userId en
la URL (observación #3): los handlers lo leen del contexto de la petición, no
del path, así que no existe forma de pedir los datos de otro usuario.

Usa respuestas simples (`EnableSimpleResponses: true`), así que devuelve
`isAuthorized` en vez de una política IAM completa.
"""

import logging

from skillpath_common.errors import Unauthenticated
from skillpath_common.tokens import from_header

logger = logging.getLogger()
logger.setLevel("INFO")

DENY = {"isAuthorized": False}


def lambda_handler(event, context=None):
    headers = event.get("headers") or {}
    # API Gateway normaliza los nombres de header a minúsculas.
    authorization = headers.get("authorization") or headers.get("Authorization")

    try:
        claims = from_header(authorization)
    except Unauthenticated as exc:
        logger.info("authorizer_denied reason=%s", exc.code)
        return DENY
    except Exception:
        logger.exception("authorizer_error")
        return DENY

    return {
        "isAuthorized": True,
        # Lo que aquí se ponga llega a los handlers en
        # event.requestContext.authorizer.lambda
        "context": {
            "userId": claims["sub"],
            "email": claims.get("email", ""),
            "name": claims.get("name", ""),
        },
    }
