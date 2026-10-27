# Spec: Local Host Storage Layout

## Metadata

```yaml
id: SPEC-2026-030
title: Local Host Storage Layout
status: accepted
owner: moonpie
created: 2026-10-22
updated: 2026-10-26
related_adrs:
  - 0014-host-storage-and-nas-mount-boundaries
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [all-stateful-services]
```

## Context

Scope split approved on 2026-10-26: this spec delivers the local host layout and migration only.
Both host migrations, validation, and cleanup are complete and accepted. Future NAS implementation is tracked by
[SPEC-2026-031](../proposed/0031-nas-storage-adoption.md). Future-facing design below is retained
as context for ADR 0014, not as an implementation requirement of this local migration.

Phobos and deimos each have one 476.9 GiB NVMe device with an LVM physical volume of 475.96 GiB.
Before the completed 2026-10-26 migration, allocation on both hosts was approximately:

| Filesystem | Size | Observed use on phobos | Observed use on deimos |
| --- | ---: | ---: | ---: |
| `/` | 27.94 GiB | 16 GiB (62%) | 7.9 GiB (31%) |
| `/home` | 447.07 GiB | 9.8 GiB (3%) | 1.1 GiB (1%) |
| swap | 976 MiB | — | — |
| VG free | 0 | — | — |

Rootful Podman uses `/var/lib/containers/storage` on `/`. Rootless Podman uses
`/home/abhaile/.local/share/containers/storage`. Persistent service data is authored beneath
`/srv`, which was part of `/`; phobos held approximately 4.2 GiB there. That allocation left most
capacity in `/home` while the operating system, rootful containers, logs, and service state
competed for the small root filesystem. Both hosts now use the local layout below; installed
details and validation evidence are recorded in [Host Storage](../../runbooks/host-storage.md).

There is currently no NAS. The short-term layout must use local NVMe storage safely. The long-term
layout must allow media, backups, and surveillance recordings to move to a NAS without changing
the stable paths presented to their consumers.

## Requirements

- [x] Give `/`, `/home`, and `/srv` independent local filesystem capacity on both hosts.
- [x] Retain unallocated volume-group capacity for later evidence-based growth.
- [x] Keep persistent service data under `/srv/<service>/`.
- [x] Preserve and validate all existing `/home` and `/srv` data during migration.
- [x] Document backup and recovery prerequisites before any destructive LVM operation.

## Constraints

- The pre-migration volume groups had no free extents.
- `/home` is ext4 and cannot be shrunk while mounted.
- `/home` contains rootless Podman state and `/srv` contains active service and database state.
- Rootful Podman graph storage remains under `/var/lib/containers/storage`.
- Rootless Podman graph storage remains under `/home/abhaile/.local/share/containers/storage`.
- Existing service data must not be hidden by mounting an empty filesystem over `/srv`.
- A same-device local copy is not the sole backup for the migration that reallocates that device.
- No live resize, filesystem recreation, data deletion, or mount activation occurs without a
  separately reviewed procedure and explicit maintenance approval.
- NAS-backed paths must not be required before a NAS exists.

## Design

### Short-term local layout

The initial target on each host is:

| Allocation | Target | Content |
| --- | ---: | --- |
| `/` | 64 GiB | OS, `/var`, logs, rootful Podman images and overlay storage |
| `/home` | 64 GiB | Human homes and rootless Podman storage |
| `/srv` | 320 GiB | Persistent service data, local media, surveillance, local backup staging |
| swap | existing 976 MiB | Swap |
| VG free | approximately 27 GiB | Reserved for later online LV growth |

The separate EFI and `/boot` partitions remain unchanged. The size targets are intentionally
symmetrical across hosts for operational simplicity and are the agreed initial plan. Free extents
allow phobos root or deimos service storage to grow differently later if observed usage justifies
it.

The new `/srv` filesystem uses ext4, matching the existing root and home filesystems. Ext4 provides
mature Debian tooling, online growth after LV extension, and familiar recovery procedures without
introducing another host filesystem technology. This decision does not require NAS storage to use
ext4; the NAS filesystem remains an implementation choice behind the exported mount contract.

The following directory contract is reserved for service adoption; creating every subtree is
outside this completed host migration:

```text
/srv/
├── <service>/
├── media/
│   ├── movies/
│   ├── tv/
│   ├── music/
│   ├── books/
│   ├── downloads/
│   │   ├── complete/
│   │   └── incomplete/
│   └── transcode/
├── backups/
│   └── <service>/
└── surveillance/
    ├── recordings/
    ├── clips/
    └── exports/
```

