# Development

Internal patterns, rendering logic, testing conventions, path resolution for contributors.

## At a glance

- Render everything: `python3 tools/render/cli.py`
- Validate only: `python3 tools/render/cli.py --validate-only`
- Tests: `make test` (unit/integration); lint via pre-commit
- Placeholder resolver: `tools/common/core/placeholder.py` (fail-fast)
- Outputs: `out/rendered/`, state in `out/state/`
- Jinja2 StrictUndefined; mapping/network drive all hosts always

## Rendering Architecture

### Builder/Orchestrator Pattern

**Builders are pure functions:**

- Return data structures (paths + content, plans, metadata)
- No disk I/O
- Examples: `networkd_builder.py`, `desec_plan.py`, service builders

**Orchestrator owns side effects:**

- `tools/render/cli.py` writes to `out/rendered/`
- Writes state files (`desec_plan.json`, `dns_serial.state`)
- Logs drift and validation errors

**When adding builders:** Keep them pure, extend orchestrator for I/O.

### Mapping-Driven Rendering

- Only services in `config/mapping.yaml` are rendered for each host
- Renderer always processes **all hosts** (full context for Caddy, DNS, deSEC)
- Network mode and VLAN determined by `mapping.yaml` + `network.yaml`

### Template System

**Jinja2 with StrictUndefined:**

- All templates fail fast on missing variables
- Variables use `%%path.to.value%%` syntax with optional filters
- Example: `%%network.services.vault.address|strip_cidr%%`
- Mixed patterns supported: `%%foo.bar%%:8053`

**Key builders:**

- **Caddy:** Merges base config + ingress blocks from all services
- **DNS:** Sorts zones, manages serials, filters by provider; skips host-only services (not in network.yaml) when building deSEC context
- **Quadlet:** Generates `.container`, `.network`, `.volume` units
- **Vault-Agent:** Merges template blocks from includes

### Volume and Quadlet Rules

- Named volumes always use `.volume` suffix (Podman requirement)
- Shared volumes: `_shared/home/` (rootless), `_shared/etc/` (rootful)
- Volume modes: `:rw` (default) or `:ro` per `service.yaml`
- Deduplication happens at build time, orchestrator writes once

## Validation Strategy

Multi-layer validation strategy with clear responsibility boundaries:

**Layer 1 (Pre-commit): Syntax & Schema** — fail fast

- YAML structure and types
- Jinja2 syntax in templates
- Python code style (Black, Ruff)
- Secrets scanning (gitleaks)

**Layer 2 (Render): Semantic Validation** — fail on critical errors, warn on recoverable issues

- Mapping consistency: services in mapping.yaml must have service.yaml
- Network uniqueness: VLAN IPs must not conflict
- Host configuration: containers needing ipvlan must have compatible host interface
- Placeholder resolution: all `%%...%%` variables must resolve
- Warnings: unmapped hosts (allowed for dormant deployments), host-only services in deSEC planning

**Layer 3 (Apply): Live System Validation** — fail before modifying system

- systemd-analyze validates networkd configs
- Drift detection flags unexpected local changes
- Backups created before any modifications
- Atomic operations ensure rollback on failure
- Apply is serialized with flock to protect state updates (timer + manual apply cannot overlap; 30s timeout)
- systemctl reload/enable/start failures are fatal (no `|| true`); failures trigger rollback
- Rollback verifies the previous commit exists before checkout

Each layer assumes previous layers succeeded. Fail vs. warn boundaries are tested and documented.

### Critical Errors (Exit 1)

Block render, require immediate config fixes:

- `ServiceNotFoundError`: Service listed in mapping.yaml but no `config/services/<svc>/service.yaml`
- `VLANNotFound`: Service references undefined VLAN in network.yaml
- `HostConfigError`: Container service requires ipvlan interface that host doesn't have
- `PlaceholderResolutionError`: Cannot resolve `%%...%%` variable in templates or service configs
- `DuplicateNetworkError`: Two services assigned same IP address

### Warnings (Exit 0)

Allow render to complete; noted in output but non-blocking:

- Unmapped host: listed in network.yaml but not assigned services (intentional for dormant deployments)
- Unrecognized service type: typed incorrectly in service.yaml (will be fixed later)
- deSEC planning skips host-only services: services without network.yaml entry are excluded from DNS planning (expected; avoids false negatives)

**Design rationale:** Legitimate scenarios like dormant hosts and future placeholders shouldn't block rendering. Critical structural errors are caught early to prevent applying invalid configs.

