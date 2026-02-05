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
- Host packaging and base system settings
- Host users and access controls
- Service quadlets for containers (& pods) (rootful & rootless)
- Service-specific configs (DNS, ingress, secrets, app configs)

## Render Stage Interfaces

- Networking: inputs `config/network.yaml`, outputs networkd units/drop-ins
- Packaging: inputs host `host.yaml` composition.software config, outputs package/command directives
- Users: inputs host `host.yaml` composition.user_management config, outputs user/group and SSH config
- Quadlets: inputs per-service config, outputs network/volume/image/build/container/pod units
- Service configs: inputs per-service config and network data, outputs DNS, ingress, and templates

## Expected Artifacts

- systemd-networkd units and drop-ins (interfaces, VLANs, ipvlan-l2)
- Host packaging and base system configuration (packages, kernel modules, sysctl, etc.)
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

## Non-Goals

- No manual edits to rendered output
- No ad-hoc changes on hosts outside the GitOps flow
- No secrets committed to the repo

## Repository Layout

- `config/` - authoritative intent (source of truth)
  - `mapping.yaml` - service-to-host assignments
  - `network.yaml` - VLANs, addresses, DNS zones/records
  - `hosts/` - host-specific overlays (common, phobos, deimos) with host.yaml
  - `services/` - per-service definitions and templates
  - `_templates/` - shared templates for rendering
- `docs/` - documentation and runbooks
  - `adr/` - architecture decision records for major changes
- `scripts/` - render and apply pipeline scripts
- `out/` - generated artifacts and state (disposable, not source of truth; see Environment Paths section for structure)
  - `rendered/` - ephemeral desired-state artifacts (overwritten on each render)
  - `state/` - persistent metadata (manifests, commit tracking)
- `policies/` - Vault policies for secret management

**Important**: Never edit files under `out/` directly. All changes must be made in `config/` and re-rendered.

Abhaile keeps the configuration declarative and the deployment steps explicit, so changes remain auditable and reversible.

## Environment Paths

Abhaile is host-first in production and supports flexible paths for workstation/CI.

All tooling reads path configuration from scripts/paths.ini (required).

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
└── state/
    └── manifest.json
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
│   └── state/
└── deimos/
    ├── rendered/
    │   ├── system/
    │   ├── software/
    │   ├── users/
    │   └── services/
    └── state/
```

The `<host>` subdirectory avoids collisions when rendering multiple hosts into one output tree.

## Drift Detection and State Model

Apply uses hash-based drift detection to compare desired state (manifest) against live system:

1. **Render** produces desired-state artifacts in `<output>/rendered/` organized by type (system/software/users/services), and writes a manifest to `<output>/state/manifest.json`
1. **Manifest** contains SHA256 hashes, sizes, permissions, and ownership for each file
1. **Apply** compares manifest hashes against live filesystem to detect changes
1. **Sync** copies changed/added files from `rendered/` to `/` and updates manifest

Artifacts are organized under `rendered/` by apply method:

- `rendered/system/` — systemd-networkd, resolved, systemd units (atomic file placement)
- `rendered/software/` — package installation, downloads, builds (execution required)
- `rendered/users/` — user/group management, sudoers (execution required)
- `rendered/services/<service>/` — per-service quadlets and configs

This makes it easy to identify which services/hosts are impacted by a change. The manifest still tracks target paths (e.g., `/etc/systemd/network/10-eth0.network`), so the intermediate directory structure is organizational only and does not affect apply.

See [ADR 0001](docs/adr/0001-output-root-and-environment-paths.md) and [ADR 0002](docs/adr/0002-hash-based-drift-detection-and-state-model.md) for design details.

## Bootstrap

Hosts are initially enrolled via a curl-bash style bootstrap script that installs prerequisites, pulls the repo, and registers the GitOps flow on the host.
