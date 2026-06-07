# Bootstrap Walkthrough

Enrolling a bare Debian 13 host into the Abhaile GitOps pipeline.

## 1. Prerequisites

- Lenovo ThinkCentre M910x with Debian 13 (trixie) net-install complete
- Physical Ethernet connected to managed switch on a trunk port (VLAN 20 tagged)
- Console/IPMI access available as fallback (in case SSH is lost after network reconfiguration)
- Operator materials prepared out-of-band:
  - age identity file — **retrieve the existing key from secure offline backup** (USB key or password manager). This must match the public key listed in `.sops.yaml` recipients. Only use `age-keygen` for initial first-time setup.
  - Git deploy key (ed25519, added to repo as read-only deploy key)
  - One-time bootstrap token (AppRole SecretID from Vault)
  - Vault unseal keys (phobos only) — stored in password manager AND as part of `config/bootstrap/sealed/phobos/vault-bootstrap.sops.yaml`. The bootstrap script reads unseal keys from the sealed artifact automatically.

## 2. Pre-Bootstrap (Both Hosts)

> ⚠️ **Network is the #1 failure point.** The physical interface is `enp0s31f6` (Intel I219-LM on M910x). If bootstrap fails to connect, check: cable seated, switch port configured as trunk with VLAN 20 tagged, and interface is up (`ip link show enp0s31f6`). Note that `systemd-networkd` is not running yet — any temp network config will be replaced after bootstrap applies rendered networkd units.

1. Set hostname during Debian install (`phobos` or `deimos`).

1. Ensure the host has a routable address on VLAN 20 (temporary DHCP or static `172.20.20.10/24` for phobos, `.11` for deimos, gateway `.1`).

   ````bash
   # Temporary network config (will be replaced by bootstrap):
   ip addr add 172.20.20.10/24 dev enp0s31f6   # or .11 for deimos
   ip link set enp0s31f6 up
   ip route add default via 172.20.20.1
   # Temporary DNS (needed for curl | bash and git clone):
   echo "nameserver 1.1.1.1" > /etc/resolv.conf
   ```bash

   ````

1. SSH in as root and place operator materials:

   ````bash
   # Create abhaile user (bootstrap is idempotent but this speeds first run):
   useradd -u 1001 -m -s /bin/bash abhaile
   groupadd -g 1001 abhaile 2>/dev/null || true

   # Age decryption identity (from secure offline backup — NOT freshly generated):
   install -d -m 0700 -o abhaile -g abhaile /home/abhaile/.config/sops/age
   # Copy keys.txt to /home/abhaile/.config/sops/age/keys.txt (mode 0600, owner abhaile)

   # Deploy key:
   install -d -m 0700 -o abhaile -g abhaile /home/abhaile/.ssh
   # Copy gitops_ed25519 to /home/abhaile/.ssh/gitops_ed25519 (mode 0600, owner abhaile)
   # Add github.com to /home/abhaile/.ssh/known_hosts
   ```bash

   ````

1. Verify network: `ping 172.20.20.1` (gateway) and `ping 1.1.1.1` (internet).

   **If failing:** check cable, switch port profile, VLAN tagging, and that `enp0s31f6` is up (`ip link show enp0s31f6`).

## 3. Running Bootstrap (Both Hosts)

````bash
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/scripts/bootstrap.sh \
  | sudo bash -s -- $(hostname -s)
