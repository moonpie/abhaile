# Bootstrap Walkthrough

Enroll a Debian 13 host into the Abhaile GitOps pipeline.

This document is host-agnostic. Host names, addresses, service assignments, and Vault endpoints
come from `config/`, `docs/INVENTORY.md`, and operator-owned secret material.

## 1. Prerequisites

- Debian 13 (trixie) installation complete.
- The host name is set and present in both:
  - `config/mapping.yaml`
  - `config/network.yaml`
- Physical Ethernet is connected to the expected switch port/profile for the host.
- Console access is available as fallback before any live apply.
- Vault is initialized, reachable from the target host, and has AppRole auth configured.
  Non-Vault hosts require Vault to be unsealed before bootstrap can unwrap or validate the SecretID
  handoff.
- Vault policies required by rendered services are present.
- `.sops.yaml` has an age recipient rule for `secrets/<host>/vault-agent.sops.yaml`.
- `secrets/<host>/vault-agent.sops.yaml` exists and is encrypted.
- The host has the matching age identity from secure backup.
- A read-only Git deploy key exists and is authorized for the repository.
- A fresh AppRole SecretID handoff is available. Prefer a response-wrapped SecretID; direct
  SecretID handoff is reserved for recovery. Do not commit either value.

## 2. Bootstrap Boundary

Bootstrap assumes the host can already reach GitHub and Vault. It prepares the local GitOps
runtime, consumes the sealed host handoff, and performs the first live render/apply. It does not
create external trust material or configure Vault.

| Operator prepares before running bootstrap | Bootstrap script handles |
| --- | --- |
| Debian 13 install, hostname, temporary network, and console fallback | Root/preflight checks and basic GitHub connectivity check |
| Host intent committed under `config/mapping.yaml`, `config/network.yaml`, and `config/hosts/<host>/` | Host existence validation in mapping and network config |
| Vault initialized, reachable, unsealed when required, and configured with policies/AppRole | AppRole handoff placement |
| `.sops.yaml` recipient rule and encrypted `secrets/<host>/vault-agent.sops.yaml` | Ephemeral SOPS decrypt of the host Vault Agent artifact |
| Host age identity at `/home/abhaile/.config/sops/age/keys.txt` | Age identity existence check |
| Read-only Git deploy key and repo authorization | Deploy key existence check and repo clone/pull |
| Fresh response-wrapped SecretID, or direct SecretID for explicit recovery | SecretID unwrap or direct recovery handling, then host-local SecretID file placement |
| Clean-room dry-run review for already configured hosts | First live render/apply and runner registration |

Bootstrap creates the `abhaile` user/group when missing, installs host packages required for the
bootstrap path, installs pinned `sops` and Vault CLI binaries, creates the Python virtual
environment, and enables `systemd-networkd` and `systemd-resolved`.

Bootstrap does not create age identities, deploy keys, GitHub deploy-key authorization, Vault
policies, Vault AppRoles, sealed SOPS artifacts, response-wrapped SecretIDs, switch/router/VLAN
state, or clean-room drift decisions.

## 3. Operator Materials

Place these files on the target host before running bootstrap:

```bash
install -d -m 0700 -o abhaile -g abhaile /home/abhaile/.config/sops/age
# Copy age keys.txt to:
# /home/abhaile/.config/sops/age/keys.txt
# mode 0600, owner abhaile

install -d -m 0700 -o abhaile -g abhaile /home/abhaile/.ssh
# Copy Git deploy key to:
# /home/abhaile/.ssh/gitops_ed25519
# mode 0600, owner abhaile

# Add the Git host to:
# /home/abhaile/.ssh/known_hosts
```

The bootstrap script creates the `abhaile` user if it is missing, but creating the user first is
acceptable when you need to place files before running the script.

## 4. Network Preparation

The host needs temporary network access for package installation, Git clone/pull, Vault AppRole
SecretID handoff, and optional script download.

If the installer did not leave working network configuration in place, configure a temporary
address from the host's intended management network:

