# Microservicio de Temas y Mazos

API REST para el catálogo de temas, «Mis temas» y los mazos que crea el propio usuario.

Creado con Claude Opus 5 el 27 de septiembre de 2026.

## Funcionalidades

- Listar el catálogo de temas, con búsqueda que ignora tildes.
- Agregar y quitar temas de «Mis temas».
- Crear mazos propios con sus tarjetas.
- Ver, renombrar y eliminar un mazo propio.
- Agregar y eliminar tarjetas de un mazo propio.

## Endpoints

- `GET /topics` — catálogo, acepta `?search=`
- `POST /topics/{topicId}/follow` — agrega el tema a «Mis temas»
- `DELETE /topics/{topicId}/follow` — lo quita
- `GET /me/topics` — temas que sigue el usuario
- `POST /me/decks` — crea un mazo propio
- `GET /me/decks` — lista los mazos propios
- `GET /me/decks/{topicId}` — detalle con sus tarjetas
- `PATCH /me/decks/{topicId}` — renombra el mazo
- `DELETE /me/decks/{topicId}` — elimina el mazo y todo lo derivado
- `POST /me/decks/{topicId}/cards` — agrega tarjetas
- `DELETE /me/decks/{topicId}/cards/{cardId}` — elimina una tarjeta

## Base de datos

- `topics-catalog-<stage>` — PK `topicId`, índice `catalog-index` por `visibility` y `name`
- `topics-user-<stage>` — PK `userId`, SK `topicId`

## Decisiones de diseño

- Un mazo propio es un tema privado con dueño, no una entidad nueva: por eso el repaso, el progreso y el examen funcionan sobre él sin cambios. El atributo `visibility` vale «public» para el catálogo y «private» para los mazos propios, y como el catálogo se consulta filtrando por ese valor a través del índice, un mazo propio no puede aparecer en él.
- Un mazo ajeno responde 404 y no 403: decir «existe pero no es tuyo» revelaría qué identificadores existen.
- Eliminar un mazo borra también sus tarjetas, el historial de repaso y el progreso, pidiéndoselo a los servicios dueños. Sin esa limpieza, el mazo borrado seguiría apareciendo en la pantalla de progreso.

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
