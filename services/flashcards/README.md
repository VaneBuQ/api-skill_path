# Microservicio de Tarjetas

API REST para el repaso diario con repetición espaciada.

Creado con Claude Opus 5 el 27 de septiembre de 2026.

## Funcionalidades

- Consultar las tarjetas que tocan hoy en un tema.
- Calificar una tarjeta y reprogramarla según la repetición espaciada.
- Limitar una sesión a tarjetas concretas, para repasar los errores del examen.

## Endpoints

- `GET /flashcards/{topicId}` — tarjetas del día, acepta `?cardIds=` y `?limit=`
- `POST /flashcards/{cardId}/review` — califica; requiere `topicId` en el cuerpo

- Endpoints internos, protegidos con `X-Internal-Key`:
- `POST /internal/cards` · `/internal/cards/list` · `/internal/cards/get`
- `POST /internal/cards/delete` · `/internal/cards/delete-topic`
- `POST /internal/reviews/delete-topic` · `/internal/reviews/studied`

## Base de datos

- `flashcards-cards-<stage>` — PK `topicId`, SK `cardId`
- `flashcards-reviews-<stage>` — PK `userId`, SK `topicId#cardId`

## Decisiones de diseño

- La clave de ordenación de las reviews combina el tema y la tarjeta en lugar de usar solo el identificador de la tarjeta: con esa última forma no se podrían consultar las pendientes de un tema sin leer las de todos los demás.
- Es la tabla que más se escribe —una vez por repaso—, así que no lleva ningún índice secundario, porque cada índice duplicaría esa escritura.
- Calificar una tarjeta cambia el progreso del tema, que vive en otro microservicio: se le comunica por HTTP. Los contadores viajan como valores absolutos y no como incrementos, de modo que perder una llamada no desvía las cifras.
- El algoritmo es una versión simplificada de SM-2. Una tarjeta se considera dominada cuando se recordó 3 veces y su intervalo llegó a 21 días.

## Despliegue automático

Requiere Node.js y Serverless Framework:

```bash
npm install -g serverless
```

> ⚠️ Este servicio llama a `progress`, así que hay que desplegarlos **antes** y pasarle sus URLs.

Cambia `org: deborajeronimo` en `serverless.yml` por tu cuenta de Serverless Dashboard, o elimina las líneas `org:` y `app:` para desplegar sin Dashboard.

Desde la carpeta de este microservicio:

```bash
serverless deploy --param="jwtSecret=..." --param="internalKey=..." --param="progressApiBase=..."
```

### Parámetros

| Parámetro | Qué es |
|---|---|
| `jwtSecret` | Secreto de los tokens. |
| `internalKey` | Secreto de las llamadas entre servicios. |
| `progressApiBase` | URL del microservicio de progreso. |

El rol de IAM `LabRole` debe existir en la cuenta; es el que traen las cuentas de AWS Academy Learner Lab.

## Prompt utilizado

Este microservicio forma parte de SkillPath, construido a partir del enunciado del Proyecto Parcial del curso. El prompt de referencia del proyecto de ejemplo usado como base para el patrón de despliegue es:

```
Rol/Persona: 
Actúa como un programador Full Stack.

Contexto: 
Una clínica necesita una web para registrar el triaje de sus pacientes.

Tarea/Objetivo: 
Crea una web responsiva con estas funcionalidades:
- Mantenimiento de Pacientes: Permite registrar los datos de un nuevo paciente (DNI, Nombres, Apellidos, Sexo (Masculino, Femenino), Fecha Nacimiento, Correo electrónico, Celular, Dirección, Distrito, Provincia, Departamento), modificar los datos de un paciente por su DNI, eliminar un paciente por su DNI validando que no tenga triajes registrados, buscar un paciente por su DNI y ver todos sus datos.
- Registro de Triaje: Se busca un paciente por su DNI, se muestra sus nombres y apellidos y se registra el triaje (Fecha y hora, Presión arterial, Frecuencia cardiaca, Saturación de óxigeno, Temperatura corporal, Peso en kilogramos y Talla en metros).
- Consulta de Triajes: Buscar triajes de un DNI, se muestra un listado de triajes encontrados (DNI, Fecha y hora) y poder ver el detalle de un triaje seleccionado.

Requisitos de la respuesta:
- Para la web responsiva (FrontEnd) utiliza sólo HTML + CSS + JavaScript. Utiliza el servicio S3 de AWS para alojar la web. Automatiza la creación de un bucket S3 público y el despliegue de la web con el framework serverless considerando el uso del rol de IAM LabRole existente.
- Para el BackEnd crea 2 microservicios o apis rest (pacientes y triajes). Utiliza estos servicios de AWS (Api Gateway, Lambda y DynamoDB) para cada microservicio. Utiliza lenguaje de programación python. Automatiza el despliegue de cada microservicio con el framework serverless considerando el uso del rol de IAM LabRole existente.
- Genera un readme.md para la web y para cada microservicio con las funcionalidades que contiene y todas las instrucciones para hacer el despliegue automático. Adicionalmente indica explícitamente que ha sido creado con GitHub Copilot y la fecha de creación e incluye como referencia todo el texto del prompt utilizado.

Elementos adicionales:
- Si es mucha información en pantalla de celular para el registro de un nuevo paciente, considera partirlo en pasos.
```