There are no per-service LVs. Filesystem ownership and permissions isolate services within `/srv`.
Quota support may be added later if measured contention requires it.

`/srv/backups` on the local NVMe is useful for staging, application exports, and rapid operational
recovery. It is not protection from loss of the NVMe device or host. Before LVM migration, required
host data must be copied to independent storage and restoration must be validated.

### Future storage contracts

ADR 0014 defines media, backup, and surveillance path contracts. SPEC-2026-031 owns NAS
implementation and failure tests; service specs own local consumer adoption.

### Completed migration

Both hosts used the separately reviewed offline SystemRescue sequence. Independent peer-host
archives passed restoration and checksum tests before resizing. Home was shrunk to 60 GiB before
reducing its LV to 64 GiB; root was grown to 64 GiB and a new 320 GiB srv LV was populated and
mounted by UUID. Two ordinary boots, service and reconciliation checks passed per host. Temporary
recovery copies were deleted after explicit cleanup approval.

Detailed one-time execution commands are no longer maintained. See
[Host Storage](../../runbooks/host-storage.md) for installed identifiers and validation evidence.

## Acceptance Criteria

- [x] The approved on-host layout is recorded in source-of-truth configuration or an installation
  runbook for both hosts.
- [x] An independent backup and tested restore path exists before either existing disk is
  repartitioned or any LV is reduced or recreated.
- [x] Bootable rescue media, local console access, required tooling, VG activation, and independent
  backup access are tested on each host without modifying installed filesystems.
- [x] A host-specific migration runbook records exact devices, sizes, commands, expected output,
  abort conditions, and recovery steps and receives separate approval before execution.
- [x] Both hosts expose separate ext4 filesystems for `/`, `/home`, and `/srv` with approximately
  the approved initial sizes and retained VG free capacity.
- [x] Existing home-directory, rootless Podman, service, and database state is preserved and
  validated after migration.
- [x] Rootful and rootless Podman retain their documented graph roots and active workloads return
  healthy.
- [x] Local backup destinations are documented as non-independent until replicated off-host.
- [x] A full reboot validation confirms expected mounts, capacity, permissions, and service health
  on each migrated host.

### Evidence

Implementation evidence for every criterion is recorded by the acceptance commit that introduces
this file and the installed layout reference. Its immutable commit is discoverable through
[this spec's Git history](https://github.com/moonpie/abhaile/commits/main/docs/specs/accepted/0030-host-storage-layout.md).
The maintenance itself was performed manually under explicit operator approval; the commit records
the resulting state and verification rather than executing the storage changes.

Validation evidence for every criterion is summarized in
[Host Storage — Migration Validation](../../runbooks/host-storage.md#migration-validation), with
installed sizes and UUIDs in its Installed Layout section.

#### Completed host migrations

Both hosts completed the 64/64/320 GiB migration, repeated-boot validation, successful
reconciliation, and explicitly approved cleanup on 2026-10-26. The operational layout and concise
validation evidence are recorded in [Host Storage](../../runbooks/host-storage.md). Detailed
one-time command transcripts are no longer maintained as an operational runbook.

The operator approved separating future NAS adoption into SPEC-2026-031. Local media directory
adoption belongs to SPEC-2026-017, surveillance paths to SPEC-2026-015, and Omada backup automation
to SPEC-2026-021. Those service deployments are not prerequisites for accepting the completed local
host migration.

## Out of Scope

- Selecting or purchasing a NAS.
- Choosing NFS versus SMB or another NAS protocol.
- Selecting backup software or repository format.
- Defining backup schedules, retention periods, off-site replication, media-library backup
  coverage, or surveillance recording retention.
- Creating a separate LV for every service.
- Moving Podman graph roots to `/srv`.
- Further destructive storage work beyond the completed, separately approved host migrations.
- Performing live NAS mounts or changing service configuration before the NAS exists.

## Open Questions

None for the completed local layout. Future NAS and backup-policy decisions are tracked in
SPEC-2026-031 and the relevant service specs.

## References

- `docs/adr/0014-host-storage-and-nas-mount-boundaries.md`
- `docs/runbooks/host-storage.md`
- `docs/specs/active/0015-services-home-automation.md`
- `docs/specs/proposed/0017-services-media.md`
- `docs/specs/proposed/0020-host-hardening.md`
- `docs/specs/proposed/0021-network-devices.md`
- `config/mapping.yaml`
- `config/services/`
