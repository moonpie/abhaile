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

The output root always contains two subdirectories:

- `rendered/` — ephemeral desired-state artifacts
- `state/` — persistent metadata (manifests, commit tracking)

### Host Default

- **Output root:** `/var/lib/abhaile/`
- **Single-host render:** `/var/lib/abhaile/rendered/` and `/var/lib/abhaile/state/`
- **Live target root:** `/`

### Workstation/CI Override

Use `--output <dir>` to set a local output root.

**Single-host render:**

```text
--output ./out
    ./out/rendered/<host>/
    ./out/state/<host>/
```

**Multi-host render:**

```text
--output ./out --all
    ./out/<host>/rendered/
    ./out/<host>/state/ (for each host)
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
