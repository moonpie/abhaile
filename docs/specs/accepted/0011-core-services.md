# Spec: Core Services

## Metadata

```yaml
id: SPEC-2026-011
title: Core Services
status: accepted
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0004-apply-execution-model
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [vault, vault-agent, authelia, caddy-internal, caddy-dmz, coredns-common, coredns-filtered, coredns-clean, coredns-omada, blocky, chrony-a, chrony-b, chrony-common, ddclient, omada-controller]
```

## Context

Phase 1 core services are deployed and running on phobos and deimos. This
accepted spec documents the service group as implemented: composition patterns,
inter-service dependencies, network topology, secrets flow, and per-host
deployment differences.

These services form the foundation layer that all future services depend on.
They provide DNS resolution, time synchronization, ingress routing, secret
delivery, and authentication before any application workload can start.

## Requirements

- [x] Document per-host service deployment mapping and differences.
- [x] Document boot and dependency ordering across the service group.
- [x] Document composition patterns used (includes, vault_agent, ingress aggregation).
- [x] Document network topology (VLANs, /32 addresses, ipvlan-l2).
- [x] Document secrets flow from Vault through vault-agent to consuming services.
- [x] Document logical service groupings and inter-service dependencies.

## Constraints

- All services use deterministic /32 ipvlan-l2 addressing on VLAN 20 (services)
  or VLAN 100 (dmz).
- No runtime secrets appear in rendered output; vault-agent delivers them at
  runtime to host-only paths.
- Service definitions in `config/services/*/service.yaml` are the source of
  truth for composition intent.
- Render produces identical output for identical input; no service config
  depends on runtime state.

## Design

### Per-Host Deployment

From `config/mapping.yaml`:

**phobos** (primary, 10 services):

- ddclient, chrony-a, coredns-filtered, blocky, caddy-internal, caddy-dmz,
  vault, vault-agent, authelia, omada-controller

**deimos** (secondary, 3 services):

- chrony-b, coredns-clean, vault-agent

phobos runs the full infrastructure stack including the Vault server, both
ingress proxies, DNS filtering (blocky → coredns-filtered), authentication,
and network management. deimos runs a minimal subset for DNS availability
(coredns-clean bypasses blocky) and independent secret delivery.

### Network Topology

Two VLANs carry core service traffic:

| VLAN | ID | CIDR | ipvlan-l2 range | Use |
| --- | --- | --- | --- | --- |
| services | 20 | 172.20.20.0/24 | .200–.254 | Internal services |
| dmz | 100 | 172.20.100.0/24 | .200–.254 | Public-facing ingress |

Host base interfaces:

- phobos: `enp0s31f6` at 172.20.20.10/24 (VLAN 20), `enp0s31f6.100` at 172.20.100.10/24 (VLAN 100)
- deimos: `enp0s31f6` at 172.20.20.11/24 (VLAN 20)

Service /32 addresses (all ipvlan-l2 on VLAN 20 unless noted):

| Service | Address | VLAN | Host |
| --- | --- | --- | --- |
| caddy-internal | 172.20.20.200/32 | services | phobos |
| authelia | 172.20.20.201/32 | services | phobos |
| vault | 172.20.20.204/32 | services | phobos |
| blocky | 172.20.20.234/32 | services | phobos |
| coredns-filtered | 172.20.20.235/32 | services | phobos |
| coredns-clean | 172.20.20.236/32 | services | deimos |
| chrony-a | 172.20.20.237/32 | services | phobos |
| chrony-b | 172.20.20.238/32 | services | deimos |
| omada-controller | 172.20.20.220/32 | services | phobos |
| caddy-dmz | 172.20.100.200/32 | dmz | phobos |

vault-agent and ddclient run on host networking and do not consume /32
addresses. coredns-common and chrony-common are composition-only targets
(include base or shared template) and do not run as standalone services.

### Service Groups

#### Secrets and Authentication

**vault** — HashiCorp Vault server on phobos.

- `podman.user: root`, `podman.network: ipvlan-l2`
- Renders `local.json` config template with listener/cluster/API addresses
  resolved from `%%network.services.vault.address%%`.
