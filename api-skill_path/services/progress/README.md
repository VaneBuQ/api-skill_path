# Microservicio de Progreso

API REST para el progreso por tema, la racha de días y la experiencia acumulada.

Creado con Claude Opus 5 el 27 de septiembre de 2026.

## Funcionalidades

- Consultar el resumen global: racha, XP, dominio y todos los temas.
- Consultar el progreso en un tema concreto.
- Registrar el efecto de un repaso o de un examen.

## Endpoints

- `GET /progress` — resumen global y progreso de todos los temas
- `GET /progress/{topicId}` — progreso en un tema

- Endpoints internos, protegidos con `X-Internal-Key`:
- `POST /internal/progress/card-reviewed` · `/internal/progress/quiz-completed`
- `POST /internal/progress/remove-topic`

## Base de datos

- `progress-table-<stage>` — PK `userId`, SK `topicId`

## Decisiones de diseño

- Además de un ítem por tema, cada usuario tiene un ítem especial con SK «#STATS» que guarda la racha y el XP. Como «#» ordena antes que cualquier letra, una sola consulta devuelve las estadísticas globales y todos los temas: es lo que permite pintar la pantalla de inicio completa con una sola llamada.
- El porcentaje de dominio no se almacena, se calcula al leer, para que no pueda desviarse de los números que resume.
- La racha se muestra en cero si el usuario no estudió ayer ni hoy. Calcularlo al leer evita tener que ejecutar un proceso nocturno sobre todos los usuarios. Todos los cálculos usan la hora de Lima y no UTC: con UTC la racha se rompería a las siete de la tarde.
- El estado «tema dominado» lo fija el examen, no el repaso.

## Despliegue automático

Requiere Node.js y Serverless Framework:

```bash
npm install -g serverless
```

Cambia `org: deborajeronimo` en `serverless.yml` por tu cuenta de Serverless Dashboard, o elimina las líneas `org:` y `app:` para desplegar sin Dashboard.

Desde la carpeta de este microservicio:

```bash
serverless deploy --param="jwtSecret=..." --param="internalKey=..."
```

### Parámetros

| Parámetro | Qué es |
|---|---|
| `jwtSecret` | Secreto de los tokens. |
| `internalKey` | Secreto de las llamadas entre servicios. |

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
