# Abhaile Tools

This directory contains all automation scripts for the Abhaile infrastructure.

For a canonical map of generated artifacts and runtime paths, see [docs/REFERENCE.md](../docs/REFERENCE.md); this file focuses on tool layout and workflows.

## Organization

```text
tools/
├── common/           # Shared utilities (errors, YAML, CIDR helpers)
│   └── core/
├── apply/            # Deployment and apply logic
├── bootstrap/        # Host enrollment scripts
├── dns/              # DNS management
├── gitops/           # GitOps automation
├── inventory/        # Inventory generation (flat structure, no lib/)
├── render/           # Main configuration renderer (flat structure, no lib/)
│   ├── dns/          # DNS builders, deSEC integration
│   ├── host/         # Host-specific configs (user, software, resolved)
│   ├── network/      # Network builders and validation
│   ├── quadlet/      # Podman quadlet generators
│   └── services/     # Service builders (Caddy, Vault-Agent, etc.)
├── validate/         # Configuration validators
└── vault/            # Vault automation
```

### Key Principles

- **Flat module structure:** Python packages under render/, inventory/ have domain-specific modules (dns/, host/, etc.) at the top level—no `lib/` subdirectory (matches tools/inventory/ pattern).
- **Shared utilities:** tools/common/core/ contains canonical, reusable helpers (load_yaml, ValidationError, RenderError, strip_cidr). All tools/ modules import from tools.common.core directly.
- **Bash organization:** tools/apply/lib/ contains modular bash scripts sourced by apply.sh; this is not part of the Python flattening.

### Subdirectories by Purpose

- **[common/](common/)** - Shared utilities across all tools
  - `core/`: Canonical home for shared Python (YAML loading, errors, CIDR utilities)
- **[apply/](apply/)** - Deployment and apply logic
  - `apply.sh`: Main deployment script (render → validate → apply)
  - `lib/`: Shared bash libraries for apply logic
  - `README.md`: Deployment documentation
- **[bootstrap/](bootstrap/)** - Host enrollment scripts
  - `bootstrap.sh`: Minimal curl-bash installer for new hosts
  - `README.md`: Bootstrap script documentation
- **[dns/](dns/)** - DNS management
  - `cli.py`: Unified DNS management CLI for deSEC synchronization
  - `README.md`: DNS tools documentation
- **[gitops/](gitops/)** - GitOps automation
  - `gitops_runner.sh`: Timer-driven sync-render-apply loop
  - `*.env.example`: Configuration examples
  - `README.md`: GitOps runner documentation
- **[inventory/](inventory/)** - Inventory generation (flat structure)
  - `cli.py`: Automated documentation generator
  - `collectors.py`, `analyzers.py`, `formatters.py`: Domain modules
  - `README.md`: Inventory generation documentation
- **[render/](render/)** - Configuration renderer (flat structure)
  - `cli.py`: Primary entry point for configuration generation
  - `dns/`: DNS context builders, record generation, zone management, deSEC API
  - `host/`: Host-specific configs (user, software, resolved)
  - `network/`: Network config builders, validation, file mapping
  - `quadlet/`: Podman quadlet template rendering
  - `services/`: Service configs, Caddy/Vault-Agent template builders
  - `validate/`: Configuration validators (split modules)
  - `README.md`: Render documentation
- **[vault/](vault/)** - Vault automation
  - `vault_unseal.sh`: SOPS-backed Vault unseal
  - `vault_token_refresh.sh`: AppRole token minting
  - `*.env.example`: Configuration examples
  - `README.md`: Vault automation documentation

## Typical Workflows

**Render configurations locally:**

```bash
make install       # Setup venv and dependencies
make render        # Render all hosts (full context for Caddy, DNS, deSEC)
make generate-inventory  # Render + generate inventory
```

**Manual render:**

```bash
# Render all hosts (always processes all hosts from mapping.yaml)
python3 tools/render/cli.py

# Validate configuration without rendering
python3 tools/render/cli.py --validate-only
```

**Bootstrap New Host:**

```bash
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/tools/bootstrap/bootstrap.sh | \
  sudo bash -s -- <hostname>
```

**GitOps Operation:**

The `gitops_runner.sh` script runs every 5 minutes via systemd timer and performs:

1. Git pull
1. Render configs
1. Apply via `apply.sh`
1. Restart affected services

See individual README files in each subdirectory for detailed documentation.
