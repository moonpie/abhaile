# Spec: Home Automation Services

## Metadata

```yaml
id: SPEC-2026-015
title: Home Automation Services
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
supersedes: null
superseded_by: null
scope:
  hosts: [phobos]
  services: [home-assistant, mosquitto, zigbee2mqtt, esphome, frigate, go2rtc]
```

## Context

Phase 3 adds the home automation service group. All six services have stub
`service.yaml` files in `config/services/` with `podman.user: root`,
`podman.network: ipvlan-l2`, and empty `composition.container: {}` blocks. They
already have /32 addresses assigned in `config/network.yaml` (172.20.20.221–226)
and DNS A records in `svc.abhaile.home.arpa.` but are not yet in
`config/mapping.yaml`.

This group introduces patterns not present in Phase 1 core services:

- USB device passthrough (Zigbee coordinator for zigbee2mqtt)
- Hardware accelerator passthrough (Coral TPU for Frigate)
- Inter-service MQTT pub/sub (mosquitto as shared broker)
- Media streaming pipelines (go2rtc → frigate, go2rtc → home-assistant)
- mDNS/network discovery requirements (ESPHome device discovery)

The existing quadlet renderer, ingress aggregation, vault-agent template
collection, and include mechanism handle the standard composition patterns.
This spec defines how each service fits those patterns and what extensions are
needed for device passthrough and broker-mediated communication.

## Requirements

- [ ] Define complete `service.yaml` for all six services following ADR 0005
  patterns.
- [ ] Add all six services to `config/mapping.yaml` under phobos.
- [ ] Define inter-service network dependencies and systemd ordering.
- [ ] Define device passthrough mechanism for USB (zigbee2mqtt) and Coral TPU
  (frigate) in quadlet composition.
- [ ] Define vault-agent templates for services that need runtime secrets.
- [ ] Define ingress blocks for web-accessible services (home-assistant,
  zigbee2mqtt, esphome, frigate, go2rtc).
- [ ] Define MQTT broker configuration and client authentication model.

## Constraints

- All services run rootful on ipvlan-l2 (VLAN 20) with /32 addressing — already
  declared in stubs.
- Coral TPU is only on phobos (apex group, gasket/apex kernel modules already
  configured in Phase 1 host software).
- USB device passthrough requires `--device` flag in container units — the
  quadlet renderer must support this.
- No runtime secrets in rendered output — vault-agent delivers credentials at
  runtime per ADR 0006.
- MQTT traffic stays on VLAN 20 between service /32 addresses — no cross-VLAN
  routing needed.
- Frigate and go2rtc need access to camera streams on the IoT VLAN (VLAN 60) —
  this requires either host network or a separate interface. Decision deferred
  to open questions.

## Design

### Service Group Overview

| Service | Address | Role | Special Hardware |
| --- | --- | --- | --- |
| home-assistant | 172.20.20.221/32 | Automation hub, UI | None |
| mosquitto | 172.20.20.222/32 | MQTT broker | None |
| zigbee2mqtt | 172.20.20.223/32 | Zigbee coordinator bridge | USB dongle |
| esphome | 172.20.20.224/32 | ESP device management/OTA | None (mDNS) |
| go2rtc | 172.20.20.225/32 | RTSP/WebRTC media proxy | None |
| frigate | 172.20.20.226/32 | NVR with object detection | Coral TPU |

### Inter-Service Dependencies

```text
mosquitto (MQTT broker, no upstream deps beyond network/DNS)
  ← home-assistant (MQTT client, subscribes to sensor/device topics)
  ← zigbee2mqtt (MQTT client, publishes Zigbee device state)
  ← frigate (MQTT client, publishes detection events)

go2rtc (RTSP relay, receives camera streams)
  ← frigate (consumes go2rtc streams for detection)
  ← home-assistant (consumes go2rtc WebRTC for live view)

zigbee2mqtt → USB coordinator → Zigbee mesh
frigate → Coral TPU (/dev/apex_0)
esphome → mDNS discovery (host_network or avahi)
```

### Systemd Boot Ordering

All services in this group start after `abhaile-secrets-ready.service`
(vault-agent rendered credentials). Within the group:

```text
abhaile-secrets-ready.service
  → mosquitto.service (broker must be up before clients)
    → zigbee2mqtt.service (After=mosquitto)
    → home-assistant.service (After=mosquitto)
    → frigate.service (After=mosquitto, After=go2rtc)
  → go2rtc.service (no MQTT dependency, starts with secrets-ready)
  → esphome.service (no MQTT dependency, starts with secrets-ready)
```

### Per-Service Design

#### mosquitto

MQTT broker. All home automation services that publish or subscribe connect
here.

Composition:

- `composition.container` with named volumes: `config`, `data`, `log`
- `composition.config` for static `mosquitto.conf` (listener, persistence,
  log settings, password_file path)
