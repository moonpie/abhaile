# Spec: Secrets Management

## Metadata

```yaml
id: SPEC-2026-010
title: Secrets Management
status: accepted
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0007-sops-bootstrap-policy-and-layout
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [vault, vault-agent, authelia, caddy-dmz, ddclient, coredns-omada]
```

## Context

The secrets management system is implemented and in production use. This accepted spec
documents the split secrets model, vault-agent template render pipeline, SOPS bootstrap
policy, and external material contracts as reference material.

Implemented behavior spans:

1. A three-class artifact model separating committed templates, rendered non-secret configs,
   and host-only secret outputs.
1. A vault-agent template render pipeline that discovers, copies, and aggregates template
   sources from co-located services into a single vault-agent configuration per host.
1. A SOPS bootstrap policy for sealed pre-Vault artifacts with host-scoped layout and
   age-based encryption.
1. An external material contract defining path ownership, modes, and lifecycle for
   bootstrap inputs, runtime tokens, and secret-bearing service outputs.

## Requirements

- [x] Document the three-class artifact model and secrets boundary.
- [x] Document the vault-agent template render pipeline (discovery → copying → rendering).
- [x] Document the SOPS bootstrap policy and sealed artifact layout.
- [x] Document the external key/token/cert material contract.
- [x] Document service authoring patterns for vault-agent template consumers.
- [x] Record secrets-related implementation decisions from TODO Decision Log.

## Constraints

- No plaintext secrets in git or repo-managed render output.
- Render is unprivileged and deterministic; it never reads or writes resolved secret values.
- Vault-agent template aggregation is host-local only (not cross-host).
- SOPS usage is limited to sealed bootstrap or recovery artifacts needed before Vault Agent is
  online.
- Apply references external secret paths but does not install secret payloads.
- Runtime secret outputs remain host-only and are produced by Vault Agent at runtime.

## Design

### Three-Class Artifact Model

The secrets model classifies all secret-related material into three artifact classes:

**Class 1: Committed templates/specs (`config/`)**

Service specs, placeholder-based config, `*.ctmpl` template sources, and template metadata.
These define secret references and destination paths but never contain resolved secret values.

Examples:

- `config/services/authelia/templates/authelia.configuration.yml.ctmpl`
- `config/services/caddy-dmz/templates/caddy-dns-desec.env.ctmpl`
- `config/services/ddclient/templates/ddclient.conf.ctmpl`
- `config/services/coredns-omada/templates/coredns-omada.env.ctmpl`
- `config/services/vault-agent/templates/ready.ctmpl`

**Class 2: Rendered non-secret configs (`<output>/rendered/`)**

Artifacts derived from repo-defined, non-secret data. Allowed only when content contains no
credentials, tokens, private keys, or decrypted material. Template sources and destination
metadata may be rendered or copied.

Examples:

- Copied `.ctmpl` files under `rendered/services/vault-agent/srv/vault/agent/templates/`
- Rendered vault-agent `config.hcl` under `rendered/services/vault-agent/srv/vault/agent/`
- Runtime output parent directories tracked as `service.directory` artifacts

#### Class 3: Host-only secret outputs (runtime/bootstrap)

Vault-rendered env files, credential-bearing app configs, token files, private keys, and
decrypted bootstrap assets. Host-local only; never committed or written to repo-managed
render output.

Examples:

- `/srv/vault/agent/out/authelia.configuration.yml`
- `/srv/vault/agent/out/authelia-redis.conf`
- `/srv/vault/agent/out/caddy-dns-desec.env`
- `/srv/vault/agent/out/ddclient.conf`
- `/srv/vault/agent/out/coredns-omada.env`
- `/srv/vault/agent/run/vault-agent-token`

### Secrets Boundary

The boundary between render-safe and host-only material:

**Render touches (Class 2 artifacts):**

- `.ctmpl` template source files (copied from service `config/` to rendered output)
- Vault-agent base config (`config.hcl`) with template metadata (source paths, dest paths, perms)
- Runtime output parent directories with ownership/mode metadata
- Manifest entries tracking all above with `vault.template`, `vault.config`, and `service.directory` kinds

**Stays host-only (Class 3 artifacts):**

