# ADR 0014: Host Storage and NAS Mount Boundaries

## Status

2026-10-26: Accepted

2026-10-24: Updated Proposed
2026-10-22: Proposed

## Context

Phobos and deimos each have one approximately 476 GiB NVMe physical volume. Their original LVM
layout allocated approximately 28 GiB to `/`, 447 GiB to `/home`, and 1 GiB to swap, with no free
extents. Persistent service data under `/srv`, rootful Podman storage under
`/var/lib/containers/storage`, and operating-system state therefore share the small root
filesystem. Rootless Podman storage lives under `/home/abhaile/.local/share/containers/storage`.

Observed usage on 2026-10-22 showed that `/home` has substantial unused capacity while phobos root
was already 62% full. Planned media, home-automation, monitoring, and utility services will add
persistent state. The homelab has no NAS today, but stable paths should permit media, backups, and
surveillance recordings to move to network storage later without changing every service
definition.

The layout must distinguish live service state, media, backups, and disposable container storage.
It must also avoid unnecessary per-service filesystems and preserve hardlinks across the media
download and library workflow.

## Decision

### Local host layout

Both hosts use these local filesystem boundaries, validated on 2026-10-26:

- `/` holds the operating system, `/var`, and rootful Podman image and overlay storage.
- `/home` holds human home directories and rootless Podman storage.
- `/srv` is a separate local LV with an ext4 filesystem holding persistent service state.
- Swap and the existing EFI and `/boot` partitions remain separate.

The initial target for each 475.96 GiB volume group is:

| Mount or allocation | Target size |
| --- | ---: |
| `/` | 64 GiB |
| `/home` | 64 GiB |
| `/srv` | 320 GiB |
| swap | existing 976 MiB |
| unallocated VG capacity | approximately 27 GiB |

These symmetric values are the agreed initial allocation plan, not a requirement to consume free
extents. Retaining VG free space is intentional so the filesystem that demonstrates real demand
can be extended later.

Ext4 is selected for `/srv` to match existing Debian host tooling and operational knowledge. It
supports online growth after an LV extension and does not introduce another local filesystem
technology. The NAS filesystem is independent of this local choice.

There will not be separate LVs for individual services, `/var`, Podman graph roots, media
subdirectories, or backup subdirectories. Rootful Podman remains at
`/var/lib/containers/storage`; rootless Podman remains below the owning account's home directory.
Persistent application data remains under `/srv/<service>/`.

### Stable path contract

The stable host paths are:

```text
/srv/<service>/                 local persistent service state
/srv/media/                     shared media tree
/srv/backups/<service>/         service backup destination
/srv/surveillance/              NVR-independent surveillance recordings
```

Service names are the backup namespace. Distinct deployed instances already use distinct service
identities such as `blocky-a` and `blocky-b`. Reproducible or ephemeral state, including Vault
Agent configuration, templates, rendered outputs, and runtime readiness files, is not backed up as
service state. If a future stateful service has multiple instances with the same service identity,
that service must define an instance subdirectory or adopt distinct instance identities before it
writes to shared backup storage.

### Media filesystem boundary

`/srv/media` is one filesystem boundary. Its initial directory contract is:

```text
/srv/media/
├── movies/
├── tv/
├── music/
├── books/
├── downloads/
│   ├── complete/
│   └── incomplete/
└── transcode/
```

Downloads and managed libraries remain on the same filesystem so Radarr, Sonarr, and related
workflows can use hardlinks. Separate mounts or NAS datasets below `/srv/media` must not split
paths that require hardlinks. A deliberately separate transcode workspace is permitted because it
does not participate in that hardlink contract.

### Backup filesystem boundary

`/srv/backups` is one filesystem boundary with logical service subdirectories. Per-service mounts
are not the default. Ownership, access control, encryption, quotas, retention, and restore policy
provide service isolation without multiplying host mount units.

A local `/srv/backups` directory is an initial destination or staging area only. A backup retained
on the same physical NVMe device as its source is not sufficient protection against device or host
loss.

