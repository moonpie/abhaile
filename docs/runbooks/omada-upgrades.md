# Omada Controller and MongoDB upgrades

Upgrade MongoDB and the controller in separate commits and validate each on Phobos.
The MongoDB 8.0.26 to 8.0.34 patch update retains the existing controller version,
database paths, authentication configuration, and feature compatibility version.
Do not run a major-version database migration for this patch update.

Before deploying, check `uname -r` on Phobos against MongoDB's
[release notes](https://www.mongodb.com/docs/manual/release-notes/8.0/).
They identify Linux kernels 6.19 through 7.0.13 as incompatible. Containers share
the host kernel, so the image does not avoid that restriction.

## Pre-upgrade backup

First export a controller backup from the Omada UI and store it securely off-host.
Also take a cold filesystem backup of the complete service directory while both
controller and MongoDB are stopped. This preserves the corresponding application
files and database together, without introducing a backup service or new tooling.

The archive contains sensitive configuration, certificates, and database contents.
Keep it root-only, outside Git, and transfer an encrypted copy off-host. A local
archive protects against a failed upgrade, not failure of the source disk.
Allow space for the archive and a separate restore-validation copy.

Use a new backup directory for each upgrade; do not overwrite a previous backup.
The example below reserves `/root/abhaile-backups/omada-before-mongo-8.0.34` and
intentionally fails if that directory already exists.

Check the runner is idle and has no queued start before maintenance. Record whether
its timer was active, stop the timer, then recheck the runner service and jobs.
If a run is active, wait for it to finish; do not interrupt recovery.

```bash
sudo systemctl stop abhaile-runner.timer
```

```bash
systemctl is-active abhaile-runner.service
```

```bash
systemctl list-jobs --no-pager
```

Proceed only when the runner is inactive or failed and has no queued job. Record
which Omada environment and certificate watchers are active, then stop them so
Vault updates or certificate renewal cannot restart containers during the copy.

```bash
systemctl is-active omada-controller-env.path omada-mongodb-env.path rebuild-omada-cert.path
```

```bash
sudo systemctl stop omada-controller-env.path omada-mongodb-env.path rebuild-omada-cert.path
```

Wait for any in-flight `omada-controller-env.service`, `omada-mongodb-env.service`,
or `rebuild-omada-cert.service` work and their queued restart jobs to finish. Check
`systemctl list-jobs --no-pager` again. Stop the controller first, then the pod and
database. Confirm both containers are stopped;
do not archive live WiredTiger files or proceed after a forced/unclean shutdown.
DNS client discovery from Omada is temporarily unavailable during maintenance.

```bash
sudo systemctl stop omada-controller-app-omada-controller.service
```

```bash
sudo systemctl stop omada-controller-app-pod.service omada-controller-app-mongodb.service
```

```bash
sudo podman ps --filter name=systemd-omada-controller-app --format '{{.Names}} {{.Status}}'
```

Inspect service shutdown logs to confirm a clean MongoDB shutdown before copying.

```bash
sudo journalctl -u omada-controller-app-mongodb.service -n 30 --no-pager -o cat
```

```bash
sudo install -d -m 0700 /root/abhaile-backups
```

```bash
sudo mkdir -m 0700 /root/abhaile-backups/omada-before-mongo-8.0.34
```

```bash
sudo tar --acls --xattrs --numeric-owner -cpf /root/abhaile-backups/omada-before-mongo-8.0.34/service.tar -C /srv omada-controller
```

```bash
sudo tar -tf /root/abhaile-backups/omada-before-mongo-8.0.34/service.tar > /dev/null
```

Archive readability alone is not a restore test. Extract into a separate root-only
scratch directory and test a copy of the MongoDB data using the original image,
isolated from production networking and credentials. Never run a validation
container against the live data directory. The following commands use a copy
inside the root-only backup directory. They deliberately start MongoDB without
authentication in a separate network namespace with no published ports, solely
for checking the copy; this is not a production configuration.

```bash
sudo mkdir -m 0700 /root/abhaile-backups/omada-before-mongo-8.0.34/restore-check
```

```bash
sudo tar --acls --xattrs --numeric-owner -xpf /root/abhaile-backups/omada-before-mongo-8.0.34/service.tar -C /root/abhaile-backups/omada-before-mongo-8.0.34/restore-check
```

```bash
sudo podman run --detach --pull=never --name abhaile-omada-backup-check --network=none --memory=2g --user=999:999 --volume /root/abhaile-backups/omada-before-mongo-8.0.34/restore-check/omada-controller/mongodb/data:/data/db --entrypoint mongod docker.io/library/mongo:8.0.26 --dbpath /data/db --bind_ip 127.0.0.1 --noauth --wiredTigerCacheSizeGB 0.25
```

Wait for startup, then require a successful ping and at least one application
database. This checks opening the copied database, not every application record.
If startup fails, inspect only the validation container's logs and stop here.

```bash
sudo podman exec abhaile-omada-backup-check mongosh --quiet --eval 'if (db.adminCommand({ping:1}).ok !== 1 || db.adminCommand({listDatabases:1,nameOnly:true}).databases.filter(d => !["admin","config","local"].includes(d.name)).length === 0) quit(1); print("Backup database opened successfully")'
```

```bash
sudo podman stop --time 60 abhaile-omada-backup-check
```

```bash
sudo podman rm --volumes abhaile-omada-backup-check
```

Keep the original archive unchanged. The scratch copy has been opened by MongoDB
and is no longer the untouched backup. Stop at any failed command; do not proceed
to deployment on a failed backup or restore check.

Restart MongoDB and the controller after the backup. The pod dependency starts the
pod when these units start. Confirm health and controller access, then restore the
timer if it was previously active. The timer must be active during reconciliation
because it is included in the runner's health checks.

```bash
sudo systemctl start omada-controller-app-mongodb.service omada-controller-app-omada-controller.service
```

Restore only the watchers that were previously active, after checking service
health. For the normal configuration where all three were active:

```bash
sudo systemctl start omada-controller-env.path omada-mongodb-env.path rebuild-omada-cert.path
```

```bash
sudo systemctl start abhaile-runner.timer
```

Do not push the upgrade until backup and restore validation have succeeded.

## Rollback

The runner restores repository-declared files and images; it does not restore
MongoDB or Omada application data. A successful image rollback does not by itself
prove that application state was restored.

If data restoration is required, stop the timer, wait for an idle runner, stop the
watchers and drain their jobs, and stop both service containers as above. Preserve
the failed service directory separately
for diagnosis. Restore the complete matching cold backup at its original path,
preserving numeric ownership, modes, ACLs, and extended attributes. Start it with
the corresponding old image/configuration through a reviewed GitOps recovery.
Do not overlay a backup onto existing database files, delete database files to
force startup, or edit runner recovery records. Restore only after reviewing the
specific failure and target backup; changes since the backup will be lost.

## Validation after deployment

Confirm the runner summary is clean and the MongoDB container runs the intended
image and is healthy. Inspect startup logs for storage, authentication, or
compatibility errors. Sign in to Omada, confirm managed devices remain connected,
and check a known dynamic client DNS record through both CoreDNS servers.
Take a new backup before any subsequent controller upgrade.