- Resolved outputs from Vault Agent template rendering (env files, app configs with credentials)
- Vault Agent sink token (`/srv/vault/agent/run/vault-agent-token`)
- Vault Agent AppRole files (`/home/abhaile/.config/vault-agent/role-id`,
  `/home/abhaile/.config/vault-agent/secret-id`)
- Any decrypted SOPS bootstrap material

### Vault-Agent Template Render Pipeline

The render pipeline for vault-agent templates lives in `src/abhaile/renderers/vault_templates/`
and runs as part of the service rendering phase. It has three stages: discovery, copying, and
base config rendering.

#### Stage 1: Discovery (`discovery.py`)

`find_base_vault_agent_service()` locates the service on the current host that defines
`composition.vault_agent.base`. This is the vault-agent service itself (currently
`vault-agent` on both hosts). Returns `None` if no base service is mapped to this host,
in which case the pipeline exits early.

`collect_vault_agent_template_specs()` walks all host-mapped services using
`walk_service_includes()` for depth-first include traversal with cycle detection.
For each service, it reads `composition.vault_agent.templates[]` entries and validates
that each has `source`, `out`, and `perms` fields. Returns a list of `VaultTemplateSpec`
frozen dataclasses in mapping order.

`resolve_vault_agent_volume_paths()` reads the base service's `container.named_volumes`
entries for the `templates` and `out` named volumes and returns the tuple:
`(templates_host_root, templates_mount_root, out_host_root, out_mount_root)`.

Current resolved paths from `vault-agent` service config:

- `templates_host_root`: `/srv/vault/agent/templates`
- `templates_mount_root`: `/agent/templates`
- `out_host_root`: `/srv/vault/agent/out`
- `out_mount_root`: `/agent/out`

#### Stage 2: Copying (`copying.py`)

`copy_vault_agent_templates()` iterates over the collected `VaultTemplateSpec` list and
for each spec:

1. Resolves the source path using `normalize_service_prefixed_path()`.
1. Validates the source `.ctmpl` file exists under `config/services/<service>/`.
1. Strips the `templates/` prefix from the relative source path.
1. Copies the template file to `rendered/services/vault-agent/<templates_host_root>/<rel>`.
1. Registers a `vault.template` artifact with:
   - `target_path`: `<templates_host_root>/<rel>` (host filesystem destination)
   - `owner_ref`: `service:vault-agent`
   - `contributor_ref`: `service:<contributing-service>`
   - `apply_hints`: `write_order: before-config`, `restart_mode: restart`, `rootless: True`, `podman_user: abhaile`
1. Builds template metadata dict with `source` (mount path), `dest` (output mount path), and `perms`.

Returns the list of template metadata dicts for base config rendering.

#### Path-Rewriting Contract

The pipeline rewrites service-relative paths into container-mount-relative paths:

- Template source paths: `<service>/templates/<file>.ctmpl` is rewritten to `/agent/templates/<file>.ctmpl` (the service prefix is stripped).
- Template destination paths: rendered as `/agent/out/<out>` where `<out>` comes from `vault_agent.templates[].out`.
- Host filesystem mapping: templates are copied to `/srv/vault/agent/templates/` and outputs go to `/srv/vault/agent/out/`.

Network placeholder syntax in base config variables supports Jinja2 filter syntax:
`%%network.services.vault.address | strip_cidr%%`.

#### Stage 3: Base Config Rendering (`rendering.py`)

`render_vault_agent_configs()` orchestrates the full pipeline and calls
`_render_base_config()` to produce the vault-agent configuration file:

1. Reads `vault_agent.base.source.template` path from the base service.
1. Resolves network placeholder variables from `vault_agent.base.source.variables` using
   `resolve_placeholders()` (e.g., `%%network.services.vault.address%%` → resolved IP).
1. Creates a Jinja2 environment and renders the template with context:
   - `vault_agent_templates`: list of `{source, dest, perms}` dicts from Stage 2
   - `service.config.<key>`: resolved variable values
1. Writes rendered config to `rendered/services/vault-agent/<destination>`.
1. Registers a `vault.config` artifact with `apply_hints`: `write_order: after-templates`,
   `restart_mode: restart`, `rootless: True`, `podman_user: abhaile`.

`_ensure_vault_output_directories()` creates and registers `service.directory` artifacts
for the output root and each unique parent directory of template output paths. These carry
`apply_hints` with `owner`, `group` (resolved from `podman.user`), and `mode: 0750`.

#### Aggregation Scope

