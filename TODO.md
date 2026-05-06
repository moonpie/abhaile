# TODO: Rebuild Repo Around config/

## Current Canonical Decisions

Read this section first. It is the condensed current-state view for implementers. The historical log below remains the trace record when deeper context is needed.
The durable architectural form of these decisions lives in ADRs 0001 through 0007; use the historical log for implementation and evolution context.

- Authoring model: `config/` is the source of truth. Service-owned systemd units are authored only under `composition.systemd`; `composition.config` is for plain config/env files and directories; authored entry-level `apply` is not part of the current model.
- Render/apply boundary: render is unprivileged, deterministic, and owns ephemeral `<output>/rendered/`; apply is privileged, owns durable `<output>/state/`, performs drift-aware reconciliation, and never mutates the host in dry-run mode.
- Manifest/state model: desired manifest is written to `<output>/rendered/manifest.json`; applied-state history lives under `<output>/state/` with current, previous, and timestamped history entries.
- Runtime execution model: apply behavior is driven by typed owner execution and renderer-internal apply hints, not free-form reload commands; service directories are enforced at apply time; unit enable/start intent is authored in config and enforced by apply.
- Secrets model: runtime secrets are never stored in git or repo-managed render output; Vault Agent renders runtime secrets on-host; any `sops` usage is limited to sealed bootstrap artifacts needed before Vault Agent can take over.
- External material contract: bootstrap token/key inputs and runtime cert/token outputs use explicit host paths and ownership; apply references these paths and wiring but does not install secret payloads.
- Vault Agent render boundary: render emits only non-secret Vault control-plane artifacts (template sources, base agent config, and managed runtime output parent directories with owner/group/mode metadata); resolved secret outputs remain host-only and never appear under `<output>/rendered/`.
- Runner boundary: commit selection, scheduled reconciliation, locking, and rollback-to-last-known-good belong to the GitOps runner layer around `abhaile-render` and `abhaile-apply`, not inside `src/abhaile/` apply logic.
- Codebase/layout: installable Python code lives under `src/abhaile/`; apply/diff are Python entrypoints; `scripts/` is reserved for wrappers/orchestration; `paths.ini` is repo-root configuration.
- Historical note: when older entries conflict, prefer newer dated decisions and any item explicitly marked canonical or superseding.

## Historical Decision Log

### Normalization status (2026-04-22)

- Canonical apply-runtime model: see ADR 0004 and ADR 0005 for the current durable statement of apply execution and service authoring behavior.
- Any `scripts/lib/python/...` path references in older decisions are historical (pre-`src/abhaile/` migration) and should be interpreted as legacy path notation.

#### ADR-covered decisions

- The current durable form of the render/apply boundary, manifest/state ownership model, runner boundary, apply execution model, service authoring model, and secrets model now lives in ADRs 0001 through 0007.
- Historical decisions from `2026-03-14` through `2026-05-04` that established those architectural boundaries have been promoted into ADRs and removed from this log to avoid duplication.
- See:
- ADR 0001: Output Root and Environment Paths
- ADR 0002: Hash-based Drift Detection and State Model
- ADR 0003: GitOps Runner Responsibility Boundary
- ADR 0004: Apply Execution Model
- ADR 0005: Service Authoring Model
- ADR 0006: Secrets Model and Bootstrap Artifacts
- ADR 0007: SOPS Bootstrap Policy and Layout

#### How to read the remaining log

- Tags are search aids only; they are not exclusive categories.
- A single decision may matter to multiple concerns such as rendering, apply, validation, ops, and repository layout.
- Do not skip an entry just because one tag or keyword looks unrelated to your immediate task.

1. Decision: `apply_todo.md` has been deleted (2026-05-04) now that all apply pipeline work is complete; it was a task tracker with no residual operator value. `actions_map.md` is retained as the authoritative implemented-behavior reference (no future/gap sections). Service restart-hint behavior and audit details live in `docs/APPLY.md` as the operator-facing source.
   Date: 2026-04-22 (updated 2026-05-04)
   Tags: docs, apply, operations, maintenance
   Rationale: Avoid keeping stale "future work" text after implementation lands; separate historical decision tracking (`TODO.md`) from operational behavior docs (`docs/APPLY.md`) and execution mapping (`actions_map.md`). Task trackers are deleted once complete to avoid confusion with active work.
   Scope: `actions_map.md`, `docs/APPLY.md`.
   Confirmed by: implementation

1. Decision: Renamed internal package path from `src/abhaile/types/` to `src/abhaile/models/` to avoid collision with Python stdlib module `types` during direct file execution patterns (e.g., `python src/abhaile/cli.py ...`).
   Date: 2026-03-13
   Tags: codebase-layout, python, imports
   Rationale: `src` layout made direct execution place `src/abhaile` first on `sys.path`, allowing `types` import shadowing; renaming eliminates the collision class without runtime `sys.path` mutation.
   Scope: `src/abhaile/models/` module path, imports (`abhaile.models.config`), and package move from `types` -> `models`.
   Confirmed by: user

1. Decision: Python source layout uses `src/abhaile/` as the canonical package path; apply/diff/render logic lives under `src/abhaile/` and CLI entrypoints are registered from that source tree.
   Date: 2026-03-13
   Tags: codebase-layout, python, cli
   Rationale: Standard Python `src/` layout reduces accidental local import masking, keeps packaging/tooling conventions clear, and separates installable code from repo assets.
   Scope: Package/module references in TODO/docs (`abhaile/...` -> `src/abhaile/...`) and upcoming source migration.
   Confirmed by: user

1. Decision: Tooling path configuration file is repo-root `paths.ini` (not `scripts/paths.ini`); `scripts/` is reserved for executable shell utilities/wrappers.
   Date: 2026-03-13
   Tags: codebase-layout, tooling, configuration
   Rationale: `paths.ini` is cross-tool project configuration used by Python and shell code, so it belongs with root project config files rather than inside an executable scripts directory.
   Scope: TODO/docs references to path config location and upcoming file move.
   Confirmed by: user

