# Adding a New Service

Sequential checklist for adding a service to Abhaile. For design rationale, see
`docs/specs/accepted/0005-service-composition.md` and `docs/adr/0005-service-authoring-model.md`.

## Prerequisites

- [ ] Choose a service name (lowercase, hyphenated, matches directory name)
- [ ] Allocate a `/32` address in the `172.20.20.200–254` range (or `172.20.100.200–254` for DMZ)
- [ ] Decide the pattern: **container**, **pod**, **rootless container**, or **host-mode**
- [ ] Decide the host: phobos, deimos, or both

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

### 3. Add to host mapping

- [ ] Add service name to `config/mapping.yaml` under the target host(s)

### 4. Create quadlet sources (container/pod only)

- [ ] Create `config/services/<name>/quadlets/` directory
- [ ] Add `container.container.j2` (or `pod.pod.j2` + per-container dirs)
- [ ] Add `image.image` if template uses `{{ image }}`
- [ ] Or add `build.build` if template uses `{{ build }}`
- [ ] All source files must exist before first render attempt
- [ ] All quadlet files must end with a trailing newline

### 5. Update DNS serial

- [ ] Render: `abhaile-render --host <host> --output ./out` — fails with content_hash mismatch
- [ ] Update the zone `serial` in `config/network.yaml`: set `date` to `YYYYMMDD`, `counter` to `00`, paste `content_hash`

## Pattern: Simple Container

Reference: `config/services/blocky/service.yaml`

- [ ] Set `podman.user: root` and `podman.network: ipvlan-l2`
- [ ] Add `composition.container.named_volumes[]` for persistent data
- [ ] Add `composition.container.mounted_files[]` for bind-mounted config files
- [ ] Add `composition.config[]` for rendered config files
- [ ] Create `quadlets/container.container.j2` and `quadlets/image.image`

Shared volumes: if multiple services use the same `host_path`, all must set `shared: true`.

## Pattern: Pod Service

Reference: `config/services/authelia/service.yaml`

- [ ] Set `podman.user: root` and `podman.network: ipvlan-l2`
- [ ] Add `composition.pod.containers[]` with `name` + `container.named_volumes[]`
- [ ] Create `quadlets/pod.pod.j2`
- [ ] Per container: create `quadlets/<container-name>/container.container.j2` + `image.image`

## Pattern: Rootless Container

Reference: `config/services/vault-agent/service.yaml`

- [ ] Set `podman.user: <username>` and `podman.network: host`
- [ ] Add `composition.container.named_volumes[]` and config entries
- [ ] Create quadlet sources under `quadlets/`

Output placed under `/home/<user>/.config/containers/systemd/` (not `/etc/containers/systemd/`).

## Pattern: Host-Mode Service

Reference: `config/services/coredns-filtered/service.yaml`

- [ ] Set `systemd.network: service-32` (or `host`)
- [ ] Add `composition.config[]` for config files
- [ ] Add `composition.systemd[]` for unit files (set `enable: true`, `start: true`)
- [ ] Set `apply.restart_unit: <unit>.service` for config-change restarts

## Optional: Vault-Agent Secrets

- [ ] Create `.ctmpl` template(s) in `config/services/<name>/templates/`
- [ ] Add `composition.vault_agent.templates[]` entries
- [ ] Create Vault policy for AppRole access
- [ ] Seed credentials in Vault KV

## Optional: Caddy Ingress

- [ ] Create Caddyfile snippet in `config/services/<name>/caddy/`
- [ ] Add `composition.ingress.internal.blocks[]` referencing it
- [ ] Add CNAME record in `config/network.yaml` DNS section

## Verification

- [ ] `abhaile-render --host <host> --output ./out` exits 0
- [ ] `grep '<name>' out/rendered/manifest.json` shows entries
- [ ] `abhaile-diff --desired-manifest out/rendered/manifest.json` shows new entries as `added`
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
| Host-mode (restart) | `chrony-a` | `apply.restart_unit`, template config |
