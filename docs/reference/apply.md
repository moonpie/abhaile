# Apply Notes

This document records the operator-facing apply behavior that was added for service-owned artifacts.

## `apply.restart_unit`

`apply.restart_unit` lives in `config/services/*/service.yaml`.

Use it when a service emits `service.config` or `service.env` artifacts but does not declare `composition.container` or `composition.pod`.

```yaml
apply:
  restart_unit: chrony.service
```

### Resolution rules

1. If `apply.restart_unit` is set, that explicit value wins.
1. Otherwise, pod-backed services derive `<service>-app.service`.
1. Otherwise, container-backed services derive `<service>.service`.
1. If no explicit or derived restart unit exists, service-owned config writes are treated as no-restart inputs.

### Rootless behavior

- Rootless service restarts run through `systemctl --user`.
- The restart user comes from `podman.user`.

### Dry-run behavior

- `abhaile-apply --dry-run` never dispatches service owner actions.
- Dry-run reports drift only; restart, directory enforcement, and other mutations are skipped.

## Service-owned artifact audit

The April 2026 audit of rendered `service.config` / `service.env` entries produced the following buckets.

### Explicit restart coverage

| Service | Artifact family | Restart unit |
| --- | --- | --- |
| `chrony-a` | `service.config` | `chrony.service` |
| `chrony-b` | `service.config` | `chrony.service` |

### Derived restart coverage

| Service | Artifact family | Derived runtime unit |
| --- | --- | --- |
| `authelia` | `service.config` | `authelia-app.service` |
| `blocky` | `service.config` | `blocky.service` |
| `caddy-dmz` | `service.config` | `caddy-dmz.service` |
| `omada-controller` | `service.env` | `omada-controller.service` |
| `vault` | `service.config`, `service.env` | `vault.service` |
| `vault-agent` | `service.config` | `vault-agent.service` |

### Intentional no-restart service input

| Service | Artifact | Reason |
| --- | --- | --- |
| `coredns-omada` | `/srv/build/coredns-omada/Containerfile` | build-time input; no service runtime unit is derived or explicitly declared |

## Related files

- [schemas/service.schema.json](../../schemas/service.schema.json)
- [docs/specs/accepted/0009-apply-pipeline.md](../specs/accepted/0009-apply-pipeline.md)