1. Decision: Apply and diff are Python console entrypoints (`abhaile-apply`, `abhaile-diff`) registered in `pyproject.toml`, with orchestration in `src/abhaile/cli/` and implementation split across `src/abhaile/plan/`, `src/abhaile/apply/`, and `src/abhaile/state/`; `scripts/` retains shell utilities/wrappers (e.g., gitops-runner wrapper); no shell scripts for apply or diff business logic.
   Date: 2026-03-13
   Tags: cli, python, apply, diff, tooling
   Rationale: Python gives testability, structured error handling, and reuse of existing `src/abhaile/` modules (manifest, validation, types); shell adds no value over `subprocess` for the OS operations apply triggers; aligning with `abhaile-render` pattern keeps CLI consistent.
   Scope: `src/abhaile/cli/`, `src/abhaile/plan/`, `src/abhaile/apply/`, `src/abhaile/state/`, `pyproject.toml` entrypoints, `abhaile-apply` and `abhaile-diff` CLI commands; all TODO Apply Pipeline and Ops Tooling session prompts updated to reflect entrypoint names.
   Confirmed by: user

1. Decision: Removed backward compatibility fallback in DNS serial validation - config_root parameter is now required (Path, not Optional[Path]); legacy synthetic hash format was deleted.
   Date: 2026-03-09
   Tags: dns, validation, rendering
   Rationale: Legacy fallback caused maintenance burden, inconsistent behavior between tests with/without config_root, and was never used in production (CLI always passes config_root); making config_root required simplifies the codebase and ensures validation always uses the exact template-rendered zone format.
   Scope: `abhaile/dns/serial_validator.py` (removed \_build_legacy_zone_content_for_hash, made config_root required in validate_zone_serial and validate_zone_serial_collect), `abhaile/validation/dns.py` (made config_root required in validate_dns_serials), test fixtures updated to provide minimal config_root with coredns-common service template.
   Confirmed by: user

1. Decision: DNS serial validation computes `serial.content_hash` from the same zone template rendering path as DNS renderer (provider `dns.zone_files` template resolution) when config root is available; this avoids false serial drift caused by legacy synthetic hash formatting differences.
   Date: 2026-03-09
   Tags: dns, validation, rendering
   Rationale: Serial validation must reflect actual rendered zone content; hashing a different canonical string than renderer output caused spurious prompts to update `serial.date`/`serial.counter`/`serial.content_hash` even when records were unchanged.
   Scope: `abhaile/dns/serial_validator.py`, `abhaile/validation/dns.py`, CLI DNS validation call path, DNS integration/unit tests.
   Confirmed by: user

1. Decision: Align user management schema with sysusers by renaming `description` to `gecos`, adding a boolean `system` flag on users, and validating uid/gid conflicts across host include chains.
   Date: 2026-03-06
   Tags: users, schema, validation
   Rationale: Sysusers uses the GECOS field name and benefits from explicit system/login user intent; static ids are preferred, so validating duplicate uid/gid values avoids ambiguous user/group definitions across includes.
   Scope: schemas/host.schema.json, config/hosts/\*/host.yaml, abhaile/validation/users.py, abhaile/cli.py.
   Confirmed by: user

1. Decision: User management merges across host composition includes by name; scalar fields must match if redefined while list fields are unioned; uid/gid conflicts across different names are validation errors.
   Date: 2026-03-06
   Tags: users, merge-semantics, validation
   Rationale: Reduce duplication (common defaults stay centralized) while preventing ambiguous overrides and id collisions.
   Scope: README.md (documentation), schemas/host.schema.json (description), users renderer and validation behavior.
   Confirmed by: user

1. Decision: User management renderer outputs systemd-sysusers config plus sudoers drop-in instead of a monolithic setup script, keeping drift/apply declarative and idempotent.
   Date: 2026-03-06
   Tags: users, rendering, apply
   Rationale: Sysusers provides native, declarative user/group reconciliation and minimizes imperative scripting while aligning with drift-driven apply.
   Scope: abhaile/renderers/users.py, CLI render pipeline, users render outputs under rendered/users/etc/.
   Confirmed by: user

1. Decision: Software renderer comment style and import conventions match project patterns: concise docstrings (no verbose "Output contract" sections), direct module imports in CLI (no package-level exports), simplified function documentation matching other renderers.
   Date: 2026-03-05
   Tags: software, code-style, python
   Rationale: Consistency with existing renderer modules (host.py, services.py, networkd.py) improves code readability and maintainability; direct imports from specific modules are more explicit than package-level exports; concise docstrings reduce noise without losing essential information.
   Scope: `abhaile/renderers/software.py` (docstring simplification), `tests/unit/python/renderers/test_software.py` (import fix from `abhaile.renderers` to `abhaile.renderers.software`).
   Confirmed by: user (after reviewing inconsistencies with project conventions)

1. Decision: Software render output uses mixed granularity: a single merged `packages.txt` artifact for apt-managed packages, and one rendered spec file per entry for `downloads`, `builds`, and `commands`; duplicate software ids across host include chains are treated as render errors; host software spec files include explicit `id` and are schema-validated.
   Date: 2026-03-05
   Tags: software, rendering, schema, apply
   Rationale: apt handles idempotency for already-installed packages, so a single package list remains safe and simple; entry-level files for downloads/builds/commands preserve declarative drift granularity so apply can target only added/changed specs; duplicate ids are unexpected and should fail fast to avoid ambiguous behavior; explicit ids and schema checks improve determinism and config safety.
   Scope: `abhaile/renderers/software.py`, CLI integration, `schemas/software-action.schema.json`, host software spec YAML files, pre-commit schema hooks.
   Confirmed by: user

