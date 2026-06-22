# ADR 0007: SOPS Bootstrap Policy and Layout

## Status

2026-06-22: Updated Accepted
2026-05-05: Accepted

## Context

ADR 0006 established the split secrets model and limited `sops` usage to sealed bootstrap and
recovery artifacts. The repo still needed concrete operator rules for where sealed artifacts live,
what they may contain, who can decrypt them, and how plaintext handling works during bootstrap and
recovery.

## Decision

`sops` usage is limited to sealed host bootstrap and host recovery artifacts.

### Allowed Data Classes in Git (Encrypted Only)

Only sealed artifacts needed before Vault Agent runtime secret rendering is available may be committed:

- one-time or short-lived host enrollment/bootstrap credentials
- initial bootstrap trust handoff values required to establish Vault access
- bootstrap-only access material required to reach control-plane dependencies pre-Vault
- host recovery material required before Vault Agent can run, such as Vault unseal keys for the
  Vault host

These values must be minimal and scoped to bootstrap or recovery, not steady-state runtime.

Vault Agent AppRole SecretIDs are durable host auth credentials. They may be supplied to bootstrap
out of band, including through a single-use response-wrapping token, but must not be committed to
git as sealed SOPS artifacts.

### Forbidden Data Classes in Git (Even Encrypted)

The following must not be stored in git, including as `sops` artifacts:

- long-lived runtime service credentials (application/API/DB/SMTP/JWT secrets)
- durable Vault Agent AppRole SecretIDs
- runtime private keys and service certificate keypairs
- Vault-rendered runtime outputs and any secret intended for steady-state service use

Runtime secret material belongs in Vault and is rendered host-local by Vault Agent.

### Repository Layout and Naming

Sealed artifacts are stored at:

- `secrets/<host>/<artifact-name>.sops.yaml`

Layout rules:

- `host` is the mapped host identity (for example `phobos`, `deimos`)
- one artifact file per logical secret bundle
- file suffix is always `.sops.yaml`
- `vault-agent.sops.yaml` stores Vault Agent bootstrap RoleID material only
- `vault-unseal.sops.yaml` stores Vault unseal recovery material only and exists only on hosts
  authorized to unseal Vault

### Recipient Model

Encryption recipients use age identities.

Each sealed artifact must include:

- at least one target-host recipient appropriate to the artifact owner
- at least one operator-controlled recovery recipient

For Vault Agent bootstrap artifacts, the target-host recipient is the `abhaile` user's age identity.
For Vault unseal recovery artifacts, the target-host recipient is a root/admin age identity on the
Vault host, not the `abhaile` user's age identity.

This supports unattended host bootstrap, automated Vault unseal recovery, and operator
recovery/rotation workflows.

### Decryption Ownership and Plaintext Persistence

Bootstrap and recovery decrypt locally on the target host.

- decryption identity is provided out-of-band by the operator (not from git)
- decrypted content is consumed in memory or ephemeral runtime locations only
- decrypted bootstrap plaintext is never committed and must not persist in durable repo-managed paths

If temporary files are required, they are short-lived, explicitly cleaned up, and not stored under the repository working tree.

## Alternatives Considered

- **Store runtime secrets in git encrypted with `sops`**: rejected because it creates a parallel runtime secret store and conflicts with the Vault Agent runtime model.
- **Use a non-host-scoped sealed artifact directory**: rejected because host-scoped layout reduces ambiguity and bootstrap blast radius.
- **Allow bootstrap plaintext persistence for convenience**: rejected because it weakens the secrets boundary and increases accidental disclosure risk.

## Consequences

- Operators have a concrete, auditable location and naming convention for sealed artifacts.
- Bootstrap ownership is explicit: host-local decrypt, operator-provided identity.
- Runtime secret handling remains fully Vault-centric.
- Future tooling for create/edit/rotate can target one canonical path model.

## References

- ADR 0006: Secrets Model and Bootstrap Artifacts
- `README.md` secrets policy section
