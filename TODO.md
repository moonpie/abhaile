# TODO: Rebuild Repo Around config/

## Decision Log

1. Decision: Renamed internal package path from `src/abhaile/types/` to `src/abhaile/models/` to avoid collision with Python stdlib module `types` during direct file execution patterns (e.g., `python src/abhaile/cli.py ...`).
   Date: 2026-03-13
   Rationale: `src` layout made direct execution place `src/abhaile` first on `sys.path`, allowing `types` import shadowing; renaming eliminates the collision class without runtime `sys.path` mutation.
   Scope: `src/abhaile/models/` module path, imports (`abhaile.models.config`), and package move from `types` -> `models`.
   Confirmed by: user

1. Decision: Python source layout uses `src/abhaile/` as the canonical package path; apply/diff/render logic lives under `src/abhaile/` and CLI entrypoints are registered from that source tree.
   Date: 2026-03-13
   Rationale: Standard Python `src/` layout reduces accidental local import masking, keeps packaging/tooling conventions clear, and separates installable code from repo assets.
   Scope: Package/module references in TODO/docs (`abhaile/...` -> `src/abhaile/...`) and upcoming source migration.
   Confirmed by: user

1. Decision: Tooling path configuration file is repo-root `paths.ini` (not `scripts/paths.ini`); `scripts/` is reserved for executable shell utilities/wrappers.
   Date: 2026-03-13
   Rationale: `paths.ini` is cross-tool project configuration used by Python and shell code, so it belongs with root project config files rather than inside an executable scripts directory.
   Scope: TODO/docs references to path config location and upcoming file move.
   Confirmed by: user

1. Decision: Apply and diff are Python console entrypoints (`abhaile-apply`, `abhaile-diff`) registered in `pyproject.toml`, with all logic in `src/abhaile/apply/`; `scripts/` retains shell utilities/wrappers (e.g., gitops-runner wrapper); no shell scripts for apply or diff business logic.
   Date: 2026-03-13
   Rationale: Python gives testability, structured error handling, and reuse of existing `src/abhaile/` modules (manifest, validation, types); shell adds no value over `subprocess` for the OS operations apply triggers; aligning with `abhaile-render` pattern keeps CLI consistent.
   Scope: `src/abhaile/apply/` module, `pyproject.toml` entrypoints, `abhaile-apply` and `abhaile-diff` CLI commands; all TODO Apply Pipeline and Ops Tooling session prompts updated to reflect entrypoint names.
   Confirmed by: user

1. Decision: Apply state history is written to `<output>/state/history/manifest-<timestamp>.json` on each successful apply; the last 10 entries are retained and older files pruned automatically; `state/manifest.json` and `state/manifest.previous.json` are plain files (no symlinks) updated by rotation.
   Date: 2026-03-13
   Rationale: History enables audit trail and arbitrary rollback without unbounded disk growth; plain files for current/previous are simpler than symlinks and avoid link breakage when history is pruned; 10 entries provides reasonable coverage without complexity.
   Scope: Apply CLI state write/rotation logic, `state/history/` directory management.
   Confirmed by: user

1. Decision: Output layout is: `<output>/rendered/` is entirely ephemeral — render wipes it before each run and writes the desired manifest inside it as `<output>/rendered/manifest.json`; `<output>/state/` is entirely durable and owned by apply — contains `manifest.json` (last applied), `manifest.previous.json` (prior applied), and `history/` (timestamped archive).
   Date: 2026-03-13
   Rationale: Clean ownership boundaries — render owns `rendered/`, apply owns `state/`; desired manifest lives in the ephemeral render tree so it is always fresh and never confused with applied state; wiping `rendered/` as a pre-render step (inside the render CLI itself) ensures stale artifacts never persist across renders.
   Scope: Render CLI (pre-render wipe of `rendered/`), apply CLI (state read/write paths), README and ADR path documentation.
   Confirmed by: user

1. Decision: Apply removal behavior uses guarded pruning with two explicit modes: `--prune` deletes only files that were in last-applied state, are absent from desired manifest, and are unchanged on host since last apply (`live_hash == last_applied_hash`); `--force-prune` additionally allows deleting those removal candidates even when host content has drifted (`live_hash != last_applied_hash`).
   Date: 2026-03-13
   Rationale: Prevent destructive deletion of locally modified files by default while still supporting explicit reconciliation of decommissioned artifacts; this addresses apply deltas between desired manifest, last-applied state, and live host state.
   Scope: Apply CLI prune planning/execution semantics, dry-run reporting, and safety gates for removal candidates.
   Confirmed by: user

1. Decision: Manifest now includes `rendered_at` and per-entry `rel_path`; `target_path` is mapped to the actual host destination path (instead of mirroring rendered tree paths with a leading slash).
   Date: 2026-03-11
   Rationale: `rendered_at` is useful for auditing/debugging render runs; `rel_path` should describe the artifact path relative to `<output>/rendered/`; `target_path` must represent where apply will reconcile on the host.
   Scope: `abhaile/renderers/manifest.py` (added `rendered_at`, added `rel_path`, mapped target paths from `system/`, `users/`, and `services/<service>/` prefixes), unit/integration manifest tests.
   Confirmed by: user

