# TODO: Abhaile Project Tracker

Working scratchpad. Specs and ADRs are the durable record; this file tracks the next execution
sequence only.

## Next Up

- [ ] 2026-06-21 Clean-room the bootstrap flow using `docs/guides/bootstrap.md`.
- [x] 2026-06-22 Run general homelab health checks across `phobos` and `deimos`.
- [x] 2026-06-22 Resolve general homelab health findings before bootstrap.
- [ ] 2026-06-22 Complete `deimos` bootstrap prerequisites.
- [ ] 2026-06-21 Deploy GitOps management on `deimos`.
- [ ] 2026-06-21 Deploy GitOps management on `phobos`.
- [ ] 2026-06-21 Work through Phase 3 service specs.
- [ ] 2026-06-21 Work through Phase 4 network/controller spec.
- [ ] 2026-06-21 Work through Phase 5 CI/dependency automation spec.

## Specs

| Phase | Spec / Authority |
| --- | --- |
| Bootstrap | `docs/specs/accepted/0014-bootstrap.md`, `docs/guides/bootstrap.md` |
| GitOps runner | `docs/specs/accepted/0012-gitops-runner.md` |
| Phase 3 services | `docs/specs/proposed/0015-services-home-automation.md` through `0020-host-hardening.md` |
| Phase 4 network/controller automation | `docs/specs/proposed/0021-network-devices.md` |
| Phase 5 CI/dependency automation | `docs/specs/proposed/0024-ci-dependency-automation.md` |

### Phase 3 Specs

| Spec | Scope |
| --- | --- |
| `docs/specs/proposed/0015-services-home-automation.md` | Home Assistant, Mosquitto, Zigbee2MQTT, ESPHome, Frigate, Go2rtc |
| `docs/specs/proposed/0016-services-monitoring.md` | Prometheus, Grafana, Loki, Alertmanager, exporters |
| `docs/specs/proposed/0017-services-media.md` | Immich, Jellyfin, Tdarr, \*arr stack, Jellyseerr, Flaresolverr |
| `docs/specs/proposed/0018-services-networking.md` | Gluetun, qBittorrent VPN egress |
| `docs/specs/proposed/0019-services-utilities.md` | Homepage, Netbox, Vaultwarden, Postfix, CrowdSec |
| `docs/specs/proposed/0020-host-hardening.md` | nftables, fail2ban, CIS-lite, per-UID routing |

Acceptance criteria live in each spec. Don't duplicate them here.

## Bootstrap Clean-Room Tracks

### General Homelab Health

- [x] 2026-06-22 Check Vault seal and raft health.
- [x] 2026-06-22 Check failed system and user units on `phobos` and `deimos`.
- [x] 2026-06-22 Check rootful and rootless Podman health on both hosts.
- [x] 2026-06-22 Repair known `deimos` `abhaile` rootless Podman storage issue.
- [x] 2026-06-22 Check DNS, NTP, network-online, and host service IP health.

### Deimos Bootstrap Prerequisites

- [x] 2026-06-22 Create encrypted `secrets/deimos/vault-agent.sops.yaml`.
- [x] 2026-06-22 Confirm `deimos` age identity exists at `/home/abhaile/.config/sops/age/keys.txt`.
- [x] 2026-06-22 Confirm `deimos` read-only Git deploy key and `known_hosts` are in place.
- [x] 2026-06-22 Create or verify the `deimos` Vault AppRole and sealed `role_id`.
- [ ] 2026-06-22 Generate a response-wrapped SecretID for `deimos` bootstrap.

### Vault Recovery Prerequisites

- [x] 2026-06-23 Create root-owned phobos Vault unseal age identity.
- [x] 2026-06-23 Add `secrets/phobos/vault-unseal.sops.yaml` SOPS recipient rule.
- [x] 2026-06-23 Create encrypted `secrets/phobos/vault-unseal.sops.yaml`.
- [x] 2026-06-23 Update bootstrap and unseal scripts for `secrets/<host>/` artifact layout.

## Implementation decisions

- Record in the active spec's Decision Notes section.
- Promote to ADR when a decision crosses service/host/agent boundaries or is expensive to reverse.

## Working With Agents

### Common Tasks

**Add a new service** — start with Architect:

> Design the `service.yaml` structure for `<service>`. Consider: container mode, storage, dependencies, ingress, vault-agent. Reference existing services (authelia for pods, omada-controller for single container, coredns-filtered for includes).

**Change a config schema** — start with Architect:

> Add `<field>` to `<config file>`. Design the schema change with backward compatibility. Propose updates to `schemas/` and renderer changes.

**Debug a failed render or test** — start with Developer:

> `make test` fails with: [error]. Investigate and fix. Read relevant test and source first.

**Write an ADR** — start with Architect:

> Write ADR for [decision]. Use `docs/adr/0000-adr-template.md`. Cover: context, alternatives, decision, consequences.

### Session Prompt

Use with the **Architect** agent. It orchestrates Developer, Code Reviewer, and Technical Writer via subagent.

```text
Follow `AGENTS.md`. Here is the work:

Spec: <path to spec>
Task: <what to implement, or "all remaining acceptance criteria">

Workflow:
1. Review the spec. Flag any ambiguities or design gaps before proceeding.
2. Once clear, hand off to Developer for implementation.
3. After implementation, hand off to Code Reviewer for validation.
4. After review passes, hand off to Technical Writer for any doc updates.
5. Report results. If all acceptance criteria are met, move spec to accepted/.

Record implementation decisions in the spec's Decision Notes.
If a durable architectural decision emerges, create or update an ADR.
```
