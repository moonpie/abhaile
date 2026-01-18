# TODO: Service Generation & Deployment

## Phase 1: Core Service Generation

### Orchestration & Rendering Infrastructure

- [x] **Service Config Rendering**
  - [x] Static file copy via `config[].source: "<path>"`
  - [x] Jinja2 template rendering via `config[].source.template` + `variables`
  - [x] Placeholder resolution `%%path.to.value%%` from service context
  - [x] Template loader rooted at `config/services/`
  - [x] Output to `<out>/<host>/services/<service>/<destination>`

### Vault & Vault-Agent (Foundation)

- [x] **Vault**
  - [x] Quadlets (.container, .volume, .image)
  - [x] Config file generation (static copy + template rendering via service.yaml)
  - [x] EnvironmentFile support (`/srv/vault/vault.env`)
  - [x] Host directory creation for volumes (`/srv/vault/config`, `/srv/vault/data`)
  - [x] Vault unseal mechanism
    - [x] `abhaile-vault-unseal.service` systemd unit (Type=oneshot, After=vault.service)
    - [x] `tools/vault/vault_unseal.sh` script with SOPS decryption
    - [x] SOPS key location: `/root/.config/sops/age/keys.txt` (via `SOPS_AGE_KEY_FILE`)
    - [x] Encrypted unseal keys: `secrets/vault-unseal.sops.yaml`
    - [x] Unit installation to `/etc/systemd/system/` in apply pipeline (apply_static_systemd_units)
  - [x] Design: Vault storage backend configuration (Raft at `/srv/vault/data`)
- [x] **Vault-Agent**
  - [x] Quadlets for rootless mode
    - [x] Rootless container support in quadlet_builder.py
    - [x] `rootless_user` metadata at service root level
    - [x] Shared volume isolation (separate .volume units per rootless/rootful context)
    - [x] Apply pipeline rootless support (copy to `/home/<user>/.config/containers/systemd/`, chown, lingering, systemctl --user)
  - [x] Sentinel file generation: `/srv/vault/agent/out/.ready` after successful template rendering
  - [x] `abhaile-secrets-ready.path` + `.service` watching sentinel for downstream dependencies
  - [x] Template collection from other services
    - [x] `vault_agent.templates` in service.yaml for declaring templates
    - [x] Automatic collection from included services (via `include:` mechanism)
    - [x] Flat template directory structure in `/srv/vault/agent/templates/`
    - [x] Dynamic config.hcl rendering per-host based on deployed services
  - [x] Design decision: Credential access pattern
    - **Decided**: Direct reference to `/srv/<service>/config/` for env files and configs
    - EnvironmentFile convention: `/srv/<service>/config/<service>.env`
    - Vault-Agent writes atomically to `/srv/<service>/config/`
    - No mounts needed for env files (systemd reads on host)
  - [x] Systemd dependency model finalized:
    - **`vault.service`**: Vault container running
    - **`abhaile-vault-unseal.service`**: Vault unsealed and API responsive (consumers needing Vault API)
    - **`abhaile-secrets-ready.service`**: Vault-agent rendered secrets available (consumers needing rendered templates/secrets)
    - **Decision**: Removed `vault-ready.service` as redundant; consumers use `abhaile-vault-unseal` or `abhaile-secrets-ready` based on needs

### DNS Infrastructure

