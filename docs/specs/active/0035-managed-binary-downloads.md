# Spec: Managed Binary Downloads

## Metadata

```yaml
id: SPEC-2026-035
title: Managed Binary Downloads
status: active
owner: moonpie
created: 2026-11-05
updated: 2026-11-09
related_adrs:
  - 0008-host-infrastructure-authoring-model
  - 0013-last-successful-ansible-reconciliation
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [sops]
```

## Context

Commit `24cd875` updated the SOPS download pin to 3.13.3. At that time, both hosts
reported 3.13.1 because reconciliation rendered command-oriented
download definitions without executing them. The operator requires
reconciliation to manage this binary on 2026-11-05.

ADR 0013 explicitly defers arbitrary software execution. This proposal
extends supported provisioning with a declarative binary download.
ADR 0013 authorizes this bounded family; delivery remains tracked here.

## Design

### Supported software boundary

Use native APT provisioning for standard host packages and retain the
existing Quadlet image/build handling. Add only a small native Ansible
role for standalone downloaded executables. Do not introduce a general
software installer or execute authored command lists.

Extend the existing software action schema with a mutually exclusive
declarative download form. Start with SOPS as a standalone Linux amd64
binary. Describe the pinned HTTPS URL, SHA-256, absolute destination,
root ownership and executable mode. Initially allow regular executables
directly under `/usr/local/bin` only. Retain existing command-oriented
definitions for compatibility with their current render-only handling.

### Manifest identity and integrity

Add one binary resource kind to the existing manifest. Its `sha256` and
`size` identify the rendered download declaration, preserving the existing
collector contract. Explicit `apply_hints` carry the executable's expected
SHA-256, owner, group and mode. Rendering never downloads the payload.

Ordinary integrity auditing handles this kind explicitly: hash the live
executable against the payload checksum and inspect ownership and mode,
rather than comparing executable bytes with the declaration checksum.
Use the existing bounded hashing rules. Binary drift must prevent a false
clean fast-path result.

### Local inspection and publication

Use native Ansible modules to inspect, fetch, verify and publish the
binary under the existing runner lock. Validate the destination and its
parents before mutation, reject conflicting managed targets, and avoid
following symlinks or replacing unexpected target types. Establish the
binary before activating declared consumers.

A matching executable requires no upstream request. If only ownership or
mode differs, repair that metadata locally without downloading. If content
is absent or mismatched, download into a private temporary location on the
destination filesystem, verify the payload checksum, set ownership and
mode, then publish by atomic replacement. Download or verification failure
preserves the installed executable. Clean temporary files on normal success or
handled failure; do not retain payloads as a persistent cache.

In check mode, compare the installed checksum and metadata with declared
intent without downloading or installing. Report required changes without
claiming that upstream availability or download verification has passed.

### Recovery limits

Use the existing runner lock, last-successful authority and recovery flow.
If reconciliation fails after replacement, the last-successful declaration
supplies the previous URL and checksum. Reconciliation downloads that
version only when the installed content differs. If the required release
is unavailable, recovery fails visibly, preserves the currently installed
executable and leaves existing recovery authority and markers intact.
Atomic publication prevents partial installation; offline rollback and
application compatibility are not guaranteed.

If first adoption fails and the last-successful manifest has no binary
entry, recovery retains the executable. It does not delete a bootstrap
tool or claim to restore an unmanaged predecessor. Recognize this case
through the existing candidate-only residue handling, without a backup
registry or new recovery record. This retained-executable rule applies to
this standalone-binary family, not to arbitrary software installation.

Ordinary removal and destination changes remain unsupported and must be
rejected before managed mutation. Do not add a general uninstaller.

### Staged rollout

1. Deploy support for the resource kind, audit and recovery classification
   without enrolling a binary. Establish that revision as last-successful
   on both hosts so recovery understands the new family.
1. Adopt the existing SOPS 3.13.1 with its verified checksum. Confirm the
   checksum on both hosts and establish the managed baseline on both before
   upgrading. A matching installation is not replaced during adoption.
1. Upgrade the declaration to SOPS 3.13.3 and validate normal reconciliation
   and recovery against the managed 3.13.1 baseline.

Keep bootstrap's SOPS pin and checksum aligned with the host declaration.
The first implementation supports standalone binaries. Vault CLI's ZIP
distribution requires a separately reviewed extension.

## Acceptance Criteria

