# Spec: Quadlet Renderer

## Metadata

```yaml
id: SPEC-2026-004
title: Quadlet Renderer
status: accepted
owner: moonpie
created: 2026-06-04
updated: 2026-06-05
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

The quadlet renderer is fully implemented and in active use. This accepted spec
documents the delivered behavior as reference documentation for operations,
maintenance, and future drift reviews.

The implemented scope combines:

1. Service quadlet rendering for both single-container and pod-based services.
1. Rootful versus rootless output placement and apply metadata hints.
1. Named-volume and mounted-file handling, including shared-volume reuse rules.
1. VLAN-aware network attachment and shared network quadlet generation.
1. Generated file naming and ownership/dependency contracts consumed by diff/apply.
1. Service composition/include and schema contracts that gate quadlet rendering.

## Requirements

- [x] Document implemented container rendering behavior and file contracts.
- [x] Document implemented pod rendering behavior and naming contracts.
- [x] Document rootful versus rootless output paths and apply-hint behavior.
- [x] Document volume handling, including shared-volume and host-path reuse rules.
- [x] Document network attachment behavior for `ipvlan-l2`, `host`, and `container:*` modes.
- [x] Document generated quadlet artifact kind/owner contracts used by apply.
- [x] Record TODO Decision Log outcomes related to quadlets and service composition.
- [x] Document current automated test coverage boundaries for include-based pod/container resolution.
- [x] Document that include-only pod/container inheritance is unsupported for service authoring.

## Constraints

- Source of truth is `config/services/*/service.yaml` plus shared templates under `config/_templates/`.
- Renderer behavior is deterministic for identical config and network inputs.
- Services without `podman` blocks are skipped by quadlet rendering.
- By schema contract, services with `podman` must define either `composition.container`
  or `composition.pod` directly in that service file (`schemas/service.schema.json`).
- Renderer code includes include-aware pod/container fallback resolution, but include-only
  pod/container authoring is not currently a schema-valid contract.
- Include-aware pod/container fallback resolution is treated as internal compatibility behavior,
  not a supported authoring interface.
- For `ipvlan-l2` services, `network.services.<service>.vlan` must exist in `config/network.yaml`.
- Rootless services cannot use `ipvlan-l2` by schema contract (`schemas/service.schema.json`).
- Rendered outputs are generated under render output trees; manual edits under rendered output are out of scope.

## Design

### Render Entry Point and Host Flow

`render_service_quadlets()` in `src/abhaile/renderers/quadlets/renderer.py` is invoked per host
from `src/abhaile/cli/render.py` after service config rendering.

Per-service behavior:

1. Read `config/services/<service>/service.yaml`.
1. Skip if no `podman` block is present.
1. Resolve `composition.pod` and `composition.container` via include-aware helpers:
   - `_resolve_pod_definition()`
   - `_resolve_container_definition()`
1. Prefer pod path when pod definition is present; otherwise render container path.
1. Track used VLANs and emit deduplicated network quadlets once per host/VLAN.

Include resolution is implemented through `resolve_composition()` and depth-first include traversal
from `src/abhaile/utils/composition.py`, with cycle detection and fail-fast `RenderError` paths.

Current validation boundary:

- Include-aware fallback resolution in quadlet helpers exists in implementation.
- Current repository tests do not include a schema-valid fixture where pod/container
  definitions are inherited solely via include; include coverage is limited to no-crash/smoke
  verification for quadlet rendering.
- Include-only inherited pod/container definitions are therefore implementation detail,
  not supported authoring contract; operators must define `composition.pod` or
  `composition.container` directly on podman services.

### Container Rendering Contract

Container-service rendering (`composition.container`) expects service-level quadlet files under
`config/services/<service>/quadlets/`.

Supported service-level sources:

- `container.container.j2` -> rendered to `<service>.container`
- `image.image` -> copied to `<service>.image`
- `build.build` -> copied to `<service>.build`
- Other static files at the quadlets root -> copied as-is

Contract details:

- Only files in the immediate service quadlets directory are rendered for container services.
- `container.container.j2` is the only supported template filename for container units.
- Template variables include: `network`, `host_name`, `service_name`, `volume_lines`, `image`, `build`.
- If template references `{{ image }}` or `{{ build }}` and corresponding source file is absent,
  rendering fails with explicit `RenderError`.
- Source quadlet files/templates must end with a trailing newline.

### Pod Rendering Contract

Pod-service rendering (`composition.pod`) uses the naming pattern introduced in TODO decisions:

- Pod unit file: `<service>-app.pod`
- Container unit files: `<service>-app-<container>.container`
- Container image/build files: `<service>-app-<container>.image|build`
- Non-shared volume files: `<service>-app-<container>-<volume>.volume`

Pod source structure:

- Pod template at `config/services/<service>/quadlets/pod.pod.j2`
- Per-container sources under `config/services/<service>/quadlets/<container-name>/`
  containing `container.container.j2` plus optional `image.image`/`build.build`

Each rendered pod container receives `pod=<service>-app.pod` in template context.
Container definitions are read from `containers[].container` when present, otherwise from the
container object itself.

### Rootful Versus Rootless Output

Output root is derived from `podman.user`:

- Rootful (`user: root`): `/etc/containers/systemd`
- Rootless (`user: <non-root>`): `/home/<user>/.config/containers/systemd`

This affects both output file paths and artifact/apply hints:

- `apply_hints.rootless` is set to `false` for rootful, `true` for rootless.
- `apply_hints.podman_user` is set for rootless artifacts.

`schemas/service.schema.json` enforces network-mode constraints aligned with this behavior:

- Rootful `podman.network`: `ipvlan-l2`, `host`, or `container:*`
- Rootless `podman.network`: `host` or `container:*`

### Volume Handling Contract

Named volumes are rendered from `composition.container.named_volumes` and pod container
`named_volumes` entries.

Each named volume requires:

- `name`
- `host_path`
- `mount_path`

Volume file and mount-line behavior:

- Non-shared named volumes are service/container-prefixed.
- Shared named volumes (`shared: true`) render to shared output path with unprefixed
  `<name>.volume` filenames. Shared volumes (used by multiple containers in a pod or
  across services) render to a `_shared/` subdirectory. For example, a shared `host-certs`
  volume renders to `<service>/_shared/host-certs.volume` rather than being prefixed with
  the container name.
- Container `Volume=` lines combine named volumes and `mounted_files` entries.
- Optional per-mount `mode` appends as suffix (`:ro`, etc.).

Host-path reuse enforcement (per Podman user):

- Duplicate `host_path` usage requires `shared: true` on all uses.
- Shared uses must resolve to the same shared volume filename.
- Violations raise `RenderError` and stop rendering.

### Network Attachment and Quadlet Generation

For services with `podman.network: ipvlan-l2`:

- Renderer resolves VLAN from `network.services.<service>.vlan`.
- Service/pod owner dependencies include `unit:<vlan>-network.service`.
- VLAN names are deduplicated and rendered once to `podman-networks/etc/containers/systemd/<vlan>.network`.

Network quadlets are rendered from `config/_templates/services/quadlets/network.network.j2`
and are currently rootful shared artifacts (`apply_hints: {rootless: false, shared: true}`).

For `host` and `container:*` network modes:

- No VLAN lookup or network quadlet generation is performed by quadlet renderer.
- Resulting behavior depends on service-provided container/pod templates.

### Artifact and Ownership Contracts

`src/abhaile/renderers/quadlets/helpers.py` defines file-suffix to artifact-kind mapping:

- `.container` -> `quadlet.container`
- `.pod` -> `quadlet.pod`
- `.image` -> `quadlet.image`
- `.build` -> `quadlet.build`
- `.volume` -> `quadlet.volume`
- `.network` -> `quadlet.network`

Owner refs derive from systemd unit naming:

- Containers/pods: `<stem>.service`
- Images/builds/volumes/networks: `<stem>-<type>.service`

Owner dependency contracts are emitted for:

- Pod containers requiring pod owner and volume/image/build owners.
- Container owners requiring volume/image/build owners.
- `ipvlan-l2` pod/container owners requiring VLAN network owner.

This dependency graph is consumed by diff/apply quadlet convergence and execution phases.

### Service Renderer Interaction

`src/abhaile/renderers/services.py` establishes companion service behavior that interacts with
quadlet-managed services:

- Include-first composition resolution for `composition.config` and `composition.systemd`.
- Apply hints for service-owned files (explicit config-change restarts, rootless context hints).
- Systemd entry apply hints for enable/start semantics.

Operationally, quadlet and service renderers share the same service composition model and rootless
metadata strategy, which keeps downstream apply execution consistent for mixed service artifacts.

### Known Limitations

- Include-only pod/container inheritance is implementation detail, not supported service authoring.
- Schema validation is expected to reject podman services that omit direct
  `composition.pod`/`composition.container` declarations.
- Current quadlet include coverage confirms non-crash behavior, but does not certify
  include-only inheritance as a supported config contract.

## Decision Notes

- Decision: Use `-app` naming for pod units and pod container artifacts.

- Rationale: Distinguishes pod-scoped artifacts from standalone container units and keeps naming deterministic.

- Impact: Pod files and dependent owner refs are consistently discoverable and testable.

- ADR: null

- Decision: Derive quadlet output roots from `podman.user` and encode rootless context in apply hints.

- Rationale: Align with podman/systemd conventions for rootful and rootless unit locations.

- Impact: Apply executor can run correct systemd scope/user logic for changed quadlet owners.

- ADR: null

- Decision: Enforce per-user host-path reuse rules with required shared-volume declaration.

- Rationale: Prevent ambiguous duplicate mounts and inconsistent volume object identity.

- Impact: Misconfigured duplicate mounts fail fast instead of creating conflicting runtime state.

- ADR: null

- Decision: Render one network quadlet per used VLAN and attach explicit owner dependencies from dependent units.

- Rationale: Avoid duplicate network artifacts while preserving deterministic start/reload ordering.

- Impact: Shared network updates can be converged safely with dependent container/pod units.

- ADR: null

- Decision: Resolve pod/container definitions through include-aware composition traversal with cycle detection.

- Rationale: Keep composition semantics consistent across renderers and support reusable base service composition.

- Impact: Renderer internals can resolve included pod/container definitions and include cycles fail with
  clear errors; however, include-only pod/container authoring remains unsupported by current schema.

- ADR: null

- Decision: Keep include-only pod/container inheritance out of the supported service authoring contract.

- Rationale: Current schema (`schemas/service.schema.json`) requires direct pod/container declaration for
  podman services, and existing tests do not validate include-only fixtures as a supported behavior.

- Impact: Operators and reviewers should treat include-only pod/container inheritance as non-contractual
  implementation detail until a future spec explicitly promotes it with schema and test changes.

- ADR: null

## Acceptance Criteria

- [x] Accepted spec documents implemented container quadlet rendering and file contracts.
- [x] Accepted spec documents implemented pod rendering behavior and naming contracts.
- [x] Accepted spec documents rootful/rootless output behavior and apply metadata assumptions.
- [x] Accepted spec documents volume handling and host-path reuse guardrails.
- [x] Accepted spec documents network attachment and VLAN network-quadlet behavior.
- [x] Accepted spec documents generated quadlet kind/owner/dependency contracts.
- [x] Accepted spec records relevant TODO Decision Log outcomes for quadlets/services.
- [x] Accepted spec documents current automated test coverage boundary for include-based
  pod/container resolution.
- [x] Accepted spec documents include-only inheritance as unsupported and out of scope.

### Evidence

Criterion: Container rendering contract.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51`
  (`docs/specs/accepted/implementation-evidence.md`),
  `src/abhaile/renderers/quadlets/renderer.py`, `src/abhaile/renderers/quadlets/container.py`.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_container.py`, `tests/integration/test_quadlets.py`.

Criterion: Pod rendering and naming contract.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51`
  (`docs/specs/accepted/implementation-evidence.md`),
  `src/abhaile/renderers/quadlets/pod.py`.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_pod.py`, `tests/integration/test_quadlets.py`.

Criterion: Rootful/rootless output and metadata hints.

- Implementation evidence: commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78`
  (`docs/specs/accepted/implementation-evidence.md`),
  `src/abhaile/renderers/quadlets/volumes.py` (`_quadlet_output_root`),
  `src/abhaile/renderers/quadlets/container.py`, `src/abhaile/renderers/quadlets/pod.py`.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_container.py` (`test_rootless_container_path`),
  `tests/unit/python/renderers/test_quadlets_pod.py` (`test_pod_rootless_user`).

Criterion: Volume handling and host-path reuse rules.

- Implementation evidence: commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78`
  (`docs/specs/accepted/implementation-evidence.md`),
  `src/abhaile/renderers/quadlets/volumes.py`.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_container.py`
  (`test_shared_volumes_no_service_prefix`, duplicate host-path error tests),
  `tests/unit/python/renderers/test_quadlets_pod.py` (`test_pod_with_shared_volume`).

Criterion: Network attachment and VLAN network quadlets.

- Implementation evidence: commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78`
  (`docs/specs/accepted/implementation-evidence.md`),
  `src/abhaile/renderers/quadlets/network.py`, `src/abhaile/renderers/quadlets/renderer.py`.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_container.py` (`test_network_quadlets_deduped`),
  `tests/integration/test_quadlets.py` (`test_render_network_quadlets_for_vlans`).

Criterion: Artifact kind/owner/dependency contracts.

- Implementation evidence: commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78`
  (`docs/specs/accepted/implementation-evidence.md`),
  `src/abhaile/renderers/quadlets/helpers.py`,
  `src/abhaile/renderers/quadlets/container.py`, `src/abhaile/renderers/quadlets/pod.py`.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_container.py` (`test_registers_container_metadata`),
  `tests/unit/python/renderers/test_quadlets_pod.py` (`test_registers_pod_metadata`),
  `tests/unit/python/apply/test_quadlet_executor.py`.

Criterion: Service/schema/decision-log alignment.

- Implementation evidence: commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78`
  (`docs/specs/accepted/implementation-evidence.md`),
  `src/abhaile/renderers/services.py`, `schemas/service.schema.json`,
  representative service definitions under `config/services/*/service.yaml`.
- Validation evidence: `tests/integration/test_composition_includes.py`,
  `tests/unit/python/renderers/test_quadlets_validation.py`, TODO historical decisions in `TODO.md`
  (entries dated 2026-02-04, 2026-02-06, 2026-02-07).

Criterion: Include-resolution testability boundary.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51`
  (`docs/specs/accepted/implementation-evidence.md`),
  include-aware helpers in `src/abhaile/renderers/quadlets/container.py` and
  `src/abhaile/renderers/quadlets/pod.py`.
