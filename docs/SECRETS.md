# Secrets Model

## Overview

Abhaile splits secrets into two phases: **bootstrap** (one-time trust before Vault Agent) and **runtime** (Vault Agent delivery after bootstrap). Bootstrap uses SOPS/age-encrypted artifacts decrypted ephemerally on the target host; runtime uses Vault Agent templates rendered to host-only paths. No plaintext secrets ever appear in git or in rendered output.

## Bootstrap Credentials

| Artifact | Scope | Path | Purpose |
| --- | --- | --- | --- |
| Vault bootstrap (sealed) | per-host | `config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml` | AppRole and optional unseal material |
| Repo bootstrap (sealed, optional) | per-host | `config/bootstrap/sealed/<host>/repo-bootstrap.sops.yaml` | Repo access token fallback |
| Age decryption identity | per-host | `/home/abhaile/.config/sops/age/keys.txt` | Decrypts sealed artifacts |
| Git deploy key | per-host | `/home/abhaile/.ssh/gitops_ed25519` | Read-only repo clone/pull |
| Vault Agent seed token | per-host | `/home/abhaile/.config/vault-agent/token` | Initial AppRole auth for Vault Agent |

The sealed Vault bootstrap artifact must include `role_id`. It may include `unseal_keys` when the
host is authorized to unseal Vault during bootstrap or early boot. Omit `unseal_keys` on hosts that
should only consume Vault after it is already unsealed.

On managed hosts, the sealed Vault bootstrap artifact is available at
`/opt/abhaile/config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml`. The host-owned
`abhaile-vault-unseal.service` checks that path and skips unseal work when the artifact is absent.

Sealed artifacts use age encryption with per-host + operator-recovery recipients defined in `.sops.yaml`.

## Runtime Secrets (Vault Agent Templates)

Vault Agent renders `.ctmpl` sources to `/srv/vault/agent/out/` at runtime. Vault KV paths are defined inside the `.ctmpl` files and are not verifiable from the repository alone.

| Service | Template Source | Output Path | Purpose |
| --- | --- | --- | --- |
| vault-agent | `vault-agent/templates/ready.ctmpl` | `/srv/vault/agent/out/.ready` | Readiness sentinel (gates downstream services) |
| authelia | `authelia/templates/authelia.configuration.yml.ctmpl` | `/srv/vault/agent/out/authelia.configuration.yml` | Session/storage/JWT/OIDC secrets |
| authelia | `authelia/templates/authelia-redis.conf.ctmpl` | `/srv/vault/agent/out/authelia-redis.conf` | Redis password |
| caddy-dmz | `caddy-dmz/templates/caddy-dns-desec.env.ctmpl` | `/srv/vault/agent/out/caddy-dns-desec.env` | deSEC API token for ACME DNS-01 |
| ddclient | `ddclient/templates/ddclient.conf.ctmpl` | `/srv/vault/agent/out/ddclient.conf` | deSEC API credentials for DDNS updates |
| coredns-omada | `coredns-omada/templates/coredns-omada.env.ctmpl` | `/srv/vault/agent/out/coredns-omada.env` | Omada Controller API credentials |

All outputs are owned `abhaile:abhaile` with mode `0640`. Consuming services use systemd `.path` units to watch their output file and trigger reload/restart.

## External Material Contract

| Path | Mode | Producer | Notes |
| --- | --- | --- | --- |
| `/home/abhaile/.config/vault-agent/token` | `0600` | Operator/Bootstrap | Seed token, never from git |
| `/home/abhaile/.config/vault-agent/role-id` | `0600` | Operator (bootstrap §4) | AppRole RoleID, written once per host |
| `/home/abhaile/.config/vault-agent/secret-id` | `0600` | Operator (bootstrap §4) | AppRole SecretID, written once per host |
| `/srv/vault/agent/run/vault-agent-token` | `0600` | Vault Agent sink | Refreshed automatically |
| `/srv/vault/agent/out/.ready` | `0640` | Vault Agent template | Gates `abhaile-secrets-ready.path` |
| `/srv/vault/agent/out/*` | `0640` | Vault Agent templates | Runtime secret-bearing configs |

## Rotation

| Category | Rotation | Mechanism |
| --- | --- | --- |
| Vault Agent sink token | Automatic (6h) | `vault-token-refresh.timer` |
| Runtime secrets (templates) | Automatic | Vault Agent re-renders on lease/TTL expiry |
| Vault unseal keys | Manual | Re-init Vault (rare, requires operator) |
| Age identities | Manual | Replace key, run `make bootstrap-rotate` |
| Bootstrap seed token | Manual | Re-mint via AppRole if expired |
| Service API keys in Vault KV | Manual | Update Vault KV, Agent re-renders |

## Adding a New Secret

1. Create `.ctmpl` template in `config/services/<service>/templates/`.
1. Declare in `service.yaml` under `composition.vault_agent.templates` with `source`, `out`, `perms`.
1. Store the secret value in Vault KV at the path referenced in the `.ctmpl`.
1. Add a systemd `.path`/`.service` pair to watch the output and reload the consumer.
1. Re-render and apply — vault-agent collects the new template automatically.

See [ADDING-A-SERVICE.md](ADDING-A-SERVICE.md) for the full service onboarding checklist.

## Emergency Access

If Vault is sealed or secrets are not rendering, see [BREAK-GLASS.md](BREAK-GLASS.md) §1 (Vault Sealed Recovery) and §6 (Token Expiry).

## Vault Policies

Vault policies live in `policies/` (e.g., `vault-agent.hcl`, `admins.hcl`). These define read/write ACLs for AppRoles and operators but do not contain secret values.
