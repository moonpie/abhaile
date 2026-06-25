# Spec: Podman Runtime Drift Audit

## Metadata

```yaml
id: SPEC-2026-026
title: Podman Runtime Drift Audit
status: proposed
owner: moonpie
created: 2026-06-25
updated: 2026-06-25
related_adrs:
  - 0004-apply-execution-model
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

During clean-room bootstrap and post-reboot recovery, phobos exposed a runtime drift class that the
file-manifest apply model does not fully detect. The rendered Authelia quadlet volume file correctly
declared:

```text
Device=/srv/authelia/authelia/config
```

but the existing podman named volume still pointed to the older bind source:

```text
/srv/authelia/config
```

`podman volume create --ignore` does not update options on an existing named volume. The rendered
file and applied manifest can therefore be correct while the live podman runtime object remains
wrong.

The same class can affect podman networks. A stale netavark network can keep old subnet, gateway, or
option values even when the rendered `.network` quadlet is correct. Containers, pods, images, build
outputs, and generated systemd units can also drift, though volumes and networks have the clearest
configuration/runtime mismatch.

The current apply pipeline already recreates changed quadlet volumes and networks when the
rendered quadlet artifact itself changes. This spec covers runtime-object drift where the rendered
artifact is not part of the current write plan, but the existing podman object does not match
desired intent.

## Requirements

- [ ] Define the podman runtime objects Abhaile should audit.
- [ ] Compare live podman named volume options against rendered `.volume` quadlet intent.
- [ ] Compare live podman network options against rendered `.network` quadlet intent.
- [ ] Report missing, stale, and unexpected podman runtime objects in structured output.
- [ ] Provide a safe read-only audit mode that never mutates host state.
- [ ] Provide explicit remediation for stale volume and network objects.
- [ ] Gate destructive remediation behind an explicit operator flag.
- [ ] Preserve the existing default `abhaile-apply` file-manifest behavior.
- [ ] Support rootful and rootless podman contexts.
- [ ] Keep remediation owner-scoped so dependent services are stopped and restarted predictably.
- [ ] Document operational procedures for inspecting and remediating runtime drift.
- [ ] Add tests for volume, network, rootless, and destructive-gate behavior.

## Constraints

- Default apply must remain deterministic and file-manifest based.
- Dry-run and audit modes must not mutate podman objects, systemd state, or apply state.
- Runtime audit must not require Vault access or decrypted secrets.
- Runtime audit must not inspect container filesystem contents.
- Runtime audit must not remove or recreate data-bearing volumes without explicit destructive
  approval.
- Remediation must avoid deleting active podman networks or volumes until dependent containers and
  pods are stopped through the existing owner dependency model.
- Runtime object comparison must use structured podman output where available.
- The first implementation should avoid new Python dependencies.
- Runtime drift state must not be written to `out/rendered/`.
- Runtime audit output must be suitable for runbooks and CI-like diagnostics, but CI must not depend
  on a live podman host.

## Design

### Scope Of Runtime Objects

The initial audit covers podman runtime objects whose desired state is declared by quadlet files:

| Object | Desired source | Live source | Initial action |
| --- | --- | --- | --- |
| Named volume | rendered `.volume` file | `podman volume inspect` | audit + optional recreate |
| Network | rendered `.network` file | `podman network inspect` | audit + optional recreate |

Follow-up support may cover containers, pods, images, and build outputs. These are lower priority
because systemd and podman usually recreate containers and pods on restart. Images and build outputs
need separate update policy because tags and local build cache can legitimately differ from remote
state.

### Interface

Preferred interface:

```text
abhaile-runtime-audit --host <host> --output /var/lib/abhaile
abhaile-runtime-audit --host <host> --output /var/lib/abhaile --json
abhaile-runtime-audit --host <host> --output /var/lib/abhaile --remediate --allow-destructive
```

`abhaile-runtime-audit` should load the rendered manifest and rendered quadlet files for the target
host. It should not read or modify apply state except where it needs the rendered manifest path.

An `abhaile-apply --runtime-checks` integration may be added later, but the first implementation
should keep runtime auditing separate from normal apply. This preserves the existing apply contract
and makes destructive remediation an explicit operator action.

### Volume Comparison

For each rendered `quadlet.volume` artifact:

1. Parse desired `Device=`, `Options=`, and volume name from the rendered `.volume` file.
1. Resolve the podman runtime object name using the existing quadlet naming rule
   (`systemd-<volume-stem>`).
1. Inspect the matching podman volume in the correct podman context.
1. Compare relevant fields:
   - `Options.device`
   - `Options.o`
   - driver, where non-default driver support is later introduced
1. Report:
   - `missing` when the volume does not exist
   - `stale` when options differ
   - `ok` when options match
   - `unexpected` for unmanaged `systemd-*` volumes when a safe ownership rule can identify them

For remediation, stop dependent owners, remove the stale named volume, restart the volume unit, then
restart dependents. Data-bearing volume remediation requires `--allow-destructive`.

### Network Comparison

For each rendered `quadlet.network` artifact:

1. Parse desired network options from the rendered `.network` file.
1. Resolve the podman runtime object name using the existing quadlet naming rule
   (`systemd-<network-stem>`).
1. Inspect the matching podman network in the correct podman context.
1. Compare supported fields such as subnet, gateway, internal flag, driver, and options.
1. Report `missing`, `stale`, `ok`, or `unexpected`.

For remediation, stop dependent containers and pods, remove the stale network, restart the network
unit, then restart dependents. Network remediation requires `--allow-destructive`.

### Rootless Context

Runtime audit must use manifest owner metadata and apply hints to decide whether a quadlet object is
rootful or rootless. Rootless commands run as the declared podman user, matching the existing
`QuadletExecutor` behavior.

### Output Contract

Human output should be concise:

```text
host=phobos runtime_drift volumes stale=1 missing=0 ok=8 networks stale=0 missing=0 ok=1
stale volume systemd-authelia-app-authelia-config:
  device expected=/srv/authelia/authelia/config actual=/srv/authelia/config
