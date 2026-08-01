.PHONY: help clean clean-venv clean-all install lint doccheck typecheck test test-fast coverage unit-test integration-test render render-host apply diff validate validate-host bootstrap-create bootstrap-edit bootstrap-rotate bootstrap-validate docs

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
empty :=
space := $(empty) $(empty)
HOST_MISMATCH_FLAG :=
HOST_MISMATCH_NOTICE :=
ifeq ($(ALLOW_HOST_MISMATCH),1)
HOST_MISMATCH_FLAG := $(space)--allow-host-mismatch
HOST_MISMATCH_NOTICE := Host mismatch allowed for dry-run validation only.
endif

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
	@echo "  make validate             Render all hosts and dry-run apply all hosts"
	@echo "  make validate-host        Render and dry-run apply one host; set HOST=<host>"

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
	$(VENV)/bin/interrogate src/abhaile

doccheck: $(VENV)
	$(VENV)/bin/interrogate -v src/abhaile

typecheck: $(VENV)
	$(VENV)/bin/mypy src/abhaile
	$(VENV)/bin/mypy tests

test: $(VENV)
	$(VENV)/bin/pytest tests/

test-fast: $(VENV)
	$(VENV)/bin/pytest tests/unit -m "not slow" --no-cov

coverage: $(VENV)
	$(VENV)/bin/pytest tests/ --cov --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

unit-test: $(VENV)
	$(VENV)/bin/pytest tests/unit/

integration-test: $(VENV)
	$(VENV)/bin/pytest tests/integration/

render: $(VENV)
	$(VENV_PYTHON) -m abhaile.cli.render --all --output ./out

render-host: $(VENV)
	@test -n "$(HOST)" || (echo "Usage: make render-host HOST=phobos" >&2; exit 1)
	$(VENV_PYTHON) -m abhaile.cli.render --host $(HOST) --output ./out

apply: $(VENV)
	@test -n "$(HOST)" || (echo "Usage: make apply HOST=phobos" >&2; exit 1)
	$(VENV_PYTHON) -m abhaile.cli.render --host $(HOST) --output ./out
	$(VENV_PYTHON) -m abhaile.cli.apply --host $(HOST) --output ./out --dry-run

diff: $(VENV)
	$(VENV_PYTHON) -m abhaile.cli.diff --output ./out

validate: $(VENV)
	$(VENV_PYTHON) -m abhaile.cli.render --all --output ./out
	$(if $(HOST_MISMATCH_NOTICE),@echo "$(HOST_MISMATCH_NOTICE)")
	$(VENV_PYTHON) -m abhaile.cli.apply --host phobos --output ./out/phobos --dry-run$(HOST_MISMATCH_FLAG)
	$(VENV_PYTHON) -m abhaile.cli.apply --host deimos --output ./out/deimos --dry-run$(HOST_MISMATCH_FLAG)

validate-host: $(VENV)
	@test -n "$(HOST)" || (echo "Usage: make validate-host HOST=phobos" >&2; exit 1)
	$(VENV_PYTHON) -m abhaile.cli.render --host $(HOST) --output ./out
	$(if $(HOST_MISMATCH_NOTICE),@echo "$(HOST_MISMATCH_NOTICE)")
	$(VENV_PYTHON) -m abhaile.cli.apply --host $(HOST) --output ./out --dry-run$(HOST_MISMATCH_FLAG)

bootstrap-create: $(VENV)
	@test -n "$(HOST)" || (echo "Usage: make bootstrap-create HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
	@test -n "$(NAME)" || (echo "Usage: make bootstrap-create HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
	scripts/sops-bootstrap create $(HOST) $(NAME)

bootstrap-edit: $(VENV)
	@test -n "$(HOST)" || (echo "Usage: make bootstrap-edit HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
	@test -n "$(NAME)" || (echo "Usage: make bootstrap-edit HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
	scripts/sops-bootstrap edit $(HOST) $(NAME)

bootstrap-rotate: $(VENV)
	@test -n "$(HOST)" || (echo "Usage: make bootstrap-rotate HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
	@test -n "$(NAME)" || (echo "Usage: make bootstrap-rotate HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
	scripts/sops-bootstrap rotate $(HOST) $(NAME)

bootstrap-validate:
	scripts/sops-bootstrap validate

docs: $(VENV)
	$(VENV_PYTHON) -m abhaile.cli.inventory --format markdown --output docs/INVENTORY.md
