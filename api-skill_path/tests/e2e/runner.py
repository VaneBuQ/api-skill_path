"""Motor que ejecuta los escenarios: resuelve variables y comprueba resultados.

Lo comparten la ejecución en memoria y la ejecución contra las APIs
desplegadas, para que ambas verifiquen exactamente lo mismo.
"""

import re

from tests.e2e.scenarios import ABSENT, EQ, EXISTS, GTE, IN, LEN, STARTS

_VAR = re.compile(r"\{\{(\w+)\}\}")


def resolve(value, variables):
    """Sustituye `{{nombre}}` en textos, listas y diccionarios."""
    if isinstance(value, str):
        # Si el texto es exactamente una variable, conserva su tipo original.
        exact = _VAR.fullmatch(value)
        if exact:
            return variables.get(exact.group(1), value)
        return _VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, dict):
        return {k: resolve(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, variables) for v in value]
    return value


def dig(payload, path):
    """Lee `items[0].topicId` dentro de la respuesta. None si no existe."""
    current = payload
    for part in path.replace("]", "").replace("[", ".").split("."):
        if part == "":
            continue
        if isinstance(current, list):
            index = int(part)
            current = current[index] if index < len(current) else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def check_failures(step, status, payload, variables):
    """Lista de problemas del paso. Vacía si todo cuadra."""
    problems = []
    if status != step.status:
        problems.append(f"esperaba HTTP {step.status} y llegó {status} — {payload}")

    for path, operator, expected in step.checks:
        actual = dig(payload, path)
        expected = resolve(expected, variables)

        if operator == EXISTS:
            ok, detalle = actual is not None, "debía venir y no vino"
        elif operator == ABSENT:
            ok, detalle = actual is None, f"no debía venir y vino: {actual!r}"
        elif operator == EQ:
            ok = actual == expected
            detalle = f"esperaba {expected!r} y llegó {actual!r}"
        elif operator == GTE:
            actual_valor = len(actual) if isinstance(actual, list) else actual
            ok = actual_valor is not None and actual_valor >= expected
            detalle = f"esperaba al menos {expected!r} y llegó {actual_valor!r}"
        elif operator == LEN:
            ok = actual is not None and len(actual) == expected
            longitud = len(actual) if actual is not None else None
            detalle = f"esperaba {expected} elementos y llegaron {longitud}"
        elif operator == STARTS:
            ok = isinstance(actual, str) and actual.startswith(expected)
            detalle = f"esperaba que empezara por {expected!r} y llegó {actual!r}"
        elif operator == IN:
            ok = actual in expected
            detalle = f"esperaba uno de {expected!r} y llegó {actual!r}"
        else:
            raise AssertionError(f"Operador desconocido: {operator}")

        if not ok:
            problems.append(f"{path}: {detalle}")

    return problems


def capture_into(step, payload, variables):
    for name, path in step.capture.items():
        variables[name] = dig(payload, path)
