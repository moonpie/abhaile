# Adding a New Service

Sequential checklist for adding a service to Abhaile. For design rationale, see
[Spec 0005](../specs/accepted/0005-service-composition.md) and
[ADR 0005](../adr/0005-service-authoring-model.md).

## Prerequisites

- [ ] Choose a service name (lowercase, hyphenated, matches directory name)
- [ ] Allocate a `/32` address in the `172.20.20.200–254` range (or `172.20.100.200–254` for DMZ)
- [ ] Decide the pattern: **container**, **pod**, **rootless container**, or **host-mode**
- [ ] Decide the host: phobos, deimos, or both

The enrollment contract in [active spec 0034](../specs/active/0034-host-and-service-enrollment.md)
covers native services, rootful/rootless containers and pods, managed builds, and configuration-only
or shared definitions. Implementation and verification progress are recorded there. A service
must not depend on its own previous manual installation. Declare needed accounts, supported
packages, directories and networking in host/service intent, and arrange operator-owned Vault or
other external prerequisites before activation. Preserve existing applications and data; conflicting
identities or runtime volume/network options require resolution rather than destructive adoption.

## Publish Prerequisites Before Service Activation

Deliver a new service in two parts when it needs operator-applied prerequisites, such as Vault
policy changes. Authoring the complete service locally does not mean publishing all changes
together. Keep the two parts in separately reviewable commits. If there are no separate
prerequisites, record that in the spec rather than creating an empty prerequisite commit.

### Part 1: Prerequisite Push

- [ ] Include canonical policy changes under `policies/` and the deployment instructions.
- [ ] Keep service enrollment, address/DNS changes, units, Quadlets, secret-template enrollment,
  and supporting activation code/tests in part 2. Include changes to shared mapped compositions
  in that review: they can activate behaviour even without a new mapping entry.
- [ ] Render the prerequisite-only revision and its base for all hosts into separate output roots;
  confirm their desired artifacts and manifests are identical. Do not compare against the complete
  working tree if it already contains part 2.
- [ ] Review and publish part 1. A commit on the runner's polled branch still triggers ordinary
  reconciliation and can repair existing drift, even when rendered desired state is unchanged.
- [ ] Confirm the target checkout contains the reviewed prerequisite revision and is clean before
  using its policy files.
- [ ] Provision runtime secret values through the protected-file workflow and apply the canonical
  policy as the human Vault admin. Record completion in the spec without credential values.

For a protected `/opt/abhaile` checkout, the admin can read the canonical policy through sudo
while keeping Vault authentication in their own shell:

```bash
set -o pipefail
sudo cat /opt/abhaile/policies/vault-agent.hcl |
  vault policy write vault-agent -
vault policy read vault-agent
```

Run this only after reviewing the policy from the intended revision. Policy files contain ACLs,
not secret values. They are applied explicitly; the renderer and runner do not upload them to Vault.
Applying a policy alone does not install a service's new Vault Agent templates.

### Part 2: Activation Push and Host Validation

- [ ] Include the complete deployment definition, mapping, network/DNS changes, helper code,
  templates, and tests. Keep schema, renderer and service migrations together in a coherent
  revision. Record the exact reviewed activation commit SHA.
- [ ] Confirm operator-applied prerequisites from part 1 are complete before publishing activation.
- [ ] Run local validation and render every affected host into temporary output roots. Review the
  complete desired-state change, including other services affected by shared definitions.
- [ ] Verify host-side Python helpers work with the bootstrap installation model. Bootstrap
  installs dependencies and source-path CLI wrappers; it does not guarantee an editable/package
  install. A unit using `python -m abhaile...` must set `PYTHONPATH=/opt/abhaile/src` explicitly
  or use a supported managed entrypoint.
- [ ] When deployment is intended, push the reviewed activation revision to `main`, the normal
  runner-polled branch. That publication authorizes normal automatic reconciliation on the hosts.