- [x] **CoreDNS**
  - [x] Build with Omada plugin
    - [x] Containerfile for building CoreDNS with omada plugin
    - [x] Build quadlet (coredns-omada.build)
    - [x] Install service to copy binary to /usr/local/bin
    - [x] Service inclusion mechanism (coredns-clean/filtered include coredns-omada)
  - [x] Vault-agent template integration for Omada credentials
    - [x] Template defined in coredns-omada/service.yaml
    - [x] Collected via include mechanism
  - [x] Config file (Corefile) generation
    - [x] Templated via coredns-common/config/Corefile.j2
    - [x] Per-service variables (bind_ip, forward_to, omada_ip, dmz_caddy_ip)
  - [x] Zone file generation (use existing `dns_builder.py` logic)
    - [x] Templates in coredns-common/config/zones/\*.j2
    - [x] Dynamic zone rendering per host
  - [x] Design: Zone update mechanism
    - **Implementation**: systemd path unit watching `/etc/coredns/zones/`
    - **Trigger**: `coredns-zones.path` monitors zone directory for changes
    - **Action**: `coredns-zones.service` sends SIGUSR1 to CoreDNS for graceful reload
    - **Serial Management**: `dns_builder.generate_serial()` auto-increments YYYYMMDDXX format
    - **Deployment**: Zone files rendered by orchestrator → systemd path triggers reload
    - **Units**: Deployed via `coredns-common` service included by coredns-filtered/clean

### Ingress Layer

- [x] **Caddy-Internal**
  - [x] Caddyfile generation from mapping.yaml + service.yaml
  - [x] Design: Automatic reverse proxy blocks vs explicit config
  - [x] Design: TLS - internal CA vs explicit cert paths
  - [x] Integration with service metadata (ports, labels)
- [x] **Caddy-DMZ**
  - [x] Caddyfile generation from mapping.yaml + service.yaml
  - [x] Build with desec plugin
    - [x] Containerfile in caddy-dmz/build/
    - [x] Build quadlet (caddy-dmz.build)
  - [x] Vault-agent template integration for desec.io credentials
    - [x] Template defined in caddy-dmz/service.yaml (caddy-dns-desec.env.ctmpl)
    - [x] Systemd path/service units for env file readiness
  - [x] Design: ACME configuration (DNS-01 via deSEC)
  - [x] Design: Public DNS (DNS via deSEC API)
- [x] **Blocky**
  - [x] Quadlets (.container, .image)
  - [x] Config file mounted from host (`/srv/blocky/config.yml`)
  - [x] Host directory creation for mounted config files
  - [x] Config file generation/templating (static config with OISD blocklist)
  - [x] Integration with DNS infrastructure (upstream for CoreDNS filtered)
- [x] **ddclient**
  - [x] ddclient.conf generation (via Vault-Agent template)
  - [x] Vault-agent template for desec.io credentials
  - [x] Design: Update mechanism and scheduling (systemd path/service, 60s daemon)

### Auth & Supporting Services

- [x] **Authelia**
  - [x] Pod quadlets (multi-container)
    - [x] Pod detection and rendering in quadlet_builder.py
    - [x] Pod naming convention: `<service>-app.pod`
    - [x] Container units: `<service>-app-<container>.container`
    - [x] Volume units: `<service>-app-<container>-<volume>.volume`
    - [x] Shared volumes rendered to `_shared/` directory
    - [x] Per-container volume lines, dependencies, health checks
  - [x] Config file generation (configuration.yml, redis.conf via Vault-Agent)
    - [x] authelia.configuration.yml.ctmpl with session, storage, JWT secrets
    - [x] authelia-redis.conf.ctmpl with password from Vault
    - [x] Systemd path/service units watching vault-agent output
    - [x] Automatic copy to volume-backed directories and container restart
  - [x] Vault-agent template for secrets (OIDC, session, storage)
    - [x] Templates collected from authelia/templates/ by vault_template_builder
    - [x] Rendered to vault-agent config.hcl template blocks
  - [x] Caddy integration
    - [x] Internal ingress block for authelia.abhaile.home.arpa
    - [x] Forward auth snippet for protecting other services
  - [x] Design: Session storage (Redis in pod)
