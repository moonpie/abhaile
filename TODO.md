# TODO: Abhaile Project Tracker

Working scratchpad. Three jobs: what's next, where decisions live, how to start a session.

## Next Up

**Documentation** or **Phase 3 Services** — operator's choice.

**Phase 3 Services** — next major feature work.
Start with `docs/specs/proposed/0015-services-home-automation.md`.

## Progress

| Phase | Status | Spec / Authority |
|-------|--------|------------------|
| Foundations | [x] | `AGENTS.md`, `README.md`, repo tooling |
| Render Pipeline | [x] | `docs/specs/accepted/0001-render-pipeline.md` |
| Apply Pipeline | [x] | `docs/specs/accepted/0009-apply-pipeline.md` |
| Secrets | [x] | `docs/specs/accepted/0010-secrets-management.md` |
| Validation & Testing | [x] | `docs/specs/accepted/0007-validation-pipeline.md` |
| GitOps Runner | [x] | `docs/specs/accepted/0012-gitops-runner.md` |
| Ops Tooling | [x] | `docs/specs/accepted/0013-ops-tooling.md` |
| Bootstrap | [x] | `docs/specs/accepted/0014-bootstrap.md` |
| Documentation | [x] | 7 ops docs + inventory generator + logging audit |
| Code Quality | [x] | Maintainability audit: 8 sprints complete |
| Services (Phase 3) | [ ] | See breakdown below |
| Network Devices (Phase 4) | [ ] | `docs/specs/proposed/0021-network-devices.md` |

### Services (Phase 3)

| Spec | Scope |
|------|-------|
| `proposed/0015-services-home-automation.md` | Home Assistant, Mosquitto, Zigbee2MQTT, ESPHome, Frigate, Go2rtc |
| `proposed/0016-services-monitoring.md` | Prometheus, Grafana, Loki, Alertmanager, exporters |
| `proposed/0017-services-media.md` | Immich, Jellyfin, Tdarr, \*arr stack, Jellyseerr, Flaresolverr |
| `proposed/0018-services-networking.md` | Gluetun, qBittorrent (VPN egress) |
| `proposed/0019-services-utilities.md` | Homepage, Netbox, Vaultwarden, Postfix, CrowdSec |
| `proposed/0020-host-hardening.md` | nftables, fail2ban, CIS-lite, per-UID routing |

Acceptance criteria live in each spec. Don't duplicate them here.

## Decision Index

| Concern | ADR | Spec |
|---------|-----|------|
| Output paths, environment modes | `0001` | `accepted/0001-render-pipeline.md` |
| Drift detection, state/manifest | `0002` | `accepted/0009-apply-pipeline.md` |
| Runner vs render/apply boundary | `0003` | `accepted/0012-gitops-runner.md` |
| Apply execution model | `0004` | `accepted/0009-apply-pipeline.md` |
| Service authoring model | `0005` | `accepted/0005-service-composition.md` |
| Secrets model, vault-agent boundary | `0006` | `accepted/0010-secrets-management.md` |
| SOPS bootstrap policy | `0007` | `accepted/0014-bootstrap.md` |
| Render pipeline contracts | — | `accepted/0001-render-pipeline.md` |
| Networking renderer | — | `accepted/0002-networking-renderer.md` |
| DNS renderer | — | `accepted/0003-dns-renderer.md` |
| Quadlet renderer | — | `accepted/0004-quadlet-renderer.md` |
| Service composition and includes | — | `accepted/0005-service-composition.md` |
| Software and users renderers | — | `accepted/0006-software-users-renderers.md` |
| Validation pipeline | — | `accepted/0007-validation-pipeline.md` |
| Core services (Phase 1) | — | `accepted/0011-core-services.md` |

All paths relative to `docs/specs/`. ADR paths: `docs/adr/000N-*.md`.

Future implementation decisions: record in the active spec's Decision Notes section. Promote to ADR when a decision crosses service/host/agent boundaries or is expensive to reverse.

## Historical Decisions

Decisions from 2026-01-31 through 2026-05-04 are incorporated into accepted specs and ADRs 0001–0007. Archive: `.old_docs/decision-log-archive.md`.

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
