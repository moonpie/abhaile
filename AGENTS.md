# Abhaile — Project Context

This is the shared context for all AI agents working on the Abhaile project. It defines the project's purpose, architecture, conventions, and expectations.

## Instruction Ownership

`AGENTS.md` is the canonical instruction file for this repository. Provider-specific files
under `.github/` are adapters only: they may point to these instructions or configure
provider-specific tools, but they must not duplicate or override project rules.

Role-specific files under `.agents/` may define persona focus, review emphasis, preferred
investigation order, validation expectations, escalation guidance, and communication style.
They must not override `AGENTS.md`.

Role-specific workflow guidance may affect how an agent investigates, validates, or reports
work, but only inside the boundaries set by this file. If a role or provider file conflicts
with Guardrails, secret handling, source-of-truth rules, spec/TODO governance, or render/apply
safety, ignore only the conflicting instruction, apply `AGENTS.md`, notify the user once in
the pre-task findings message, and continue unless the table below requires pausing.

Precedence order:

1. Guardrails
1. Secret handling
1. Source-of-truth and render/apply safety
1. Spec and TODO governance
1. User task instructions
1. Role-specific agent guidance
1. General style preferences

Instruction resolution table:

| Condition | Action | Escalation |
| --- | --- | --- |
| Role or provider file conflicts with `AGENTS.md` | Ignore only the conflicting instruction, apply `AGENTS.md`, notify user once | None |
| Requested role or provider file is missing | Apply `AGENTS.md`; notify user if the role/provider was explicitly requested | None |
| Requested role or provider file is empty or unreadable | Treat as missing | Same as missing-file escalation |
| `AGENTS.md` is unavailable | Notify user; apply only Guardrails if separately provided | Do not proceed with render, apply, spec, config, or secrets work until `AGENTS.md` is provided or the user explicitly confirms base-rules-only execution |
| Both `AGENTS.md` and requested role/provider file are unavailable | Notify user of both; apply only Guardrails if separately provided | Do not proceed until `AGENTS.md` is provided or the user explicitly confirms base-rules-only execution; treat all operations as Guardrail-sensitive |

## Portability Notes

- `AGENTS.md` is the canonical, provider-neutral project context.
- `.agents/` contains provider-neutral persona definitions.
- `.github/` contains GitHub/Copilot-specific adapters and configuration.
- `docs/specs/` contains project workflow documents that are useful with or without AI tools.

## Project Overview

Abhaile is a GitOps-managed homelab running on two Lenovo ThinkCentre M910x Tiny machines (i7-7700T, 32GB DDR4) with Debian 13. Services run as bare-metal processes or podman containers/pods.

The repo defines desired state in `config/`, renders host-specific artifacts, and applies them with drift detection. The reconciliation pattern is: desired state in git → render → compare → apply.

### Hosts

- **phobos** — primary host (Coral TPU, mostly infrastructure services)
- **deimos** — secondary host (mostly media services, subset of infrastructure services for availability)

### Key Infrastructure

- Podman quadlets (rootful and rootless) with deterministic /32 ipvlan-l2 addressing
- systemd-networkd for host networking (VLANs, service IPs)
- Split-horizon DNS via CoreDNS (internal + external)
- HashiCorp Vault + vault-agent for secrets (AppRole, templates)
- Caddy for ingress (internal CA + public ACME via deSEC)
- Authelia for SSO/authentication
- SOPS/age for bootstrap secrets (encrypted in repo)

## Architecture

### Render/Apply Pipeline

```text
config/ (source of truth)
  → render (unprivileged, deterministic, idempotent)
    → out/rendered/ (ephemeral desired-state artifacts)
      → apply (privileged, validated, atomic)
        → live host filesystem
```

- **Render** takes desired state only from `config/`, outputs to `out/rendered/<host>/`
- **Apply** compares desired manifest against live state, stages atomically, reloads changed units
- **State** lives in `out/state/<host>/` (manifests, history)

Renderers may also read repository code, schemas, templates, and path configuration needed to
validate and produce deterministic output.

### Source of Truth

All intent lives in `config/`:

- `config/mapping.yaml` — service-to-host assignments
- `config/network.yaml` — VLANs, addresses, DNS zones/records
- `config/hosts/<host>/host.yaml` — host composition (config, software, users)
- `config/services/<service>/service.yaml` — per-service behaviour
- `config/_templates/` — shared rendering templates

### Rendered Artifact Types

