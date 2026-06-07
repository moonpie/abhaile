# Spec: Inventory Generator

## Metadata

```yaml
id: SPEC-2026-022
title: Inventory Generator
status: proposed
owner: moonpie
created: 2026-06-07
updated: 2026-06-07
related_adrs: []
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

`abhaile-inventory` currently prints a simple host→services list or JSON dump. Operators lack
a single generated reference document showing the full network and service layout — IP
assignments, VLAN topology, DNS zones, and per-service network modes. This information exists
across `config/mapping.yaml`, `config/network.yaml`, and per-service `service.yaml` files but
requires manual cross-referencing.

Extending the existing CLI to produce a comprehensive markdown inventory document gives
operators a generated, always-accurate reference without maintaining a separate hand-written
doc.

## Requirements

- [ ] Extend `abhaile-inventory` with `--format {table,markdown,json}` flag (default: `table`,
  preserving current behavior).
- [ ] Add `--output PATH` flag to write output to a file instead of stdout.
- [ ] Markdown output includes all sections defined in Design.
- [ ] `make docs` target generates `docs/INVENTORY.md`.
- [ ] Existing `--json` flag becomes an alias for `--format json`.
- [ ] Existing `--validate` flag works with all formats.

## Constraints

- No new dependencies. Markdown is generated with string formatting.
- Read-only operation; no config mutation.
- Render is not required — inventory reads config sources directly.
- Output is deterministic for identical config input.
- Follows existing coding conventions (type annotations, `RenderError` on config issues,
  module-level `LOG`).

## Design

### CLI Changes

```text
abhaile-inventory [--format {table,markdown,json}] [--output PATH] [--validate]
```

- `--format table` — current behavior (host/service list to stdout).
- `--format markdown` — full inventory document.
- `--format json` — machine-readable JSON with all collected data.
- `--output PATH` — write to file; omit for stdout.
- `--json` — retained as alias for `--format json` (backward compat).
- `--validate` — check service definitions exist; combinable with any format.

### Data Collection

Module: `src/abhaile/cli/inventory.py` (extend existing) or extract collection logic to
`src/abhaile/inventory/collector.py` if the module exceeds ~200 lines.

Data gathered from:

| Source | Fields extracted |
| --- | --- |
| `config/mapping.yaml` | host→service assignments, service ordering |
| `config/network.yaml` `vlans` | name, id, cidr, gateway, ipvlanl2_range |
| `config/network.yaml` `hosts` | host interfaces, per-interface address/vlan |
| `config/network.yaml` `services` | address, vlan, dns records per service |
| `config/network.yaml` `dns.zones` | zone names, provider type, serial metadata |
| `config/services/*/service.yaml` | `podman.user`, `podman.network`, `systemd.network` |

Service YAML is loaded only for services present in `mapping.yaml`. Missing `service.yaml`
files produce a warning row (network mode = `unknown`) rather than aborting — unless
`--validate` is set, in which case they fail as today.

### Markdown Output Sections

#### 1. Header and Metadata

```markdown
# Abhaile Service & Network Inventory

> Generated: 2026-06-07T08:31:49+01:00
> Sources: config/mapping.yaml, config/network.yaml, config/services/*/service.yaml
```

#### 2. VLAN Summary

| Name | ID | CIDR | Gateway | ipvlan-l2 Range |
| --- | --- | --- | --- | --- |
| services | 20 | 172.20.20.0/24 | 172.20.20.1 | 172.20.20.200–254 |
| dmz | 100 | 172.20.100.0/24 | 172.20.100.1 | 172.20.100.200–254 |

Sorted by VLAN ID.

#### 3. Hosts

| Host | Interface | Address | VLAN |
| --- | --- | --- | --- |
| phobos | enp0s31f6 | 172.20.20.10/24 | services |
| phobos | enp0s31f6.100 | 172.20.100.10/24 | dmz |
| deimos | enp0s31f6 | 172.20.20.11/24 | services |

Sorted by host name, then interface name.

#### 4. Services by Host

One subsection per host (sorted alphabetically):

```markdown
### phobos

