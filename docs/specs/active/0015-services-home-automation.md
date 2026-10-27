# Spec: Home Automation Services

## Metadata

```yaml
id: SPEC-2026-015
title: Home Automation Services
status: active
owner: moonpie
created: 2026-06-05
updated: 2026-10-27
related_adrs:
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0014-host-storage-and-nas-mount-boundaries
supersedes: null
superseded_by: null
scope:
  hosts: [phobos]
  services: [home-assistant, mosquitto, zigbee2mqtt, esphome, frigate, go2rtc]
```

## Context

Deploy a simple home-automation platform on phobos for the equipment already in the home and for
likely near-term additions. The initial deployment may use supported cloud integrations where that
gets existing devices working sooner. The intended long-term direction is local control without a
runtime dependency on vendor clouds.

Current equipment includes:

- Reolink cameras
- Hive heating, thermostat, and radiator valves
- IKEA Tradfri lights
- SONOFF S60ZBTPG Zigbee plugs
- Teckin SP27 and Gosund UP111 Wi-Fi plugs managed by Smart Life
- Shelly 1PM Mini Gen4 and Shelly 2PM Gen4 devices
- an Ethernet/PoE SMLIGHT SLZB-06 Zigbee coordinator with a CC2652P radio at `172.20.50.10`
- a PCIe Coral TPU exposed on phobos as `/dev/apex_0`

The five services have stub definitions under `config/services/` and existing addresses in
`config/network.yaml`, but they are not mapped to phobos. The obsolete standalone go2rtc stub and
address also remain from the earlier proposal.

## Goals

- Deploy Home Assistant, Mosquitto, Zigbee2MQTT, ESPHome, and Frigate on phobos.
- Use Frigate's bundled go2rtc rather than operating a separate go2rtc service.
- Provide a stable local MQTT bus with one identity per client.
- Connect Zigbee2MQTT to the SMLIGHT coordinator over Ethernet instead of USB passthrough.
- Pass the Coral TPU to Frigate.
- Deploy the services first, then agree application configuration ownership case by case after
  inspecting their supported files and runtime behaviour.
- Establish backup and restore coverage for irreplaceable service state.
- Permit supported Hive and Tuya cloud integrations during initial adoption without making them
  architectural dependencies of the service deployment.

## Non-Goals

- Pairing or migrating every existing device as part of service deployment.
- Removing the Hive or IKEA hubs during the initial rollout.
- Converting Smart Life plugs to local firmware.
- Managing Omada VLANs, ACLs, multicast relays, or DHCP reservations.
- External Home Assistant access or a public DMZ ingress.
- High availability or multi-host failover for the home-automation group.
- Cross-spec host capacity validation; assess capacity after the planned service estate is deployed,
  unless operational symptoms require earlier investigation.
- Adding Matter, Thread, Z-Wave, local voice, or Bluetooth proxy services without corresponding
  hardware or a separate accepted requirement.

## Service Addresses

Use one continuous address block on the Services VLAN:

| Service | Address | Role |
| --- | --- | --- |
| home-assistant | `172.20.20.221/32` | Automation hub and UI |
| mosquitto | `172.20.20.222/32` | MQTT broker |
| zigbee2mqtt | `172.20.20.223/32` | Zigbee-to-MQTT bridge |
| esphome | `172.20.20.224/32` | ESP device management and OTA |
| frigate | `172.20.20.225/32` | NVR, detection, and bundled go2rtc |

Remove the entire obsolete `config/services/go2rtc/` directory and its standalone service identity.
Remove Frigate's old `.226` identity rather than retaining an alias. Address `.226` becomes
unallocated.

## Architecture

```text
IKEA, SONOFF, and later Hive Zigbee devices
                  |
       SMLIGHT PoE coordinator
                  | TCP 6638
            Zigbee2MQTT
                  |
              Mosquitto
                  |
           Home Assistant

Shelly ----------------------> Home Assistant local integration
Hive Hub/cloud --------------> Home Assistant during initial migration
Smart Life/Tuya cloud -------> Home Assistant during initial migration
Reolink ---> Frigate/go2rtc --> Home Assistant live video
       `---------------------> Home Assistant Reolink integration
