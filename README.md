# SkillPath — API (Backend / Microservicios)

Backend de **SkillPath**, una app de microlearning activo (flashcards con repetición
espaciada, quizzes y seguimiento de progreso) para personas que están cursando una
especialización, bootcamp, maestría o materia universitaria.

Curso **Cloud Computing** — Maestría en Ciencia de Datos e Inteligencia Artificial (CDIA V5),
UTEC Posgrado. Docente: Oscar Mejía.

Frontend: [web-skill_path](https://github.com/VaneBuQ/web-skill_path)

## Arquitectura

Cinco microservicios independientes sobre **AWS Lambda + Amazon DynamoDB**, patrón
**database-per-service**: cada servicio tiene sus propias tablas y ningún rol IAM le da
acceso a las de otro.

| Microservicio | Responsabilidad | Tablas propias | Historias |
|---|---|---|---|
| `auth-service` | Registro e inicio de sesión | `users` | 9, 10 |
| `topics-service` | Catálogo de temas y "Mis temas" | `topics`, `user-topics` | 1 |
| `flashcards-service` | Tarjetas y repetición espaciada | `flashcards`, `user-card-reviews` | 2, 3 |
| `progress-service` | Progreso por tema, racha y XP | `user-progress` | 4, 5, 11 |
| `quiz-service` | Generación y calificación de quizzes | `quiz-attempts` | 6 |

Los servicios que necesitan datos de otro **no leen su tabla: invocan al servicio dueño**
(`flashcards → progress`, `quiz → flashcards`, `quiz → progress`).

## Tecnologías

- **Python 3.11** · handlers AWS Lambda (sin framework web: API Gateway ya hace el routing)
- **Amazon API Gateway HTTP API** con authorizer Lambda que valida JWT
- **Amazon DynamoDB** bajo demanda, una o más tablas por microservicio
- **AWS SAM** como infraestructura como código
- `pytest` + `moto` para pruebas; colección de **Postman** generada desde los mismos escenarios

## Estructura

```
api-skill_path/
├── template.yaml              # infraestructura: 7 tablas, HTTP API, 6 Lambdas
├── samconfig.toml             # parámetros de despliegue por entorno
├── Makefile
├── shared/                    # Lambda layer con el código común
│   └── python/skillpath_common/
│       ├── rules.py           # SM-2, "dominado", racha, XP, reglas del quiz
│       ├── router.py          # despacho HTTP + llamadas entre servicios
│       ├── errors.py          # catálogo de errores de la API
│       ├── tokens.py          # emisión y validación de JWT
│       ├── passwords.py       # PBKDF2-SHA256
│       ├── db.py  invoke.py  dates.py  ids.py  http.py
├── services/
│   ├── authorizer/            # valida el JWT en el borde
│   ├── auth_service/  topics_service/  flashcards_service/
│   ├── progress_service/  quiz_service/
├── seed/                      # catálogo de temas y flashcards
├── scripts/
│   ├── seed.py                # carga la semilla (cardCount derivado)
│   └── generate_postman.py    # colección Postman desde los escenarios de pytest
├── tests/
│   ├── unit/                  # lógica y contratos, sin AWS
│   └── e2e/                   # contra una API desplegada
└── docs/postman/
```

## Ejecución local

```bash
make install     # crea .venv e instala dependencias
make test        # pruebas unitarias — no necesita AWS ni credenciales
make lint
```

Para desplegar hacen falta [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
y [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html):

```bash
aws ssm put-parameter --name /skillpath/dev/jwt-secret --type SecureString \
    --value "$(openssl rand -hex 32)"
make deploy
make seed
```

## Catálogo de APIs

Todas las rutas van bajo la URL base que devuelve el output `ApiBaseUrl` del stack.
Salvo las marcadas como públicas, exigen `Authorization: Bearer <token>`.

| Servicio | Método | Endpoint | Descripción |
|---|---|---|---|
| auth | POST | `/auth/register` | Crea una cuenta y devuelve el token · *público* |
| auth | POST | `/auth/login` | Valida credenciales y devuelve el token · *público* |
| auth | GET | `/auth/me` | Perfil del usuario autenticado |
| topics | GET | `/topics` | Catálogo de temas, con búsqueda · *público* |
| topics | POST | `/topics/{topicId}/follow` | Agrega el tema a "Mis temas" |
| topics | DELETE | `/topics/{topicId}/follow` | Quita el tema de "Mis temas" |
| topics | GET | `/me/topics` | Temas que sigue el usuario |
| flashcards | GET | `/flashcards/{topicId}` | Tarjetas que tocan hoy en ese tema |
| flashcards | POST | `/flashcards/{cardId}/review` | Registra la calificación y reprograma |
| progress | GET | `/progress` | Resumen global (racha, XP) + progreso de todos los temas |
| progress | GET | `/progress/{topicId}` | Progreso en un tema |
| quiz | POST | `/quiz/{topicId}/start` | Genera un quiz de 10 preguntas |
| quiz | POST | `/quiz/{quizId}/submit` | Califica y devuelve el puntaje |
| quiz | GET | `/quiz/{quizId}` | Consulta un intento |

Las decisiones de diseño detrás de este catálogo están en
[`docs/01-correcciones-y-decisiones.md`](../docs/01-correcciones-y-decisiones.md).

## Cómo contribuir

1. Rama desde `main` con el prefijo del tipo de cambio y el microservicio afectado:
   - `feature/auth-service-nombre-corto`
   - `bugfix/quiz-service-nombre-corto`
2. Commits con **Conventional Commits**: `tipo(microservicio): descripción breve en presente`.
3. `make test` y `make lint` en verde antes de abrir el PR.
4. Incluir evidencia de pruebas cuando el cambio afecte un endpoint.
5. Revisión de al menos un integrante antes del merge a `main`.

| Tipo | Cuándo usarlo | Ejemplo |
|---|---|---|
| `feat` | Nueva funcionalidad | `feat(flashcards-service): agregar endpoint de repetición espaciada` |
| `fix` | Corrección de un bug | `fix(auth-service): corregir expiración del token` |
| `docs` | Solo documentación | `docs(readme): documentar variables de entorno` |
| `style` | Formato de código | `style(progress-service): aplicar linter` |
| `refactor` | Ni bug ni función nueva | `refactor(quiz-service): extraer lógica de puntaje a un helper` |
| `test` | Agregar o corregir pruebas | `test(topics-service): cubrir el catálogo ordenado` |
| `chore` | Mantenimiento | `chore: actualizar dependencias` |

## Equipo

- Grace Selenia Moscosso Flores
- Débora Elsa Jerónimo Balcázar
- Vanessa Elizabeth Burbano Quintero
- Miguel Ángel Valdivia Bambarén
