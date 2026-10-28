# Spec: Private Volume Directory Management

## Metadata

```yaml
id: SPEC-2026-033
title: Private Volume Directory Management
status: active
owner: moonpie
created: 2026-10-29
updated: 2026-10-29
related_adrs:
  - 0005-service-authoring-model
  - 0014-host-storage-and-nas-mount-boundaries
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

Private bind-backed named volumes already identify the host directories a service needs. However,
`manage_host_ownership: false` prevents both directory creation and metadata registration. Several
services relied on directories that existed before Ansible adoption. Their successful reconciliation
therefore did not establish complete directory provisioning intent.

Mosquitto exposed another defect: config rendering created its output-tree parent before volume
rendering ran. The volume renderer returned when that output directory existed, so the manifest
omitted directory intent even though its volume definition supplied the required metadata.
Phobos's absent live parent then failed Ansible check mode. Commit `65cb022` added a supported
but duplicate `composition.config` directory declaration to work around the omission.

The owner inspected all twelve opted-out paths on Phobos. Their shallow contents appeared related
to the assigned applications, and all were on the local `/srv` ext4 filesystem. All twelve were
absent on Deimos, consistent with current service assignments. There was no observed external
filesystem or unrelated-use justification for leaving these private roots unmanaged. This is
metadata and filename evidence, not an examination of file contents or a deletion authorization.

The agreed model is to manage the exact private volume directory's owner, group and mode while
leaving application-created descendants alone. No empty physical host is available or required
for acceptance; missing-directory behavior will be exercised in disposable test fixtures.

## Requirements

- Remove `manage_host_ownership` from schema, service definitions, renderer branches and tests;
  reject the retired field rather than silently ignoring either boolean value.
- Register every non-shared named-volume host directory as a managed directory, regardless of
  whether config rendering already created that directory in the output tree.
- Preserve inspected top-level metadata when adopting previously excluded directories.
- Retain existing deterministic rootless defaults and explicit rootful ownership requirements.
- Preserve `shared: true` behavior: a shared volume declaration does not claim host-directory
  ownership. Keep `/etc/ssl/certs` outside this private-directory mechanism.
- Converge only the declared directory's owner, group and mode. Do not recurse, delete contents,
  or independently restart services for a matching directory-metadata adoption.
- Accept coherent duplicate directory declarations without discarding existing provenance;
  reject conflicting identities or metadata with a clear diagnostic.
- Remove Mosquitto's duplicate config-directory declaration once the volume supplies its
  equivalent managed-directory artifact, preserving the failure history and deployment notes.
- Preserve check-mode behavior, directory-before-file ordering, managed state and data across
  ordinary reconciliation and recovery.

## Constraints

- No new dependencies, privileged render, secret reads, mapping/network changes, storage migration,
  or runner-state edits. Intent remains in `config/`; render remains deterministic.
- No recursive `chown`, `chmod`, deletion, directory recreation, or data cleanup.
- No changes to registry images, container composition, service activation, or NAS ownership.
- Do not treat successful tests in temporary directories as evidence of a full empty-host deployment.
- Existing-host validation records the normal runner's render/check phase or an optional
  operator-run manual check. Publication to `main` when deployment is intended authorizes the
  runner's normal gated apply. Live-host mutation is not a prerequisite for spec acceptance.
- Keep this change separate from SPEC-2026-032: image authoring preserves rendered output, whereas
  this change intentionally adds directory manifest entries.

## Design

### Directory Ownership Contract

A private named-volume declaration is sufficient directory intent. Rootful volumes continue to
require `host_owner` and `host_group`; retain `host_mode`'s existing `0750` default. All twelve
adopted roots will declare owner, group and mode explicitly using the inspection below, including
read-only mounts. Mount access mode does not determine whether the host directory needs creation.

Rootless volumes retain current owner/group defaults from the runtime user and mode `0750`, with
existing explicit overrides available. The rendered manifest always contains concrete resolved
metadata. Removing the opt-out does not introduce mandatory duplicated fields for rootless volumes.

Observed adoption values (2026-10-29):

| Phobos host path | Owner UID | Group GID | Mode |
| --- | --- | --- | --- |
| `/srv/vault/config` | 0 | 0 | `0750` |
| `/srv/vault/data` | 0 | 0 | `0750` |
| `/srv/caddy/internal/config` | 0 | 0 | `0750` |
| `/srv/caddy/internal/data` | 0 | 0 | `0750` |
| `/srv/caddy/dmz/config` | 0 | 0 | `0750` |
| `/srv/caddy/dmz/data` | 0 | 0 | `0750` |
| `/srv/authelia/authelia/config` | 0 | 0 | `0750` |
| `/srv/authelia/authelia/data` | 0 | 0 | `0750` |
| `/srv/authelia/redis/data` | 999 | 0 | `0750` |
| `/srv/omada-controller/omada-controller/cert` | 0 | 0 | `0750` |
| `/srv/omada-controller/omada-controller/data` | 508 | 508 | `0750` |
| `/srv/omada-controller/omada-controller/logs` | 508 | 508 | `0750` |

Redis's existing child snapshot has group `1000`, although its parent has group `0`. Preserve both.
Other application-created child modes and ownership, certificates, databases, backups and logs
remain outside top-level directory metadata convergence. Reconfirm root metadata before deployment
if these observations no longer match the host; do not substitute container runtime UID assumptions.

Shared paths retain their existing handling and host-path sharing validation. `shared: true` must
continue to mean actual sharing, not become a replacement ownership opt-out. Future shared writable
application storage needs its own agreed owner under the applicable service/storage contract.

### Registration and Duplicate Handling

In `src/abhaile/renderers/quadlets/volumes.py`, separate output-directory creation from registering
intent. The existence of a physical output directory is not evidence of a managed artifact. A
previously created output directory must still lead to a manifest directory declaration.

Before inserting a volume-derived directory artifact, inspect existing collector registration:

- If an existing artifact has the same render/target directory identity, service owner and resolved
  owner/group/mode, reuse it and preserve contributor metadata and applicable hints.
- If its kind, target, service owner or directory metadata conflicts, fail with the path and
  conflicting declarations. Do not use renderer order or unconditional `replace=True` to choose.
- Preserve existing detection of distinct rendered artifacts targeting the same host directory;
  do not add a generic cross-service last-wins or ownership-merging mechanism.

Render must not perform host account lookups to decide whether differently authored names and IDs
are equivalent. Use consistent declarations and existing deterministic value handling; unresolved
identity differences should produce a clear conflict rather than silently override one another.

Explicit `composition.config` directories remain supported for genuine additional directory intent.
Remove the Mosquitto entry only because its named volume already declares the exact same directory,
with owner/group `root` and mode `0755`. Its `data` and `secrets` volumes retain their existing intent.

### Convergence

Reuse the current manifest inventory and `managed_directories` role. It already runs before service
file publication and uses `file: state=directory` without recursion. Add bounded validation/tests
where necessary so an existing file or symlink at a managed directory target is rejected before
metadata enforcement, rather than redirected or replaced. Do not introduce a second apply engine
or filesystem staging model.

Check mode must recognise an absent config parent supplied by a managed volume root without creating
it. A real run against a disposable fixture must create the root, preserve descendants and converge
idempotently. Recovery must not recursively remove data-bearing directories merely because an older
manifest does not list them. Matching inspected metadata should require no ownership repair or
service restart on the established hosts.

### Acceptance Environments

Use production rendering and Ansible roles with destinations redirected into temporary test trees:

1. Missing directory roots and config files beneath them.
1. Existing roots with matching or deliberately drifted metadata and populated child trees.
1. Repeated rendering, duplicate declarations, conflicting metadata, and existing file/symlink targets.

Tests can use the current test account for real filesystem ownership operations and assert the
intended application numeric IDs separately in rendered metadata. Do not require production user
IDs or an empty machine merely to run the suite. Record what ownership combinations were actually
exercised and any unavailable privileged checks.

On Phobos and Deimos, the operator reviews the intended render/manifest delta and records check
mode from the normal runner, or uses the documented unprivileged-render/privileged-check workflow
for an optional manual check. Record host revisions, expected metadata and results. No SSH
automation, service restart, Vault access or live apply is needed solely to perform a manual check.
Optional disposable-container startup/reconciliation observations can
strengthen entrypoint-ownership evidence; a full empty-host deployment and application startup
remain unverified unless separately performed.

### Boundaries and Affected Records

This fixes private named-volume roots, not automatic creation of every file's parent directory.
Blocky's `/srv/blocky` and Omada Mongo's `/srv/omada-controller/mongodb/initdb` are file-only parent
examples; their provisioning policy remains a separate design question. Do not quietly add service
specific parent workarounds or claim this spec resolves all fresh-host dependencies.

| Record | Treatment |
| --- | --- |
| ADR 0005 + ADR index | Record mandatory private-volume directory intent and the descendant boundary |
| Active 0015 | Preserve the original failure/fix history; link replacement and later host-validation evidence |
| Active 0032 | Keep image authoring scope and output-equality evidence separate; cross-reference this delivery |
| Accepted 0004, 0005, 0011 | Reference volume/composition/core-service contracts; do not reopen completed specs |
| Accepted 0028 | Preserve directory-before-file and check-mode semantics; use production roles in regression tests |
| Accepted 0030 / ADR 0014 | Preserve local `/srv/<service>` storage boundaries; no filesystem changes |
| Proposed 0031 | No immediate NAS change; shared mounts retain separate ownership and mount-safety requirements |

Implementation areas: `schemas/common.schema.json`, `src/abhaile/renderers/quadlets/volumes.py`,
collector integration as needed for coherent registration, the twelve opted-out volume declarations,
Mosquitto's duplicate entry, bounded managed-directory target checks, and relevant renderer/schema/
Ansible tests. Update the authoring guide and Mosquitto runbook during implementation. Change the
current misleading “rootful writable volume” diagnostic to describe private named volumes, since
read-only mounts also require correctly provisioned host roots.

## Decision Notes

- Decision: Remove the ownership opt-out for private volume roots and retain rootless defaults.
  Rationale: Inspected paths have service-private uses; volume intent already identifies needed
  roots. Impact: Explicit adoption metadata for twelve roots, with no recursive application-data
  management. ADR: [0005](../../adr/0005-service-authoring-model.md).
- Decision: Reuse matching directory declarations and reject conflicts.
  Rationale: Directory registration must not depend on incidental output existence or renderer
  order. Impact: Duplicate authoring is unnecessary; conflicting intent fails visibly.
- Decision: Accept using disposable filesystem fixtures and recorded existing-host check mode.
  Rationale: No empty physical host is available. Impact: Proves the bounded directory contract;
  does not claim complete first-install or application-startup verification.

## Acceptance Criteria

- [ ] Schema rejects the removed field for both boolean values; all service definitions validate
  without it, and renderer code no longer branches on the field.
- [ ] All twelve adopted roots render the inspected numeric owner/group/mode; existing rootless
  defaults, read-only private roots and shared-path behavior remain correct.
- [ ] A pre-existing render-tree parent still registers a managed directory; identical declarations
  preserve provenance and conflicting identities/metadata fail deterministically.
- [ ] Mosquitto's redundant config-directory entry is removed and the production config-parent
  check succeeds with the volume-managed parent absent in a disposable fixture.
- [ ] Production directory-role tests create missing roots, repair top-level metadata drift and
  converge idempotently without changing child content, modes or ownership. Existing file/symlink
  targets fail safely; recovery/cleanup does not recursively delete application data.
- [ ] All-host render comparison accounts for intended directory manifest additions and metadata
  changes only; existing config, Quadlet, image, network and helper bytes remain unchanged.
- [ ] Existing-host check-mode results for Phobos and Deimos are recorded by the operator, including
  revision, expected directory changes and unavailable validation. No empty-host deployment is
  required or claimed.
- [ ] Relevant tests and repository checks are recorded; guide, runbook, ADR/index and spec 0015
  references describe the implemented behavior. Each completed criterion has commit/PR and
  validation evidence.

### Evidence

Local implementation and disposable-fixture validation are present in the working tree.
Acceptance criteria remain unchecked pending implementation commit/PR references and formal
evidence. Operator-run Phobos and Deimos check-mode results have not been supplied; that criterion
remains pending. The spec stays active.

The operator's directory/mount listings establish adoption metadata only. Application file
contents were not read; no unrelated files were identified in the shallow inspection. No live-host
ownership changes, deletion, service restarts or deployment were performed during implementation.

### Local Validation (2026-10-29)

- Agent review approved activation. Independent Code Reviewer and SysAdmin implementation reviews
  found no material bugs or operational blockers.
- 39 focused tests passed, including all 16 production `managed_directories` role cases and the
  production Mosquitto absent-config-parent check. Filesystem mutations were confined to temporary
  test trees owned by the test account; intended production UIDs/GIDs were asserted in manifests.
- The broader selected suite below passed 672 tests with 86.64% branch-aware coverage, exceeding
  the configured 85% gate. The managed-directory role suite was run separately; the complete runner
  and unrelated Ansible suites were not rerun.
- `make lint` passed, including repository hooks, mypy and 100% docstring coverage. New untracked
  files were explicitly passed to pre-commit because `--all-files` does not select them.
- Fresh all-host before/after render comparison found identical bytes for every non-manifest
  file. Phobos adds exactly the twelve adopted directory entries and changes only the existing
  `/srv/mosquitto/config` entry's hints/provenance after removal of its duplicate declaration.
  No entries are removed. Deimos's manifest is unchanged, and manifest metadata outside entries
  is unchanged on both hosts. All output roots were temporary directories.

```bash
.venv/bin/pytest tests/unit/python/renderers/test_volume_directory_registration.py \
  tests/integration/test_private_volume_directories.py \
  tests/integration/test_ansible_managed_directories.py \
  tests/integration/test_mosquitto.py --no-cov

