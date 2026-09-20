#!/usr/bin/env python3
"""Arma un .zip por función Lambda, listo para subir a mano en la consola.

Como el despliegue es manual no hay layers: cada zip lleva dentro todo lo que
necesita (el handler, `skillpath_common` y PyJWT). Son unos pocos cientos de
kilobytes, muy por debajo del límite de 50 MB de la consola.

    python scripts/package.py            # todas
    python scripts/package.py auth-service
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infra.spec import SERVICES  # noqa: E402

BUILD = ROOT / "build"
DIST = ROOT / "dist"
SHARED = ROOT / "shared" / "python"
REQUIREMENTS = ROOT / "shared" / "requirements.txt"


def install_dependencies(target: Path) -> None:
    """PyJWT es Python puro, así que no depende de la arquitectura."""
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--quiet", "--no-compile",
            "-r", str(REQUIREMENTS),
            "--target", str(target),
        ],
        check=True,
    )


def build(service: str) -> Path:
    spec = SERVICES[service]
    staging = BUILD / service
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # 1. el handler
    shutil.copytree(ROOT / spec["code"], staging, dirs_exist_ok=True)
    # 2. el código compartido
    shutil.copytree(SHARED / "skillpath_common", staging / "skillpath_common")
    # 3. las dependencias
    install_dependencies(staging)

    # Nada de esto debe viajar dentro del zip.
    for basura in list(staging.rglob("__pycache__")) + list(staging.rglob("*.dist-info")):
        shutil.rmtree(basura, ignore_errors=True)
    for archivo in staging.rglob("*.pyc"):
        archivo.unlink(missing_ok=True)

    DIST.mkdir(exist_ok=True)
    destino = DIST / f"{service}.zip"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as archivo:
        for ruta in sorted(staging.rglob("*")):
            if ruta.is_file():
                archivo.write(ruta, ruta.relative_to(staging))

    shutil.rmtree(staging)
    return destino


def main(argv: list[str]) -> int:
    objetivos = argv[1:] or list(SERVICES)
    desconocidos = [s for s in objetivos if s not in SERVICES]
    if desconocidos:
        print(f"Servicio desconocido: {', '.join(desconocidos)}")
        print(f"Disponibles: {', '.join(SERVICES)}")
        return 1

    print("Empaquetando para subir a la consola de AWS\n")
    for service in objetivos:
        destino = build(service)
        kb = destino.stat().st_size / 1024
        print(f"   ✓ {service:20s} {destino.relative_to(ROOT)}  ({kb:.0f} KB)")

    print("\nListo. Sube cada .zip en Lambda → Código → Cargar desde → Archivo .zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
