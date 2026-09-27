# SkillPath — API. Despliegue con Serverless Framework.
VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: help install test sync seed lint

help:
	@grep -E '^[a-zA-Z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Crea el entorno virtual e instala dependencias de desarrollo
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements-dev.txt

test: ## Pruebas: montan los seis servicios con DynamoDB simulado, sin AWS
	$(PY) -m pytest tests/unit

sync: ## Copia shared/common.py a cada microservicio (hazlo antes de desplegar)
	./scripts/sync-common.sh

seed: ## Carga el catálogo de temas y las tarjetas en DynamoDB
	$(PY) scripts/seed.py

test-live: ## Ejecuta los escenarios contra AWS (necesita las seis URLs)
	$(PY) -m pytest tests/e2e -q

postman: ## Regenera la colección de Postman desde los escenarios
	$(PY) scripts/generate_postman.py

lint: ## Revisa estilo
	$(VENV)/bin/ruff check shared services scripts tests