1. Decision: DNS reverse zones automatically generate PTR records from A/AAAA records marked with `ptr: true` in network.yaml; PTR records have reverse DNS notation name (final octets) and FQDN rdata with trailing dot; reverse zone identification uses smart IP-to-zone matching (172.20.20.10 belongs to 20.20.172.in-addr.arpa.); PTR records rendered inline during zone file generation; DNS serial validation compares rendered zone hash against network.yaml content_hash, computing expected serial from git HEAD (last commit) serial vs today's date, incrementing counter if same day or resetting to 00 if new day; validation reports only fields that differ between expected and current workspace values (serial.date, serial.counter, serial.content_hash).
   Date: 2026-02-08
   Tags: dns, rendering, validation, network
   Rationale: PTR records enable reverse DNS lookups (IP → hostname) which are essential for service identification, logging correlation, and security policies; automatic generation from forward records (marked with ptr: true) maintains single source of truth and prevents manual sync errors; FQDN format with trailing dot ensures correct DNS resolution; smart zone matching handles /24 networks correctly (comparing first 3 octets); git HEAD comparison for serial increment prevents counter exhaustion during development iterations—serial only increments once per commit, not per render; differential reporting (only changed fields) reduces noise and makes fixes clearer; expected serial computation uses git HEAD date/counter (not workspace) to determine increment logic, ensuring predictable behavior across development cycles.
   Scope: DNS renderer (scripts/lib/python/renderers/dns.py): added \_ip_to_reverse_dns() to convert IPs to reverse DNS notation, \_collect_ptr_records_for_reverse_zone() to scan forward zones for ptr: true A records and generate PTR records for matching reverse zones, updated \_collect_zone_records() to invoke PTR collection for reverse zones; refactored \_validate_zone_serial() to use git HEAD for increment logic (not workspace), compute expected hash with expected serial in SOA, compare expected vs current workspace values, and report only differences; PTR records generated for 2 reverse zones (20.20.172.in-addr.arpa. with 11 PTR records, 100.20.172.in-addr.arpa. with 2 PTR records); validation output format changed from "Committed serial: X, Expected serial: Y" to showing only fields needing updates.
   Confirmed by: user

