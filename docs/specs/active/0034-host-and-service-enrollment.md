# Spec: Host and Service Enrollment

## Metadata

```yaml
id: SPEC-2026-034
title: Host and Service Enrollment
status: active
owner: moonpie
created: 2026-10-29
updated: 2026-10-30
related_adrs:
  - 0003-gitops-runner-responsibility-boundary
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0008-host-infrastructure-authoring-model
  - 0013-last-successful-ansible-reconciliation
  - 0014-host-storage-and-nas-mount-boundaries
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

Two Mosquitto deployment failures exposed assumptions inherited from existing-host migration.
First, its required config directory was absent from the manifest; spec 0033 addresses that
registration defect. Next, the rootful Quadlet role refused missing volume definitions because
its deferred-family guard requires existing identical files.

The subsequent review found related ordering and provisioning gaps: config publication checks a
service before its new Quadlet is installed; native units and build consumers can start before
their inputs exist; host networking runs after some network consumers; and an active Vault Agent
does not prove a newly added secret template has produced its output. General rootless services
are advertised but reconciliation currently restricts them to Vault Agent. Declared users/groups
are rendered without ordinary convergence, and bootstrap creates only the automation identity.
The bootstrap package list also does not fulfill all declared service software prerequisites.

The goal is a consistent lifecycle for an additional host joining an existing lab and for later
host/service additions. Vault already exists. This is a provisioning and ordering correction,
not a replacement reconciliation architecture or an exhaustive acceptance programme.

## Requirements

- Create missing declared resources using native facilities, then converge supported mutable
  properties. Existing resources must not be silently replaced or destructively adopted.
- Support first deployment of every advertised service pattern, not just currently mapped
  examples. A service must not require its own previous manual installation.
- Establish accounts, required software, storage prerequisites, networking and configuration
  before activating their consumers. Required runtime secret outputs must be ready as well.
- Use the same reconciliation roles for additional-host bootstrap and subsequent deployment.
  Bootstrap establishes minimum trust/tooling and hands over; it is not a second installer.
- Preserve check-mode safety, existing applications/data, management connectivity, normal runner
  operation and the last-successful recovery model.
- Keep implementation small: existing Ansible roles/modules and systemd/Podman dependencies,
  without custom provisioning scripts, a generic operation compiler or another state ledger.

## Constraints

- Intent remains in `config/`; rendering stays unprivileged, deterministic and secret-free.
- No first-lab Vault deployment, initialization or unseal redesign. Existing Vault availability,
  policies/AppRole provisioning and protected operator trust handoff remain prerequisites.
- A clean host means a documented supported Debian baseline with operator access, package/repo
  reachability, identified interfaces and provisioned local storage. No disk formatting or
  implicit storage migration is authorized by this spec.
- Preserve protected automation identity/access and current networkd adoption/recovery safeguards. Existing UID/GID
  conflicts, incompatible runtime resources and conflicting network ownership fail clearly.
- Do not renumber/delete accounts, recursively change application data, or remove/recreate
  data-bearing Podman volumes to make enrollment succeed.
- Live apply remains explicitly authorized through the existing documented mechanisms. This
  spec does not authorize live host actions or ad hoc recovery-record edits.

## Design

### Create Missing Resources and Order Their Consumers

Use ordinary idempotent tasks for resource creation and publication. Separate publication from
activation where a role currently starts a consumer before another role can publish its inputs.
Gather changed owners with existing role facts and activate once at the appropriate phase;
retain existing-service config refresh behavior. Use native unit dependencies for runtime
relationships rather than building an application-specific dependency executor.

Check mode must not install prerequisites or start workloads to make its own validation possible.
Bootstrap supplies the minimum validation tooling; when a check depends on a new account,
executable, network or build output that remains absent, report that check as pending rather than
successful. Perform the prerequisite-dependent validation in the authorized live path once its
prerequisites exist and before activating the consumer. Retain existing preflight file-safety and
recovery gates; this does not permit bypassing validation or weakening network protections.

The intended ordering is foundations, declared prerequisites, directories/files/unit definitions,
then activation and health. This is a dependency rule, not a rigid global sequence: Vault Agent
must activate before its outputs can be consumed, and managed builds must complete before their
consumers start. Network operations retain their existing validation and recovery safeguards.

Missing ordinary directories, users/groups and supported Quadlet resources should be routine
creation cases. File-only config parents also need deterministic directory intent, with existing
explicit/private-volume metadata taking precedence; do not guess metadata from live state or
create parents incidentally with unspecified permissions. Reject conflicting declarations.

For existing bind-volume/network objects, inspect identity and relevant options before relying
on them. Permit compatible reuse; fail on ambiguity or incompatibility. Creating a missing
Quadlet file does not authorize changing an existing runtime object's options. Retain the
current refusal of unsupported existing resource-definition changes.

### Coverage

| Area | Enrollment behavior |
| --- | --- |
| Users/groups | Create declared identities and memberships before owned files/services; validate name/ID collisions and preserve protected access |
| Rootless foundations | Prepare the declared user's home, required subordinate IDs, linger and user manager before its supported workloads |
| Host networking | Establish declared VLANs/interfaces before dependent Podman networks or addressed services; retain management-link safeguards |
| Software | Supply declared supported packages and existing managed-build outputs before consumers; diagnose unsupported acquisition early |
| Native systemd | Publish config, environment, drop-in parents and units before activation; distinguish daemons, successful oneshots and triggers |
| Rootful/rootless containers and pods | Support initial units, images/build outputs, mounts, networks and named-user execution without pre-existing target workloads |
| Config-only/shared definitions | Publish declared files/directories and preserve include semantics without inventing an activation requirement |
| Auxiliary Quadlets | Handle missing volume/network/image definitions through native publication/dependencies and collision checks |
| Vault Agent and secrets | Enroll templates and user units, then wait boundedly for required protected outputs before their consumer starts |
| Caddy/CoreDNS | Validate and publish initial configuration without requiring the target service already running; order watchers, builds and activation |

Schema-rejected combinations remain unsupported. Rendering a definition is not sufficient proof
that reconciliation supports it; discrepancies must be resolved or explicitly brought back for
agreement, not hidden by narrowing this table to current role restrictions.

For packages, prefer Ansible's package facilities. Existing supported local-build workflows
remain the build mechanism. Do not introduce a command-oriented software operation engine to
execute all future-facing software declarations. Inventory remaining download/driver/build
prerequisites before implementation; any newly required acquisition mechanism needs a concrete
design review rather than an assumption that the binary is already installed.

For rootless account preparation, use existing host intent where it suffices; any additional
intent must be explicit and schema-validated. Avoid arbitrary subordinate-ID allocations in
render and do not grant ordinary service users authority over automation access.

### Additional-Host Bootstrap

Keep the existing trust handoff for repository access and Vault Agent authentication. Install
only the minimum tooling needed to render and reconcile, then use ordinary roles to establish
declared foundations and services. Do not require an initial last-successful revision before
the first reconciliation; record it only once the required initial reconciliation and readiness
have succeeded. A missing required output is an actionable failure, not a warning followed by
successful enrollment. An interrupted bootstrap must be safely retryable without claiming a
successful baseline or arming recovery from an incomplete one.

### Implementation Boundaries

Expected code areas are `scripts/bootstrap.sh`, the existing Ansible orchestration and resource
roles, host/service renderers and schemas where required intent is missing, and actionable health
checks. Update `docs/guides/adding-a-service.md` and bootstrap/host guidance to describe the same
provisioning path. No manually maintained parallel resource inventory is needed.

Deliver in focused changes: host prerequisites, resource creation, publication/activation
ordering, then bootstrap handoff. Resolve shared ordering together where splitting would leave
an unusable intermediate contract. Keep detailed test planning proportional to each change.

This spec proposes an explicit extension to ADR 0013's deferred software and reserved host-access
boundaries. Before implementing those extensions, amend the current ADRs to record the approved
bounded behavior; do not revive superseded reconciliation models. Preserve accepted specs as
historical delivery records and link this follow-up from relevant current guidance.

## Decision Notes

- Decision: Scope clean-host enrollment to an additional host with existing Vault.
  Rationale: Lab creation is not the current operational need.
- Decision: Prefer create-if-missing and sensible dependency ordering through native mechanisms.
  Rationale: Existing-host migration restrictions must not become bespoke provisioning systems.
- Decision: Keep one lifecycle coverage table with focused implementation changes.
  Rationale: Catch shared assumptions without turning the Mosquitto correction into a rewrite.

## Acceptance Criteria

- [ ] The coverage table has implementation evidence or explicitly agreed remaining boundaries;
  no supported service type depends on its own previous manual installation.
- [ ] Missing host prerequisites and service resources are created in the required order;
  incompatible existing resources fail clearly while existing application data is preserved.
- [ ] Additional-host bootstrap uses the ordinary reconciliation path and records its first
  successful revision only after required convergence/readiness succeeds.
- [ ] Focused tests cover changed creation/ordering behavior, check-mode safety, unchanged reruns
  and relevant failure/retry behavior; documentation and governing ADRs match implementation.

### Evidence

Implementation is present in the working tree; no live-host acceptance is claimed. The context records static
review findings; missing auxiliary Quadlet refusal was also reproduced in disposable role checks.
An empty physical host is not required. Use temporary fixtures and disposable Debian environments
where actual systemd/Podman behavior needs verification, recording their practical limits.

### Implementation Progress

Native host foundations, file-parent registration, auxiliary Quadlet creation, generic rootless
workloads, separated publication/build/activation, candidate Caddy validation, secret-output waits
and bootstrap readiness gates are implemented. Vendor-unit drop-ins carry explicit parent-unit
activation for Chrony and ddclient. Existing CoreDNS zone-only reload behavior is preserved.

Validation so far: 674 Python/render/bootstrap tests passed with 86.76% branch-inclusive coverage;
24 production-role service-config, Vault Agent and manifest-selection cases passed. Additional
focused account, rootful/rootless Quadlet and Caddy/CoreDNS checks are recorded in their tests.
These are fixture-based checks, not proof of a clean-host runtime deployment.

Delivery remains subject to recovery compatibility review: the previous successful revision must
understand newly managed families before their publication is enabled. No commits or pushes have
been made for this spec. Acceptance checkboxes remain open pending delivery evidence.

## Out of Scope

- Bootstrapping a lab without Vault, redesigning secret storage or exposing credential values.
- Disk provisioning, NAS migration, account renumbering/removal, and destructive runtime adoption.
- A generic deployment engine, new runner/recovery ledgers or parallel bootstrap apply path.
- Automatically executing every existing command-oriented software declaration.
- Exhaustive acceptance infrastructure before the provisioning design and fixes are agreed.

## Open Questions

- Which currently declared software prerequisites need acquisition beyond standard packages and
  existing managed builds? Resolve concrete cases during implementation planning.

## References

- [Software and users renderers](../accepted/0006-software-users-renderers.md)
- [Bootstrap](../accepted/0014-bootstrap.md)
- [Target-host reconciliation](../accepted/0028-target-host-reconciliation-model.md)
- [Host storage layout](../accepted/0030-host-storage-layout.md)
- [Home automation](../active/0015-services-home-automation.md)
- [Container image authoring](../accepted/0032-container-image-authoring.md)
- [Private volume directory management](../active/0033-private-volume-directory-management.md)
- [Current reconciliation decision](../../adr/0013-last-successful-ansible-reconciliation.md)
- [Adding a service](../../guides/adding-a-service.md)
