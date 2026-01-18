# ADR 0008: Dual Caddy + Authelia Ingress (Internal & DMZ)

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/ARCHITECTURE.md`, `docs/NETWORK.md`

## Context

Services require TLS, consistent routing, and centralized auth. Internal and DMZ endpoints have different certificate and exposure needs.

## Decision

Deploy two Caddy instances:

- **Internal Caddy** on the services VLAN for `*.abhaile.home.arpa`.
- **DMZ Caddy** on VLAN 100 for `*.abhaile.dedyn.io`.

Authelia provides SSO and forward-auth integration for protected services.

## Consequences

- ✅ Centralized TLS and auth policy for HTTP services.
- ✅ Clear separation between internal and DMZ exposure.
- ⚠️ Non-HTTP protocols still require bespoke listeners.

## Alternatives Considered

- **Single ingress**: rejected due to mixed trust and exposure models.
- **Per-service TLS**: rejected due to operational overhead.
