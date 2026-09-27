# Microservicio de Autenticación

API REST para registro e inicio de sesión, desplegada con AWS Lambda, API Gateway y DynamoDB.

Creado con Claude Opus 5 el 27 de septiembre de 2026.

## Funcionalidades

- Registrar una cuenta con nombre, correo y contraseña.
- Iniciar sesión y obtener un token JWT válido por 24 horas.
- Consultar el perfil del usuario autenticado.

## Endpoints

- `POST /auth/register` — crea la cuenta y devuelve el token
- `POST /auth/login` — valida credenciales y devuelve el token
- `GET /auth/me` — perfil del usuario autenticado

## Base de datos

- `auth-table-<stage>` — PK `userId`

## Decisiones de diseño

- La unicidad del correo se impone con un ítem centinela «EMAIL#<correo>» en la misma tabla, escrito en una transacción condicional. Ese mismo ítem sirve para buscar al usuario al iniciar sesión, de modo que no hace falta un índice secundario: un índice sería de consistencia eventual y alguien recién registrado podría no poder entrar durante unos milisegundos.
- Las contraseñas se guardan con PBKDF2-SHA256 y un salt distinto por usuario.
- Cuando las credenciales son incorrectas, el mensaje no dice si falló el correo o la contraseña, y la verificación tarda lo mismo exista o no la cuenta.

## Despliegue automático

Requiere Node.js y Serverless Framework:

```bash
npm install -g serverless
```

Cambia `org: deborajeronimo` en `serverless.yml` por tu cuenta de Serverless Dashboard, o elimina las líneas `org:` y `app:` para desplegar sin Dashboard.

Desde la carpeta de este microservicio:

```bash
serverless deploy --param="jwtSecret=..."
```

### Parámetros

| Parámetro | Qué es |
|---|---|
| `jwtSecret` | Secreto para firmar los tokens. Debe ser el mismo en los seis servicios. |

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
