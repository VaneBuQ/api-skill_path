# SkillPath — Catálogo de APIs

> **Este archivo se genera.** No lo edites a mano: cambia `infra/spec.py`
> o `scripts/generate_api_catalog.py` y ejecuta `make api-catalog`.

21 endpoints repartidos en 5 microservicios.

---

## Convenciones

**Base URL.** La URL de invocación de la etapa en API Gateway:
`https://{apiId}.execute-api.us-east-1.amazonaws.com/{stage}`

**Autenticación.** `auth-service` emite un JWT (HS256, 24 h) con el `userId`
en el claim `sub`. Salvo tres rutas públicas, todas exigen la cabecera
`Authorization: Bearer <token>`, que valida un autorizador de API Gateway
antes de llegar al servicio.

**El `userId` nunca viaja en la URL.** Todo recurso del usuario cuelga de
`/me`, y el identificador sale del token. Así no existe forma de pedir los
datos de otra persona cambiando la ruta.

**Formato de error.** Todos los códigos ≥400 devuelven el mismo envelope:

```json
{
  "error": {
    "code": "NOT_ENOUGH_CONCEPTS",
    "message": "Necesitas estudiar al menos 10 conceptos. Llevas 7 en Estructuras de Datos.",
    "details": { "studied": 7, "required": 10, "topicName": "Estructuras de Datos" }
  },
  "requestId": "b3f1e0c2-..."
}
```

`message` está en español y es apto para mostrarse al usuario tal cual, así
que el frontend no traduce códigos. `requestId` es el de API Gateway y sirve
para encontrar la petición en CloudWatch.

**Errores transversales**, posibles en cualquier ruta:

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Cuerpo o parámetros inválidos; `details.fields` los enumera |
| 401 | `UNAUTHENTICATED` | Falta el token, o está vencido o manipulado |
| 403 | `FORBIDDEN` | El recurso no pertenece al usuario |
| 404 | `NOT_FOUND` | El recurso no existe |
| 429 | `RATE_LIMITED` | Límite de peticiones de API Gateway |
| 500 | `INTERNAL_ERROR` | Error inesperado; no filtra detalles al cliente |

**Formatos.** Instantes en ISO-8601 UTC (`2026-09-21T14:30:00Z`); fechas de
calendario como `YYYY-MM-DD`. Los identificadores llevan prefijo: `usr_`,
`crd_`, `qz_`, `deck_`. La racha y el «repaso de hoy» se calculan en
**America/Lima (UTC-5)**: con UTC, la racha se rompería a las 19:00 hora local.

---

## Resumen

| Servicio | Endpoints | Tablas propias | Historias |
|---|---|---|---|
| `auth-service` | 3 | `users` | 9, 10 |
| `topics-service` | 11 | `topics`, `user-topics` | 1, 8 |
| `flashcards-service` | 2 | `flashcards`, `user-card-reviews` | 2, 3 |
| `progress-service` | 2 | `user-progress` | 4, 5, 11 |
| `quiz-service` | 3 | `quiz-attempts` | 6 |

Los servicios que necesitan datos de otro **no leen su tabla: invocan al
servicio dueño**. Ningún rol de IAM da acceso de escritura a una tabla ajena.

| Origen | Destino | Para qué |
|---|---|---|
| `flashcards-service` | `progress-service` | Actualizar el progreso tras un repaso |
| `quiz-service` | `flashcards-service` | Obtener las tarjetas y generar las preguntas |
| `quiz-service` | `progress-service` | Sumar el XP del quiz |
| `topics-service` | `flashcards-service` | Crear y borrar las tarjetas de un mazo propio |
| `topics-service` | `progress-service` | Limpiar el progreso de un mazo eliminado |

---

## `auth-service`

Registro e inicio de sesión (historias 9 y 10)

- **`users`** — tabla propia. PK `userId`

### `POST /auth/register` · **público**

Crea una cuenta y devuelve el token

**Petición**

```json
{
  "name": "Lucía Mendoza",
  "email": "lucia@universidad.edu",
  "password": "Secreta123"
}
```

**Respuesta 201**

