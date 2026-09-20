# SkillPath — Guía de despliegue manual en AWS

> **Este archivo se genera.** No lo edites a mano: cambia `infra/spec.py`
> y vuelve a ejecutar `make deploy-guide`. Las pruebas leen esa misma
> especificación, así que la guía y el código no pueden contradecirse.

Región: **us-east-1** (N. Virginia) · Entorno: **dev**

## Orden de trabajo

1. Crear las **7 tablas** de DynamoDB (§1)
2. Guardar el **secreto del JWT** (§2)
3. Crear las **6 funciones** Lambda y subir su .zip (§3)
4. Crear la **HTTP API** y sus rutas (§4)
5. Cargar los **datos semilla** (§5)
6. **Comprobar** que todo responde (§6)

Las funciones se crean antes que la API porque la API necesita
seleccionarlas, y las tablas antes que las funciones porque sus nombres
van en las variables de entorno.

---

## §1 · Tablas de DynamoDB

DynamoDB → Tablas → **Crear tabla**, una por cada una. En todas:
**Personalizar la configuración** → Capacidad de lectura/escritura →
**Bajo demanda**. Así no se paga nada mientras nadie use la app.

---

### 1. `skillpath-dev-users`

Dueño: **auth-service**

| Campo | Valor |
|---|---|
| Nombre de la tabla | `skillpath-dev-users` |
| Clave de partición | `userId` · S (String) |
| Clave de ordenación | *(ninguna)* |
| Configuración | **Personalizar** → Capacidad **Bajo demanda** |
| Recuperación a un punto anterior | Activada |

> Sin índice por correo: la búsqueda va por un ítem centinela "EMAIL#<correo>" en esta misma tabla, que además impone la unicidad. Un índice secundario sería de consistencia eventual y quien acaba de registrarse podría fallar al iniciar sesión.

*Atributos que guarda:* email, name, passwordHash, authProvider, createdAt

---

### 2. `skillpath-dev-topics`

Dueño: **topics-service**

| Campo | Valor |
|---|---|
| Nombre de la tabla | `skillpath-dev-topics` |
| Clave de partición | `topicId` · S (String) |
| Clave de ordenación | *(ninguna)* |
| Configuración | **Personalizar** → Capacidad **Bajo demanda** |
| Recuperación a un punto anterior | Activada |

**Índice secundario global `catalog-index`**

| Campo | Valor |
|---|---|
| Clave de partición | `visibility` · String |
| Clave de ordenación | `name` · String |
| Atributos proyectados | **Todos** |

> Devuelve el catálogo ordenado por nombre sin hacer Scan. visibility vale "public" para el catálogo y "private" para los mazos que crea el usuario (historia 8), que por lo tanto nunca aparecen aquí.

*Atributos que guarda:* name, description, cardCount, icon, level, visibility, ownerId, createdAt

---

### 3. `skillpath-dev-user-topics`

Dueño: **topics-service**

| Campo | Valor |
|---|---|
| Nombre de la tabla | `skillpath-dev-user-topics` |
| Clave de partición | `userId` · S (String) |
| Clave de ordenación | `topicId` · String |
| Configuración | **Personalizar** → Capacidad **Bajo demanda** |
| Recuperación a un punto anterior | Activada |

> topicName, cardCount e icon van denormalizados porque DynamoDB no tiene JOIN: sin ellos, pintar «Mis temas» exigiría un GetItem por tema.

*Atributos que guarda:* followedAt, topicName, cardCount, icon, isOwn

---

### 4. `skillpath-dev-flashcards`

Dueño: **flashcards-service**

| Campo | Valor |
|---|---|
| Nombre de la tabla | `skillpath-dev-flashcards` |
| Clave de partición | `topicId` · S (String) |
| Clave de ordenación | `cardId` · String |
| Configuración | **Personalizar** → Capacidad **Bajo demanda** |
| Recuperación a un punto anterior | Activada |

