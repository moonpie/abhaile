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

## Render Pipeline Sections

Render should be structured into clear functions:

- Host networking (systemd-networkd, VLANs, ipvlan-l2)
- Host software and base system settings
- Host users and access controls
- Service quadlets for containers (& pods) (rootful & rootless)
- Service-specific configs (DNS, ingress, secrets, app configs)

## Render Stage Interfaces

- Networking: inputs `config/network.yaml`, outputs networkd units/drop-ins
- Software: inputs host `host.yaml` composition.software config, outputs merged package list and per-entry software specs
- Users: inputs host `host.yaml` composition.user_management config, outputs user/group and SSH config
- Quadlets: inputs per-service config, outputs network/volume/image/build/container/pod units
- Service configs: inputs per-service config and network data, outputs DNS, ingress, and templates

## Expected Artifacts

- systemd-networkd units and drop-ins (interfaces, VLANs, ipvlan-l2)
- Host software and base system configuration (packages, kernel modules, sysctl, etc.)
- Host users and access configuration (accounts, groups, sudo, SSH)
- Podman quadlets (as applicable)
  - networks
  - volumes
  - images
  - build
  - containers
  - pods
- Service-specific configuration artifacts (DNS zones/records, ingress, secrets, per-service configs)
- Systemd units/timers for GitOps sync and service reloads (if applicable)

Apply should:

- Validate rendered output and config inputs
- Stage changes atomically
- Update state metadata for drift detection
- Reload or restart impacted services

## Design Principles

- Unprivileged render phase; privileged apply phase
- Atomic apply with validation and rollback safety
- Deterministic `/32` service addressing (ipvlan-l2)
- Split-horizon DNS for internal vs external resolution
- Secrets boundary between bootstrap (encrypted) and runtime (templated)
- Reconciliation pattern: desired state in git, drift analysis, idempotent apply

## Secrets Policy

Abhaile enforces a strict secrets boundary across bootstrap, render/apply, and runtime.

### Artifact Classes

- **Committed templates/specs (in `config/`)**: service specs, placeholder-based config, `*.ctmpl` sources, and template metadata. These may define secret references and destination paths, but must never contain resolved secret values.

- **Rendered non-secret configs (`<output>/rendered/`)**: artifacts derived from repo data that are strictly non-secret. These are allowed only when content contains no credentials, tokens, private keys, decrypted material, or other secret values. Template sources and destination metadata may be rendered or copied.

- **Host-only secret outputs (runtime/bootstrap on host)**: Vault-rendered env files, app configs containing credentials, token files, private keys, and decrypted bootstrap assets. These are host-local only and must not be committed or written to repo-managed render output.

### Boundary Rules

- No secrets in git.
- No resolved secret values in repo-managed rendered output.
- `config/` remains source of truth for desired structure and secret references, not secret payloads.
- External secret material is required at bootstrap/runtime and delivered outside git.
- Render remains unprivileged and deterministic; apply remains privileged and enforces host reconciliation.

### Ownership

- **Bootstrap:** establishes initial trust/access, may use sealed bootstrap artifacts.
- **Apply:** reconciles host state and wiring, but does not materialize resolved secret values into repo-managed output.
- **Runtime:** Vault Agent renders resolved secrets to host-only destinations for service consumption.

### External Key/Token/Cert Material Contract

Apply installs references (units, watches, mounts, and directories) for external secret material, but does not install secret files.

| Artifact / Path | Class | Owner:Group | Mode | Producer / Provisioning | Responsible phase |
| --- | --- | --- | --- | --- | --- |
| `/home/abhaile/.config/vault-agent/token` | Bootstrap-only input (Vault auth seed token file) | `abhaile:abhaile` | `0600` | Operator/Bootstrap provides host-local token out-of-band; never from git render output | Bootstrap + Operator |
| `/srv/vault/agent/run/vault-agent-token` | Runtime secret output (Vault Agent sink token) | `abhaile:abhaile` | `0600` | Vault Agent sink writes it at runtime (`config.hcl`) | Runtime (Vault Agent) |
| `/srv/vault/agent/out/.ready` | Runtime readiness sentinel (non-secret) | `abhaile:abhaile` | `0640` | Vault Agent template render (`ready.ctmpl`) | Runtime (Vault Agent) |
| `/srv/vault/agent/out/<template-out>` (for example `authelia.configuration.yml`, `authelia-redis.conf`, `ddclient.conf`, `coredns-omada.env`, `caddy-dns-desec.env`) | Runtime secret-bearing service inputs | `abhaile:abhaile` | `0640` (from each `composition.vault_agent.templates[].perms`) | Vault Agent template rendering from `*.ctmpl` sources | Runtime (Vault Agent) |
| `/srv/caddy/internal/data/certificates/local/omada-controller.svc.abhaile.home.arpa/omada-controller.svc.abhaile.home.arpa.crt` | Runtime certificate input for Omada chain rebuild | service runtime owner (Caddy-managed) | runtime-managed | Caddy internal PKI runtime output; watched by `rebuild-omada-cert.path` | Runtime (service-managed) |
| `/srv/omada-controller/cert` | Runtime certificate bundle destination for Omada | `root:root` | `0750` directory, file modes set by rebuild script | Host-local `rebuild-omada-cert.sh` workflow (operator/bootstrap-managed script path) | Runtime + Operator |
| `/etc/ssl/certs` | Host trust store (non-secret cert roots) | OS-managed | OS-managed | Debian/host package management | Host base system |

Validation stance:

- Apply assumes external secret/key/token files exist at their declared host paths.
- Apply does not pre-validate presence or permissions of secret material.
- Missing/incorrect external material fails in the owning runtime unit (Vault Agent, systemd path/service, or container startup), not in render output generation.