1. Decision: Manifest simplified to drift-only fields: manifest-level `host` string, per-entry `target_path`, `sha256`, and `size`; apply-specific fields (mode, uid, gid, kind, source, rel_path) and manifest-level timestamp (rendered_at) deferred until apply implementation.
   Date: 2026-03-09
   Rationale: Drift detection only requires content hash and target location; minimal schema reduces coupling and simplifies initial implementation; apply-specific metadata (permissions, ownership, artifact classification) can be added later when apply command is developed; removing timestamp improves determinism.
   Scope: `abhaile/renderers/manifest.py` (removed \_classify_artifact helper, simplified build_manifest signature to require host parameter, reduced entry fields), `tests/unit/python/renderers/test_manifest.py` (updated all tests for new schema).
   Confirmed by: user

1. Decision: Removed backward compatibility fallback in DNS serial validation - config_root parameter is now required (Path, not Optional[Path]); legacy synthetic hash format was deleted.
   Date: 2026-03-09
   Rationale: Legacy fallback caused maintenance burden, inconsistent behavior between tests with/without config_root, and was never used in production (CLI always passes config_root); making config_root required simplifies the codebase and ensures validation always uses the exact template-rendered zone format.
   Scope: `abhaile/dns/serial_validator.py` (removed \_build_legacy_zone_content_for_hash, made config_root required in validate_zone_serial and validate_zone_serial_collect), `abhaile/validation/dns.py` (made config_root required in validate_dns_serials), test fixtures updated to provide minimal config_root with coredns-common service template.
   Confirmed by: user

1. Decision: DNS serial validation computes `serial.content_hash` from the same zone template rendering path as DNS renderer (provider `dns.zone_files` template resolution) when config root is available; this avoids false serial drift caused by legacy synthetic hash formatting differences.
   Date: 2026-03-09
   Rationale: Serial validation must reflect actual rendered zone content; hashing a different canonical string than renderer output caused spurious prompts to update `serial.date`/`serial.counter`/`serial.content_hash` even when records were unchanged.
   Scope: `abhaile/dns/serial_validator.py`, `abhaile/validation/dns.py`, CLI DNS validation call path, DNS integration/unit tests.
   Confirmed by: user

1. Decision: Manifest writer records only regular files (no directories/symlinks), adds `kind` and `source` fields, and maps `target_path` by stripping `system/`, `users/`, and `services/<service>/` prefixes while leaving `software/` as a logical namespace; `rendered_at` remains a manifest-level timestamp and apply is responsible for creating any required directories.
   Date: 2026-03-08
   Rationale: Apply needs stable file inventory without directory noise; `kind`/`source` allow apply to route execution-required artifacts; logical paths for software avoid coupling to output overrides; per-file timestamps would break determinism, while a single manifest timestamp remains useful for auditing.
   Scope: abhaile/renderers/manifest.py, tests/unit/python/renderers/test_manifest.py, apply pipeline planning.
   Confirmed by: user

1. Decision: Align user management schema with sysusers by renaming `description` to `gecos`, adding a boolean `system` flag on users, and validating uid/gid conflicts across host include chains.
   Date: 2026-03-06
   Rationale: Sysusers uses the GECOS field name and benefits from explicit system/login user intent; static ids are preferred, so validating duplicate uid/gid values avoids ambiguous user/group definitions across includes.
   Scope: schemas/host.schema.json, config/hosts/\*/host.yaml, abhaile/validation/users.py, abhaile/cli.py.
   Confirmed by: user

1. Decision: User management merges across host composition includes by name; scalar fields must match if redefined while list fields are unioned; uid/gid conflicts across different names are validation errors.
   Date: 2026-03-06
   Rationale: Reduce duplication (common defaults stay centralized) while preventing ambiguous overrides and id collisions.
   Scope: README.md (documentation), schemas/host.schema.json (description), users renderer and validation behavior.
   Confirmed by: user

1. Decision: User management renderer outputs systemd-sysusers config plus sudoers drop-in instead of a monolithic setup script, keeping drift/apply declarative and idempotent.
   Date: 2026-03-06
   Rationale: Sysusers provides native, declarative user/group reconciliation and minimizes imperative scripting while aligning with drift-driven apply.
   Scope: abhaile/renderers/users.py, CLI render pipeline, users render outputs under rendered/users/etc/.
   Confirmed by: user

1. Decision: Software renderer comment style and import conventions match project patterns: concise docstrings (no verbose "Output contract" sections), direct module imports in CLI (no package-level exports), simplified function documentation matching other renderers.
   Date: 2026-03-05
   Rationale: Consistency with existing renderer modules (host.py, services.py, networkd.py) improves code readability and maintainability; direct imports from specific modules are more explicit than package-level exports; concise docstrings reduce noise without losing essential information.
   Scope: `abhaile/renderers/software.py` (docstring simplification), `tests/unit/python/renderers/test_software.py` (import fix from `abhaile.renderers` to `abhaile.renderers.software`).
   Confirmed by: user (after reviewing inconsistencies with project conventions)

