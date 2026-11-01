# Home Assistant Deployment

Follow [spec 0015](../specs/active/0015-services-home-automation.md). The initial
activation maps the container to Phobos; internal Caddy ingress follows owner setup
and trusted proxy configuration.

## Ownership and Runtime

Home Assistant Container 2026.10.4 uses `172.20.20.221:8123` on the existing Services
VLAN. The complete `/config` directory persists under `/srv/home-assistant/config`.
Home Assistant owns its configuration, integrations, registries, credentials and
SQLite database. GitOps manages the container and directory metadata, not those files.
No host networking, privileged mode, Bluetooth/D-Bus access or direct Zigbee coordinator
connection is required for this stage. Allow up to five minutes for container shutdown.

## Bootstrap Decision

The operator confirmed no Omada ACLs currently restrict the listener. Before its owner
account exists, a reachable Home Assistant instance exposes unauthenticated owner
creation. Authelia on a Caddy route alone cannot protect the direct service listener.
On 2026-11-01 the operator approved a short attended first-run setup window on the
existing open lab network. Create the owner promptly after startup. Do not leave the
instance waiting indefinitely for owner creation; do not add ACLs solely for this stage.

## Subsequent Steps

Deploy through the normal render/check/reconcile path, then check startup:

```bash
sudo systemctl status home-assistant.service --no-pager -l
```

```bash
sudo journalctl -u home-assistant.service --since '15 minutes ago' --no-pager -o cat -n 60
```

Open `http://home-assistant.svc.abhaile.home.arpa:8123` (or
`http://172.20.20.221:8123`) and create the owner account privately. This initial direct
connection is HTTP. Keep credentials out of chat and Git. Initial startup may take
several minutes; inspect logs if the UI is unavailable. Do not connect ZHA to the SLZB-06.

Complete the basic location/timezone setup. Optional integrations can wait. Confirm the
normal login/dashboard appears and owner creation is no longer offered.

In **Settings > System > Network > HTTP server**, enable forwarding support and trust only internal
Caddy's address `172.20.20.200`, not an entire VLAN. Confirm the settings after the
application restarts; Home Assistant reverts unconfirmed HTTP changes after five minutes.
Publish the reviewed internal Caddy route with Home Assistant's native authentication.

Configure Home Assistant's MQTT integration using the existing Mosquitto broker and
its dedicated identity from Vault. Do not install another broker or configure ZHA to
connect to the SLZB-06. Enable Zigbee2MQTT Home Assistant discovery through its declared
startup setting when the integration is ready; existing paired devices remain paired.

## References

- [Container installation](https://www.home-assistant.io/installation/linux/)
- [HTTP and trusted proxy settings](https://www.home-assistant.io/integrations/http/)
- [MQTT integration](https://www.home-assistant.io/integrations/mqtt/)
- [Zigbee2MQTT discovery](https://www.zigbee2mqtt.io/guide/usage/integrations/home_assistant.html)