Vault-agent aggregation is host-local. Only services mapped to the same host contribute
templates to that host's vault-agent config. This matches the physical constraint that
vault-agent writes templates to local filesystem paths.

Current aggregation per host (from `config/mapping.yaml`):

- **phobos**: vault-agent (base + `.ready`), authelia (2 templates), caddy-dmz (1 template),
  ddclient (1 template), coredns-omada (1 template, via include through coredns-filtered)
- **deimos**: vault-agent (base + `.ready`), coredns-omada (1 template, via include through
  coredns-clean)

### Service Authoring: vault_agent.templates

Services declare vault-agent template contributions in `composition.vault_agent.templates`:

```yaml
composition:
  vault_agent:
    templates:
      - source: <service>/templates/<name>.ctmpl
        out: <output-filename>
        perms: '<mode>'
```

Fields:

- `source`: path to the `.ctmpl` file relative to the service directory. May include the
  service name prefix (stripped by `normalize_service_prefixed_path()`).
- `out`: filename written to the vault-agent output volume at runtime. Relative to
  the `out` named volume mount path (`/agent/out/`).
- `perms`: octal permission string for the rendered output file (e.g., `0640`).

Services do not define where templates are placed on the host filesystem; that is
determined by the base vault-agent service's named volume configuration.

Consuming services pair their `vault_agent.templates` entries with `composition.systemd`
path/service units that watch the output path and trigger config reload:

- `authelia`: `authelia-config.path` watches `/srv/vault/agent/out/authelia.configuration.yml`
- `caddy-dmz`: `caddy-dns-desec.path` watches `/srv/vault/agent/out/caddy-dns-desec.env`
- `ddclient`: `ddclient-conf.path` watches `/srv/vault/agent/out/ddclient.conf`
- `coredns-omada`: `coredns-omada-env.path` watches `/srv/vault/agent/out/coredns-omada.env`

### SOPS Bootstrap Policy

SOPS is allowed only for sealed bootstrap or recovery artifacts needed before Vault Agent can
render runtime secrets.

**Allowed in git (encrypted):**

- Host-scoped, bootstrap-phase credentials for initial trust establishment.
- Short-lived access material for reaching control-plane dependencies pre-Vault.
- Host recovery material required before Vault Agent can run, such as Vault unseal keys for the
  Vault host.

**Forbidden in git (even encrypted):**

- Long-lived runtime service secrets (API keys, DB passwords, JWT secrets).
- Runtime private keys and certificate keypairs.
- Vault-rendered outputs.

**Layout:**

```text
secrets/<host>/<artifact-name>.sops.yaml
```

**Recipient model:**

- Encryption uses age identities.
- Each artifact requires a target-host recipient appropriate to the artifact owner and at least one
  operator recovery recipient.
- Vault Agent bootstrap artifacts use the `abhaile` user's age identity.
- Vault unseal recovery artifacts use a root/admin age identity on the Vault host.
- Decryption occurs locally on the target host with an operator-provided identity (not from git).

**Plaintext handling:**

- Decrypted material is consumed in memory or ephemeral runtime locations only.
- No decrypted bootstrap plaintext persists under the repo working tree.
- Temporary files, if unavoidable, are created in ephemeral locations and removed immediately.

### External Key/Token/Cert Material Contract

Apply installs references (units, watches, mounts, directories) for external secret
material but does not install secret files. Missing or incorrect external material fails
in the owning runtime unit, not in render output.

| Path | Class | Owner:Group | Mode | Producer |
| --- | --- | --- | --- | --- |
| `/home/abhaile/.config/vault-agent/role-id` | Bootstrap input | `abhaile:abhaile` | `0600` | Bootstrap from `secrets/<host>/vault-agent.sops.yaml` |
| `/home/abhaile/.config/vault-agent/secret-id` | Bootstrap input | `abhaile:abhaile` | `0600` | Bootstrap from out-of-band SecretID handoff |
| `/root/.config/sops/age/vault-unseal.keys.txt` | Recovery input | `root:root` | `0600` | Operator-provisioned Vault unseal age identity |
| `/srv/vault/agent/run/vault-agent-token` | Runtime output | `abhaile:abhaile` | `0600` | Vault Agent sink |
| `/srv/vault/agent/out/.ready` | Runtime sentinel | `abhaile:abhaile` | `0640` | Vault Agent template |
| `/srv/vault/agent/out/<file>` | Runtime secret | `abhaile:abhaile` | `0640` | Vault Agent template |

