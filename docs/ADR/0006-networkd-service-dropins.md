# ADR 0006: systemd-networkd Drop-Ins for Service `/32`s

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/NETWORK.md`, `docs/ARCHITECTURE.md`

## Context

Service `/32` addresses must persist across re-renders and be easy to migrate between hosts. Monolithic network files are brittle and hard to diff.

## Decision

Render one drop-in file per service:

- `service-addr.conf` drop-ins add `/32` addresses on host interfaces.
- `service-route.conf` drop-ins add routes for container service `/32`s.
- Drop-ins are placed under the correct `ipvlan-l2[.vlan_id]` directory.

## Consequences

- ✅ `/32` addresses survive host reboots and re-renders.
- ✅ Migrations are simple: move the drop-in to another host and reapply.
- ⚠️ Requires consistent VLAN metadata and ordering rules.

## Alternatives Considered

- **Single merged config file**: rejected due to noisy diffs and fragility.
- **Custom scripting at boot**: rejected due to drift risk.

## Notes

Drop-in filenames are ordered by last octet (`NNN-<service>.conf`) for stable diffs.