## Path Resolution

All paths are centrally defined in `tools/paths.ini`. Tools detect the repo root via `.git/` and compute paths dynamically (no `.env` parsing in Python; Bash-only).

### Development Paths

```text
/path/to/repo/
├── config/              # Source of truth
├── tools/render/        # Rendering logic
├── out/
│   ├── rendered/        # Generated configs (default output)
│   ├── state/           # Drift tracking hashes
│   └── inventory/       # Built artifacts (JSON/YAML/CSV)
```

Run: `python3 tools/render/cli.py` → outputs to `out/rendered/` and `out/state/`

### Production Paths

```text
/opt/abhaile/                           # Git repo clone (owned by abhaile:abhaile)

/var/lib/abhaile/
├── rendered/                           # Generated configs (immutable output)
├── state/                              # Drift tracking & state hashes (mutable)
├── software/                           # Software artifacts
└── backups/                            # Timestamped backups (networkd, services, etc.)

/etc/abhaile/
├── gitops/.env                         # GitOps runner environment (SOPS-decrypted)
└── <service>/                          # Per-service secrets (SOPS-decrypted)

/etc/systemd/network/                   # systemd-networkd configs (applied by root)
/etc/systemd/system/                    # Systemd units (applied by root)
/etc/containers/systemd/                # Rootful quadlets (applied by root)
/home/<user>/.config/containers/systemd # Rootless quadlets (applied by user systemd)

/home/abhaile/.ssh/gitops_ed25519       # GitOps deploy SSH key (mode 0600)
/home/abhaile/.config/sops/age/keys.txt # Age private key for SOPS (mode 0600)
```

Run (production): `python3 tools/render/cli.py --output-dir /var/lib/abhaile/rendered`

**Privilege boundary:** Unprivileged `abhaile` user renders to `/var/lib/abhaile/rendered` and updates state in `/var/lib/abhaile/state`. Privileged `root` user applies configs from rendered output.

## Placeholder Resolution

Abhaile uses a single canonical resolver to handle `%%...%%` placeholders consistently across builders.

- Location: `tools/common/core/placeholder.py`
- Behavior: Fail-fast on missing keys, with detection for nested and circular references
- Supported filters: `strip_cidr` (e.g., `%%network.services.vault.address|strip_cidr%%`)
- Mixed strings: Placeholders can be embedded within strings (e.g., `https://%%services.caddy.address%%:2019`)
- Undefined filters: Raise a `ValidationError` to ensure explicit handling

Usage guidelines:

- Builders must call `resolve_placeholders()` for any templated values in service configs, DNS, and inventory generation.
- Jinja2 still uses `StrictUndefined`; placeholder resolution occurs before template rendering to guarantee complete context.

Design notes:

- DNS deSEC context builder tolerates host-only services (e.g., `ddclient`) by skipping them when no `network.yaml` entry exists. This avoids false negatives in public DNS planning while keeping render strict elsewhere.

## Container Architecture

### Rootless vs Rootful Container Policy

Services use a hybrid approach to balance security and functionality requirements:

**Rootful containers** (`/etc/containers/systemd/*.container`):

- Required for services needing `ipvlan-l2` container networking
- Required for services needing privileged ports (< 1024)
- Required for services with host filesystem mounts (`/etc/`, `/var/lib/`, etc.)
- Examples: CoreDNS (port 53), Caddy (port 443), qBittorrent (ipvlan), Vault (port 8200)
- All core infrastructure services run rootful

**Rootless containers** (`~/.config/containers/systemd/*.container`):

- Reserved for helper agents (Vault Agent, config fetchers)
- Used for low-risk, low-privilege tools
- Run under service-specific user systemd
- Improve security posture where networking/host access not required

**Trade-off:** Dual-mode management increases operational complexity but improves security for services that don't require root. Critical services (DNS, ingress, secrets) remain rootful for functionality; helper tasks are rootless for isolation.

Management is configured in `config/services/<svc>/service.yaml` via `container_mode` setting and Podman quadlet type (rootful vs rootless systemd socket).

## Testing

### Directory Structure

```text
tests/
├── unit/                 # Pure unit tests (mocked, fast)
│   ├── common/           # Core utilities
│   ├── render/           # Rendering logic
│   ├── inventory/        # Inventory generation
│   └── validate/         # Config validation
├── integration/          # End-to-end workflows (render, apply, dns cli)
└── performance/          # Performance/latency checks (render time)
```