The readiness sentinel (`abhaile-secrets-ready.path` + `abhaile-secrets-ready.service`)
gates downstream service startup on `/srv/vault/agent/out/.ready` existence.

### Vault Service Configuration

The vault service itself (`config/services/vault/service.yaml`) runs as rootful podman on
ipvlan-l2 and receives its non-secret configuration through `composition.config`:

- `vault/config/local.json.j2` renders with network placeholder variables for listener,
  cluster, and API addresses.
- `vault/config/vault.env` is a static environment file.

Vault contributes an internal ingress block to caddy-internal. It does not define
`vault_agent.templates` because it is the secrets provider, not a consumer.

### Apply Validation Stance

- Apply assumes external secret/key/token files exist at declared host paths.
- Apply does not pre-validate presence or permissions of secret material.
- Failures surface in owning runtime units (Vault Agent, systemd path/service, container
  startup), not in render output generation.
- Apply enforces rendered output directories (ownership, group, mode) from manifest
  `apply_hints` on `service.directory` artifacts.

## Decision Notes

- Decision: Runtime secrets are never stored in git or repo-managed render output; Vault Agent renders them on-host.

- Rationale: Git should not be a parallel runtime secret store; render output must be safe to inspect.

- Impact: All secret-bearing configs are Class 3 artifacts produced by Vault Agent at runtime.

- ADR: 0006-secrets-model-and-bootstrap-artifacts

- Decision: Vault-agent template aggregation is host-local (same-host services only).

- Rationale: Vault-agent writes to local filesystem; cross-host aggregation is physically meaningless.

- Impact: Each host gets its own vault-agent config with only co-located service templates.

- ADR: 0006-secrets-model-and-bootstrap-artifacts

- Decision: Render emits only non-secret vault control-plane artifacts (template sources, base config, output directories).

- Rationale: Keeps render unprivileged and deterministic; resolved secret values are a runtime concern.

- Impact: Manifest tracks `vault.template`, `vault.config`, and `service.directory` kinds with apply hints.

- ADR: 0006-secrets-model-and-bootstrap-artifacts

- Decision: SOPS is limited to bootstrap/recovery artifacts, host-scoped, and uses age encryption
  with operator recovery recipients.

- Rationale: Minimal sealed handoff before Vault Agent is available; host-scoping limits blast radius.

- Impact: Sealed artifacts at `secrets/<host>/`; no runtime secrets in git even encrypted.

- ADR: 0007-sops-bootstrap-policy-and-layout

- Decision: Apply references external material paths and wiring but does not install secret payloads.

- Rationale: Secret material lifecycle is owned by bootstrap (operator) and runtime (Vault Agent), not apply.

- Impact: Missing secrets fail in runtime units, not during render or apply validation.

- ADR: 0006-secrets-model-and-bootstrap-artifacts

- Decision: Template ordering follows mapping.yaml service order with depth-first include expansion.

- Rationale: Deterministic aggregation order is required for reproducible vault-agent config.

- Impact: Template metadata in `config.hcl` is stable across re-renders for identical inputs.

- ADR: null

## Acceptance Criteria

- [x] Reference spec documents the three-class artifact model and secrets boundary.
- [x] Reference spec documents the vault-agent template render pipeline stages.
- [x] Reference spec documents SOPS bootstrap policy, layout, and recipient model.
- [x] Reference spec documents external key/token/cert material contract.
- [x] Reference spec documents service authoring patterns with concrete examples.
- [x] Reference spec records secrets-related implementation decisions.

### Evidence

Criterion: Three-class artifact model and secrets boundary.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) and [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/renderers/vault_templates/](../../../src/abhaile/renderers/vault_templates/) and [src/abhaile/renderers/metadata.py](../../../src/abhaile/renderers/metadata.py).
- Validation evidence: [tests/unit/python/renderers/test_vault_templates_templates.py](../../../tests/unit/python/renderers/test_vault_templates_templates.py), [tests/unit/python/renderers/test_vault_templates_base.py](../../../tests/unit/python/renderers/test_vault_templates_base.py), [tests/integration/test_vault_templates.py](../../../tests/integration/test_vault_templates.py).