- [x] **Omada-Controller**
  - [x] Quadlets (.container, .volume, .image)
    - [x] Container with network, static IP, ulimits
    - [x] Named volumes for cert, data, logs
    - [x] Shared host-certs volume
  - [x] Cert-bundle generation from Caddy-internal TLS
    - [x] rebuild-omada-cert.sh script (leaf + root CA concatenation)
    - [x] Systemd path watching Caddy cert file
    - [x] Systemd service to rebuild and restart on cert renewal
  - [x] Caddy integration
    - [x] Internal ingress (omada.abhaile.home.arpa)
    - [x] Service cert block (omada-controller.svc.abhaile.home.arpa)
    - [x] DMZ ingress (omada.abhaile.dedyn.io via hairpin)
  - [x] Design: Certificate update mechanism (systemd path/service watching Caddy cert)

### Host Configuration

- [x] **Users**
  - [x] User configuration generation (common + per-host)
    - [x] users.yaml files for common, phobos, deimos
    - [x] User metadata: uid, gid, home, shell, groups, description
    - [x] Group definitions (abhaile, apex for Coral TPU)
    - [x] Per-host group overrides (phobos adds apex group)
  - [x] SSH keys management
    - [x] ssh_authorized_keys field in users.yaml structure
    - [x] Per-host SSH keys can override common config
    - [x] authorized_keys file generation in user_builder.py
    - [x] Output file: `<host>/users/<user>-authorized_keys`
    - [x] File permissions: 0600 for security
    - [x] Deployment: Copy to `$HOME/.ssh/authorized_keys` on host
  - [x] Sudo configuration
    - [x] Sudoers file generation from rules list
    - [x] setup-users.sh script for useradd/usermod commands
    - [x] sudoers.d-abhaile with Defaults and user rules
- [x] **Software & Packages**
  - [x] `software.yaml` schema (packages/downloads/builds/commands) for common + per-host
  - [x] Action descriptor library under `config/hosts/software/{downloads,builds,commands}/`
    - [x] SOPS binary fetch, gasket-dkms build, unattended upgrades, kernel modules, systemd enablement
  - [x] `software_builder.py` renders merged plan, apt install script, downloads/builds/commands runners, and documentation
- [x] **Phobos-Specific**
  - [x] Coral TPU configuration
    - [x] Group definition (apex) in users.yaml
    - [x] Group assignment to abhaile user
  - [x] Kernel module loading
    - [x] coral-tpu-modules.yaml command descriptor
    - [x] Loads gasket and apex modules
    - [x] Persists to /etc/modules
  - [x] Udev rules
    - [x] coral-tpu-udev.yaml command descriptor
    - [x] /etc/udev/rules.d/65-apex.rules for device access
    - [x] Grants apex group access to Coral TPU device
- [x] **Host Services (non-container)**
  - [x] systemd-networkd drop-ins for /32 service IPs
    - [x] service-addr.conf.j2 template for /32 address rendering
    - [x] Last-octet ordering for drop-in filenames (NNN-\<service>.conf)
    - [x] Rendered to phobos/systemd-networkd via orchestrator
  - [x] Gratuitous ARP for service migration
    - [x] send_gratuitous_arp() function in tools/apply/lib/runtime.sh
    - [x] Dynamic interface detection from drop-in directory structure
    - [x] Uses arping (preferred) or ip neighbor proxy (fallback)
    - [x] Integrated into apply.sh apply phase
  - [x] systemd-resolved configuration
    - [x] resolved.conf in config/hosts/common/systemd-resolved/
    - [x] Builder integration (resolved_builder.py)
    - [x] Orchestrator rendering to out/rendered/\<host>/systemd-resolved/
    - [x] Deployment integration (apply_resolved_config in apply.sh)

### Systemd Integration

- [x] **Core systemd Units**
  - [x] `abhaile-vault-unseal.service` (SOPS decrypt + unseal)
  - [x] `abhaile-secrets-ready.path` + `.service` (sentinel for secrets readiness via vault-agent)
    - [x] Path unit watching `/srv/vault/agent/out/.ready` sentinel
    - [x] Service unit started on sentinel creation
  - [x] `abhaile-gitops@.service` + `abhaile-gitops@.timer` (repo sync with jitter)