- `composition.vault_agent.templates` for `mosquitto-passwords.ctmpl`
  (hashed password file for client authentication)
- `composition.systemd` for path/service watching vault-agent output to
  reload mosquitto on password changes

Ports: 1883 (MQTT), 9001 (WebSocket, optional for HA integration)

Design notes:

- Mosquitto listens on its /32 address only.
- Password file authentication — no anonymous access.
- Each client service (home-assistant, zigbee2mqtt, frigate) gets a dedicated
  MQTT user with credentials stored in Vault.

#### home-assistant

Central automation hub. Connects to mosquitto for device state, go2rtc for
camera streams, and exposes a web UI.

Composition:

- `composition.container` with named volumes: `config`
- `composition.config` for base `configuration.yaml` (template with MQTT
  broker address, go2rtc integration, trusted_proxies for Caddy)
- `composition.vault_agent.templates` for secrets (MQTT credentials, any API
  keys, internal integrations)
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (protected by Authelia forward auth)
- `composition.systemd` for path/service to reload HA on vault-agent secret
  rotation

Ports: 8123 (HTTP UI)

Design notes:

- Home Assistant config directory is persistent and operator-managed for
  automations/dashboards — render provides only the base `configuration.yaml`
  and secrets wiring.
- Trusted proxies include caddy-internal's /32 for forward auth headers.
- MQTT discovery enabled for zigbee2mqtt and frigate integration.

#### zigbee2mqtt

Bridges Zigbee mesh devices to MQTT topics. Requires USB Zigbee coordinator
passthrough.

Composition:

- `composition.container` with named volumes: `data`
- `composition.container.devices` — USB coordinator passthrough
- `composition.config` for `configuration.yaml` (template with MQTT broker
  address, serial port path, frontend settings)
- `composition.vault_agent.templates` for MQTT credentials and optional
  network encryption key
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (frontend UI, protected by Authelia)

Ports: 8080 (frontend UI)

Device passthrough: The quadlet `.container` unit needs `AddDevice=/dev/ttyUSB0`
(or `/dev/ttyACM0`, depending on coordinator model). The device path is
declared in `service.yaml` and rendered into the container unit.

Design notes:

- The exact USB device path depends on the coordinator hardware plugged into
  phobos. The renderer passes it through to `AddDevice=` in the quadlet.
- zigbee2mqtt persists network state in its data volume — loss of this volume
  requires re-pairing all devices.

#### esphome

Manages ESP8266/ESP32 devices. Provides OTA updates and a dashboard UI.
Requires mDNS for device discovery.

Composition:

- `composition.container` with named volumes: `config`
- `composition.config` for dashboard settings (if any static config needed)
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (dashboard UI, protected by Authelia)

Ports: 6052 (dashboard), 6053 (native API)

Design notes:

- ESPHome needs mDNS to discover devices on the network. With ipvlan-l2 the
  container shares the L2 domain with the services VLAN, so mDNS multicast
  should reach it. If IoT devices are on VLAN 60, ESPHome needs a route or
  additional interface to reach them (see open questions).
- No vault-agent templates needed unless API authentication is added.
- ESPHome config directory holds device YAML definitions maintained by the
  operator — render provides only the dashboard bootstrap.

#### go2rtc

Lightweight RTSP/WebRTC media proxy. Aggregates camera streams and serves them
to Frigate and Home Assistant.

Composition:

- `composition.container` with named volumes: `config`
- `composition.config` for `go2rtc.yaml` (template with stream definitions
  using camera RTSP URLs)
- `composition.vault_agent.templates` for camera credentials (RTSP
  username/password per camera)
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (WebRTC/API UI, protected by Authelia)

Ports: 1984 (API/UI), 8554 (RTSP), 8555 (WebRTC)

Design notes:

- go2rtc acts as the single point of camera connection — Frigate and Home
  Assistant both consume streams from go2rtc rather than connecting to cameras
  directly.
- Camera RTSP URLs contain credentials and are delivered via vault-agent
  template.
- go2rtc needs network access to camera devices on the IoT/Camera VLAN (see
  open questions).

#### frigate

NVR with real-time object detection using Coral TPU. Publishes detection events
to MQTT.

Composition:

- `composition.container` with named volumes: `config`, `media`
  (recordings/clips)
- `composition.container.devices` — Coral TPU passthrough (`/dev/apex_0`)
- `composition.config` for `config.yaml` (template with go2rtc integration,
  MQTT broker address, detector config for Coral, camera definitions)
- `composition.vault_agent.templates` for MQTT credentials
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (Frigate UI, protected by Authelia)
- `composition.systemd` for path/service if config reload is needed on
  secret rotation

Ports: 5000 (UI), 8971 (API)

