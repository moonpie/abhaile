# Copilot Instructions

You are working in the Abhaile GitOps repo. The authoritative state lives in `config/`, and the goal is to render/apply host-specific artifacts for Debian hosts (phobos, deimos).

## Big picture

- Render is unprivileged and reads only from `config/`; apply is privileged and enforces safety gates.
- Targets run systemd-networkd and Podman quadlets, with deterministic /32 ipvlan-l2 service addressing and split-horizon DNS.
- Treat rendered output under `<output>/rendered/` as disposable; never edit generated artifacts directly.
- Runtime secrets are Vault-managed on-host; any `sops` usage is limited to sealed bootstrap artifacts, not day-to-day service secrets.

## Source of truth & structure

- Host/service placement: `config/mapping.yaml` (e.g., phobos runs ddclient/chrony-a/caddy-\*).
- Network/DNS intent: `config/network.yaml` (VLANs, hosts, service /32s, DNS zones/records). Uses template placeholders like `%%services.caddy-dmz.address | strip_cidr%%`.
- Service definitions: `config/services/<service>/service.yaml` (type: pod/container, mode: rootful/rootless, network, configs, ingress, vault-agent templates).
- Host overlays: `config/hosts/{common,phobos,deimos}/` (software/users/systemd/systemd-networkd/systemd-resolved).
- Shared templates: `config/_templates/**` for host/service rendering.

## Service authoring model

- `composition.systemd` is the only authored home for service-owned systemd units; use `enable` and `start` booleans there when boot/runtime lifecycle is intended.
- `composition.config` is for plain config/env files and directories only; do not place systemd units there.
- Authored entry-level `apply` blocks are not part of the current model; runtime behavior comes from explicit authored sections plus renderer-internal apply hints.
- Service-level `apply.restart_unit` is the explicit mechanism for restarting host daemons whose config is managed but which do not have quadlet-derived unit names.

### Service patterns (examples)

- `config/services/authelia/service.yaml` shows a pod with multiple containers, named volumes, ingress blocks, and vault-agent templates (`*.ctmpl`).
- Service directories often include config/, quadlets/, systemd/, templates/, and caddy ingress fragments.

## Render/apply contract (must-haves)

- Render reads only from `config/` and emits desired artifacts under `<output>/rendered/`; the desired manifest is written as `<output>/rendered/manifest.json`.
- Apply owns durable state under `<output>/state/`, including `manifest.json`, `manifest.previous.json`, and `history/`.
- Render outputs include systemd-networkd, quadlets, DNS, non-secret service configs, and Vault Agent control-plane artifacts; resolved secret outputs must never appear in repo-managed render output.
- Apply validates inputs, stages atomically, updates state on success, and reloads or restarts only changed owners.
- Apply and diff business logic live in Python entrypoints under `src/abhaile/`; shell in `scripts/` is for wrappers/orchestration only.
- Commit-aware rollback and scheduled reconciliation belong to the GitOps runner layer, not `src/abhaile/` apply logic.

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
- Do not commit secrets; commit templates, placeholders, and sealed bootstrap artifacts only. Keep runtime secret values out of git, even in rendered output.
- Keep render deterministic and idempotent; apply is safe by default (dry-run unless explicit).
- If behavior is unclear, ask for clarification before making assumptions.
