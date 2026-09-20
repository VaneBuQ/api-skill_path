"""Catálogo de errores de la API.

Todos los servicios devuelven el mismo envelope:

    {"error": {"code": ..., "message": ..., "details": {...}}, "requestId": ...}

`message` está en español y es apto para mostrarse al usuario tal cual.
"""


class ApiError(Exception):
    """Error de negocio que se traduce a una respuesta HTTP.

    Los handlers lanzan estas excepciones y el decorador `@handler` las convierte
    en respuestas; nunca hay que construir la respuesta de error a mano.
    """

    status = 500
    code = "INTERNAL_ERROR"
    message = "Ocurrió un error inesperado."

    def __init__(self, message=None, details=None, code=None, status=None):
        self.message = message or self.message
        self.details = details
        if code:
            self.code = code
        if status:
            self.status = status
        super().__init__(self.message)

    def to_dict(self):
        error = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


# --- Transversales -----------------------------------------------------------

class ValidationError(ApiError):
    status = 400
    code = "VALIDATION_ERROR"
    message = "Los datos enviados no son válidos."


class Unauthenticated(ApiError):
    status = 401
    code = "UNAUTHENTICATED"
    message = "Necesitas iniciar sesión."


class Forbidden(ApiError):
    status = 403
    code = "FORBIDDEN"
    message = "No tienes acceso a este recurso."


class NotFound(ApiError):
    status = 404
    code = "NOT_FOUND"
    message = "No se encontró el recurso."


class Conflict(ApiError):
    status = 409
    code = "CONFLICT"
    message = "La operación entra en conflicto con el estado actual."


# --- auth-service ------------------------------------------------------------

class EmailAlreadyExists(Conflict):
    code = "EMAIL_ALREADY_EXISTS"
    message = "Ese correo ya está registrado."


class InvalidCredentials(ApiError):
    status = 401
    code = "INVALID_CREDENTIALS"
    # HU10: el mensaje NO debe revelar si falló el correo o la contraseña.
    message = "Correo o contraseña incorrectos."


# --- topics-service ----------------------------------------------------------

class TopicNotFound(NotFound):
    code = "TOPIC_NOT_FOUND"
    message = "El tema no existe."


class NotFollowingTopic(Forbidden):
    code = "NOT_FOLLOWING_TOPIC"
    message = "Primero agrega este tema a «Mis temas»."


# --- flashcards-service ------------------------------------------------------

class CardNotFound(NotFound):
    code = "CARD_NOT_FOUND"
    message = "La tarjeta no existe."


class InvalidRating(ValidationError):
    code = "INVALID_RATING"
    message = "La calificación debe ser «forgot», «hard» o «easy»."


# --- progress-service --------------------------------------------------------

class ProgressNotFound(NotFound):
    code = "PROGRESS_NOT_FOUND"
    message = "Todavía no tienes progreso en este tema."


# --- quiz-service ------------------------------------------------------------

class NotEnoughConcepts(Conflict):
    code = "NOT_ENOUGH_CONCEPTS"
    message = "Necesitas estudiar más conceptos para generar el quiz."


class QuizNotFound(NotFound):
    code = "QUIZ_NOT_FOUND"
    message = "El quiz no existe."


class QuizAlreadySubmitted(Conflict):
    code = "QUIZ_ALREADY_SUBMITTED"
    message = "Este quiz ya fue enviado."


class IncompleteAnswers(ValidationError):
    code = "INCOMPLETE_ANSWERS"
    message = "Faltan respuestas por enviar."
