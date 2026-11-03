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
The next publication adds `https://home-assistant.abhaile.home.arpa` through internal
Caddy, retaining Home Assistant's native login and response headers. No Authelia gate
is added. Use the trusted Caddy root on the client device. After reconciliation, verify
login, dashboard rendering and live state updates through that HTTPS URL. Set it as
Home Assistant's local URL where appropriate; do not change external/remote access.
The direct service URL remains HTTP and requires native authentication after setup.

Configure Home Assistant's MQTT integration using the existing Mosquitto broker and
its dedicated identity from Vault. Do not install another broker or configure ZHA to
connect to the SLZB-06. Once MQTT connects, publish `ZIGBEE2MQTT_CONFIG_HOMEASSISTANT_ENABLED=true` in the
Zigbee2MQTT Quadlet. Reconciliation restarts Zigbee2MQTT, which publishes discovery
information through the broker; existing paired devices remain paired. Keep MQTT
discovery enabled in Home Assistant. No new Vault fields or policies are needed.

After the discovery revision reconciles, open **Settings > Devices & services > MQTT**.
Confirm the three paired SONOFF plugs appear (a Zigbee2MQTT bridge device may appear too).
Test one plug from Home Assistant and confirm its state also updates in Zigbee2MQTT.
Do not reset devices, re-pair them, install another broker or attach the coordinator
through ZHA. If devices do not appear, check Zigbee2MQTT logs and the MQTT integration
before changing network or broker configuration.

## Caddy-DMZ Access

Before deploying the route, open **Settings > System > Network > HTTP server**.
Keep forwarded-header support enabled and add `172.20.100.200` alongside the existing
trusted proxy `172.20.20.200`. Apply and confirm the settings after Home Assistant
restarts. Verify the internal URL still works.

After reconciliation, open `https://home-assistant.abhaile.dedyn.io` on the LAN and
again over WireGuard from outside the LAN. Verify the certificate is trusted, native
login succeeds, and dashboard state updates live. Test Companion app access and confirm
the internal URL still works. If Home Assistant reports an untrusted proxy, check its
logs for the actual connection source before changing the trusted proxy list.

See the [DNS and ingress runbook](dns-and-ingress.md) for resolver and WireGuard checks.

## References

- [Container installation](https://www.home-assistant.io/installation/linux/)
- [HTTP and trusted proxy settings](https://www.home-assistant.io/integrations/http/)
- [MQTT integration](https://www.home-assistant.io/integrations/mqtt/)
- [Zigbee2MQTT discovery](https://www.zigbee2mqtt.io/guide/usage/integrations/home_assistant.html)
