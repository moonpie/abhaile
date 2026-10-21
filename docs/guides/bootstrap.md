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

Warning: bootstrap performs live Ansible reconciliation in Stage 7. Once reconciliation runs, host
networking is reconfigured from rendered `systemd-networkd` artifacts. Keep console access
available until the host is verified.

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
   sudo install -d -m 0750 -o abhaile -g abhaile /opt/abhaile
   sudo -H -u abhaile env HOME=/home/abhaile \
     GIT_SSH_COMMAND="ssh -i /home/abhaile/.ssh/gitops_ed25519 -o IdentitiesOnly=yes" \
     git clone -b main git@github.com:moonpie/abhaile.git /opt/abhaile
   ```

   If the repo already exists:

   ```bash
   cd /opt/abhaile
   sudo chown -R abhaile:abhaile /opt/abhaile
   sudo -H -u abhaile env HOME=/home/abhaile \
     git fetch origin main
   sudo -H -u abhaile env HOME=/home/abhaile \
     git checkout main
   sudo -H -u abhaile env HOME=/home/abhaile \
     git pull --ff-only origin main
   ```

1. Install runtime dependencies or run the bootstrap script up to the point where the venv exists.
   If the venv already exists:

   ```bash
   sudo -H -u abhaile env HOME=/home/abhaile \
     /opt/abhaile/.venv/bin/pip install -r /opt/abhaile/requirements.txt
   ```

   Bootstrap creates local entrypoint wrappers in `/opt/abhaile/.venv/bin` after the
   runtime dependencies import successfully.

1. Render the host.

   ```bash
   sudo install -d -m 0750 -o root -g abhaile /var/lib/abhaile
   sudo install -d -m 0750 -o abhaile -g abhaile /var/lib/abhaile/rendered
   sudo install -d -m 0750 -o abhaile -g abhaile /var/lib/abhaile/runner
   sudo -H -u abhaile env HOME=/home/abhaile \
     /opt/abhaile/.venv/bin/abhaile-render --host "$(hostname -s)" --output /var/lib/abhaile
   ```

1. Run Ansible check mode with native validations.

   ```bash
   sudo env ANSIBLE_CONFIG=/opt/abhaile/ansible/ansible.cfg \
     /usr/bin/ansible-playbook -i localhost, --connection=local --check \
     --extra-vars '{"abhaile_rendered_root":"/var/lib/abhaile/rendered","abhaile_config_root":"/opt/abhaile/config","abhaile_expected_host":"'"$(hostname -s)"'"}' \
     /opt/abhaile/ansible/playbooks/reconcile.yml
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
1. First render, live apply, and baseline: render host artifacts, apply desired state, then atomically
   record the exact checked-out commit as `last-successful-commit`.
1. Runner registration: explicitly install the reserved recovery, runner, and timer units from
   the accepted baseline, then enable and start the GitOps runner timer.

Bootstrap records the baseline only after the explicit live apply succeeds and before enabling the
timer. Routine runner execution refuses unattended mutation when that baseline is absent; it does
not infer first-enrollment success for itself.

The three reserved runner units are deliberately outside ordinary in-process Ansible publication.
Bootstrap installs them only after establishing the accepted baseline. For an existing host whose
accepted commit changes those units, follow **Reserved Runner Unit Updates** in the operations
runbook; do not copy them during an active runner execution.

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
sudo cat /var/lib/abhaile/runner/last-successful-commit
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

## 9. Existing-Host Assessment

Assess an existing host before re-enrollment or Ansible cutover. Do not run bootstrap, render,
apply, or reconciliation during this assessment. Record the command output in the operator's
change record; the repository does not maintain a second host-inventory ledger or classify the
results automatically.

First prove that the operator's own account—not `abhaile`—can connect, obtain administrative
access, and reach the machine through its console or other recovery path. Do not change the
`abhaile` account or sudo policy until those independent paths have been exercised.

Use ordinary Ansible facts for the platform baseline:

