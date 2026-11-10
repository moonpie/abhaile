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

### CoreDNS build upgrades

CoreDNS runs as a native host binary extracted from the `coredns-omada` build.
Update the CoreDNS source tag, external Omada plugin, and Go builder together;
the plugin's Go module requirements can change the resolved dependency graph.
Check the compiled binary's version, build module information, and plugin list.
The Alpine distribution stage packages the binary for installation; it is not
the running DNS service's operating system.

The installer stages the binary alongside `/usr/local/bin/coredns`, sets mode
`0755`, and atomically renames it over the destination. A running daemon keeps
its old executable until the build consumer restart. A failed staging copy leaves
the old executable in place and removes the temporary file.

Deploy the atomic installer as its own baseline before changing build versions.
Confirm it is last-successful on both hosts so recovery also uses the safe installer.

For the 1.15.0 build, the declared dependencies are Omada plugin 1.9.1,
Go 1.27.3, and Alpine 3.24.4. The plugin includes a fix for client discovery with
Omada Controller 6.2. Validate dynamic client records against the live controller
after deployment; isolated static DNS checks cannot prove API compatibility.

Keep explicit `fallthrough` in the Omada block. Plugin 1.8.1 automatically passed
missing records to the next handler; 1.9.1 requires this option. Without it, a
successfully populated Omada zone can return NXDOMAIN for Git-managed static names
and child/reverse SOA queries before the file plugin can answer. Plugin ordering
is unchanged: Omada answers matching dynamic records first, and missing records
fall back to the static files. This does not establish static-first precedence.
Validate both dynamic and static answers after controller initialization; an
unavailable controller does not exercise this path.

Roll out one DNS host at a time. Before pushing, pause the runner timer on the
other host and confirm its runner is idle. Validate the first host before restoring
the other timer. Keep one working resolver available while the other builds and
restarts; independent runners do not provide a coordinated rolling deployment.
The timer on the host being reconciled must remain active for its health checks.

After each deployment, check the runner summary, `/usr/local/bin/coredns -version`,
and `/usr/local/bin/coredns -plugins`. Query that resolver directly for a static
service record, a known Omada client, the `dedyn.io` wildcard, the reserved VPN
name, and recursive answers. Check filtered and clean views from their respective
client networks, including AAAA/TXT forwarding. Preserve the old working build
image until both hosts pass: give it a separate local tag before rebuilding, because
the build replaces `localhost/coredns-omada:latest`. Merely avoiding image pruning
does not retain the old tag. Reverting pins may require upstream access to rebuild;
the retained image is available for an explicitly reviewed recovery if needed.

### Split-horizon answers

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

## Phobos DMZ DNS Replies and ARP

On 2026-11-03, Home Assistant and Omada returned HTTP 502 through Caddy-DMZ.
From Caddy-DMZ, CoreDNS on Deimos answered, while CoreDNS on Phobos logged
successful queries but its replies never reached the container.

With an empty neighbour cache, Phobos used the Services VLAN address
`172.20.20.235` as the ARP sender on `ipvlan-l2.100`. The request went
unanswered. Setting `arp_announce=2` on that host interface changed the
ARP sender to `172.20.100.20`. The cold-cache lookup then succeeded, with
DNS replies still sourced from `172.20.20.235`.

GitOps publishes `/etc/sysctl.d/70-abhaile-dmz-arp.conf` on Phobos.
The `abhaile-dmz-arp.service` oneshot applies that file during reconciliation
when the interface already exists. Systemd applies interface-specific
sysctl settings when the interface appears. Slash notation preserves the
dot in the interface name.

```ini
net/ipv4/conf/ipvlan-l2.100/arp_announce = 2
```

After reconciliation, read the value under
`/proc/sys/net/ipv4/conf/ipvlan-l2.100/arp_announce`. Clear only the
neighbour entry for `172.20.100.200` during an attended check, then query
`172.20.20.235` from Caddy-DMZ without priming the cache with ping.
Verify Home Assistant and Omada over DMZ HTTPS. If DMZ addressing changes,
recheck the ARP sender address. The previous interface value was `0`. Removing the drop-in does not reset a
live kernel value. If reverting the fix, restore that value explicitly after
reconciling the removal.

## Future Public Exposure

The architecture prepares stable public names, trusted certificates and application routes before
Internet exposure. A later edge change can expose Caddy-DMZ, with public DNS and firewall/NAT
adjustments as necessary, while preserving URLs, certificate trust and backend placement.

That change requires explicit authorization and review of every route on the exposed listener.
Keep LAN/VPN-only routes restricted. Existing listener placement or a public certificate does not
prove public reachability. Hairpin NAT is not needed for the documented local DNS access path.