```bash
ip addr add <host-management-address>/<prefix> dev <physical-interface>
ip link set <physical-interface> up
ip route add default via <gateway-address>
echo "nameserver <temporary-dns-server>" > /etc/resolv.conf
```

Verify:

```bash
ping <gateway-address>
curl -fsS --connect-timeout 10 https://github.com >/dev/null
curl -fsS --connect-timeout 10 <vault-health-or-seal-status-url> >/dev/null
```

Warning: bootstrap performs a live apply in Stage 7. Once apply runs, host networking is
reconfigured from rendered `systemd-networkd` artifacts. Keep console access available until the
host is verified.

## 5. Sealed Bootstrap Artifact

Each host needs an encrypted artifact at:

```text
secrets/<host>/vault-agent.sops.yaml
```

The artifact must contain the AppRole `role_id` used by Vault Agent. The AppRole SecretID is
supplied separately at runtime and must not be stored in the sealed artifact.

Example plaintext shape before SOPS encryption:

```yaml
role_id: <vault-agent-approle-role-id>
```

Vault unseal keys are not part of onboarding bootstrap. Automated unseal uses the recovery artifact
documented in [Secrets Model](../reference/secrets.md).

### AppRole SecretID Handoff

Create the host AppRole material in Vault before running bootstrap. Use the host-specific AppRole
name from the Vault configuration, then store the RoleID in the sealed Vault Agent artifact:

```bash
vault read -field=role_id auth/approle/role/<host-approle>/role-id
sops secrets/<host>/vault-agent.sops.yaml
```

For normal bootstrap, create a response-wrapped SecretID and provide the wrapping token to the
bootstrap prompt or `BOOTSTRAP_TOKEN_FD`:

```bash
vault write -wrap-ttl=10m -field=wrapping_token \
  -f auth/approle/role/<host-approle>/secret-id
```

For recovery only, create a direct SecretID and run bootstrap with
`BOOTSTRAP_DIRECT_SECRET_ID=1`:

```bash
vault write -field=secret_id -f auth/approle/role/<host-approle>/secret-id
```

Do not write the SecretID or wrapping token to git, shell history, logs, or rendered output.

Create or edit the encrypted artifact with `sops`:

```bash
sops secrets/<host>/vault-agent.sops.yaml
```

Commit the encrypted artifact and `.sops.yaml` changes before bootstrapping the host.

## 6. Clean-Room Adoption

For an already configured host, validate drift before handing control to the live bootstrap path.
This is the recommended path when replacing manual service management with GitOps.

1. Clone or update the repo on the target host.

   If `/opt/abhaile` does not exist yet, create it with the read-only deploy key:

   ```bash
   sudo install -d -m 0755 /opt
   sudo GIT_SSH_COMMAND="ssh -i /home/abhaile/.ssh/gitops_ed25519 -o IdentitiesOnly=yes" \
     git clone -b main git@github.com:moonpie/abhaile.git /opt/abhaile
   sudo chown -R root:root /opt/abhaile
   ```

   If the repo already exists:

   ```bash
   cd /opt/abhaile
   git fetch origin main
   git checkout main
   git pull --ff-only origin main
   ```

1. Install runtime dependencies or run the bootstrap script up to the point where the venv exists.
   If the venv already exists:

   ```bash
   /opt/abhaile/.venv/bin/pip install -r /opt/abhaile/requirements.txt
   /opt/abhaile/.venv/bin/pip install --no-build-isolation --no-deps --editable /opt/abhaile
   ```

1. Render the host.

   ```bash
   /opt/abhaile/.venv/bin/abhaile-render --host "$(hostname -s)" --output /var/lib/abhaile
   ```

1. Run a dry-run apply with validations.

   ```bash
   sudo /opt/abhaile/.venv/bin/abhaile-apply \
     --host "$(hostname -s)" \
     --output /var/lib/abhaile \
     --dry-run \
     --dry-run-validations
   ```

1. Review the reported changes. Confirm that only the intended files, units, services, and
   networkd artifacts will be managed.