- Static `vault.env` environment file.
- Named volumes: `config`, `data`, `host-certs`.
- Contributes internal ingress block to caddy-internal.

**vault-agent** — secret delivery agent on phobos and deimos.

- `podman.user: abhaile` (rootless), `podman.network: host`
- Renders base `config.hcl` template with vault address from
  `%%network.services.vault.address%%`.
- Deploys `abhaile-secrets-ready.path` and `.service` watching the sentinel
  file at `/srv/vault/agent/out/.ready`.
- Aggregates `vault_agent.templates` from all same-host services that declare them.
- Named volumes: `templates`, `run`, `out`, `host-certs`.
- Mounted files: AppRole material at `/home/abhaile/.config/vault-agent/role-id` and
  `/home/abhaile/.config/vault-agent/secret-id`, plus rendered `config.hcl`.

**authelia** — SSO/authentication on phobos.

- `podman.user: root`, `podman.network: ipvlan-l2`
- Pod composition: `authelia` container + `redis` container in a shared pod.
- Vault-agent templates: `authelia.configuration.yml.ctmpl` and
  `authelia-redis.conf.ctmpl` for session/storage/JWT secrets and Redis password.
- Systemd path/service units watch vault-agent output for config reload:
  `authelia-config.path` and `authelia-redis-conf.path`.
- Static `users_database.yml` for file-based user store.
- Contributes internal ingress block to caddy-internal.

#### Ingress Layer

**caddy-internal** — internal reverse proxy on phobos.

- `podman.user: root`, `podman.network: ipvlan-l2`
- Defines `composition.ingress.internal.base` — the aggregation target for all
  internal ingress blocks.
- Base Caddyfile at `caddy-internal/config/Caddyfile`.
- Contributors: vault, authelia, omada-controller (internal + svc-cert blocks).
- Named volumes: `config`, `data`, `host-certs`.
- Internal CA for `*.abhaile.home.arpa` TLS.

**caddy-dmz** — public-facing reverse proxy on phobos.

- `podman.user: root`, `podman.network: ipvlan-l2`
- Defines `composition.ingress.dmz.base` — aggregation target for DMZ ingress.
- Custom build with deSEC DNS plugin (`caddy-dmz/build/Containerfile`).
- Vault-agent template: `caddy-dns-desec.env.ctmpl` for ACME DNS-01 credentials.
- The container reads the Vault Agent rendered env file directly from
  `/srv/vault/agent/out/caddy-dns-desec.env`.
- Systemd path/service: `caddy-dns-desec.path` watches env file for restart.
- Contributors: omada-controller (dmz-ingress block).
- DNS-01 via deSEC for `*.abhaile.dedyn.io` public certificates.

#### DNS Infrastructure

**coredns-common** — shared composition base (not directly deployed).

- No `podman` section; exists only as an include target.
- Provides zone file rendering via `composition.dns.zone_files` with
  `coredns-common/config/zones/zone.zone.j2` template.
- Deploys `coredns-zones.path` and `.service` for SIGUSR1 reload on zone changes.

**coredns-omada** — Omada plugin build and integration (included, not standalone).

- Provides Containerfile, build quadlet (`coredns-omada.build`), and install service.
- Deploys the main `coredns.service` systemd unit.
- Vault-agent template: `coredns-omada.env.ctmpl` for Omada API credentials.
- Systemd path/service: `coredns-omada-env.path` watches env file for reload.

**coredns-filtered** — ad-filtering DNS resolver on phobos.

- `systemd.network: service-32` (host service with /32 drop-in).
- `composition.include: [coredns-common, coredns-omada]`
- Corefile template variables: binds to own IP, forwards to blocky at
  `%%network.services.blocky.address%%:8053`.
- Resolves as `ns1.abhaile.home.arpa` via direct A record because authoritative
  NS targets must not be CNAMEs.

**coredns-clean** — unfiltered DNS resolver on deimos.

- `systemd.network: service-32` (host service with /32 drop-in).
- `composition.include: [coredns-common, coredns-omada]`
- Corefile template variables: binds to own IP, forwards to upstream
  `9.9.9.9 149.112.112.112 1.1.1.1 1.0.0.1` (no blocky).
