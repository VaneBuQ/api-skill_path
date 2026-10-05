# SkillPath — API (Backend / Microservicios)

Backend de **SkillPath**, una app de microlearning activo: flashcards con repetición
espaciada, comprobación de respuestas escritas con IA, examen de autoevaluación y
seguimiento del progreso.

Curso **Cloud Computing** — Maestría en Ciencia de Datos e Inteligencia Artificial
(CDIA V5), UTEC Posgrado. Docente: Oscar Mejía.

Frontend: [web-skill_path](https://github.com/VaneBuQ/web-skill_path)

---

## Arquitectura

**Seis microservicios independientes**, cada uno con su propio API Gateway, sus funciones
Lambda y sus tablas de DynamoDB. Se despliegan por separado con **Serverless Framework**.

| Microservicio | Qué hace | Tablas propias | Rutas |
|---|---|---|---|
| `auth` | Registro, inicio de sesión y perfil | `users` | 3 |
| `topics` | Catálogo, «Mis temas» y mazos propios | `topics-catalog`, `topics-user` | 11 |
| `flashcards` | Tarjetas del día y repetición espaciada | `cards`, `reviews` | 2 + 7 internas |
| `progress` | Progreso por tema, racha y XP | `progress` | 2 + 3 internas |
| `quiz` | Examen de autoevaluación | `attempts` | 3 |
| `ia` | Comprueba la respuesta escrita del usuario | `checks` | 2 |

Los servicios que necesitan datos de otro **no leen su tabla: le piden por HTTP**, igual
que en el proyecto de ejemplo de la clínica. Los endpoints internos van protegidos con un
secreto compartido (`X-Internal-Key`), porque cada API Gateway es público.

```
flashcards ──> progress      actualizar el progreso tras un repaso
quiz       ──> flashcards    obtener las tarjetas y generar preguntas
quiz       ──> progress      marcar el tema como dominado
topics     ──> flashcards    crear y borrar tarjetas de un mazo propio
topics     ──> progress      limpiar el progreso de un mazo eliminado
ia         ──> flashcards    obtener la respuesta correcta de la tarjeta
```

## Tecnologías

- **Python 3.13** sobre AWS Lambda, una función por endpoint
- **Amazon API Gateway** (HTTP API), uno por microservicio
- **Amazon DynamoDB**, bajo demanda
- **Serverless Framework** para automatizar el despliegue
- **API de Groq (GPT-OSS 120B, capa gratuita)** para evaluar las respuestas escritas

**Sin dependencias externas.** Los `requirements.txt` están vacíos a propósito: el JWT se
firma con `hmac`, las contraseñas con `hashlib` y las llamadas HTTP con `urllib`, todo de
la librería estándar. Así no hace falta empaquetar nada ni usar Docker.

---

## Estructura

```
api-skill_path/
├── shared/common.py          código común: fuente única
├── scripts/
│   ├── sync-common.sh        lo copia a cada servicio
│   └── seed.py               carga el catálogo de temas
├── seed/                     temas y tarjetas iniciales
├── services/
│   ├── auth/         handler.py · serverless.yml · requirements.txt · README.md
│   ├── topics/
│   ├── flashcards/
│   ├── progress/
│   ├── quiz/
│   └── ia/
└── tests/                    pruebas con DynamoDB simulado
```

`common.py` se copia a cada servicio porque en este patrón no hay Lambda Layers: cada
servicio se empaqueta solo con lo que hay en su carpeta.

---

## Antes de desplegar

### 1. Herramientas

```bash
npm install -g serverless
```

También necesitas las credenciales de AWS configuradas (`aws configure`, o las variables
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y `AWS_SESSION_TOKEN` si usas Learner Lab).

### 2. Cambia la cuenta de Serverless Dashboard

Los `serverless.yml` traen `org: deborajeronimo`. **Cámbialo por tu cuenta** en los seis
archivos, o elimina las líneas `org:` y `app:` si prefieres desplegar sin Dashboard:

```bash
sed -i '' 's/^org: deborajeronimo$/org: TU-CUENTA/' services/*/serverless.yml
```

### 3. El rol de IAM

Todas las funciones usan el rol `LabRole`, que ya existe en las cuentas de AWS Academy
Learner Lab. Si tu cuenta no lo tiene, crea un rol con permisos para Lambda, API Gateway,
DynamoDB y CloudFormation, y cambia el nombre en los seis `serverless.yml`.

### 4. Prepara los tres secretos

| Parámetro | Qué es | Cómo obtenerlo |
|---|---|---|
| `jwtSecret` | Firma los tokens de sesión | `openssl rand -hex 32` |
| `internalKey` | Autoriza las llamadas entre servicios | `openssl rand -hex 32` |
| `aiApiKey` | **Tu clave de la API de Groq** | [console.groq.com](https://console.groq.com) → API Keys (gratis, sin tarjeta) |

> ### 🔑 Dónde va tu clave de la API de Groq
>
> **Solo en la línea de comandos, al desplegar el servicio `ia`:**
>
> ```bash
> serverless deploy --param="aiApiKey=gsk_..."
> ```
>
> Serverless la guarda como variable de entorno de la función Lambda. **No la escribas en
> ningún archivo del repositorio**: no hay ningún `.env` ni ninguna línea en los
> `serverless.yml` donde ponerla, y es a propósito.
>
> Si prefieres no teclearla cada vez, expórtala en tu terminal antes de desplegar:
>
> ```bash
> export AI_KEY="gsk_..."
> serverless deploy --param="aiApiKey=$AI_KEY"
> ```
>
> Sin esa clave, todo funciona menos el botón «Comprobar con IA», que responde
> «La comprobación con IA no está configurada».

El `jwtSecret` y el `internalKey` **deben ser idénticos en los seis servicios**. Si uno
difiere, ese servicio rechazará todos los tokens o todas las llamadas internas.

---

## Despliegue

Los servicios se llaman entre sí por URL, así que **el orden importa**: cada uno necesita
las URLs de los que ya están desplegados. Guarda la URL que imprime cada despliegue.

```bash
export JWT="$(openssl rand -hex 32)"
export INTERNAL="$(openssl rand -hex 32)"
export AI_KEY="gsk_..."   # tu clave
```

```bash
./scripts/sync-common.sh
```

### 1 · progress (no depende de nadie)

```bash
cd services/progress && serverless deploy --param="jwtSecret=$JWT" --param="internalKey=$INTERNAL"
```

Copia la URL: `export PROGRESS_URL="https://..."`

### 2 · flashcards (necesita progress)

```bash
cd services/flashcards && serverless deploy --param="jwtSecret=$JWT" --param="internalKey=$INTERNAL" --param="progressApiBase=$PROGRESS_URL"
```

Copia la URL: `export FLASHCARDS_URL="https://..."`

### 3 · auth (no depende de nadie)

```bash
cd services/auth && serverless deploy --param="jwtSecret=$JWT"
```

### 4 · topics (necesita flashcards y progress)

```bash
cd services/topics && serverless deploy --param="jwtSecret=$JWT" --param="internalKey=$INTERNAL" --param="flashcardsApiBase=$FLASHCARDS_URL" --param="progressApiBase=$PROGRESS_URL"
```

### 5 · quiz (necesita flashcards y progress)

```bash
cd services/quiz && serverless deploy --param="jwtSecret=$JWT" --param="internalKey=$INTERNAL" --param="flashcardsApiBase=$FLASHCARDS_URL" --param="progressApiBase=$PROGRESS_URL"
```

### 6 · ia (necesita flashcards y tu clave)

```bash
cd services/ia && serverless deploy --param="jwtSecret=$JWT" --param="internalKey=$INTERNAL" --param="flashcardsApiBase=$FLASHCARDS_URL" --param="aiApiKey=$AI_KEY"
```

### 7 · Carga los datos iniciales

**Este paso no es opcional.** Sin él las tablas quedan vacías y la aplicación
parece rota aunque los seis servicios respondan: «Explorar» no muestra ningún
tema, no hay tarjetas que repasar, el progreso se queda en cero y el quiz nunca
se habilita porque exige 10 conceptos estudiados. Todo con la misma causa.

```bash
STAGE=dev python3 scripts/seed.py
```

Carga 6 temas con 12 tarjetas cada uno (72 en total). Para comprobar que
entraron, sin abrir la consola de AWS:

```bash
curl -s "$TOPICS_URL/topics" | python3 -m json.tool | head -20
```

Si devuelve `{"items": []}`, la semilla no se cargó: revisa que las credenciales
de AWS Academy sigan vigentes (caducan al cerrar el laboratorio) y vuelve a
ejecutarla. Es idempotente, se puede repetir sin duplicar nada.

### 8 · Anota las seis URLs

Las necesitas para configurar el frontend. Si las pierdes:

```bash
cd services/auth && serverless info
```

---

## Pruebas y evidencia en Postman

Los escenarios de extremo a extremo se declaran **una sola vez**, en
`tests/e2e/scenarios.py`, y se usan de tres formas que no pueden desincronizarse:

| | Qué hace |
|---|---|
| `make test` | Los ejecuta **en memoria** contra los seis handlers, con DynamoDB simulado y las rutas tomadas de los `serverless.yml` |
| `make postman` | Los convierte en la colección que pide la rúbrica |
| `make test-live` | Los ejecuta por HTTP contra las APIs desplegadas |

Es decir: **la colección de Postman queda verificada antes de desplegar nada**, y si un
endpoint cambia sin actualizar el escenario, `make test` falla.

```bash
make install
```

```bash
make test
```

**No necesita AWS, credenciales ni la clave de la IA** — la llamada al modelo se
simula. Son 53 pasos repartidos en 5 escenarios: cuenta y catálogo, repaso con IA, examen
de dominio, mazos propios y seguridad.

### La colección de Postman

```bash
make postman
```

Genera `docs/postman/SkillPath.postman_collection.json`. Al importarla en Postman:

1. Rellena las **seis variables** de URL: `authUrl`, `topicsUrl`, `flashcardsUrl`,
   `progressUrl`, `quizUrl` e `iaUrl`, con lo que imprimió cada `serverless deploy`.
   Sin barra final.
2. Ejecútala con **Collection Runner**, no petición por petición: los escenarios van en
   orden y cada uno continúa la sesión del anterior.
3. Para volver a ejecutarla, cambia la variable `email`: el primer paso crea una cuenta y
   el correo no se puede repetir.

El paso «Comprobar una respuesta escrita con IA» llama al modelo de verdad y cuesta una
fracción de céntimo.

### Contra las APIs desplegadas

```bash
AUTH_URL=https://... TOPICS_URL=https://... FLASHCARDS_URL=https://... PROGRESS_URL=https://... QUIZ_URL=https://... IA_URL=https://... make test-live
```

Si esos 53 pasos pasan contra AWS, el backend está bien desplegado.

---

## Catálogo de APIs

Todas las rutas exigen `Authorization: Bearer <token>` salvo las marcadas como públicas.

### auth

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/auth/register` | Crea una cuenta y devuelve el token · *público* |
| `POST` | `/auth/login` | Valida credenciales y devuelve el token · *público* |
| `GET` | `/auth/me` | Perfil del usuario autenticado |

### topics

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/topics` | Catálogo de temas, con búsqueda · *público* |
| `POST` | `/topics/{topicId}/follow` | Agrega el tema a «Mis temas» |
| `DELETE` | `/topics/{topicId}/follow` | Quita el tema de «Mis temas» |
| `GET` | `/me/topics` | Temas que sigue el usuario |
| `POST` | `/me/decks` | Crea un mazo propio con sus tarjetas |
| `GET` | `/me/decks` | Lista los mazos propios |
| `GET` | `/me/decks/{topicId}` | Detalle de un mazo con sus tarjetas |
| `PATCH` | `/me/decks/{topicId}` | Renombra un mazo propio |
| `DELETE` | `/me/decks/{topicId}` | Elimina el mazo y todo lo derivado |
| `POST` | `/me/decks/{topicId}/cards` | Agrega tarjetas al mazo |
| `DELETE` | `/me/decks/{topicId}/cards/{cardId}` | Elimina una tarjeta |

### flashcards

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/flashcards/{topicId}` | Tarjetas que tocan hoy. Acepta `?cardIds=` para repasar errores |
| `POST` | `/flashcards/{cardId}/review` | Registra la calificación. Requiere `topicId` en el cuerpo |

### progress

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/progress` | Resumen global (racha, XP) y progreso de todos los temas |
| `GET` | `/progress/{topicId}` | Progreso en un tema |

### quiz

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/quiz/{topicId}/start` | Genera un examen de 10 preguntas |
| `POST` | `/quiz/{quizId}/submit` | Califica; con 7 aciertos el tema queda dominado |
| `GET` | `/quiz/{quizId}` | Consulta un intento |

### ia

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/ia/check-answer` | Evalúa la respuesta escrita contra la correcta |
| `GET` | `/ia/history/{topicId}` | Historial de comprobaciones del usuario |

---

## Problemas frecuentes

| Síntoma | Causa más probable |
|---|---|
| `401` con un token recién emitido | El `jwtSecret` no es idéntico en los seis servicios |
| `403 FORBIDDEN` en una llamada interna | El `internalKey` no coincide entre servicios |
| «Explorar» dice «El catálogo está vacío» | No se ejecutó el paso 7, `scripts/seed.py` |
| No hay nada que repasar y el quiz nunca se habilita | Lo mismo: sin catálogo no hay tarjetas que estudiar |
| El repaso funciona pero el progreso no cambia | Falta `--param="progressApiBase=..."` en flashcards. La aplicación ahora lo avisa en pantalla durante el repaso |
| El examen da `503 QUIZ_GENERATION_FAILED` | Falta `--param="flashcardsApiBase=..."` en quiz |
| «La comprobación con IA no está configurada» | Falta `--param="aiApiKey=..."` en ia |
| El navegador bloquea las llamadas | El servicio no se desplegó con `httpApi: cors: true` |
| `ImportError: No module named common` | Ejecuta `./scripts/sync-common.sh` antes de desplegar |

> Para saber **cuál** de las seis URLs está mal, abre «Configuración» en la
> aplicación web y pulsa **Probar conexión**: prueba las seis y dice si cada una
> responde, no responde, o responde pero es la URL de otro microservicio —el
> error más fácil de cometer pegando seis URLs casi idénticas.

---

## Cómo contribuir

Ramas `feature/<servicio>-<nombre>` o `bugfix/<servicio>-<nombre>`, y commits con
**Conventional Commits** usando el microservicio como scope:

| Tipo | Ejemplo |
|---|---|
| `feat` | `feat(ia): limitar la respuesta a 60 palabras` |
| `fix` | `fix(auth): corregir la expiración del token` |
| `docs` | `docs(readme): documentar el orden de despliegue` |
| `test` | `test(quiz): cubrir el umbral de 7 de 10` |
| `chore` | `chore: actualizar dependencias` |

## Equipo

- Grace Selenia Moscosso Flores
- Débora Elsa Jerónimo Balcázar
- Vanessa Elizabeth Burbano Quintero
- Miguel Ángel Valdivia Bambarén
