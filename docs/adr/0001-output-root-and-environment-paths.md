# ADR 0001: Output Root and Environment Paths

## Status

2026-05-05: Updated Accepted
2026-01-31: Accepted

## Context

Abhaile runs in two contexts:

- **Host (production)**: single-host render/apply and scheduled reconciliation
- **Workstation/CI**: development, validation, and optional multi-host rendering

The project needs a stable output root on hosts that survives repo updates, while still allowing local overrides for workstation and CI use. The output structure also needs to express ownership boundaries clearly: render owns desired-state artifacts, while apply owns durable applied-state records.

## Decision

### Output Root Structure

The output root always contains two top-level subdirectories:

- `rendered/` — ephemeral, render-owned desired-state artifacts
- `state/` — durable, apply-owned state and history

### Rendered Artifact Organization

Artifacts under `rendered/` are organized by apply method:

- `rendered/system/` — atomic file placement artifacts such as systemd-networkd, resolved, and systemd units
- `rendered/software/` — execution-required software artifacts such as `packages.txt`, downloads, builds, and commands
- `rendered/users/` — execution-required user-management artifacts
- `rendered/services/<service>/` — service-specific artifacts such as quadlets, configs, and ingress material

The desired manifest is written as `rendered/manifest.json`. The rendered tree is disposable and may be wiped before each render. Its layout is organizational only; apply uses manifest target paths to reconcile the host.

### State Ownership

Apply owns `state/` and maintains durable state there, including:

- `state/manifest.json` — last successfully applied manifest
- `state/manifest.previous.json` — prior successfully applied manifest
- `state/history/` — timestamped apply history entries

### Host Default

- **Output root:** `/var/lib/abhaile/`
- **Single-host render root:** `/var/lib/abhaile/rendered/`
- **Single-host state root:** `/var/lib/abhaile/state/`
- **Live target root:** `/`

### Workstation/CI Override

Use `--output <dir>` to set a local output root.

Single-host example:

```text
./out/
├── rendered/
│   ├── manifest.json
│   ├── system/
│   ├── software/
│   ├── users/
│   └── services/
└── state/
```

Multi-host rendering may use per-host subdirectories under the chosen output root to avoid collisions.

### Live Target Root

- Apply always targets `/` on hosts
- No alternate live-root support is provided

## Alternatives Considered

- **Always include `<host>` on production hosts**: rejected because it adds path complexity without improving single-host production safety.
- **Write output under the repo checkout**: rejected because it couples durable state to a mutable checkout location.
- **Store the desired manifest under `state/`**: rejected because it weakens the ownership boundary between render-owned desired artifacts and apply-owned durable applied state.

## Consequences

- Hosts have a stable output root independent of repo location
- Render output is explicitly ephemeral and disposable
- Desired-state and applied-state ownership are separated cleanly
- Workstation/CI can reproduce host-like output layout with a local override
- Future runner/bootstrap tooling can rely on a stable path contract

## References

- ADR 0002: Hash-based Drift Detection and State Model