```json
{
  "userId": "usr_01J9X...",
  "name": "Lucía Mendoza",
  "email": "lucia@universidad.edu",
  "initials": "LM",
  "token": "eyJhbGciOi...",
  "expiresIn": 86400,
  "createdAt": "2026-09-21T14:30:00Z"
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Correo mal formado, contraseña de menos de 8 caracteres o nombre vacío |
| 409 | `EMAIL_ALREADY_EXISTS` | Ese correo ya está registrado |

### `POST /auth/login` · **público**

Valida credenciales y devuelve el token

**Petición**

```json
{
  "email": "lucia@universidad.edu",
  "password": "Secreta123"
}
```

**Respuesta 200**

```json
{
  "userId": "usr_01J9X...",
  "name": "Lucía Mendoza",
  "email": "lucia@universidad.edu",
  "initials": "LM",
  "token": "eyJhbGciOi...",
  "expiresIn": 86400
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Falta el correo o la contraseña |
| 401 | `INVALID_CREDENTIALS` | Mensaje genérico: no revela si falló el correo o la contraseña |

### `GET /auth/me`

Perfil del usuario autenticado

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `NOT_FOUND` | El token es válido pero la cuenta ya no existe |

---

## `topics-service`

Catálogo, «Mis temas» y mazos propios (historias 1 y 8)

- **`topics`** — tabla propia. PK `topicId`
- **`user-topics`** — tabla propia. PK `userId` · SK `topicId`

### `GET /topics` · **público**

Catálogo de temas, con búsqueda

**Respuesta 200**

```json
{
  "items": [
    {
      "topicId": "algebra-lineal",
      "name": "Álgebra lineal",
      "description": "Matrices, determinantes...",
      "cardCount": 12,
      "icon": "atom",
      "level": "intermedio"
    }
  ]
}
```

### `POST /topics/{topicId}/follow`

Agrega el tema a «Mis temas»

**Respuesta 201 · 200 si ya lo seguía**

```json
{
  "topicId": "algebra-lineal",
  "name": "Álgebra lineal",
  "cardCount": 12,
  "followedAt": "2026-09-21T14:31:00Z",
  "alreadyFollowing": false
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `TOPIC_NOT_FOUND` | El tema no existe, o es un mazo privado de otra persona |

### `DELETE /topics/{topicId}/follow`

Quita el tema de «Mis temas»

**Respuesta 204** — sin contenido.

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `NOT_FOUND` | El usuario no sigue ese tema |
| 409 | `OWN_DECK_CANNOT_UNFOLLOW` | Un mazo propio se elimina, no se deja de seguir |

### `GET /me/topics`

Temas que sigue el usuario

**Respuesta 200**

```json
{
  "items": [
    {
      "topicId": "algebra-lineal",
      "name": "Álgebra lineal",
      "cardCount": 12,
      "icon": "atom",
      "isOwn": false,
      "followedAt": "2026-09-12T10:00:00Z"
    }
  ]
}
```

### `POST /me/decks`

Crea un mazo propio con sus tarjetas

**Petición**

```json
{
  "name": "Apuntes de Cloud Computing",
  "description": "Lo que entró en el parcial",
  "cards": [
    {
      "question": "¿Qué es IaC?",
      "answer": "Definir la infraestructura en archivos versionados.",
      "hint": "No tiene que ver con la Parte C."
    }
  ]
}
```

**Respuesta 201**

```json
{
  "topicId": "deck_01J9XYZ...",
  "name": "Apuntes de Cloud Computing",
  "description": "Lo que entró en el parcial",
  "cardCount": 1,
  "icon": "book-open",
  "isOwn": true,
  "createdAt": "2026-09-21T19:00:00Z"
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Falta el nombre o no hay ninguna tarjeta completa |
| 503 | `DECK_CREATION_FAILED` | No se pudieron guardar las tarjetas |

### `GET /me/decks`

Lista los mazos propios del usuario

### `GET /me/decks/{topicId}`

Detalle de un mazo propio con sus tarjetas

**Respuesta 200**

```json
{
  "topicId": "deck_01J9XYZ...",
  "name": "Apuntes de Cloud Computing",
  "cardCount": 3,
  "cards": [
    {
      "cardId": "crd_0001",
      "question": "¿Qué es IaC?",
      "answer": "Definir la infraestructura...",
      "hint": "No tiene que ver con la Parte C."
    }
  ]
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `NOT_FOUND` | El mazo no existe o no es del usuario |

### `PATCH /me/decks/{topicId}`

Renombra un mazo propio

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Nombre vacío o demasiado largo |
| 404 | `NOT_FOUND` | El mazo no existe o no es del usuario |

### `DELETE /me/decks/{topicId}`

Elimina un mazo propio

**Respuesta 204** — sin contenido.

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `NOT_FOUND` | El mazo no existe o no es del usuario |

### `POST /me/decks/{topicId}/cards`

Agrega una tarjeta al mazo

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Tarjeta sin pregunta o sin respuesta |
| 404 | `NOT_FOUND` | El mazo no existe o no es del usuario |
| 503 | `CARD_CREATION_FAILED` | No se pudieron guardar las tarjetas |

### `DELETE /me/decks/{topicId}/cards/{cardId}`

Elimina una tarjeta

**Respuesta 204** — sin contenido.

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `NOT_FOUND` | El mazo o la tarjeta no existen |

---

## `flashcards-service`

Tarjetas y repetición espaciada (historias 2 y 3)

- **`flashcards`** — tabla propia. PK `topicId` · SK `cardId`
- **`user-card-reviews`** — tabla propia. PK `userId` · SK `topicCardId`
- **`user-topics`** — solo lectura, es de topics-service. PK `userId` · SK `topicId`

### `GET /flashcards/{topicId}`

Tarjetas que tocan hoy en ese tema

**Respuesta 200**

```json
{
  "topicId": "algebra-lineal",
  "topicName": "Álgebra lineal",
  "dueCount": 12,
  "cardsTotal": 12,
  "cardsMastered": 0,
  "xpAvailable": 60,
  "items": [
    {
      "cardId": "crd_0001",
      "question": "¿Cuándo una matriz es invertible?",
      "answer": "Cuando su determinante es distinto de cero.",
      "hint": "determinante ≠ 0...",
      "position": 1,
      "state": "new"
    }
  ]
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 403 | `NOT_FOLLOWING_TOPIC` | El usuario no sigue ese tema |

### `POST /flashcards/{cardId}/review`

Registra la calificación y reprograma

**Petición**

```json
{
  "topicId": "algebra-lineal",
  "rating": "easy"
}
```

**Respuesta 200**

```json
{
  "cardId": "crd_0001",
  "topicId": "algebra-lineal",
  "rating": "easy",
  "repetitions": 1,
  "easeFactor": 2.6,
  "intervalDays": 1,
  "nextReviewDate": "2026-09-22",
  "state": "learning",
  "xpAwarded": 5,
  "remainingDue": 11,
  "progress": {
    "cardsTotal": 12,
    "cardsMastered": 0,
    "percent": 0,
    "xpTotal": 5,
    "streakDays": 1
  }
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Falta `topicId`, que es parte de la clave de la tarjeta |
| 400 | `INVALID_RATING` | La calificación no es forgot, hard ni easy |
| 403 | `NOT_FOLLOWING_TOPIC` | El usuario no sigue ese tema |
| 404 | `CARD_NOT_FOUND` | La tarjeta no existe en ese tema |

---

## `progress-service`

Progreso por tema, racha y XP (historias 4, 5 y 11)

- **`user-progress`** — tabla propia. PK `userId` · SK `topicId`

### `GET /progress`

Resumen global (racha, XP) y progreso de todos los temas

**Respuesta 200**

```json
{
  "summary": {
    "streakDays": 12,
    "longestStreakDays": 19,
    "xpTotal": 2480,
    "studiedToday": true,
    "masteryPercent": 58,
    "cardsMastered": 73,
    "cardsTotal": 124
  },
  "items": [
    {
      "topicId": "algebra-lineal",
      "topicName": "Álgebra lineal",
      "cardsTotal": 36,
      "cardsMastered": 24,
      "cardsPending": 12,
      "percent": 67,
      "lastStudiedAt": "2026-09-12T18:20:00Z"
    }
  ]
}
```

### `GET /progress/{topicId}`

Progreso en un tema

**Respuesta 200**

```json
{
  "topicId": "algebra-lineal",
  "topicName": "Álgebra lineal",
  "cardsTotal": 36,
  "cardsMastered": 24,
  "cardsPending": 12,
  "percent": 67,
  "lastStudiedAt": "2026-09-12T18:20:00Z"
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `PROGRESS_NOT_FOUND` | El usuario aún no ha repasado nada en ese tema |

---

## `quiz-service`

Generación y calificación de quizzes (historia 6)

- **`quiz-attempts`** — tabla propia. PK `userId` · SK `quizId`
- **`user-topics`** — solo lectura, es de topics-service. PK `userId` · SK `topicId`

### `POST /quiz/{topicId}/start`

Genera un quiz de 10 preguntas

**Respuesta 201**

```json
{
  "quizId": "qz_01J9XYZ...",
  "topicId": "estructuras-de-datos",
  "topicName": "Estructuras de Datos",
  "questionCount": 10,
  "timeLimitSeconds": 360,
  "xpReward": 120,
  "basedOnConcepts": 24,
  "startedAt": "2026-09-21T15:00:00Z",
  "questions": [
    {
      "questionId": "q1",
      "position": 1,
      "prompt": "¿Qué estructura sigue el principio LIFO?",
      "options": [
        { "key": "A", "text": "La cola..." },
        { "key": "B", "text": "La pila..." }
      ]
    }
  ]
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 403 | `NOT_FOLLOWING_TOPIC` | El usuario no sigue ese tema |
| 409 | `NOT_ENOUGH_CONCEPTS` | Menos de 10 conceptos estudiados; `details` trae `studied`, `required` y `topicName` |

### `POST /quiz/{quizId}/submit`

Califica y devuelve el puntaje

**Petición**

```json
{
  "answers": [
    { "questionId": "q1", "selected": "B" }
  ],
  "durationSeconds": 214
}
```

**Respuesta 200**

```json
{
  "quizId": "qz_01J9XYZ...",
  "score": 80,
  "correctCount": 8,
  "total": 10,
  "xpAwarded": 120,
  "timedOut": false,
  "submittedAt": "2026-09-21T15:06:00Z",
  "results": [
    {
      "questionId": "q1",
      "cardId": "crd_0031",
      "selected": "B",
      "correctKey": "B",
      "correct": true
    }
  ],
  "conceptsToReview": [
    {
      "cardId": "crd_0044",
      "concept": "Complejidad de tablas hash"
    }
  ]
}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `UNKNOWN_QUESTION` | Una respuesta no pertenece a este quiz |
| 404 | `QUIZ_NOT_FOUND` | El quiz no existe o es de otro usuario |
| 409 | `QUIZ_ALREADY_SUBMITTED` | El quiz ya fue enviado |

### `GET /quiz/{quizId}`

Consulta un intento

| HTTP | `code` | Cuándo |
|---|---|---|
| 404 | `QUIZ_NOT_FOUND` | El quiz no existe o es de otro usuario |

---

## Todos los endpoints

| Método | Ruta | Servicio | Auth |
|---|---|---|---|
| `POST` | `/auth/login` | `auth-service` | — |
| `GET` | `/auth/me` | `auth-service` | JWT |
| `POST` | `/auth/register` | `auth-service` | — |
| `POST` | `/flashcards/{cardId}/review` | `flashcards-service` | JWT |
| `GET` | `/flashcards/{topicId}` | `flashcards-service` | JWT |
| `GET` | `/me/decks` | `topics-service` | JWT |
| `POST` | `/me/decks` | `topics-service` | JWT |
| `DELETE` | `/me/decks/{topicId}` | `topics-service` | JWT |
| `GET` | `/me/decks/{topicId}` | `topics-service` | JWT |
| `PATCH` | `/me/decks/{topicId}` | `topics-service` | JWT |
| `POST` | `/me/decks/{topicId}/cards` | `topics-service` | JWT |
| `DELETE` | `/me/decks/{topicId}/cards/{cardId}` | `topics-service` | JWT |
| `GET` | `/me/topics` | `topics-service` | JWT |
| `GET` | `/progress` | `progress-service` | JWT |
| `GET` | `/progress/{topicId}` | `progress-service` | JWT |
| `GET` | `/quiz/{quizId}` | `quiz-service` | JWT |
| `POST` | `/quiz/{quizId}/submit` | `quiz-service` | JWT |
| `POST` | `/quiz/{topicId}/start` | `quiz-service` | JWT |
| `GET` | `/topics` | `topics-service` | — |
| `DELETE` | `/topics/{topicId}/follow` | `topics-service` | JWT |
| `POST` | `/topics/{topicId}/follow` | `topics-service` | JWT |

