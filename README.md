# Abhaile

Abhaile is a GitOps-managed homelab for two Debian hosts (phobos and deimos). The repo defines the desired state for host networking, system services, and containerized apps, then renders host-specific artifacts and applies them in a controlled, repeatable way.

## What It Manages

- Host networking via systemd-networkd, including VLANs and service addressing
- Podman-based services (quadlets) with deterministic network identities
- DNS zones and records for internal and external resolution
- Secrets templates and runtime wiring (bootstrap vs runtime)

## Source of Truth

All intent lives in `config/`:

- `config/mapping.yaml` assigns services to hosts
- `config/network.yaml` defines VLANs, addresses, and DNS
- `config/hosts/<host>/host.yaml` defines host composition (config, software, users)
- `config/services/<service>/service.yaml` defines per-service behavior

## High-Level Flow

1. Render: generate host-specific configs and templates from `config/`.
1. Apply: validate, stage, and apply changes with drift detection.

## Reconciliation

Abhaile follows a reconciliation pattern: the desired state lives in git, the current state is read and compared for drift, and apply actions are idempotent. This keeps hosts converging toward the declared intent without relying on manual changes.

## How It Works

Render transforms `config/` into host-scoped artifacts. Apply compares them against live state using SHA-256 drift detection and reconciles atomically. See [Architecture](docs/ARCHITECTURE.md) for diagrams and detail.

Key rules:

- No secrets in git or rendered output — see [Secrets](docs/reference/secrets.md)
- Environment paths are configurable — see [ADR 0001](docs/adr/0001-output-root-and-environment-paths.md)
- State is apply-owned, updated only after success — see [ADR 0002](docs/adr/0002-hash-based-drift-detection-and-state-model.md)

## Design Principles

- Unprivileged render phase; privileged apply phase
- Atomic apply with validation and rollback safety
- Deterministic `/32` service addressing (ipvlan-l2)
- Split-horizon DNS for internal vs external resolution
- Secrets boundary between bootstrap (encrypted) and runtime (templated)
- Reconciliation pattern: desired state in git, drift analysis, idempotent apply

## Non-Goals

- No manual edits to rendered output
- No ad-hoc changes on hosts outside the GitOps flow
- No secrets committed to the repo

## Dependencies

Runtime dependencies live in requirements.txt. Development tooling lives in requirements-dev.txt, which includes requirements.txt.

- Runtime: install requirements.txt only for production or CI execution.
- Development: use make install to set up the venv, install requirements-dev.txt, and register pre-commit hooks.

## Repository Layout

- `src/abhaile/` - Python package implementation (CLI, renderers, validation, DNS, apply planning)
- `config/` - authoritative intent (source of truth)
  - `mapping.yaml` - service-to-host assignments
  - `network.yaml` - VLANs, addresses, DNS zones/records
  - `hosts/` - host-specific overlays (common, phobos, deimos) with host.yaml
  - `services/` - per-service definitions and templates
  - `_templates/` - shared templates for rendering
- `tests/` - unit and integration pytest suites
- `docs/` - documentation and runbooks
  - `adr/` - architecture decision records for major changes
  - `guides/` - procedural walkthroughs and authoring checklists
  - `reference/` - stable behavior and model references
  - `runbooks/` - operational and recovery procedures
- `scripts/` - executable shell utilities/wrappers
- `paths.ini` - project-wide tooling path configuration
- `out/` - generated artifacts and state (disposable, not source of truth)
  - `rendered/` - ephemeral desired-state artifacts (overwritten on each render)
  - `state/` - persistent metadata (manifests, commit tracking)
- `policies/` - Vault policies for secret management

## CLI Entrypoints

- `abhaile-render` (`abhaile.cli.render:main`) — render desired artifacts (`--host` or `--all`, optional `--output`)
- `abhaile-diff` (`abhaile.cli.diff:main`) — read-only desired vs applied drift summary
- `abhaile-apply` (`abhaile.cli.apply:main`) — reconcile desired state with dry-run and prune safety gates

**Important**: Never edit files under `out/` directly. All changes must be made in `config/` and re-rendered.

Abhaile keeps the configuration declarative and the deployment steps explicit, so changes remain auditable and reversible.

## User Management Merge Semantics

User definitions are merged across `composition.include` by name (includes first, then host):

- Scalar fields (`uid`, `system`, `primary_group`, `home`, `shell`, `gecos`) must match if redefined; mismatches are validation errors.
- List fields (`additional_groups`, `ssh_authorized_keys`) are unioned deterministically.
- Group definitions are merged by name; duplicate `gid` values across different group names are validation errors.
- Duplicate `uid` values across different user names are validation errors.

This keeps common defaults (for example `system: false`) centralized while allowing per-host additions like extra groups.

## Bootstrap

Hosts are initially enrolled via a bootstrap script. See [Bootstrap](docs/guides/bootstrap.md) for details.

## Documentation

| Document | Purpose |
|----------|---------|
| [Architecture](docs/ARCHITECTURE.md) | System design, pipeline diagrams, component map |
| [Operations](docs/runbooks/operations.md) | Day-to-day commands, diagnostics, decision trees |
| [Break-Glass](docs/runbooks/break-glass.md) | Emergency recovery when normal paths are broken |
| [Bootstrap](docs/guides/bootstrap.md) | Host enrollment from bare metal |
| [Secrets](docs/reference/secrets.md) | Credential model, vault-agent, rotation |
| [Inventory](docs/INVENTORY.md) | Service IPs, VLANs, DNS (generated) |
| [Adding a Service](docs/guides/adding-a-service.md) | Step-by-step service authoring checklist |
| [Adding a Kind](docs/guides/adding-a-kind.md) | New artifact kind end-to-end |
| [ADRs](docs/adr/) | Architecture decision records |
| [Specs](docs/specs/) | Feature specs (proposed → active → accepted) |
