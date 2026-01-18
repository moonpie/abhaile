.PHONY: help install test lint pre-commit render generate-inventory clean clean-venv

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

help:
	@echo "Abhaile Makefile targets:"
	@echo "  make install              Create venv, install dependencies and pre-commit hooks"
	@echo "  make test                 Run all Python tests (unit + integration)"
	@echo "  make lint                 Run pre-commit hooks on all files"
	@echo "  make pre-commit           Alias for 'make lint'"
	@echo "  make render               Run orchestrator to render all host configs"
	@echo "  make generate-inventory   Render all hosts, then generate inventory artifacts"
	@echo "  make clean                Remove rendered output and test artifacts"
	@echo "  make clean-venv           Remove virtual environment"

	$(VENV):
	$(PYTHON) -m venv $(VENV)

install: $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	$(VENV_PIP) install pre-commit pytest pytest-cov
	$(VENV)/bin/pre-commit install

test: $(VENV)
	@mkdir -p tmp
	$(VENV)/bin/pytest tests/ -v --cov=tools --cov-report=term-missing

lint: $(VENV)
	$(VENV)/bin/pre-commit run --all-files

pre-commit: lint

render: $(VENV)
	$(VENV_PYTHON) tools/render/cli.py

generate-inventory: $(VENV) render
	$(VENV_PYTHON) tools/inventory/cli.py

clean:
	rm -rf out/rendered
	rm -rf .pytest_cache
	rm -rf tmp/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

clean-venv:
	rm -rf $(VENV)
