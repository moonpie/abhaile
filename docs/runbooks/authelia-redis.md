# Authelia Redis upgrades and rollback

Redis stores Authelia sessions. User accounts and password hashes live in the file
backend; Authelia's durable storage lives in `/srv/authelia/authelia/data/db.sqlite3`.
Neither is part of Redis session recovery.

## Persistence and version compatibility

The Redis template disables AOF with `appendonly no` but retains default RDB
snapshotting. Redis writes its snapshot to `/srv/authelia/redis/data/dump.rdb`.
Do not interpret disabling AOF as disabling persistence.

The Redis 8.2.11 to 8.10.3 upgrade preserves existing snapshots and session expiry.
An isolated test with synthetic data verified authenticated commands, loading the
old snapshot, TTL preservation, and saving with the new version under a 256 MB
container memory limit. This does not replace live Authelia login validation.

Redis 8.10.3 writes RDB format 15; Redis 8.2.11 supports format 12 and rejects the
new snapshot. Reverting the image alone is therefore insufficient after a new
snapshot has been written. See the upstream format definitions for
[8.2.11](https://github.com/redis/redis/blob/8.2.11/src/rdb.h) and
[8.10.3](https://github.com/redis/redis/blob/8.10.3/src/rdb.h).

## Rollback policy

The operator-approved policy is to discard Redis sessions on downgrade. Everyone
must sign in again. Do not restore an older session snapshot: doing so could
restore a session that was logged out after that snapshot.

The reconciler does not delete session data automatically. Its attempt to restore
the previous image may fail if the previous Redis cannot load the current RDB.
This is an expected manual recovery boundary, not a database rollback guarantee.
Never edit runner recovery records to bypass that failure.

Before recovery, wait for the runner to finish and prevent its timer from starting
another run. Coordinate this work in an authenticated administrative session; SSO
will be unavailable while the pod is stopped.

1. Stop `abhaile-runner.timer` after confirming the runner service is idle.
1. Stop `authelia-app-pod.service` and confirm both Authelia and Redis containers
   have stopped. Redis must be stopped before removing the snapshot, because a
   graceful shutdown can write it again.
1. Remove only `/srv/authelia/redis/data/dump.rdb`, if present. Do not delete the
   directory, change its ownership, or touch either Authelia data directory.
   If AOF has been enabled or other persistence files are present, reassess this
   procedure before deleting anything else.
1. Restore the runner timer if it was active before maintenance, then restore the
   intended compatible Redis image through the repository and the
   documented runner reconciliation mechanism. Do not manually alter Quadlets or
   runner state. With no RDB, Redis starts with an empty session store.
1. Confirm Redis is healthy, inspect Authelia startup logs, and sign in to a
   protected application in a fresh private tab. Confirm logout and login work.
1. Confirm a clean reconciliation summary. The runner timer must be active during
   reconciliation because it is part of the actionable health checks.

The precise runner retry command depends on whether recovery failed or a corrected
commit is being deployed; use the runner's documented recovery procedure for that
state rather than removing failed-target suppression records. See the
[runner operations guide](operations.md#runner-status) for status and manual starts.