Criterion: Vault-agent template render pipeline stages.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) for [src/abhaile/renderers/vault_templates/discovery.py](../../../src/abhaile/renderers/vault_templates/discovery.py), [src/abhaile/renderers/vault_templates/copying.py](../../../src/abhaile/renderers/vault_templates/copying.py), [src/abhaile/renderers/vault_templates/rendering.py](../../../src/abhaile/renderers/vault_templates/rendering.py).
- Validation evidence: [tests/unit/python/renderers/test_vault_templates_templates.py](../../../tests/unit/python/renderers/test_vault_templates_templates.py), [tests/unit/python/renderers/test_vault_templates_base.py](../../../tests/unit/python/renderers/test_vault_templates_base.py), [tests/unit/python/renderers/test_vault_templates_errors.py](../../../tests/unit/python/renderers/test_vault_templates_errors.py), [tests/unit/python/renderers/test_vault_templates_error_paths.py](../../../tests/unit/python/renderers/test_vault_templates_error_paths.py), [tests/integration/test_vault_templates.py](../../../tests/integration/test_vault_templates.py).

Criterion: SOPS bootstrap policy and layout.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete), [docs/adr/0007-sops-bootstrap-policy-and-layout.md](../../adr/0007-sops-bootstrap-policy-and-layout.md).
- Validation evidence: Policy enforcement is structural (layout convention and pre-commit gitleaks scanning); no runtime code implements SOPS decryption in render/apply.

Criterion: External material contract.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete), [docs/adr/0006-secrets-model-and-bootstrap-artifacts.md](../../adr/0006-secrets-model-and-bootstrap-artifacts.md), [config/services/vault-agent/service.yaml](../../../config/services/vault-agent/service.yaml).
- Validation evidence: Contract paths documented in ADR 0006 and verified against service config `container.mounted_files` and `named_volumes` entries.

Criterion: Service authoring patterns.

- Implementation evidence: [config/services/authelia/service.yaml](../../../config/services/authelia/service.yaml), [config/services/caddy-dmz/service.yaml](../../../config/services/caddy-dmz/service.yaml), [config/services/ddclient/service.yaml](../../../config/services/ddclient/service.yaml), [config/services/coredns-omada/service.yaml](../../../config/services/coredns-omada/service.yaml).
- Validation evidence: [tests/integration/test_vault_templates.py](../../../tests/integration/test_vault_templates.py) and [tests/integration/test_composition_includes.py](../../../tests/integration/test_composition_includes.py).

Criterion: Secrets-related implementation decisions.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) and [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete), aligned with vault-agent and secrets model decisions in [TODO.md](../../../TODO.md).
- Validation evidence: Behaviors match TODO Decision Log entries dated 2026-02-07 (vault-agent templates renderer) and 2026-05-05 (ADR 0006/0007 acceptance).

## Out of Scope

- Vault server deployment, unsealing, or policy management.
- SOPS tooling for creating/rotating sealed artifacts (tracked separately in Ops Tooling phase).
- Apply executor behavior for vault-agent restarts beyond manifest metadata.
- Runtime Vault Agent behavior after rendered templates are placed on host.
- Cross-host secret distribution or replication.

## Open Questions

- None.

## References

- `docs/specs/GOVERNANCE.md`
- `docs/specs/_template.md`
- `docs/specs/accepted/0001-render-pipeline.md`
- `docs/specs/accepted/implementation-evidence.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/adr/0007-sops-bootstrap-policy-and-layout.md`
- `src/abhaile/renderers/vault_templates/discovery.py`
- `src/abhaile/renderers/vault_templates/copying.py`
- `src/abhaile/renderers/vault_templates/rendering.py`
- `config/services/vault-agent/service.yaml`
- `config/services/vault/service.yaml`
- `config/services/authelia/service.yaml`
- `config/services/caddy-dmz/service.yaml`
- `config/services/ddclient/service.yaml`
- `config/services/coredns-omada/service.yaml`
- `tests/unit/python/renderers/test_vault_templates_templates.py`
- `tests/unit/python/renderers/test_vault_templates_base.py`
- `tests/unit/python/renderers/test_vault_templates_errors.py`
- `tests/unit/python/renderers/test_vault_templates_error_paths.py`
- `tests/integration/test_vault_templates.py`
- `tests/integration/test_composition_includes.py`
- `TODO.md`