.venv/bin/pytest tests/unit/python \
  tests/integration/test_container_image_authoring.py \
  tests/integration/test_private_volume_directories.py \
  tests/integration/test_quadlets.py \
  tests/integration/test_composition_includes.py \
  tests/integration/test_quadlet_devices.py \
  tests/integration/test_mosquitto.py \
  tests/integration/test_dns.py \
  tests/integration/test_ingress.py \
  tests/integration/test_render_e2e.py \
  tests/integration/test_vault_templates.py
```

Implementation and test evidence awaiting a commit reference:

- `schemas/common.schema.json` rejects the retired field; opted-out service declarations now
  supply the inspected metadata. `test_private_volume_directories.py` checks both retired boolean
  values, all service schemas and actual Phobos directory metadata.
- `src/abhaile/renderers/quadlets/volumes.py` always registers private directory intent and reuses
  matching registrations without replacing provenance. `test_volume_directory_registration.py`
  covers incidental output parents, metadata/identity conflicts, unresolved name-versus-ID
  differences, existing output files/symlinks, rootless defaults and shared exclusions.
- `ansible/roles/managed_directories/tasks/main.yml` inspects and validates every target before
  nonrecursive convergence. Its integration suite tests absent roots, root-mode repair, child
  content/mode/UID/GID preservation, idempotence, and file/live-link/dangling-link rejection in
  check and real modes before earlier valid targets change.
- The empty-older-inventory fixture proves the directory role leaves existing data untouched;
  it is not a complete runner-recovery proof. Existing directory cleanup/recovery safeguards are
  unchanged and their unit tests remain in the broader selected suite.
- Mosquitto's named volume now supplies its directory artifact without the workaround. Its real
  config-role check succeeds with an absent parent in a temporary target tree. The authoring guide,
  runbook, ADR/index and spec 0015 preserve the failure history and describe the replacement.

## Out of Scope

- Live deployment, destructive cleanup, recursive metadata changes, or forced service restarts.
- Requiring or rebuilding an empty physical host, or claiming a complete bootstrap proof.
- Generic parent creation for file-only bind mounts/config entries.
- Service image authoring, new runtime inheritance, NAS adoption, or storage relocation.
- Changing runner recovery authority or replacing Ansible's bounded convergence model.

## Open Questions

File-only parent provisioning remains deferred. A separate proposal is needed before changing
those ownership/default rules; this does not block the named-volume directory contract here.

## References

- [ADR 0005: Service Authoring Model](../../adr/0005-service-authoring-model.md)
- [ADR 0014: Host Storage Boundaries](../../adr/0014-host-storage-and-nas-mount-boundaries.md)
- [0004: Quadlet Renderer](../accepted/0004-quadlet-renderer.md)
- [0005: Service Composition](../accepted/0005-service-composition.md)
- [0011: Core Services](../accepted/0011-core-services.md)
- [0015: Home Automation](../active/0015-services-home-automation.md)
- [0028: Target Host Reconciliation](../accepted/0028-target-host-reconciliation-model.md)
- [0030: Host Storage Layout](../accepted/0030-host-storage-layout.md)
- [0031: NAS Storage Adoption](../proposed/0031-nas-storage-adoption.md)
- [0032: Container Image Authoring](../active/0032-container-image-authoring.md)