- [x] **Dependency Ordering**
  - [x] Boot order: networkd → chrony → coredns → blocky → vault → vault-agent → services
    - [x] Hardcoded systemd dependencies in quadlet templates
    - [x] Host-aware: only depends on services deployed on same host
    - [x] vault: After chrony-a, blocky
    - [x] caddy-dmz, authelia: After abhaile-secrets-ready
    - [x] caddy-internal: After vault
    - [x] omada-controller: After caddy-internal
  - [x] Service ordering via `After=`, `Requires=`, `Wants=`
    - [x] Template rendering of systemd directives in quadlets
- [x] **Reload Mechanisms**
  - [x] Caddy reload triggers (config hash change)
    - [x] caddy-dns-desec.path watching env file changes
    - [x] caddy-dns-desec.service restarts Caddy on update
  - [x] CoreDNS reload triggers (zone/config hash change)
    - [x] coredns-zones.path watching zone directory
    - [x] coredns-zones.service sends SIGUSR1 to CoreDNS
  - [x] Vault-agent template reload triggers (batch daemon-reload)
    - [x] Authelia config/redis config path units with daemon-reload commands

## Phase 2: Deployment & Automation

### CI/CD Pipeline

- [x] **Pre-commit Hooks**
  - [x] YAML validation (check-yaml hook)
  - [x] Python linting (ruff with --fix, black formatting)
  - [x] Bash linting (shellcheck with severity warning, selective exclusions)
  - [x] Template validation (j2lint for Jinja2 syntax)
  - [x] JSON validation (check-json hook)
  - [x] JSON Schema validation (check-jsonschema for mapping.yaml, network.yaml, service.yaml)
  - [x] Trailing whitespace/end-of-file fixes
  - [x] Merge conflict detection
  - [x] Secret scanning (gitleaks)
- [x] **CI Validation**
  - [x] Pre-commit hook execution (all hooks)
  - [x] Unit tests (pytest with coverage on tools/lib)
  - [x] Integration tests (orchestrator render tests)
  - [x] Orchestrator render tests (all hosts)
  - [x] Systemd unit validation (systemd-analyze verify on .network/.netdev)
  - [x] Quadlet syntax validation ([Unit] section check)
  - [x] Network validation (IP uniqueness, VLAN consistency via utils.py)
  - [x] Secret scan (gitleaks-action)
  - [x] JSON Schema validation (via pre-commit)
  - [x] Trivy security scanning (HIGH/CRITICAL, SARIF upload to GitHub Security)
- [x] **Renovate**
  - [x] Configuration file (.renovaterc.json)
  - [x] Monday daytime schedule (09:00-17:00)
  - [x] Manual review for all updates (no auto-merge)
  - [x] Max 3 concurrent PRs
  - [x] Dependency labels
  - [x] Python dependencies (requirements.txt via pip_requirements)
  - [x] Container image tags (regex manager for \*.image files)
  - [x] Dockerfile base images (dockerfile manager enabled)
  - [x] GitHub Actions workflow versions (Renovate auto-detects)
- [x] **Nightly CI Jobs**
  - [x] Scheduled execution (03:00 UTC daily)
  - [x] Pre-commit execution (full)
  - [x] Orchestrator render (all hosts)
  - [x] Secret scan (gitleaks via pre-commit)
  - [x] Trivy dependency scan (MEDIUM/HIGH/CRITICAL)
  - [x] Trivy container image scan (from quadlet Image= lines)
  - [x] Inventory generation (INVENTORY.md uploaded as artifact, tracked in repo)
- [x] **Build System**
  - [x] Makefile with venv isolation
  - [x] Targets: install, test, lint, render, clean, clean-venv
  - [x] pytest configuration (pyproject.toml)
  - [x] .gitignore for build artifacts (.venv, .coverage, **pycache**, out/, tmp/)
  - [x] INVENTORY.md tracked in repo (generated by nightly jobs)