- Resolves as `ns2.abhaile.home.arpa` via direct A record because authoritative
  NS targets must not be CNAMEs.

**blocky** — DNS-level ad blocking on phobos.

- `podman.user: root`, `podman.network: ipvlan-l2`
- Static `config.yml` with OISD blocklist.
- Upstream for coredns-filtered only; coredns-clean bypasses it.
- Listens on port 8053 for forwarded queries from coredns-filtered.

#### NTP

**chrony-common** — shared template (not a service definition).

- Provides `chrony-common/config/chrony.conf.j2` template used by chrony-a and
  chrony-b.

**chrony-a** — NTP server on phobos.

- `systemd.network: service-32` (host service with /32 drop-in).
- `apply.restart_unit: chrony.service`
- Template variables: binds to own IP, peers with chrony-b, stratum 10.
- Resolves as `ntp-a.abhaile.home.arpa` via CNAME.

**chrony-b** — NTP server on deimos.

- `systemd.network: service-32` (host service with /32 drop-in).
- `apply.restart_unit: chrony.service`
- Template variables: binds to own IP, peers with chrony-a, stratum 11.
- Resolves as `ntp-b.abhaile.home.arpa` via CNAME.

#### Network Management

**ddclient** — dynamic DNS updater on phobos.

- `systemd.network: host` (no /32 address, runs on host network).
- Vault-agent template: `ddclient.conf.ctmpl` for deSEC API credentials.
- Systemd path/service: `ddclient-conf.path` watches conf file for restart.
- Updates `*.abhaile.dedyn.io` records via deSEC API.

**omada-controller** — TP-Link network controller on phobos.

- `podman.user: root`, `podman.network: ipvlan-l2`
- Static env file at `/etc/omada-controller/omada-controller.env`.
- Certificate chain rebuild: `rebuild-omada-cert.path` watches Caddy internal
  CA cert file, triggers `rebuild-omada-cert.service` to run the repo-managed
  `/opt/abhaile/tools/bash/rebuild-omada-cert.sh`, concatenate leaf + root CA,
  copy the matching key, and restart the controller.
- Contributes ingress blocks to both caddy-internal (internal + svc-cert) and
  caddy-dmz (dmz-ingress for hairpin NAT).
- Named volumes: `cert`, `data`, `logs`, `host-certs`.

### Composition Patterns

The core services demonstrate all composition patterns defined in the service
authoring model:

**Include inheritance** (`composition.include`):

- coredns-filtered and coredns-clean both include `[coredns-common, coredns-omada]`.
- This gives them zone file rendering, systemd units (path watcher, install
  service, main service), vault-agent templates, and build artifacts without
  duplication.

**Vault-agent template aggregation** (`composition.vault_agent.templates`):

- authelia, caddy-dmz, coredns-omada, and ddclient each declare templates.
- vault-agent on the same host collects all declared templates into its
  `config.hcl` and copies source `.ctmpl` files to the templates volume.
- On phobos: authelia + caddy-dmz + coredns-omada + ddclient templates aggregated.
- On deimos: only coredns-omada templates (via coredns-clean include chain).

**Ingress block aggregation** (`composition.ingress`):

- caddy-internal defines `ingress.internal.base` and collects internal blocks
  from vault, authelia, and omada-controller.
- caddy-dmz defines `ingress.dmz.base` and collects DMZ blocks from
  omada-controller.

**Pod composition** (`composition.pod`):

- authelia uses a pod with two containers (authelia + redis) sharing a network
  namespace.

**Host-native services** (`systemd.network: service-32`):

- chrony-a, chrony-b, coredns-filtered, coredns-clean run as host systemd
  services with /32 address drop-ins on ipvlan-l2 interfaces.

### Boot and Dependency Ordering

The systemd dependency chain on phobos follows this order:

```text
systemd-networkd (host interfaces + ipvlan-l2 + VLANs)
  → chrony-a.service (NTP, stratum 10)
    → coredns-filtered (DNS, via coredns.service)
      → blocky.service (ad-filtering upstream)
        → vault.service (secret store)
          → abhaile-vault-unseal.service (phobos-only SOPS recovery + API unseal)
          → vault-agent (rootless, secret delivery; retries/restarts until Vault is usable)
            → abhaile-secrets-ready.path/.service (sentinel watch)
              → caddy-dmz, authelia (After=abhaile-secrets-ready)
          → caddy-internal (After=vault)
            → omada-controller (After=caddy-internal, needs internal CA cert)
```

