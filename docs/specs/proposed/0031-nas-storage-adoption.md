# Spec: NAS Storage Adoption

## Metadata

```yaml
id: SPEC-2026-031
title: NAS Storage Adoption
status: proposed
owner: moonpie
created: 2026-10-26
updated: 2026-10-26
related_adrs:
  - 0014-host-storage-and-nas-mount-boundaries
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [media, backups, surveillance]
```

## Context

The hosts have completed the local storage migration under SPEC-2026-030. No NAS is deployed.
The operator approved tracking NAS adoption separately on 2026-10-26. ADR 0014 defines the
durable storage boundaries; this spec tracks their future NAS implementation.

## Requirements

- Provide separate mounts at `/srv/media`, `/srv/backups`, and `/srv/surveillance` on consuming hosts.
- Keep application configuration and databases on local `/srv/<service>/` storage.
- Preserve media hardlinks and service backup namespaces during migration.
- Prevent writes beneath absent expected NAS mounts and isolate backup write authority.

## Constraints

Select and review the NAS, protocol, credentials, capacity, and policies before activation.
Local staging on the source NVMe is not independent backup protection. Surveillance recordings
remain separate from ordinary service backups. No NAS mount is required before the NAS exists.

## Design

Use three exports/filesystems with distinct access, quota, snapshot, retention, and replication
policies. Preserve `/srv/backups/<service>/`; do not create per-service mounts by default.
Keep downloads and managed libraries on one filesystem where hardlinks are required. Transcode
workspace may remain local. NVR configuration/database state remains in its service directory.

Author deterministic mounts through `config/` and render/apply. Stop writers, copy and validate
existing data and metadata, then activate mounts. Order consumers after mounts and verify mount
identity before writes. Test ordinary boot, NAS absence, reconnect, and recovery. Backup jobs and
recording writers fail without their required mount; any degraded read-only media mode requires
an explicit service policy.

Restrict backup identities using exports, ACLs, credentials, or repository authorization. Select
repository encryption where supported and define off-host protection in the backup policy.

## Acceptance Criteria

- [ ] NAS protocol, exports, ownership, capacity, and mount options are reviewed and recorded.
- [ ] Declarative mounts expose all three approved paths on consuming hosts.
- [ ] Migrated contents, numeric ownership, permissions, ACLs, xattrs, and links validate.
- [ ] Media workflows demonstrate hardlinks where required.
- [ ] Boot, NAS absence, reconnect, and recovery tests prove writers fail closed.
- [ ] Backup identities cannot modify unrelated service backup sets.
- [ ] Surveillance capacity and retention policy is agreed and tested before recording starts.
- [ ] Backup encryption, retention, replication, and restore requirements are agreed and tested.

### Evidence

Record implementation commit/PR and validation evidence per criterion when activated.

## Out of Scope

Repeating the local LVM migration. Service deployment and local path adoption remain in the
home-automation, media, and network-device specs, including Omada backup automation.

## Open Questions

1. Which NAS, protocol, mount options, and outage/recovery policy will be used?
1. Which backup tool, schedule, encryption, retention, and off-site target will be selected?
1. What surveillance capacity and retention policy will be enforced?

## References

- [ADR 0014](../../adr/0014-host-storage-and-nas-mount-boundaries.md)
- [Local storage](../accepted/0030-host-storage-layout.md)
- [Home automation](0015-services-home-automation.md)
- [Media services](0017-services-media.md)
- [Network devices](0021-network-devices.md)