```bash
sudo /usr/bin/ansible localhost -i localhost, -c local \
  -m ansible.builtin.setup \
  -a '{"gather_subset":["!all","min","network","virtual"],"filter":["ansible_hostname","ansible_distribution*","ansible_architecture","ansible_virtualization_*","ansible_default_ipv4","ansible_interfaces"]}'
```

Confirm from that output that the short hostname is the intended `deimos` or `phobos` host and
that the system is Debian 13. Treat unexpected platform, hostname, interface, or address facts as
a stop condition rather than trying to repair them during assessment.

Then collect the fixed host-local observations below. These commands are read-only; non-zero
results are evidence to investigate, not permission to mutate the host.

```bash
getent passwd abhaile
getent group abhaile
id abhaile
sudo -n -l -U abhaile

sudo -u abhaile git -C /opt/abhaile status --short --branch
sudo -u abhaile git -C /opt/abhaile rev-parse HEAD
sudo -u abhaile git -C /opt/abhaile remote get-url origin
sudo -u abhaile test -x /opt/abhaile/.venv/bin/abhaile-render
test -x /usr/bin/ansible-playbook

systemctl show abhaile-runner.service abhaile-runner.timer \
  -p Id -p LoadState -p UnitFileState -p ActiveState -p SubState
systemctl list-timers abhaile-runner.timer --no-pager
loginctl show-user abhaile -p Linger -p RuntimePath -p State

sudo -u abhaile env HOME=/home/abhaile XDG_RUNTIME_DIR=/run/user/$(id -u abhaile) \
  bash -c 'cd /tmp && exec systemctl --user show vault-agent.service \
    -p Id -p LoadState -p UnitFileState -p ActiveState -p SubState'
sudo -u abhaile env HOME=/home/abhaile XDG_RUNTIME_DIR=/run/user/$(id -u abhaile) \
  bash -c "cd /tmp && exec podman ps --all --format '{{.Names}} {{.Status}}'"

networkctl list --no-pager
networkctl status --no-pager
find /etc/systemd/network -maxdepth 2 -mindepth 1 -printf '%y %p\n' | sort

sudo awk 'NR == 1 && $1 ~ /^[0-9a-f]{40}$/ {print FILENAME, $1, "fields=" NF}' \
  /var/lib/abhaile/runner/last-successful-commit \
  /var/lib/abhaile/runner/current-run \
  /var/lib/abhaile/runner/failed-target 2>/dev/null
```

The `awk` command intentionally reports only each record's SHA-shaped first field and field count;
it does not read secret-bearing environment, SSH identity, age, SOPS, Vault, or service
configuration files. During the completed migration, a three-field last-successful record was
replaced with the candidate's verified SHA-only baseline after its approved publication succeeded.
Missing optional runner records are valid observations. A
missing, malformed, or unexpected last-successful record blocks unattended Ansible reconciliation
until the initial baseline is established through the disposable-VM-proven adoption procedure.

Finally, verify repository authentication without changing the checkout:

```bash
sudo -u abhaile env \
  HOME=/home/abhaile \
  GIT_SSH_COMMAND='ssh -i /home/abhaile/.ssh/gitops_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/home/abhaile/.ssh/known_hosts' \
  git -C /opt/abhaile ls-remote --exit-code origin HEAD
```

This last command requires GitHub connectivity and is therefore recorded separately from the
local recovery evidence. Local recovery must remain possible from retained Git objects when it
fails.

## 10. Re-Enrollment

When re-bootstrapping an existing host:

- Existing packages, user, and repo clone are reused where possible.
- Runner state under `/var/lib/abhaile/runner/` is preserved.
- Rendered output under `/var/lib/abhaile/rendered/` is regenerated by render.
- A fresh AppRole SecretID handoff is required.
- The existing Vault Agent AppRole files are overwritten.
- Services may restart if their managed units or configs change.
- Host networking is re-applied from rendered networkd artifacts.

Before re-enrollment, stop the runner and verify that no runner job remains. Bootstrap enforces
this quiescent boundary before making changes:

```bash
sudo systemctl disable --now abhaile-runner.timer
systemctl is-active abhaile-runner.service || true
systemctl list-jobs --no-legend | grep -E 'abhaile-runner[.]' || echo runner_jobs_absent
```

Proceed only when the service is `inactive` or `failed` and `runner_jobs_absent` is reported.

Re-enable it after verification if bootstrap did not already do so:

```bash
systemctl enable --now abhaile-runner.timer
```

## 11. Completed Existing-Host Migration Record

> Historical evidence only. Both hosts completed this one-time cutover on 2026-10-20. Do not run
> the commands in this section for enrollment or routine recovery; use Sections 6-7 and the
> operations/break-glass runbooks. The former Python mutation command is retired.

The runner script and systemd unit paths are unchanged by this migration. Installing the new
runner at those paths therefore changes authority; it is a cutover unless the maintenance window
has a reviewed copy of the legacy revision available for exact restoration. Do not overwrite the
runner and then describe the result as a reversible proof without that copy.

Prepare the candidate on an exact reviewed non-polled ref. Keep `main` and `origin/main` at the
exact legacy revision throughout the reversible proof. Set `EXPECTED_LEGACY_REVISION` and
`EXPECTED_CANDIDATE_REVISION` from the reviewed handoff; do not infer either value from a moving
branch. Stop scheduling and execution before fetching or aligning the candidate, then prove that
the runner and its shared lock are quiescent:

```bash
cd /opt/abhaile
legacy_branch=main
candidate_branch=review/phase-6-deimos
legacy_revision=${EXPECTED_LEGACY_REVISION:?set the exact reviewed legacy SHA}
candidate_revision=${EXPECTED_CANDIDATE_REVISION:?set the exact reviewed candidate SHA}
test "$(sudo -u abhaile git rev-parse "refs/heads/${legacy_branch}")" = "$legacy_revision"
test "$(sudo -u abhaile git rev-parse "refs/remotes/origin/${legacy_branch}")" = \
  "$legacy_revision"
sudo systemctl disable --now abhaile-runner.timer
sudo systemctl stop abhaile-runner.service
sudo systemctl reset-failed abhaile-runner.service
test "$(systemctl is-enabled abhaile-runner.timer)" = disabled
test "$(systemctl is-active abhaile-runner.timer)" = inactive
test "$(systemctl is-active abhaile-runner.service)" = inactive
test -z "$(systemctl list-jobs --no-legend | awk '$2 ~ /^abhaile-runner[.]/ {print}')"
sudo -u abhaile flock --nonblock /var/lib/abhaile/runner/lock true
sudo -u abhaile git fetch origin "$candidate_branch"
candidate_ref="refs/remotes/origin/${candidate_branch}"
test "$(sudo -u abhaile git rev-parse "$candidate_ref")" = "$candidate_revision"
test "$candidate_revision" != "$legacy_revision"
sudo -u abhaile git cat-file -e "${legacy_revision}^{commit}"
sudo -u abhaile git cat-file -e "${candidate_revision}^{commit}"
```

Replace `candidate_branch` with the exact reviewed remote review branch; it must not be the polled
branch. The lock assertion acquires and releases the same lock used by the runner without
blocking. This migration candidate intentionally replaces already-pushed Phase 1-4 history, so it
is not a descendant of the legacy revision. Exact reviewed SHAs, not ancestry, bind this one-time
proof. Routine runner updates remain fast-forward-only. Keep `abhaile-runner.timer` stopped for
the entire dry-run and live proof.

The migration detached at the candidate, rendered it, and proved the then-retained mutation plan.
Only after that explicitly approved one-time publication succeeded did it
succeeds, atomically replace the legacy metadata-suffixed runner record with the exact candidate
SHA using the reviewed state helper:

```bash
sudo -u abhaile git checkout --detach "$candidate_revision"
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/abhaile-render \
  --host "$(hostname -s)" --output /var/lib/abhaile
# The retired migration-only check/live publication occurred here.
sudo test ! -e /var/lib/abhaile/runner/current-run
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/python -c '
from pathlib import Path
import sys
from abhaile.state.reconciliation import establish_last_successful

establish_last_successful(Path(sys.argv[1]), sys.argv[2])
' /var/lib/abhaile/runner "$candidate_revision"
test "$(sudo sed -n '1p' /var/lib/abhaile/runner/last-successful-commit)" = \
  "$candidate_revision"
test "$(sudo awk 'END {print NR}' /var/lib/abhaile/runner/last-successful-commit)" -eq 1
```

Next run the Section 12 adoption playbook in check mode and, with its separate network approval,
live mode. This installs and verifies recovery against the candidate baseline before changing the
network backend. After adoption and its reboot/access checks pass, exercise direct candidate
reconciliation against the same non-polled remote branch:

```bash
sudo -H -u abhaile env \
  HOME=/home/abhaile \
  ABHAILE_BRANCH="$candidate_branch" \
  ABHAILE_REMOTE=origin \
  /opt/abhaile/scripts/abhaile-runner
test "$(sudo sed -n '1p' /var/lib/abhaile/runner/last-successful-commit)" = \
  "$candidate_revision"
```

The service environment remains configured for `main`; only this manual, lock-serialized proof
selects the non-polled candidate branch.

If the proof is accepted, keep scheduling stopped while the repository owner promotes exactly
`candidate_revision` to `origin/main`. Because this migration deliberately rewrote the pushed
Phase 1-4 history, the repository owner must perform this one-time promotion from an administrator
workstation with a write credential. Bind the rewrite to the observed legacy tip and the reviewed
candidate with `--force-with-lease`; never grant write access to the host deploy key for this step:

```bash
legacy_revision=${EXPECTED_LEGACY_REVISION:?set the exact reviewed legacy SHA}
candidate_revision=${EXPECTED_CANDIDATE_REVISION:?set the exact proven candidate SHA}
candidate_branch=review/phase-6-deimos
git fetch origin main "$candidate_branch"
test "$(git rev-parse refs/remotes/origin/main)" = "$legacy_revision"
test "$(git rev-parse "refs/remotes/origin/${candidate_branch}")" = "$candidate_revision"
git push --force-with-lease="refs/heads/main:${legacy_revision}" \
  origin "${candidate_revision}:refs/heads/main"
test "$(git ls-remote --refs origin refs/heads/main | awk '{print $1}')" = \
  "$candidate_revision"
```

Run that block only with separate explicit cutover approval. It is a migration-only history
replacement, not permission for routine non-fast-forward publication. Then, on the host, fetch,
align the local polled branch explicitly, and verify both refs name that exact SHA. Enable the new
timer only after reconciliation, local health, `last-successful-commit`, recovery-unit dependency,
and administrator access checks pass:

```bash
sudo -u abhaile git fetch --prune origin
test "$(sudo -u abhaile git rev-parse refs/remotes/origin/main)" = "$candidate_revision"
sudo -u abhaile git branch --force main "$candidate_revision"
sudo -u abhaile git checkout main
test "$(sudo -u abhaile git rev-parse refs/heads/main)" = "$candidate_revision"
# Complete the reviewed cutover checks before enabling scheduling.
sudo systemctl enable --now abhaile-runner.timer
```

If cutover is refused, restore the exact legacy revision and its rendered unit files while
scheduling remains stopped. Disable the candidate-only boot restore service and prove its networkd
dependency is absent before restarting legacy scheduling. If the proof adopted networkd, first
restore and verify the approved legacy boot-network authority; either re-enable the preserved
legacy backend or explicitly verify that the legacy revision's networkd files, enabled networkd
service, and administrator path survive reboot.