1. Decision: DNS zone renderer with git-aware serial validation; zones rendered to `out/rendered/services/<providing-service>/etc/coredns/zones/<zone>.zone` (to deployed services like coredns-clean/coredns-filtered, not base service coredns-common) in BIND RFC 1035 format; rendering is per-host (only services on current host receive zones), matching ingress pattern; serial tracking uses date/counter/content_hash (YYYYMMDDCC format); validation compares rendered zone hash against stored hash; if mismatch, fails with expected serial values; counter increments relative to git HEAD (last commit), not working tree, preventing unnecessary increments during iterative development; validation collects all zone errors before failing for better UX; only internal zones rendered (external zones like desec.io skipped); records ordered deterministically (hosts in definition order, then services in definition order, preserving per-entity record order); zone records aggregated from ALL services in mapping.yaml (for cross-host service discovery) but zones only rendered to services on current host; render_dns() accepts host_services (current host's services) and all_services (for record aggregation), resolves composition.include chains to detect dns.zone_files inheritance, and renders each zone to services on current host that provide it.
   Date: 2026-02-08
   Tags: dns, rendering, validation, services
   Rationale: DNS zones need deterministic rendering with change detection; serial tracking prevents stale zone propagation; git-aware increment logic prevents exhausting counter space (00-99) during development iterations by only incrementing once per commit; collecting all errors before failing allows user to update all zones in single edit; BIND format required for CoreDNS zone plugin; deterministic ordering ensures cross-host consistency; zones must render to deployed services (coredns-clean on deimos, coredns-filtered on phobos) not base service (coredns-common) because only deployed services appear in mapping.yaml and receive quadlets/systemd units—matches ingress pattern where caddy-dmz/caddy-internal aggregate from other services; per-host rendering allows future divergence in zone configurations between coredns-clean and coredns-filtered (e.g., different filtering rules per host) while maintaining cross-host record aggregation for service discovery; eliminates special-case "render once" logic that would break host-specific rendering.
   Scope: DNS renderer (scripts/lib/python/renderers/dns.py: render_dns with host_services/all_services parameters, resolve_service_composition helper, provider_to_services map building scoped to host_services, \_validate_zone_serial, \_validate_zone_serial_collect, \_collect_zone_records aggregates from network which contains all hosts/services, \_render_zone_file, \_compute_content_hash, \_get_git_head_serial); DNS validation (scripts/lib/python/validation/dns.py: validate_dns_serials) integrated into load_and_validate() for fail-fast; scripts/render integration calls render_dns per-host with host_services.get(host, []) and all_services; 27 unit tests + 7 integration tests (all 160 tests passing); renders zone files for 4 internal zones (svc.abhaile.home.arpa, abhaile.home.arpa, 20.20.172.in-addr.arpa, 100.20.172.in-addr.arpa) to coredns-clean (deimos) and coredns-filtered (phobos) directories separately per host.
   Confirmed by: user

1. Decision: All renderers (vault-agent, ingress, quadlets) recursively follow `composition.include` to collect their respective content from included services; includes are processed depth-first (includes before direct definitions); cycle detection with clear error messages; services rendered in mapping.yaml order with includes expanded inline; visited tracking prevents redundant processing; each renderer has dedicated resolver functions (\_collect_service_vault_templates, \_collect_service_ingress_blocks, \_resolve_pod_definition, \_resolve_container_definition) that handle include traversal.
   Date: 2026-02-07
   Tags: rendering, services, includes, quadlets, ingress, vault-agent
   Rationale: Include mechanism should work consistently across all composition content types (config, vault_agent, ingress, pod, container), not just config; depth-first traversal ensures included content appears before direct definitions, allowing overrides; cycle detection prevents infinite recursion; visited tracking maintains efficiency; this enables base/common services (like coredns-omada) to define vault templates, ingress blocks, or container definitions that are inherited by services that include them (like coredns-filtered, coredns-clean).
   Scope: All three renderers updated with recursive include resolution (vault_templates.py: \_collect_service_vault_templates, ingress.py: \_collect_service_ingress_blocks, quadlets.py: \_resolve_pod_definition/\_resolve_container_definition); 24 existing unit tests still pass; 20 existing integration tests still pass; 5 new integration tests added (test_composition_includes.py) to explicitly verify include support; verified with coredns-omada vault template now appearing in both phobos (via coredns-filtered) and deimos (via coredns-clean) renders.
   Confirmed by: user

1. Decision: Vault-agent templates renderer aggregates vault-agent templates from services running on the SAME HOST (not cross-host like ingress) because vault-agent writes to local filesystem at /agent/templates/ on each host; template `source` paths are derived by replacing `<service>/templates/` with `/agent/templates/`, and template files are copied to `/srv/vault/agent/templates/` with the same replacement; template `dest` paths are rendered as `/agent/out/<out>`; base vault-agent service defines vault_agent.base with source template and variables; template variables support network placeholders (%%network.services.vault.address | strip_cidr%%) with jinja2 filter syntax; aggregated template metadata rendered into base config (config.hcl.j2) with deterministic ordering by mapping.yaml order (and within a service, in service.yaml order).
   Date: 2026-02-07
   Tags: vault-agent, rendering, services, secrets
   Rationale: Vault-agent runs unprivileged on each host and writes templates to local filesystem, so must only aggregate from co-located services; the templates/out volumes require host-path placement under `/srv/vault/agent/{templates,out}` while config references mounted `/agent/{templates,out}` paths; network placeholder resolution with filter support handles complex configuration like CIDR-stripped addresses; mapping order preserves intent and is deterministic.
   Scope: Vault templates renderer (scripts/lib/python/renderers/vault_templates.py) with integration into render pipeline (scripts/render); 13 unit tests + 3 integration tests all passing; verified with actual config for phobos (authelia, caddy-dmz, ddclient templates) and deimos (vault-agent only).
   Confirmed by: user

1. Decision: Ingress renderer aggregates Caddy configuration blocks from ALL services in mapping (across all hosts) into base services (caddy-dmz, caddy-internal) that are running on the CURRENT HOST ONLY; blocks appended in mapping.yaml order (and within a service, in service.yaml order); source paths in service.yaml may include service-name prefix (e.g., "caddy-dmz/config/Caddyfile") which renderer strips; aggregated content marked with comment separators and per-service headers.
   Date: 2026-02-07
   Tags: ingress, rendering, services, caddy
   Rationale: Centralized reverse proxies need configuration from all services regardless of host placement, but the base Caddyfile should only be rendered on the host where the reverse proxy service is deployed; mapping order preserves intent and enables logical grouping; service-prefix handling maintains compatibility with existing config path patterns; comment separators provide clear visual separation in aggregated Caddyfiles.
   Scope: Ingress renderer (scripts/lib/python/renderers/ingress.py) with integration into render pipeline; aggregates `ingress.{dmz|internal}.blocks` from all services into services defining `ingress.{dmz|internal}.base` (scoped to current host); 11 unit tests + 3 integration tests.
   Confirmed by: user

1. Decision: Quadlets renderer (pods) extends container renderer to handle multi-container pods with `-app` suffix naming convention (pod: \<service>-app.pod, containers: \<service>-app-\<container>.container, volumes: \<service>-app-\<container>-\<volume>.volume); container definitions extracted from `containers[].container` key if present; shared volumes across pod containers rendered once and reused; network quadlets generated at pod level for ipvlan-l2 mode.
   Date: 2026-02-06
   Tags: quadlets, rendering, pods, services
   Rationale: `-app` suffix clearly distinguishes pod-related artifacts from standalone containers; container key extraction supports existing service.yaml structure (authelia pattern); shared volume reuse prevents duplicate host path errors when multiple containers mount same volume; leveraging existing container logic maximizes code reuse while supporting pod-specific features.
   Scope: Pod rendering in quadlets renderer (\_render_pod_quadlets, \_render_named_volumes_for_pod_container); tested with authelia service (2 containers: authelia + redis, shared host-certs volume); 6 new unit tests + 1 integration test.
   Confirmed by: user

1. Decision: Quadlets renderer (containers) generates output to well-known paths per user (rootful: /etc/containers/systemd/, rootless: /home/\<user>/.config/containers/systemd/); shared volumes render to \_shared subdirectory with non-prefixed names; network quadlets deduplicated per VLAN and rendered to podman-networks/ (rootful only); volume_lines in container templates include both named_volumes and mounted_files; Jinja2 trim_blocks/lstrip_blocks prevent blank lines from template control tags.
   Date: 2026-02-06
   Tags: quadlets, rendering, containers, network
   Rationale: Well-known paths align with systemd/podman quadlet conventions; shared volume deduplication reduces redundancy; network quadlet deduplication avoids duplicates when multiple services use same VLAN; whitespace control ensures clean output formatting without empty lines from templating.
   Scope: Quadlets renderer (scripts/lib/python/renderers/quadlets.py) and integration into render pipeline (scripts/render).
   Confirmed by: user

1. Decision: Service config rendering resolves composition includes first (depth-first), then renders the service's own config entries to allow overrides by later entries; cycles are an error.
   Date: 2026-02-04
   Tags: services, rendering, includes
   Rationale: Ensures shared config from included services is applied before service-specific overrides; avoids silent infinite recursion.
   Scope: Service configs renderer include handling.
   Confirmed by: assistant

1. Decision: Resolve systemd-networkd drop-in interface names by parsing the base file's [Match] Name=, and allow any \*.d drop-in directory (not just .network.d).
   Date: 2026-02-02
   Tags: network, systemd-networkd, rendering, validation
   Rationale: Avoids fragile filename parsing and supports all systemd-networkd drop-in types; ensures base file exists and provides authoritative interface name.
   Scope: Networking renderer drop-in selection and validation logic.
   Confirmed by: user

1. Decision: Centralize tooling paths in repo-root `paths.ini` for consistent path resolution.
   Date: 2026-02-01
   Tags: tooling, configuration, codebase-layout
   Rationale: Single source of truth for defaults across tooling in any language.
   Scope: root-level project config and tooling path resolution.
   Confirmed by: user

1. Decision: Suggestions and alternatives are allowed, but must be confirmed before deviating from the task prompt.
   Date: 2025-03-08
   Tags: workflow, collaboration, prompts
   Rationale: Encourage improvements while keeping scope controlled.
   Scope: Task execution prompts and agent behavior.
   Confirmed by: user

1. Decision: Use `scripts/` directory instead of `tools/` for render/apply pipeline.
   Date: 2026-01-31
   Tags: codebase-layout, tooling
   Rationale: Aligns with common convention; `scripts/` is clearer for operational tooling.
   Scope: Repository layout and documentation.
   Confirmed by: task requirements (Foundations phase)

1. Decision: Render scope is single-host or `--all` (no partial host lists).
   Date: 2026-01-31
   Tags: render, cli, workflow
   Rationale: Simplifies render logic and state tracking; multi-host validation is only for pre-commit checks.
   Scope: Render CLI and workstation/CI workflows.
   Confirmed by: user

1. Decision: Apply is always single-host; workstation/CI uses `--dry-run` mode for drift analysis.
   Date: 2026-01-31
   Tags: apply, cli, workflow, safety
   Rationale: Simplifies apply atomicity and safety gates; no need for multi-host apply orchestration.
   Scope: Apply CLI and workstation/CI workflows.
   Confirmed by: user

1. Decision: Define config schema using JSON Schema (draft-07) with `check-jsonschema` pre-commit hooks.
   Date: 2026-02-01
   Tags: schema, validation, tooling
   Rationale: Pre-commit validation of mapping/network/service YAML files catches structural errors early; JSON Schema is well-supported and allows template placeholders.
   Scope: Config validation (mapping.schema.json, network.schema.json, service.schema.json in schemas/).
   Confirmed by: user (via Foundations/Define config schema task)

1. Decision: Adopt explicit host.yaml files with schema validation for host configuration.
   Date: 2026-02-01
   Tags: hosts, schema, configuration
   Rationale: Centralizes host-specific configuration in a single declarative file (matching service.yaml pattern); enables schema validation via pre-commit; improves discoverability and reduces cognitive load vs. scattered implicit directory structure. Composition uses additive inheritance via `include: common` with no deletion capability.
   Scope: Host configuration structure (config/hosts/\<host>/host.yaml and host.schema.json).
   Confirmed by: user (via implementation review)

## Routine Prompts

### Session Preface

#### Context Preamble

```text
You are my coding buddy for this repo. Follow `.github/copilot-instructions.md`.
Before changing anything, read the most relevant context in this order:
1. `TODO.md`:
   - `Current Canonical Decisions`
   - the specific phase/task you are working on
   - any tagged historical decisions relevant to the task
2. ADRs in `docs/adr/` that are relevant to the task
3. `README.md` and any task-specific operational docs (for example `docs/APPLY.md`, `docs/TESTING.md`) if relevant
4. The specific config or source files you need for the task

Work only on the task below.
Be explicit about files you read/write and keep changes minimal.
Suggest alternatives when you see them, but ask for confirmation before deviating.
Treat ADRs as the durable source for architectural decisions.
Use the Decision Log in `TODO.md` only for implementation/evolution decisions that are not ADR-worthy.
If you make or confirm a durable architectural decision, create or update an ADR instead of duplicating that decision in the historical log.

Restate the task in your own words, list the files you will read/write, and call out any assumptions or ambiguities before you start.
Do not proceed if there are material ambiguities; let me clarify them first.
If everything is clear - please provide a short plan (3–6 steps) before making changes.

When updating `TODO.md`:
- keep `Current Canonical Decisions` aligned with the current ADR-backed truth
- keep the historical log chronological
- add `Tags:` to any new historical decision entries
- do not re-add detailed ADR-covered architecture back into the historical log

Here is the task:
<Prompt>
```

### Proceed

```text
Proceed with the plan. Ask for confirmation if you need to deviate.
```

### Session Wrap-up

```text
Summarize what changed, list files modified, note any follow-ups, and state whether any decisions were recorded.
If you made an implementation/evolution decision that is not ADR-worthy, update the historical Decision Log in `TODO.md` with date, tags, rationale, scope, and confirmation source.
If you made or refined a durable architectural decision, create or update the relevant ADR and update `Current Canonical Decisions` in `TODO.md` if needed.
```

## Render/Apply Contract (Derived From config/)

### Inputs

- `config/mapping.yaml` defines which services render per host.
- `config/network.yaml` defines VLANs, IPs, DNS zones, and records.
- `config/hosts/**/host.yaml` defines host software, users, systemd-networkd templates, and common config.
- `config/services/**` defines service metadata, quadlets, systemd units, configs, and vault-agent templates.
- `config/_templates/**` defines shared Jinja-style templates for network, quadlets, and host/service files.

### Service Authoring Semantics

- `composition.systemd` is the authored source of truth for service-owned systemd units and their `enable`/`start` intent.
- `composition.config` is limited to plain config/env files and directories; it is not a second place to author systemd lifecycle behavior.
- `composition.vault_agent` defines Vault Agent control-plane inputs such as template sources, output names, and non-secret agent config inputs.
- Pod/container/quadlet sections define runtime composition; apply behavior is derived from these sections and renderer-internal hints, not ad hoc per-entry imperative commands.

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
└── manifest.json
```

This organization makes it easy to identify which artifacts require execution vs atomic file placement. The manifest tracks final target paths (e.g., `/etc/systemd/network/10-eth0.network`); the intermediate directory structure is organizational only. `<output>/rendered/` is ephemeral and is wiped/rebuilt by render; `<output>/state/` is durable and owned by apply.

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
- Commit-aware rollback is not part of render/apply itself; it belongs to the GitOps runner layer that manages repo revision selection and retry.

### Privilege Boundaries and Safety Checks

- Render runs unprivileged and never touches hosts.
- Apply uses sudo on target hosts; rootful podman for services marked `mode: rootful`.
- Mandatory checks before apply:
  - host identity and target match (`hostname` and config host name)
  - address and VLAN uniqueness validation from `config/network.yaml`
  - service-to-host mapping validation from `config/mapping.yaml`
  - template rendering success and manifest integrity
- Service restarts are scoped to changed units/quadlets only.
- Secrets never stored in repo as plaintext; runtime secrets are Vault-managed on-host, while any `sops` usage is limited to sealed bootstrap artifacts needed before Vault Agent can take over.
- Reconciliation pattern: desired state in git, drift analysis compares current vs desired, idempotent actions reconcile.

## Phases

### Phase: Foundations

**Status:** ✅ Complete

### Phase: Render Pipeline

**Status:** ✅ Complete

### Phase: Apply Pipeline

**Status:** ✅ Complete

### Phase: Secrets

**Status:** ✅ Complete

### Phase: GitOps Runner

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Runner wrapper | Provide a runner under `scripts/` that owns `git fetch/pull`, commit selection, and invocation of `abhaile-render` + `abhaile-apply` for the local host. | Runner exits non-zero on unrecoverable failure and logs each pipeline step clearly. | Apply Pipeline |
| [ ] | Last-successful commit tracking | Persist the last successfully applied commit reference per host. | Runner records the commit SHA only after render+apply succeed for that host. | Runner wrapper |
| [ ] | Automatic rollback retry | On failure at a newer commit, checkout the previously successful commit and re-run render+apply. | Failed update attempts fall back to last-known-good commit and restore service successfully or fail loudly with clear state. | Last-successful commit tracking |
| [ ] | Systemd service and timer | Install a systemd service/timer pair that executes the runner on a schedule. | Units install cleanly, timer triggers as expected, and logs are visible in journald. | Runner wrapper |
| [ ] | Runner state and locking | Prevent overlapping runs and document runner-owned state paths. | Concurrent timer/manual invocations are serialized and state paths are documented. | Systemd service and timer |

#### Session Prompt (Runner wrapper)

- Phase/Task: GitOps Runner / Runner wrapper.
- Required inputs: `TODO.md`, `README.md`, `Makefile`, `paths.ini`, `scripts/`, `src/abhaile/cli/`.
- Outputs to produce: executable runner wrapper in `scripts/` that fetches git state, detects whether a newer commit exists, and invokes `abhaile-render` + `abhaile-apply` for the local host.
- Required decisions to capture:
- Define whether the runner tracks "latest fetched commit", "checked out commit", and "last successful commit" separately.
- Define the local-host detection rule and how the runner maps the current machine to a host in `config/mapping.yaml`.
- Define behavior when the working tree is dirty, the repo cannot fast-forward, or the configured host is absent from repo config.
- Acceptance: runner is host-oriented, logs fetch/select/render/apply steps clearly, skips when already at the selected commit, and exits non-zero on unrecoverable failure.
- Constraints: orchestration only; render/apply business logic remains in `src/abhaile/`; no secrets stored in repo; do not hide git checkout behavior inside apply.
- Dependencies: Apply Pipeline.

#### Session Prompt (Last-successful commit tracking)

- Phase/Task: GitOps Runner / Last-successful commit tracking.
- Required inputs: runner wrapper, local hostname, writable runner state directory.
- Outputs to produce: runner-owned state file for the last successful commit (for example under `/var/lib/abhaile/runner/`).
- Required decisions to capture:
- Define whether state is one file per host or a single structured state file.
- Define exactly when a commit becomes "successful" if render succeeded but apply was a no-op, partially changed state, or required prune confirmation.
- Define whether the stored state also records timestamp, repo remote, branch, or manifest path for audit/debugging.
- Acceptance: after a fully successful host run, the exact applied commit SHA is stored durably and is unambiguous relative to repo HEAD and rollback target.
- Constraints: update state only after full success; host-scoped state; no ambiguity between current HEAD and last-known-good commit.
- Dependencies: Runner wrapper.

#### Session Prompt (Automatic rollback retry)

- Phase/Task: GitOps Runner / Automatic rollback retry.
- Required inputs: last-successful commit state, git working tree, runner wrapper.
- Outputs to produce: runner logic that, on failure at a newer commit, checks out the last successful commit and re-runs render+apply.
- Required decisions to capture:
- Define which failures trigger rollback retry versus immediate hard failure (for example render/apply failure at new commit vs git fetch failure vs dirty worktree).
- Define whether rollback is attempted once only and how the runner returns the repo to the intended branch afterwards.
- Define operator-visible state/logging so it is obvious the host is running last-known-good rather than latest.
- Acceptance: failed new commits do not strand the host if the last-known-good commit is available; rollback attempt is explicit in logs; runner fails loudly if rollback also fails.
- Constraints: rollback is commit-based, not manifest-based; do not embed checkout/retry behavior in `src/abhaile/`; avoid infinite retry loops.
- Dependencies: Last-successful commit tracking.

#### Session Prompt (Systemd service and timer)

- Phase/Task: GitOps Runner / Systemd service and timer.
- Required inputs: runner wrapper, bootstrap docs, target unit locations.
- Outputs to produce: systemd `.service` and `.timer` units plus installation docs.
- Required decisions to capture:
- Define service user, working directory, environment file usage, and state directory ownership.
- Define timer cadence and whether missed runs should catch up on boot.
- Define the relationship between unit-level overlap protection and runner-level locking.
- Acceptance: timer triggers runner periodically, service is oneshot/non-overlapping, journald captures fetch/render/apply/rollback output, and unit installation is reproducible.
- Constraints: systemd owns scheduling; no ad hoc cron; runner must be safe to invoke manually outside the timer.
- Dependencies: Runner wrapper.

#### Session Prompt (Runner state and locking)

- Phase/Task: GitOps Runner / Runner state and locking.
- Required inputs: runner wrapper, systemd execution model, documented state directories.
- Outputs to produce: locking strategy and documented runner-owned state paths.
- Required decisions to capture:
- Define whether locking is implemented in systemd, shell/Python runner code, or both.
- Define stale-lock recovery behavior after crash/reboot.
- Define the full runner-owned state layout and keep it separate from apply state unless there is a deliberate reason to merge them.
- Acceptance: overlapping runs are prevented for timer and manual invocations; stale locks do not wedge the host permanently; docs explain where commit, lock, and runner status files live.
- Constraints: keep state separate from render/apply manifests unless there is a strong reason to combine them.
- Dependencies: Systemd service and timer.

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
| [ ] | Sealed bootstrap artifact tooling | Provide a supported way to create, edit, and rotate `sops`-encrypted bootstrap artifacts without exposing plaintext in git. | Operator workflow for sealed artifact creation/edit/rotation is documented and implemented via canonical tooling. | SOPS bootstrap policy and layout |

#### Session Prompt (Make targets)

- Phase/Task: Ops Tooling / Make targets.
- Required inputs: `Makefile`, available CLI entrypoints, `README.md`.
- Outputs to produce: `Makefile` targets `render`, `apply`, `validate`.
- Required decisions to capture:
- Define default arguments for each target and whether host/output paths must be passed through variables.
- Define whether `make` calls Python entrypoints directly or uses wrapper scripts.
- Acceptance: targets call the canonical entrypoints, pass through required args predictably, and return non-zero on failure.
- Constraints: no network access; no secrets; avoid duplicate business logic in `Makefile`.
- Dependencies: Renderer CLI.

#### Session Prompt (Host inventory view)

- Phase/Task: Ops Tooling / Host inventory view.
- Required inputs: `config/mapping.yaml`.
- Outputs to produce: `scripts/inventory` (or similar) that prints host -> services mapping.
- Required decisions to capture:
- Define whether the tool is human-readable only or also supports a machine-readable format.
- Define whether it validates that mapped services exist in `config/services/`.
- Acceptance: output includes all hosts and mapped services in deterministic order and fails clearly if mapping references missing services.
- Constraints: read-only; no secrets; do not duplicate full validation logic already owned elsewhere.
- Dependencies: Renderer CLI.

#### Session Prompt (Diff tool)

- Phase/Task: Ops Tooling / Diff tool.
- Required inputs: any two manifest JSON files (e.g., desired vs applied, applied vs history entry).
- Outputs to produce: `abhaile-diff` console entrypoint in `src/abhaile/cli/diff.py` with comparison logic in `src/abhaile/plan/`.
- Required decisions to capture:
- Define manifest identity rules: compare by `target_path`, and specify how metadata-only changes are reported.
- Define exit-code behavior for "differences found" versus "invalid manifest" versus "no diff".
- Acceptance: diff shows added/changed/removed entries with `target_path` and `sha256`, accepts two manifest paths as positional arguments, and has predictable exit codes for automation.
- Constraints: read-only; no secrets; no host access required.
- Dependencies: Drift detection.

#### Session Prompt (Sealed bootstrap artifact tooling)

- Phase/Task: Ops Tooling / Sealed bootstrap artifact tooling.
- Required inputs: `README.md`, secrets policy/ADR decisions, chosen `sops` artifact layout, available CLI/tooling conventions.
- Outputs to produce: canonical operator tooling or wrappers for creating, editing, re-encrypting, and validating sealed bootstrap artifacts; update operator docs in `README.md`.
- Required decisions to capture:
- Define whether operators interact with `sops` directly or through repo-provided wrappers/Make targets.
- Define how new bootstrap artifacts are initialized and how recipient changes or key rotation are applied safely.
- Define validation checks that ensure committed bootstrap artifacts remain encrypted and structurally valid.
- Acceptance: there is one documented workflow for sealed artifact lifecycle operations, it avoids committing plaintext by accident, and it matches the repo's chosen `sops` layout.
- Constraints: no plaintext secret files left in the repo tree; no duplication of secret policy logic outside the canonical docs/tooling.
- Dependencies: SOPS bootstrap policy and layout.

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
- Required decisions to capture:
- Define the minimum operator journey: bootstrap, render, apply, diff, rollback, and runner behavior.
- Explicitly document which directories are ephemeral vs durable and which commands are authoritative entrypoints.
- Acceptance: README matches actual scripts, directories, and state paths; no stale command names or secret-handling ambiguity remains.
- Constraints: align with `config/` as source of truth and with implemented CLI names/paths.
- Dependencies: Render/Apply Contract.

#### Session Prompt (Architecture docs)

- Phase/Task: Documentation / Architecture docs.
- Required inputs: `README.md`, `src/abhaile/cli/render.py`, `src/abhaile/cli/apply.py`, GitOps runner artifacts if present.
- Outputs to produce: `docs/architecture.md` describing pipeline stages and artifacts.
- Required decisions to capture:
- Separate render, apply, runner, and bootstrap responsibilities clearly.
- Document ownership boundaries between rendered output, apply state, and runner state.
- Acceptance: architecture doc references actual stages, state paths, and handoff boundaries, and does not describe superseded behavior.
- Constraints: no secrets; prefer current architecture over historical narrative.
- Dependencies: Define repo layout.

#### Session Prompt (ADR updates)

- Phase/Task: Documentation / ADR updates.
- Required inputs: `docs/adr/`, `README.md`.
- Outputs to produce: ADRs for renderer language, drift strategy, secrets, bootstrap.
- Required decisions to capture:
- ADRs should record current chosen behavior, rejected alternatives worth remembering, and any operator-visible consequences.
- Avoid duplicating transient task-tracker detail that belongs only in `TODO.md`.
- Acceptance: ADRs are numbered, cross-reference related docs where useful, and capture only stable architectural decisions.
- Constraints: no secrets; do not restate implementation minutiae better kept in code/tests.
- Dependencies: Record key ADRs.

### Phase: Bootstrap

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Curl-bash bootstrap | Provide a `scripts/bootstrap.sh` that installs prerequisites and enrolls host. | `curl \<url\> \| bash` workflow documented and safe. | GitOps Runner |
| [ ] | Bootstrap sealed artifact handoff | Ensure bootstrap can access and use the required `sops`-encrypted bootstrap artifacts to establish initial trust without leaving decrypted material behind. | Bootstrap documents and implements how sealed bootstrap artifacts are decrypted/consumed, and no plaintext bootstrap secret persists after enrollment unless explicitly intended. | SOPS bootstrap policy and layout |
| [ ] | Host enrollment flow | Define steps for host naming, SSH key install, and first apply. | Process documented and tested on a clean host. | Curl-bash bootstrap |
| [ ] | One-time token handling | Require a bootstrap token or SSH key passed via env or prompt. | Bootstrap refuses to run without explicit token. | Curl-bash bootstrap |

#### Session Prompt (Curl-bash bootstrap)

- Phase/Task: Bootstrap / Curl-bash bootstrap.
- Required inputs: `README.md`, `src/abhaile/cli/render.py`, `src/abhaile/cli/apply.py`, GitOps runner artifacts if present.
- Outputs to produce: `scripts/bootstrap.sh`; update `README.md` with curl-bash usage and safety notes.
- Required decisions to capture:
- Define exactly what bootstrap is allowed to install/configure versus what must remain operator-managed.
- Define whether bootstrap clones the repo directly, installs a packaged release, or fetches only the runner/bootstrap assets.
- Define idempotency and rerun behavior on partially enrolled hosts.
- Acceptance: bootstrap installs prerequisites, fetches the repo or release payload, registers GitOps units, and refuses to run without explicit token/key.
- Constraints: no secrets in repo; external key material required; render/apply boundary enforced; avoid hidden long-lived secrets in shell history or logs.
- Dependencies: GitOps Runner.

#### Session Prompt (Host enrollment flow)

- Phase/Task: Bootstrap / Host enrollment flow.
- Required inputs: `README.md`, `scripts/bootstrap.sh`.
- Outputs to produce: documented enrollment steps and first apply process in `README.md`.
- Required decisions to capture:
- Define the source of host identity truth and how a machine becomes `phobos` or `deimos`.
- Define the exact point where first render/apply occurs and what prerequisites must already exist.
- Acceptance: steps cover host naming, repo access, external key placement, GitOps unit enablement, and first successful apply.
- Constraints: no secrets documented; avoid hand-wavy "configure access" wording.
- Dependencies: Curl-bash bootstrap.

#### Session Prompt (Bootstrap sealed artifact handoff)

- Phase/Task: Bootstrap / Bootstrap sealed artifact handoff.
- Required inputs: `scripts/bootstrap.sh`, secrets policy/ADR decisions, `sops` bootstrap artifact layout, bootstrap credential handling design.
- Outputs to produce: bootstrap logic and docs for locating, decrypting, consuming, and cleaning up sealed bootstrap artifacts during enrollment.
- Required decisions to capture:
- Define whether bootstrap decrypts artifacts in memory, to a temp file, or via a short-lived working directory, and how cleanup is enforced.
- Define the minimum set of sealed bootstrap artifacts required to establish repo/Vault access on a fresh host.
- Define failure behavior when required encrypted artifacts are missing, undecryptable, or inconsistent with the target host.
- Acceptance: bootstrap can consume the required sealed artifacts deterministically, fails clearly when they are unavailable, and does not leave unintended plaintext behind on disk.
- Constraints: no decrypted bootstrap material committed; no long-lived plaintext unless explicitly part of the design; keep bootstrap-only secrets separate from runtime Vault-managed secrets.
- Dependencies: SOPS bootstrap policy and layout.

#### Session Prompt (One-time token handling)

- Phase/Task: Bootstrap / One-time token handling.
- Required inputs: `scripts/bootstrap.sh`.
- Outputs to produce: token/key requirement and prompt/env handling in `scripts/bootstrap.sh`.
- Required decisions to capture:
- Define accepted credential forms for bootstrap and whether they are mutually exclusive or fallback options.
- Define whether token input is interactive, environment-based, or file-descriptor based, and how it avoids leaking into logs/process lists/history.
- Define disposal/expiry expectations once bootstrap completes.
- Acceptance: bootstrap exits non-zero without explicit credential input, does not echo/write secrets to disk, and documents the supported credential handoff method.
- Constraints: no secrets stored; token never written to disk; avoid unsafe argument-passing that exposes secrets via process list.
- Dependencies: Curl-bash bootstrap.