```

All five containers use rootful Quadlets on `ipvlan-l2`. Traffic among their Services VLAN `/32`
addresses does not cross the gateway. Existing routed unicast connectivity is used for IoT and
Camera VLAN devices. No additional phobos VLAN interface, container network, or host networking is
introduced.

Cross-VLAN multicast discovery is not required for deployment. Use stable addresses or DNS names
for devices on other VLANs. A future Omada automation specification may manage ACLs and multicast
reflection.

## Service Design

### Delivery and Configuration Ownership

Deliver this spec in two phases. First deploy all five services using their defaults where suitable
and only the additional configuration needed for secure startup and deployment validation. Git owns
container definitions, ingress, secret delivery, storage mounts, and service lifecycle throughout.
Supply required settings through the existing service composition mechanisms; deployment must not
expose an insecure default merely to defer configuration.

After all five services deploy successfully, configure each application manually on the host and
inspect its supported configuration files, UI behaviour, and file rewrites. With that evidence,
agree which settings are stable, which are mutable, and whether supported separate files can keep
their ownership clear. Only then add selected application configuration to git through
`composition.config` for installation at the appropriate `/srv/<service>/` paths. Do not introduce
a seed-only installation policy or new ownership metadata. Until ownership is agreed, reconciliation
must preserve application-managed files and data.

The service designs below describe the final configured outcome. Container health and secure
ingress establish deployment readiness; MQTT integrations, coordinator connectivity, camera
recording, retention, and restore evidence establish the later functional outcome. A service that
requires configuration before it can start receives the minimum necessary during deployment.

### Mosquitto

- Persist broker data and configuration.
- Disable anonymous access.
- Give Home Assistant, Zigbee2MQTT, and Frigate separate MQTT identities.
- Deliver credentials through the existing Vault Agent and service-owned copy/refresh pattern.
- Listen on the internal Services VLAN address and require authentication from every client; do not
  add HTTP ingress.
- Defer source-VLAN restrictions to SPEC-2026-021 rather than adding a host firewall solely for
  Mosquitto.
- Start before MQTT clients, but allow clients to reconnect rather than hard-coupling their
  lifecycle to the broker with `Requires=`.

### Zigbee2MQTT

- Connect to the SMLIGHT SLZB-06 at `172.20.50.10:6638` over Ethernet.
- Use the Zigbee2MQTT `zstack` adapter driver for the coordinator's CC2652P radio.
- Persist Zigbee2MQTT data, including coordinator/network metadata.
- Use a dedicated Mosquitto identity delivered by Vault Agent.
- Publish its frontend through internal Caddy ingress protected by Authelia.
- Do not add USB device passthrough or a coordinator udev rule.

The initial local Zigbee adoption targets IKEA Tradfri devices and SONOFF S60ZBTPG plugs. Hive
migration is deliberately later because boiler control and fallback behaviour require separate
validation.

### Home Assistant

- Persist the complete Home Assistant configuration directory.
- Treat that directory as application/operator-owned mutable state; reconciliation must not replace
  UI-managed automations, dashboards, registries, or integration data.
- Decide which application files to manage declaratively during the per-service configuration
  phase; preserve manually configured state until that ownership is agreed.
- Configure MQTT discovery and connect using a dedicated broker identity.
- Publish internal ingress through Caddy and retain Home Assistant's native authentication.
- Configure trusted proxy settings for the internal Caddy service.
- Permit initial use of the supported Hive and Tuya integrations.
- Use native local integrations for Shelly and Reolink.

### ESPHome

- Deploy the dashboard even though no ESPHome-managed device is currently confirmed.
- Persist the operator-managed device configuration directory.
- Publish the dashboard through internal Caddy ingress protected by Authelia.
- Do not require mDNS across VLANs; devices may be configured by stable address.
- Do not add host networking, an Avahi reflector, or another phobos VLAN interface.

Deploying ESPHome now is intentional: it makes the expected tool available before the first
compatible device is introduced.

### Frigate

- Use Frigate's bundled go2rtc for live view and restreaming.
- Pass `/dev/apex_0` to the rootful container with Quadlet `AddDevice=` and require successful Coral
  detector initialization as runtime proof. Add a supplemental group only if the image's effective
  runtime user cannot open the device; do not use ad hoc permission changes or a privileged
  container.
- Persist configuration and database state separately from recording media.
- Store recordings, clips, and exports under the NVR-independent `/srv/surveillance/` boundary
  defined by SPEC-2026-030; keep Frigate configuration and database state under `/srv/frigate/`.
- Use a dedicated Mosquitto identity delivered by Vault Agent.
- Connect to Reolink cameras over existing routed unicast connectivity.
- Publish authenticated port `8971` through internal Caddy ingress.
- Do not configure consumers or ingress to use unauthenticated port `5000` initially.
- Enable RTSP/WebRTC listeners only when a named Home Assistant use case requires them. Defer
  source-network enforcement for direct service ports to SPEC-2026-021 and document any temporary
  exposure while routing remains open.
- Initially target three days of continuous recordings, seven days of motion recordings, and
  30 days of alert/detection recordings, following Frigate's conservative retention example.
  These overlapping retention targets are subject to available capacity.
- Preserve at least the greater of 15% of `/srv` capacity or 50 GiB using the storage guard below.
  Protecting shared service storage takes priority over recording retention.

#### Storage Pressure and Recovery

Use one small host-side systemd timer and guard, checking available space on the filesystem
containing `/srv/surveillance/` every minute. Stop Frigate cleanly before free space reaches the
reserve. Select and document additional headroom for writes between checks and during shutdown
using the configured aggregate camera bitrate. This is a periodic emergency brake, not a hard
filesystem reservation or protection against arbitrary growth by other services.

When the guard stops Frigate, record one persistent service-owned inhibition marker outside runner
recovery state. Every start requires both sufficient free space and an absent inhibition marker.
Reboot, automatic restarts, and reconciliation must respect this gate even after space recovers.
Log the storage reason distinctly. An inhibited Frigate remains visibly degraded; existing health
failure and repair cooldown reporting may remain, but repair attempts must not bypass the gate.
Do not modify runner recovery records or introduce a general inhibition or health framework.

An inhibited Frigate loses recording, detection, and its live-view/restream services. Its retention
cleanup also stops, so waiting alone will not reclaim space. Changing retention settings while
Frigate is stopped does not itself reclaim space. Recovery is manual: safely reclaim unrelated
space or use a documented maintenance procedure with Frigate-supported operations, verify sufficient
headroom, explicitly clear inhibition, and start Frigate. Document that procedure before enabling
recording. Do not automatically resume Frigate or delete its media files externally.
Frigate's database tracks recordings; external deletion can leave missing-file references and
incorrect usage accounting. A directory/user quota can instead cause write failures without
triggering Frigate's filesystem-free-space cleanup. Neither is the normal control mechanism.

Each camera has a 256 GB SD card. Camera-managed SD recording provides an independent fallback
while the camera remains powered and recording is enabled. Frigate does not manage these cards or
automatically backfill its timeline from them; the local Home Assistant Reolink integration can
provide separate playback where supported.

Keep this initial policy under review. After one week of recording operation, inspect actual
bitrate, retained history, `/srv` free space, and any guard activations before deciding whether to
change retention or storage allocation. Record the observation here. SPEC-2026-016 owns disk-space
and storage-inhibition notifications; the local guard must work without the monitoring stack.

The initial camera inventory is:

| Camera | Model | Address | Status |
| --- | --- | --- | --- |
| Doorbell | Reolink D340P PoE | `172.20.60.10` | Deployed |
| House Gable | Reolink RLC-540A PoE | `172.20.60.11` | Deployed |
| House Front | Reolink RLC-540A PoE | `172.20.60.12` | Deployed |
| House Back | Reolink RLC-540A PoE | `172.20.60.13` | Deployed |
| Garage Front | Reolink RLC-540A PoE | `172.20.60.14` | Deployed |
| Garage Back | Reolink RLC-540A PoE | `172.20.60.15` | Planned |
| Garage Internal | Reolink RLC-540A PoE | `172.20.60.16` | Planned |

## Ordering and Failure Behaviour

Use ordinary systemd ordering, not a tightly coupled application stack:

```text
network-online.target
  -> secrets-ready and service-specific secret copy units
  -> mosquitto -> home-assistant, zigbee2mqtt, frigate
  -> esphome
