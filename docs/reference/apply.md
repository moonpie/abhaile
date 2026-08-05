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

- Rootless service restarts target the user's systemd manager with
  `systemctl --user -M <user>@`.
- The restart user comes from `podman.user`.

### Dry-run behavior

- `abhaile-apply --dry-run` never dispatches service owner actions.
- Dry-run reports drift only; restart, directory enforcement, and other mutations are skipped.
- Registry image acquisitions are reported in `image_acquisitions` JSON output but are not
  pulled during a normal dry-run.
- Managed build transactions are reported in `build_transactions` JSON output but are not started
  during a normal dry-run.

## Registry Image Acquisition

Registry-backed Quadlet containers render direct image references in their `.container` files:

```ini
[Container]
Image=ghcr.io/0xerr0r/blocky:v0.27.0
Pull=missing
```

Abhaile does not render a separate `.image` Quadlet for normal registry images. `Pull=missing`
lets Podman start from local storage during boot and contact the registry only when the desired
image is absent.

Before a live apply stages a changed registry-backed `.container`, apply uses manifest
`apply_hints` to plan explicit `pre-pull` actions. It pulls the desired image in the same Podman
context as the service: rootful storage for rootful services, or the configured `podman.user`
storage for rootless services.

On Podman 5.4.2, apply uses `podman pull IMAGE`, verifies with `podman image exists IMAGE`, and
records diagnostics from `podman image inspect IMAGE`. Abhaile does not pass `--policy`, and
rendered Quadlets do not use `Policy=`.

The transaction order is:

1. Compare the desired image reference with the previously applied reference.
1. Pull and verify the new image if acquisition is required.
1. Stage the changed `.container` and remove any obsolete managed `.image` artifact.
1. Run the appropriate systemd daemon reload.
1. Restart and verify the generated service.
1. Update applied state only after the apply transaction succeeds.

If pre-pull fails, apply stops before writing the new `.container`, before removing the old
`.image` migration artifact, before daemon reload, and before updating applied state. The running
service is left unchanged. If a later restart or health step fails, normal apply failure handling
preserves the last successful applied state; pulled images are left in local storage for manual
cleanup.

Use immutable version tags or digests for normal updates. Mutable tags are not refreshed at boot;
refreshing an unchanged mutable tag is not an implicit reconciliation behavior.

## Managed Build Transactions

Managed `.build` Quadlets are a separate GitOps transaction type. They render `Pull=missing`, which
only controls acquisition of missing base images referenced by `FROM`; it does not make build steps
such as `apt update`, `git clone`, `curl`, or `go get` work offline. Builds are therefore started
only by apply when the declared build input fingerprint changes, never by ordinary boot recovery.

Build metadata declares the output image, input files, optional post-build action, and consumers.
Apply stages build inputs and the `.build` Quadlet, reloads systemd, verifies the generated build
unit, starts it, verifies the output image in the correct Podman store, runs any post-build action,
then restarts consumers. Applied state is updated only after the whole transaction succeeds.

CoreDNS is modeled through the generic build transaction by declaring `post_build.install_unit` and
`post_build.verify_binary`; it is not a planner special case.

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
| `vault` | `service.config`, `service.env` | `vault.service` |

### Explicit no-direct-restart coverage

| Service | Artifact family | Reason |
| --- | --- | --- |
| `authelia` | `service.config` | Static users database; secret refreshes are handled by copy/path units |
| `caddy-dmz` | `service.config` | Caddy image build input; runtime Caddyfile and DNS env have separate handling |
| `coredns-clean` | included `service.config` | CoreDNS Omada build input; CoreDNS runtime config uses `coredns.config` |
| `coredns-filtered` | included `service.config` | CoreDNS Omada build input; CoreDNS runtime config uses `coredns.config` |
| `omada-controller` | `service.config` | First-boot MongoDB init input and helper/systemd units; runtime env refresh is handled by Omada env copy/path units |

## Related files

- [schemas/service.schema.json](../../schemas/service.schema.json)
- [docs/specs/accepted/0009-apply-pipeline.md](../specs/accepted/0009-apply-pipeline.md)