On deimos the chain is shorter:

```text
systemd-networkd
  → chrony-b.service (NTP, stratum 11)
    → coredns-clean (DNS, via coredns.service)
      → vault-agent (rootless, connects to phobos vault)
        → abhaile-secrets-ready.path/.service
```

Key dependency semantics:

- vault depends on chrony-a and blocky (needs time sync and DNS for Raft/TLS).
- caddy-internal depends on vault (needs Vault API for internal PKI).
- caddy-dmz and authelia depend on `abhaile-secrets-ready` (need vault-agent
  rendered credentials).
- omada-controller depends on caddy-internal (needs internal CA certificate
  for its cert chain rebuild).
- ddclient depends on `abhaile-secrets-ready` (needs deSEC credentials from
  vault-agent).

### Secrets Flow

The secrets delivery path for core services:

1. Bootstrap writes AppRole material to `/home/abhaile/.config/vault-agent/role-id` and
   `/home/abhaile/.config/vault-agent/secret-id` (host-local, never in git).
1. vault-agent authenticates to Vault with AppRole auto-auth and manages its runtime sink token.
1. vault-agent renders `.ctmpl` templates to `/srv/vault/agent/out/<filename>`.
1. vault-agent writes `.ready` sentinel after all templates render successfully.
1. `abhaile-secrets-ready.path` detects sentinel, starts `.service`.
1. Per-service systemd path units watch their specific output files:
   - `authelia-config.path` → copies `authelia.configuration.yml` to volume, restarts.
   - `authelia-redis-conf.path` → copies `authelia-redis.conf` to volume, restarts.
   - `caddy-dns-desec.path` → restarts caddy-dmz with new env file.
   - `coredns-omada-env.path` → restarts coredns with new Omada credentials.
   - `ddclient-conf.path` → restarts ddclient with new deSEC credentials.

No resolved secret values appear in rendered repo output. Render produces only
the `.ctmpl` source files, `config.hcl` template block declarations, and
systemd path/service unit files.

### DNS Records

Core services register in two internal zones:

- `svc.abhaile.home.arpa.` — A records pointing to /32 service addresses
  (with PTR for reverse lookups).
- `abhaile.home.arpa.` — direct A records for `ns1`/`ns2` authoritative
  nameserver targets, plus CNAME aliases for user-facing names.

caddy-dmz additionally holds the external wildcard:

- `*.abhaile.dedyn.io` → 172.20.100.200 (A record in `abhaile.dedyn.io.` zone).

Zone files are rendered by the DNS renderer from `config/network.yaml` records
and served by coredns-filtered/coredns-clean via included coredns-common zone
file composition.

## Decision Notes

- Decision: phobos runs the full secrets/ingress/DNS/auth stack; deimos runs only availability-critical subset (DNS, NTP, vault-agent).

- Rationale: Single Vault instance avoids HA complexity for a homelab. DNS and NTP on deimos provide resolution if phobos is down.

- Impact: deimos services that need secrets connect to phobos vault over the network.

- ADR: null

- Decision: coredns-filtered forwards to blocky; coredns-clean forwards to public resolvers directly.

- Rationale: Provides both filtered and unfiltered DNS options for different network segments/VLANs without duplication of zone serving.

- Impact: Both instances share zone files and the Omada plugin via include inheritance.

- ADR: null

- Decision: chrony-a and chrony-b peer with each other at different strata (10 vs 11).

- Rationale: Consistent time across both hosts with deterministic primary/secondary ordering.

- Impact: All services and network devices can use either NTP server for redundancy.

- ADR: null

- Decision: Vault-agent runs rootless under the `abhaile` user.

- Rationale: Least privilege — vault-agent only needs to write templates and maintain its own token; rootful is unnecessary.

- Impact: Quadlets install to `~abhaile/.config/containers/systemd/` with user lingering enabled.