- `system/` — systemd-networkd, resolved (atomic file placement)
- `software/` — packages, downloads, builds (execution required)
- `users/` — user/group management, sudoers (execution required)
- `services/<service>/` — quadlets, configs, templates per service

## Repository Layout

```text
src/abhaile/          Python package (CLI, renderers, validation, DNS, apply)
config/               Authoritative intent (source of truth)
tests/                Unit and integration pytest suites
docs/                 Documentation, ADRs, specs
  adr/                Architecture decision records
  specs/              Spec-driven development artifacts
schemas/              JSON schemas for config validation
scripts/              Shell utilities/wrappers
policies/             Vault policies
paths.ini             Project-wide path configuration
```

## Coding Conventions

### Python

- **Python 3.10+** with full type annotations
- **src layout**: `src/abhaile/` is the installable package
- **Formatter**: black (line-length 100)
- **Linter**: ruff
- **Type checker**: mypy (strict mode — see pyproject.toml for exact flags)
- **Docstring coverage**: interrogate (fail-under 90%)
- **Line length**: 100 characters

### Style Patterns

```python
# Module-level logger
LOG = logging.getLogger(__name__)

# Frozen dataclasses for config/value objects
@dataclass(frozen=True)
class ValidatedConfig:
    """Brief description."""
    host_services: dict[str, list[str]]
    mapping: MappingConfig

# Domain errors
from abhaile.utils.errors import RenderError
raise RenderError(f"Missing service definition: {service_path}")

# Type hints on all functions (tests exempt from disallow_untyped_defs)
def render_service_configs(
    host: str,
    services: List[str],
    network: Dict[str, Any],
    config_root: Path,
    output_dir: Path,
) -> None:

# Imports: direct module imports, not package-level re-exports
from abhaile.renderers.software import render_software_artifacts  # yes
from abhaile.renderers import render_software_artifacts            # no
```

### Docstrings

- Concise, imperative mood for the summary line
- Args/Returns/Raises sections when non-obvious
- No verbose "Output contract" blocks — keep it brief
- Match the style of existing renderers (see `services.py`, `networkd.py`)

### Error Handling

- `RenderError` for all domain/rendering errors (fail-fast with clear messages)
- No bare `except:` clauses
- Validate inputs early with clear error messages
- Schema validation preferred for config inputs

### Logging

- `LOG = logging.getLogger(__name__)` at module level
- `LOG.info()` for significant operations (rendering a host, applying changes)
- `LOG.debug()` for detailed tracing
- `LOG.warning()` for recoverable issues
- `LOG.error()` for failures before raising
- Messages should be concise and include relevant context (host name, service name, file path)

### Testing

- **Framework**: pytest with markers (`unit`, `integration`, `slow`)
- **Coverage**: branch coverage via pytest-cov (minimum threshold: 90%, enforced in CI)
- **Fixtures**: shared in `tests/conftest.py` (`tmp_repo`, `tmp_repo_with_config`, `write_file`, `tmp_output`)
- **Test structure**: mirrors source — `tests/unit/python/renderers/`, `tests/unit/python/validation/`
- **Naming**: `test_<behaviour>` functions in `Test<Subject>` classes
- **Pattern**: arrange (fixtures/write_file) → act (call function) → assert (check output files/values)
- **No external or persistent I/O in unit tests** — filesystem I/O is allowed only through temporary fixtures such as `tmp_path`, `tmp_repo`, and related project fixtures
- **Integration tests** may do filesystem I/O, marked with `@pytest.mark.integration`

### Shell Scripts

- Linted with shellcheck (severity: warning)
- Located in `scripts/` for utilities/wrappers
- Business logic belongs in Python, not shell

### YAML

- Formatted with yamlfmt, linted with yamllint
- Schema-validated via pre-commit (JSON Schema for mapping, network, host, service files)

### Jinja2 Templates

- Linted with j2lint
- Extension: `.j2` for templates
- Placeholder syntax for network references: `%%path.to.value%%` (resolved by Python, not Jinja2)

### Commits and PRs

- Conventional commits preferred
- Atomic commits (one logical change per commit)
- PRs should reference relevant specs or TODO items

## Tooling

### Build & Development

- `make install` — create venv, install deps + pre-commit hooks
- `make lint` — run all pre-commit hooks + mypy + interrogate
- `make test` — run all tests with coverage
- `make test-fast` — unit tests only, excluding slow
- `make typecheck` — mypy only
- `make doccheck` — interrogate only