```

Clients use `After=` and, where useful, `Wants=` for Mosquitto. A broker restart must not stop the
client services; they are expected to reconnect. Each service uses its own restart policy and health
evidence.

## Secrets

No resolved secret may enter git or rendered artifacts. Use the existing Vault Agent aggregation and
service-owned copy/refresh pattern for:

- Mosquitto password-file material
- MQTT client credentials
- Reolink camera credentials used by Frigate from `secret/abhaile/reolink`
- other credentials that must be available as files or environment variables

Use one `secret/abhaile/mqtt` KV secret with distinct username and password fields for Home
Assistant, Zigbee2MQTT, and Frigate. Vault Agent renders client-specific environment fragments and a
broker-side plaintext staging file. A service-owned refresh unit converts the staged broker file to
Mosquitto's hashed password-file format before atomically installing it; plaintext credentials must
not appear in process arguments, git, or ordinary rendered artifacts.

Home Assistant integrations configured through its UI remain in Home Assistant's protected
persistent configuration. Do not duplicate those values into declarative configuration merely to
make them visible to Abhaile.

## Backups

Back up state whose loss would require significant manual reconstruction:

- Home Assistant configuration and database
- Zigbee2MQTT data and coordinator/network backup
- Mosquitto persistent data and configuration
- ESPHome device definitions and secrets
- Frigate configuration and database

Frigate recordings under `/srv/surveillance/` follow a separate storage and retention policy and
need not be included in the configuration backup. Cover every state set listed above. Before
accepting the spec, perform one representative end-to-end restore of Home Assistant and validate
that the Zigbee2MQTT coordinator/network backup can be read and is suitable for recovery.

Backup output uses `/srv/backups/<service>/` as defined by SPEC-2026-030 and ADR 0014. The backup
tool, retention, encryption, and off-host replication policy remain to be selected. A local backup
on the same NVMe device is staging or rapid-recovery material, not independent protection.

## Implementation Plan

### Phase 1: Deploy the Services

1. Normalize the address block and remove the standalone go2rtc service directory and identity.
1. Complete schema validation and focused tests for the renderer-supported container `devices`
   field.
1. Implement and reconcile Mosquitto, Zigbee2MQTT, Home Assistant, ESPHome, and Frigate in that
   order, including their persistent mounts, secret delivery, ingress, and required startup settings.
1. Validate each service's startup, secure access, and persistence before proceeding to the next.
   Use defaults where suitable and keep optional integrations and recording disabled until configured.
   Complete required first-user setup and any broker/coordinator configuration needed for secure
   startup; this does not decide eventual ownership of the application's remaining settings.
1. Confirm deployment reconciliation is idempotent and all five services return after reboot.

Each service stage must render and pass Ansible check mode before live reconciliation. Deployment
success does not require completed device adoption, camera recording, or backup-policy selection.

### Phase 2: Configure and Validate Each Service

1. Configure each application manually, inspect its configuration model, and agree which files or
   settings to move into git using existing composition support. Verify reconciliation preserves
   the remaining application-managed state.
1. Complete MQTT integrations, Zigbee coordinator connectivity, and selected Home Assistant
   integrations. Pairing or migrating every device remains outside this spec.
1. Configure Frigate cameras, verify Coral operation, and validate retention and the storage guard
   before enabling recording. Select guard headroom using configured aggregate camera bitrates.
1. Select the backup tool, schedule, retention, encryption, and independent destination; implement
   coverage and collect the required restore evidence before completing the spec.
1. Review actual recording storage use after one week and record the results here.

Both phases belong to this spec. Completing deployment is a milestone, not acceptance of the full
spec. Device migration can proceed independently once the relevant service is configured.

## Acceptance Criteria

### Deployment Milestone

- [ ] `config/network.yaml` contains the five-service `.221–.225` block, with Frigate at `.225`, no
  standalone go2rtc identity, and `.226` unallocated.
- [ ] The obsolete `config/services/go2rtc/` directory is removed in full.
- [ ] The five services are mapped to phobos.
- [ ] Container `devices` is accepted by schema validation and covered by focused tests.
- [ ] All five services start with defaults or minimum required secure configuration, persistent
  mounts, git-owned deployment definitions, and working ingress/secret delivery as applicable.
- [ ] Mosquitto rejects anonymous clients and uses distinct client identities with protected
  secret delivery before deployment readiness is declared.
- [ ] HTTP services have the agreed ingress authentication and protected direct listeners;
  required administrator setup is complete and no unauthenticated management/onboarding bypass
  remains exposed. Home Assistant and Frigate retain native authentication.
- [ ] Zigbee2MQTT and ESPHome dashboards use Authelia-protected internal Caddy ingress; direct
  dashboard access requires supported native authentication or is inaccessible.
- [ ] No ingress or configured consumer uses Frigate's unauthenticated port `5000`; any enabled
  RTSP/WebRTC listener has a named Home Assistant use case and documented temporary exposure.
- [ ] A full phobos render and Ansible check pass before live reconciliation.
- [ ] Reconciliation is idempotent after deployment and preserves application-managed files.
- [ ] All five services survive a phobos reboot and return to their configured deployment state.
- [ ] Existing tests and deployed services have no regressions.

### Per-Service Configuration and Completion

- [ ] Application configuration ownership is agreed per service after manual configuration and
  inspection; selected git-managed files use existing composition support and reconciliation
  preserves application-owned state without a new seed-only mechanism.
- [ ] Zigbee2MQTT connects to the SMLIGHT SLZB-06 at `172.20.50.10:6638` using `zstack` and persists
  its network state.
- [ ] Home Assistant persists UI-managed state, connects to MQTT, and is reachable through internal
  Caddy using native authentication.
- [ ] ESPHome is deployed, persistent, and reachable through internal Caddy without requiring
  cross-VLAN mDNS.
- [ ] Frigate uses bundled go2rtc, detects the Coral TPU, reaches the initial Reolink cameras, and is
  reachable through authenticated internal ingress.
- [ ] Frigate stores recordings, clips, and exports under `/srv/surveillance/`, separately from its
  backed-up configuration and database state.
- [ ] Frigate targets three days of continuous, seven days of motion, and 30 days of
  alert/detection recordings, with capacity protection taking priority.
- [ ] A one-minute storage guard stops Frigate cleanly with documented headroom above the greater
  of 15% of `/srv` capacity or 50 GiB; the same start gate prevents restart below the threshold.
- [ ] Storage inhibition is clearly logged and visible to reconciliation, survives restart/reboot
  attempts through a persistent service-owned marker even after free space recovers, and requires
  explicit operator clearance and sufficient space to resume. Degraded/cooldown reporting and a
  safe manual recovery procedure are documented without external media deletion.
- [ ] Camera SD recording and separate local playback are checked as fallback coverage; no
  automatic Frigate backfill is assumed.
- [ ] One week after recording begins, actual storage use and retained history are reviewed and
  the observation and any policy changes are recorded here.
- [ ] No service requires a second phobos VLAN interface or host networking.
- [ ] Service credentials are delivered without plaintext secrets in git or rendered output.
- [ ] Backup coverage exists for every listed state set, Home Assistant is restored end to end, and
  the Zigbee2MQTT coordinator/network backup is validated as readable and suitable for recovery.
- [ ] The final configured services pass render/check validation, reconcile idempotently, and
  return healthy after reboot without regressions.

### Evidence

For each completed criterion, record the implementation commit and the relevant automated test,
render result, dry-run/check result, host observation, or restore evidence.

## Agreed Implementation Decisions

1. **MQTT secrets:** use one `secret/abhaile/mqtt` secret with per-client fields and generate the
   hashed broker password file from a protected Vault Agent staging file.
1. **Direct Frigate ports:** use authenticated `8971` through internal Caddy, leave `5000` unused,
   enable RTSP/WebRTC only for a named Home Assistant requirement, and defer network ACLs to
   SPEC-2026-021.
1. **Backups:** keep `/srv/backups/<service>/` as the destination contract. Backup-tool,
   schedule, encryption, retention, and independent-destination selection is a configuration-phase
   gate before backup acceptance evidence, not a blocker for deploying the services.
1. **Two-phase delivery:** deploy all services securely first, then configure each manually and
   agree application configuration ownership from observed behaviour and supported file separation.
   Git always owns containers, ingress, secret delivery, mounts, and lifecycle. Do not add a
   seed-only mechanism or decide the full application settings split before deployment.
1. **Storage authority:** ADR 0014 is accepted and the local SPEC-2026-030 migrations are complete.
   Validate Frigate's local path adoption here; future NAS adoption belongs to SPEC-2026-031.
1. **Surveillance capacity:** confirm available space at `/srv/surveillance/` before enabling
   recording. This is a Frigate-stage operational check, not a blocker for Mosquitto, Home
   Assistant, Zigbee2MQTT, or ESPHome.
1. **Initial storage protection (2026-10-27):** retain Frigate-managed cleanup and add a small
   periodic stop/start guard on shared `/srv`. Accept temporary loss of Frigate functionality
   and manual recovery in preference to external file deletion or quota-induced write failures.
   Review actual usage after one week of recording; changing filesystem boundaries remains a
   separate storage decision under ADR 0014.

## References

- [Frigate recording and retention](https://docs.frigate.video/configuration/record/)
- [Home Assistant Reolink playback](https://www.home-assistant.io/integrations/reolink/#media-browser-for-playback-of-recordings)
- `docs/specs/proposed/0016-services-monitoring.md`
- `config/services/home-assistant/service.yaml`
- `config/services/mosquitto/service.yaml`
- `config/services/zigbee2mqtt/service.yaml`
- `config/services/esphome/service.yaml`
- `config/services/frigate/service.yaml`
- `config/services/go2rtc/service.yaml` (obsolete stub to remove)
- `config/network.yaml`
- `config/mapping.yaml`
- `config/services/authelia/service.yaml` (service-owned secret refresh pattern)
- `config/services/omada-controller/service.yaml` (service-owned environment refresh pattern)
- `docs/adr/0005-service-authoring-model.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/adr/0014-host-storage-and-nas-mount-boundaries.md`
- `docs/specs/accepted/0030-host-storage-layout.md`
- `docs/specs/proposed/0021-network-devices.md`
- `docs/specs/accepted/0011-core-services.md`