### SOPS Bootstrap Policy (Bootstrap-Only)

`sops` is allowed only for sealed bootstrap artifacts needed before Vault Agent can render runtime secrets.

#### Allowed in Git (encrypted with `sops`)

- Host-scoped, bootstrap-phase credentials required to establish initial trust (for example: one-time enrollment token material or initial Vault bootstrap handoff values).
- Bootstrap-only access material needed to reach control-plane dependencies before Vault Agent is online (for example: short-lived repo access bootstrap credential).

These artifacts must be minimal, host-scoped where possible, and limited to pre-Vault bootstrap.

#### Forbidden in Git (even if encrypted)

- Long-lived runtime service secrets (application passwords, API keys, database credentials, SMTP credentials, JWT secrets).
- Runtime private keys and certificate keypairs used by running services.
- Vault-rendered outputs and any secret material intended for steady-state runtime consumption.

Runtime secret values belong in Vault and are rendered on-host by Vault Agent.

#### Repository Layout and Naming Convention

- Sealed bootstrap artifacts live under `config/bootstrap/sealed/`.
- Artifacts are host-scoped under `config/bootstrap/sealed/<host>/`.
- File naming convention is `<artifact-name>.sops.yaml`.

Examples:

- `config/bootstrap/sealed/phobos/vault-bootstrap.sops.yaml`
- `config/bootstrap/sealed/deimos/repo-bootstrap.sops.yaml`

#### Recipient and Decryption Model

- Encryption recipients use age identities.
- Each sealed artifact must include:
  - a host bootstrap recipient for the target host, and
  - at least one operator-controlled recovery recipient.
- Decryption occurs locally on the target host during bootstrap.
- The decryption identity is provided out-of-band by the operator (not from git).

Current host software assumptions in `config/hosts/common/host.yaml` already include `age` and `sops` installation.

#### Plaintext Handling Rules

- Decrypted bootstrap material must never be committed.
- Bootstrap should consume decrypted values in memory or via short-lived runtime paths only.
- If temporary files are unavoidable, they must be created in an ephemeral runtime location and removed immediately after use.
- Decrypted bootstrap plaintext must not persist under the repo working tree or other durable git-managed paths.

See [ADR 0006](docs/adr/0006-secrets-model-and-bootstrap-artifacts.md) and [ADR 0007](docs/adr/0007-sops-bootstrap-policy-and-layout.md) for the durable architecture decisions.

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
- `scripts/` - executable shell utilities/wrappers
- `paths.ini` - project-wide tooling path configuration
- `out/` - generated artifacts and state (disposable, not source of truth; see Environment Paths section for structure)
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

## Environment Paths

Abhaile is host-first in production and supports flexible paths for workstation/CI.

All tooling reads path configuration from repo-root paths.ini (required).

### Host Default

- **Output root:** `/var/lib/abhaile/`
- **Rendered output:** `/var/lib/abhaile/rendered/`
- **State:** `/var/lib/abhaile/state/`
- **Live target root:** `/`

### Workstation/CI Override

Use `--output <dir>` to set a local output root (e.g., `--output ./out`):

**Single-host render:**

```text
./out/
├── rendered/
│   ├── system/                  (systemd-networkd, resolved - atomic file placement)
│   ├── software/                (packages, downloads, builds - execution required)
│   ├── users/                   (user/group setup, sudoers - execution required)
│   └── services/
│       ├── caddy-dmz/
│       └── vault/
└── (state/ is created by apply, not render)
```

**Multi-host render (`--all`):**

```text
./out/
├── phobos/
│   ├── rendered/
│   │   ├── system/
│   │   ├── software/
│   │   ├── users/
│   │   └── services/
│   └── (state/ created by apply)
└── deimos/
    ├── rendered/
    │   ├── system/
    │   ├── software/
    │   ├── users/
    │   └── services/
  └── (state/ created by apply)
```

The `<host>` subdirectory avoids collisions when rendering multiple hosts into one output tree.

## Drift Detection and State Model

Apply uses hash-based drift detection to compare desired state (manifest) against live system:

1. **Render** produces desired-state artifacts in `<output>/rendered/` organized by type (system/software/users/services), and writes desired manifest `<output>/rendered/manifest.json`
1. **Apply state** stores durable host reconciliation metadata in `<output>/state/`: current applied manifest `<output>/state/manifest.json`, previous applied manifest `<output>/state/manifest.previous.json`, and history archive `<output>/state/history/manifest-<timestamp>.json` (retained, bounded)
1. **Apply** compares desired manifest and applied manifest against live filesystem to detect add/change/remove drift
1. **Sync** copies changed/added files from `rendered/` to `/`, runs scoped owner-based reload and restart actions per artifact family (systemd, users, coredns, caddy, vault, networkd, quadlet), and then updates state manifests on success

Artifacts are organized under `rendered/` by apply method:

- `rendered/system/` — systemd-networkd, resolved, systemd units (atomic file placement)
- `rendered/software/` — package installation, downloads, builds (execution required)
- `rendered/users/` — user/group management, sudoers (execution required)
- `rendered/services/<service>/` — per-service quadlets and configs

This makes it easy to identify which services/hosts are impacted by a change. The manifest still tracks target paths (e.g., `/etc/systemd/network/10-eth0.network`), so the intermediate directory structure is organizational only and does not affect apply.

See [ADR 0001](docs/adr/0001-output-root-and-environment-paths.md) and [ADR 0002](docs/adr/0002-hash-based-drift-detection-and-state-model.md) for design details.

## Bootstrap

Hosts are initially enrolled via a curl-bash style bootstrap script that installs prerequisites, pulls the repo, and registers the GitOps flow on the host.
