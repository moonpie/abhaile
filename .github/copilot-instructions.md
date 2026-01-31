# Copilot Instructions

You are working in the Abhaile GitOps repo. The authoritative state lives in `config/`, and the goal is to render/apply host-specific artifacts for Debian hosts (phobos, deimos).

## Big picture

- Render is unprivileged and reads only from `config/`; apply is privileged and enforces safety gates.
- Targets run systemd-networkd and Podman quadlets, with deterministic /32 ipvlan-l2 service addressing and split-horizon DNS.
- Treat rendered output under `out/` as disposable; never edit generated artifacts directly.

## Source of truth & structure

- Host/service placement: `config/mapping.yaml` (e.g., phobos runs ddclient/chrony-a/caddy-\*).
- Network/DNS intent: `config/network.yaml` (VLANs, hosts, service /32s, DNS zones/records). Uses template placeholders like `%%services.caddy-dmz.address | strip_cidr%%`.
- Service definitions: `config/services/<service>/service.yaml` (type: pod/container, mode: rootful/rootless, network, configs, ingress, vault-agent templates).
- Host overlays: `config/hosts/{common,phobos,deimos}/` (software/users/systemd/systemd-networkd/systemd-resolved).
- Shared templates: `config/_templates/**` for host/service rendering.

### Service patterns (examples)

- `config/services/authelia/service.yaml` shows a pod with multiple containers, named volumes, ingress blocks, and vault-agent templates (`*.ctmpl`).
- Service directories often include config/, quadlets/, systemd/, templates/, and caddy ingress fragments.

## Render/apply contract (must-haves)

- Render reads only from `config/` and emits per-host artifacts to `out/rendered/<host>/`.
- Drift/state metadata lives in `out/state/<host>/` for apply/diff.
- Render outputs include systemd-networkd, quadlets, DNS, runtime templates, and service configs.
- Apply validates inputs, stages atomically, updates state, and reloads only changed units.

## Coding Preferences

- Use Python for rendering/transforms; use shell only for host-level apply orchestration.
- Keep dependencies minimal and pinned; document any new dependency.
- Validate config inputs early with clear errors (schema checks preferred).
- Prefer small, composable scripts over monolithic ones.

## Testing and Validation

- Prefer schema validation for config inputs.
- Ensure apply supports a safe dry-run mode.

### Workflows

- `make install` creates the venv and installs `requirements.txt` + pre-commit.
- `make lint` runs pre-commit hooks across the repo.

## Guardrails

- Prefer changes in `config/` over hard-coded script edits.
- Do not commit secrets; use templates and vault-agent outputs.
- Keep render deterministic and idempotent; apply is safe by default (dry-run unless explicit).
- If behavior is unclear, ask for clarification before making assumptions.
