# Microservicio de Quiz

API REST para el examen de autoevaluación por tema.

Creado con Claude Opus 5 el 27 de septiembre de 2026.

## Funcionalidades

- Generar un examen de 10 preguntas de opción múltiple sobre los conceptos ya estudiados.
- Calificar el examen; con 7 aciertos de 10 el tema queda dominado.
- Consultar un intento, en curso o ya enviado.

## Endpoints

- `POST /quiz/{topicId}/start` — genera el examen
- `POST /quiz/{quizId}/submit` — califica y devuelve el resultado
- `GET /quiz/{quizId}` — consulta un intento

## Base de datos

- `quiz-attempts-<stage>` — PK `userId`, SK `quizId`

## Decisiones de diseño

- El examen exige 10 conceptos **estudiados**, no 10 tarjetas en el mazo: evalúa lo que el usuario ha repasado.
- Alterna dos formas de pregunta: «Dado el concepto X, elige la definición correcta» y «Dada la definición Y, elige el concepto correcto». Así no se memoriza la posición de la respuesta.
- La respuesta correcta se guarda con el intento y nunca se envía al cliente hasta que el examen se entrega.
- Las preguntas sin responder cuentan como incorrectas: al agotarse los 6 minutos el examen se envía automáticamente en vez de invalidarse.
- Una condición de escritura impide que el mismo examen se envíe dos veces.

## Despliegue automático

Requiere Node.js y Serverless Framework:

```bash
npm install -g serverless
```

> ⚠️ Este servicio llama a `flashcards` y `progress`, así que hay que desplegarlos **antes** y pasarle sus URLs.

Cambia `org: deborajeronimo` en `serverless.yml` por tu cuenta de Serverless Dashboard, o elimina las líneas `org:` y `app:` para desplegar sin Dashboard.

Desde la carpeta de este microservicio:

```bash
serverless deploy --param="jwtSecret=..." --param="internalKey=..." --param="flashcardsApiBase=..." --param="progressApiBase=..."
```

### Parámetros

| Parámetro | Qué es |
|---|---|
| `jwtSecret` | Secreto de los tokens. |
| `internalKey` | Secreto de las llamadas entre servicios. |
| `flashcardsApiBase` | URL del microservicio de tarjetas. |
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
