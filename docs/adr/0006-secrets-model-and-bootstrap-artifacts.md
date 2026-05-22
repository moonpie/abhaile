# ADR 0006: Secrets Model and Bootstrap Artifacts

## Status

2026-05-05: Updated Accepted
2026-05-05: Accepted

## Context

Abhaile needs to manage secret-dependent services without turning the git repo or rendered output into a secret store. The project also needs a minimal bootstrap path for fresh hosts before Vault Agent can assume runtime secret delivery.

## Decision

Abhaile uses a split secret model:

- runtime secrets are rendered on-host by Vault Agent
- repo-managed render output may include templates, placeholders, destination metadata, and non-secret control-plane config only
- runtime secret values must never appear in git or repo-managed render output
- `sops` is reserved for sealed bootstrap artifacts needed before Vault Agent can take over

### Artifact Classes

Abhaile recognizes three artifact classes:

1. **Committed templates/specs (`config/`)**

   - service specs, placeholders, `*.ctmpl` files, and template metadata
   - may define destination paths and secret references
   - must not contain resolved secret values

1. **Rendered non-secret configs (`<output>/rendered/`)**

   - generated only from repo-defined, non-secret data
   - allowed only when output contains no credentials, tokens, private keys, decrypted material, or resolved secret payloads
   - template sources and destination paths may be rendered or copied

1. **Host-only secret outputs (bootstrap/runtime on host):**

   - Vault-rendered env files
   - app configs that contain credentials
   - token files
   - private keys
   - decrypted bootstrap assets

   These outputs are host-local and must never be committed or emitted into repo-managed rendered output.

### Ownership Boundary

- **Bootstrap** owns initial trust establishment and may consume sealed bootstrap artifacts.
- **Apply** owns privileged host reconciliation and wiring but does not materialize resolved secret values into repo-managed output.
- **Runtime (Vault Agent)** owns rendering resolved secrets into host-only destinations.

This preserves the render/apply privilege boundary: render stays unprivileged and deterministic, while apply remains privileged and reconciliation-focused.

### Bootstrap Boundary

- bootstrap may consume sealed artifacts to establish initial trust or access
- decrypted bootstrap material must not be committed and should not persist on disk unless explicitly intended by the design
- external key material and bootstrap credentials are documented separately from runtime Vault-managed secrets
- external secret material is required at bootstrap/runtime and is delivered outside git

### Runtime Boundary

- Vault Agent templates and non-secret agent config are renderable
- Vault-rendered outputs such as tokens, env files, private keys, and credential-bearing app configs are host-only runtime artifacts
- resolved secret values must never be emitted under `<output>/rendered/`

### External Key/Token/Cert Material Contract

Concrete host paths are split by lifecycle and ownership:

| Artifact / Path | Class | Owner:Group | Mode | Producer / Provisioning | Responsible phase |
| --- | --- | --- | --- | --- | --- |
| `/home/abhaile/.config/vault-agent/token` | Bootstrap-only input (Vault auth seed token file) | `abhaile:abhaile` | `0600` | Operator/bootstrap host-local provisioning (out-of-band) | Bootstrap + Operator |
| `/srv/vault/agent/run/vault-agent-token` | Runtime secret output (Vault Agent sink token) | `abhaile:abhaile` | `0600` | Vault Agent sink runtime write | Runtime (Vault Agent) |
| `/srv/vault/agent/out/.ready` | Runtime readiness sentinel (non-secret) | `abhaile:abhaile` | `0640` | Vault Agent template render | Runtime (Vault Agent) |
| `/srv/vault/agent/out/<template-out>` (for example `authelia.configuration.yml`, `authelia-redis.conf`, `ddclient.conf`, `coredns-omada.env`, `caddy-dns-desec.env`) | Runtime secret-bearing service inputs | `abhaile:abhaile` | `0640` (from `composition.vault_agent.templates[].perms`) | Vault Agent template rendering from committed `*.ctmpl` sources | Runtime (Vault Agent) |
| `/srv/caddy/internal/data/certificates/local/omada-controller.svc.abhaile.home.arpa/omada-controller.svc.abhaile.home.arpa.crt` | Runtime certificate input for Omada chain rebuild | service runtime owner (Caddy-managed) | runtime-managed | Caddy internal PKI runtime output | Runtime (service-managed) |
| `/srv/omada-controller/cert` | Runtime certificate bundle destination for Omada | `root:root` | `0750` directory, file modes set by rebuild script | Host-local rebuild workflow (`rebuild-omada-cert.sh`) | Runtime + Operator |

This separates bootstrap-only inputs from long-lived runtime material and makes path ownership explicit.

### Apply Validation Stance for External Material

- Apply references external secret/key/token/cert paths but does not install secret material.
- Apply does not pre-validate existence or permissions of external secret files.
- Failures for missing/incorrect external material surface in the owning runtime unit (Vault Agent/systemd/container), not by rendering secret payloads.

### Vault Agent Render Integration Boundary

Render emits Vault Agent **control-plane** artifacts only, with deterministic layout under `rendered/services/vault-agent/`:

- copied `*.ctmpl` template sources from service `composition.vault_agent.templates` definitions
- rendered non-secret base agent config from `composition.vault_agent.base`
- managed runtime output parent directories (not runtime secret files)

Manifest entries must include destination path metadata for all of the above. For managed output directories, manifest `apply_hints` carry ownership and mode metadata so apply can safely create/enforce destination paths without reading or producing secret values.

Runtime secret outputs remain host-only and are never materialized during render. This includes any resolved output files referenced by Vault template `out` paths.

## Alternatives Considered

- **Store runtime service secrets in git encrypted with `sops`**: rejected because it makes git a parallel runtime secret store and weakens the Vault-based operating model.
- **Allow render output to materialize resolved secret values**: rejected because rendered output is repo-managed and should remain safe to inspect and regenerate.
- **Avoid any sealed bootstrap artifacts in git**: rejected because some bootstrap flows need a minimal sealed handoff before Vault Agent is available.

## Consequences

- Secret handling is cleaner and more defensible
- Operators can reason separately about bootstrap trust material and runtime secret delivery
- Render remains safe to run offline and inspect without exposing secret values
- Future service additions must decide explicitly whether a value is bootstrap-only, runtime-only, or non-secret control-plane data
- Secret policy review can classify new artifacts quickly using the three-class model
- Operators have concrete, non-ambiguous host paths for bootstrap and runtime external key/token/cert material
- The apply contract stays narrow: reconcile references and directories, never materialize secret payloads

## References

- ADR 0001: Output Root and Environment Paths
- ADR 0004: Apply Execution Model
- ADR 0005: Service Authoring Model
- ADR 0007: SOPS Bootstrap Policy and Layout
