# ADR 0002: `/32` Service Addressing via ipvlan-l2 Networks

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/NETWORK.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`

## Context

Services need deterministic IPs for ACLs, monitoring, and migrations. Bridge-based container networking makes deterministic addressing and per-service ACLs harder to enforce.

## Decision

Assign each service a dedicated `/32` and attach container services to `ipvlan-l2` networks. Host services use `service-32` drop-ins for their addresses.

## Consequences

- ✅ Service IPs are stable and independent of container lifecycle.
- ✅ Service migrations reduce to moving the `/32` assignment and reapplying.
- ⚠️ Requires gratuitous ARP on migration and consistent VLAN metadata.

## Alternatives Considered

- **Bridge networking**: simpler but lacks deterministic per-service IPs.
- **macvlan**: workable but adds MAC churn and L2 complexity.
- **ipvlan-l3**: rejected for now due to current host and tooling assumptions.

## Notes

Drop-in file ordering uses the last octet of the `/32` for stable filenames.
