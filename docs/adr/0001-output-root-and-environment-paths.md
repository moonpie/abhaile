# ADR 0001: Output Root and Environment Paths

## Status

2026-01-31: Accepted

## Context

Abhaile runs in two contexts:

- **Host (production)**: single-host render and apply via systemd timer
- **Workstation/CI**: single-host or multi-host renders for development and validation

We need a single, predictable output root on hosts that persists across repo updates, while allowing flexible overrides for workstation/CI. The render/apply flow is host-first and single-host by default; multi-host is only for workstation/CI validation.

## Decision

### Output Root Structure

The output root always contains two top-level subdirectories:

- `rendered/` — ephemeral desired-state artifacts, organized by source (host vs service)
- `state/` — persistent metadata (manifests, commit tracking)

### Rendered Artifact Organization

Artifacts under `rendered/` are organized by apply method:

- `rendered/system/` — system configuration files (systemd-networkd, resolved, systemd units) - atomic file placement
- `rendered/software/` — software installation artifacts (packages, downloads, builds, commands) - execution required
- `rendered/users/` — user management artifacts (user/group setup, sudoers) - execution required
- `rendered/services/<service>/` — service-specific artifacts (quadlets, configs, ingress)

This organization makes it easy to identify which artifacts require execution versus atomic file placement. The manifest in `state/` still tracks target paths (e.g., `/etc/systemd/network/10-eth0.network`), so the intermediate directory structure is organizational only and does not affect apply.

### Host Default

- **Output root:** `/var/lib/abhaile/`
- **Single-host render:** `/var/lib/abhaile/rendered/` and `/var/lib/abhaile/state/`
- **Live target root:** `/`

### Workstation/CI Override

Use `--output <dir>` to set a local output root.

**Single-host render:**

```text
--output ./out
    ./out/rendered/
    │   ├── system/
    │   │   ├── etc/systemd/network/
    │   │   ├── etc/systemd/resolved.conf
    │   │   └── etc/systemd/system/
    │   ├── software/
    │   │   ├── packages.txt
    │   │   ├── downloads/
    │   │   │   └── <id>.yaml
    │   │   ├── builds/
    │   │   │   └── <id>.yaml
    │   │   └── commands/
    │   │       └── <id>.yaml
    │   ├── users/
    │   │   ├── setup-users.sh
    │   │   └── etc/sudoers.d/abhaile
    │   └── services/
    │       ├── caddy-dmz/
    │       │   ├── etc/containers/systemd/caddy-dmz.container
    │       │   └── srv/caddy-dmz/Caddyfile
    │       └── vault/
    │           ├── etc/containers/systemd/vault.container
    │           └── srv/vault/config.json
    └── ./out/state/
        └── manifest.json
```

**Multi-host render:**

```text
--output ./out --all
    ./out/<host>/rendered/
    │   ├── system/
    │   ├── software/
    │   ├── users/
    │   └── services/
    ./out/<host>/state/
        └── manifest.json
(for each host)
```

The `<host>` subdirectory is included in workstation/CI to avoid collisions when rendering multiple hosts into one output tree.

### Live Target Root

- Apply always targets `/` on hosts
- No alternate root support (simplifies atomicity and safety gates)

## Alternatives Considered

### A. Always include `<host>` on hosts

Redundant for single-host production runs and complicates paths without clear benefit.

### B. Use repo-local `./out/` on hosts

Couples render/apply to repo checkout state; output becomes ephemeral across pulls or cleans.

### C. Environment variables for path configuration

More error-prone than explicit `--output` overrides; harder to reason about in scripts and logs.

## Consequences

- Hosts have a stable output root independent of repo location
- Render output is ephemeral; manifest in state/ is the durable record
- Workstation/CI can use a single `--output` override to produce same structure as host
- Multi-host validation is safe (no path collisions)
- Scripts must handle path selection logic: include `<host>` for multi-host, omit for single-host

## References

- TODO.md: Foundations / Define environment paths
- ADR 0002: Hash-based Drift Detection and State Model