Device passthrough: `AddDevice=/dev/apex_0` in the quadlet `.container` unit.
The Coral TPU device is already configured on phobos (apex group, udev rules,
kernel modules from Phase 1 host software config).

Design notes:

- Frigate consumes RTSP streams from go2rtc, not directly from cameras.
- The Coral TPU detector runs in `edgetpu` mode, requiring the apex device node.
- Media storage volume needs sizing consideration — recordings accumulate.
- Frigate publishes MQTT events that Home Assistant subscribes to for
  automation triggers.

### Device Passthrough in Quadlets

The quadlet renderer currently supports `named_volumes` and `mounted_files` in
container composition. Device passthrough adds a new field:

```yaml
composition:
  container:
    devices:
      - /dev/ttyUSB0  # zigbee2mqtt USB coordinator
```

This renders to `AddDevice=/dev/ttyUSB0` in the `.container` quadlet unit.

For Frigate's Coral TPU:

```yaml
composition:
  container:
    devices:
      - /dev/apex_0
```

The renderer passes device paths directly to `AddDevice=` lines. No
group/permission logic is needed in the renderer — host udev rules (already
configured) set device ownership.

### Vault-Agent Template Aggregation

Services declaring `composition.vault_agent.templates` have their templates
collected by vault-agent on phobos (existing pattern from core services). New
templates for this group:

| Service | Template | Output | Content |
| --- | --- | --- | --- |
| mosquitto | `mosquitto-passwords.ctmpl` | `mosquitto-passwords` | Hashed passwords for all MQTT clients |
| home-assistant | `home-assistant-secrets.ctmpl` | `home-assistant-secrets.yaml` | MQTT creds, integration API keys |
| zigbee2mqtt | `zigbee2mqtt-secret.ctmpl` | `zigbee2mqtt-secret.yaml` | MQTT creds, network key |
| go2rtc | `go2rtc-streams.ctmpl` | `go2rtc-streams.yaml` | Camera RTSP URLs with credentials |
| frigate | `frigate-mqtt.ctmpl` | `frigate-mqtt.env` | MQTT credentials |

These follow the existing pattern: vault-agent renders to
`/srv/vault/agent/out/<filename>`, systemd path units watch the output, and
trigger services copy/reload as needed.

### Ingress Aggregation

All web-accessible services contribute internal ingress blocks to
caddy-internal following the existing pattern:

| Service | FQDN | Auth |
| --- | --- | --- |
| home-assistant | `home-assistant.abhaile.home.arpa` | Authelia forward auth |
| zigbee2mqtt | `zigbee2mqtt.abhaile.home.arpa` | Authelia forward auth |
| esphome | `esphome.abhaile.home.arpa` | Authelia forward auth |
| go2rtc | `go2rtc.abhaile.home.arpa` | Authelia forward auth |
| frigate | `frigate.abhaile.home.arpa` | Authelia forward auth |

mosquitto does not need ingress — MQTT clients connect directly to its /32
address on port 1883.

Home Assistant may optionally also get a DMZ ingress block for external access
via `caddy-dmz` (deferred to open questions).

### DNS Records

Already defined in `config/network.yaml`:

- `home-assistant.svc.abhaile.home.arpa. A 172.20.20.221`
- `mosquitto.svc.abhaile.home.arpa. A 172.20.20.222`
- `zigbee2mqtt.svc.abhaile.home.arpa. A 172.20.20.223`
- `esphome.svc.abhaile.home.arpa. A 172.20.20.224`
- `go2rtc.svc.abhaile.home.arpa. A 172.20.20.225`
- `frigate.svc.abhaile.home.arpa. A 172.20.20.226`

CNAME records in `abhaile.home.arpa.` for user-facing names will be added to
`config/network.yaml` during implementation (e.g., `ha` → caddy,
`cameras` → caddy).

## Decision Notes

- Decision: All services run rootful on ipvlan-l2.

- Rationale: Device passthrough (USB, TPU) requires rootful containers. Keeping the entire group rootful avoids mixed privilege models within a tightly coupled service set.

- Impact: Simpler container management; all quadlets go to `/etc/containers/systemd/`.

- ADR: null

- Decision: mosquitto is the single MQTT broker for the group.

- Rationale: zigbee2mqtt, frigate, and home-assistant all need an MQTT bus. A single broker on a dedicated /32 with authenticated access is simpler than embedded brokers or multiple instances.

- Impact: mosquitto is a hard dependency — if it's down, device state stops flowing.

- ADR: null

- Decision: go2rtc as a standalone service rather than embedded in Frigate.

- Rationale: Standalone go2rtc allows Home Assistant to consume WebRTC streams without going through Frigate, and allows camera connection management independent of NVR concerns.

- Impact: Two containers instead of one for the camera pipeline, but cleaner separation of concerns.

