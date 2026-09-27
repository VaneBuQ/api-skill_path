#!/usr/bin/env bash
# Copia shared/common.py a cada microservicio.
#
# En este patrón no hay Lambda Layers: cada servicio se empaqueta solo con lo
# que hay en su carpeta. Ejecuta esto antes de desplegar si tocaste el original.
set -euo pipefail

cd "$(dirname "$0")/.."

for service in services/*/; do
  [ -f "${service}serverless.yml" ] || continue
  cp shared/common.py "${service}common.py"
  echo "   ✓ ${service}common.py"
done

echo
echo "Código común sincronizado."