> La clave es compuesta, así que para leer una tarjeta hacen falta topicId Y cardId: por eso POST /flashcards/{cardId}/review exige topicId en el cuerpo (observación #5).

*Atributos que guarda:* question, answer, hint, position, difficulty, createdAt

---

### 5. `skillpath-dev-user-card-reviews`

Dueño: **flashcards-service**

| Campo | Valor |
|---|---|
| Nombre de la tabla | `skillpath-dev-user-card-reviews` |
| Clave de partición | `userId` · S (String) |
| Clave de ordenación | `topicCardId` · String |
| Configuración | **Personalizar** → Capacidad **Bajo demanda** |
| Recuperación a un punto anterior | Activada |

> La SK es "topicId#cardId", no solo cardId: con la clave del informe original no se podían consultar las pendientes de UN tema sin leer las de todos (observación #4).

**Índice secundario global `due-index`**

| Campo | Valor |
|---|---|
| Clave de partición | `userTopicKey` · String |
| Clave de ordenación | `nextReviewDate` · String |
| Atributos proyectados | **Todos** |

> La consulta principal de la app: tarjetas de este usuario en este tema que vencen hoy o antes. Devuelve exactamente esas, sin filtrar en memoria (observación #4).

*Atributos que guarda:* topicId, cardId, nextReviewDate, lastReviewedAt, easeFactor, intervalDays, repetitions, lapses, lastRating, state, userTopicKey

---

### 6. `skillpath-dev-user-progress`

Dueño: **progress-service**

| Campo | Valor |
|---|---|
| Nombre de la tabla | `skillpath-dev-user-progress` |
| Clave de partición | `userId` · S (String) |
| Clave de ordenación | `topicId` · String |
| Configuración | **Personalizar** → Capacidad **Bajo demanda** |
| Recuperación a un punto anterior | Activada |

> La SK es el topicId salvo un ítem especial "#STATS" por usuario que guarda racha y XP (observación #1). Como "#" ordena antes que cualquier letra, una sola Query trae estadísticas y todos los temas.

*Atributos que guarda:* topicName, cardsTotal, cardsMastered, cardsPending, lastStudiedAt · y en el ítem #STATS: streakDays, longestStreakDays, lastStudyDate, xpTotal. El porcentaje NO se guarda: se calcula al leer, porque un valor derivado y almacenado acaba desviándose de lo que resume.

---

### 7. `skillpath-dev-quiz-attempts`

Dueño: **quiz-service**

| Campo | Valor |
|---|---|
| Nombre de la tabla | `skillpath-dev-quiz-attempts` |
| Clave de partición | `userId` · S (String) |
| Clave de ordenación | `quizId` · String |
| Configuración | **Personalizar** → Capacidad **Bajo demanda** |
| Recuperación a un punto anterior | Activada |

> quizId es un ULID, ordenable por tiempo, así que Query(userId) devuelve el historial en orden cronológico sin índice adicional.

**Índice secundario global `topic-attempt-index`**

| Campo | Valor |
|---|---|
| Clave de partición | `userTopicKey` · String |
| Clave de ordenación | `startedAt` · String |
| Atributos proyectados | **Solo los siguientes**: `score`, `status`, `topicId` |

> Último intento por tema, sin recorrer el historial completo.

*Atributos que guarda:* topicId, topicName, status, questions, answers, score, correctCount, total, startedAt, expiresAt, submittedAt, durationSeconds, xpAwarded

---

## §2 · Secreto del JWT

Las funciones firman y validan los tokens con un secreto compartido.
Genera uno con:

```bash
openssl rand -hex 32
```

Guárdalo en **Systems Manager → Parameter Store → Crear parámetro**:

| Campo | Valor |
|---|---|
| Nombre | `/skillpath/dev/jwt-secret` |
| Tipo | **SecureString** |
| Valor | el resultado del comando |

Luego copia ese mismo valor en la variable `JWT_SECRET` de **las seis**
funciones. Si una tiene un secreto distinto, rechazará todos los tokens.

> El secreto nunca se guarda en el repositorio.

---

## §3 · Funciones Lambda

Primero genera los paquetes:

```bash
make package
```

Luego, por cada función: Lambda → **Crear función** → *Crear desde cero*,
con los valores de abajo. El código se sube en **Código → Cargar desde →
Archivo .zip**.

---

### 1. `skillpath-dev-authorizer`

Valida el JWT y entrega el userId a los demás servicios

| Campo | Valor |
|---|---|
| Nombre | `skillpath-dev-authorizer` |
| Tiempo de ejecución | python3.11 |
| Arquitectura | arm64 |
| Memoria | 128 MB |
| Tiempo de espera | 5 s |
| Controlador (Handler) | `app.lambda_handler` |
| Código | subir `dist/authorizer.zip` |

**Variables de entorno**

| Clave | Valor |
|---|---|
| `STAGE` | `dev` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGIN` | `<dominio de CloudFront, o http://localhost:5173 en dev>` |
| `JWT_SECRET` | `<el mismo secreto en todas las funciones>` |

> ⚠️ No le des acceso a ninguna otra tabla. Que cada función solo alcance
> las suyas es lo que hace real el patrón *database-per-service*.

---

### 2. `skillpath-dev-auth-service`

Registro e inicio de sesión (historias 9 y 10)

| Campo | Valor |
|---|---|
| Nombre | `skillpath-dev-auth-service` |
| Tiempo de ejecución | python3.11 |
| Arquitectura | arm64 |
| Memoria | 256 MB |
| Tiempo de espera | 10 s |
| Controlador (Handler) | `app.lambda_handler` |
| Código | subir `dist/auth-service.zip` |

**Variables de entorno**

| Clave | Valor |
|---|---|
| `STAGE` | `dev` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGIN` | `<dominio de CloudFront, o http://localhost:5173 en dev>` |
| `JWT_SECRET` | `<el mismo secreto en todas las funciones>` |
| `USERS_TABLE` | `skillpath-dev-users` |

**Permisos del rol de ejecución** (IAM → Roles → el rol de esta función)

| Recurso | Acciones de DynamoDB |
|---|---|
| `skillpath-dev-users` | GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems |

> ⚠️ No le des acceso a ninguna otra tabla. Que cada función solo alcance
> las suyas es lo que hace real el patrón *database-per-service*.

---

### 3. `skillpath-dev-topics-service`

Catálogo, «Mis temas» y mazos propios (historias 1 y 8)

| Campo | Valor |
|---|---|
| Nombre | `skillpath-dev-topics-service` |
| Tiempo de ejecución | python3.11 |
| Arquitectura | arm64 |
| Memoria | 256 MB |
| Tiempo de espera | 10 s |
| Controlador (Handler) | `app.lambda_handler` |
| Código | subir `dist/topics-service.zip` |

**Variables de entorno**

| Clave | Valor |
|---|---|
| `STAGE` | `dev` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGIN` | `<dominio de CloudFront, o http://localhost:5173 en dev>` |
| `JWT_SECRET` | `<el mismo secreto en todas las funciones>` |
| `TOPICS_TABLE` | `skillpath-dev-topics` |
| `USER_TOPICS_TABLE` | `skillpath-dev-user-topics` |
| `FLASHCARDS_FUNCTION` | `skillpath-dev-flashcards-service` |
| `PROGRESS_FUNCTION` | `skillpath-dev-progress-service` |

**Permisos del rol de ejecución** (IAM → Roles → el rol de esta función)

| Recurso | Acciones de DynamoDB |
|---|---|
| `skillpath-dev-topics` | GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems |
| `skillpath-dev-user-topics` | GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems |

Además necesita `lambda:InvokeFunction` sobre: `skillpath-dev-flashcards-service`, `skillpath-dev-progress-service`

> ⚠️ No le des acceso a ninguna otra tabla. Que cada función solo alcance
> las suyas es lo que hace real el patrón *database-per-service*.

---

### 4. `skillpath-dev-flashcards-service`

Tarjetas y repetición espaciada (historias 2 y 3)

| Campo | Valor |
|---|---|
| Nombre | `skillpath-dev-flashcards-service` |
| Tiempo de ejecución | python3.11 |
| Arquitectura | arm64 |
| Memoria | 256 MB |
| Tiempo de espera | 10 s |
| Controlador (Handler) | `app.lambda_handler` |
| Código | subir `dist/flashcards-service.zip` |

**Variables de entorno**

| Clave | Valor |
|---|---|
| `STAGE` | `dev` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGIN` | `<dominio de CloudFront, o http://localhost:5173 en dev>` |
| `JWT_SECRET` | `<el mismo secreto en todas las funciones>` |
| `FLASHCARDS_TABLE` | `skillpath-dev-flashcards` |
| `USER_CARD_REVIEWS_TABLE` | `skillpath-dev-user-card-reviews` |
| `USER_TOPICS_TABLE` | `skillpath-dev-user-topics` |
| `PROGRESS_FUNCTION` | `skillpath-dev-progress-service` |

**Permisos del rol de ejecución** (IAM → Roles → el rol de esta función)

| Recurso | Acciones de DynamoDB |
|---|---|
| `skillpath-dev-flashcards` | GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems |
| `skillpath-dev-user-card-reviews` | GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems |
| `skillpath-dev-user-topics` | GetItem, Query, Scan — tabla de *topics-service*, solo lectura |

Además necesita `lambda:InvokeFunction` sobre: `skillpath-dev-progress-service`

> ⚠️ No le des acceso a ninguna otra tabla. Que cada función solo alcance
> las suyas es lo que hace real el patrón *database-per-service*.

---

### 5. `skillpath-dev-progress-service`

Progreso por tema, racha y XP (historias 4, 5 y 11)

| Campo | Valor |
|---|---|
| Nombre | `skillpath-dev-progress-service` |
| Tiempo de ejecución | python3.11 |
| Arquitectura | arm64 |
| Memoria | 256 MB |
| Tiempo de espera | 10 s |
| Controlador (Handler) | `app.lambda_handler` |
| Código | subir `dist/progress-service.zip` |

**Variables de entorno**

| Clave | Valor |
|---|---|
| `STAGE` | `dev` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGIN` | `<dominio de CloudFront, o http://localhost:5173 en dev>` |
| `JWT_SECRET` | `<el mismo secreto en todas las funciones>` |
| `USER_PROGRESS_TABLE` | `skillpath-dev-user-progress` |

**Permisos del rol de ejecución** (IAM → Roles → el rol de esta función)

| Recurso | Acciones de DynamoDB |
|---|---|
| `skillpath-dev-user-progress` | GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems |

> ⚠️ No le des acceso a ninguna otra tabla. Que cada función solo alcance
> las suyas es lo que hace real el patrón *database-per-service*.

---

### 6. `skillpath-dev-quiz-service`

Generación y calificación de quizzes (historia 6)

| Campo | Valor |
|---|---|
| Nombre | `skillpath-dev-quiz-service` |
| Tiempo de ejecución | python3.11 |
| Arquitectura | arm64 |
| Memoria | 256 MB |
| Tiempo de espera | 15 s |
| Controlador (Handler) | `app.lambda_handler` |
| Código | subir `dist/quiz-service.zip` |

**Variables de entorno**

| Clave | Valor |
|---|---|
| `STAGE` | `dev` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGIN` | `<dominio de CloudFront, o http://localhost:5173 en dev>` |
| `JWT_SECRET` | `<el mismo secreto en todas las funciones>` |
| `QUIZ_ATTEMPTS_TABLE` | `skillpath-dev-quiz-attempts` |
| `USER_TOPICS_TABLE` | `skillpath-dev-user-topics` |
| `FLASHCARDS_FUNCTION` | `skillpath-dev-flashcards-service` |
| `PROGRESS_FUNCTION` | `skillpath-dev-progress-service` |

**Permisos del rol de ejecución** (IAM → Roles → el rol de esta función)

| Recurso | Acciones de DynamoDB |
|---|---|
| `skillpath-dev-quiz-attempts` | GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems |
| `skillpath-dev-user-topics` | GetItem, Query, Scan — tabla de *topics-service*, solo lectura |

Además necesita `lambda:InvokeFunction` sobre: `skillpath-dev-flashcards-service`, `skillpath-dev-progress-service`

> ⚠️ No le des acceso a ninguna otra tabla. Que cada función solo alcance
> las suyas es lo que hace real el patrón *database-per-service*.

---

## §4 · HTTP API

API Gateway → **Crear API** → **HTTP API** (no REST API: cuesta 3.5 veces
más y el costeo del informe usa el precio de HTTP API). Nombre: `skillpath-dev`.

### 4.1 CORS

| Campo | Valor |
|---|---|
| Access-Control-Allow-Origin | `http://localhost:5173` en desarrollo; el dominio de CloudFront en producción |
| Access-Control-Allow-Headers | `authorization`, `content-type` |
| Access-Control-Allow-Methods | `GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS` |
| Access-Control-Max-Age | 600 |

### 4.2 Autorizador

Autorización → **Crear autorizador** → **Lambda**:

| Campo | Valor |
|---|---|
| Nombre | `jwt-authorizer` |
| Función Lambda | `skillpath-dev-authorizer` |
| Versión del formato de carga | **2.0** |
| Respuestas de autorizador simples | **Activado** |
| Origen de identidad | `$request.header.Authorization` |
| Almacenar en caché | 300 segundos |

> Las respuestas simples hacen que el autorizador devuelva `isAuthorized`
> en vez de una política IAM completa, que es lo que espera el código.

### 4.3 Rutas

21 rutas. Todas con integración **Lambda** hacia la función indicada.
En la columna *Autorizador*, `jwt-authorizer` significa que hay que
adjuntarlo en Rutas → la ruta → Autorización.

| Método | Ruta | Integración | Autorizador | Qué hace |
|---|---|---|---|---|
| `POST` | `/auth/login` | `skillpath-dev-auth-service` | — *(pública)* | Valida credenciales y devuelve el token |
| `GET` | `/auth/me` | `skillpath-dev-auth-service` | `jwt-authorizer` | Perfil del usuario autenticado |
| `POST` | `/auth/register` | `skillpath-dev-auth-service` | — *(pública)* | Crea una cuenta y devuelve el token |
| `POST` | `/flashcards/{cardId}/review` | `skillpath-dev-flashcards-service` | `jwt-authorizer` | Registra la calificación y reprograma |
| `GET` | `/flashcards/{topicId}` | `skillpath-dev-flashcards-service` | `jwt-authorizer` | Tarjetas que tocan hoy en ese tema |
| `GET` | `/me/decks` | `skillpath-dev-topics-service` | `jwt-authorizer` | Lista los mazos propios del usuario |
| `POST` | `/me/decks` | `skillpath-dev-topics-service` | `jwt-authorizer` | Crea un mazo propio con sus tarjetas |
| `DELETE` | `/me/decks/{topicId}` | `skillpath-dev-topics-service` | `jwt-authorizer` | Elimina un mazo propio |
| `GET` | `/me/decks/{topicId}` | `skillpath-dev-topics-service` | `jwt-authorizer` | Detalle de un mazo propio con sus tarjetas |
| `PATCH` | `/me/decks/{topicId}` | `skillpath-dev-topics-service` | `jwt-authorizer` | Renombra un mazo propio |
| `POST` | `/me/decks/{topicId}/cards` | `skillpath-dev-topics-service` | `jwt-authorizer` | Agrega una tarjeta al mazo |
| `DELETE` | `/me/decks/{topicId}/cards/{cardId}` | `skillpath-dev-topics-service` | `jwt-authorizer` | Elimina una tarjeta |
| `GET` | `/me/topics` | `skillpath-dev-topics-service` | `jwt-authorizer` | Temas que sigue el usuario |
| `GET` | `/progress` | `skillpath-dev-progress-service` | `jwt-authorizer` | Resumen global (racha, XP) y progreso de todos los temas |
| `GET` | `/progress/{topicId}` | `skillpath-dev-progress-service` | `jwt-authorizer` | Progreso en un tema |
| `GET` | `/quiz/{quizId}` | `skillpath-dev-quiz-service` | `jwt-authorizer` | Consulta un intento |
| `POST` | `/quiz/{quizId}/submit` | `skillpath-dev-quiz-service` | `jwt-authorizer` | Califica y devuelve el puntaje |
| `POST` | `/quiz/{topicId}/start` | `skillpath-dev-quiz-service` | `jwt-authorizer` | Genera un quiz de 10 preguntas |
| `GET` | `/topics` | `skillpath-dev-topics-service` | — *(pública)* | Catálogo de temas, con búsqueda |
| `DELETE` | `/topics/{topicId}/follow` | `skillpath-dev-topics-service` | `jwt-authorizer` | Quita el tema de «Mis temas» |
| `POST` | `/topics/{topicId}/follow` | `skillpath-dev-topics-service` | `jwt-authorizer` | Agrega el tema a «Mis temas» |

> Solo tres rutas son públicas: registrarse, iniciar sesión y ver el
> catálogo. Si olvidas adjuntar el autorizador a cualquier otra, esa ruta
> queda abierta a Internet.

### 4.4 Etapa

Crea la etapa **`dev`** con implementación automática activada.
La URL de invocación resultante es la que va en `VITE_API_BASE_URL` del frontend.

---

## §5 · Datos semilla

Con las tablas ya creadas y las credenciales de AWS configuradas:

```bash
make seed
```

Carga los 6 temas del catálogo y sus tarjetas. El `cardCount` se calcula
a partir de las tarjetas realmente insertadas, nunca se teclea.

---

## §6 · Comprobación

Sustituye `<URL>` por la URL de invocación de la etapa:

```bash
curl -s <URL>/topics
```

Debe devolver los 6 temas. Luego crea una cuenta:

```bash
curl -s -X POST <URL>/auth/register -H 'Content-Type: application/json' -d '{"name":"Prueba","email":"prueba@uni.edu","password":"Secreta123"}'
```

Debe devolver `201` con un `token`. Con ese token, una ruta protegida:

```bash
curl -s <URL>/me/topics -H 'Authorization: Bearer <TOKEN>'
```

Si responde `401`, revisa que el autorizador esté adjunto a la ruta y que
`JWT_SECRET` sea idéntico en las seis funciones.

---

## Problemas frecuentes

| Síntoma | Causa más probable |
|---|---|
| `500` en todas las rutas de un servicio | Falta una variable de entorno con el nombre de una tabla |
| `401` con un token recién emitido | `JWT_SECRET` distinto entre funciones |
| `403 AccessDeniedException` en los logs | Al rol de la función le falta el permiso sobre esa tabla |
| El repaso funciona pero el progreso no cambia | Falta `lambda:InvokeFunction` de flashcards-service sobre progress-service |
| El navegador bloquea las llamadas | CORS: el origen configurado no coincide con el del frontend |
| `Internal Server Error` sin logs | El handler no es `app.lambda_handler`, o el .zip tiene una carpeta de más dentro |

