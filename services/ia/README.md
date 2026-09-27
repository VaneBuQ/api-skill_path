# Microservicio de IA

API REST que evalúa con inteligencia artificial la respuesta que el usuario escribe sobre un concepto.

Creado con Claude Opus 5 el 27 de septiembre de 2026.

## Funcionalidades

- Comparar la respuesta escrita del usuario con la respuesta correcta de la tarjeta.
- Devolver un veredicto (correcta, a medias o incorrecta), un puntaje y una explicación breve.
- Sugerir una calificación para la repetición espaciada.
- Consultar el historial de comprobaciones de un tema.

## Endpoints

- `POST /ia/check-answer` — evalúa la respuesta escrita
- `GET /ia/history/{topicId}` — historial de comprobaciones

## Base de datos

- `ia-checks-<stage>` — PK `userId`, SK `topicId#cardId#instante`

## Decisiones de diseño

- Esta es la funcionalidad que distingue a SkillPath de una app de flashcards normal. En el repaso clásico el usuario ve la respuesta y se autocalifica, lo que mide reconocimiento y no recuerdo. Aquí tiene que producir la respuesta antes de verla.
- La respuesta del usuario se limita a **60 palabras** y la explicación de la IA a **40**. El límite se pide en las instrucciones al modelo, se impone con `max_tokens` y se recorta en el servicio por si acaso. Acota el costo y, sobre todo, la calidad: una respuesta larga es imposible de evaluar y una explicación larga nadie la lee.
- La respuesta correcta se pide siempre al microservicio de tarjetas, nunca se acepta del navegador: si no, cualquiera podría enviar la suya.
- La IA **sugiere** la calificación, pero decide el usuario. Calificar sola sería frágil: una respuesta correcta expresada de forma rara se penalizaría y el usuario perdería la confianza en la aplicación.
- El modelo es `claude-haiku-4-5`. Comparar una respuesta con la correcta es una tarea de juez: corta y acotada. Un modelo mayor costaría cinco veces más sin mejorar el veredicto.
- La llamada se hace por HTTPS con `urllib` de la librería estándar y no con el SDK oficial: el SDK arrastra dependencias con código compilado que en Lambda habría que empaquetar para Amazon Linux, y este patrón de despliegue no empaqueta dependencias.

## Despliegue automático

Requiere Node.js y Serverless Framework:

```bash
npm install -g serverless
```

> ⚠️ Este servicio llama a `flashcards`, así que hay que desplegarlos **antes** y pasarle sus URLs.

Cambia `org: deborajeronimo` en `serverless.yml` por tu cuenta de Serverless Dashboard, o elimina las líneas `org:` y `app:` para desplegar sin Dashboard.

Desde la carpeta de este microservicio:

```bash
serverless deploy --param="jwtSecret=..." --param="internalKey=..." --param="flashcardsApiBase=..." --param="anthropicApiKey=..."
```

### Parámetros

| Parámetro | Qué es |
|---|---|
| `jwtSecret` | Secreto de los tokens. |
| `internalKey` | Secreto de las llamadas entre servicios. |
| `flashcardsApiBase` | URL del microservicio de tarjetas. |
| `anthropicApiKey` | **Tu clave de la API de Anthropic.** Ver abajo. |

> ### 🔑 Dónde va tu clave de la API de Anthropic
>
> **Solo en la línea de comandos**, al desplegar este servicio:
>
> ```bash
> serverless deploy --param="anthropicApiKey=sk-ant-..."
> ```
>
> Serverless la guarda como variable de entorno de la función Lambda.
> **No la escribas en ningún archivo del repositorio**: no hay ningún `.env`
> ni ninguna línea en el `serverless.yml` donde ponerla, y es a propósito.
>
> La obtienes en [console.anthropic.com](https://console.anthropic.com) → API Keys.
>
> Sin ella, la aplicación funciona igual salvo el botón «Comprobar con IA»,
> que responde «La comprobación con IA no está configurada».

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