### Deploy Pipeline & Host Configuration

- [x] **Staging & Apply Logic**
  - [x] Local `tmp/` directory for staging (not `/tmp/`)
  - [x] Service quadlet staging from rendered output
  - [x] Dry-run mode with drift detection and directory creation preview
  - [x] Named volume host directory creation (`Device=` in `.volume` units)
  - [x] Mounted_files host directory creation (`Volume=` absolute paths in `.container` units)
  - [x] Mode `0750` for created directories
  - [x] Rootless quadlet installation
    - [x] Detect `home/<user>/.config/containers/systemd/` paths in rendered output
    - [x] Copy to actual `/home/<user>/.config/containers/systemd/` with correct ownership
    - [x] Enable user lingering (`loginctl enable-linger`)
    - [x] User systemd daemon-reload and enable (`systemctl --user`)
  - [x] `systemctl daemon-reload` after quadlet changes

### GitOps & Deployment

- [x] **GitOps Mechanism**
  - [x] Systemd timer (`abhaile-gitops@.timer`) for periodic execution
  - [x] Oneshot service (`abhaile-gitops@.service`) that runs `gitops_runner.sh`
  - [x] Repo fetch with branch/commit/tag pinning support
  - [x] Orchestrator integration (render configs for target host)
  - [x] Drift detection (compare staged output to live configs; exit if no drift)
  - [x] Config validation (systemd-analyze, quadlet syntax, semantic checks)
  - [x] Atomic apply with backup/restore (copy to live, daemon-reload, conditional service restart)
  - [x] State file tracking (commit hash, timestamp, run status)
  - [x] Dry-run mode (simulate without applying changes)
  - [x] Environment-driven config (repo URL, branch, dry-run flag, auto-restart flag, git credentials)
- [x] **Credentials handling**
  - [x] SOPS age encryption support
    - [x] Age key location: `/root/.config/sops/age/keys.txt` (or via `SOPS_AGE_KEY_FILE`)
    - [x] Bootstrap check: error if age key missing; provide setup instructions
    - [x] Documentation: `secrets/README.md` with key generation and rotation guide
  - [x] Token creation/handling for vault-agent
    - [x] AppRole-based token minting via `abhaile-vault-token-refresh@.service` + `.timer`
    - [x] Env file: `/etc/abhaile/vault-agent-approle/<host>.env` (SOPS-encrypted)
    - [x] Script: `tools/vault/vault_token_refresh.sh` (mints token via Vault API)
    - [x] Token written to `/home/abhaile/.config/vault-agent/token` (mode 0600)
    - [x] Refresh every 12h; persistent across reboot; randomized delay (600s)
  - [x] SOPS decryption in GitOps runner
    - [x] Function `decrypt_secrets_if_changed()` checks SOPS file mtime vs plaintext
    - [x] Decrypts to `/etc/abhaile/<service>/` directories (mode 0600)
    - [x] Supports split-per-service structure: `secrets/<service>.sops.yaml`
    - [x] Aborts apply if decryption fails (safe failure)
  - [x] Vault Unseal handling
    - [x] Already implemented: `abhaile-vault-unseal.service` with SOPS decryption
  - [x] Credentials handling (SOPS + env files)
    - [x] Created secrets/README.md and example SOPS templates
    - [x] GitOps env files templates (`secrets/gitops-<host>.sops.env.example`)
    - [x] deSEC token env file template (`secrets/caddy-dmz-desec.sops.yaml.example`)
    - [x] Vault AppRole credentials templates (`secrets/vault-agent-approle-<host>.sops.env.example`)
    - [x] Documentation in docs/CREDENTIALS.md with workflow guide
    - [x] Integration with gitops_runner.sh decrypt_secrets_if_changed()
