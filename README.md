# SkillPath — API (Backend / Microservicios)

Backend de **SkillPath**, una app de microlearning activo (flashcards con repetición espaciada, quizzes y seguimiento de progreso) para personas que están cursando una especialización, bootcamp, maestría o materia universitaria.

Proyecto desarrollado para el curso **Cloud Computing** — Maestría en Ciencia de Datos e Inteligencia Artificial (CDIA V5), UTEC Posgrado.

Repositorio del frontend: [web-skill_path](https://github.com/VaneBuQ/web-skill_path)

## Arquitectura

Arquitectura de **microservicios independientes**, cada uno con su propia base de datos, desplegados en AWS como contenedores o funciones serverless.

| Microservicio | Responsabilidad | Historias de usuario que cubre |
|---|---|---|
| `auth-service` | Registro e inicio de sesión de usuarios | Historia 9, 10 |
| `topics-service` | Gestión de temas y mazos de estudio | Historia 1 |
| `flashcards-service` | Tarjetas de repaso y algoritmo de repetición espaciada | Historia 2, 3 |
| `progress-service` | Cálculo y consulta de progreso por tema | Historia 4 |
| `quiz-service` | Generación y calificación de quizzes de autoevaluación | Historia 6 |

*(Ajustar nombres/servicios según el diseño final de la Parte B.)*

## Tecnologías

- Python (FastAPI / Flask — completar según implementación)
- Contenedores Docker o AWS Lambda (serverless)
- Base de datos propia por microservicio (SQL o NoSQL, según Parte B)
- AWS (región y servicios definidos en el diagrama de arquitectura de la Parte B)
- Postman (evidencia de pruebas de cada microservicio)

## Catálogo de APIs

| Microservicio | Método | Endpoint | Descripción |
|---|---|---|---|
| auth-service | POST | `/auth/register` | Crea una cuenta nueva |
| auth-service | POST | `/auth/login` | Inicia sesión y devuelve token |
| topics-service | GET | `/topics` | Lista los temas disponibles |
| topics-service | POST | `/topics/{id}/follow` | Agrega un tema a "Mis temas" |
| flashcards-service | GET | `/flashcards/{topicId}` | Obtiene las tarjetas pendientes de repaso |
| flashcards-service | POST | `/flashcards/{cardId}/review` | Registra la calificación del repaso |
| progress-service | GET | `/progress/{topicId}` | Devuelve el progreso del usuario en un tema |
| quiz-service | POST | `/quiz/{topicId}/start` | Genera un quiz de opción múltiple |
| quiz-service | POST | `/quiz/{quizId}/submit` | Envía respuestas y devuelve el puntaje |

*(Completar/ajustar con los endpoints reales implementados.)*

## Estructura del proyecto

```
api-skill_path/
├── auth-service/
│   ├── app/
│   ├── Dockerfile
│   └── requirements.txt
├── topics-service/
├── flashcards-service/
├── progress-service/
├── quiz-service/
├── docs/
│   └── postman/          # colecciones de Postman como evidencia de pruebas
└── README.md
```

## Instalación y ejecución local

```bash
# clonar el repositorio
git clone https://github.com/VaneBuQ/api-skill_path.git
cd api-skill_path

# por cada microservicio, por ejemplo auth-service
cd auth-service
pip install -r requirements.txt
uvicorn app.main:app --reload
```

O usando Docker:

```bash
docker compose up --build
```


## Cómo contribuir

1. Crear una rama a partir de `main` con el prefijo del tipo de cambio y el microservicio afectado:
   - `feature/auth-service-nombre-corto` — nueva funcionalidad
   - `bugfix/quiz-service-nombre-corto` — corrección de un bug
2. Hacer commits siguiendo el estándar **Conventional Commits** (ver tabla abajo).
3. Incluir en el Pull Request evidencia de pruebas (captura o colección de Postman) cuando el cambio afecte un endpoint.
4. Esperar la revisión de al menos un integrante del equipo antes de hacer merge a `main`.

### Estructura de los commits

Formato: `tipo(microservicio): descripción breve en presente`

| Tipo | Cuándo usarlo | Ejemplo |
|---|---|---|
| `feat` | Nueva funcionalidad | `feat(flashcards-service): agregar endpoint de repetición espaciada` |
| `fix` | Corrección de un bug | `fix(auth-service): corregir expiración del token` |
| `docs` | Cambios solo de documentación | `docs(readme): documentar variables de entorno` |
| `style` | Formato de código (sin afectar lógica) | `style(progress-service): aplicar linter` |
| `refactor` | Cambio de código que no arregla un bug ni agrega función | `refactor(quiz-service): extraer lógica de puntaje a un helper` |
| `test` | Agregar o corregir pruebas | `test(topics-service): agregar colección de Postman` |
| `chore` | Mantenimiento (dependencias, Docker, CI) | `chore: actualizar Dockerfile de auth-service` |

## Equipo

- Nombre Apellido — rol
- Nombre Apellido — rol

## Curso

**Cloud Computing** — Maestría en Ciencia de Datos e Inteligencia Artificial (CDIA V5)
Docente: Oscar Mejía — UTEC Posgrado