### Pre-commit Hooks

Formatting: black, yamlfmt, mdformat
Linting: ruff, mypy, yamllint, pymarkdown, j2lint, shellcheck
Validation: check-yaml, check-json, JSON schema validation
Security: gitleaks (secret scanning)

### CI

- Pre-commit execution (all hooks)
- pytest (unit + integration, with coverage)
- Trivy security scanning
- Nightly: full render, dependency scan, container image scan

### Dependencies

- Runtime: minimal and pinned in `requirements.txt` (PyYAML, Jinja2, jsonschema)
- Dev: `requirements-dev.txt` (includes runtime + pytest, pre-commit, etc.)
- New dependencies must be justified and documented

## Design Principles

1. **Declarative intent, explicit deployment** — config/ is the source of truth; changes are auditable and reversible
1. **Unprivileged render, privileged apply** — render can run anywhere; apply requires root on target
1. **Deterministic and idempotent** — same input always produces same output; re-running is safe
1. **Schema-first validation** — catch errors early with clear messages
1. **Minimal dependencies** — prefer stdlib; justify any new dependency
1. **Small, composable modules** — each renderer/validator has a focused responsibility
1. **Test-driven confidence** — unit tests for logic, integration tests for render pipeline
1. **Security by default** — no secrets in repo, gitleaks scanning, vault-agent for runtime secrets

## Interaction Protocol

All agents must follow these rules when working with the user, in priority order:

1. **Do not make risky assumptions.** If resolving an ambiguity would affect secrets, data loss/corruption, live apply behaviour, `config/network.yaml`, `config/mapping.yaml`, `out/rendered/`, or `out/state/`, stop and ask for clarification. For other ambiguous choices, state one sentence prefixed with "Assumption:" and proceed. When uncertain which category applies, stop and ask.
1. **Confirm before deviating.** Any change to scope, approach, or design that differs from what was agreed requires user confirmation first.
1. **Suggest improvements.** If you see a better approach than the current plan, propose it with reasoning, but do not change scope, approach, or design unless the user explicitly approves.
1. **Be explicit about what you're doing.** State which files you will read/write and call out assumptions before starting work.

Role-specific guidance is defined in each agent file under `.agents/`.
Role/provider file resolution is defined by the decision table in Instruction Ownership.

## Guardrails

Guardrails take precedence over all Interaction Protocol rules when they conflict.

- Never manually edit files under `out/rendered/` — all desired-state changes must go through `config/` and re-render
- `out/state/` is apply-owned state and may only be written by the apply process, not by ad hoc manual edits
- Never commit secrets — use SOPS/age for bootstrap, vault-agent templates for runtime
- Prefer changes in `config/` over hard-coded script edits
- Keep render deterministic — no timestamps, random values, or external state in render output
- Apply commands must default to dry-run. A live apply requires an explicit user request in the current conversation and the required CLI flag or documented apply mechanism.

### Secret Handling

Treat values as secrets when they are explicitly identified as sensitive, appear in secret-named
keys/files/variables, or match known credential formats. Secret-named contexts include terms
such as `password`, `token`, `key`, `secret`, `credential`, `cert`, and `private`.

False-positive candidates include public certificates, checksums, public keys, service names,
hostnames, IP addresses, and SOPS-encrypted values unless they appear in a plaintext secret
context.

If plaintext secret content appears in user input:

1. Do not repeat the value.
1. Refer to it as `[REDACTED_SECRET]`.
1. Use a vault-agent template path, SOPS reference, or `{{ vault_placeholder_<purpose> }}`
   placeholder where the value would otherwise appear.
1. Notify the user once.

If plaintext secret content appears in an existing tracked file:

1. Stop using the secret value immediately.
1. Do not quote or reproduce the value.
1. Report the affected file path once.
1. Continue unrelated work.
1. Block only work that requires that secret until the user provides a SOPS reference,
   vault-agent template path, or remediation instruction.

If generated content would contain a plaintext secret:

1. Prefer replacing it with the correct vault-agent template or SOPS reference.
1. If the correct reference is unknown, block that file write and ask.
1. Use `{{ vault_placeholder_<purpose> }}` only for drafts or explicit placeholders, not final
   runnable config unless placeholders are valid for that file type.

## Agent Team

This project uses a team of AI agents with distinct personas. Each agent has focused responsibilities and a specific perspective. Agent definitions live in `.agents/`:

| Agent | File | Focus |
| ----- | ---- | ----- |
| Architect | `.agents/architect.md` | System design, specs, ADRs, technical coherence |
| Developer | `.agents/developer.md` | Python/Jinja2/YAML implementation, tests |
| SysAdmin | `.agents/sysadmin.md` | Systemd, podman, networking, security, operations |
| Code Reviewer | `.agents/code-reviewer.md` | Code review, quality gate, spec compliance |
| Technical Writer | `.agents/technical-writer.md` | Documentation, runbooks, ADR drafts |

### Invoking Agents

**VS Code Copilot Chat:** Select the agent from the agents dropdown. Custom agents are defined in `.github/agents/` with tool restrictions and handoffs between roles.

**Other tools:** Provide this file and the relevant agent file as context.

Example (manual context loading):

```text
#file:AGENTS.md #file:.agents/architect.md Design the apply pipeline
```

## Spec-Driven Development

Specs live in `docs/specs/` and follow the template at `docs/specs/_template.md`. The workflow:

1. Identify a need (feature, fix, refactor, new service)
1. Write a spec (or ask the Architect agent to draft one)
1. Review and accept the spec
1. Implement against the spec
1. Review implementation against the spec
1. Update docs as needed

Specs serve as both planning artifacts and documentation of what was built and why.

`docs/specs/GOVERNANCE.md` is authoritative for spec lifecycle mechanics. `AGENTS.md` is
authoritative for when agents must check and enforce that governance.

Before starting implementation, run the pre-task governance checklist:

1. **Stage 1 (always):** run role/provider file resolution and Interaction Protocol rules; collect findings for this stage.
1. **Stage 2a (conditional):** if spec work is referenced, run Spec Pre-Implementation Checks and collect findings.
1. **Stage 2b (conditional):** if TODO work is referenced, run TODO checks and collect findings.
1. If neither spec nor TODO work is referenced, skip Stage 2.
1. **Stage 3 (always):** send one consolidated pre-task message. If there are no findings, say that no work is paused.
1. For each finding, pause only the affected portions and continue unblocked work. A portion is the smallest independently actionable task or file section that directly reads from, writes to, or calls validation logic against the specific file, spec, TODO item, or secret that triggered the check. Indirect dependencies, where blocked data is passed in as an argument, do not block a portion unless that argument is unavailable.
1. If a single file contains both blocked and unblocked work, complete only the unblocked parts and mark blocked sections with TODO placeholders.
1. Explicitly list which portions are proceeding and which are paused.
1. When multiple independent block conditions apply to the same portion, report all applicable block reasons for that portion in one consolidated finding entry. Do not treat one block reason as subsuming another.

Spec work is referenced when the user explicitly names a spec, asks to implement or update a
spec-tracked feature, changes acceptance criteria, or requests a spec status/location transition.
TODO work is referenced when the user asks to implement, close, remove, or otherwise act on a
specific `TODO.md` item. Reading specs or TODOs for context does not by itself trigger the
conditional checks.

### Spec Pre-Implementation Checks

Run these checks before implementing work that references a spec:

| Check | Block condition | Allowed override |
| --- | --- | --- |
| Governance file available | `docs/specs/GOVERNANCE.md` cannot be read and a status/location transition is requested | No |
| Referenced spec available | A named spec file cannot be read | Yes, user may explicitly proceed without the spec |
| Status value valid | `status` is not `proposed`, `active`, `accepted`, `rejected`, or `superseded` | Yes, user may explicitly proceed treating it as `proposed` |
| Status/location consistent | Metadata status disagrees with directory lifecycle | No, ask user to correct or approve a specific normalization |
| Implementation allowed | Spec is not `active` | No, except accepted-spec drift analysis may proceed without implementation |
| Partial completion checked | Active spec has some acceptance criteria already satisfied | No block; report before implementation |
| Supersession chain valid | Missing, invalid, or cyclic supersession metadata prevents authority resolution | Yes for missing chain only; no for cycles |
| Accepted-spec drift | Accepted spec and implementation differ | No implementation against the closed spec; offer a new spec or reopening when governance allows |

Spec lifecycle is directory-first. Metadata `status` must match the directory, except:

- `rejected` specs live in `docs/specs/archive/rejected/`
- `superseded` specs live in `docs/specs/accepted/`

If directory and status disagree, pause implementation for that spec and ask whether to correct
the file location, metadata, or both.