- [x] **Bootstrap**
  - [x] curl-bash bootstrap script for new hosts (tools/bootstrap/bootstrap.sh)
  - [x] Initial host setup (users, packages, ssh keys, base config)
  - [x] Repository clone and initial render
  - [x] First-run deployment (dry-run mode)
  - [x] SOPS age key setup check and pre-flight validation
  - [x] Install systemd units (gitops, vault-token-refresh, vault-unseal)
  - [x] Decrypt and place initial secrets
  - [x] Documentation in tools/bootstrap/README.md
- [ ] **Deployment Validation**
  - [ ] Atomic apply with backup/rollback
  - [ ] Rollback mechanism
  - [ ] Deploy on deimos
  - [ ] Deploy on phobos
  - [ ] Service health checks
  - [ ] End-to-end connectivity tests
  - [ ] DNS resolution validation (internal + DMZ)
  - [ ] TLS certificate validation (internal CA + public ACME)
  - [ ] deSEC apply phase validation (live API apply + rollback path)
  - [ ] Trigger/poll/timer design
  - [ ] Change detection and validation
  - [ ] State file tracking for deployed configs
  - [ ] Deployment state tracking

### Documentation & Inventory

- [x] **Documentation Generation**
  - [x] Network topology diagram (VLANs, hosts, services) → see `docs/NETWORK.md`
  - [x] Service inventory (what runs where) → see `docs/INVENTORY.md` + root `INVENTORY.md`
  - [x] Port mapping documentation → see `docs/net/PORTS.md`
  - [x] DNS zone documentation (authoritative/recursive specifics) → see `docs/net/DNS.md`
  - [x] Architecture decision records (ADR)
  - [x] README updates for each component (`README.md`, `docs/README.md`)
  - [x] Quick test/validation section in README (pre-commit, pytest, orchestrator render)
- [x] **Inventory Generation**
  - [x] JSON/YAML inventory of all deployed services
  - [x] Host-to-service mapping export
  - [x] Network assignment report (IPs, VLANs)
  - [x] TLS certificate inventory
  - [x] Dependency graph generation
- [x] **Operational Documentation**
  - [x] Deployment runbook → `docs/OPERATIONS.md`
  - [x] Troubleshooting guides → `docs/OPERATIONS.md`
  - [x] Backup/restore procedures → `docs/OPERATIONS.md`
  - [x] Disaster recovery plan → `docs/OPERATIONS.md`
  - [x] Service migration guide (/32 movement + gratuitous ARP) → `docs/OPERATIONS.md`
  - [x] Break-glass procedures (ER605 port 5 + laptop) → `docs/OPERATIONS.md`
  - [x] Vault unseal procedures (SOPS + offline keys) → `docs/QUICKSTART.md` + `docs/CREDENTIALS.md`
  - [x] ACL testing matrix → `docs/NETWORK.md`
  - [x] Secret rotation schedule → `docs/CREDENTIALS.md` + `docs/OPERATIONS.md`
- [x] **Auto-Generated Documentation**
  - [x] INVENTORY.md (Service|Host|VLAN|IP|Ports|FQDNs)
  - [x] Commit signing policy (Conventional Commits) → `docs/POLICY.md`

## Phase 3: Additional Homelab Services

### Home Automation

- [ ] **Home Assistant**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Integration with Mosquitto
- [ ] **Mosquitto (MQTT)**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Vault-agent template for passwords
- [ ] **Zigbee2MQTT**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] USB device passthrough
- [ ] **ESPHome**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
- [ ] **Frigate**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Coral TPU integration (phobos)
  - [ ] Go2rtc integration
- [ ] **Go2rtc**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation

### Host Hardening & Observability

- [ ] **Host Hardening**
  - [ ] nftables configuration (default deny, service-specific rules)
  - [ ] Per-UID egress routing for qBittorrent → Gluetun
  - [ ] DoH/DoT blocklist management (monthly refresh)
  - [ ] Fail2ban configuration (nftables actions)
  - [ ] CIS-lite baseline (rp_filter, SYN cookies, SSH hardening)
  - [ ] Filesystem configuration (noatime, \_netdev mounts)
