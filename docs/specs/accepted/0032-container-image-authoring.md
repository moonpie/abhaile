# Spec: Container Image Authoring

## Metadata

```yaml
id: SPEC-2026-032
title: Container Image Authoring
status: accepted
owner: moonpie
created: 2026-10-28
updated: 2026-10-30
related_adrs:
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

At the start of this spec, registry image settings had overlapping authoring locations: `podman.image` and
`podman.pull_policy` supply service-level defaults, while container definitions may override
those fields. This complicates standalone versus pod authoring, inheritance, and validation.

Both locations were introduced by commit `9aed382` on 2026-08-05 when registry references moved
from separate `.image` Quadlets into service YAML. Its operational purpose was direct `Image=`
references with `Pull=missing` and separation from managed local builds. That behavior does not
require service-level image defaults. The schema described those defaults as convenient for a
single container or default pod image, but the deployed multi-container pods already specify
images individually. Blocky historically kept its image in the shared container definition.

An initial, uncommitted implementation of this spec allowed runtime and image pairs under
`podman`. On 2026-10-29, the owner approved revising the design to make container definitions the
canonical home for registry image settings. This revision replaces that design within the same
active spec; it does not supersede another spec. The earlier implementation has now been revised
in the working tree; completion evidence is recorded below.

This cross-service work remains separate from home-automation spec 0015 and the Mosquitto
configuration-directory fix.

## Requirements

- Limit `podman` to the required local runtime fields `user` and `network`; reject `image`,
  `pull_policy`, empty blocks, incomplete runtime declarations, and unknown fields there.
- Declare registry image settings under `composition.container` for standalone containers and
  `composition.pod.containers[].container` for pod members, using the same container schema.
- Require every declared pod to have a `containers` list with at least one member. Each member
  must contain `name` and a nested `container` object.
- Remove service-level registry image fallback and the precedence between `podman` and container
  image settings. Reject pod-member wrapper-level image fields outside the nested `container`.
- Keep runtime fields local to the eventual deployed service; never inherit them.
- Reuse existing container composition for shared image definitions, including Blocky common.
- Preserve container pull-policy values and defaults, local builds, runtime metadata,
  rootful/rootless network restrictions, and existing container-definition selection rules.
- Validate mapped services and their include closures before rendering, sharing the rules with
  a read-only project pre-commit check.
- Migrate all managed service definitions and supporting image references to the canonical
  locations without changing rendered artifacts or manifests on either host.

## Constraints

- No new dependencies, network access, Vault access, or live-host operations are needed for
  validation. Render remains deterministic and unprivileged.
- Do not change mapping, networking, DNS serials, reconciliation, directory management, or runner
  recovery state as part of this work.
- Private volume directory management is tracked separately by
  [spec 0033](../active/0033-private-volume-directory-management.md). Its intended directory
  manifest additions must not be folded into this spec's image-migration output-equality evidence.
- Do not redesign include traversal, deduplication, container selection, deep-merge behavior,
  missing-definition diagnostics, or cycle detection.
- Preserve managed-build metadata and semantics, including the distinct `build.pull_policy`.
  Existing legacy `.image` fallback handling is not expanded or removed by this spec; managed
  registry services must use container YAML rather than rely on that compatibility path.
- Accepted specs remain historical delivery records; this active spec authorizes the change.

## Design

### Canonical Locations

| Purpose | Authored location | Inherited? |
| --- | --- | --- |
| Runtime context | `podman.user`, `podman.network` | No |
| Standalone registry image | `composition.container.image`, `pull_policy` | Through container composition |
| Pod-member registry image | `composition.pod.containers[].container.image`, `pull_policy` | Through pod/container composition |
| Managed local build | Existing `build` metadata and Quadlet sources | Existing behavior unchanged |

The entire `podman` section remains optional for native services and shared fragments. If present,
`user` and `network` are both required. A mapped Podman service declares that runtime context
locally, even if an included definition also declares runtime fields. Mapping determines which
services are deployed; included container fragments need no `podman` section.

Standalone and pod-member container objects use `common.schema.json#/definitions/containerConfig`.
The `image` field remains a non-empty string when supplied. `pull_policy` remains optional with
an effective renderer default of `missing` and allowed values `always`, `missing`, `never`, and
`newer`. This revision does not introduce image/policy pair dependencies on container fragments.
A registry-backed container needs a resolved image; local build sources remain an alternative.
There is no service-wide registry image or pull-policy default to consult.

