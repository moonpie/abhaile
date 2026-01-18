# ADR 0003: Split-Horizon DNS with Dual CoreDNS

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/NETWORK.md`, `docs/OPERATIONS.md`

## Context

Internal services and DMZ endpoints must be resolved differently, and client VLANs require separate DNS policy (filtered vs clean). DNS needs authoritative control for service `/32`s and internal FQDNs.

## Decision

Run two CoreDNS instances:

- **Filtered** (phobos) forwards to Blocky.
- **Clean** (deimos) forwards to upstream resolvers.

Authoritative zones:

- `abhaile.home.arpa` for internal services.
- `svc.abhaile.home.arpa` for direct service `/32` records.
- `abhaile.dedyn.io` for DMZ endpoints.

## Consequences

- ✅ Internal and DMZ namespaces are explicit and auditable.
- ✅ VLAN-specific DNS policy is easy to enforce.
- ⚠️ Requires monitoring two resolvers and maintaining zone serials.

## Alternatives Considered

- **Single resolver**: rejected due to policy differences across VLANs.
- **Upstream DNS only**: rejected due to lack of internal authoritative control.
