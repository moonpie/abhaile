# ADR 0004: Secrets via SOPS for Bootstrap, Vault for Runtime

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/CREDENTIALS.md`, `docs/QUICKSTART.md`

## Context

Bootstrap secrets must exist before Vault is online, but runtime services should not read secrets from Git. Secrets must be auditable and rotatable.

## Decision

- Use SOPS-encrypted files in `secrets/` for bootstrap material (unseal keys, deploy keys).
- Use Vault as the runtime source of truth for service secrets.
- Deliver runtime secrets via Vault Agent templates and watchers.

## Consequences

- ✅ Bootstrap is reproducible without plaintext secrets in Git.
- ✅ Runtime secrets are centralized, auditable, and revocable.
- ⚠️ Vault must be unsealed early in the boot chain.

## Alternatives Considered

- **All secrets in Git (encrypted)**: rejected due to runtime exposure risk.
- **External KMS auto-unseal**: deferred until future infra supports it.