Standalone example:

```yaml
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    image: docker.io/hashicorp/vault:1.21.4
    pull_policy: missing
```

Pod-member example:

```yaml
podman:
  user: root
  network: ipvlan-l2
composition:
  pod:
    containers:
      - name: redis
        container:
          image: docker.io/library/redis:8.2.2-alpine
          pull_policy: missing
```

Shared Blocky example:

```yaml
# blocky-common (excerpt)
name: blocky-common
composition:
  container:
    image: ghcr.io/0xerr0r/blocky:v0.27.0
    pull_policy: missing
```

```yaml
# blocky-a (excerpt; blocky-b follows the same pattern)
name: blocky-a
podman:
  user: root
  network: ipvlan-l2
composition:
  include:
    - blocky-common
```

### Resolution and Validation

Registry resolution reads the selected container definition, validates its image/policy and
applies the existing policy default. Remove the separate service-level image traversal.

Preserve the current container-definition selection: a non-empty local container/pod definition
wins; otherwise the resolver selects the first included definition it can resolve. Deep merging
within included composition continues to use its existing traversal and overlay rules. This
spec does not promise new field-by-field inheritance when a local definition replaces an
inherited one, nor new merging of pod-member lists. Test these boundaries explicitly.

Per-file schema validation checks runtime requirements, canonical field locations, allowed
values and unknown fields. A declared `composition.pod` requires `containers` with `minItems: 1`.
Each member requires both `name` and its nested `container` object; `{}` remains valid for that
object where image/build sources are resolved separately under the existing compatibility
rules. An empty object does not itself make a runnable container. Remove the unused wrapper-level
`image` and `pull_policy` schema properties. Existing deployed pods already use the nested form.
There is no exception for empty pod placeholders or fragments: a shared fragment that does not
declare a pod can omit `composition.pod` entirely.

Project validation schema-checks each mapped definition and every included definition before
rendering. It preserves canonical missing-definition and cycle diagnostics. The same logic is
used by CLI render and a pre-commit project hook, without rendering, reading credentials, or
contacting hosts. Retain the hook's `pass_filenames: false` and `always_run: true`: it checks the
mapped project once, including deletion-only commits which ordinary filename selection misses.

Retain the existing requirement that a definition with `podman` supplies `composition.container`,
`composition.pod`, or `composition.include`. Shared container fragments are valid without runtime
settings; `podman` image-only fragments are no longer valid anywhere.

### Migration and Implementation Areas

- `schemas/service.schema.json`: restore runtime-only `podman`; reject service-level and
  pod-wrapper image/policy fields. Keep the shared container schema and policy defaults.
- `src/abhaile/renderers/quadlets/helpers.py`, `container.py`, and `pod.py`: remove service-level
  image resolution, consume the selected container object consistently, and preserve local builds.
- Shared CLI/project service validation and `.pre-commit-config.yaml`: retain include validation
  and the read-only hook from the earlier implementation; adjust runtime assumptions as needed.
- Move Vault, Vault Agent, Caddy Internal, and Mosquitto image settings into their standalone
  container definitions. Restore Blocky's image to `blocky-common.composition.container`.
  For Mosquitto, retain `systemd` before `container` and author the same pinned image literally in
  the password-helper variables and container definition, as explicitly approved by the owner.
  Authelia and Omada already use the desired nested pod-member container shape.
- Audit all service definitions, templates, tests, image extraction and documentation for the
  removed service-level/wrapper paths. Keep inventory's runtime fields local.
- Replace tests for service-level image pairs with canonical-location and container-resolution
  tests. Reuse the useful include-validation, hook, read-only and output-equality tests.
- Update the authoring guide, ADR 0005/index, and proposed inventory/CI requirements.

### Impacted Contracts