```

JSON output should include stable fields for scripts and runbooks:

```json
{
  "host": "phobos",
  "mode": "audit",
  "objects": [
    {
      "type": "volume",
      "name": "systemd-authelia-app-authelia-config",
      "owner_ref": "unit:authelia-app-authelia-config-volume.service",
      "status": "stale",
      "differences": {
        "device": {
          "expected": "/srv/authelia/authelia/config",
          "actual": "/srv/authelia/config"
        }
      }
    }
  ]
}
```

Secret values must never be included in runtime audit output.

### Remediation Safety

Runtime remediation must be explicit:

- `--remediate` requests mutation.
- `--allow-destructive` is required for volume or network recreation.
- The command must report planned destructive actions before executing. JSON output must include
  the same plan in structured form for automation.
- Active dependents must be stopped through systemd owner actions before object removal.
- Failure to stop dependents must abort remediation.
- Missing objects may be recreated by starting the generated unit and do not require deletion.

### Relationship To Apply

Normal `abhaile-apply` remains the file-manifest reconciler. It should continue to recreate changed
quadlet volumes and networks when the quadlet artifact is in the write plan. Runtime audit covers
the gap where the file is unchanged but the podman object is stale.

If runtime audit becomes common enough, a later implementation may add an apply flag that runs the
read-only audit after file staging. That flag should not become default until runtime, operational
noise, and destructive remediation behavior are proven.

## Decision Notes

- Decision: Runtime podman object drift is modeled as a separate audit/remediation workflow rather
  than default apply behavior.
- Rationale: The existing apply contract is deterministic and file-manifest based. Inspecting every
  podman object on every apply run would add live runtime state to the default reconciliation path.
- Impact: Operators get an explicit tool for stale volume/network recovery without slowing or
  complicating routine GitOps convergence.
- ADR: No new ADR initially. Update ADR 0004 if implementation changes the apply execution model.

## Acceptance Criteria

- [ ] `abhaile-runtime-audit` reports stale named volume `Device=` drift from rendered `.volume`
  intent.
- [ ] `abhaile-runtime-audit` reports stale podman network option drift from rendered `.network`
  intent.
- [ ] JSON output includes host, object type, object name, owner ref, status, and field-level
  differences.
- [ ] Rootless volume/network inspection runs in the declared podman user context.
- [ ] Read-only audit mode does not mutate podman objects, systemd units, or apply state.
- [ ] Remediation refuses volume or network recreation unless `--allow-destructive` is supplied.
- [ ] Remediation stops dependents, recreates stale objects, and restarts dependents in owner order.
- [ ] Existing `abhaile-apply` behavior remains unchanged unless a runtime-check flag is explicitly
  introduced.
- [ ] Operations runbook documents stale podman volume and network diagnosis and remediation.
- [ ] Tests cover volume drift, network drift, missing objects, rootless context, JSON output, and
  destructive-gate failures.
- [ ] `make lint` and `make test-fast` pass.

### Evidence

- Implementation evidence: pending.
- Validation evidence: pending.

## Out of Scope

- Continuous runtime monitoring.
- CI execution against live podman hosts.
- Container filesystem inspection.
- Automatic image update policy.
- Remote registry drift detection.
- Automatic remediation during default GitOps runner apply.
- Generic systemd unit health remediation beyond podman runtime objects.

## Open Questions

1. Should runtime audit be a separate CLI only, or should `abhaile-apply --runtime-checks` be added
   in the first implementation?
1. Which volume classes are safe to recreate automatically? Config bind volumes are lower risk;
   data volumes need stricter handling.
1. Should unexpected unmanaged `systemd-*` podman objects be reported in the first implementation or
   deferred until ownership rules are clearer?
1. Should missing image and build artifacts be part of runtime audit, or remain handled by generated
   image/build units?

## References

- [ADR 0004: Apply Execution Model](../../adr/0004-apply-execution-model.md)
- [ADR 0005: Service Authoring Model](../../adr/0005-service-authoring-model.md)
- [Spec 0004: Quadlet Renderer](../accepted/0004-quadlet-renderer.md)
- [Spec 0009: Apply Pipeline](../accepted/0009-apply-pipeline.md)
- [Spec 0011: Core Services](../accepted/0011-core-services.md)
