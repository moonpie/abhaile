# ADR 0002: Hash-based Drift Detection and State Model

## Status

2026-01-31: Accepted

## Context

Render produces desired-state artifacts, and apply must detect what has changed on the live system before making changes. We need an efficient, deterministic way to track and compare desired state without keeping old renders around.

Two approaches:

1. **File diffing**: diff old vs new rendered trees (requires keeping previous renders)
1. **Hash-based inventory**: manifest contains hashes of all desired files; apply compares manifest against live filesystem hashes

The production workflow on hosts is:

- git pull --> render --> analyze drift --> apply (if drift detected)

Since render overwrites `rendered/`, we can't rely on old renders for comparison.

## Decision

### Manifest Schema

Render produces `/var/lib/abhaile/state/manifest.json` containing an array of artifacts:

```json
{
  "rendered_at": "2026-01-31T12:34:56Z",
  "artifacts": [
    {
      "target_path": "/etc/systemd/network/lan.network",
      "rel_path": "etc/systemd/network/lan.network",
      "sha256": "abc123...",
      "size": 1024,
      "mode": "0644",
      "uid": 0,
      "gid": 0
    },
    ...
  ]
}
```

### Drift Detection Logic

1. **Read current manifest** from `/var/lib/abhaile/state/manifest.json`
1. **For each artifact in manifest:**
   - Calculate SHA256 of live file at `target_path`
   - Compare SHA256, size, mode, uid, gid
   - Report as changed, missing, or unchanged
1. **Detect orphaned files:** files on live system not in manifest (optional: report but don't auto-delete)
1. **Drift summary:** list all changes grouped by category (added, changed, removed, orphaned)

### Apply with Drift Detection

1. Render current state --> `/var/lib/abhaile/rendered/`
1. Generate manifest --> `/var/lib/abhaile/state/manifest.json`
1. Run drift detection
1. If drift exists and apply mode is enabled:
   - Sync changed/added files from `rendered/` to `/`
   - Set permissions and ownership
   - Update state file with new manifest
   - Restart impacted systemd units
1. If no drift: update state file only (commit tracking)

### Why Hash-based

- **Efficient**: single pass per file, no file diffing overhead
- **Deterministic**: same input --> same hash always
- **Safe**: old renders don't need to persist; manifest is the durable record
- **Atomic**: all file hashes in one manifest; easy to track what was last applied
- **Aligns with GitOps**: desired state in repo --> rendered artifacts --> manifest as inventory

## Alternatives Considered

### A. File diffing (old render vs new render)

Requires keeping previous renders around; storage overhead and complex cleanup.

### B. Checksum stored in rendered files (e.g., comments)

Couples metadata to content; harder to update manifests independently of renders.

### C. Tree diffing (e.g., rsync or git diff)

Still requires preserving old tree; less explicit about what changed.

## Consequences

- Render output is ephemeral; only manifest persists
- Drift detection is fast and requires no historical data
- State file becomes single source of truth for "what was last applied"
- Must handle file permissions and ownership explicitly in manifest
- Apply can fail atomically: if sync fails, manifest not updated

## References

- TODO.md: Foundations / Define environment paths
- ADR 0001: Output Root and Environment Paths
