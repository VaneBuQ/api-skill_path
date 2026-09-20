#!/usr/bin/env python3
"""Genera `docs/despliegue-manual.md` desde `infra/spec.py`.

La guía se genera en vez de escribirse a mano para que no pueda contradecir a
las pruebas: ambas leen la misma especificación.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infra.spec import (  # noqa: E402
    ARCHITECTURE,
    MEMORY_MB,
    REGION,
    RUNTIME,
    SERVICES,
    TABLES,
    TIMEOUT_SECONDS,
    all_routes,
    env_for,
    function_name,
    table_name,
)

STAGE = "dev"
OUT = ROOT / "docs" / "despliegue-manual.md"


def tabla_seccion(short, spec, n):
    pk_name, pk_type = spec["pk"]
    lineas = [
        f"### {n}. `{table_name(STAGE, short)}`",
        "",
        f"Dueño: **{spec['owner']}**",
        "",
        "| Campo | Valor |",
        "|---|---|",
        f"| Nombre de la tabla | `{table_name(STAGE, short)}` |",
        f"| Clave de partición | `{pk_name}` · {pk_type} (String) |",
    ]
    if spec["sk"]:
        lineas.append(f"| Clave de ordenación | `{spec['sk'][0]}` · String |")
    else:
        lineas.append("| Clave de ordenación | *(ninguna)* |")
    lineas += [
        "| Configuración | **Personalizar** → Capacidad **Bajo demanda** |",
        "| Recuperación a un punto anterior | Activada |",
        "",
    ]
    if spec.get("why"):
        lineas += [f"> {spec['why']}", ""]

    for index in spec["indexes"]:
        lineas += [
            f"**Índice secundario global `{index['name']}`**",
            "",
            "| Campo | Valor |",
            "|---|---|",
            f"| Clave de partición | `{index['pk'][0]}` · String |",
        ]
        if index.get("sk"):
            lineas.append(f"| Clave de ordenación | `{index['sk'][0]}` · String |")
        if index["projection"] == "ALL":
            lineas.append("| Atributos proyectados | **Todos** |")
        else:
            incluidos = ", ".join(f"`{a}`" for a in index["included"])
            lineas.append(f"| Atributos proyectados | **Solo los siguientes**: {incluidos} |")
        lineas += ["", f"> {index['why']}", ""]

    lineas += [f"*Atributos que guarda:* {spec['attributes']}", "", "---", ""]
    return lineas


def funcion_seccion(service, spec, n):
    nombre = function_name(STAGE, service)
    lineas = [
        f"### {n}. `{nombre}`",
        "",
        f"{spec['description']}",
        "",
        "| Campo | Valor |",
        "|---|---|",
        f"| Nombre | `{nombre}` |",
        f"| Tiempo de ejecución | {RUNTIME} |",
        f"| Arquitectura | {ARCHITECTURE} |",
        f"| Memoria | {spec.get('memory', MEMORY_MB)} MB |",
        f"| Tiempo de espera | {spec.get('timeout', TIMEOUT_SECONDS)} s |",
        "| Controlador (Handler) | `app.lambda_handler` |",
        f"| Código | subir `dist/{service}.zip` |",
        "",
        "**Variables de entorno**",
        "",
        "| Clave | Valor |",
        "|---|---|",
    ]
    for clave, valor in env_for(STAGE, service).items():
        lineas.append(f"| `{clave}` | `{valor}` |")
    lineas.append("")

    permisos = []
    for short, modo in spec["tables"].items():
        acciones = (
            "GetItem, Query, Scan" if modo == "read"
            else "GetItem, Query, Scan, PutItem, UpdateItem, DeleteItem, BatchWriteItem, TransactWriteItems"
        )
        dueno = TABLES[short]["owner"]
        nota = "" if dueno == service else f" — tabla de *{dueno}*, solo lectura"
        permisos.append(f"| `{table_name(STAGE, short)}` | {acciones}{nota} |")

    if permisos:
        lineas += [
            "**Permisos del rol de ejecución** (IAM → Roles → el rol de esta función)",
            "",
            "| Recurso | Acciones de DynamoDB |",
            "|---|---|",
            *permisos,
            "",
        ]
    if spec["invokes"]:
        objetivos = ", ".join(f"`{function_name(STAGE, t)}`" for t in spec["invokes"])
        lineas += [
            f"Además necesita `lambda:InvokeFunction` sobre: {objetivos}",
            "",
        ]
    lineas += [
        "> ⚠️ No le des acceso a ninguna otra tabla. Que cada función solo alcance",
        "> las suyas es lo que hace real el patrón *database-per-service*.",
        "",
        "---",
        "",
    ]
    return lineas


def main():
    rutas = all_routes()
    doc = [
        "# SkillPath — Guía de despliegue manual en AWS",
        "",
        "> **Este archivo se genera.** No lo edites a mano: cambia `infra/spec.py`",
        "> y vuelve a ejecutar `make deploy-guide`. Las pruebas leen esa misma",
        "> especificación, así que la guía y el código no pueden contradecirse.",
        "",
        f"Región: **{REGION}** (N. Virginia) · Entorno: **{STAGE}**",
        "",
        "## Orden de trabajo",
        "",
        "1. Crear las **7 tablas** de DynamoDB (§1)",
        "2. Guardar el **secreto del JWT** (§2)",
        "3. Crear las **6 funciones** Lambda y subir su .zip (§3)",
        "4. Crear la **HTTP API** y sus rutas (§4)",
        "5. Cargar los **datos semilla** (§5)",
        "6. **Comprobar** que todo responde (§6)",
        "",
        "Las funciones se crean antes que la API porque la API necesita",
        "seleccionarlas, y las tablas antes que las funciones porque sus nombres",
        "van en las variables de entorno.",
        "",
        "---",
        "",
        "## §1 · Tablas de DynamoDB",
        "",
        "DynamoDB → Tablas → **Crear tabla**, una por cada una. En todas:",
        "**Personalizar la configuración** → Capacidad de lectura/escritura →",
        "**Bajo demanda**. Así no se paga nada mientras nadie use la app.",
        "",
        "---",
        "",
    ]
    for n, (short, spec) in enumerate(TABLES.items(), start=1):
        doc += tabla_seccion(short, spec, n)

    doc += [
        "## §2 · Secreto del JWT",
        "",
        "Las funciones firman y validan los tokens con un secreto compartido.",
        "Genera uno con:",
        "",
        "```bash",
        "openssl rand -hex 32",
        "```",
        "",
        "Guárdalo en **Systems Manager → Parameter Store → Crear parámetro**:",
        "",
        "| Campo | Valor |",
        "|---|---|",
        f"| Nombre | `/skillpath/{STAGE}/jwt-secret` |",
        "| Tipo | **SecureString** |",
        "| Valor | el resultado del comando |",
        "",
        "Luego copia ese mismo valor en la variable `JWT_SECRET` de **las seis**",
        "funciones. Si una tiene un secreto distinto, rechazará todos los tokens.",
        "",
        "> El secreto nunca se guarda en el repositorio.",
        "",
        "---",
        "",
        "## §3 · Funciones Lambda",
        "",
        "Primero genera los paquetes:",
        "",
        "```bash",
        "make package",
        "```",
        "",
        "Luego, por cada función: Lambda → **Crear función** → *Crear desde cero*,",
        "con los valores de abajo. El código se sube en **Código → Cargar desde →",
        "Archivo .zip**.",
        "",
        "---",
        "",
    ]
    for n, (service, spec) in enumerate(SERVICES.items(), start=1):
        doc += funcion_seccion(service, spec, n)

    doc += [
        "## §4 · HTTP API",
        "",
        "API Gateway → **Crear API** → **HTTP API** (no REST API: cuesta 3.5 veces",
        f"más y el costeo del informe usa el precio de HTTP API). Nombre: `skillpath-{STAGE}`.",
        "",
        "### 4.1 CORS",
        "",
        "| Campo | Valor |",
        "|---|---|",
        "| Access-Control-Allow-Origin | `http://localhost:5173` en desarrollo; el dominio de CloudFront en producción |",
        "| Access-Control-Allow-Headers | `authorization`, `content-type` |",
        "| Access-Control-Allow-Methods | `GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS` |",
        "| Access-Control-Max-Age | 600 |",
        "",
        "### 4.2 Autorizador",
        "",
        "Autorización → **Crear autorizador** → **Lambda**:",
        "",
        "| Campo | Valor |",
        "|---|---|",
        "| Nombre | `jwt-authorizer` |",
        f"| Función Lambda | `{function_name(STAGE, 'authorizer')}` |",
        "| Versión del formato de carga | **2.0** |",
        "| Respuestas de autorizador simples | **Activado** |",
        "| Origen de identidad | `$request.header.Authorization` |",
        "| Almacenar en caché | 300 segundos |",
        "",
        "> Las respuestas simples hacen que el autorizador devuelva `isAuthorized`",
        "> en vez de una política IAM completa, que es lo que espera el código.",
        "",
        "### 4.3 Rutas",
        "",
        f"{len(rutas)} rutas. Todas con integración **Lambda** hacia la función indicada.",
        "En la columna *Autorizador*, `jwt-authorizer` significa que hay que",
        "adjuntarlo en Rutas → la ruta → Autorización.",
        "",
        "| Método | Ruta | Integración | Autorizador | Qué hace |",
        "|---|---|---|---|---|",
    ]
    for method, path, auth, description, service in rutas:
        autorizador = "— *(pública)*" if auth == "NONE" else "`jwt-authorizer`"
        doc.append(
            f"| `{method}` | `{path}` | `{function_name(STAGE, service)}` | {autorizador} | {description} |"
        )

    doc += [
        "",
        "> Solo tres rutas son públicas: registrarse, iniciar sesión y ver el",
        "> catálogo. Si olvidas adjuntar el autorizador a cualquier otra, esa ruta",
        "> queda abierta a Internet.",
        "",
        "### 4.4 Etapa",
        "",
        f"Crea la etapa **`{STAGE}`** con implementación automática activada.",
        "La URL de invocación resultante es la que va en `VITE_API_BASE_URL` del frontend.",
        "",
        "---",
        "",
        "## §5 · Datos semilla",
        "",
        "Con las tablas ya creadas y las credenciales de AWS configuradas:",
        "",
        "```bash",
        "make seed",
        "```",
        "",
        "Carga los 6 temas del catálogo y sus tarjetas. El `cardCount` se calcula",
        "a partir de las tarjetas realmente insertadas, nunca se teclea.",
        "",
        "---",
        "",
        "## §6 · Comprobación",
        "",
        "Sustituye `<URL>` por la URL de invocación de la etapa:",
        "",
        "```bash",
        "curl -s <URL>/topics",
        "```",
        "",
        "Debe devolver los 6 temas. Luego crea una cuenta:",
        "",
        "```bash",
        "curl -s -X POST <URL>/auth/register -H 'Content-Type: application/json' -d '{\"name\":\"Prueba\",\"email\":\"prueba@uni.edu\",\"password\":\"Secreta123\"}'",
        "```",
        "",
        "Debe devolver `201` con un `token`. Con ese token, una ruta protegida:",
        "",
        "```bash",
        "curl -s <URL>/me/topics -H 'Authorization: Bearer <TOKEN>'",
        "```",
        "",
        "Si responde `401`, revisa que el autorizador esté adjunto a la ruta y que",
        "`JWT_SECRET` sea idéntico en las seis funciones.",
        "",
        "---",
        "",
        "## Problemas frecuentes",
        "",
        "| Síntoma | Causa más probable |",
        "|---|---|",
        "| `500` en todas las rutas de un servicio | Falta una variable de entorno con el nombre de una tabla |",
        "| `401` con un token recién emitido | `JWT_SECRET` distinto entre funciones |",
        "| `403 AccessDeniedException` en los logs | Al rol de la función le falta el permiso sobre esa tabla |",
        "| El repaso funciona pero el progreso no cambia | Falta `lambda:InvokeFunction` de flashcards-service sobre progress-service |",
        "| El navegador bloquea las llamadas | CORS: el origen configurado no coincide con el del frontend |",
        "| `Internal Server Error` sin logs | El handler no es `app.lambda_handler`, o el .zip tiene una carpeta de más dentro |",
        "",
    ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print(f"Escrito {OUT.relative_to(ROOT)} ({len(doc)} líneas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