- Validation evidence: `tests/integration/test_composition_includes.py`
  (`test_quadlets_resolves_container_from_includes`) currently validates non-crash behavior,
  not include-only inherited pod/container fixtures.

Criterion: Include-only inheritance is unsupported.

- Implementation evidence: commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78`
  (`docs/specs/accepted/implementation-evidence.md`),
  `schemas/service.schema.json` requires direct `composition.pod` or
  `composition.container` for podman services.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_validation.py`
  and pre-commit schema validation path for service definitions.

## Out of Scope

- Introducing new quadlet artifact types or unit-execution semantics.
- Changes to podman runtime behavior outside rendered quadlet contracts.
- Extending schema with additional podman/network modes.
- Reworking apply executor behavior beyond currently emitted owner/apply hints.
- Promoting include-only pod/container inheritance to a supported authoring model.

## Open Questions

- None.

## References

- `docs/specs/_template.md`
- `docs/specs/GOVERNANCE.md`
- `docs/specs/accepted/implementation-evidence.md`
- `src/abhaile/renderers/quadlets/renderer.py`
- `src/abhaile/renderers/quadlets/container.py`
- `src/abhaile/renderers/quadlets/pod.py`
- `src/abhaile/renderers/quadlets/network.py`
- `src/abhaile/renderers/quadlets/volumes.py`
- `src/abhaile/renderers/quadlets/helpers.py`
- `src/abhaile/renderers/services.py`
- `src/abhaile/utils/composition.py`
- `src/abhaile/cli/render.py`
- `schemas/service.schema.json`
- `config/services/authelia/service.yaml`
- `config/services/vault-agent/service.yaml`
- `tests/unit/python/renderers/test_quadlets_container.py`
- `tests/unit/python/renderers/test_quadlets_pod.py`
- `tests/unit/python/renderers/test_quadlets_validation.py`
- `tests/unit/python/apply/test_quadlet_executor.py`
- `tests/integration/test_quadlets.py`
- `tests/integration/test_composition_includes.py`
- `TODO.md`
