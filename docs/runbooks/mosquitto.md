# Mosquitto Deployment and Credential Refresh

This runbook deploys Mosquitto rootfully on phobos at `172.20.20.222:1883` using the pinned
`docker.io/library/eclipse-mosquitto:2.1.2-alpine` image. Anonymous access is disabled.
There is no HTTP ingress or host-port publishing. Source-network restrictions remain work for
SPEC-2026-021; the MQTT listener currently accepts authenticated connections over routed networks.

## Two-Part Publication

Follow [the service publication workflow](../guides/adding-a-service.md#publish-prerequisites-before-service-activation).
Keep these parts separately reviewable:

| Part | Include | Gate before proceeding |
| --- | --- | --- |
| Prerequisite push | `policies/vault-agent.hcl` and operator documentation | Reviewed policy is present on phobos, applied by the Vault admin, and the six MQTT fields are provisioned |
| Activation push | Mosquitto mapping, network/DNS changes, service files, password helper, source-path fix, and tests | Prerequisites complete; reviewed activation is published to main for runner-gated render/check/apply |

The prerequisite-only revision must render identically to its base on both hosts. Do not include
the activation mapping, new template enrollment, or DNS changes in that push. Even a policy/docs
commit can cause the runner to reconcile existing state; it does not automatically upload Vault
policies. Confirm the prerequisite commit has reached the host before applying its policy file.

Once prerequisites are complete and deployment is intended, publish the reviewed activation
revision to `main`. The normal runner renders and runs Ansible check mode before apply, then runs
health checks. Record its completed revision and results on both phobos and deimos, because shared
DNS or renderer changes can affect both hosts. A separate review branch or routine timer suspension
is not required. Optional manual checks use the linked privilege-separated workflow and must not
conflict with an active runner. Do not interrupt apply or edit runner recovery records.
Both publication parts belong to spec 0015's deployment phase; the later application-configuration
phase remains separate.

## Persistent State and Ownership

| Host path | Purpose | Ownership and access |
| --- | --- | --- |
| `/srv/mosquitto/config/` | Git-managed broker configuration | Root-owned; mounted read-only |
| `/srv/mosquitto/data/` | Broker persistence database | UID/GID 1883, mode 0750; writable |
| `/srv/mosquitto/secrets/` | Generated password hashes and refresh state | Root-owned, GID 1883, mode 0750; mounted read-only |

The broker and password helper each declare the same pinned image literally in `service.yaml`.
When updating the version, update both declarations; the deployment regression checks that their
rendered image references match.

The broker runs as UID/GID 1883, avoiding the image entrypoint's recursive ownership changes.
The installed password file is root-owned, GID 1883, mode 0640. Its refresh-state file is
root-owned, mode 0600. Reconciliation manages deployment files and directory metadata, without
replacing the broker database or generated credentials.
The private config volume supplies the managed `/srv/mosquitto/config` directory declaration,
including when config rendering has already created an incidental output parent. No duplicate
`composition.config` directory entry is needed.

[Active spec 0033](../specs/active/0033-private-volume-directory-management.md) tracks the general
registration fix replacing the explicit-directory workaround from commit `65cb022`. Operator-run
existing-host check-mode evidence remains pending. Tests use disposable filesystem fixtures;
no empty physical host is required or claimed.

## Vault Prerequisites

Provision one KV v2 secret at `secret/abhaile/mqtt`, using these approved fields:

| Client | Username field | Password field |
| --- | --- | --- |
| Home Assistant | `home_assistant_username` | `home_assistant_password` |
| Zigbee2MQTT | `zigbee2mqtt_username` | `zigbee2mqtt_password` |
| Frigate | `frigate_username` | `frigate_password` |

Use three distinct usernames and non-empty, single-line passwords. Usernames cannot contain
whitespace, colons, or NUL characters. Passwords cannot contain CR, LF, or NUL characters.
Use the protected temporary-file workflow in [Operations](operations.md) to provision values;
never put them in command arguments, shell history, or git.

After the prerequisite push is present in phobos's clean checkout, review and apply its canonical
policy through your Vault-admin session:

```bash
sudo cat /opt/abhaile/policies/vault-agent.hcl
```

Confirm the existing rules are preserved and the MQTT rule is present, then apply and read back:

```bash
set -o pipefail
sudo cat /opt/abhaile/policies/vault-agent.hcl |
  vault policy write vault-agent -
vault policy read vault-agent
```

Sudo reads the protected file; `vault` uses the admin's existing authentication. Do not rebuild the
policy separately from git or apply the old checkout's five-rule file. Provisioning values and
applying this policy complete the operator prerequisites; no agent restart is needed yet. The new
staging template is installed and Vault Agent restarted by the later authorized reconciliation.

Only Vault Agent receives the AppRole credentials and reads this shared
secret. Applications receive their own derived files during their respective deployment stages;
they do not receive Vault credentials or mounts of Vault Agent's output directory.

Vault Agent renders the three accounts into `/srv/vault/agent/out/mosquitto-accounts.json` with
mode 0600, owned by its existing runtime account. This file contains plaintext credentials and
must not be printed, copied into diagnostic bundles, or mounted into the broker.

## Refresh Behaviour

`mosquitto-passwords.service` runs before the broker and when its path watcher observes a staging
change. The Python helper validates the accounts, copies plaintext into a mode-0700 temporary
directory under `/run`, and invokes the pinned image's `mosquitto_passwd -U` with SHA-512 PBKDF2
hashing. The helper container uses no network, a read-only root filesystem, no capabilities,
and a single writable temporary mount. Credential values never enter process arguments or
converter output logs. Temporary plaintext is removed on success and handled failures.

The helper atomically installs hashes on the destination filesystem and queues a restart only
when the broker is already active. It records the input/image fingerprint and installed-file
digest after the restart request succeeds. Unchanged input and an intact installed file do not
trigger another conversion or restart. Failed updates remain eligible for retry; failed
conversion preserves the previously installed file. This state is service-owned, outside runner
recovery records.

If staging is missing or invalid during initial startup, the broker fails closed. After fixing
Vault access or account values, wait for the staging template and explicitly retry the service
through normal reconciliation. Check both the refresh unit and broker logs; do not edit runner
recovery records.

Rotation uses one source update in Vault. The broker's derived file refreshes automatically.
Client refreshes are established in their service stages and may briefly lag behind the broker.
Home Assistant's MQTT integration stores external broker credentials through its UI; changing
Vault does not by itself update that integration. Agree its supported rotation procedure during
the configuration phase, without rewriting its internal application state.

## Deployment Validation

For normal publication to `main`, record the completed runner revision and its render/check,
apply and health results. The runner performs the host check before apply; the manual checks below
are optional and do not introduce a separate promotion or timer-restoration gate.

### Optional Manual Host Checks

Use a clean phobos checkout at the exact reviewed revision. Coordinate any manual checkout changes
with the runner and let active reconciliation finish first. The virtual environment needs the
existing runtime dependencies; bootstrap
does not guarantee that the Abhaile package is installed. The password-refresh unit explicitly sets
`PYTHONPATH=/opt/abhaile/src` before invoking its module. Check that the candidate helper imports
without running password conversion:

```bash
sudo env PYTHONPATH=/opt/abhaile/src \
  /opt/abhaile/.venv/bin/python -m abhaile.cli.mosquitto_passwords --help
```

Render as the unprivileged `abhaile` user, then use sudo for Ansible to inspect protected live
state. A plain `make check HOST=phobos` does not perform this privilege separation. On phobos:

```bash
sudo -H -u abhaile \
  /opt/abhaile/.venv/bin/abhaile-render --host phobos --output /var/lib/abhaile

sudo env ANSIBLE_CONFIG=/opt/abhaile/ansible/ansible.cfg \
  ANSIBLE_LOCAL_TEMP=/tmp \
  ANSIBLE_ROLES_PATH=/opt/abhaile/ansible/roles \
  /usr/bin/ansible-playbook -i localhost, --connection=local --check \
  --extra-vars '{"abhaile_rendered_root":"/var/lib/abhaile/rendered","abhaile_config_root":"/opt/abhaile/config","abhaile_expected_host":"phobos"}' \
  /opt/abhaile/ansible/playbooks/reconcile.yml
```

For optional manual validation, use
[the same host-check procedure](operations.md#host-render-and-privileged-check) on deimos for
changes to shared definitions. These commands run in check mode and do not activate Mosquitto.
Resolve failures through git; do not interrupt an active runner or edit recovery records.

### Verify Runner Deployment

When deployment is intended, push the reviewed revision to `main` and follow the normal
[runner reconciliation workflow](operations.md#render-and-reconcile). There is no separate
candidate promotion step. If template enrollment changes, reconciliation publishes Vault Agent's
template and restarts the agent before starting the rootful broker. Verify the staging file exists
and is mode 0600 without printing its contents, then inspect:

```bash
systemctl status mosquitto-passwords.service mosquitto-passwords.path mosquitto.service
journalctl -u mosquitto-passwords.service -u mosquitto.service --since '10 minutes ago'
sudo podman healthcheck run systemd-mosquitto
```

The container health command checks that the running listener rejects anonymous MQTT v5
connections with reason code 135. It does not establish authenticated MQTT functionality.
Before declaring this stage ready, use Mosquitto
2.1 or newer client tools to verify all three accounts and anonymous rejection. Supply account
credentials through temporary mode-0600 client configuration files using `-o`, never `-u`/`-P`
values on the command line. Each file contains only the corresponding account's client options.
For example, with an operator-prepared protected profile:

```bash
# Terminal 1: subscribe with the account being tested.
mosquitto_sub -o /run/mqtt-client-check.conf -h 172.20.20.222 \
  -t abhaile/deployment-check -C 1 -W 10

# Terminal 2: publish the probe without retaining it.
mosquitto_pub -o /run/mqtt-client-check.conf -h 172.20.20.222 \
  -t abhaile/deployment-check -m deployment-check -q 1

# Use an empty profile so a default local profile cannot supply credentials.
mosquitto_sub -o /dev/null -h 172.20.20.222 \
  -t abhaile/deployment-check -E -W 5
```

The authenticated pair must exchange the probe for each account. The anonymous command must
fail with an authentication/authorization refusal, rather than a timeout or routing failure.
Remove temporary profiles after testing. Record the actual results in spec 0015.

Also verify that broker persistence survives a restart, an unchanged reconciliation does not
restart it, and a phobos reboot restores it. Proceed to Zigbee2MQTT after this Mosquitto stage's
startup, authentication, and persistence evidence is collected. Backup implementation and
restore evidence remain part of the spec's configuration phase.

## References

- [Mosquitto password conversion](https://mosquitto.org/man/mosquitto_passwd-1.html)
- [Mosquitto client configuration files](https://mosquitto.org/man/mosquitto_sub-1.html)
- [Home Assistant MQTT broker settings](https://www.home-assistant.io/integrations/mqtt/#broker-configuration)
