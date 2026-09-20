"""Reglas de negocio de SkillPath.

Están aquí, fuera de los handlers, porque varios servicios necesitan la misma
definición: `flashcards-service` decide cuándo una tarjeta pasa a dominada y
`progress-service` cuenta cuántas lo están. Si cada uno tuviera su propia copia,
los porcentajes dejarían de cuadrar.

Ninguna de estas reglas venía en los documentos originales; se definieron al
resolver las observaciones #9, #10 y #19.
"""

# --- Repetición espaciada (SM-2 simplificado) · observación #9 ---------------

EASE_INITIAL = 2.5
EASE_MIN = 1.3
EASE_MAX = 2.8

RATINGS = ("forgot", "hard", "easy")

# Una tarjeta está dominada cuando se recordó 3 veces y ya se espació 3 semanas.
# Es el criterio de «tarjeta madura» estándar en repetición espaciada.
MASTERED_MIN_REPETITIONS = 3
MASTERED_MIN_INTERVAL_DAYS = 21

# --- Experiencia · observación #1 --------------------------------------------

XP_PER_CARD = 5      # 8 tarjetas pendientes = 40 XP («+40 XP disponibles hoy»)
XP_PER_QUIZ = 120    # fijo al completar, como anuncia el prototipo

# --- Quiz · observaciones #8 y #10 -------------------------------------------

QUIZ_QUESTION_COUNT = 10
QUIZ_OPTIONS_PER_QUESTION = 4
# El umbral cuenta tarjetas ESTUDIADAS por el usuario, no tarjetas del mazo.
QUIZ_MIN_STUDIED_CONCEPTS = 10
QUIZ_TIME_LIMIT_SECONDS = 360  # 6 minutos, como dice el prototipo


def clamp_ease(ease: float) -> float:
    return max(EASE_MIN, min(EASE_MAX, round(ease, 2)))


def is_mastered(repetitions: int, interval_days: int) -> bool:
    return (
        repetitions >= MASTERED_MIN_REPETITIONS
        and interval_days >= MASTERED_MIN_INTERVAL_DAYS
    )


def state_for(repetitions: int, interval_days: int, reviewed: bool = True) -> str:
    """Estado de una tarjeta: new / learning / mastered."""
    if not reviewed:
        return "new"
    if is_mastered(repetitions, interval_days):
        return "mastered"
    return "learning"


def schedule(rating: str, *, repetitions: int, interval_days: int, ease: float) -> dict:
    """Aplica SM-2 y devuelve el nuevo estado de programación de la tarjeta.

    No toca la base de datos ni conoce fechas: recibe el estado anterior y
    devuelve el siguiente. Así se puede probar exhaustivamente sin AWS.
    """
    if rating not in RATINGS:
        raise ValueError(f"Calificación desconocida: {rating!r}")

    if rating == "forgot":
        # Vuelve al principio y reaparece hoy mismo.
        repetitions = 0
        interval_days = 0
        ease = clamp_ease(ease - 0.20)
        lapse = 1
    elif rating == "hard":
        repetitions += 1
        interval_days = max(1, round(interval_days * 1.2))
        ease = clamp_ease(ease - 0.15)
        lapse = 0
    else:  # easy
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


# --- Racha · observación #1 ---------------------------------------------------

def next_streak(current: int, last_study_date: str | None, today: str, yesterday: str) -> int:
    """Racha tras registrar estudio hoy.

    Se llama solo cuando el usuario efectivamente estudió.
    """
    if last_study_date == today:
        return current or 1     # ya contaba hoy; no se suma dos veces
    if last_study_date == yesterday:
        return current + 1
    return 1                     # primer día, o se rompió la racha


def streak_as_read(current: int, last_study_date: str | None, today: str, yesterday: str) -> int:
    """Racha tal como debe mostrarse al leerla.

    HU5 pide que la racha se reinicie a 0 si el usuario no estudió el día
    anterior. Calcularlo en la lectura evita tener que correr un proceso
    nocturno que recorra a todos los usuarios.
    """
    if not last_study_date:
        return 0
    if last_study_date in (today, yesterday):
        return current
    return 0
