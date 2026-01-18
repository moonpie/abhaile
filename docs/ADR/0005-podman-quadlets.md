# ADR 0005: Podman Quadlets for Deterministic Container Networking

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/DEVELOPMENT.md`

## Context

Services require deterministic unit management, ordered startup, and predictable network behavior across hosts.

## Decision

Use systemd quadlets for all Podman containers and networks:

- Quadlets are rendered from service metadata and shared templates.
- Networks are created explicitly per VLAN for `ipvlan-l2`.
- Pod units are used only when multiple containers must share a netns.
- Rootless quadlets are reserved for helper agents (e.g., Vault Agent).

### Implementation Notes

- Pure builders: `build_quadlet_outputs`, `build_container_service_outputs`, and `build_pod_service_outputs` return destination paths + content; they do not perform file I/O.
- Orchestrator-only I/O: `cli.py` writes quadlet outputs, logs, and stages shared volume units; thin wrappers (`render_quadlets`, `render_container_service`, `render_pod_service`) remain for test compatibility.
- Shared volumes: `build_volume_unit_outputs` deduplicates shared `.volume` units and emits to `_shared/home/.../systemd` for rootless and `_shared/etc/containers/systemd` for rootful.

## Consequences

- ✅ Units are managed by systemd with predictable lifecycle.
- ✅ Network declarations are audited and versioned.
- ⚠️ Quadlet syntax must remain compatible with host systemd.

## Alternatives Considered

- **Raw podman commands**: rejected due to lack of declarative state.
- **Docker Compose**: rejected to avoid runtime drift and mismatched unit semantics.
