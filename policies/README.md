# Vault Policies (management)

This directory holds Vault policy files (`*.hcl`). Policies are plain-text and not secrets; you can either apply them manually or automate uploading them to a Vault server.

Recommended options

- Manual (simple): use the `vault` CLI to write or update policies.
- Automated (repeatable): use the included `tools/vault/apply_policies.sh` script.

Manual commands

Export your Vault environment first:

```bash
export VAULT_ADDR=https://vault.example.local:8200
export VAULT_TOKEN=... # or use vault login prior to running commands
```

Write/update all policies in this directory:

```bash
for f in policies/*.hcl; do
  name=$(basename "$f" .hcl)
  vault policy write "$name" "$f"
done
```

Validate a policy:

```bash
vault policy read <policy_name>
```

Delete a policy:

```bash
vault policy delete <policy_name>
```

Automated: `tools/vault/apply_policies.sh`

This repo includes a tiny helper script at `tools/vault/apply_policies.sh` that will perform a dry-run by default and can apply policies when passed `--apply`.

Usage:

```bash
# dry-run (shows what it would do)
tools/vault/apply_policies.sh --dry-run

# apply (writes policies to Vault)
tools/vault/apply_policies.sh --apply
```

Prerequisites

- `vault` CLI available in PATH
- `VAULT_ADDR` and `VAULT_TOKEN` (or logged-in session) available in the environment
- Optional: `VAULT_CACERT` if using self-signed CA

Notes

- Policies are intentionally kept plaintext under `policies/` so they are visible in Git history and reviewable.
- Keep secrets (tokens, private keys) out of this directory; store those in `secrets/` and encrypt with SOPS.