### Unit Test Rules

✅ **Do:**

- Use `tmp_path` for temporary files
- Mock external dependencies with `monkeypatch`
- Test logic, not I/O
- Run fast (\<1 second each)

❌ **Don't:**

- Use `subprocess.run()` or spawn processes
- Depend on external services
- Write to repo directories

### Key Test Areas

**Rendering logic:**

- Mapping-driven service rendering
- Network mode validation (service-32, ipvlan-l2)
- Template substitution with filters
- Quadlet/volume generation
- Caddy ingress merging
- DNS zone building and serial management

**Inventory generation:**

- Data collection from rendered output
- Service classification
- Network assignment analysis
- Dependency graph generation

**Configuration validation:**

- Schema compliance (mapping, network, service)
- Semantic validation (VLAN references, host interfaces)
- Template syntax checking

### Running Tests

```bash
# All tests
make test

# Unit tests only
.venv/bin/pytest tests/unit/

# Specific test file
.venv/bin/pytest tests/unit/render/test_dns_builder.py -v

# With coverage
.venv/bin/pytest --cov=tools tests/

# E2E smoke (optional; skipped by default)
E2E_SMOKE=1 .venv/bin/pytest tests/e2e/ -q

# Live deSEC integration tests (optional; requires token)
# Prefer running only in controlled environments (e.g., nightly CI)
DESEC_TOKEN=your_token .venv/bin/pytest tests/integration/test_dns_cli.py -q
```

## Tool Organization

### Flat Module Structure

Python packages use domain-specific modules at top level (no `lib/` subdirs):

```text
tools/
├── common/core/       # Shared utilities
├── render/
│   ├── dns/          # DNS builders
│   ├── host/         # Host configs
│   ├── network/      # Network builders
│   ├── quadlet/      # Podman quadlet generators
│   └── services/     # Service builders
├── inventory/         # Flat structure
└── validate/          # Flat structure
```

**Rationale:** Simpler imports, clearer ownership, matches `tools/apply/lib/` bash pattern.

### Shared Utilities (tools/common/core/)

Canonical utilities used across all tools:

- `load_yaml()`: YAML loading with validation
- `ValidationError`, `RenderError`: Error types
- `strip_cidr()`, `get_last_octet()`: Network helpers

**Import pattern:** `from tools.common.core import load_yaml, ValidationError`

## Code Style

**Python:**

- Black formatter (line length 100)
- Ruff linter
- Type hints preferred for public APIs
- Docstrings for modules and public functions

**Bash:**

- Shellcheck clean
- Functions prefixed with namespace (`apply_`, `validate_`)
- Sourced libraries in `tools/apply/lib/`

**Markdown:**

- mdformat for formatting
- PyMarkdown for linting
- MD013 (line length) disabled for tables/diagrams
- Prefer ~120 char paragraphs for readability

## CI Secrets (Optional)

To enable optional jobs in GitHub Actions Nightly:

- `E2E_SMOKE=1`: Runs E2E smoke tests (render + apply dry-run, no external DNS)
- `DESEC_LIVE=1` and `DESEC_TOKEN`: Runs live deSEC integration tests (tools/dns/cli.py); use carefully

## Pre-Commit Hooks

```bash
# Install hooks
pre-commit install

# Run all hooks
pre-commit run --all-files

# Run specific hook
pre-commit run validate-schemas --all-files
```

Hooks enforce:

- YAML/JSON validation
- Jinja2 syntax checking
- Python formatting (Black, Ruff)
- Bash linting (shellcheck)
- Secret scanning (gitleaks)
- Markdown formatting

## Design Decisions (Development)

**Unmapped/empty hosts:** Render proceeds without error; allows dormant hosts.

**Services without network config:** Valid; renders without drop-ins/quadlets.

**deSEC drift checks:** Non-fatal in dev; external API failures shouldn't block.

**State file format:**

- Simple format: `<sha256>  <path>` (network, systemd, resolved, software, users)
- Services format: `<sha256>  <render_path>  <target_path>` (handles rootful/rootless)

## See Also

- [QUICKSTART.md](QUICKSTART.md) – Get started quickly
- [OPERATIONS.md](OPERATIONS.md) – Deployment workflows
- [MAINTENANCE.md](MAINTENANCE.md) – Routine maintenance and troubleshooting
- [NETWORK.md](NETWORK.md) – Network topology and ACLs
