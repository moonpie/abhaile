# Zigbee2MQTT Deployment

This stage follows [spec 0015](../specs/active/0015-services-home-automation.md).
The operator confirmed a fresh SLZB-06 network. Device pairing and broader application
configuration follow deployment; do not restore or reset an unrelated network.

## Prerequisite Publication

Publish the policy change and this runbook before mapping Zigbee2MQTT to Phobos. Verify the
runner has accepted that prerequisite revision, then apply the policy with the operator's
existing Vault login. Run each command separately; never paste credential values into chat.

```bash
export VAULT_ADDR=http://172.20.20.204:8200
```

```bash
set -o pipefail
```

```bash
sudo cat /opt/abhaile/policies/vault-agent.hcl | vault policy write vault-agent -
```

```bash
vault policy read vault-agent
```

The policy must allow reading `secret/data/abhaile/zigbee2mqtt`. The operator has already
created its `frontend_auth_token` field. MQTT continues to use the dedicated Zigbee2MQTT
fields in `secret/abhaile/mqtt`; do not create a second MQTT credential copy in Vault.

## Activation

Publish the reviewed service, mapping, DNS and SSO changes after policy installation.
Follow the normal runner check/live path; do not manually precreate application files.

The container uses `172.20.20.223`, broker `172.20.20.222:1883`, and coordinator
`tcp://172.20.50.10:6638` with adapter `zstack`. Git owns container startup settings,
ingress, secret delivery and the persistent mount. Zigbee2MQTT owns everything it writes
under `/srv/zigbee2mqtt/data`, including generated network identifiers and configuration.
No setup server is enabled; invalid startup configuration must fail closed.

The environment refresh service copies the protected Vault Agent output into
`/etc/zigbee2mqtt/zigbee2mqtt.env` and refreshes the service when needed. Do not print
either file or inspect the container's full environment. Environment settings are also
persisted by Zigbee2MQTT; umask 0077 protects newly created application files.

## Operator Verification

```bash
sudo journalctl -fu abhaile-runner.service -o cat
```

```bash
sudo systemctl status zigbee2mqtt.service --no-pager -l
```

```bash
sudo podman inspect systemd-zigbee2mqtt --format '{{.State.Status}} {{.State.Health.Status}}'
```

```bash
sudo stat -c '%n mode=%a owner=%u:%g' /srv/zigbee2mqtt/data
```

Expected: running/healthy and data root root:root 0750. Check first-use volume metadata;
do not weaken declared permissions merely to suppress drift. The HTTP health probe checks
frontend availability, not MQTT connectivity or frontend authorization by itself.

Open `https://zigbee2mqtt.abhaile.home.arpa` in a browser and verify Authelia authentication
and the admins-only authorization rule. Enter the native frontend token privately using
the operator's secret-management workflow; do not share token-bearing frontend URLs or put
credentials in command arguments.
Verify direct control/WebSocket access cannot operate without the native token; the
static frontend page may be publicly served. Confirm the fresh coordinator starts,
MQTT connects, and device joining remains closed before any pairing action.

Verify unchanged reconciliation preserves application files and does not restart the
service. Record startup, authorization and coordinator evidence in spec 0015. Choose
any restart/reboot checks based on the actual configuration risk and planned maintenance.

## Upstream Basis

- [Pinned release 2.14.2](https://github.com/Koenkk/zigbee2mqtt/releases/tag/2.14.2)
- [Environment settings](https://www.zigbee2mqtt.io/guide/configuration/)
- [Pinned startup/onboarding behavior](https://github.com/Koenkk/zigbee2mqtt/blob/2.14.2/lib/util/onboarding.ts)
- [MQTT settings](https://www.zigbee2mqtt.io/guide/configuration/mqtt.html)
- [Frontend authentication](https://www.zigbee2mqtt.io/guide/configuration/frontend.html)
