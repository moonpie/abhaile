# Secrets Management

This directory contains SOPS-encrypted secrets for Abhaile GitOps automation.

**Complete documentation:** [docs/CREDENTIALS.md](../docs/CREDENTIALS.md)

## Quick Reference

**Decrypt a secret:**

```bash
sops -d secrets/vault-unseal.sops.yaml
```

**Create new SOPS file:**

```bash
sops -e /tmp/plaintext.yaml > secrets/myservice.sops.yaml
```

**Update encryption keys:**

```bash
sops updatekeys secrets/myservice.sops.yaml
```

See [docs/CREDENTIALS.md](../docs/CREDENTIALS.md) for:

- SOPS file structure and usage
- Age key setup and rotation
- Vault integration workflow
- Bootstrap secrets catalog

1. Verify decryption as abhaile user:

```bash
sudo -u abhaile sops -d secrets/vault-unseal.sops.yaml > /dev/null
```

### Rotation Process

1. Generate a new keypair on a trusted machine.
1. Add the new recipient to all `secrets/*.sops.yaml` and re-encrypt.
1. Roll out the new private key to each host.
1. Remove old recipients once all hosts are updated.

### Notes

- Age keys are high-impact secrets; store offline copies.
- Do not commit private keys to Git.
- Age private keys must exist at `/home/abhaile/.config/sops/age/keys.txt` on each host, owned by `abhaile:abhaile`.
- Secrets are decrypted on-demand by the `abhaile` user during render; missing Age key causes GitOps to abort safely.
- The `abhaile` user is created by the bootstrap script if it doesn't exist.

## Creating New Secret Files

1. Define the plaintext YAML structure in a temp file
1. Encrypt with `sops -e` to `secrets/<name>.sops.yaml`
1. Add the file to Git (encrypted)
1. On target host: GitOps runner decrypts to `/etc/abhaile/`
1. Document the structure in `docs/CREDENTIALS.md`

Examples are in `.example` files in this directory (unencrypted templates for reference).
