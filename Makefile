# SkillPath — API. Requiere python3.11. El despliegue es manual en la consola de AWS.
VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: help install test test-cov lint fmt package deploy-guide seed postman clean

help:
	@grep -E '^[a-zA-Z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Crea el entorno virtual e instala dependencias
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements-dev.txt

test: ## Pruebas unitarias (no necesita AWS ni credenciales)
	$(PY) -m pytest tests/unit

test-cov: ## Pruebas con reporte de cobertura
	$(PY) -m pytest tests/unit --cov=shared --cov=services --cov=infra --cov-report=term-missing

lint: ## Revisa estilo
	$(VENV)/bin/ruff check shared services tests scripts infra

fmt: ## Corrige estilo automáticamente
	$(VENV)/bin/ruff check --fix shared services tests scripts infra

package: ## Arma un .zip por función, listo para subir a la consola
	$(PY) scripts/package.py

deploy-guide: ## Regenera docs/despliegue-manual.md desde infra/spec.py
	$(PY) scripts/generate_deploy_guide.py

seed: ## Carga el catálogo de temas y las flashcards
	$(PY) scripts/seed.py

postman: ## Genera la colección de Postman desde los escenarios de pytest
	$(PY) scripts/generate_postman.py

clean:
	rm -rf build dist .pytest_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
