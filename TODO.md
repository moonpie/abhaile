# TODO: Abhaile Project Tracker

Working scratchpad. Specs and ADRs are the durable record; this file tracks the next execution
sequence only.

## Next Up

- [ ] 2026-06-21 Work through Phase 3 service specs.
- [ ] 2026-06-21 Work through Phase 4 network/controller spec.
- [ ] 2026-06-21 Work through Phase 5 CI/dependency automation spec.

## Migration Confirmation and Post-Migration Cleanup

This is a temporary execution checklist for the migration from the legacy custom apply flow to the Ansible local convergence model. The durable architecture remains in the active spec; this file tracks the operational gate and the final cleanup step.

### Migration sequence for hosts already bootstrapped with the legacy flow

The hosts are already enrolled with the old bootstrap path, so migration is not just a repo push. The sequence below reflects the actual transition to the new model.

- [x] 2026-09-09 Push the repo changes for the new model and confirm the target branch is the one the hosts will fetch.
- [ ] 2026-09-09 On each host, confirm the one-time bootstrap prerequisites are present before the new flow is enabled: `abhaile` age identity at `/home/abhaile/.config/sops/age/keys.txt`, repo deploy key at `/home/abhaile/.ssh/gitops_ed25519`, and `known_hosts` is populated.
- [ ] 2026-09-09 On each host, confirm the matching repo secret bundle exists at `secrets/<host>/vault-agent.sops.yaml` and that `.sops.yaml` contains the host recipient rule before enabling the Ansible convergence path.
- [ ] 2026-09-09 Run the host bootstrap / re-enrollment flow on each host using the new path (`scripts/bootstrap.sh` or the equivalent host bootstrap command) so the host is enrolled in the new GitOps + local convergence model rather than the legacy flow.
- [ ] 2026-09-09 On each host, run the local convergence play from `ansible/playbooks/converge.yml` with the correct `ABHAILE_HOST` value to prove the migration path works end to end.
- [ ] Confirm the GitOps runner is enabled and the host is tracking the new repo state instead of the legacy bootstrap path.
- [ ] Confirm `--dry-run` and non-destructive checks are safe and behave as expected.
- [ ] Confirm idempotent re-runs are clean and stable across both hosts.
- [ ] Confirm drift detection and safe-prune semantics are understood and safe.
- [ ] Confirm rollback and health-gate behavior remains intact.

### Go / No-Go gate before cleanup

The cleanup phase must not begin until all items below are satisfied and explicitly reviewed.

- [ ] Confirm no critical legacy apply logic remains outside Ansible ownership.
- [ ] Confirm manual host edits are no longer required for standard reconciliation.
- [ ] Confirm the compatibility wrapper is redundant rather than still required.
- [ ] Confirm the active spec still matches the deployed architecture and operational reality.
- [ ] Sign off: migration is complete enough to begin cleanup.

### Final cleanup step after go decision

- [ ] Remove or simplify deprecated custom apply branches that are no longer required.
- [ ] Eliminate duplicate compatibility logic once Ansible coverage is proven.
- [ ] Remove unnecessary temporary state/ledger scaffolding if no longer required.
- [ ] Update docs and operator guidance to reflect the final supported model.
- [ ] Keep the Ansible-first reconciliation path as the canonical execution model.

### Execution note

`bootstrap.sh` is the host bootstrap / re-enrollment step for a machine already bootstrapped with the legacy flow. `ansible/playbooks/converge.yml` is the local host convergence proof step after enrollment. Cleanup happens only after the migration gate is passed.

## Specs

| Phase | Spec / Authority |
| --- | --- |
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