A shared backup mount does not grant every host or service unrestricted write access. NAS export
policy, credentials, ACLs, or repository authorization must limit each backup identity to the
service backup sets it needs. Backup data should also use repository encryption independently of
transport where the selected backup tool supports it.

### Surveillance filesystem boundary

`/srv/surveillance` contains recordings, clips, and exports produced by the active NVR. NVR
configuration, databases, and other durable application state remain under `/srv/<service>/` and
use the ordinary service backup policy.

Surveillance storage is separate from `/srv/media` and `/srv/backups` because it has a continuous
write workload, aggressive capacity-based retention, sensitive access controls, and little value
from conventional backup or long snapshot retention. The path is deliberately independent of
Frigate so a future NVR replacement can retain the same storage contract.

### Future NAS layout

When NAS storage is introduced, it will provide three independent host mounts:

```text
NAS media export    -> /srv/media
NAS backup export   -> /srv/backups
NAS surveillance export -> /srv/surveillance
```

Media, backups, and surveillance remain separate exports or filesystems because they have
different access, snapshot, retention, quota, and replication requirements. The rest of `/srv`
remains on the local LV for latency-sensitive service state.

Mount consumers must fail closed. If an expected NAS mount is absent, media services, backup jobs,
and NVR writers must not write into the underlying local mount-point directory. Systemd mount
dependencies and explicit mount-point validation will enforce this before consumers start.
Existing local data must be migrated and verified before any of the three network mounts is
enabled.

## Alternatives Considered

- **Keep the current large `/home` and use `/` for service data**: rejected because service and
  Podman growth can exhaust the small root filesystem and disrupt the host.
- **Place service data below `/home`**: rejected because home-directory ownership and rootless
  runtime state are different concerns from system service state.
- **Create one LV or NAS mount per service**: rejected as the default because it creates rigid
  allocation, mount, dependency, and recovery overhead without a current isolation requirement.
- **Mount each media subdirectory separately**: rejected because filesystem boundaries prevent
  hardlinks between downloads and managed libraries.
- **Use one NAS mount for both media and backups**: rejected because live bulk data and protected
  recovery data require different permissions and lifecycle policies.
- **Store surveillance below `/srv/media`**: rejected because camera recordings have a distinct
  write, retention, quota, access, and snapshot policy and no hardlink relationship with the media
  library.
- **Use an NVR-specific recording path**: rejected because the storage contract should survive
  replacement of Frigate with another NVR.
- **Add a hostname below every backup service directory**: rejected for the current model because
  stateful replicated services use distinct `-a` and `-b` identities. An instance namespace can be
  introduced only where a future same-named stateful deployment requires it.
- **Move all Podman storage to `/srv`**: rejected because images and overlay layers are disposable
  runtime storage, while `/srv` is the persistent service-state boundary.
- **Use a different local filesystem for `/srv`**: rejected for the initial layout because ext4
  meets current requirements and matches the existing Debian recovery and administration tooling.

## Consequences

- Root filesystem capacity is separated from persistent service-data growth.
- Stable `/srv/media`, `/srv/backups`, and `/srv/surveillance` paths allow a future NAS transition
  without rewriting consumer storage contracts.
- The media layout preserves hardlink-based imports.
- Backup paths remain simple and service-oriented.
- The shared backup tree requires least-privilege write authorization and repository encryption.
- All three NAS mounts become explicit availability dependencies and need fail-closed ordering for
  their writers.
- The initial migration required offline, backup-dependent maintenance to reclaim space from
  ext4 `/home`. Both hosts now retain approximately 27 GiB of unallocated VG capacity.
- Omada and other service-specific backup automation must use the service backup convention.

## References

- [SPEC-2026-030: Local Host Storage Layout](../specs/accepted/0030-host-storage-layout.md)
- [SPEC-2026-031: NAS Storage Adoption](../specs/proposed/0031-nas-storage-adoption.md)
- [Installed host storage and validation](../runbooks/host-storage.md)
- SPEC-2026-017: Media Services
- SPEC-2026-015: Home Automation Services
- SPEC-2026-021: Network Devices
- ADR 0005: Service Authoring Model
