# Architecture

Abhaile is a GitOps-managed homelab running on two Debian 13 hosts (phobos, deimos). Desired state lives in `config/`, is rendered into host-specific artifacts, and applied with hash-based drift detection. The system converges hosts toward declared intent without manual changes.

## Pipeline

```mermaid
flowchart LR
    A[config/] -->|render| B[rendered/]
    B -->|apply| C[live host]
    C -.->|drift check| D[state/]
    D -.->|compare| B
```

Render is unprivileged and deterministic. Apply is privileged, atomic, and defaults to dry-run. See [README](../README.md) for design principles.

## Network Topology

```mermaid
flowchart TD
    subgraph VLAN20[Services VLAN 20]
        P[phobos .10]
        D[deimos .11]
        SVC["/32 ipvlan-l2 services\n.200–.254"]
    end
    subgraph VLAN100[DMZ VLAN 100]
        CDZ[caddy-dmz .200]
    end
    P --- SVC
    D --- SVC
    P --- CDZ
    DNS[Split-horizon DNS\ncoredns-filtered / coredns-clean]
    SVC --> DNS
```

Each containerized service gets a deterministic /32 address on ipvlan-l2. See [INVENTORY.md](INVENTORY.md) for the full address table.

## Secrets Flow

```mermaid
flowchart LR
    S[sealed artifacts\nsecrets/<host>/] -->|sops decrypt| B[bootstrap/recovery]
    B -->|AppRole files| VA[vault-agent]
    VA -->|templates| R[runtime secrets\n/srv/vault/agent/out/]
    R -->|path watch| SVC[services]
```

No secrets in git or rendered output. Vault Agent renders credentials at runtime to host-only paths.

## Key Components

| Layer | Role | Key paths |
|-------|------|-----------|
| Config | Source of truth | `config/mapping.yaml`, `config/network.yaml`, `config/services/*/service.yaml` |
| Render | Deterministic artifact generation | `src/abhaile/renderers/`, `src/abhaile/cli/render.py` |
| Apply | Host reconciliation with drift detection | `src/abhaile/apply/`, `src/abhaile/cli/apply.py` |
| Plan | Manifest comparison and owner ordering | `src/abhaile/plan/diff.py` |
| Runner | GitOps scheduling, fetch, rollback | `scripts/abhaile-runner` |
| Bootstrap | Fresh host enrollment | `scripts/bootstrap.sh` |

## Where to Look

| Topic | Reference |
|---|---|
| Reconciliation model | [README.md](../README.md) |
| Service-host mapping | [config/mapping.yaml](../config/mapping.yaml) |
| IP/VLAN assignments | [config/network.yaml](../config/network.yaml) |
| Adding or modifying a service | `config/services/<name>/service.yaml`, [ADR 0005](adr/0005-service-authoring-model.md) |
| Apply phases | [Spec 0009](specs/accepted/0009-apply-pipeline.md) |
| Secrets boundary | [ADR 0006](adr/0006-secrets-model-and-bootstrap-artifacts.md) |
| Running render/apply locally | `make render`, `make apply HOST=<host>` |
| Spec status | [docs/specs/README.md](specs/README.md) |
| Operations runbook | [docs/runbooks/operations.md](runbooks/operations.md) |
| Emergency procedures | [docs/runbooks/break-glass.md](runbooks/break-glass.md) |
| Bootstrap a host | [docs/guides/bootstrap.md](guides/bootstrap.md) |
| Add a new service | [docs/guides/adding-a-service.md](guides/adding-a-service.md) |
| Credential reference | [docs/reference/secrets.md](reference/secrets.md) |
| Network inventory | [docs/INVENTORY.md](INVENTORY.md) |