| Record | Status | Treatment |
| --- | --- | --- |
| 0004 Quadlet Renderer | Accepted | Reference runtime selection and canonical image resolution; record existing drift below |
| 0005 Service Composition | Accepted | Reuse existing container composition; preserve selection and traversal |
| 0007 Validation Pipeline | Accepted | Retain include-aware project checks alongside per-file validation |
| 0011 Core Services | Accepted | Cover standalone migrations, Blocky, rootless Vault Agent and Caddy builds |
| 0015 Home Automation | Active | Migrate Mosquitto authoring/helper reference; preserve deployed behavior |
| 0022 Inventory Generator | Proposed | Keep deployment discovery based on mapping and local runtime context |
| 0024 CI Dependency Automation | Proposed | Extract registry images from canonical container objects, including shared definitions |
| ADR 0005 | Accepted, amended | Record runtime-local and container-owned image authoring |

Accepted spec 0004's statements that include-only pod/container authoring is unsupported already
conflict with current schema and Blocky usage. This drift predates either version of spec 0032.
The existing Blocky pattern remains explicitly supported here. Do not reopen the accepted spec
or treat the pattern as a newly added runtime feature. Reconciliation and runtime-audit contracts
need no changes if rendered artifacts and manifest metadata remain equal.

## Decision Notes

- Decision (2026-10-29): Make container definitions the canonical registry image/policy location.
  Rationale: Standalone and pod containers share one schema and resolution model; there is no
  demonstrated deployed need for a service-wide image fallback. Impact: Replace the uncommitted
  `podman` image-pair model and migrate standalone image settings. ADR:
  [0005](../../adr/0005-service-authoring-model.md).
- Decision: Keep runtime fields local and preserve existing container policy defaults and
  composition selection. Rationale: Limit this change to image authoring consistency without
  silently changing privilege, networking, boot pulls, or inheritance semantics.
- Decision: Maintain two matching Mosquitto image literals, with `systemd` before `container`.
  Rationale: The owner explicitly accepts the maintenance cost for this service's readable section
  order. Impact: Remove its YAML image anchor/alias; update both literals on image upgrades and
  retain the deployment regression that compares helper and broker image references.
- Decision: Replace the unmapped NetBox empty-pod scaffold with an unconfigured placeholder,
  retaining its intended pod design in a comment. Rationale: Empty pods are invalid under the
  approved schema and no NetBox containers have been specified. Impact: No mapped service or
  rendered artifact changes; future NetBox delivery must declare its actual containers.

## Acceptance Criteria

- [x] Schema tests accept runtime-only `podman` and canonical standalone/pod container image
  settings; reject `podman.image`, `podman.pull_policy`, pod-wrapper equivalents, empty/incomplete
  runtime blocks, unknown fields, invalid images/policies, and invalid rootful/rootless networks.
- [x] Schema tests reject pods without `containers`, empty container lists, and members missing
  `name` or nested `container`; accept a nested empty object structurally while preserving
  separate renderer checks for required image/build sources.
- [x] CLI and project validation schema-check mapped and included definitions before rendering,
  retain cycle/missing-definition diagnostics, and keep runtime fields local.
- [x] The real pre-commit hook covers shared-fragment-only, schema-only and deletion-only changes;
  project validation performs no render or live-host operations.
- [x] Tests prove standalone and pod image resolution uses only the selected container object,
  preserves `missing` as the policy default, and cannot fall back to removed image locations.
- [x] Tests preserve nested include selection, local-definition replacement, shared Blocky
  composition, pod-member images, local builds, rootless unit placement, ownership and health hints.
- [x] All managed definitions and supporting references use canonical image locations. Full-host
  artifacts and manifests remain byte-identical to the pre-change baseline for both hosts.
- [x] Appropriate tests and repository checks are recorded; guide, ADR/index and linked proposed
  specs agree with the revised contract. Any pre-existing coverage failure remains explicit.

### Evidence