- [ ] **Node-exporter + Podman-exporter**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
- [ ] **Promtail**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation (log shipping to Loki)

### Monitoring & Observability

- [ ] **Prometheus**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation (scrape targets from service.yaml)
  - [ ] Service discovery integration
  - [ ] Job configurations for all exporters
- [ ] **Alertmanager**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Vault-agent template for notification credentials (email)
  - [ ] Design: Future Matrix/Telegram integration
- [ ] **Grafana**
  - [ ] Quadlets (.container, .volume)
  - [ ] Datasource provisioning (Prometheus, Loki)
  - [ ] Dashboard provisioning
  - [ ] Vault-agent template for admin password
  - [ ] Enable metrics endpoint
- [ ] **Loki**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Integration with Promtail/journal
  - [ ] Retention policy (Infra 30d, Apps 7d)
  - [ ] Syslog receiver (UDP 514, TCP 1514) for Omada/ER605/switches
- [ ] **Exporters**
  - [ ] Blackbox exporter (HTTP/DNS/TCP probes)
    - [ ] Internal probes (\*.abhaile.home.arpa, \*.svc.abhaile.home.arpa)
    - [ ] DMZ probes (\*.abhaile.dedyn.io via hairpin NAT)
    - [ ] TCP probes (DNS :53, MQTT :1883, SMTP :25, Vault :8200)
    - [ ] External probes (1.1.1.1, 9.9.9.9, desec.io, deb.debian.org)
    - [ ] Validation of Blackbox probes post-deployment
  - [ ] SNMP exporter (ER605, switches, APs)
    - [ ] Per-device modules
    - [ ] 60s scrape interval
    - [ ] SNMP v2c community string via Vault
  - [ ] Node exporter (host metrics) - already deployed
  - [ ] Podman exporter (container metrics) - already deployed
  - [ ] Optional exporters:
    - [ ] chrony-exporter (NTP drift)
    - [ ] smartctl-exporter (disk health)
    - [ ] ups-exporter (NUT integration)
    - [ ] Custom exporters (nftables bytes/packets per /32)

### Network Monitoring

- [ ] **Uptime Kuma**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
- [ ] **LibreSpeed**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
- [ ] **Smokeping**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation (targets)

### Networking & VPN

- [ ] **Gluetun + qBittorrent Integration**
  - [ ] Gluetun quadlets with VPN provider config
  - [ ] qBittorrent Network=container:gluetun
  - [ ] Start order enforcement (Gluetun before qBittorrent)
    - [ ] Quadlet dependency (qBittorrent After/Requires gluetun.service)
    - [ ] qBittorrent only starts if Gluetun healthy
  - [ ] Kill-switch: nftables per-UID egress + policy routing table `vpn`
  - [ ] Vault-agent template for VPN credentials

### Media & Content

- [ ] **Immich**
  - [ ] Quadlets (.container, .volume, pod)
  - [ ] Config generation
  - [ ] Database integration
- [ ] **Jellyfin**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Hardware acceleration (VA-API/QSV)
- [ ] **Tdarr**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Transcoding node configuration
- [ ] **\*arr Stack** (Radarr, Sonarr, Lidarr, Readarr, Bazarr, Prowlarr)
  - [ ] Quadlets for each service
  - [ ] Config generation
  - [ ] Shared volume configuration
  - [ ] API key management via vault-agent
- [ ] **Jellyseerr**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Integration with Jellyfin + \*arr
- [ ] **Flaresolverr**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation

### Utilities

- [ ] **Homepage**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation (dashboard links)
  - [ ] Service discovery integration
- [ ] **Netbox**
  - [ ] Quadlets (.container, .volume, pod)
  - [ ] Config generation
  - [ ] Database integration
  - [ ] IPAM/DCIM documentation