1. Decision: Software render output uses mixed granularity: a single merged `packages.txt` artifact for apt-managed packages, and one rendered spec file per entry for `downloads`, `builds`, and `commands`; duplicate software ids across host include chains are treated as render errors; host software spec files include explicit `id` and are schema-validated.
   Date: 2026-03-05
   Rationale: apt handles idempotency for already-installed packages, so a single package list remains safe and simple; entry-level files for downloads/builds/commands preserve declarative drift granularity so apply can target only added/changed specs; duplicate ids are unexpected and should fail fast to avoid ambiguous behavior; explicit ids and schema checks improve determinism and config safety.
   Scope: `abhaile/renderers/software.py`, CLI integration, `schemas/software-action.schema.json`, host software spec YAML files, pre-commit schema hooks.
   Confirmed by: user

1. Decision: Keep the apply manifest module and implement drift detection in the apply pipeline; tracked in TODO items until implementation is complete.
   Date: 2026-02-15
   Rationale: Apply is required for the repo’s workflow, and drift detection is a core safety gate; keeping the module makes the planned responsibilities explicit and prevents ad hoc implementation later.
   Scope: src/abhaile/apply/manifest.py and apply pipeline integration.
   Confirmed by: user

1. Decision: DNS reverse zones automatically generate PTR records from A/AAAA records marked with `ptr: true` in network.yaml; PTR records have reverse DNS notation name (final octets) and FQDN rdata with trailing dot; reverse zone identification uses smart IP-to-zone matching (172.20.20.10 belongs to 20.20.172.in-addr.arpa.); PTR records rendered inline during zone file generation; DNS serial validation compares rendered zone hash against network.yaml content_hash, computing expected serial from git HEAD (last commit) serial vs today's date, incrementing counter if same day or resetting to 00 if new day; validation reports only fields that differ between expected and current workspace values (serial.date, serial.counter, serial.content_hash).
   Date: 2026-02-08
   Rationale: PTR records enable reverse DNS lookups (IP → hostname) which are essential for service identification, logging correlation, and security policies; automatic generation from forward records (marked with ptr: true) maintains single source of truth and prevents manual sync errors; FQDN format with trailing dot ensures correct DNS resolution; smart zone matching handles /24 networks correctly (comparing first 3 octets); git HEAD comparison for serial increment prevents counter exhaustion during development iterations—serial only increments once per commit, not per render; differential reporting (only changed fields) reduces noise and makes fixes clearer; expected serial computation uses git HEAD date/counter (not workspace) to determine increment logic, ensuring predictable behavior across development cycles.
   Scope: DNS renderer (scripts/lib/python/renderers/dns.py): added \_ip_to_reverse_dns() to convert IPs to reverse DNS notation, \_collect_ptr_records_for_reverse_zone() to scan forward zones for ptr: true A records and generate PTR records for matching reverse zones, updated \_collect_zone_records() to invoke PTR collection for reverse zones; refactored \_validate_zone_serial() to use git HEAD for increment logic (not workspace), compute expected hash with expected serial in SOA, compare expected vs current workspace values, and report only differences; PTR records generated for 2 reverse zones (20.20.172.in-addr.arpa. with 11 PTR records, 100.20.172.in-addr.arpa. with 2 PTR records); validation output format changed from "Committed serial: X, Expected serial: Y" to showing only fields needing updates.
   Confirmed by: user