- [ ] Follow the runner's normal sequence: fetch/select the revision, render, run Ansible check
  mode, apply only after check mode succeeds, then perform health checks. Let the active run finish;
  do not interrupt apply, change its checkout, or edit runner recovery records.
- [ ] Confirm the finished runner summary identifies the intended revision. Record host check-mode
  and reconciliation results. A failure before apply is not evidence of successful deployment;
  inspect diagnostics and fix the candidate through git.
- [ ] Verify Vault template delivery, service startup, authentication, persistent state,
  idempotence, and reboot recovery as required by the active service spec.

Review branches and manual candidate checkout testing are optional. Normal publication to `main`
uses the runner's render/check gate and does not require a separate review-branch promotion or a
routine timer suspension. For an independent manual check, use
[the privilege-separated host workflow](../runbooks/operations.md#host-render-and-privileged-check)
and coordinate any checkout changes with the runner so no active reconciliation is interrupted.

The two parts separate operator prerequisites from activation. Record the observed check phase
from the normal runner or an optional manual check; pushing to `main` can deploy automatically
once that gate passes.

## Core Checklist (All Services)

### 1. Register the address

- [ ] Add entry to `config/network.yaml` → `services.<name>`:

```yaml
myservice:
  address: 172.20.20.XXX/32
  vlan: services
  dns:
    - zone: svc.abhaile.home.arpa.
      records:
        - type: a
          name: myservice
          rdata: "%%network.services.myservice.address | strip_cidr%%"
          ptr: true
```

### 2. Create the service definition

- [ ] Create `config/services/<name>/service.yaml` with required fields:

```yaml
name: <name>
composition: {}
```

- [ ] Add `podman:` block (container/pod/rootless) or `systemd:` block (host-mode)
- [ ] Populate `composition:` block (see pattern-specific steps below)

Schema requirements:

The following image-authoring contract is implemented under active spec 0032; completion evidence
and delivery status are tracked in that spec.

- Both `name` and `composition` are always required
- A `podman` block contains only the required `user` and `network` fields.
- Each mapped Podman service declares `user` and `network` locally; these fields are never
  inherited. Shared container definitions need no `podman` block.
- Standalone images belong to `composition.container.image`; pod-member images belong to
  `composition.pod.containers[].container.image`. Both use the same container definition schema.
- A declared pod requires at least one member in `containers`; each member requires `name` and
  a nested `container` object.
- `pull_policy` is optional in that container object and defaults to `missing` during rendering.
  Service-level and pod-member wrapper-level image/policy declarations are rejected.
- `composition` must include `pod`, `container`, or `include` when `podman` is present.
- Rootless services (`podman.user` ≠ `root`) may use `host` or `container:<name>`, not `ipvlan-l2`.
- Existing container-composition selection and local builds remain supported. There is no
  service-level registry image fallback.

For example, `blocky-common.composition.container` declares the shared image once while `blocky-a`
and `blocky-b` each declare their runtime context and include the common container definition. See
[spec 0032](../specs/accepted/0032-container-image-authoring.md) for the full contract, including
the supported include-only container pattern that predates this change.

A non-empty local `composition.container` replaces the inherited container definition. If you
add local volumes, mounted files, or other container settings, supply the image and all other
needed settings in that local object too. Alternatively, keep the complete container definition
in the shared composition. An inherited image is not merged into a local container automatically.

Pre-commit validates individual files and runs a project check for mapped services and their
include closures. The project check runs on every commit, including deletion-only commits, so
removing an included definition cannot bypass validation. Run it independently with:

```bash
.venv/bin/python scripts/validate-services.py
```

It requires no render, network access, Vault credentials or host privileges. CLI render performs
the same service checks before generating any artifacts.

### 3. Add to host mapping

- [ ] Add service name to `config/mapping.yaml` under the target host(s)

### 4. Create quadlet sources (container/pod only)

- [ ] Create `config/services/<name>/quadlets/` directory
- [ ] Add `container.container.j2` (or `pod.pod.j2` + per-container dirs)
- [ ] Set the registry image in service configuration; templates use `{{ image }}` directly
- [ ] Or add `build.build` if template uses `{{ build }}`
- [ ] All source files must exist before first render attempt
- [ ] All quadlet files must end with a trailing newline

### 5. Update DNS serial

- [ ] Render: `abhaile-render --host <host> --output ./out` — fails with content_hash mismatch
- [ ] Update the zone `serial` in `config/network.yaml`: set `date` to `YYYYMMDD`, `counter` to `00`, paste `content_hash`

## Pattern: Simple Container

Reference: `config/services/blocky-a/service.yaml` and `config/services/blocky-common/service.yaml`

- [ ] Set `podman.user: root` and `podman.network: ipvlan-l2`
- [ ] Set `image: <registry>/<image>:<version>` in `composition.container`, directly or through
  an included container definition, and optionally set `pull_policy: missing` there
- [ ] Add `composition.container.named_volumes[]` for persistent data
  - If multiple services use the same `host_path`, all must set `shared: true`
  - Private rootful volumes require `host_owner` and `host_group`; `host_mode` defaults to `0750`.
    Rootless owner/group default to the runtime user. Only the host directory's own metadata is
    managed; application-created descendants are untouched. There is no ownership opt-out.
- [ ] Add `composition.container.mounted_files[]` for bind-mounted config files
- [ ] Add `composition.config[]` for rendered config files
- [ ] If a config parent is a private named-volume host directory, its volume declaration already
  supplies managed directory intent; do not duplicate it in `composition.config[]`.
- [ ] Review inferred parents for other managed files. Rootful parents default to `root:root`
  mode `0755`; rootless private parents default to their runtime user/group and mode `0700`.
  Outside the user's home, more distant ancestors default to `root:root` mode `0755` so another
  service does not inherit a private ancestor. Distribution roots and account homes remain
  prerequisites. Declare a directory with `destination`, `owner`, `group`, and `mode` when these
  defaults are unsuitable. Explicit metadata takes precedence; conflicting inferred metadata
  fails rather than depending on render order. Incidental output directories alone are not intent.
- [ ] Create `quadlets/container.container.j2`; include `Image={{ image }}` and
  `Pull={{ pull_policy }}`

See [spec 0033](../specs/active/0033-private-volume-directory-management.md) for private volume-root
management and [spec 0034](../specs/active/0034-host-and-service-enrollment.md) for the subsequent
managed-file parent provisioning and enrollment contract.

## Pattern: Pod Service

Reference: `config/services/authelia/service.yaml`

- [ ] Set `podman.user: root` and `podman.network: ipvlan-l2`
- [ ] Add at least one `composition.pod.containers[]` member, each with `name` and nested
  `container`; registry-backed members set `container.image`, optional `container.pull_policy`,
  and any `container.named_volumes[]`
- [ ] Create `quadlets/pod.pod.j2`
- [ ] Per container: create `quadlets/<container-name>/container.container.j2`; include
  `Image={{ image }}` and `Pull={{ pull_policy }}`

## Pattern: Managed Local Build

- [ ] Create `quadlets/build.build` with `Pull=missing`; do not use `Policy=`
- [ ] Declare `build.output_image`, `build.pull_policy: missing`, and all material `build.inputs`
- [ ] Add `build.consumers[]` for services restarted after output image verification
- [ ] For install workflows, add `build.post_build.install_unit` and optional
  `build.post_build.verify_binary`
- [ ] Keep runtime `.container` references pointed at the local build output, for example
  `Image={{ build }}`

## Pattern: Rootless Container

Reference: `config/services/vault-agent/service.yaml`

- [ ] Set `podman.user: <username>` and `podman.network: host`
- [ ] Set `image: <registry>/<image>:<version>` in `composition.container`, directly or through
  an included container definition, and optionally set `pull_policy: missing` there
- [ ] Add `composition.container.named_volumes[]` and config entries
- [ ] Create quadlet sources under `quadlets/`

Output placed under `/home/<user>/.config/containers/systemd/` (not `/etc/containers/systemd/`).
The supported runtime account home is `/home/<user>`; a different account home is rejected rather
than publishing units to a directory its user manager does not read. Rootless pods use the same
named-user execution context and nested container definitions as other pods.

For a new rootless account, declare its user/group in host `composition.user_management`, including
that home and an explicit `rootless` mapping with `subuid_start`, `subgid_start`, and `count`.
Each start and the count must be at least `65536`; select non-overlapping subordinate ranges and
retain compatible existing assignments. `rootless.linger` defaults to `true`; `false` preserves
existing lingering policy without enabling or disabling it. Reconciliation prepares the user
manager before workload activation. It does not renumber existing accounts or namespace ranges.

## Pattern: Host-Mode Service

Reference: `config/services/coredns-filtered/service.yaml`

- [ ] Set `systemd.network: service-32` (or `host`)
- [ ] Add `composition.config[]` for config files
- [ ] Add `composition.systemd[]` for unit files (set `enable: true`, `start: true`)
- [ ] Set `apply.config_change_restart_unit: <unit>.service` for config-change restarts

When customizing a packaged daemon such as Chrony or ddclient, place its drop-in in
`composition.systemd`. A drop-in's `enable` and `start` fields refer to the parent vendor unit,
not the drop-in filename. Package installation and all configuration publication precede parent
activation; a changed drop-in refreshes the parent. Keep successful oneshots and path/timer triggers
distinct from long-running daemon readiness.

Declare supported standard packages in host software intent. Existing managed Quadlet builds
remain available for local image or binary production. Command-oriented software downloads,
builds and commands remain rendered records, not automatically executed installers. Record any
unsupported acquisition, hardware, kernel-driver, firmware or device-access prerequisites and
complete them explicitly; enrollment must not assume that a previous manual service installed them.

## Optional: Vault-Agent Secrets

- [ ] Create `.ctmpl` template(s) in `config/services/<name>/templates/`
- [ ] Add `composition.vault_agent.templates[]` entries
- [ ] Publish and apply the canonical Vault policy through part 1 before activating new templates
- [ ] Seed credentials in Vault KV without committing or displaying their values
- [ ] If a container needs copied secret output before startup, add a
  service-owned oneshot copy unit and make the container `Requires=` /
  `After=` that unit
- [ ] If the same secret output needs refresh handling, add a path unit that
  starts the same copy unit
- [ ] Use `systemctl try-restart` in copy-unit post actions so first startup
  and refresh can share the unit safely

## Optional: Caddy Ingress

- [ ] Create Caddyfile snippet in `config/services/<name>/caddy/`
- [ ] Add `composition.ingress.internal.blocks[]` referencing it
- [ ] Add CNAME record in `config/network.yaml` DNS section

## Verification

- [ ] `abhaile-render --host <host> --output ./out` exits 0
- [ ] `grep '<name>' out/rendered/manifest.json` shows entries
- [ ] On the target host, render as `abhaile` and run the privileged Ansible check using the
  [host-check workflow](../runbooks/operations.md#host-render-and-privileged-check)
- [ ] `abhaile-render --all --output ./out` passes (no cross-host regression)
- [ ] `make test && make lint` passes

## Reference Services

| Pattern | Example | Key features |
|---------|---------|--------------|
| Simple container | `blocky` | ipvlan-l2, static config, shared volume |
| Container + secrets | `caddy-dmz` | vault_agent templates, custom build |
| Pod + secrets + ingress | `authelia` | Pod with sidecar, path watchers, ingress |
| Rootless container | `vault-agent` | Rootless podman, host network |
| Host-mode (service-32) | `coredns-filtered` | Includes, template variables |
| Host-mode (restart) | `chrony-a` | `apply.config_change_restart_unit`, template config |
