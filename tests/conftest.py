"""Arranque de las pruebas.

Los handlers leen las variables de entorno y crean el cliente de DynamoDB al
importarse, así que todo eso debe estar puesto antes del primer import.
"""

import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("JWT_SECRET", "secreto-solo-para-pruebas")
os.environ.setdefault("INTERNAL_KEY", "interno-solo-para-pruebas")