1. Continue to live bootstrap only after the dry-run result is understood.

## 7. Running Bootstrap

From a shell on the target host:

```bash
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/scripts/bootstrap.sh \
  | sudo bash -s -- "$(hostname -s)"
```

Or, if the repo is already cloned:

```bash
sudo /opt/abhaile/scripts/bootstrap.sh "$(hostname -s)"
```

The script prompts for the SecretID handoff material. You can also provide it through
`BOOTSTRAP_TOKEN` or `BOOTSTRAP_TOKEN_FD`. The preferred value is a response-wrapped AppRole
SecretID. Direct SecretID input is for recovery and requires `BOOTSTRAP_DIRECT_SECRET_ID=1`.

Bootstrap stages:

1. Preflight: root, host argument, Debian version warning, basic network check.
1. Prerequisites: packages, pinned SOPS install, Vault CLI install, networkd/resolved enablement.
1. User and credentials: `abhaile` user, age identity, deploy key, SecretID handoff.
1. Repo and environment: clone/pull repo, create venv, install runtime dependencies.
1. Configuration validation: host exists in mapping and network config.
1. Sealed handoff: decrypt host artifact ephemerally, optionally unseal Vault, and write Vault
   Agent AppRole files.
1. First render and live apply: render host artifacts and apply desired state.
1. Runner registration: enable and start the GitOps runner timer.

If it fails, check:

```bash
journalctl -u abhaile-runner.service --no-pager -n 50
cat /var/log/abhaile/bootstrap.log
```

Common causes:

- Age identity missing or does not match the SOPS recipient.
- Deploy key missing or not authorized for the repo.
- Host missing from `config/mapping.yaml` or `config/network.yaml`.
- Sealed Vault Agent artifact missing or not encrypted for this host.
- Vault unavailable, sealed, response-wrapping token expired, or AppRole SecretID handoff rejected.
- Dry-run revealed local manual drift that needs cleanup before live apply.

## 8. Verification

The host is enrolled when all checks pass:

```bash
systemctl status abhaile-runner.timer --no-pager
systemctl list-timers abhaile-runner.timer --no-pager
test -f /srv/vault/agent/out/.ready && echo OK
cat /var/lib/abhaile/runner/last-successful-commit
machinectl shell abhaile@ /bin/systemctl --user status vault-agent.service
```

If `machinectl` is unavailable, use the explicit user runtime instead:

```bash
sudo -u abhaile XDG_RUNTIME_DIR=/run/user/$(id -u abhaile) \
  systemctl --user status vault-agent.service
```

Check services mapped to this host:

```bash
systemctl status <unit>.service --no-pager
```

Use `config/mapping.yaml` and `docs/INVENTORY.md` to identify expected services and addresses.

## 9. Re-Enrollment

When re-bootstrapping an existing host:

- Existing packages, user, and repo clone are reused where possible.
- Runner state under `/var/lib/abhaile/runner/` is preserved.
- Rendered output under `/var/lib/abhaile/rendered/` is regenerated by render.
- A fresh AppRole SecretID handoff is required.
- The existing Vault Agent AppRole files are overwritten.
- Services may restart if their managed units or configs change.
- Host networking is re-applied from rendered networkd artifacts.

Before re-enrollment, stop the runner if you want a quiet maintenance window:

```bash
systemctl stop abhaile-runner.timer
systemctl stop abhaile-runner.service
```

Re-enable it after verification if bootstrap did not already do so:

```bash
systemctl enable --now abhaile-runner.timer
```

## 10. Adding a New Host

When adding another host:

1. Add the host to `config/network.yaml`.
1. Add desired service mapping in `config/mapping.yaml`.
1. Add host composition under `config/hosts/<host>/`.
1. Generate or retrieve the host age identity.
1. Add the host public age recipient to `.sops.yaml`.
1. Create `secrets/<host>/vault-agent.sops.yaml`.
1. Validate sealed artifacts.
1. Commit and push.
1. Follow this bootstrap walkthrough on the target host.
