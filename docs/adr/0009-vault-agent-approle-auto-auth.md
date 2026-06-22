# ADR 0009: Vault Agent AppRole Auto-Auth

## Status

2026-06-22: Accepted

## Context

An earlier bootstrap design handed Vault Agent a host-local seed token at
`/home/abhaile/.config/vault-agent/token`. That model made the bootstrap boundary small, but it
left token lifecycle semantics unclear. A seed token can expire, miss renewal during a long outage,
or be revoked, and the host then needs operator intervention before Vault Agent can render runtime
secrets again.

Vault Agent supports native AppRole auto-auth. The AppRole method reads a role ID and secret ID
from files, authenticates to Vault, writes a runtime sink token, and can re-authenticate after
restart. HashiCorp's Vault Agent AppRole documentation defines `role_id_file_path`,
`secret_id_file_path`, and `remove_secret_id_file_after_reading`; durable host restart behavior
requires keeping the SecretID file available.

## Decision

Vault Agent authentication uses native AppRole auto-auth with host-local AppRole material.

Each managed host has:

- `/home/abhaile/.config/vault-agent/role-id`
- `/home/abhaile/.config/vault-agent/secret-id`

Both files are owned by `abhaile:abhaile`, mode `0600`, and mounted read-only into the Vault Agent
container. Vault Agent config uses the `approle` auto-auth method with
`remove_secret_id_file_after_reading = false`.

Bootstrap provisions the host-local AppRole files. The repository may contain
`secrets/<host>/vault-agent.sops.yaml` with the AppRole RoleID, but it must not contain the durable
host SecretID or Vault unseal material. The SecretID is supplied out of band during bootstrap,
preferably through a single-use response-wrapping token that bootstrap unwraps before writing the
host-local file.

The Vault Agent sink token remains runtime-owned at `/srv/vault/agent/run/vault-agent-token`.
Custom systemd token refresh units are not part of the design.

## Consequences

- Vault Agent can restart or re-authenticate without full host re-bootstrap.
- Token renewal is delegated to Vault Agent rather than a custom timer.
- The host-local AppRole SecretID becomes durable machine credential material and must be treated
  as a host secret.
- SecretID rotation/revocation requires a documented operator workflow.
- Bootstrap becomes responsible for writing both AppRole files atomically with strict permissions.
- ADR 0006's external material contract uses AppRole credential files instead of a seed token file.
- ADR 0007 continues to prohibit durable runtime credentials in git, including SOPS-encrypted git.

## Alternatives Considered

- **Renewable seed token with Vault Agent token_file auto-auth:** rejected because correctness
  depends on token period and outage duration. It also makes expired-token recovery a bootstrap
  concern instead of an auth-method concern.
- **Custom systemd refresh timer using AppRole files:** rejected because Vault Agent already owns
  authentication and renewal. A custom timer duplicates auth behavior and creates another failure
  path.
- **Persist only a Vault token indefinitely:** rejected because an effectively immortal token is
  harder to rotate and does not express host identity as clearly as AppRole.

## References

- ADR 0006: Secrets Model and Bootstrap Artifacts
- ADR 0007: SOPS Bootstrap Policy and Layout
- SPEC-2026-025: Vault Agent AppRole Auto-Auth
- HashiCorp Vault Agent AppRole auto-auth documentation:
  <https://developer.hashicorp.com/vault/docs/agent-and-proxy/autoauth/methods/approle>
