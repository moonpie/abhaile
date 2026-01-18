# Quick Start

Three steps to get started: install dependencies, render configurations, apply to a host.

## Prerequisites

- Debian host with systemd-networkd and Podman installed
- Age key for SOPS decryption
- Git deploy key for repo access
- Host present in `config/mapping.yaml` and `config/network.yaml`
- SOPS decryption check passes: `sops -d secrets/gitops-<host>.sops.env | head -n1`

**Automated bootstrap:** See [tools/bootstrap/README.md](../tools/bootstrap/README.md) for one-command enrollment.

**Bootstrap validation:** The bootstrap script validates host presence in mapping/network, required keys (Age + Git deploy), and fails fast before declaring success.

## Workflow

### 1. Install

```bash
git clone git@github.com:moonpie/abhaile.git /opt/abhaile
cd /opt/abhaile
make install       # Creates venv and installs requirements
```

### 2. Render

Processes all hosts from `config/mapping.yaml` and generates configs to `out/rendered/`:

```bash
make render        # Or: python3 tools/render/cli.py
```

**Output:** `out/rendered/<host>/systemd-networkd/`, `out/rendered/<host>/services/`, `out/state/`

### 3. Apply

```bash
./tools/apply/apply.sh phobos              # Dry-run (shows drift)
sudo ./tools/apply/apply.sh --apply phobos # Apply changes
```

**Apply workflow:** Validates → detects drift → stages atomically → reloads services → updates state.

### 4. Verify

```bash
ip addr show                                     # Check network interfaces
podman ps                                        # Verify containers
sudo systemctl status abhaile-gitops@phobos.service
```

## Common Tasks

**Update service config:**

```bash
vim config/services/caddy-internal/service.yaml
make render
sudo ./tools/apply/apply.sh --apply phobos
```

**Add new service:**

```bash
mkdir -p config/services/myservice
vim config/services/myservice/service.yaml
vim config/mapping.yaml    # Add to host
vim config/network.yaml    # Add address/VLAN if needed
make render && sudo ./tools/apply/apply.sh --apply phobos
```

## Troubleshooting

See [OPERATIONS.md](OPERATIONS.md#troubleshooting) for common issues. Quick checks:

- **Render fails:** Missing `service.yaml` or undefined VLAN → update `config/`
- **Apply drift warnings:** Review changes, decide to accept or update templates
- **GitOps sync fails:** Check deploy key and Age key permissions

## Next Steps

- [NETWORK.md](NETWORK.md) – VLANs, ACLs, topology
- [OPERATIONS.md](OPERATIONS.md) – Deployment workflows, drift, DR
- [README.md](../README.md) – Full documentation index