| Service | Address | VLAN | Network Mode | User |
| --- | --- | --- | --- | --- |
| caddy-internal | 172.20.20.200/32 | services | ipvlan-l2 | root |
| vault-agent | — | — | host | abhaile |
```

Within each host, services appear in mapping order. Address/VLAN come from
`network.services.<name>`. Network mode and user come from service.yaml
(`podman.network` or `systemd.network`). Services without a network entry show `—`.

#### 5. Address Allocation

Full sorted table of all /32 service addresses across both hosts:

| Address | Service | VLAN | Host(s) |
| --- | --- | --- | --- |
| 172.20.20.200/32 | caddy-internal | services | phobos |
| 172.20.20.201/32 | authelia | services | phobos |
| ... | | | |

Sorted by IP (numeric). Host(s) derived from mapping — a service on both hosts appears once
with comma-separated hosts.

#### 6. DNS Summary

| Zone | Type | Provider | Records |
| --- | --- | --- | --- |
| svc.abhaile.home.arpa. | internal | coredns-common | 42 |
| abhaile.home.arpa. | internal | coredns-common | 15 |
| abhaile.dedyn.io. | external | desec.io | 1 |

Record count is the sum of records from `hosts.*.dns` + `services.*.dns` entries that
reference the zone, plus any inline `dns.zones[].records`. Sorted by zone name.

### JSON Output Structure

When `--format json`:

```json
{
  "generated_at": "2026-06-07T08:31:49+01:00",
  "vlans": { "<name>": { "id": 20, "cidr": "...", "gateway": "...", "ipvlanl2_range": "..." } },
  "hosts": { "<name>": { "interfaces": {...}, "services": ["..."] } },
  "services": { "<name>": { "address": "...", "vlan": "...", "network_mode": "...", "user": "...", "hosts": ["..."] } },
  "dns_zones": [ { "name": "...", "type": "...", "provider": "...", "record_count": 42 } ]
}
```

### Makefile Integration

```makefile
docs: $(VENV)
    $(VENV_PYTHON) -m abhaile.cli.inventory --format markdown --output docs/INVENTORY.md
```

Add `docs` to the `.PHONY` list.

### IP Sort Helper

Parse IPv4 addresses to integer tuples for sorting. Use `ipaddress.ip_address` from stdlib
(already available, no new dep).

## Decision Notes

- Decision: Extend existing `inventory.py` rather than a new entrypoint.
  Rationale: The functionality is a superset of current behavior; avoids proliferating CLI tools.
  Impact: `--json` becomes an alias; existing scripts continue to work.

- Decision: Markdown generation uses plain string formatting, not a template engine.
  Rationale: Output is table-heavy and straightforward; Jinja2 adds no value here.
  Impact: Simple, no new dependency.

- Decision: Missing service.yaml produces warning row in non-validate mode.
  Rationale: Inventory should be useful even with incomplete config (e.g., stub services not yet fleshed out).
  Impact: Operators see `unknown` network mode for stubs; `--validate` still fails hard.

## Acceptance Criteria

- [ ] `abhaile-inventory --format markdown` produces all six sections with correct data from config files.
- [ ] `abhaile-inventory --format json` produces the documented JSON structure.
- [ ] `abhaile-inventory` (no flags) preserves current table output (backward compatible).
- [ ] `--output docs/INVENTORY.md` writes to file instead of stdout.
- [ ] `--validate` exits non-zero on missing service definitions with all formats.
- [ ] `make docs` generates `docs/INVENTORY.md` from current config.
- [ ] Address allocation table is sorted by numeric IP.
- [ ] DNS record counts are accurate across host/service/inline records.
- [ ] Output is deterministic for identical config input.
- [ ] Unit tests cover: markdown section generation, JSON structure, IP sorting, missing service handling.
- [ ] No regressions in existing inventory tests.

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- Rendered artifact inventory (manifest contents) — that's `abhaile-diff` territory.
- Runtime state (what's actually running vs what's configured).
- Service dependency graphs or boot ordering visualization.
- HTML output format.

## Open Questions

None.

## References

- `src/abhaile/cli/inventory.py` (current implementation)
- `config/mapping.yaml`
- `config/network.yaml`
- `docs/specs/accepted/0013-ops-tooling.md` (SPEC-2026-013 — original inventory task)
- `Makefile`