- [ ] **Vaultwarden**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Vault-agent template for admin token
- [ ] **Postfix**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Vault-agent template for relay credentials
  - [ ] VLAN/host-based relay restrictions
- [ ] **Crowdsec**
  - [ ] Quadlets (.container, .volume)
  - [ ] Config generation
  - [ ] Integration with Caddy/logs
  - [ ] ER605 bouncer integration
  - [ ] Alert-only mode for LAN sources
  - [ ] nftables + ER605 ACL access restrictions (Admin/VPN + Prometheus only)

## Phase 4: Network & Omada Configuration

### Network Device Configuration (Manual via Omada)

- [ ] **ER605 Gateway**
  - [ ] VLAN configuration (1, 99, 20, 30, 40, 50, 60, 70, 80, 90, 100)
  - [ ] DHCP scopes per VLAN (Option 6: DNS, Option 42: NTP, Option 15/119: domain)
  - [ ] Inter-VLAN ACL policy (explicit allows + denies)
    - [ ] Inter-VLAN ACL testing
  - [ ] WireGuard VPN server (wg0, 172.20.90.1/24, UDP 51820)
    - [ ] VPN profile validation (admin/user/travel)
  - [ ] NAT hairpin for DMZ access
  - [ ] DoH/DoT blocklist enforcement
  - [ ] UDP/123 (NTP) WAN blocking (except admin/VPN)
  - [ ] UPnP disabled (exception: VLAN 40 Gaming)
  - [ ] CrowdSec bouncer integration
- [ ] **Switch Configuration (SG2218, SG2016P, SG2008P)**
  - [ ] Port profiles (TRUNK-Core, TRUNK-Phobos, TRUNK-AccessSwitch, ACCESS-\*, AP-Uplink)
  - [ ] RSTP configuration (root = SG2218, secondary = SG2016P)
  - [ ] IGMP snooping + querier (VLAN 20, 70)
  - [ ] Storm control on TRUNK-Phobos
  - [ ] BPDU Guard on access ports
  - [ ] MAC limiting on trunks
  - [ ] LLDP + descriptive device names
- [ ] **Access Points (4x EAP653)**
  - [ ] SSID configuration (6 SSIDs, VLAN mappings)
  - [ ] Wi-Fi 6 optimization
  - [ ] PMF optional on IoT SSID
  - [ ] 11k/v/r disabled on IoT SSID
  - [ ] Multicast enhancements for Cast VLAN
  - [ ] Client isolation on Guest + Camera VLANs
  - [ ] Bonjour gateway (one-way VLAN 70 → VLAN 20)
- [ ] **QoS Configuration**
  - [ ] High priority: VLAN 40 (Gaming) → WAN
  - [ ] DSCP marking (EF/CS6)
  - [ ] Trust DSCP on trunks/AP uplinks
- [ ] **Backup & Export**
  - [ ] Omada site backup schedule (Daily/Weekly/Monthly)
  - [ ] Export to `/opt/abhaile/backups/omada/`
  - [ ] Validate restore process

### Network Implementation Validation

- [ ] **Blocklist & DNS Filtering Automation**
  - [ ] DoH/DoT blocklist refresh automation (Blocky/CoreDNS)
  - [ ] Scheduled fetch from upstream sources (StevenBlack, OISD, etc.)
  - [ ] GitOps integration: commit updated blocklists, auto-deploy
  - [ ] Validation: blocklist apply without breaking legitimate queries
- [ ] **Phase-by-phase validation**
  - [ ] Core init (VLAN 1 → VLAN 99 + trunks)
  - [ ] VLANs/Subnets + DHCP validation
  - [ ] Permissive ACLs (broad allows, validate 20↔99, 20→60)
  - [ ] Wireless SSIDs + DHCP/isolation
  - [ ] Tightened ACLs (enforce DNS/NTP/IoT blocks)
  - [ ] VPN deployment + profile validation
  - [ ] QoS + Multicast confirmation
  - [ ] Monitoring/Backups (SNMP + syslog)
