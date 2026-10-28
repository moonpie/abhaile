# Adding a New Service

Sequential checklist for adding a service to Abhaile. For design rationale, see
[Spec 0005](../specs/accepted/0005-service-composition.md) and
[ADR 0005](../adr/0005-service-authoring-model.md).

## Prerequisites

- [ ] Choose a service name (lowercase, hyphenated, matches directory name)
- [ ] Allocate a `/32` address in the `172.20.20.200–254` range (or `172.20.100.200–254` for DMZ)
- [ ] Decide the pattern: **container**, **pod**, **rootless container**, or **host-mode**
- [ ] Decide the host: phobos, deimos, or both

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
  templates, and tests. Record the exact reviewed activation commit SHA.
- [ ] Publish the candidate to a non-polled review branch first. Publishing directly to the
  polled branch can trigger live deployment before operator validation.
- [ ] Before changing a managed host checkout for candidate testing, arrange an approved
  maintenance window: suspend automatic scheduling, let active reconciliation finish, and verify
  there is no running transaction or conflicting runner lock. Cover every host polling the
  activation branch; shared DNS changes can affect hosts beyond the new service's host.
- [ ] Fetch and select the exact reviewed candidate in a clean target checkout. Record the
  previous revision so a failed check can return to the accepted checkout. Do not interrupt an
  active apply, overwrite local work, or edit runner recovery records.
- [ ] Verify host-side Python helpers work with the bootstrap installation model. Bootstrap
  installs dependencies and source-path CLI wrappers; it does not guarantee an editable/package
  install. A unit using `python -m abhaile...` must set `PYTHONPATH=/opt/abhaile/src` explicitly
  or use a supported managed entrypoint.
- [ ] On each affected host, render as `abhaile`, then run Ansible check mode with sudo using
  [the explicit privilege-separated workflow](../runbooks/operations.md#host-render-and-privileged-check).
  Check the complete host plan, not just the newly added service.
- [ ] Resolve failures and recheck the final candidate. If checks fail, restore the previously
  accepted checkout before resuming its normal scheduling; leave a failed activation unpublished.
- [ ] After explicit live approval, promote that exact checked commit to the polled branch and
  reconcile it through the runner. Keep scheduling controlled until prerequisite and check gates
  have passed. Restore normal timer scheduling for the authorized run and its health checks.
- [ ] Verify Vault template delivery, service startup, authentication, persistent state,
  idempotence, and reboot recovery; record evidence in the active spec.

The two parts are delivery stages, not a requirement to use exactly two `git push` commands:
review-branch publication and promotion may require separate pushes. Publishing the activation
commit to the polled branch is a deployment action when automatic reconciliation is enabled.

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

- Both `name` and `composition` are always required
- If `podman:` is present, requires `user` and `network`; `composition` must include `pod` or `container`
- Rootless services (`podman.user` ≠ `root`) can only use `network: host` — not `ipvlan-l2`
- Registry-backed containers set `podman.image` or per-container `image`; `pull_policy` defaults to
  `missing`

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

Reference: `config/services/blocky/service.yaml`

- [ ] Set `podman.user: root` and `podman.network: ipvlan-l2`
- [ ] Set `podman.image: <registry>/<image>:<version>` and optionally
  `podman.pull_policy: missing`
- [ ] Add `composition.container.named_volumes[]` for persistent data
  - If multiple services use the same `host_path`, all must set `shared: true`
- [ ] Add `composition.container.mounted_files[]` for bind-mounted config files
- [ ] Add `composition.config[]` for rendered config files
- [ ] Create `quadlets/container.container.j2`; include `Image={{ image }}` and
  `Pull={{ pull_policy }}`

## Pattern: Pod Service

Reference: `config/services/authelia/service.yaml`

- [ ] Set `podman.user: root` and `podman.network: ipvlan-l2`
- [ ] Add `composition.pod.containers[]` with `name`, `image`, optional `pull_policy`,
  and `container.named_volumes[]`
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
- [ ] Set `podman.image: <registry>/<image>:<version>` and optionally
  `podman.pull_policy: missing`
- [ ] Add `composition.container.named_volumes[]` and config entries
- [ ] Create quadlet sources under `quadlets/`

Output placed under `/home/<user>/.config/containers/systemd/` (not `/etc/containers/systemd/`).

## Pattern: Host-Mode Service

Reference: `config/services/coredns-filtered/service.yaml`

- [ ] Set `systemd.network: service-32` (or `host`)
- [ ] Add `composition.config[]` for config files
- [ ] Add `composition.systemd[]` for unit files (set `enable: true`, `start: true`)
- [ ] Set `apply.config_change_restart_unit: <unit>.service` for config-change restarts

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
