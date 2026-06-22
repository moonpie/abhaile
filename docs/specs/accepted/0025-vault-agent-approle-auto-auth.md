# Spec: Vault Agent AppRole Auto-Auth

## Metadata

```yaml
id: SPEC-2026-025
title: Vault Agent AppRole Auto-Auth
status: accepted
owner: moonpie
created: 2026-06-22
updated: 2026-06-22
related_adrs:
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0007-sops-bootstrap-policy-and-layout
  - 0009-vault-agent-approle-auto-auth
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [vault-agent]
```

## Context

The GitOps flow has not yet been deployed on a managed host, so the Vault Agent authentication
model can be corrected before first rollout. The desired model is that Vault Agent owns
authentication by using its native AppRole auto-auth method. Bootstrap establishes the host's
durable Vault identity, and Vault Agent uses that identity to authenticate, renew, and
re-authenticate after restarts.

## Requirements

- [x] Replace Vault Agent `token_file` auto-auth with native `approle` auto-auth.
- [x] Store host-local AppRole material at explicit, documented paths.
- [x] Bootstrap writes AppRole files atomically with strict ownership and permissions.
- [x] Do not persist AppRole SecretIDs in git, rendered output, logs, process arguments, or
  repo-managed state.
- [x] Support response-wrapped SecretID handoff as the preferred bootstrap input.
- [x] Remove the custom Vault token refresh unit/timer from desired state.
- [x] Document AppRole creation, bootstrap, rotation, revocation, and recovery workflows.
- [x] Render integration tests cover the migrated Vault Agent config for phobos and deimos.
- [x] Existing bootstrap tests cover the new credential handoff contract.

## Constraints

- Render must remain deterministic and must not read Vault or secret files.
- Apply must not materialize plaintext secret values into rendered output.
- The durable SecretID is host-local machine credential material and must be treated as a secret.
- AppRole policy must remain least-privilege and scoped to Vault Agent template reads.
- Vault Agent must be able to restart and re-authenticate without full host re-bootstrap.
- The design must be safe for hosts currently managed manually during clean-room bootstrap testing.
- No live apply is part of this spec unless explicitly requested during implementation.

## Design

### Desired Auth Flow

```text
operator creates host AppRole SecretID in Vault
  -> operator supplies wrapped SecretID or SecretID during bootstrap
  -> bootstrap decrypts host sealed artifact for role_id
  -> bootstrap writes role-id and secret-id host files
  -> apply places Vault Agent config and quadlet mounts
  -> Vault Agent authenticates with AppRole
  -> Vault Agent writes runtime sink token
  -> Vault Agent renders runtime secrets
```

### Host-Local Files

| Path | Owner | Mode | Producer | Consumer |
| --- | --- | --- | --- | --- |
| `/home/abhaile/.config/vault-agent/role-id` | `abhaile:abhaile` | `0600` | bootstrap | Vault Agent |
| `/home/abhaile/.config/vault-agent/secret-id` | `abhaile:abhaile` | `0600` | bootstrap | Vault Agent |
| `/srv/vault/agent/run/vault-agent-token` | `abhaile:abhaile` | `0600` | Vault Agent | Vault Agent/runtime diagnostics |

The `/home/abhaile/.config/vault-agent/token` seed-token handoff is not part of the intended
first-deployment model.

### Vault Agent Config

Vault Agent config uses:

```hcl
auto_auth {
  method "approle" {
    config = {
      role_id_file_path = "/agent/role-id"
      secret_id_file_path = "/agent/secret-id"
      remove_secret_id_file_after_reading = false
    }
  }

  sink "file" {
    config = {
      path = "/agent/run/vault-agent-token"
      mode = 0600
    }
  }
}
```

The SecretID file must remain available because Vault Agent may need it after process restart.

### Bootstrap Contract

`secrets/<host>/vault-agent.sops.yaml` contains the AppRole `role_id`. It must not contain the
AppRole SecretID or Vault unseal material.

`BOOTSTRAP_TOKEN` and `BOOTSTRAP_TOKEN_FD` represent SecretID handoff material:

- preferred: a Vault response-wrapping token for the host AppRole SecretID
- allowed for manual recovery with `BOOTSTRAP_DIRECT_SECRET_ID=1`: the host AppRole SecretID itself

Bootstrap unwraps the value by default. If unwrap fails, bootstrap fails closed unless
`BOOTSTRAP_DIRECT_SECRET_ID=1` is set, in which case it treats the value as a direct SecretID.
The script must not log the value or pass it through process arguments.

### Service Composition

`vault-agent.container` mounts:

- `/home/abhaile/.config/vault-agent/role-id` to `/agent/role-id:ro`
- `/home/abhaile/.config/vault-agent/secret-id` to `/agent/secret-id:ro`
- `/srv/vault/agent/run` for the runtime sink token

The custom `vault-token-refresh.service` and `vault-token-refresh.timer` are not rendered.

### Agent Review Input

Architect:

- Prefer a durable host identity over a seed token whose lifecycle depends on renewal timing.
- Treat this as an ADR-backed trust model change, not a small script fix.

SysAdmin:

- Prefer restart and outage resilience. A host should recover after Vault Agent restart without
  full re-bootstrap when its AppRole SecretID remains valid.
- Require explicit rotation and revocation procedures because the SecretID is durable machine
  credential material.

Developer:

- Implement using Vault Agent native `approle` config rather than custom refresh scripts.
- Keep render deterministic by treating credential files as external mounted material.

Code Reviewer:

- Verify `remove_secret_id_file_after_reading = false`; otherwise restart resilience is broken.
- Add tests that catch stale `token_file` config and deleted refresh-unit references.

Technical Writer:

- Update bootstrap, secrets, and break-glass docs around AppRole SecretID lifecycle.
- Avoid describing the bootstrap input as a generic "one-time token" without explaining whether it
  is a response-wrapping token or direct SecretID.

## Decision Notes

- Decision: Vault Agent uses native AppRole auto-auth instead of token-file auto-auth.

- Rationale: AppRole expresses durable host identity and supports re-authentication after restart.

- Impact: Bootstrap must provision durable host-local AppRole files.

- ADR: 0009-vault-agent-approle-auto-auth

- Decision: AppRole SecretIDs are not stored in SOPS artifacts.

- Rationale: They are durable machine credentials, not bootstrap-only committed material.

- Impact: Operators must create and provide SecretIDs out of band during bootstrap or rotation.

- ADR: 0007-sops-bootstrap-policy-and-layout

- Decision: Do not use a custom token refresh timer.

- Rationale: Vault Agent owns authentication, renewal, and sink-token lifecycle.

- Impact: Runtime token refresh is observable through Vault Agent logs and sink token state.

- ADR: 0009-vault-agent-approle-auto-auth

## Acceptance Criteria

- [x] `config/services/vault-agent/config/config.hcl.j2` uses `approle` auto-auth.
- [x] Vault Agent container mounts `role-id` and `secret-id` read-only and no longer mounts
  `/home/abhaile/.config/vault-agent/token`.
- [x] Bootstrap writes `role-id` and `secret-id` atomically as `abhaile:abhaile` mode `0600`.
- [x] Bootstrap supports response-wrapped SecretID handoff and direct SecretID recovery handoff.
- [x] `vault-token-refresh.service` and `vault-token-refresh.timer` are absent from desired state
  and rendered output.
- [x] Docs describe AppRole creation, bootstrap handoff, rotation, revocation, and recovery.
- [x] Render tests verify phobos and deimos Vault Agent output.
- [x] Bootstrap tests verify the AppRole handoff contract.
- [x] `make lint` and `make test-fast` pass.

### Evidence

- Implementation: current working tree changes to `config/services/vault-agent/`,
  `scripts/bootstrap.sh`, Vault Agent documentation, ADR 0009, and this spec. Commit reference
  pending.
- Validation:
  - `bash -n scripts/bootstrap.sh`
  - `shellcheck scripts/bootstrap.sh`
  - `git diff --check`
  - `.venv/bin/pre-commit run check-yaml --files config/services/vault-agent/service.yaml`
  - `.venv/bin/pre-commit run j2lint --files config/services/vault-agent/config/config.hcl.j2`
  - `.venv/bin/pre-commit run pymarkdown --files docs/guides/bootstrap.md docs/reference/secrets.md docs/runbooks/break-glass.md docs/specs/accepted/0014-bootstrap.md docs/specs/accepted/0025-vault-agent-approle-auto-auth.md`
  - `.venv/bin/pytest tests/integration/test_bootstrap.py --no-cov`
  - `.venv/bin/pytest tests/integration/test_vault_templates.py::TestVaultTemplatesIntegration::test_vault_agent_approle_config_for_phobos_and_deimos tests/integration/test_render_apply_e2e.py::TestRenderApplyE2E::test_render_migrated_host_systemd_units_for_phobos_and_deimos --no-cov`
  - `make lint`
  - `make test-fast`

## Out of Scope

- Changing Vault policy contents beyond what the AppRole already needs.
- Automating Vault AppRole creation in the render/apply pipeline.
- Live host apply or Vault mutation without an explicit operator request.
- Replacing Vault AppRole with a different auth method.

## Open Questions

- What SecretID TTL, use limit, CIDR binding, and rotation cadence should the operator use for
  phobos and deimos?

## References

- ADR 0006: Secrets Model and Bootstrap Artifacts
- ADR 0007: SOPS Bootstrap Policy and Layout
- ADR 0009: Vault Agent AppRole Auto-Auth
- SPEC-2026-010: Secrets Management
- SPEC-2026-011: Core Services
- SPEC-2026-014: Bootstrap
- HashiCorp Vault Agent AppRole auto-auth documentation:
  <https://developer.hashicorp.com/vault/docs/agent-and-proxy/autoauth/methods/approle>
