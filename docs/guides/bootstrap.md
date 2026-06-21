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
  Non-Vault hosts require Vault to be unsealed before bootstrap can mint the seed token. A host
  that can unseal Vault may include `unseal_keys` in its sealed artifact.
- Vault policies required by rendered services are present.
- `.sops.yaml` has an age recipient rule for `config/bootstrap/sealed/<host>/`.
- `config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml` exists and is encrypted.
- The host has the matching age identity from secure backup.
- A read-only Git deploy key exists and is authorized for the repository.
- A fresh one-time bootstrap token is available. This is the Vault AppRole SecretID supplied at
  runtime; do not commit it.

## 2. Operator Materials

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

## 3. Network Preparation

The host needs temporary network access for package installation, Git clone/pull, Vault AppRole
login, and optional script download.

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

## 4. Sealed Bootstrap Artifact

Each host needs an encrypted artifact at:

```text
config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml
```

The artifact must contain the AppRole `role_id` used to mint the initial Vault Agent seed token.
It may also contain `unseal_keys` when this host is allowed to unseal Vault during bootstrap or
early boot. The AppRole SecretID is supplied separately at runtime as the one-time bootstrap token.

Example plaintext shape before SOPS encryption:

```yaml
role_id: <vault-agent-approle-role-id>
unseal_keys:
  - <vault-unseal-key-1>
  - <vault-unseal-key-2>
```

Omit `unseal_keys` on hosts that should only consume Vault after it is already unsealed.

Create or edit the encrypted artifact with the helper script:

```bash
make bootstrap-create HOST=<host> NAME=vault-bootstrap
make bootstrap-edit HOST=<host> NAME=vault-bootstrap
make bootstrap-validate
```

Commit the encrypted artifact and `.sops.yaml` changes before bootstrapping the host.

## 5. Clean-Room Migration

For an already configured host, validate drift before handing control to the live bootstrap path.
This is the recommended path when replacing manual service management with GitOps.

1. Clone or update the repo on the target host.

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

## 6. Running Bootstrap

From a shell on the target host:

```bash
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/scripts/bootstrap.sh \
  | sudo bash -s -- "$(hostname -s)"
```

Or, if the repo is already cloned:

```bash
sudo /opt/abhaile/scripts/bootstrap.sh "$(hostname -s)"
```

The script prompts for the one-time bootstrap token. You can also provide it through
`BOOTSTRAP_TOKEN` or `BOOTSTRAP_TOKEN_FD`.

Bootstrap stages:

1. Preflight: root, host argument, Debian version warning, basic network check.
1. Prerequisites: packages, pinned SOPS install, Vault CLI install, networkd/resolved enablement.
1. User and credentials: `abhaile` user, age identity, deploy key, bootstrap token.
1. Repo and environment: clone/pull repo, create venv, install runtime dependencies.
1. Configuration validation: host exists in mapping and network config.
1. Sealed handoff: decrypt host artifact ephemerally, optionally unseal Vault, mint Vault Agent
   seed token.
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
- Sealed bootstrap artifact missing or not encrypted for this host.
- Vault unavailable, sealed, or AppRole login rejected.
- Dry-run revealed local manual drift that needs cleanup before live apply.

## 7. Verification

The host is enrolled when all checks pass:

```bash
systemctl status abhaile-runner.timer --no-pager
systemctl list-timers abhaile-runner.timer --no-pager
test -f /srv/vault/agent/out/.ready && echo OK
cat /var/lib/abhaile/runner/last-successful-commit
machinectl shell abhaile@ /bin/systemctl --user status vault-agent.service
```

Check services mapped to this host:

```bash
systemctl status <unit>.service --no-pager
```

Use `config/mapping.yaml` and `docs/INVENTORY.md` to identify expected services and addresses.

## 8. Re-Enrollment

When re-bootstrapping an existing host:

- Existing packages, user, and repo clone are reused where possible.
- Runner state under `/var/lib/abhaile/runner/` is preserved.
- Rendered output under `/var/lib/abhaile/rendered/` is regenerated by render.
- A fresh one-time bootstrap token is required.
- The existing Vault Agent seed token is overwritten.
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

## 9. Adding a New Host

When adding another host:

1. Add the host to `config/network.yaml`.
1. Add desired service mapping in `config/mapping.yaml`.
1. Add host composition under `config/hosts/<host>/`.
1. Generate or retrieve the host age identity.
1. Add the host public age recipient to `.sops.yaml`.
1. Create `config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml`.
1. Validate sealed artifacts.
1. Commit and push.
1. Follow this bootstrap walkthrough on the target host.
