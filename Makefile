# SkillPath — API. Requiere: python3.11, y para desplegar: aws-sam-cli + aws-cli.
VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help install test test-cov lint fmt validate build deploy seed postman clean

help:
	@grep -E '^[a-zA-Z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Crea el entorno virtual e instala dependencias
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

test: ## Ejecuta las pruebas unitarias (no necesita AWS)
	$(PY) -m pytest tests/unit

test-cov: ## Pruebas con reporte de cobertura
	$(PY) -m pytest tests/unit --cov=shared --cov=services --cov-report=term-missing

lint: ## Revisa estilo
	$(VENV)/bin/ruff check shared services tests scripts

fmt: ## Corrige estilo automáticamente
	$(VENV)/bin/ruff check --fix shared services tests scripts
	$(VENV)/bin/ruff format shared services tests scripts

validate: ## Valida la plantilla de SAM
	sam validate --lint

build: ## Empaqueta las Lambdas
	sam build

deploy: build ## Despliega el stack a AWS
	sam deploy

seed: ## Carga el catálogo de temas y las flashcards
	$(PY) scripts/seed.py

postman: ## Genera la colección de Postman desde los escenarios de pytest
	$(PY) scripts/generate_postman.py

clean:
	rm -rf .aws-sam .pytest_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
