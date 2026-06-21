# Spec: CI and Dependency Automation

## Metadata

```yaml
id: SPEC-2026-024
title: CI and Dependency Automation
status: proposed
owner: moonpie
created: 2026-06-21
updated: 2026-06-21
related_adrs: []
supersedes: null
superseded_by: null
scope:
  hosts: []
  services: []
```

## Context

Abhaile currently has strong local validation commands, but no repository-level
CI workflow and no dependency update automation. Local checks include
`make lint`, `make test-fast`, full pytest coverage, schema validation,
pre-commit hooks, mypy, interrogate, shellcheck, yamllint, j2lint, and gitleaks.
Those checks are effective when run manually, but they do not yet provide a
shared pull request gate.

The repo also pins and references software in several forms:

- Python runtime and development dependencies in `pyproject.toml`,
  `requirements.txt`, and `requirements-dev.txt`
- pre-commit hook revisions in `.pre-commit-config.yaml`
- GitHub Actions versions once CI workflows are added
- container images in quadlet `.image` files and service build inputs
- host software downloads and checksums under `config/hosts/*/software/`
- bootstrap and operational tool versions such as `sops` and `vault`

Phase 5 should make routine maintenance visible and reviewable without allowing
automation to make unreviewed deployment changes. The desired outcome is a
small, predictable CI surface and dependency update PRs that are easy to assess.

Renovate is the leading dependency automation candidate because it supports many
package managers and custom extraction rules for dependencies that are not
detected by built-in managers. That matters for Abhaile because several versions
live in project-specific YAML under `config/`. Dependabot remains a fallback for
standard GitHub-hosted dependency updates if Renovate proves too noisy or too
complex.

## Requirements

- [ ] Add CI workflows that run repository validation on pull requests and pushes
- [ ] Keep CI behaviour equivalent to documented local commands where practical
- [ ] Add dependency automation configuration for standard package managers
- [ ] Add custom dependency extraction for Abhaile-specific software references
- [ ] Define structured metadata for host software downloads before automating them
- [ ] Group update PRs so review load stays low
- [ ] Separate low-risk tool updates from high-risk runtime and deployment updates
- [ ] Prevent dependency automation from committing secrets or generated state
- [ ] Require tests and lint checks before any automated merge policy is enabled
- [ ] Record bot trust, branch protection, and automerge policy in an ADR before enabling automerge
- [ ] Document the operational review process for dependency update PRs

## Constraints

- CI must not perform live apply, host mutation, or network controller writes.
- CI must not write to `out/state/` or manually edit `out/rendered/`.
- CI may render desired state for validation, but rendered output remains
  ephemeral.
- CI render checks should use a temporary output root, not the repository
  `out/` path.
- CI must not require Vault, SOPS private keys, host SSH keys, or production
  secrets.
- Secret scanning must remain part of the validation path.
- Dependency automation must open pull requests by default; direct commits to
  protected branches are out of scope.
- Runtime dependency updates must not be automerged until the test and review
  policy is explicitly accepted.
- Container image and host software updates must preserve version and checksum
  integrity.
- The first implementation should avoid paid-only platform features.
- GitHub Actions validation workflows should request `contents: read` only.
- Workflows or apps that create dependency update PRs may request write
  permissions only for the minimum scopes needed to create branches, commits,
  and pull requests.

## Design

### CI Workflows

Add GitHub Actions workflows under `.github/workflows/`.

Initial workflows:

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `ci.yml` | pull request, push | Run `make lint` and `make test-fast` |
| `render.yml` | pull request, push | Render all hosts and check deterministic output |
| `security.yml` | pull request, schedule | Run secret and dependency/security scans |

`ci.yml` is the required baseline gate. `render.yml` may be folded into
`ci.yml` if separate workflow overhead is not useful. `security.yml` may start
with the existing gitleaks pre-commit hook and later add container or filesystem
scanning when the dependency update flow is stable.

CI should install dependencies through the existing `make install` path unless
that proves too slow. If caching is added, cache keys must be based on dependency
files and Python version, not broad workspace paths.

Validation workflows should set explicit least-privilege permissions. The
default validation posture is read-only repository access.

### Validation Contract

CI should initially run:

