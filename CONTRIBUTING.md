# Contributing to Abhaile

Thank you for your interest in contributing! This document covers contribution guidelines, commit conventions, and development standards.

## Getting Started

```bash
# Clone the repository
git clone git@github.com:moonpie/abhaile.git
cd abhaile

# Install dependencies and pre-commit hooks
make install

# Verify your setup
make test
make lint
```

## Commit Conventions

### Commit Signing

- All commits to `main` must be signed
- Configure GPG signing: `git config --global commit.gpgsign true`

### Conventional Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

**Examples:**

```text
feat: add automatic rollback to GitOps runner
fix: correct render path in apply.sh
docs: update QUICKSTART with bootstrap steps
```

## Branching Strategy

- Feature branches target `main`
- Branch naming: `feature/<description>` or `fix/<description>`
- CI must be green before merge
- PRs should be squashed to maintain clean history

## Documentation Standards

### Required Updates

- Update `docs/` alongside config or tooling changes
- Keep ADRs current with status updates (Accepted, Superseded, Deprecated)
- Update command examples when CLIs change
- Regenerate inventory after service changes: `make generate-inventory`

### Markdown Standards

- Formatted with **mdformat** (runs via pre-commit)
- Linted with **PyMarkdown** (runs via pre-commit)
- Line-length (`MD013`) disabled for tables and long links
- Keep paragraphs readable, prefer ~120 char wrapping where practical
- Use Mermaid for diagrams

## Code Standards

### Python

- **Formatter:** Black (line length 100)
- **Linter:** Ruff
- **Type hints:** Preferred for public APIs
- **Docstrings:** Required for modules and public functions

### Bash

- **Linter:** Shellcheck (must pass)
- **Functions:** Prefix with namespace (`apply_`, `validate_`)
- **Libraries:** Source from `tools/bash_lib/` or `tools/apply/lib/`

## Pre-Commit Hooks

Pre-commit hooks run automatically on commit. Enforce:

- YAML/JSON validation
- Jinja2 syntax checking
- Python formatting (Black, Ruff)
- Bash linting (shellcheck)
- Secret scanning (gitleaks)
- Markdown formatting

**Manual execution:**

```bash
# Run all hooks
pre-commit run --all-files

# Run specific hook
pre-commit run validate-schemas --all-files
```

## Testing

```bash
# Run all tests
make test

# Run specific test file
pytest tests/unit/render/test_dns_builder.py -v

# With coverage
pytest --cov=tools tests/
```

See [tests/README.md](tests/README.md) for complete testing guide.

## Pull Request Process

1. Create feature branch from `main`
1. Make your changes, ensuring:
   - Pre-commit hooks pass
   - Tests pass (`make test`)
   - Documentation updated
1. Push to your fork
1. Open PR against `main`
1. Address review feedback
1. Squash commits on merge

## Development Workflow

```bash
# Make config changes
vim config/services/myservice/service.yaml

# Render configurations
make render

# Test locally (dry-run)
./tools/apply/apply.sh phobos

# Apply if correct
sudo ./tools/apply/apply.sh --apply phobos

# Commit changes
git add config/
git commit -m "feat: add myservice configuration"
```

## Questions or Issues?

- Check [docs/README.md](docs/README.md) for documentation index
- Review [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for internals
- Open an issue for bugs or feature requests
