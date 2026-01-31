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
- Packaging: inputs host/software config, outputs package/command directives
- Users: inputs host/users config, outputs user/group and SSH config
- Quadlets: inputs per-service config, outputs network/volume/image/build/container/pod units
- Service configs: inputs per-service config and network data, outputs DNS, ingress, and templates

## Expected Artifacts

Render should produce, per host:

- systemd-networkd units and drop-ins (interfaces, VLANs, ipvlan-l2)
- Host packaging and base system configuration (packages, kernel modules, sysctl, etc.)
- Host users and access configuration (accounts, groups, sudo, SSH)
- Podman quadlets (ass applicable)
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

- `config/` - authoritative intent
- `docs/` - documentation and runbooks
- `docs/adr/` - architecture decision records for major changes
- `tools/` - renderer and apply pipeline
- `out/` - generated artifacts and state (not source of truth)

Abhaile keeps the configuration declarative and the deployment steps explicit, so changes remain auditable and reversible.

## Bootstrap

Hosts are initially enrolled via a curl-bash style bootstrap script that installs prerequisites, pulls the repo, and registers the GitOps flow on the host.