```text
make lint
make test-fast
abhaile-render --all --output "$RUNNER_TEMP/abhaile-render"
git diff --check
```

Full `make test` can be added as a scheduled workflow or as a required check if
runtime stays acceptable. The local and CI command names should stay aligned so
that a failed CI check can be reproduced without reading workflow internals.
The render check intentionally uses a temporary output root instead of
`make validate`, because the local target writes to `./out`.

### Dependency Automation

Add dependency automation configuration after CI is in place. Renovate is the
preferred first implementation. The configuration should be conservative:

- dependency dashboard enabled
- update PRs scheduled into a predictable window
- separate groups for Python dependencies, pre-commit hooks, GitHub Actions,
  container images, and host software downloads
- no automerge for runtime dependencies, container images, host software
  downloads, or major updates
- optional automerge only for low-risk patch updates after required CI checks
  are stable and the policy is explicitly accepted
- labels that identify update type and risk

Dependabot is an acceptable fallback for standard ecosystems if Renovate cannot
handle the repo-specific config cleanly, but the custom update surface must not
be split across multiple bots without a clear reason.

### Dependency Classes

Classify dependency updates by blast radius:

| Class | Examples | Default Handling |
| --- | --- | --- |
| CI tooling | GitHub Actions, pre-commit hooks | PR, grouped, low risk |
| Python tooling | pytest, mypy, ruff, black, interrogate | PR, grouped |
| Python runtime | PyYAML, Jinja2, jsonschema | PR, test required |
| Container images | service images in `config/services/` | PR, render plus review |
| Host downloads | `sops`, `vault`, static binaries | PR, checksum required |
| Security updates | vulnerable packages or images | PR, prioritized |
| Major updates | any breaking version boundary | PR, never automerge |

### Custom Extraction

Abhaile-specific version references should be made machine-readable rather than
handled with broad ad hoc regexes. Preferred patterns:

- add explicit metadata fields where schemas already model downloads or images
- add `renovate:` comments only where a structured field is not practical
- keep checksums adjacent to the version and require update PRs to refresh them
- fail CI when a versioned host download lacks a checksum or update policy

Custom extraction should cover:

- host software download URLs and checksums under `config/hosts/*/software/`
- container image references in `config/services/**/quadlets/**/image.image`
- built service image inputs such as `config/services/**/build/Containerfile`
- GitHub release or tag based tools that are not represented in standard
  dependency files

Host software downloads should move away from command-only version definitions
before automated updates are enabled. The desired schema shape should include:

- datasource, such as GitHub releases, GitHub tags, or vendor release API
- package name or repository name
- current version
- versioning scheme when semver is not enough
- URL template or resolved URL
- checksum and checksum algorithm
- install destination
- update policy, such as manual, PR only, or security-prioritized

Command lists may still perform installation, but version discovery and checksum
verification should be represented as structured data that CI and dependency
automation can validate.

### Security Scanning

The first security gate should reuse existing local checks:

- gitleaks for secret scanning
- schema validation for config files
- shellcheck, yamllint, j2lint, and Python linting/type checks through
  `make lint`

Later additions may include:

- dependency vulnerability scanning
- container image scanning for configured service images
- SBOM generation for the Python package and rendered service image set

Any scanner that requires external credentials or uploads private dependency
metadata needs an explicit decision before implementation.

### Pull Request Policy

Dependency PRs should include:

- the dependency or grouped dependency names
- current and proposed versions
- affected files
- risk class
- required validation checks
- manual review notes for host downloads, container images, and major updates

Branch protection should require CI checks before merge once workflows exist.
Automerge is not part of the initial implementation unless limited to a
well-defined low-risk class and explicitly accepted after observing the first
batch of update PRs.

Before automerge is enabled or CI checks become formal merge gates, create an
ADR covering:

- bot trust boundary
- branch protection requirements
- allowed automerge classes
- required checks for bot-created PRs
- rollback expectations if a merged dependency update breaks GitOps deployment

## Decision Notes

- Decision: CI is implemented before dependency automation.

- Rationale: Update PRs are only useful when the repository can validate them
  consistently. CI provides the trust boundary for bot-created changes.

- Impact: Dependency automation waits until the baseline checks are reliable.

- ADR: null

- Decision: Renovate is the preferred first dependency automation candidate.