- ADR: null

- Decision: Device passthrough uses `AddDevice=` in quadlet units via a `devices` field in service.yaml.

- Rationale: `AddDevice=` is the podman quadlet equivalent of `--device`. A declarative list in service.yaml keeps device mapping in config/ source of truth.

- Impact: Quadlet renderer needs to support the `devices` field. Minimal change — one new key rendered to one new quadlet directive per device.

- ADR: null

- Decision: Coral TPU access uses existing phobos host configuration (apex group, udev rules, kernel modules).

- Rationale: Phase 1 host software already configures the TPU device permissions. Frigate just needs `AddDevice=/dev/apex_0` — no additional host config work.

- Impact: Frigate can only run on phobos (only host with Coral TPU).

- ADR: null

## Acceptance Criteria

- [ ] Detail `service.yaml` definitions for all services in this group
- [ ] Quadlet renderer supports `devices` field producing `AddDevice=` directives
- [ ] All six services added to `config/mapping.yaml` under phobos
- [ ] Mosquitto vault-agent template produces password file with per-client credentials
- [ ] Inter-service systemd ordering renders correctly (mosquitto before clients, go2rtc before frigate)
- [ ] Ingress blocks render for all web-accessible services with Authelia forward auth
- [ ] Vault-agent on phobos collects templates from all six services
- [ ] Unit tests pass for new renderer logic (devices field)
- [ ] Integration test: full render of phobos produces correct artifacts for all six services
- [ ] No regressions in existing integration tests

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- Camera hardware selection, IP assignment, and RTSP configuration (operator responsibility).
- Home Assistant automation/dashboard content (operator-managed config, not rendered).
- Zigbee device pairing and mesh configuration.
- Frigate recording retention policies and storage sizing.
- IoT VLAN (60) firewall rules and inter-VLAN routing (Phase 4 network config).
- DMZ/external access for Home Assistant (separate decision).
- HA (high-availability) or multi-host deployment of this group.

## Open Questions

1. **Camera VLAN access** — go2rtc and frigate need to reach cameras on the
   IoT/Camera VLAN (VLAN 60). Options: (a) add a second ipvlan-l2 interface on
   VLAN 60 to those containers, (b) rely on inter-VLAN routing at the gateway
   with appropriate ACLs, (c) run go2rtc with host networking. Which approach?

1. **ESPHome mDNS discovery** — ESPHome discovers devices via mDNS. If IoT
   devices are on VLAN 60 and ESPHome is on VLAN 20, mDNS won't cross VLANs.
   Options: (a) avahi reflector, (b) static device list in ESPHome (no mDNS
   needed for compiled devices), (c) second interface on VLAN 60. Which
   approach?

1. **USB device path stability** — Zigbee coordinators can change device node
   on reboot (`/dev/ttyUSB0` vs `/dev/ttyUSB1`). Should we add a udev rule to
   create a stable symlink (e.g., `/dev/zigbee-coordinator`) and reference that
   in the quadlet? If yes, this adds a host software config item.

1. **Home Assistant external access** — Should HA get a DMZ ingress block via
   caddy-dmz for `ha.abhaile.dedyn.io`? Or keep it internal-only with VPN
   access?

1. **Vault paths and MQTT credentials structure** — What Vault KV path
   structure for MQTT client credentials? Proposed:
   `secret/services/mosquitto/clients/{home-assistant,zigbee2mqtt,frigate}` each
   containing `username` and `password` keys.

1. **Frigate media storage location** — Should Frigate's media volume use a
   dedicated mount/partition, or a subdirectory under `/srv/frigate/media/`?
   Recordings can grow large and impact disk space for other services.

1. **go2rtc hardware acceleration** — Should go2rtc use VA-API/QSV for
   transcoding? phobos has an i7-7700T with Intel HD 630. If yes, this needs
   `/dev/dri` device passthrough.

## References

- `config/services/home-assistant/service.yaml` (stub)
- `config/services/mosquitto/service.yaml` (stub)
- `config/services/zigbee2mqtt/service.yaml` (stub)
- `config/services/esphome/service.yaml` (stub)
- `config/services/frigate/service.yaml` (stub)
- `config/services/go2rtc/service.yaml` (stub)
- `config/network.yaml` (address assignments)
- `config/mapping.yaml` (current host mapping — group not yet added)
- `config/services/authelia/service.yaml` (reference for complete service pattern)
- `docs/adr/0005-service-authoring-model.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/specs/proposed/0021-network-devices.md` (SPEC-2026-021 — camera VLAN ACLs, IoT VLAN routing)
- `docs/specs/proposed/0016-services-monitoring.md` (SPEC-2026-016 — Prometheus scraping of this group)
- `docs/specs/accepted/0011-core-services.md` (SPEC-2026-011 — Phase 1 reference implementation)
