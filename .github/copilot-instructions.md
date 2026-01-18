# AI Coding Agent Instructions for Abhaile

These instructions help AI agents work productively in this repo by summarizing the architecture, workflows, and project-specific conventions.

## Big Picture

GitOps for 2-host homelab (`phobos`, `deimos`): render systemd-networkd + Podman quadlets from YAML, deploy with drift detection.

**Key concepts:**

- **Config:** `config/{mapping,network}.yaml` + per-service metadata define what runs where
- **Render:** `tools/render/cli.py` processes all hosts → `out/rendered/` (full context required for Caddy/DNS/deSEC)
- **Deploy:** `tools/apply/apply.sh` validates, drift-checks, stages, applies atomically
- **Secrets:** SOPS (bootstrap) → Vault (runtime)
- **Network:** ipvlan-l2 on Omada VLAN fabric; service /32s on VLAN 20, DMZ on VLAN 100

**When prompts conflict with `docs/`, prefer the docs.**

## Documentation Roadmap

Read these first when working on specific areas:

- **[README.md](../README.md)** - Architecture overview with system diagram
- **[docs/QUICKSTART.md](../docs/QUICKSTART.md)** - Bootstrap workflows and first deployment
- **[docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md)** - Rendering patterns, testing, validation
- **[docs/OPERATIONS.md](../docs/OPERATIONS.md)** - Deploy workflows, drift detection, DR procedures
- **[docs/NETWORK.md](../docs/NETWORK.md)** - VLANs, DNS, ACLs, VPN configuration
- **[docs/CREDENTIALS.md](../docs/CREDENTIALS.md)** - Secrets management (SOPS → Vault)

## Key Directories

- **`config/`** - Source of truth: `mapping.yaml`, `network.yaml`, per-service metadata
- **`config/_templates/`** - Shared Jinja2 templates (drop-ins, quadlets)
- **`config/hosts/<host>/`** - Host-specific network templates
- **`tools/render/`** - Python rendering orchestrator + domain builders
- **`tools/apply/`** - Bash deploy script + validation libraries
- **`out/rendered/`** - Generated configs (dev output)
- **`out/state/`** - Drift tracking state files
- **`docs/`** - Consolidated documentation suite

## Architecture Patterns

**Network modes:**

- `service-32`: Host-based /32 addresses → `service-addr.conf.j2` drop-ins
- `ipvlan-l2`: Container services → `service-route.conf.j2` + Podman network quadlets per VLAN

**Rendering:**

- Always processes **all hosts** from `mapping.yaml` (full context required for Caddy/DNS/deSEC)
- Jinja2 uses `StrictUndefined`; missing context keys fail fast
- Drop-in filenames use last octet for stable ordering: `NNN-<service>.conf`
- Dynamic builds: CoreDNS zones, Vault-Agent templates, Caddy ingress (planned)

**Key constraints:**

- IPv6 disabled; VLAN scheme `172.20.<VLAN>.0/24`
- Service /32s on VLAN 20, DMZ on VLAN 100
- Physical NIC `enp0s31f6`, ipvlan devices `ipvlan-l2[.<vlan>]`

See [ARCHITECTURE.md](../docs/ARCHITECTURE.md) and [NETWORK.md](../docs/NETWORK.md) for full details.

## Developer Workflows

**Quick commands:**

```bash
# Render all hosts (required for Caddy/DNS/deSEC context)
python3 tools/render/cli.py

# Validate only
python3 tools/render/cli.py --validate-only

# Dry-run deploy
./tools/apply/apply.sh phobos

# Apply changes (requires sudo)
sudo ./tools/apply/apply.sh --apply phobos

# Skip re-render if fresh (safety checks enforced)
./tools/apply/apply.sh --skip-render --apply phobos
```

**For detailed workflows:**

- Bootstrap: [QUICKSTART.md](../docs/QUICKSTART.md)
- Deploy/drift: [OPERATIONS.md](../docs/OPERATIONS.md)
- Rendering internals: [DEVELOPMENT.md](../docs/DEVELOPMENT.md)

## Key Conventions

- **Mapping-driven:** `config/mapping.yaml` is source of truth for service placement; render always processes all hosts
- **Fail fast:** Missing `service.yaml` or undefined Jinja2 variables are fatal errors
- **Skip-render safety:** `--skip-render` enforces config freshness checks before applying
- **File types:** `*.netdev` copied verbatim; `*.network.j2` and `*.conf.j2` rendered
- **Testing:** Use `SKIP_DESEC=1` for tests; mock external APIs (deSEC, Vault) unless testing live integration

## External Integrations

- **Podman:** Quadlets define container networks; systemd manages lifecycle
- **Vault:** Agent templates collected from services; SOPS-encrypted bootstrap secrets in `secrets/`
- **Omada:** Network fabric managed separately; see [NETWORK.md](../docs/NETWORK.md) for VLAN/ACL design
- **Monitoring:** Prometheus/Grafana/Loki services defined under `config/services/`

## Testing

**Structure:** `tests/{unit,integration,performance,e2e}/`

**Key patterns:**

- Unit: Mocked, fast (\<1s each), test domain logic
- Integration: End-to-end workflows with subprocess/file I/O
- Mock externals: `SKIP_DESEC=1` for deSEC, mock Vault unless testing live

**CI:** `.github/workflows/{ci,nightly}.yml`

See [DEVELOPMENT.md](../docs/DEVELOPMENT.md#testing) for philosophy, fixtures, and conventions.

## Template Structure

- Drop-ins: `config/_templates/hosts/{service-addr,service-route}.conf.j2`
- Host-specific: `config/hosts/<host>/systemd-networkd/*.{network.j2,netdev}`
- Quadlets: `config/_templates/services/quadlets/network.network.j2`
- Service configs: `config/services/<svc>/{service.yaml,templates/}`

## Contributing

1. Update config YAML or templates in `config/`
1. Render and verify: `python3 tools/render/cli.py`
1. Dry-run: `./tools/apply/apply.sh <host>`
1. Inspect `out/rendered/` and `out/state/`
1. Apply if correct: `sudo ./tools/apply/apply.sh --apply <host>`

**Extend builders in `tools/render/lib/` for new patterns; keep validations consistent.**