- Rationale: Abhaile needs standard package-manager support plus custom
  extraction for versions in repo-specific YAML. Renovate supports custom
  managers, while Dependabot is strongest for standard ecosystems.

- Impact: The first implementation must keep Renovate configuration simple and
  reviewable. If it becomes too complex, the fallback is Dependabot for standard
  ecosystems plus a separate documented process for Abhaile-specific updates.

- ADR: null

- Decision: Automerge is disabled by default.

- Rationale: This repo controls host desired state. Even correct dependency
  updates can change live service behaviour after the GitOps runner applies a
  commit.

- Impact: Routine updates require review until a narrower low-risk policy is
  accepted.

- ADR: null

- Decision: Bot trust and merge-gate policy require an ADR before automerge.

- Rationale: CI checks and dependency bots affect what can enter the branch
  that GitOps hosts eventually apply. That trust boundary is long-lived and
  cross-cutting.

- Impact: This spec may implement read-only CI and dependency PR creation before
  the ADR, but automerge and formal branch protection policy wait for the ADR.

- ADR: required before automerge or formal branch protection enforcement

## Acceptance Criteria

- [ ] CI workflow runs `make lint` on pull requests
- [ ] CI workflow runs `make test-fast` on pull requests
- [ ] CI workflow validates all-host render output without requiring production secrets
- [ ] CI workflow includes `git diff --check`
- [ ] CI documentation explains how to reproduce each required check locally
- [ ] Validation workflows declare least-privilege GitHub token permissions
- [ ] Dependency automation config opens PRs for Python dependencies
- [ ] Dependency automation config opens PRs for pre-commit hook revisions
- [ ] Dependency automation config opens PRs for GitHub Actions versions
- [ ] Dependency automation config detects container image updates in quadlet `.image` files
- [ ] Dependency automation config detects supported service build input updates
- [ ] Host software download schema records datasource, package, version, URL, checksum, and policy metadata
- [ ] Dependency automation config detects host software download updates where structured metadata supports it
- [ ] Host software update PRs include refreshed checksums or are blocked
- [ ] Update PRs are grouped by dependency class
- [ ] Major updates are separated from minor and patch updates
- [ ] Runtime, container, and host software updates are not automerged
- [ ] ADR records bot trust, branch protection, and automerge policy before automerge is enabled
- [ ] Security scanning remains part of the pull request validation path
- [ ] The update review process is documented

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [workflow run, local command output, or equivalent]

If validation is not applicable, use `N/A` with a short rationale and reviewer
approval.

## Out of Scope

- Live deployment from CI
- Running `abhaile-apply` in CI
- Publishing release artifacts
- Paid-only security or dependency features
- Fully unattended dependency updates for runtime services
- Automated host package upgrades outside the Abhaile desired-state model
- Replacing the GitOps runner

## Open Questions

1. **Renovate hosting** - Should Renovate run as the hosted GitHub app, a
   scheduled GitHub Action, or a self-hosted job?

1. **Automerge threshold** - Is any class safe enough for automerge after CI is
   stable, or should all dependency updates remain manual?

1. **Checksum refresh** - What tool should refresh host download checksums, and
   should checksum verification happen in CI before PR creation or after the PR
   is opened?

   Host download update PRs must not be mergeable unless checksums are present
   and validated. The open question is tooling and timing, not whether checksum
   validation is required.

1. **Container image policy** - Should image updates track tags only, tags plus
   digests, or digest-pinned references?

1. **Full test cadence** - Should full `make test` run on every PR, nightly, or
   only for dependency update PRs?

1. **ADR scope** - Should the ADR cover only bot trust, automerge, and branch
   protection, or also dependency grouping, security update priority, and
   rollback expectations?

## References

- `Makefile`
- `.pre-commit-config.yaml`
- `pyproject.toml`
- `requirements.txt`
- `requirements-dev.txt`
- `config/hosts/*/software/`
- `config/services/*/service.yaml`
- `config/services/**/quadlets/**/image.image`
- `config/services/**/build/Containerfile`
- Renovate documentation: `https://docs.renovatebot.com/`
- Renovate regex custom manager documentation:
  `https://docs.renovatebot.com/modules/manager/regex/`
- GitHub Dependabot version updates documentation:
  `https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-version-updates`
