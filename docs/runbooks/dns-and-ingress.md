# DNS and Ingress Access

[ADR 0015](../adr/0015-dns-ingress-and-certificate-trust-boundaries.md) records the architectural
intent. This runbook describes repository configuration and intended access paths; it does not
verify live router or public DNS state.

## Expected Access Paths

| Client | End-user application path |
| --- | --- |
| Home LAN | Home DNS → private Caddy-DMZ address → configured application route |
| Away with WireGuard | VPN → home DNS and private Caddy-DMZ address → configured route |
| Away without WireGuard | No intended application access today |

Use `https://<application>.abhaile.dedyn.io` for configured end-user routes. Caddy-DMZ uses
Let's Encrypt via deSEC DNS-01, so browsers need no internal CA installation. DNS-01 does not
require inbound public HTTP/HTTPS. Explicit Caddy routes select applications; unknown wildcard
names receive HTTP 404. Backend containers can remain on the Services VLAN.

Internal `home.arpa` HTTPS routes use the internal CA and require client trust in that CA.
Application authentication is independent of certificate trust and routing.

## DNS Behavior

Both CoreDNS instances override A queries for `abhaile.dedyn.io` and its subdomains to
`172.20.100.200`. AAAA, TXT and other record types follow upstream resolution. External zone
records in `config/network.yaml` are not published by the renderer.

The reserved VPN namespace (`vpn.abhaile.dedyn.io` and its descendants) forwards directly upstream. After reconciliation, local A queries for
`vpn.abhaile.dedyn.io` should return the WAN IPv4 address maintained by ddclient.

VPN clients need home DNS and routes to the resolver addresses and the DMZ subnet. Public DNS
answers, router forwarding and actual client profiles require operator verification. No VLAN
isolation is assumed; the operator has reported that VLAN ACLs are not currently enforced.

## Read-only Checks

From a client with `dig`, compare local and upstream A answers. The resolver below is phobos's
configured CoreDNS address; use a resolver reachable from the client.

```bash
dig @172.20.20.235 test.abhaile.dedyn.io A +short
```

```bash
dig @172.20.20.235 vpn.abhaile.dedyn.io A +short
```

```bash
dig @9.9.9.9 vpn.abhaile.dedyn.io A +short
```

The application should resolve locally to `172.20.100.200`. The local VPN answer should match the
upstream WAN answer.
Check AAAA answers separately if clients attempt IPv6.

Visit `https://test.abhaile.dedyn.io` from the LAN, then from an outside network with WireGuard.
The configured response is `dmz caddy ok`, with a trusted certificate. A working test route does
not establish that every application route or authentication flow works.

For failures, distinguish DNS resolution, VPN/DMZ routing, TLS trust, Caddy routing and application
authentication. See [operations](operations.md) and [break-glass procedures](break-glass.md).

## Future Public Exposure

The architecture prepares stable public names, trusted certificates and application routes before
Internet exposure. A later edge change can expose Caddy-DMZ, with public DNS and firewall/NAT
adjustments as necessary, while preserving URLs, certificate trust and backend placement.

That change requires explicit authorization and review of every route on the exposed listener.
Keep LAN/VPN-only routes restricted. Existing listener placement or a public certificate does not
prove public reachability. Hairpin NAT is not needed for the documented local DNS access path.