Spec pre-implementation checks are not bypassable by user instruction for the affected portions
they block, except where the table explicitly provides a user-confirmation fallback. If the user
explicitly asks to skip a check, explain which rule prevents it and offer the nearest compliant
alternative while continuing unrelated unblocked work.

User override requests for a blocked finding never unlock that blocked portion unless the specific check explicitly allows it; they do not block unrelated portions.

### Decision And Task Governance

| Record type | Use when | Location |
| --- | --- | --- |
| TODO item | Transient work item, no durable decision needed | `TODO.md` |
| Spec | Feature/fix/refactor with acceptance criteria and delivery tracking | `docs/specs/proposed/`, `docs/specs/active/`, `docs/specs/accepted/` |
| ADR | Decision affects more than one host/service/agent boundary, persists beyond a single spec, or is expensive to reverse | `docs/adr/` |
| Implementation decision note | Decision is scoped to one spec implementation | Relevant spec file |

- `TODO.md` is temporary working state only and may be deleted when its list is complete.
- Do not treat `TODO.md` as a permanent decision record.
- Specs are the single source of truth for roadmap and task completion tracking.
- Any separate tracker is reporting-only and must not be authoritative.
- Keep ADRs canonical in `docs/adr/`, and maintain an ADR index for discoverability.
- TODO hygiene: each `TODO.md` item should be promoted to a spec, completed, or removed within 14 days.
- Each `TODO.md` item must begin with a date-only ISO 8601 creation date on the same line, for example: `- [ ] 2024-01-15 Do the thing`.
- Before implementing or closing work from `TODO.md`, check the item date against the current date in the active environment context.
- If a TODO item has a missing or unparseable date, pause that item and ask whether to promote it to a spec, update the date, complete it, or remove it.
- If a TODO item is older than 14 days, pause that item and ask whether to promote it to a spec, proceed as explicitly approved stale work, complete it, or remove it.
- If a TODO item has a future creation date, flag this as a likely data-entry error and ask whether to correct the date or proceed.
- If the current date is unavailable, treat all dated TODO items as potentially stale and notify the user that age checks cannot be performed without a current date before acting on any TODO item.
- If a TODO item references a spec file that cannot be read, apply the referenced-spec check first before performing TODO age/date checks. Age/date checks are informational only when implementation is already blocked by a missing spec.
- "Complete" means perform or verify the work and mark the item done with evidence. "Remove" means delete the stale item without implementing it.

#### Required Spec Metadata

Each spec should include a compact metadata header with these fields:

- `id`
- `title`
- `status` (`proposed|active|accepted|rejected|superseded`)
- `owner`
- `created`
- `updated`
- `related_adrs` (list)
- `supersedes` (optional)
- `superseded_by` (optional)
- `scope` (hosts/services touched)
- If the current date is unavailable and a spec write requires setting `created` or `updated`, set the value to `UNKNOWN-DATE`, notify the user once, and continue. Do not block spec work solely because the current date is unavailable.

If a spec references a `supersedes` or `superseded_by` spec that cannot be read, notify the user with the missing spec ID and do not treat the current spec as the authoritative version until the chain is resolved or the user explicitly confirms.
If resolving a `supersedes`/`superseded_by` chain produces a cycle (for example, A -> B -> A), stop chain resolution immediately, notify the user with the cycle path, and treat neither spec as authoritative until the user corrects the metadata.
If a spec encountered during `supersedes`/`superseded_by` chain resolution has an unrecognized status, apply the unrecognized-status rule (treat as `proposed`, flag to user) and pause chain resolution for that node until the user corrects the status.
If a spec encountered during `supersedes`/`superseded_by` chain resolution cannot be read, apply the referenced-spec check: notify the user with the missing spec ID, halt chain resolution at that node, and treat the current spec as non-authoritative until the chain is resolved or the user explicitly confirms.
When following a `supersedes`/`superseded_by` chain, track visited spec IDs regardless of direction. If any spec ID is encountered more than once during traversal (including the starting spec), treat this as a cycle, stop resolution, and notify the user with the full traversal path.

#### Task Completion Tracking

- Use acceptance criteria checkboxes in the active spec as the primary completion tracker.
- Each completed criterion should reference implementation evidence (PR/commit and validation/tests).
- On completion, move the spec to `accepted/` and update linked ADRs when applicable.

Operational details for spec lifecycle handling, status transitions, and PR checklist gates are in
`docs/specs/GOVERNANCE.md`.