```bash
sudo systemctl disable --now abhaile-network-restore.service
sudo systemctl daemon-reload
test ! -e /etc/systemd/system/systemd-networkd.service.requires/abhaile-network-restore.service
! systemctl show systemd-networkd.service --property=Requires --value \
  | tr ' ' '\n' \
  | grep -Fxq abhaile-network-restore.service
sudo -u abhaile git checkout --detach "$legacy_revision"
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/abhaile-render \
  --host "$(hostname -s)" --output /var/lib/abhaile
# The retired migration-only restoration publication occurred here before recovery authority was
# restored while scheduling remained stopped.
sudo test ! -e /var/lib/abhaile/runner/current-run
sudo -u abhaile git checkout --detach "$candidate_revision"
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/python -c '
from pathlib import Path
import sys
from abhaile.state.reconciliation import establish_last_successful

establish_last_successful(Path(sys.argv[1]), sys.argv[2])
' /var/lib/abhaile/runner "$legacy_revision"
sudo -u abhaile git checkout "$legacy_branch"
test "$(sudo -u abhaile git rev-parse "refs/heads/${legacy_branch}")" = "$legacy_revision"
test "$(sudo -u abhaile git rev-parse "refs/remotes/origin/${legacy_branch}")" = "$legacy_revision"
test "$(sudo sed -n '1p' /var/lib/abhaile/runner/last-successful-commit)" = "$legacy_revision"
sudo systemctl enable --now abhaile-runner.timer
```

Verify the restored unit content, boot-network authority, branch refs, and active timer belong to
`legacy_revision`; do not merely restart the candidate runner. No other scheduler or permanent
runtime is introduced for this proof.

## 12. Existing-Host Networkd Adoption

Do not make recurring reconciliation choose a host's network backend. When an existing Debian host
still has `networking.service` enabled, adopt networkd once in a console-backed maintenance window.
Keep `/etc/network/interfaces{,.save}`, ifupdown packages and hooks, and `/etc/resolv.conf`
unchanged during this step; they remain recovery evidence and separately reviewed foundations.

Render the reviewed revision and run the adoption playbook in check mode first:

```bash
cd /opt/abhaile
sudo /usr/bin/ansible-playbook -i localhost, --connection=local --check \
  ansible/playbooks/adopt-networkd.yml \
  --extra-vars '{"abhaile_rendered_root":"/var/lib/abhaile/rendered","abhaile_config_root":"/opt/abhaile/config","abhaile_expected_host":"deimos"}'
```

Replace `deimos` with the local short hostname and its rendered directory. Review the check output,
keep the host console open, and then explicitly authorize the live adoption:

```bash
sudo /usr/bin/ansible-playbook -i localhost, --connection=local \
  ansible/playbooks/adopt-networkd.yml \
  --extra-vars '{"abhaile_rendered_root":"/var/lib/abhaile/rendered","abhaile_config_root":"/opt/abhaile/config","abhaile_expected_host":"deimos","abhaile_live_apply":true}'
```

The playbook first validates and installs `abhaile-network-restore.service`, requiring an existing
valid `last-successful-commit` before it enables the unit's effective dependency on networkd. It
then publishes networkd configuration, enables and starts networkd, verifies the declared
management interface/address/route, and only then disables `networking.service` for the next boot.
It deliberately does not stop the live legacy service. If recovery installation, activation, or
acceptance fails, the legacy service remains enabled.

Before rebooting, verify the expected states and network path from both the host and a separate
administrative session:

```bash
systemctl is-enabled \
  abhaile-network-restore.service systemd-networkd.service networking.service
systemctl is-active systemd-networkd.service
test -L /etc/systemd/system/systemd-networkd.service.requires/abhaile-network-restore.service
systemctl show systemd-networkd.service -p Requires
systemctl show abhaile-network-restore.service -p Before
ip -brief address
ip route
```

Reboot once while console access remains available, repeat those checks, and verify administrative
SSH access. Adoption is incomplete until the host returns with networkd enabled and active, the
legacy backend disabled, and the expected management path intact. Ordinary reconciliation then
repairs networkd service drift but refuses to perform this first-time backend transition.

## 13. Adding a New Host

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