- ADR: 0005-service-authoring-model

- Decision: omada-controller cert chain rebuilds via systemd path watching Caddy internal CA output.

- Rationale: Omada requires a combined cert bundle (leaf + CA root) that Caddy does not produce directly.

- Impact: `rebuild-omada-cert.path` triggers on cert file change; the service concatenates and restarts the controller.

- ADR: null

- Decision: caddy-dmz uses a custom build with deSEC DNS plugin for ACME DNS-01.

- Rationale: Public TLS certificates for `*.abhaile.dedyn.io` require DNS-01 challenge; deSEC is the registrar.

- Impact: Build quadlet produces custom Caddy image; deSEC API token delivered via vault-agent.

- ADR: null

## Acceptance Criteria

- [x] Per-host service mapping is documented with deployment differences explained.
- [x] Boot/dependency ordering is documented with the full systemd chain for both hosts.
- [x] Composition patterns (include, vault_agent, ingress, pod, service-32) are documented with concrete service examples.
- [x] Network topology is documented with VLAN assignments and /32 address table.
- [x] Secrets flow is documented from bootstrap token through vault-agent to consuming services.
- [x] All 15 services in scope are described with their composition keys, network mode, and role.

### Evidence

Criterion: Per-host service mapping.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) and [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for `config/mapping.yaml` and per-service `service.yaml` definitions.
- Validation evidence: `tests/integration/test_render_e2e.py` renders both hosts from mapping.

Criterion: Boot/dependency ordering.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) for quadlet and systemd unit rendering with After/Requires directives in `src/abhaile/renderers/quadlets/` and `src/abhaile/renderers/services.py`.
- Validation evidence: `tests/integration/test_quadlets.py`, service unit tests confirming dependency declarations.

Criterion: Composition patterns.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) for include resolution in `src/abhaile/utils/composition.py`, ingress in `src/abhaile/renderers/ingress.py`, vault templates in `src/abhaile/renderers/vault_templates/`.
- Validation evidence: `tests/integration/test_composition_includes.py`, `tests/integration/test_ingress.py`, `tests/integration/test_vault_templates.py`.

Criterion: Network topology.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) for networkd drop-in rendering in `src/abhaile/renderers/networkd.py` from `config/network.yaml`.
- Validation evidence: `tests/unit/python/renderers/test_networkd.py`, `tests/integration/test_render_e2e.py`.

Criterion: Secrets flow.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for vault-agent composition, systemd path/service units, and secrets-ready sentinel.
- Validation evidence: `tests/integration/test_vault_templates.py`, `tests/unit/python/renderers/test_vault_templates_base.py`.

Criterion: Service coverage.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) and [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for all service definitions under `config/services/` in scope.
- Validation evidence: `tests/integration/test_render_e2e.py` covers full render of both hosts including all in-scope services.

## Out of Scope

- Apply execution behavior (covered by ADR 0004 and SPEC-2026-009).
- Service composition mechanics (covered by SPEC-2026-005).
- Render pipeline internals (covered by SPEC-2026-001).
- Phase 2+ services not yet deployed.
- Vault HA or multi-instance topology.
- Network device (ER605, switches, APs) configuration.

## Open Questions

- None.

## References

- `config/mapping.yaml`
- `config/network.yaml`
- `config/services/vault/service.yaml`
- `config/services/vault-agent/service.yaml`
- `config/services/authelia/service.yaml`
- `config/services/caddy-internal/service.yaml`
- `config/services/caddy-dmz/service.yaml`
- `config/services/coredns-common/service.yaml`
- `config/services/coredns-filtered/service.yaml`
- `config/services/coredns-clean/service.yaml`
- `config/services/coredns-omada/service.yaml`
- `config/services/blocky/service.yaml`
- `config/services/chrony-a/service.yaml`
- `config/services/chrony-b/service.yaml`
- `config/services/ddclient/service.yaml`
- `config/services/omada-controller/service.yaml`
- `docs/adr/0004-apply-execution-model.md`
- `docs/adr/0005-service-authoring-model.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/specs/accepted/0001-render-pipeline.md`
- `docs/specs/accepted/0005-service-composition.md`
