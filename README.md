# Abhaile

Abhaile is a GitOps-managed home lab for two Debian hosts (`phobos`, `deimos`): network configuration, host services, and containerized apps. The repo renders systemd-networkd configs, Podman quadlets, DNS zones, and Vault templates, then applies them via automated systemd timers.

## Architecture Overview

Abhaile implements **declarative infrastructure as code** for a home lab with:

- **Two Debian hosts** (`phobos`, `deimos`) running systemd + Podman
- **GitOps automation** via systemd timers (unprivileged render phase, privileged apply phase)
- **Deterministic networking** with per-service `/32` addresses via ipvlan-l2
- **Split-horizon DNS** (filtered and clean CoreDNS instances)
- **Secrets management** via SOPS (bootstrap) and Vault (runtime)
- **Omada network fabric** with VLAN segmentation and default-deny ACLs

### How It Works

```mermaid
graph TD
    A[config/ YAML<br/>Source of Truth] --> B[cli.py<br/>Generate Configs]
    B --> C[out/rendered/<br/>Host Configs]
    B --> D[out/state/<br/>Drift Tracking]
    C --> E[apply.sh<br/>Validate + Deploy]
    E --> F[/etc/systemd/network/<br/>Live Host State]
    E --> G[Reload Services<br/>systemd-networkd, Podman]

    H[GitOps Timer<br/>Every 5 minutes] --> B
    B --> I[.apply_ready flag]
    I --> J[GitOps Apply Path<br/>Privileged]
    J --> E
```

**Key principles:**

1. **Mapping-driven:** `config/mapping.yaml` determines which services run on which hosts
1. **Always renders all hosts:** Full context needed for Caddy ingress, DNS zones, deSEC plans
1. **Atomic deployment:** Validate → stage → backup → apply → verify
1. **Drift detection:** SHA256 state tracking across 6 config categories
1. **Privilege boundary:** Unprivileged render (abhaile user) + privileged apply (root)

## Quick Start

**Bring up a new host:**

```bash
# Automated enrollment (requires Age key and deploy key)
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/tools/bootstrap/bootstrap.sh | \
  sudo bash -s -- <host>
```

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for detailed walkthrough.

**Render configurations locally:**

```bash
make install       # Setup venv and dependencies
make render        # Render all hosts
make generate-inventory  # Render + generate inventory
```

**Run tests and validation:**

```bash
make test          # Run pytest suite
make lint          # Run pre-commit hooks
```

## Documentation

Start here:

- **[docs/QUICKSTART.md](docs/QUICKSTART.md)** – Get started in 3 steps (install, render, apply)
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** – System design, ADR index, technical decisions
- **[docs/NETWORK.md](docs/NETWORK.md)** – VLANs, ACLs, DNS, VPN, topology
- **[docs/OPERATIONS.md](docs/OPERATIONS.md)** – Deployment, drift management, backups, security
- **[docs/CREDENTIALS.md](docs/CREDENTIALS.md)** – Secrets management (SOPS + Vault)
- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** – Rendering logic, testing, path resolution
- **[docs/REFERENCE.md](docs/REFERENCE.md)** – Generated artifacts, script index, paths

Source of truth lives in `config/`; render/apply pipeline in `tools/`.

See [docs/README.md](docs/README.md) for complete documentation index.

## Project Structure

```text
abhaile/
├── config/                    # Source of truth
│   ├── mapping.yaml          # Host-to-service assignments
│   ├── network.yaml          # VLANs, hosts, service addressing
│   └── services/<svc>/       # Per-service config + templates
├── docs/                      # Authoritative documentation
│   ├── QUICKSTART.md         # Get started guide
│   ├── ARCHITECTURE.md       # System design + ADR index
│   ├── NETWORK.md            # Complete network reference
│   ├── OPERATIONS.md         # Day-to-day operations
│   └── ADR/                  # Architecture decision records
├── tools/                     # Automation scripts
│   ├── render/               # Configuration renderer
│   ├── apply/                # Deployment orchestrator
│   ├── bootstrap/            # Host enrollment
│   └── inventory/            # Documentation generator
├── out/                       # Generated artifacts (dev)
│   ├── rendered/             # Host configs
│   └── state/                # Drift tracking
└── tests/                     # Unit + integration tests
```

## Common Tasks

**Update service configuration:**

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
make render
sudo ./tools/apply/apply.sh --apply phobos
```

**Check for drift:**

```bash
./tools/apply/apply.sh phobos
```

**Generate inventory:**

```bash
make generate-inventory
cat INVENTORY.md
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines, commit conventions, and development standards.
