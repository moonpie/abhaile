# Apply scripts exported environment variables

This document lists the environment variables that `tools/apply/*` scripts export or consume, and the expected contract for each.

**See `tools/paths.ini` for path configuration. See `tools/bash_lib/paths.sh` for how paths are loaded and exported as ABHAILE\_\* environment variables.**

## Core Variables

- `SCRIPT_DIR`: Directory containing the running script. Resolved by `tools/apply/lib/env.sh` but callers may pre-set to override resolution.
- `ROOT_DIR`: Repository root used by deploy scripts. Default derived from `SCRIPT_DIR`; callers may set to override.
- `REPO_DIR`: Path to install target (default `/opt/abhaile`). Used for packaging/install helpers.
- `PROD_RENDER_DIR`: Production location for rendered output (default `/var/lib/abhaile/rendered`).
- `PROD_STATE_DIR`: Production state directory (default `/var/lib/abhaile/state`).
- `PROD_NET_CONFIG_DIR`: Production systemd network directory (default `/etc/systemd/network`).
- `PROD_SOFTWARE_DIR`: Production software target directory (default `/var/lib/abhaile/software`).
- `DRY_RUN_DIR`: Optional caller-provided directory for dry-run outputs (defaults to `./out/` under the repo root).
- `RENDER_DIR`: Final render directory used for the current invocation (set by `env.sh` to either prod or dry-run locations).
- `STATE_DIR`: Final state directory used for the current invocation (set by `env.sh`).
- `NET_CONFIG_DIR`: Final systemd network directory to write to when applying (set to `PROD_NET_CONFIG_DIR` during `--apply`).
- `SOFTWARE_TARGET_DIR`: Directory where software artifacts are staged or installed.

Flags and other environment inputs:

- `TARGET_HOST`: Hostname to operate on (positional parameter or `--host`).
- `DRY_RUN`: Internal flag used by the script (0 for apply, 1 for dry-run).
- `VERBOSE`: If exported, enables more verbose logging.
- `SKIP_RENDER`: If exported, skip the render phase and reuse `RENDER_DIR`.
- `SKIP_DESEC_SYNC`: If exported, skip the deSEC DNS sync/drift check.

## System Configuration Paths (used by apply.sh)

- `SYSTEMD_NETWORK_DIR`: systemd-networkd config directory (default `/etc/systemd/network`)
- `SYSTEMD_SYSTEM_DIR`: systemd unit directory (default `/etc/systemd/system`)
- `SYSTEMD_RESOLVED_CONF`: systemd-resolved config file (default `/etc/systemd/resolved.conf`)
- `CONTAINER_SYSTEMD_DIR`: Podman quadlet directory (default `/etc/containers/systemd`)
- `BACKUP_DIR_BASE`: Base directory for backups (default `/var/lib/abhaile/backups`)
- `XDG_RUNTIME_DIR_TEMPLATE`: Template for user runtime dir (default `/run/user/%d` where %d is replaced with UID)

Notes & recommendations

- `env.sh` respects caller-provided `SCRIPT_DIR`/`ROOT_DIR` — prefer explicitly setting these in CI or wrappers rather than relying on computed defaults.
- Avoid `eval` of arbitrary Python output in production; the repo currently uses `eval "$(python3 tools/config.py)"` as a convenience. Consider adding a `--emit-env` flag to `tools/config.py` to print a safe, stable key=value list instead of arbitrary shell code.
- Scripts should treat `RENDER_DIR`/`STATE_DIR` as authoritative inputs; callers (CI or deploy runners) may export them to target custom locations.

If you want, I can also generate a small `tools/apply/ENV_VARS.example` shell snippet to source from CI wrappers.
