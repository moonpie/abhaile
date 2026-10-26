# Host Storage

## Installed Layout

Both hosts completed migration and validation on 2026-10-26. ADR 0014 defines the durable storage
and future NAS contracts. SPEC-2026-030 records local migration delivery; proposed SPEC-2026-031
tracks future NAS adoption.

| Allocation | Both hosts | Purpose |
| --- | ---: | --- |
| `/` | 64 GiB ext4 | OS, `/var`, rootful Podman storage |
| `/home` | 64 GiB ext4 | User homes and rootless Podman storage |
| `/srv` | 320 GiB ext4 | Persistent service state and local bulk storage |
| swap | 976 MiB | Existing swap LV |
| VG free | 27656 MiB (6914 extents) | Reserved for future growth |

Each host uses `/dev/nvme0n1p3` as its LVM PV, with 4 MiB extents. The VGs are `deimos-vg` and
`phobos-vg`; each contains `root`, `home`, `srv`, and `swap_1`. Root spans two linear segments;
this is expected. EFI and `/boot` retain their original partitions.

| Host | `/srv` filesystem UUID |
| --- | --- |
| deimos | `87f30644-ea35-44bd-8f94-6efad48f2964` |
| phobos | `ea8a4ca2-87cf-44f2-823f-abd5e356be1a` |

Each `/etc/fstab` mounts `/srv` by UUID as `ext4 defaults 0 2`. Existing root and home UUIDs were
preserved. Rootful Podman remains at `/var/lib/containers/storage`; rootless Podman remains at
`/home/abhaile/.local/share/containers/storage`. Bind-backed service volumes resolve through `/srv`.

Useful read-only checks:

```bash
findmnt --real -o TARGET,SOURCE,FSTYPE,OPTIONS,UUID
```

```bash
df -h / /home /srv
```

```bash
sudo lvs -o vg_name,lv_name,lv_size,devices; sudo vgs -o vg_name,vg_size,vg_free,vg_extent_size
```

## Migration Validation

Both migrations used SystemRescue 13.02, with separately approved device-specific sequences.
Home ext4 was shrunk to 60 GiB before reducing its LV to 64 GiB, then grown to fill it. Root was
grown to 64 GiB and a new 320 GiB ext4 srv LV was populated with metadata-preserving copies.
Offline filesystem checks passed, and source/target comparisons passed before activating `/srv`.

Writers were stopped before archiving `/home` and `/srv`, including Phobos's stateful applications
and databases. Archives passed gzip tests, full extraction, recursive comparison, direct tar
comparison, and independent peer-host checksum verification before resizing.

EFI dirty-state repairs passed offline checks on both hosts. Deimos separately tested an installed
boot before LVM changes. The operator explicitly chose to combine Phobos's EFI and migration boot
validation at its first post-migration boot.

Both hosts passed two ordinary boots, mount and capacity inspection, service/container checks,
DNS/network checks, kernel storage-log checks, and successful GitOps reconciliation. Integrity
checks reported zero drift and uncertainty; actionable health checks passed. Phobos's final home
usage was 509 MiB and srv usage approximately 4.3 GiB; Deimos's home usage was 506 MiB.

After validation, explicit operator approval authorized deleting `/srv.pre-migration` and all
temporary migration archives, metadata copies, EFI images, and transport files on both hosts.
Absence checks passed while each new `/srv` remained mounted. No migration recovery copy remains.
A routine independent backup system is still future work.

## Future Changes

Inspect actual devices, mounts, usage, and current backups before planning any further resize.
The completed migration commands are not a reusable authorization or recovery procedure.
Local backup staging on the source NVMe does not protect against device loss.

Future NAS mounts use `/srv/media`, `/srv/backups`, and `/srv/surveillance`, with consumer mount
dependencies and tests that prevent writes under absent mounts. See
[ADR 0014](../adr/0014-host-storage-and-nas-mount-boundaries.md) and
[SPEC-2026-031](../specs/proposed/0031-nas-storage-adoption.md).
