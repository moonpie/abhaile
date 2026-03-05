.PHONY: help clean clean-venv clean-all install lint doccheck typecheck test test-fast coverage unit-test integration-test

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

help:
	@echo "Abhaile Makefile targets:"
	@echo "  make clean                Remove build/compile artifacts"
	@echo "  make clean-venv            Remove virtual environment"
	@echo "  make clean-all             Remove artifacts and virtual environment"
	@echo "  make install              Create venv, install dependencies and pre-commit hooks"
	@echo "  make lint                 Run pre-commit hooks on all files"
	@echo "  make doccheck             Run docstring coverage checks"
	@echo "  make typecheck            Run mypy type checking"
	@echo "  make test                 Run all python tests"
	@echo "  make test-fast            Run tests excluding slow"
	@echo "  make coverage             Run tests with HTML coverage report"
	@echo "  make unit-test            Run python unit tests"
	@echo "  make integration-test     Run integration tests"

$(VENV):
	$(PYTHON) -m venv $(VENV)

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml
	rm -rf *.egg-info .eggs build dist
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.pyd" \) -delete

clean-venv:
	rm -rf $(VENV)

clean-all: clean clean-venv

install: $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e .
	@if [ -f requirements-dev.txt ]; then $(VENV_PIP) install -r requirements-dev.txt; fi
	$(VENV_PIP) install pre-commit
	$(VENV)/bin/pre-commit install

lint: $(VENV)
	$(VENV)/bin/pre-commit run --all-files
	$(VENV)/bin/mypy abhaile
	$(VENV)/bin/mypy tests
	$(VENV)/bin/interrogate abhaile

doccheck: $(VENV)
	$(VENV)/bin/interrogate -v abhaile

typecheck: $(VENV)
	$(VENV)/bin/mypy abhaile
	$(VENV)/bin/mypy tests

test: $(VENV)
	$(VENV)/bin/pytest tests/

test-fast: $(VENV)
	$(VENV)/bin/pytest tests/unit -m "not slow"

coverage: $(VENV)
	$(VENV)/bin/pytest tests/ --cov --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

unit-test: $(VENV)
	$(VENV)/bin/pytest tests/unit/

integration-test: $(VENV)
	$(VENV)/bin/pytest tests/integration/
