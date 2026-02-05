# TODO: Rebuild Repo Around config/

## Decision Log

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

1. Decision: Centralize tooling paths in scripts/paths.ini for consistent path resolution.
   Date: 2026-02-01
   Rationale: Single source of truth for defaults across scripts in any language.
   Scope: scripts and tooling path resolution.
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

#### Pre-prompt

```text
You are my coding buddy for this repo. Follow .github/copilot-instructions.md.
Work only on the task below.
Be explicit about files you read/write and keep changes minimal.
Suggest alternatives when you see them, but ask for confirmation before deviating.
Log any decisions in the Decision Log at the top of TODO.md if they’re not ADR-worthy.
```

#### Post-prompt

```text
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
│   ├── install-packages.sh
│   ├── downloads.sh
│   ├── builds.sh
│   └── commands.sh
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
- Package/install manifest: merged `packages`, `downloads`, `builds`, `commands` per host.
- DNS zone artifacts: rendered zone files and serial tracking for `coredns-common`.
- Apply manifest: deterministic inventory with hashes for drift detection and safe apply.

### State/Drift Tracking Expectations

- Render outputs are deterministic and include a per-host manifest with SHA256 for each artifact.
- Apply stores last-applied manifest on the host (e.g., `/var/lib/abhaile/state.json`) and compares for drift.
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

**Status:** Complete

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [x] | Define repo layout | Establish folder structure for `render/`, `docs/`, `docs/adr/`, and `scripts/`. | Layout documented in `README.md` and directories created. | None |
| [x] | Define environment paths | Specify workstation/CI vs host paths for rendered output, state, and live targets; define detection logic. | Paths documented in `README.md` and ADRs; hash-based drift model defined. | Define repo layout |
| [x] | Define config schema | Write a lightweight schema or validation rules for `config/` (mapping, network, hosts, services). | Schema rules documented; validator stub exists. | Define repo layout |

#### Session Prompt (Define repo layout)

- Phase/Task: Foundations / Define repo layout.
- Required inputs: `TODO.md`, `README.md`.
- Outputs to produce: create `docs/`, `docs/adr/`, `scripts/`, `out/`, `out/rendered/`, `out/state/`; update `README.md` to document layout and output paths.
- Acceptance: directories exist; `README.md` includes layout and `out/` usage; no other files required.
- Constraints: `config/` is source of truth; no secrets in repo.
- Dependencies: none.

#### Session Prompt (Define environment paths)

- Phase/Task: Foundations / Define environment paths.
- Required inputs: `README.md`, `docs/adr/` if present.
- Outputs to produce: update `README.md` with workstation vs host paths; ADR in `docs/adr/` describing environment detection and root path selection.
- Acceptance: paths for render output, state, and live target roots are explicit for both environments.
- Constraints: no rendered output committed to git; no secrets.
- Dependencies: Define repo layout.

#### Session Prompt (Define config schema)

- Phase/Task: Foundations / Define config schema.
- Required inputs: `TODO.md`, `config/mapping.yaml`, `config/network.yaml`, `config/services/*/service.yaml`.
- Outputs to produce: schema files in `schemas/`; schema validation handled by `check-jsonschema` hooks in pre-commit.
- Acceptance: schema covers mapping/network/service yaml files.
- Constraints: schema matches existing `config/` shape; no network access; no secrets.
- Dependencies: Define repo layout.

### Phase: Render Pipeline

**Status:** In progress

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [x] | Renderer CLI | Implement a `scripts/render` tool that reads `config/` and emits `<output>/rendered/` (default: `/var/lib/abhaile/rendered/` on hosts). | Running the tool renders a host tree with a manifest in `<output>/state/manifest.json`. | Define config schema |
| [x] | Networking renderer | Render systemd-networkd configs and resolved config from host templates and `config/network.yaml`. | `<output>/rendered/system/etc/systemd/network/` and resolved files present. | Renderer CLI |
| [ ] | Packaging renderer | Merge `packages`, `downloads`, `builds`, and `commands` from `config/hosts/**/host.yaml` (composition.software) across host/common. | Per-host package manifest and command plan rendered under `<output>/rendered/`. | Renderer CLI |
| [ ] | Users renderer | Render user/group/sudoers artifacts from `config/hosts/**/host.yaml` (user_management). | User/group/sudoers files generated under `<output>/rendered/` with deterministic ordering. | Renderer CLI |
| [x] | Service configs renderer | Copy static configs and render templates for each mapped service. | All configs referenced by service.yaml are rendered under `<output>/rendered/services/<service>`. | Renderer CLI |
| [ ] | Quadlets renderer (containers) | Render `.container`, `.image`, `.network`, `.volume` for container services. | Quadlet files generated under `<output>/rendered/services/<service>` per mapped service. | Renderer CLI |
| [ ] | Quadlets renderer (pods) | Render `.pod` and per-container `.container` for pod services. | Pod quadlets rendered under `<output>/rendered/services/<service>` per mapped service. | Renderer CLI |
| [ ] | Ingress renderer | Aggregate ingress blocks with base into Caddy configuration. | Caddyfiles rendered under `<output>/rendered/services/<service>` for `<service>` that defines the base ingress definition. | Service configs renderer |
| [ ] | Vault Templates renderer | Aggregate vault_agent templates with base into per-host vault-agent configuration. | vault-agent configuration rendered under `<output>/rendered/services/vault-agent` as per definition. | Service configs renderer |
| [ ] | DNS renderer | Render CoreDNS zone files and serials from `config/network.yaml` for `composition.dns` found in `service.yaml` files. | Zone files and serial metadata rendered deterministically under `<output>/rendered/services/<service>` as per definition. | Renderer CLI |
| [-] | Manifest writer | Produce `<output>/state/manifest.json` with hashes and metadata. | Manifest is complete and stable across reruns. | Renderer CLI |

#### Session Prompt (Renderer CLI)

- Phase/Task: Render Pipeline / Renderer CLI.
- Required inputs: `TODO.md`, `README.md`, `config/` tree, `docs/adr/` if present.
- Outputs to produce: `scripts/render`; output tree under `<output>/rendered/` and `<output>/state/` (see ADR 0001 for path defaults and overrides).
- Acceptance: `scripts/render --host <host>` creates `<output>/rendered/` and `<output>/state/manifest.json`; exits non-zero on render errors.
- Constraints: unprivileged render only; `config/` is the only input source; no secrets materialized.
- Dependencies: Define config schema.

#### Session Prompt (Networking renderer)

- Phase/Task: Render Pipeline / Networking renderer.
- Required inputs: `config/network.yaml`, `config/hosts/**`, `config/_templates/hosts/**`.
- Outputs to produce: `<output>/rendered/system/etc/systemd/network/*.network` and `.netdev`; `<output>/rendered/system/etc/systemd/resolved.conf`.
- Acceptance: generated files are deterministic and include VLANs, ipvlan-l2, and host interfaces.
- Constraints: templates fail fast on missing network data.
- Dependencies: Renderer CLI.

#### Session Prompt (Packaging renderer)

- Phase/Task: Render Pipeline / Packaging renderer.
- Required inputs: `config/hosts/**/host.yaml` (composition.software), `config/hosts/common/host.yaml`.
- Outputs to produce: `<output>/rendered/software/install-packages.sh`; `<output>/rendered/software/downloads.sh`; `<output>/rendered/software/builds.sh`; `<output>/rendered/software/commands.sh`.
- Acceptance: manifests include merged `packages`, `downloads`, `builds`, `commands` per host.
- Constraints: deterministic ordering; no network access.
- Dependencies: Renderer CLI.

#### Session Prompt (Users renderer)

- Phase/Task: Render Pipeline / Users renderer.
- Required inputs: `config/hosts/**/host.yaml` (user_management), `config/hosts/common/host.yaml`.
- Outputs to produce: `<output>/rendered/users/setup-users.sh`; `<output>/rendered/users/etc/sudoers.d/abhaile`.
- Acceptance: user/group/sudo data is deterministic and sorted; no duplicates.
- Constraints: no secrets; read-only from `config/`.
- Dependencies: Renderer CLI.

#### Session Prompt (Service configs renderer)

- Phase/Task: Render Pipeline / Service configs renderer.
- Required inputs: `config/services/**`, `config/_templates/services/**`, `config/network.yaml`.
- Outputs to produce: `<output>/rendered/services/<service>/...` with configs and rendered templates.
- Acceptance: all configs referenced by service.yaml are rendered; template errors fail the render.
- Constraints: templates must not materialize secrets.
- Dependencies: Renderer CLI.

#### Session Prompt (Quadlets renderer - containers)

- Phase/Task: Render Pipeline / Quadlets renderer (containers).
- Required inputs: `config/services/**`, `config/_templates/services/quadlets/**`, `config/mapping.yaml`.
- Outputs to produce: `<output>/rendered/services/<service>/etc/containers/systemd/*.container`, `.image`, `.network`, `.volume`, `.build`.
- Acceptance: quadlets generated for all mapped container services; files are deterministic.
- Constraints: no secrets; rootful/rootless modes follow service config.
- Dependencies: Renderer CLI.

#### Session Prompt (Quadlets renderer - pods)

- Phase/Task: Render Pipeline / Quadlets renderer (pods).
- Required inputs: `config/services/**`, `config/_templates/services/quadlets/**`, `config/mapping.yaml`.
- Outputs to produce: `<output>/rendered/services/<service>/etc/containers/systemd/*.pod` and related `.container` units.
- Acceptance: pod quadlets generated for all mapped pod services; dependencies are explicit.
- Constraints: no secrets; pod definitions derived from service config.
- Dependencies: Renderer CLI.

#### Session Prompt (Ingress renderer)

- Phase/Task: Render Pipeline / Ingress renderer.
- Required inputs: `config/services/**`, `config/network.yaml`.
- Outputs to produce: `<output>/rendered/services/{caddy-dmz,caddy-internal}/`.
- Acceptance: host ingress fragments are aggregated and deterministic.
- Constraints: no secrets; only mapped services included.
- Dependencies: Service configs renderer.

#### Session Prompt (Vault Templates renderer)

- Phase/Task: Render Pipeline / Vault Templates renderer.
- Required inputs: `config/services/**`, `config/network.yaml`.
- Outputs to produce: `<output>/rendered/services/vault-agent/`.
- Acceptance: vault-agent config is aggregated and deterministic.
- Constraints: no secrets; only mapped services included.
- Dependencies: Service configs renderer.

#### Session Prompt (DNS renderer)

- Phase/Task: Render Pipeline / DNS renderer.
- Required inputs: `config/network.yaml`, `config/services/**`, `config/_templates/services/**`.
- Outputs to produce: `<output>/rendered/services/<service>/etc/coredns/zones/*`; `<output>/state/dns-serials.json`.
- Acceptance: zones render deterministically with stable serials and correct records.
- Constraints: no secrets; zone rendering is pure function of `config/network.yaml`.
- Dependencies: Renderer CLI.

#### Session Prompt (Manifest writer)

- Phase/Task: Render Pipeline / Manifest writer.
- Required inputs: `<output>/rendered/`.
- Outputs to produce: `<output>/state/manifest.json` with a stable schema.
- Acceptance: manifest lists every rendered file with fields: `target_path`, `rel_path`, `sha256`, `size`, `mode`, `uid`, `gid`, `kind`, `source`, `rendered_at`.
- Constraints: deterministic ordering; no secrets in manifest.
- Dependencies: Renderer CLI.

### Phase: Apply Pipeline

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Apply CLI | Implement `scripts/apply` to sync `<output>/rendered/` to the host via SSH/SFTP/rsync. | Dry-run and apply modes functional for a host. | Manifest writer |
| [ ] | Drift detection | Compare render manifest with host state and report differences. | Apply prints drift summary before changes. | Apply CLI |
| [ ] | Safe systemd reload | Only reload/restart units and quadlets when artifacts changed. | Changed services restart; unchanged services stay running. | Apply CLI |
| [ ] | Host safety gate | Enforce hostname and SSH host key checks before apply. | Apply aborts on mismatch. | Apply CLI |
| [ ] | Rollback strategy | Document and implement minimal rollback (last-applied snapshot). | Previous manifest can be restored safely. | Apply CLI |

#### Session Prompt (Apply CLI)

- Phase/Task: Apply Pipeline / Apply CLI.
- Required inputs: `TODO.md`, `README.md`, `<output>/rendered/`, `<output>/state/manifest.json`.
- Outputs to produce: `scripts/apply`; document host state file path in `README.md` (e.g., `/var/lib/abhaile/state/manifest.json`).
- Acceptance: dry-run mode shows planned changes; apply mode syncs `<output>/rendered/` to host.
- Constraints: apply runs with sudo on target; no secrets written; render/apply boundary enforced.
- Dependencies: Manifest writer.

#### Session Prompt (Drift detection)

- Phase/Task: Apply Pipeline / Drift detection.
- Required inputs: `<output>/state/manifest.json`, host state file (last-applied).
- Outputs to produce: drift summary output in `scripts/apply` (or `scripts/diff` if already exists).
- Acceptance: drift summary compares `target_path` + `sha256` and reports added/changed/removed files.
- Constraints: read-only by default; destructive actions require explicit confirmation.
- Dependencies: Apply CLI.

#### Session Prompt (Safe systemd reload)

- Phase/Task: Apply Pipeline / Safe systemd reload.
- Required inputs: `<output>/state/manifest.json`, drift summary.
- Outputs to produce: reload/restart logic inside `scripts/apply`.
- Acceptance: only changed units/quadlets are restarted; unchanged services remain running.
- Constraints: minimize disruption; log each restarted unit.
- Dependencies: Apply CLI.

#### Session Prompt (Host safety gate)

- Phase/Task: Apply Pipeline / Host safety gate.
- Required inputs: `config/mapping.yaml`, target host identity (hostname/SSH host key).
- Outputs to produce: host identity validation logic inside `scripts/apply`.
- Acceptance: apply aborts on hostname or host key mismatch.
- Constraints: fail closed; no bypass without explicit flag.
- Dependencies: Apply CLI.

#### Session Prompt (Rollback strategy)

- Phase/Task: Apply Pipeline / Rollback strategy.
- Required inputs: host state file, `<output>/state/manifest.json`.
- Outputs to produce: snapshot/rollback logic; document usage in `README.md`.
- Acceptance: previous manifest and artifacts can be restored safely on host.
- Constraints: rollback is explicit; no automatic destructive changes.
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

**Status:** In progress

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [x] | Config validation | Implement validation for IP uniqueness, VLAN sanity, and mapping integrity. | Validation fails on invalid config and passes on current. | Define config schema |
| [-] | Render determinism | Add tests or checks for stable render output hashes. | Re-render yields identical manifests. | Manifest writer |
| [-] | Unit and integration test suite | Comprehensive pytest suite covering utils, validation, renderers, and end-to-end flow. | 32 tests (25 unit + 7 integration) all passing; docs/TESTING.md. | Manifest writer |
| [-] | Linting hooks | Add a basic lint/check workflow for YAML and templates. | Lint script runs locally without network access. | Define repo layout |

#### Session Prompt (Config validation)

- Phase/Task: Validation and Testing / Config validation.
- Required inputs: `config/`, `docs/schema.md` if present.
- Outputs to produce: `scripts/validate` checks for IP uniqueness, VLAN sanity, mapping integrity.
- Acceptance: invalid config returns non-zero and prints actionable errors.
- Constraints: offline; no secrets.
- Dependencies: Define config schema.

#### Session Prompt (Render determinism)

- Phase/Task: Validation and Testing / Render determinism.
- Required inputs: `scripts/render`, `<output>/rendered/`, `<output>/state/manifest.json`.
- Outputs to produce: determinism check script or mode in `scripts/validate`.
- Acceptance: rerun render produces identical manifest hashes for unchanged inputs.
- Constraints: offline; no network access.
- Dependencies: Manifest writer.

#### Session Prompt (Linting hooks)

- Phase/Task: Validation and Testing / Linting hooks.
- Required inputs: `config/`, `scripts/`, `docs/schema.md`.
- Outputs to produce: `scripts/lint` or `scripts/check`; update `README.md` with usage.
- Acceptance: lint/check runs locally without network access and fails on malformed YAML/templates.
- Constraints: no network access; no secrets.
- Dependencies: Define repo layout.

### Phase: Ops Tooling

**Status:** Not started

| Status | Task | Description | Completion Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| [ ] | Make targets | Add `make render`, `make apply`, `make validate`. | Targets call scripts and return non-zero on failure. | Renderer CLI |
| [ ] | Host inventory view | Provide a command to list services per host from `config/mapping.yaml`. | Output shows host -> services mapping. | Renderer CLI |
| [ ] | Diff tool | Provide `scripts/diff` to compare render vs host state. | Diff reports file-level differences. | Drift detection |

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
- Required inputs: `<output>/state/manifest.json`, host state file, `scripts/apply`.
- Outputs to produce: `scripts/diff` that compares rendered manifest with host state.
- Acceptance: diff shows added/changed/removed files with paths and hashes.
- Constraints: read-only; no secrets.
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
