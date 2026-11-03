# Spec: Host Hardening

## Metadata

```yaml
id: SPEC-2026-020
title: Host Hardening
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-11-03
related_adrs:
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [fail2ban]
```

## Context

Both hosts currently run with no stateful firewall, no egress restrictions, and default kernel
parameters. The old TODO tracked hardening areas under "Host Hardening & Observability":
nftables (default deny, service-specific rules), fail2ban configuration with nftables actions, CIS-lite baseline (rp_filter, SYN
cookies, SSH hardening), and filesystem configuration (noatime).

Gluetun owns torrent VPN leak protection under [SPEC-2026-018](0018-services-networking.md).

fail2ban already has a `service.yaml` stub declaring `systemd.network: host` with an empty
composition block. It runs as a host-level systemd service (not containerised) and needs
nftables integration for ban actions.

The key architectural decision is how nftables rules enter the render pipeline. The existing
`system/` renderer handles systemd-networkd units and resolved config. nftables rulesets are
structurally similar (declarative files placed atomically), but they require rule ordering,
and per-host service awareness.

## Requirements

- [ ] Render a deterministic nftables ruleset per host with default-deny ingress and restricted egress
- [ ] Generate per-service ingress rules derived from `config/network.yaml` and `config/mapping.yaml` (open only ports each host actually serves)
- [ ] Render fail2ban configuration with nftables ban actions
- [ ] Render CIS-lite sysctl baseline (rp_filter, SYN cookies, TCP hardening, SSH kernel params) per host
- [ ] Render filesystem mount options (noatime) into fstab or mount drop-ins

## Constraints

- Render must remain unprivileged and deterministic — no live host state reads.
- nftables rules must be expressible from data already in `config/` (service addresses, ports, VLAN topology). No new external data sources.
- fail2ban runs on the host network (already declared in its `service.yaml` stub). It is not containerised.
- Rule ordering must be deterministic across renders — same input produces identical rule file byte-for-byte.
- Rendered nftables rules must not include timestamps, counters, or runtime state.
- CrowdSec integration (if later deployed) must be additive — the base ruleset must accommodate an nftables set that CrowdSec can populate without re-rendering.

## Design

### nftables Ruleset Structure

The ruleset uses nftables' native set/chain model with a single configuration file per host:

```text
out/rendered/<host>/system/nftables/nftables.conf
```

Table and chain layout:

```text
table inet filter {
  set svc_addrs { ... }       # /32 service addresses on this host
  set local_nets { ... }      # VLAN CIDRs this host participates in

  chain input {
    type filter hook input priority 0; policy drop;
    ct state established,related accept
    iif lo accept
    icmp type echo-request accept
    icmpv6 type { ... } accept
    # Per-service rules (rendered from mapping + network data)
    tcp dport 22 ip saddr @local_nets accept   # SSH from local only
    ...per-service port rules...
    # fail2ban set hook
    ip saddr @f2b-sshd drop
  }

  chain forward {
    type filter hook forward priority 0; policy drop;
    # Container-to-container forwarding if needed
  }

  chain output {
    type filter hook output priority 0; policy accept;
  }
}
```

### Rule Generation from Config Data

The renderer derives ingress rules from:

1. **`config/mapping.yaml`** — which services run on which host.
1. **`config/network.yaml`** — service addresses and VLAN CIDRs.
1. **`config/services/<service>/service.yaml`** — port declarations (from existing `composition.container` or a new `ports` field for host services).

For each service assigned to a host, the renderer generates `accept` rules for that service's
declared ports, bound to its /32 address. This keeps the ruleset minimal — only ports for
services actually deployed on the host are opened.

### fail2ban Integration

fail2ban runs as a native systemd service. Rendered artifacts:

```text
out/rendered/<host>/services/fail2ban/
  jail.local        # jail definitions (sshd, recidive)
  action.d/
    nftables.local  # override: use inet filter table, set-based bans
```

The nftables ruleset includes a named set (`@f2b-sshd`, `@f2b-recidive`) referenced in the
input chain. fail2ban populates these sets at runtime via its nftables action. The renderer
creates the empty set declarations; fail2ban fills them.

Jails rendered:

- `sshd` — ban after 3 failures, 1h ban, nftables action.
- `recidive` — ban repeat offenders for 7d.

### CIS-Lite Sysctl Baseline

Rendered as a sysctl drop-in:

```text
out/rendered/<host>/system/sysctl/99-hardening.conf
```

Contents (both hosts):

```ini
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
kernel.sysrq = 0
```

### SSH Hardening

Rendered as an sshd config drop-in:

```text
out/rendered/<host>/system/ssh/sshd_config.d/99-hardening.conf
```

Contents:

```text
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
```

### Filesystem Configuration

