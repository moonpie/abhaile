# Apply Notes

This document records the operator-facing apply behavior that was added for service-owned artifacts.

## `apply.config_change_restart_unit`

`apply.config_change_restart_unit` lives in `config/services/*/service.yaml`.

Use it when a mapped service emits `service.config` or `service.env` artifacts.
The check is include-aware: config entries from included services are evaluated
as part of the mapped service that renders them.

```yaml
apply:
  config_change_restart_unit: chrony.service
```

### Resolution rules

1. If `apply.config_change_restart_unit` is set to a unit name, service-owned
   config/env writes try-restart that unit.
1. If `apply.config_change_restart_unit` is set to `null`, service-owned
   config/env writes intentionally do not trigger a direct restart.
1. No pod or container unit name is derived implicitly. Service authors must
   model direct restarts, path units, copy units, or static inputs explicitly.

### Rootless behavior

- Rootless service restarts run through `systemctl --user`.
- The restart user comes from `podman.user`.

### Dry-run behavior

- `abhaile-apply --dry-run` never dispatches service owner actions.
- Dry-run reports drift only; restart, directory enforcement, and other mutations are skipped.

## File Metadata

Apply normalizes non-directory file writes instead of inheriting render-time
ownership or umask.

- User-managed files use explicit `apply_hints` ownership and mode.
- Rootless artifacts use the configured `podman.user` as owner and group,
  with mode `0644`.
- Other managed files are written as `root:root` with mode `0644`.

## Service-owned artifact audit

The April 2026 audit of rendered `service.config` / `service.env` entries produced the following buckets.

### Direct config-change restart coverage

| Service | Artifact family | Restart unit |
| --- | --- | --- |
| `blocky` | `service.config` | `blocky.service` |
| `chrony-a` | `service.config` | `chrony.service` |
| `chrony-b` | `service.config` | `chrony.service` |
| `omada-controller` | `service.config`, `service.env` | `omada-controller.service` |
| `vault` | `service.config`, `service.env` | `vault.service` |

### Explicit no-direct-restart coverage

| Service | Artifact family | Reason |
| --- | --- | --- |
| `authelia` | `service.config` | Static users database; secret refreshes are handled by copy/path units |
| `caddy-dmz` | `service.config` | Caddy image build input; runtime Caddyfile and DNS env have separate handling |
| `coredns-clean` | included `service.config` | CoreDNS Omada build input; CoreDNS runtime config uses `coredns.config` |
| `coredns-filtered` | included `service.config` | CoreDNS Omada build input; CoreDNS runtime config uses `coredns.config` |

## Related files

- [schemas/service.schema.json](../../schemas/service.schema.json)
- [docs/specs/accepted/0009-apply-pipeline.md](../specs/accepted/0009-apply-pipeline.md)