1. Decision: DNS zone renderer with git-aware serial validation; zones rendered to `out/rendered/services/<providing-service>/etc/coredns/zones/<zone>.zone` (to deployed services like coredns-clean/coredns-filtered, not base service coredns-common) in BIND RFC 1035 format; rendering is per-host (only services on current host receive zones), matching ingress pattern; serial tracking uses date/counter/content_hash (YYYYMMDDCC format); validation compares rendered zone hash against stored hash; if mismatch, fails with expected serial values; counter increments relative to git HEAD (last commit), not working tree, preventing unnecessary increments during iterative development; validation collects all zone errors before failing for better UX; only internal zones rendered (external zones like desec.io skipped); records ordered deterministically (hosts in definition order, then services in definition order, preserving per-entity record order); zone records aggregated from ALL services in mapping.yaml (for cross-host service discovery) but zones only rendered to services on current host; render_dns() accepts host_services (current host's services) and all_services (for record aggregation), resolves composition.include chains to detect dns.zone_files inheritance, and renders each zone to services on current host that provide it.
   Date: 2026-02-08
   Rationale: DNS zones need deterministic rendering with change detection; serial tracking prevents stale zone propagation; git-aware increment logic prevents exhausting counter space (00-99) during development iterations by only incrementing once per commit; collecting all errors before failing allows user to update all zones in single edit; BIND format required for CoreDNS zone plugin; deterministic ordering ensures cross-host consistency; zones must render to deployed services (coredns-clean on deimos, coredns-filtered on phobos) not base service (coredns-common) because only deployed services appear in mapping.yaml and receive quadlets/systemd units—matches ingress pattern where caddy-dmz/caddy-internal aggregate from other services; per-host rendering allows future divergence in zone configurations between coredns-clean and coredns-filtered (e.g., different filtering rules per host) while maintaining cross-host record aggregation for service discovery; eliminates special-case "render once" logic that would break host-specific rendering.
   Scope: DNS renderer (scripts/lib/python/renderers/dns.py: render_dns with host_services/all_services parameters, resolve_service_composition helper, provider_to_services map building scoped to host_services, \_validate_zone_serial, \_validate_zone_serial_collect, \_collect_zone_records aggregates from network which contains all hosts/services, \_render_zone_file, \_compute_content_hash, \_get_git_head_serial); DNS validation (scripts/lib/python/validation/dns.py: validate_dns_serials) integrated into load_and_validate() for fail-fast; scripts/render integration calls render_dns per-host with host_services.get(host, []) and all_services; 27 unit tests + 7 integration tests (all 160 tests passing); renders zone files for 4 internal zones (svc.abhaile.home.arpa, abhaile.home.arpa, 20.20.172.in-addr.arpa, 100.20.172.in-addr.arpa) to coredns-clean (deimos) and coredns-filtered (phobos) directories separately per host.
   Confirmed by: user

1. Decision: All renderers (vault-agent, ingress, quadlets) recursively follow `composition.include` to collect their respective content from included services; includes are processed depth-first (includes before direct definitions); cycle detection with clear error messages; services rendered in mapping.yaml order with includes expanded inline; visited tracking prevents redundant processing; each renderer has dedicated resolver functions (\_collect_service_vault_templates, \_collect_service_ingress_blocks, \_resolve_pod_definition, \_resolve_container_definition) that handle include traversal.
   Date: 2026-02-07
   Rationale: Include mechanism should work consistently across all composition content types (config, vault_agent, ingress, pod, container), not just config; depth-first traversal ensures included content appears before direct definitions, allowing overrides; cycle detection prevents infinite recursion; visited tracking maintains efficiency; this enables base/common services (like coredns-omada) to define vault templates, ingress blocks, or container definitions that are inherited by services that include them (like coredns-filtered, coredns-clean).
   Scope: All three renderers updated with recursive include resolution (vault_templates.py: \_collect_service_vault_templates, ingress.py: \_collect_service_ingress_blocks, quadlets.py: \_resolve_pod_definition/\_resolve_container_definition); 24 existing unit tests still pass; 20 existing integration tests still pass; 5 new integration tests added (test_composition_includes.py) to explicitly verify include support; verified with coredns-omada vault template now appearing in both phobos (via coredns-filtered) and deimos (via coredns-clean) renders.
   Confirmed by: user

1. Decision: Vault-agent templates renderer aggregates vault-agent templates from services running on the SAME HOST (not cross-host like ingress) because vault-agent writes to local filesystem at /agent/templates/ on each host; template `source` paths are derived by replacing `<service>/templates/` with `/agent/templates/`, and template files are copied to `/srv/vault/agent/templates/` with the same replacement; template `dest` paths are rendered as `/agent/out/<out>`; base vault-agent service defines vault_agent.base with source template and variables; template variables support network placeholders (%%network.services.vault.address | strip_cidr%%) with jinja2 filter syntax; aggregated template metadata rendered into base config (config.hcl.j2) with deterministic ordering by mapping.yaml order (and within a service, in service.yaml order).
   Date: 2026-02-07
   Rationale: Vault-agent runs unprivileged on each host and writes templates to local filesystem, so must only aggregate from co-located services; the templates/out volumes require host-path placement under `/srv/vault/agent/{templates,out}` while config references mounted `/agent/{templates,out}` paths; network placeholder resolution with filter support handles complex configuration like CIDR-stripped addresses; mapping order preserves intent and is deterministic.
   Scope: Vault templates renderer (scripts/lib/python/renderers/vault_templates.py) with integration into render pipeline (scripts/render); 13 unit tests + 3 integration tests all passing; verified with actual config for phobos (authelia, caddy-dmz, ddclient templates) and deimos (vault-agent only).
   Confirmed by: user

1. Decision: Ingress renderer aggregates Caddy configuration blocks from ALL services in mapping (across all hosts) into base services (caddy-dmz, caddy-internal) that are running on the CURRENT HOST ONLY; blocks appended in mapping.yaml order (and within a service, in service.yaml order); source paths in service.yaml may include service-name prefix (e.g., "caddy-dmz/config/Caddyfile") which renderer strips; aggregated content marked with comment separators and per-service headers.
   Date: 2026-02-07
   Rationale: Centralized reverse proxies need configuration from all services regardless of host placement, but the base Caddyfile should only be rendered on the host where the reverse proxy service is deployed; mapping order preserves intent and enables logical grouping; service-prefix handling maintains compatibility with existing config path patterns; comment separators provide clear visual separation in aggregated Caddyfiles.
   Scope: Ingress renderer (scripts/lib/python/renderers/ingress.py) with integration into render pipeline; aggregates `ingress.{dmz|internal}.blocks` from all services into services defining `ingress.{dmz|internal}.base` (scoped to current host); 11 unit tests + 3 integration tests.
   Confirmed by: user

1. Decision: Quadlets renderer (pods) extends container renderer to handle multi-container pods with `-app` suffix naming convention (pod: \<service>-app.pod, containers: \<service>-app-\<container>.container, volumes: \<service>-app-\<container>-\<volume>.volume); container definitions extracted from `containers[].container` key if present; shared volumes across pod containers rendered once and reused; network quadlets generated at pod level for ipvlan-l2 mode.
   Date: 2026-02-06
   Rationale: `-app` suffix clearly distinguishes pod-related artifacts from standalone containers; container key extraction supports existing service.yaml structure (authelia pattern); shared volume reuse prevents duplicate host path errors when multiple containers mount same volume; leveraging existing container logic maximizes code reuse while supporting pod-specific features.
   Scope: Pod rendering in quadlets renderer (\_render_pod_quadlets, \_render_named_volumes_for_pod_container); tested with authelia service (2 containers: authelia + redis, shared host-certs volume); 6 new unit tests + 1 integration test.
   Confirmed by: user

1. Decision: Quadlets renderer (containers) generates output to well-known paths per user (rootful: /etc/containers/systemd/, rootless: /home/\<user>/.config/containers/systemd/); shared volumes render to \_shared subdirectory with non-prefixed names; network quadlets deduplicated per VLAN and rendered to podman-networks/ (rootful only); volume_lines in container templates include both named_volumes and mounted_files; Jinja2 trim_blocks/lstrip_blocks prevent blank lines from template control tags.
   Date: 2026-02-06
   Rationale: Well-known paths align with systemd/podman quadlet conventions; shared volume deduplication reduces redundancy; network quadlet deduplication avoids duplicates when multiple services use same VLAN; whitespace control ensures clean output formatting without empty lines from templating.
   Scope: Quadlets renderer (scripts/lib/python/renderers/quadlets.py) and integration into render pipeline (scripts/render).
   Confirmed by: user

1. Decision: Service config rendering resolves composition includes first (depth-first), then renders the service's own config entries to allow overrides by later entries; cycles are an error.
   Date: 2026-02-04
   Rationale: Ensures shared config from included services is applied before service-specific overrides; avoids silent infinite recursion.
   Scope: Service configs renderer include handling.
   Confirmed by: assistant

1. Decision: Resolve systemd-networkd drop-in interface names by parsing the base file's [Match] Name=, and allow any \*.d drop-in directory (not just .network.d).
   Date: 2026-02-02
   Rationale: Avoids fragile filename parsing and supports all systemd-networkd drop-in types; ensures base file exists and provides authoritative interface name.
   Scope: Networking renderer drop-in selection and validation logic.
   Confirmed by: user

1. Decision: Centralize tooling paths in repo-root `paths.ini` for consistent path resolution.
   Date: 2026-02-01
   Rationale: Single source of truth for defaults across tooling in any language.
   Scope: root-level project config and tooling path resolution.
   Confirmed by: user

1. Decision: Suggestions and alternatives are allowed, but must be confirmed before deviating from the task prompt.
   Date: 2025-03-08
   Rationale: Encourage improvements while keeping scope controlled.
   Scope: Task execution prompts and agent behavior.
   Confirmed by: user

1. Decision: Use `scripts/` directory instead of `tools/` for render/apply pipeline.
   Date: 2026-01-31
   Rationale: Aligns with common convention; `scripts/` is clearer for operational tooling.
   Scope: Repository layout and documentation.
   Confirmed by: task requirements (Foundations phase)

1. Decision: Render scope is single-host or `--all` (no partial host lists).
   Date: 2026-01-31
   Rationale: Simplifies render logic and state tracking; multi-host validation is only for pre-commit checks.
   Scope: Render CLI and workstation/CI workflows.
   Confirmed by: user

1. Decision: Apply is always single-host; workstation/CI uses `--dry-run` mode for drift analysis.
   Date: 2026-01-31
   Rationale: Simplifies apply atomicity and safety gates; no need for multi-host apply orchestration.
   Scope: Apply CLI and workstation/CI workflows.
   Confirmed by: user

1. Decision: Define config schema using JSON Schema (draft-07) with `check-jsonschema` pre-commit hooks.
   Date: 2026-02-01
   Rationale: Pre-commit validation of mapping/network/service YAML files catches structural errors early; JSON Schema is well-supported and allows template placeholders.
   Scope: Config validation (mapping.schema.json, network.schema.json, service.schema.json in schemas/).
   Confirmed by: user (via Foundations/Define config schema task)

1. Decision: Adopt explicit host.yaml files with schema validation for host configuration.
   Date: 2026-02-01
   Rationale: Centralizes host-specific configuration in a single declarative file (matching service.yaml pattern); enables schema validation via pre-commit; improves discoverability and reduces cognitive load vs. scattered implicit directory structure. Composition uses additive inheritance via `include: common` with no deletion capability.
   Scope: Host configuration structure (config/hosts/\<host>/host.yaml and host.schema.json).
   Confirmed by: user (via implementation review)

## Routine Prompts

### Session Preface

#### Prompt Wrapping

```text
You are my coding buddy for this repo. Follow .github/copilot-instructions.md.
Work only on the task below.
Be explicit about files you read/write and keep changes minimal.
Suggest alternatives when you see them, but ask for confirmation before deviating.
Log any decisions in the Decision Log at the top of TODO.md if they’re not ADR-worthy.

<Prompt>

Restate the task in your own words, list the files you will read/write, and call out any assumptions or ambiguities before you start.
Do not proceed if there are any ambiguities - let me clarify them first
If everything is clear - please provide a short plan (3–6 steps) before making changes.
```

### Proceed

```text
Proceed with the plan. Ask for confirmation if you need to deviate.
```

### Session Wrap-up

```text
Summarize what changed, list files modified, note any follow-ups, and update the Decision Log if a decision was made.
Or create/update ADRs if any decision is high-profile enough to warrant that
```

## Render/Apply Contract (Derived From config/)

### Inputs

- `config/mapping.yaml` defines which services render per host.
- `config/network.yaml` defines VLANs, IPs, DNS zones, and records.
- `config/hosts/**/host.yaml` defines host software, users, systemd-networkd templates, and common config.
- `config/services/**` defines service metadata, quadlets, systemd units, configs, and vault-agent templates.
- `config/_templates/**` defines shared Jinja-style templates for network, quadlets, and host/service files.

### Rendered Output Structure

Artifacts are organized under `<output>/rendered/` by apply method:

```text
<output>/rendered/
├── system/                      (atomic file placement)
│   ├── etc/systemd/network/
│   ├── etc/systemd/resolved.conf
│   └── etc/systemd/system/
├── software/                    (execution required)
│   ├── packages.txt
│   ├── downloads/
│   │   └── <id>.yaml
│   ├── builds/
│   │   └── <id>.yaml
│   └── commands/
│       └── <id>.yaml
├── users/                       (execution required)
│   ├── setup-users.sh
│   └── etc/sudoers.d/abhaile
├── services/                    (service-specific artifacts)
│   ├── caddy-dmz/
│   │   ├── etc/containers/systemd/
│   │   └── srv/caddy-dmz/
│   └── vault/
│       ├── etc/containers/systemd/
│       └── srv/vault/
└── <output>/state/manifest.json
```

This organization makes it easy to identify which artifacts require execution vs atomic file placement. The manifest tracks final target paths (e.g., `/etc/systemd/network/10-eth0.network`); the intermediate directory structure is organizational only.

### Required Artifact Types Per Host

- Systemd-networkd artifacts: `.netdev`, `.network`, and resolved config (rendered templates + static files).
- Systemd unit artifacts: `.service`, `.path`, `.timer` (host and service-specific).
- Quadlets for containers/pods: `.container`, `.pod`, `.network`, `.volume`, `.image`, `.build`.
- Service configs: static configs and rendered templates (Caddy, blocky, CoreDNS, ddclient, etc.).
- Vault agent templates: `.ctmpl` rendered outputs with strict perms (no secrets committed).
- Software artifacts: merged `packages.txt` and per-entry `downloads|builds|commands` specs per host.
- DNS zone artifacts: rendered zone files and serial tracking for `coredns-common`.
- Apply manifest: deterministic inventory with hashes for drift detection and safe apply.

### State/Drift Tracking Expectations

- Render outputs are deterministic and include a per-host manifest with SHA256 for each artifact.
- Apply stores last-applied manifest on the host (e.g., `/var/lib/abhaile/state/manifest.json`) and compares for drift.
- Drift detection is read-only by default; apply requires explicit confirmation for destructive changes.
- Any changes outside the render tree are reported but not overwritten unless flagged.
- Rendered output is never committed to the git repo.

### Privilege Boundaries and Safety Checks

- Render runs unprivileged and never touches hosts.
- Apply uses sudo on target hosts; rootful podman for services marked `mode: rootful`.
- Mandatory checks before apply:
  - host identity and target match (`hostname`, SSH host key, and config host name)
  - address and VLAN uniqueness validation from `config/network.yaml`
  - service-to-host mapping validation from `config/mapping.yaml`
  - template rendering success and manifest integrity
- Service restarts are scoped to changed units/quadlets only.
- Secrets never stored in repo; only templates and external runtime materials.
- Reconciliation pattern: desired state in git, drift analysis compares current vs desired, idempotent actions reconcile.

## Phases

### Phase: Foundations

**Status:** ✅ Complete

### Phase: Render Pipeline

**Status:** ✅ Complete

All renderer tasks implemented and tested. Manifest writer simplified to drift-only fields (see Decision Log entry from 2026-03-09).

### Phase: Apply Pipeline

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Apply CLI | Implement `abhaile-apply` to sync `<output>/rendered/` to the host via local copy on target. | Dry-run and apply modes functional for a host. | Manifest writer |
| [ ] | Drift detection | Compare render manifest with host state and report differences. | Apply prints drift summary before changes. | Apply CLI |
| [ ] | Safe systemd reload | Only reload/restart units and quadlets when artifacts changed. | Changed services restart; unchanged services stay running. | Apply CLI |
| [ ] | Host safety gate | Enforce hostname and SSH host key checks before apply. | Apply aborts on mismatch. | Apply CLI |
| [ ] | Rollback strategy | Document and implement minimal rollback (last-applied snapshot). | Previous manifest can be restored safely. | Apply CLI |

#### Session Prompt (Apply CLI)

- Phase/Task: Apply Pipeline / Apply CLI.
- Required inputs: `TODO.md`, `README.md`, `<output>/rendered/manifest.json`, `<output>/state/manifest.json` (last applied).
- Outputs to produce: `abhaile-apply` console entrypoint (`src/abhaile/apply/` module); document host state paths in `README.md` (`/var/lib/abhaile/state/manifest.json`, `/var/lib/abhaile/state/manifest.previous.json`, `/var/lib/abhaile/state/history/`).
- Acceptance: dry-run mode shows planned add/change/remove actions; apply mode copies files atomically to target paths, sets permissions, runs reload_actions, updates state.
- Constraints: apply runs with sudo on target; no secrets written; render/apply boundary enforced; `rendered/` owned by render, `state/` owned by apply.
- Dependencies: Manifest writer.

#### Session Prompt (Drift detection)

- Phase/Task: Apply Pipeline / Drift detection.
- Required inputs: `<output>/rendered/manifest.json` (desired), `<output>/state/manifest.json` (last applied), live filesystem.
- Outputs to produce: drift summary inside `abhaile-apply`; standalone two-manifest comparison in `abhaile-diff`.
- Acceptance: drift summary compares `target_path` + `sha256` and reports added/changed/removed files; prune candidates identified via 3-way comparison (desired vs applied vs live).
- Constraints: read-only by default; destructive actions require explicit confirmation.
- Dependencies: Apply CLI.

#### Session Prompt (Safe systemd reload)

- Phase/Task: Apply Pipeline / Safe systemd reload.
- Required inputs: `<output>/rendered/manifest.json` (`reload_actions` block), drift summary.
- Outputs to produce: reload/restart logic inside `abhaile-apply` (`src/abhaile/apply/` module).
- Acceptance: only changed units/quadlets are restarted; unchanged services remain running; `daemon-reload` runs before unit restarts.
- Constraints: minimize disruption; log each restarted unit.
- Dependencies: Apply CLI.

#### Session Prompt (Host safety gate)

- Phase/Task: Apply Pipeline / Host safety gate.
- Required inputs: `<output>/rendered/manifest.json` (`host` field), live `hostname` on target.
- Outputs to produce: host identity validation logic inside `abhaile-apply` (`src/abhaile/apply/` module).
- Acceptance: apply aborts if manifest `host` does not match live `hostname`.
- Constraints: fail closed; no bypass without explicit flag.
- Dependencies: Apply CLI.

#### Session Prompt (Rollback strategy)

- Phase/Task: Apply Pipeline / Rollback strategy.
- Required inputs: `<output>/state/manifest.previous.json`, `<output>/state/history/`.
- Outputs to produce: rollback subcommand or flag in `abhaile-apply`; document usage in `README.md`.
- Acceptance: previous manifest and rendered artifacts can be re-applied safely; rollback is explicit only.
- Constraints: rollback is explicit; no automatic destructive changes; state history retained for last 10 applies.
- Dependencies: Apply CLI.

### Phase: Secrets

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Secrets policy | Document that secrets live outside the repo; templates only in `config/`. | Policy documented in `README.md` and ADR. | Record key ADRs |
| [ ] | Vault agent integration | Ensure rendered outputs include vault-agent templates and required services. | Vault-agent files render with correct perms. | Service configs renderer |
| [ ] | External key material | Define bootstrap/runtime locations for keys (e.g., `/etc/abhaile/keys`). | Paths documented; apply does not install secrets. | Secrets policy |

#### Session Prompt (Secrets policy)

- Phase/Task: Secrets / Secrets policy.
- Required inputs: `TODO.md`, `README.md`, `docs/adr/` if present.
- Outputs to produce: update `README.md` with secrets policy; ADR in `docs/adr/` for secrets boundary.
- Acceptance: policy states no secrets in repo and template-only rendering.
- Constraints: `config/` remains source of truth.
- Dependencies: Record key ADRs.

#### Session Prompt (Vault agent integration)

- Phase/Task: Secrets / Vault agent integration.
- Required inputs: `config/services/**` (vault-agent templates), `<output>/rendered/` if present.
- Outputs to produce: render-stage updates to include vault-agent templates under `<output>/rendered/services/vault-agent/`.
- Acceptance: vault-agent templates render with correct permissions metadata in manifest.
- Constraints: no secret material rendered.
- Dependencies: Service configs renderer.

#### Session Prompt (External key material)

- Phase/Task: Secrets / External key material.
- Required inputs: `README.md`, `docs/adr/` if present.
- Outputs to produce: document external key paths and bootstrap/runtime expectations in `README.md` and ADR.
- Acceptance: explicit paths and ownership stated (e.g., `/etc/abhaile/keys`); apply does not install secrets.
- Constraints: no secrets in repo.
- Dependencies: Secrets policy.

### Phase: Validation and Testing

**Status:** ✅ Complete

All validation (config/IP/VLAN/mapping), linting (pre-commit), and test suite (160 tests) implemented and passing.

### Phase: Ops Tooling

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Make targets | Add `make render`, `make apply`, `make validate`. | Targets call scripts and return non-zero on failure. | Renderer CLI |
| [ ] | Host inventory view | Provide a command to list services per host from `config/mapping.yaml`. | Output shows host -> services mapping. | Renderer CLI |
| [ ] | Diff tool | Provide `abhaile-diff` to compare any two manifest files. | Diff reports added/changed/removed files with paths and hashes. | Drift detection |

#### Session Prompt (Make targets)

- Phase/Task: Ops Tooling / Make targets.
- Required inputs: `scripts/`, `README.md`.
- Outputs to produce: `Makefile` targets `render`, `apply`, `validate`.
- Acceptance: targets call scripts and return non-zero on failure.
- Constraints: no network access; no secrets.
- Dependencies: Renderer CLI.

#### Session Prompt (Host inventory view)

- Phase/Task: Ops Tooling / Host inventory view.
- Required inputs: `config/mapping.yaml`.
- Outputs to produce: `scripts/inventory` (or similar) that prints host -> services mapping.
- Acceptance: output includes all hosts and mapped services.
- Constraints: read-only; no secrets.
- Dependencies: Renderer CLI.

#### Session Prompt (Diff tool)

- Phase/Task: Ops Tooling / Diff tool.
- Required inputs: any two manifest JSON files (e.g., desired vs applied, applied vs history entry).
- Outputs to produce: `abhaile-diff` console entrypoint in `src/abhaile/apply/` module.
- Acceptance: diff shows added/changed/removed entries with `target_path` and `sha256`; accepts two manifest paths as positional arguments.
- Constraints: read-only; no secrets; no host access required.
- Dependencies: Drift detection.

### Phase: Documentation

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | README refresh | Document render/apply workflow, bootstrap, and safety checks. | `README.md` updated with workflow and examples. | Render/Apply Contract |
| [ ] | Architecture docs | Create `docs/architecture.md` describing pipeline stages. | Document created and referenced from README. | Define repo layout |
| [ ] | ADR updates | Write ADRs for renderer language, drift strategy, secrets, and bootstrap. | ADRs created in `docs/adr/`. | Record key ADRs |

#### Session Prompt (README refresh)

- Phase/Task: Documentation / README refresh.
- Required inputs: `README.md`, `scripts/`, `docs/adr/`.
- Outputs to produce: update `README.md` with render/apply workflow, bootstrap, safety checks, and output paths.
- Acceptance: README matches actual scripts and directories; no secrets documented.
- Constraints: align with `config/` as source of truth.
- Dependencies: Render/Apply Contract.

#### Session Prompt (Architecture docs)

- Phase/Task: Documentation / Architecture docs.
- Required inputs: `README.md`, `scripts/render`, `scripts/apply`.
- Outputs to produce: `docs/architecture.md` describing pipeline stages and artifacts.
- Acceptance: architecture doc references actual render/apply stages and paths.
- Constraints: no secrets.
- Dependencies: Define repo layout.

#### Session Prompt (ADR updates)

- Phase/Task: Documentation / ADR updates.
- Required inputs: `docs/adr/`, `README.md`.
- Outputs to produce: ADRs for renderer language, drift strategy, secrets, bootstrap.
- Acceptance: ADRs numbered and include decisions/alternatives.
- Constraints: no secrets.
- Dependencies: Record key ADRs.

### Phase: Bootstrap

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Curl-bash bootstrap | Provide a `scripts/bootstrap.sh` that installs prerequisites and enrolls host. | `curl \<url\> \| bash` workflow documented and safe. | Apply CLI |
| [ ] | Host enrollment flow | Define steps for host naming, SSH key install, and first apply. | Process documented and tested on a clean host. | Curl-bash bootstrap |
| [ ] | One-time token handling | Require a bootstrap token or SSH key passed via env or prompt. | Bootstrap refuses to run without explicit token. | Curl-bash bootstrap |

#### Session Prompt (Curl-bash bootstrap)

- Phase/Task: Bootstrap / Curl-bash bootstrap.
- Required inputs: `README.md`, `scripts/render`, `scripts/apply`.
- Outputs to produce: `scripts/bootstrap.sh`; update `README.md` with curl-bash usage and safety notes.
- Acceptance: bootstrap installs prerequisites, clones repo, and registers GitOps units; refuses to run without explicit token/key.
- Constraints: no secrets in repo; external key material required; render/apply boundary enforced.
- Dependencies: Apply Pipeline completed.

#### Session Prompt (Host enrollment flow)

- Phase/Task: Bootstrap / Host enrollment flow.
- Required inputs: `README.md`, `scripts/bootstrap.sh`.
- Outputs to produce: documented enrollment steps and first apply process in `README.md`.
- Acceptance: steps cover host naming, SSH key install, and first apply.
- Constraints: no secrets documented.
- Dependencies: Curl-bash bootstrap.

#### Session Prompt (One-time token handling)

- Phase/Task: Bootstrap / One-time token handling.
- Required inputs: `scripts/bootstrap.sh`.
- Outputs to produce: token/key requirement and prompt/env handling in `scripts/bootstrap.sh`.
- Acceptance: bootstrap exits non-zero without explicit token/key.
- Constraints: no secrets stored; token never written to disk.
- Dependencies: Curl-bash bootstrap.
