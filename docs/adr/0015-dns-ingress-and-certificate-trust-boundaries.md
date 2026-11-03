# ADR 0015: DNS, Ingress, and Certificate Trust Boundaries

## Status

2026-11-03: Accepted — retrospective record of existing architectural intent, clarified with
moonpie. This is the recording date; the original decision date is not established.

## Context

End-user devices should access services through stable HTTPS names without installing the lab's
internal CA. Infrastructure and administration also need an internal namespace and trust path.
Remote access currently uses WireGuard; direct public Internet access is a possible later step.
The DMZ proxy establishes that future entry point without requiring public exposure today.

This context explains the existing CoreDNS override, separate Caddy instances, deSEC DNS-01,
and ddclient VPN endpoint. It does not authorize new application routes or router changes.

## Decision

- `*.abhaile.home.arpa` provides internal service and administration access, with Caddy's internal
  CA where HTTPS is used. `*.svc.abhaile.home.arpa` identifies service endpoints.
- `*.abhaile.dedyn.io` provides the end-user ingress namespace through Caddy-DMZ, using publicly
  trusted Let's Encrypt certificates obtained through deSEC DNS-01. End users need no internal
  CA bundle for these routes. Internal user-facing routes may coexist during migration.
- Local DNS overrides A queries for this namespace to Caddy-DMZ at `172.20.100.200`. The intended
  exception is `vpn.abhaile.dedyn.io`, which must resolve upstream to the WAN address published
  by ddclient. External zone declarations are not published by the DNS renderer.
- DNS sends the wildcard to the proxy; application selection happens in explicit Caddy routes.
  Unconfigured names retain the wildcard HTTP 404 response. No individual local DNS record is
  required for each application route.
- LAN clients reach the proxy directly. Away from home, WireGuard supplies access to the home
  DNS resolvers and a route to the DMZ address. Public DNS and routing for the VPN endpoint are
  separate from service ingress. This IPv4 access path does not require hairpin NAT.
- Authentication is application-specific: native authentication where required by clients,
  and Authelia where appropriate. DMZ ingress does not require moving backend services into
  the DMZ VLAN. Internal TLS trust between proxies remains separate from browser trust.
- Future public access should require changes at the edge: expose Caddy-DMZ and adjust public
  DNS and firewall/NAT as needed. Application URLs, certificates, routes and backend placement
  should already be suitable. Before exposure, review every route on the exposed listener;
  routes requiring LAN/VPN-only access need explicit restrictions.

## Alternatives Considered

- Internal-CA certificates for every end-user device: adds certificate installation and trust
  maintenance, contrary to the intended end-user experience.
- Public-IP hairpin NAT for LAN access: unnecessary with the local private-address override.
- Per-application local DNS selection: duplicates selection already performed by Caddy routing.

## Consequences

The namespace and certificate choice do not prove Internet reachability or enforce VLAN isolation.
All VLANs are currently open according to the operator; ACL enforcement remains separate work.
Internet publication remains a separate, explicit operational decision.

A dedicated CoreDNS block forwards the reserved VPN namespace directly upstream. The template overrides A records only,
including the zone apex. AAAA and other
record types follow upstream resolution. IPv6 publication/routing needs separate review.

Actual public DNS answers, WireGuard client DNS/routes and WAN forwarding are not verified by
this record. An externally managed zone's private-address declaration is not evidence of the
live public DNS answer. VPN clients must use home DNS and route to its addresses and the DMZ.

## References

- [DNS renderer](../specs/accepted/0003-dns-renderer.md)
- [Core services](../specs/accepted/0011-core-services.md)
- [Home automation](../specs/active/0015-services-home-automation.md)
- [Media](../specs/proposed/0017-services-media.md)
- [Networking](../specs/proposed/0018-services-networking.md)
- [Monitoring](../specs/proposed/0016-services-monitoring.md)
- [Utilities](../specs/proposed/0019-services-utilities.md)
- [Network devices](../specs/proposed/0021-network-devices.md)
- [DNS and ingress access runbook](../runbooks/dns-and-ingress.md)
