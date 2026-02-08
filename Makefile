.PHONY: help clean install lint test unit-test integration-test

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

help:
	@echo "Abhaile Makefile targets:"
	@echo "  make clean                Remove virtual environment"
	@echo "  make install              Create venv, install dependencies and pre-commit hooks"
	@echo "  make lint                 Run pre-commit hooks on all files"
	@echo "  make test                 Run all python tests"
	@echo "  make unit-test            Run python unit tests"
	@echo "  make integration-test     Run integration tests"

	$(VENV):
	$(PYTHON) -m venv $(VENV)

clean:
	rm -rf $(VENV)

install: $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	$(VENV_PIP) install pre-commit
	$(VENV)/bin/pre-commit install

lint: $(VENV)
	$(VENV)/bin/pre-commit run --all-files

test: $(VENV)
	$(VENV)/bin/pytest tests/

unit-test: $(VENV)
	$(VENV)/bin/pytest tests/unit/

integration-test: $(VENV)
	$(VENV)/bin/pytest tests/integration/