```bash

Or if the repo is already cloned: `sudo /opt/abhaile/scripts/bootstrap.sh $(hostname -s)`

The script prompts for the one-time bootstrap token (or pass via `BOOTSTRAP_TOKEN` env var).

**What it does:** installs packages (podman, git, age, jq, sops), clones repo to `/opt/abhaile`, creates venv, validates host exists in `config/mapping.yaml`, decrypts sealed artifacts from `config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml`, places the Vault seed token, runs `abhaile-render` + `abhaile-apply`, enables `abhaile-runner.timer`.

> ⚠️ **Point of no return:** Once `abhaile-apply` executes (Stage 7), host networking is reconfigured via systemd-networkd. If the rendered network config is wrong, SSH access may be lost. **Ensure console/IPMI access is available before running bootstrap.** If SSH drops after apply, connect via console and check `/var/log/abhaile/bootstrap.log`.

**If it fails:** check `/var/log/abhaile/bootstrap.log`. Common causes:

- Missing age key → "decryption failure" → verify `/home/abhaile/.config/sops/age/keys.txt`
- Missing deploy key → git clone fails → verify SSH key and known_hosts
- Host not in mapping → "not found in mapping.yaml" → commit host to config first
- Vault unreachable → token minting fails → see §4 below

## 4. Post-Bootstrap: First Host (Phobos Only)

Vault must be running before bootstrap can mint the seed token. For first-time phobos enrollment:

> ⚠️ **Expected failure on first-ever phobos enrollment:** Bootstrap will fail at "Vault AppRole login failed" because Vault doesn't exist yet. **This is normal.** Continue to step 1 below — the script is idempotent and can be re-run after Vault is operational.

1. Bootstrap installs and starts the Vault container via render+apply.

1. **Initialize Vault** (first time only):

   ```bash
   export VAULT_ADDR=https://172.20.20.204:8200
   vault operator init -key-shares=5 -key-threshold=3
   ```bash

   Save unseal keys and root token to **both**:

   - Password manager (primary recovery source)
   - `config/bootstrap/sealed/phobos/vault-bootstrap.sops.yaml` (encrypted, for automated unseal on re-enrollment)

1. **Unseal Vault** using 3 of the 5 unseal keys (threshold=3):

   ```bash
   vault operator unseal   # repeat 3 times with different keys
   ```bash

   Note: On re-enrollment, the bootstrap script reads `unseal_keys` from the sealed artifact and unseals automatically. Manual unseal is only needed on first init.

1. **Configure AppRole** and policies — see `policies/` directory for Vault policy HCL files (one-time operator setup, not automated by bootstrap). At minimum: enable AppRole auth, create the `vault-agent` policy from `policies/vault-agent.hcl`, create a role allowing token minting with that policy.

1. **Write AppRole credentials to disk** (required by `vault-token-refresh.timer`):

   ```bash
   sudo -u abhaile mkdir -p /home/abhaile/.config/vault-agent
   vault read -field=role_id auth/approle/role/vault-agent/role-id \
     | sudo -u abhaile tee /home/abhaile/.config/vault-agent/role-id > /dev/null
   vault write -f -field=secret_id auth/approle/role/vault-agent/secret-id \
     | sudo -u abhaile tee /home/abhaile/.config/vault-agent/secret-id > /dev/null
   sudo chmod 0600 /home/abhaile/.config/vault-agent/{role-id,secret-id}
   ```

1. **Re-run bootstrap** now that Vault is reachable — it will mint the seed token and complete.

1. Wait for secrets sentinel: `test -f /srv/vault/agent/out/.ready && echo OK`

   **If `.ready` doesn't appear within 60s:** check vault-agent logs: `machinectl shell abhaile@ /bin/journalctl --user -u vault-agent.service -n 30`

## 5. Post-Bootstrap: Second Host (Deimos Only)

Deimos connects to phobos Vault over the network. Phobos must be fully operational first.

1. Verify phobos Vault is unsealed and reachable from deimos: `curl -sk https://172.20.20.204:8200/v1/sys/seal-status | jq .sealed` → must be `false`.

1. Run bootstrap on deimos (§3). It mints a seed token against phobos Vault.

1. Wait for secrets sentinel on deimos: `test -f /srv/vault/agent/out/.ready && echo OK`

   **If token minting fails:** confirm Vault address is reachable from deimos (`ping 172.20.20.204`), and that the AppRole is configured to accept auth from deimos.

## 6. Verification (Both Hosts)

All must be true before the host is considered enrolled:

- [ ] `systemctl status abhaile-runner.timer` → active
- [ ] `test -f /srv/vault/agent/out/.ready` → exists
- [ ] `cat /var/lib/abhaile/runner/last-successful-commit` → contains a SHA
- [ ] `machinectl shell abhaile@ /bin/systemctl --user status vault-agent.service` → active
- [ ] Services mapped to this host are running: `systemctl status <service>.service`

## 7. Re-Enrollment

When re-bootstrapping an existing host (hardware replacement, recovery):

- The script is idempotent: existing packages, user, and repo clone are skipped.
- Runner state at `/var/lib/abhaile/runner/` is preserved (not wiped).
- Rendered output at `/var/lib/abhaile/rendered/` is wiped and regenerated by render.
- A new bootstrap token is required (previous one-time token was consumed).
- The existing Vault Agent token at `/home/abhaile/.config/vault-agent/token` is overwritten. If vault-agent.service is currently running, it will be restarted during apply — brief interruption is expected.
- Running podman containers will be restarted by apply if their quadlet units changed. Expect brief service downtime during re-enrollment.
- Host networking (systemd-networkd) is re-applied — if you are connected via SSH over the service VLAN, ensure the rendered config is correct or have console access ready.
- If Vault data is lost (phobos disaster): re-initialize Vault, re-create policies/AppRoles, then bootstrap both hosts fresh.
- Sealed artifacts remain valid as long as the age identity matches what's encrypted in `config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml`. During DR, retrieve the **existing** age key from offline backup — do not generate a new one.

## 8. Onboarding a New Host (SOPS Recipients)

When adding a third host (not re-enrolling an existing one):

1. **Generate an age identity for the new host:**

   ```bash
   age-keygen -o /home/abhaile/.config/sops/age/keys.txt
   ```

   Save the public key (starts with `age1...`).

1. **Add the host's public key to `.sops.yaml`:**

   Add a new `creation_rules` entry scoped to `config/bootstrap/sealed/<newhost>/` with:
   - The new host's age public key
   - The operator recovery key (same one used for existing hosts)

1. **Create the sealed artifact:**

   ```bash
   mkdir -p config/bootstrap/sealed/<newhost>
   sops --encrypt --in-place config/bootstrap/sealed/<newhost>/vault-bootstrap.sops.yaml
   ```

1. **Re-encrypt existing artifacts** if the new host needs access to shared secrets:

   ```bash
   sops updatekeys config/bootstrap/sealed/<newhost>/vault-bootstrap.sops.yaml
   ```

1. **Commit** `.sops.yaml` + sealed artifacts, then bootstrap the host per §3.
````
