# Vault Automation Tools

Scripts for Vault token minting and unseal automation.

- `vault_token_refresh.sh`: AppRole token mint + renewal, driven by `abhaile-vault-token-refresh@.timer`.
- `vault_unseal.sh`: SOPS-backed unseal helper used by `abhaile-vault-unseal.service`.

Systemd units reference the scripts directly from the GitOps checkout at `/opt/abhaile/tools/vault/`. No installation to `/usr/local/sbin/` is needed.
