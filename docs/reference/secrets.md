# Secrets Model

## Overview

Abhaile splits secrets into three phases: **bootstrap** (one-time trust before Vault Agent),
**recovery** (privileged host recovery such as Vault unseal), and **runtime** (Vault Agent delivery
after bootstrap). Bootstrap and recovery use SOPS/age-encrypted artifacts decrypted ephemerally by
the appropriate host identity; runtime uses Vault Agent templates rendered to host-only paths. No
plaintext secrets ever appear in git or in rendered output.

## Bootstrap Credentials

| Artifact | Scope | Path | Purpose |
| --- | --- | --- | --- |
| Vault Agent bootstrap (sealed) | per-host | `secrets/<host>/vault-agent.sops.yaml` | AppRole RoleID handoff |
| Vault unseal recovery (sealed) | Vault host | `secrets/<host>/vault-unseal.sops.yaml` | Automated Vault unseal recovery |
| Age decryption identity | per-host | `/home/abhaile/.config/sops/age/keys.txt` | Decrypts Vault Agent bootstrap artifact |
| Vault unseal age identity | Vault host | `/root/.config/sops/age/vault-unseal.keys.txt` | Decrypts Vault unseal recovery artifact |
| Operator recovery age identity | offline | operator password manager / encrypted offline backup | Recovery recipient for sealed artifacts |
| Git deploy key | per-host | `/home/abhaile/.ssh/gitops_ed25519` | Read-only repo clone/pull |
| Vault Agent AppRole material | per-host | `/home/abhaile/.config/vault-agent/{role-id,secret-id}` | Durable host auth for Vault Agent |

`vault-agent.sops.yaml` must include `role_id` and must not contain `unseal_keys` or AppRole
SecretID material.

`vault-unseal.sops.yaml` contains `unseal_keys` only for hosts authorized to unseal Vault during
boot recovery. Omit the file on hosts that should only consume Vault after it is already unsealed.
Automated unseal is a privileged host recovery activity, not Vault Agent runtime auth.

On managed hosts, sealed artifacts are available under `/opt/abhaile/secrets/<host>/`.
`abhaile-vault-unseal.service` is rendered only for hosts authorized to perform Vault unseal
recovery. Hosts that only consume Vault do not receive the unseal unit or helper script. On a Vault
host, a missing unseal artifact is an operational error and should fail visibly.

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
| `/home/abhaile/.config/vault-agent/role-id` | `0600` | Bootstrap | AppRole RoleID from `secrets/<host>/vault-agent.sops.yaml` |
| `/home/abhaile/.config/vault-agent/secret-id` | `0600` | Bootstrap | AppRole SecretID from out-of-band handoff, never from git |
| `/root/.config/sops/age/vault-unseal.keys.txt` | `0600` | Operator | Root-owned age identity for automated Vault unseal on the Vault host |
| `/srv/vault/agent/run/vault-agent-token` | `0600` | Vault Agent sink | Refreshed automatically |
| `/srv/vault/agent/out/.ready` | `0640` | Vault Agent template | Gates `abhaile-secrets-ready.path` |
| `/srv/vault/agent/out/*` | `0640` | Vault Agent templates | Runtime secret-bearing configs |

## Rotation

| Category | Rotation | Mechanism |
| --- | --- | --- |
| Vault Agent sink token | Automatic | Vault Agent renewal |
| Vault Agent AppRole SecretID | Manual | Create in Vault, deliver through wrapped bootstrap handoff, restart Vault Agent |
| Runtime secrets (templates) | Automatic | Vault Agent re-renders on lease/TTL expiry |
| Vault unseal keys | Manual | Re-init Vault (rare, requires operator) |
| Host age identities | Manual | Replace key, run SOPS rotation for affected artifacts |
| Operator recovery age identity | Manual | Replace offline key, rotate all affected sealed artifacts |
| Service API keys in Vault KV | Manual | Update Vault KV, Agent re-renders |

## Adding a New Secret

1. Create `.ctmpl` template in `config/services/<service>/templates/`.
1. Declare in `service.yaml` under `composition.vault_agent.templates` with `source`, `out`, `perms`.
1. Store the secret value in Vault KV at the path referenced in the `.ctmpl`.
1. Add a systemd `.path`/`.service` pair to watch the output and reload the consumer.
1. Re-render and apply — vault-agent collects the new template automatically.

See [Adding a Service](../guides/adding-a-service.md) for the full service onboarding checklist.

## Emergency Access

If Vault is sealed or secrets are not rendering, see [Break-Glass](../runbooks/break-glass.md) §1 (Vault Sealed Recovery) and §6 (Vault-Agent AppRole Auth Recovery).

## Vault Policies

Vault policies live in `policies/` (e.g., `vault-agent.hcl`, `admins.hcl`). These define read/write ACLs for AppRoles and operators but do not contain secret values.