- [x] Schema rejects mixed declarative and command-oriented forms and invalid URLs,
  checksums, destinations and modes. Schema validation restricts destination
  syntax to direct children of `/usr/local/bin`; live checks reject non-regular targets.
- [x] SOPS renders deterministically as a managed resource on both hosts, with
  declaration identity distinct from payload checksum and metadata.
- [x] Matching installations and metadata-only repair make no upstream requests,
  including when the upstream host is unavailable.
- [x] Check mode reports absent, mismatched and matching binaries without mutation
  or downloads.
- [x] Apply installs or updates atomically and a second apply is idempotent.
- [x] Download failure, checksum mismatch and unexpected paths preserve installed
  software; publication uses the existing runner lock and cleans temporary files.
- [x] Ordinary integrity checks detect binary content and metadata drift.
- [x] Runner recovery tests cover an interrupted upgrade, restoration from the
  previous declaration, unavailable upstream during restoration, and retention
  during failed first adoption without deleting an existing bootstrap executable.
- [x] Unsupported removal, destination changes and conflicting managed targets
  are rejected safely before managed mutation.
- [x] Existing command-oriented download, build and command definitions preserve
  their render-only behavior.
- [x] ADR 0013, bootstrap guidance and software documentation explain the supported
  resource and recovery boundaries, including the upstream dependency for rollback.
- [x] The support-only revision is last-successful on both hosts before enrollment;
  both then establish a checksum-verified managed SOPS 3.13.1 baseline before upgrade.
- [ ] Both hosts report SOPS 3.13.3 with the declared checksum after reconciliation.
- [ ] An existing age-encrypted artifact decrypts successfully with plaintext
  discarded rather than printed or written persistently.

## Evidence

Record implementation commits, automated checks and operator validation
against each completed criterion.

Implementation reference for completed criteria: commit `b94c3b2652c4e6d4dffbd67a5f4a646e1e5d4166`
(`feat: add managed host binary download support`). Test references below provide
validation evidence for those criteria.

Both hosts accepted that support-only revision on 2026-11-08. Deimos completed
with `full-new-commit`, exit 0, 65 audited entries and a clean post-full result;
Phobos completed with `full-new-commit`, exit 0, 191 audited entries and a clean
post-full result. Both reported zero drift/uncertainty and no rollback.

Before enrollment, the operator confirmed `/usr/local/bin/sops` on both hosts
matches the 3.13.1 checksum
`620a9d7e3352ababeca6908cea24a6e8b14ce89a448ddbd3f94f1ef3398f470a`.
Enrollment commit `041cef77c9ed816a95a2555361908f10b80065ae` declared that same
binary as managed. Phobos completed its adoption at 2026-11-09T00:02:42Z with
`full-new-commit`, exit 0, 193 audited entries and a clean post-full result.
Deimos subsequently passed `fast-clean` at 2026-11-09T00:04:42Z with that commit
as last-successful, exit 0 and 68 audited entries. Both reported zero drift and
uncertainty; the operator confirmed the original checksum remains installed on
both hosts. Both-host rendering and eight renderer tests passed before enrollment.
This establishes the managed 3.13.1 baseline before the 3.13.3 upgrade.

The upgrade changes the declaration and bootstrap pin together to 3.13.3, using
the upstream Linux amd64 checksum
`e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b`.
Host upgrade and age-decryption validation remain pending.

Validation on 2026-11-08: `make lint`, all 580 fast unit tests, the 166-test
focused regression set, and deterministic renders of both hosts passed. The
additional full-suite run was stopped; it is not claimed as completed validation.

- Schema and deterministic renderer coverage:
  `tests/integration/test_binary_render.py`.
- Native role installation, offline no-op, metadata repair, failed verification,
  restoration and complete-role check mode:
  `tests/integration/test_ansible_managed_binaries.py`.
- Actual runner recovery and pre-mutation removal rejection:
  `tests/integration/test_runner.py`; removal classification:
  `tests/unit/python/state/test_removals.py`.
- Payload identity, metadata drift and bounded auditing:
  `tests/unit/python/test_integrity.py`.
- Operator delivery instructions: [managed binaries runbook](../../runbooks/managed-binaries.md).

## Out of Scope

- Generic execution of software command lists.
- Archive extraction, package repositories and source builds.
- A new software operation engine or runner recovery ledger.
- Persistent payload caches, backup registries and offline rollback guarantees.
- Arbitrary filesystem destinations and automatic software removal.