All criteria are complete. Implementation reference for each criterion: [commit 4fd9eaa](https://github.com/moonpie/abhaile/commit/4fd9eaa25ff4c5f6317f957bac614da84df32d4c). The criterion-specific validation is recorded below, including the canonical schema, image resolution, real project-hook and all-host comparison evidence. The subsequent 674-test run also passed (86.76% coverage); no live broker deployment is required by this authoring spec. Earlier pairing tests were replaced with canonical-container authoring, selection and migration tests.

Historical validation on 2026-10-28, for the earlier pairing proposal only:

- 643 selected unit and renderer/validation integration tests passed. The coverage gate failed
  at 84.53% against the configured 85%; the matching existing-test selection at baseline commit
  `65cb022` passed 569 tests with 83.77% coverage. The threshold was not lowered.
- Lint, type checks and docstring checks passed; full-host output comparisons were byte-identical.
- Independent review found no material issues with that earlier design. Full Ansible acceptance
  and runner suites were not completed. No live-host operations were performed.

These historical results establish prior working state, not acceptance evidence for container-only
authoring. Revised validation results are recorded separately below.

### Revised Implementation Validation (2026-10-29)

- 653 selected unit and integration tests passed using the command below. The coverage gate
  failed at 84.54% against the configured 85%; the earlier matching baseline selection was
  83.77%. The existing shortfall remains explicit and the threshold was not changed.
- `make lint` passed, including pre-commit, mypy and 100% docstring coverage. New untracked files
  were checked explicitly because `--all-files` does not select them.
- Fresh renders of phobos and deimos before and after this revision were byte-identical,
  including manifests. All render output was written beneath temporary roots.
- Independent Code Reviewer review found no material issues and independently confirmed project
  validation and output equality. No live-host operations were performed; the full Ansible
  acceptance and runner suites were not rerun for this authoring-only revision.

```bash
.venv/bin/pytest tests/unit/python \
  tests/integration/test_container_image_authoring.py \
  tests/integration/test_quadlets.py \
  tests/integration/test_composition_includes.py \
  tests/integration/test_quadlet_devices.py \
  tests/integration/test_mosquitto.py \
  tests/integration/test_dns.py \
  tests/integration/test_ingress.py \
  tests/integration/test_render_e2e.py \
  tests/integration/test_vault_templates.py
```

Criterion-specific implementation and validation evidence for commit `4fd9eaa`:

- `schemas/service.schema.json` and `tests/integration/test_container_image_authoring.py` cover
  canonical image locations, runtime requirements, nonempty pods, nested container objects,
  schema rejection of removed fields, and validation of include closures.
- `src/abhaile/renderers/quadlets/helpers.py`, `renderer.py`, `pod.py`, and `container.py` consume
  only selected container registry settings. `test_quadlets_image_config.py` covers defaults,
  existing include selection, local replacement, deep merging within selected includes,
  removed-fallback rejection, and direct-renderer nested-object errors.
- The real project-hook deletion regression and source-wrapper tests retain read-only
  pre-commit coverage. Shared validation remains in `src/abhaile/validation/services.py` and
  `src/abhaile/cli/validate_services.py`, used by CLI render and `scripts/validate-services.py`.
- Vault, Vault Agent, Caddy Internal and Mosquitto now use standalone container images;
  Blocky's shared container owns its image. Existing pod/build/device/health regression suites
  pass. Complete-container composition comparisons preserve Blocky and rootless runtime hints.
- Mosquitto's broker and helper have matching literal image references and `systemd` precedes
  `container`, following the owner's explicit exception to the earlier anchor decision. Its
  broker Quadlet and password-helper unit render unchanged; no operational behavior is changed.
- The guide, image-update runbook, ADR/index and linked proposed inventory/CI notes document
  canonical container authoring. The unmapped NetBox placeholder no longer declares an empty pod.

## Out of Scope

- Inheriting runtime settings or introducing generic whole-object Podman inheritance.
- New include conflict rules, field-level override semantics, pod list merging, or policy-pair
  requirements for container fragments.
- Redesigning builds or deleting the legacy `.image` compatibility path.
- Changing live services, MQTT credentials, the Mosquitto directory fix, or runner state.
- Implementing inventory, CI automation or runtime-audit features.

## Open Questions

None for the approved canonical authoring locations. Any further change to container inheritance
or policy defaults requires separate agreement.

## References

- [Image migration commit 9aed382](https://github.com/moonpie/abhaile/commit/9aed3824adc5df9cd2ea28cd9e6d684abf651c61)
- [ADR 0005: Service Authoring Model](../../adr/0005-service-authoring-model.md)
- [0004: Quadlet Renderer](../accepted/0004-quadlet-renderer.md)
- [0005: Service Composition](../accepted/0005-service-composition.md)
- [0007: Validation Pipeline](../accepted/0007-validation-pipeline.md)
- [0011: Core Services](../accepted/0011-core-services.md)
- [0015: Home Automation](0015-services-home-automation.md)
- [0022: Inventory Generator](../proposed/0022-inventory-generator.md)
- [0024: CI Dependency Automation](../proposed/0024-ci-dependency-automation.md)
