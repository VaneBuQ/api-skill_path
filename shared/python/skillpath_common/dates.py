"""Fechas y horas en la zona del usuario.

Todo el cálculo de rachas y de «tarjetas que tocan hoy» se hace en
America/Lima (UTC-5). Si se usara UTC, la racha de un usuario peruano se
rompería a las 19:00 hora local, que es cuando más se estudia.
"""

from datetime import UTC, date, datetime, timedelta, timezone

# Perú no aplica horario de verano, así que un offset fijo es correcto y evita
# depender de la base de datos de zonas horarias dentro de Lambda.
LIMA = timezone(timedelta(hours=-5), name="America/Lima")

DATE_FMT = "%Y-%m-%d"


def now() -> datetime:
    """Instante actual en hora de Lima."""
    return datetime.now(LIMA)


def today() -> date:
    """Fecha de calendario actual en Lima."""
    return now().date()


def today_str() -> str:
    return today().strftime(DATE_FMT)


def yesterday_str() -> str:
    return (today() - timedelta(days=1)).strftime(DATE_FMT)


def to_iso(moment: datetime | None = None) -> str:
    """Timestamp ISO-8601 en UTC, que es como se guarda todo instante."""
    moment = moment or now()
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: str) -> date:
    return datetime.strptime(value, DATE_FMT).date()


def add_days(days: int, start: date | None = None) -> str:
    """Fecha de calendario resultante de sumar `days` días."""
    return ((start or today()) + timedelta(days=days)).strftime(DATE_FMT)


def is_due(next_review_date: str) -> bool:
    """¿Esta tarjeta toca hoy o ya venció?"""
    return next_review_date <= today_str()