Rendered as a systemd mount drop-in or fstab snippet to enforce `noatime` on data partitions.
The exact mechanism depends on whether hosts use fstab or systemd mount units (to be confirmed
during implementation). The renderer outputs the declarative desired state; apply enforces it.

### DNS Filtering Boundary

CoreDNS applies source-subnet policy through the mirrored resolver pair described in
[SPEC-2026-021](0021-network-devices.md). Enforcement against alternate client resolvers
is deferred. Host hardening leaves ordinary HTTPS egress outside DNS filtering rules.

### Render Pipeline Integration

Two options exist for integrating nftables and hardening artifacts into the render pipeline:

**Option A — Extend the existing system renderer:** Add nftables, sysctl, sshd, and fstab
rendering alongside the existing networkd and resolved builders. Artifacts land in
`out/rendered/<host>/system/`.

**Option B — New `hardening` renderer:** A dedicated renderer that reads hardening-specific
config and produces artifacts under `out/rendered/<host>/system/` (same output location, new
code module).

Both options produce identical output structure. The decision affects code organisation only.
See open questions.

### CrowdSec Accommodation

The rendered nftables ruleset includes a named set (`@crowdsec-blacklists`) in the input chain
that is empty at render time. If CrowdSec is later deployed, its bouncer populates this set at
runtime without requiring a re-render. This is the same pattern used for fail2ban sets.

## Decision Notes

_To be recorded during implementation._

## Acceptance Criteria

- [ ] Detail nftables ruleset structure and rendering approach
- [ ] Render per-host nftables.conf with default-deny ingress, service-derived allow rules, and deterministic ordering
- [ ] fail2ban jail and action configuration renders with nftables set-based bans
- [ ] CIS-lite sysctl drop-in renders for both hosts
- [ ] SSH hardening drop-in renders for both hosts
- [ ] nftables ruleset includes empty named sets for fail2ban and CrowdSec (runtime-populated)
- [ ] Filesystem noatime configuration renders for both hosts
- [ ] Render output is byte-for-byte deterministic (no timestamps, no counter state)
- [ ] Integration test: full render of both hosts produces valid nftables syntax (parseable by `nft -c -f`)
- [ ] Unit tests cover rule generation from mapping/network data variations
- [ ] No regressions in existing render integration tests

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- CrowdSec service deployment and bouncer configuration (separate spec).
- ER605 gateway ACLs and inter-VLAN firewall rules (Phase 4 network config).
- Runtime nftables counter or connection tracking state.
- Vault-agent integration (fail2ban has no secrets; VPN endpoint IPs are non-secret config).
- Kernel upgrades, secure boot, or UEFI hardening.
- Intrusion detection beyond fail2ban/CrowdSec set accommodation.
- Unattended-upgrades (already handled by the host software renderer).

## Open Questions

1. **Render approach:** Should nftables/sysctl/sshd rendering extend the existing system
   renderer (adding builders alongside `networkd_builder.py` and `resolved_builder.py`), or
   live in a new top-level `hardening` renderer module? The system renderer already handles
   atomic-file-placement artifacts and the output directory is `system/`. A new module adds
   code isolation but introduces another orchestrator call. Which approach?

1. **Rule ordering strategy:** nftables evaluates rules top-to-bottom within a chain. How
   should the renderer order per-service rules deterministically? Options: (a) sort by
   service name alphabetically, (b) sort by port number, (c) sort by service address
   (last octet, matching the drop-in ordering used for networkd). Recommend (c) for
   consistency with existing conventions.

1. **CrowdSec bouncer interaction:** The current design pre-creates an empty
   `@crowdsec-blacklists` set. When CrowdSec is deployed, does it need additional chains,
   or is a single set in the input chain sufficient? The CrowdSec nftables bouncer typically
   wants its own table (`crowdsec`) — should the rendered ruleset accommodate this, or should
   CrowdSec's own deployment create its table independently?

1. **Config location for hardening parameters:** Should per-host hardening knobs (SSH allow-lists, custom sysctl overrides) live in `config/hosts/<host>/host.yaml`
   under a new `composition.hardening` key, or in a dedicated `config/hardening/<host>.yaml`
   file? The former keeps host config consolidated; the latter avoids bloating `host.yaml`.

## References

- `config/services/fail2ban/service.yaml` (stub — `systemd.network: host`, empty composition)
- `config/network.yaml` — VLAN topology, service /32 addresses
- `config/mapping.yaml` — service-to-host assignments
- `docs/specs/proposed/0018-services-networking.md` (SPEC-2026-018 — Gluetun leak protection)
- `docs/specs/proposed/0019-services-utilities.md` (SPEC-2026-019 — CrowdSec service definition and bouncer outputs)
- `src/abhaile/renderers/` — existing renderer modules (networkd, resolved, services)
- `.old_docs/TODO.md` — Phase 3 "Host Hardening & Observability" items
- CIS Debian Linux Benchmark (reference for sysctl/SSH baselines)
