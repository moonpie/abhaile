# Spec: Media Services

## Metadata

```yaml
id: SPEC-2026-017
title: Media Services
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [deimos]
  services: [immich, jellyfin, tdarr, radarr, sonarr, lidarr, readarr, bazarr, prowlarr, jellyseerr, flaresolverr]
```

## Context

Phase 3 media services extend the homelab with photo management, media streaming,
automated library acquisition, transcoding, and request management. All services deploy
to deimos, which currently runs only chrony-b, coredns-clean, and vault-agent.

The service definitions in `config/services/` exist as stubs with basic structure
(`name`, `podman.user`, `podman.network`, empty `composition.container`). This spec
defines the full service.yaml content, inter-service relationships, shared storage
layout, hardware acceleration strategy, and secrets model for the group.

These services form four functional subgroups:

- **Photo management:** Immich (server + machine-learning + database + Redis)
- **Media server:** Jellyfin (streaming with hardware transcode)
- **Transcoding:** Tdarr (library optimization with worker nodes)
- **Acquisition stack:** Radarr, Sonarr, Lidarr, Readarr (library managers), Bazarr
  (subtitles), Prowlarr (indexer proxy), Jellyseerr (request management),
  Flaresolverr (Cloudflare bypass for indexers)

All services bind to deterministic /32 ipvlan-l2 addresses on VLAN 20 (services) as
defined in `config/network.yaml`.

## Requirements

- [ ] Define complete service.yaml for each service with container images, volumes,
  environment, ports, and composition metadata
- [ ] Establish shared storage volume layout for media libraries accessible across the
  acquisition stack, transcoding, and playback services
- [ ] Configure hardware acceleration (VA-API/QSV) passthrough for Jellyfin and Tdarr
  on deimos (i7-7700T integrated graphics)
- [ ] Define inter-service API key delivery model for \*arr stack communication
- [ ] Add all 11 services to deimos in `config/mapping.yaml`
- [ ] Define caddy-internal ingress blocks for web-accessible services
- [ ] Define systemd dependency ordering relative to existing deimos services
- [ ] Register DNS records (already present in `config/network.yaml`)

## Constraints

- All services run as rootful containers on ipvlan-l2 (consistent with existing stubs).
- No runtime secrets in rendered output; API keys and credentials delivered via
  vault-agent or generated at first-run by the application.
- Render remains deterministic — no runtime state dependencies.
- Shared storage paths must be consistent across all services that access the same
  media files to avoid hardlink breakage.
- Hardware acceleration requires `/dev/dri` device passthrough and appropriate
  container privileges; no kernel module changes needed (i915 loads by default on
  Debian 13 with i7-7700T).
- Services depend on `abhaile-secrets-ready` only if they consume vault-agent
  templates; services that self-manage credentials at first-run do not.

## Design

### Network Addressing

All services occupy the upper range of the services VLAN ipvlan-l2 block:

| Service | Address | Port(s) |
| --- | --- | --- |
| immich | 172.20.20.240/32 | 3001 (web) |
| jellyfin | 172.20.20.241/32 | 8096 (web) |
| tdarr | 172.20.20.242/32 | 8265 (web), 8266 (node) |
| radarr | 172.20.20.243/32 | 7878 |
| sonarr | 172.20.20.244/32 | 8989 |
| lidarr | 172.20.20.245/32 | 8686 |
| readarr | 172.20.20.246/32 | 8787 |
| bazarr | 172.20.20.247/32 | 6767 |
| prowlarr | 172.20.20.248/32 | 9696 |
| jellyseerr | 172.20.20.249/32 | 5055 |
| flaresolverr | 172.20.20.250/32 | 8191 |

### Service Subgroups

#### Photo Management — Immich

Immich runs as a pod with multiple containers:

- **immich-server** — main application (API + web UI)
- **immich-machine-learning** — ML inference for face/object recognition
- **immich-postgres** — PostgreSQL with pgvecto.rs extension
- **immich-redis** — session/job queue cache

Pod composition follows the same pattern as authelia (shared network namespace).
The ML container benefits from the host CPU but does not require GPU acceleration
for a personal photo library at this scale.

Volumes:

- `upload` — user photo/video uploads (`/srv/immich/upload`)
- `model-cache` — ML model cache (`/srv/immich/model-cache`)
- `postgres-data` — database storage (`/srv/immich/postgres`)

#### Media Server — Jellyfin

Single container with hardware-accelerated transcoding via Intel QSV (i7-7700T).

Device passthrough: `/dev/dri/renderD128` for VA-API/QSV access.

Volumes:

- `config` — Jellyfin configuration and metadata (`/srv/jellyfin/config`)
- `cache` — transcoding cache (`/srv/jellyfin/cache`)
- Media library mount (read-only bind from shared storage)

#### Transcoding — Tdarr

Tdarr server + integrated node for library transcoding/optimization.

Device passthrough: `/dev/dri/renderD128` for hardware-accelerated encoding.

Volumes:

- `config` — Tdarr server configuration (`/srv/tdarr/config`)
- `temp` — transcoding workspace (`/srv/tdarr/temp`)
- Media library mount (read-write bind from shared storage)

#### Acquisition Stack — \*arr Services

All \*arr services follow the same container pattern: single container, named config
volume, shared media library access.

**Radarr** — movie library manager.
**Sonarr** — TV series library manager.
**Lidarr** — music library manager.
**Readarr** — ebook/audiobook library manager.
**Bazarr** — subtitle management (companion to Radarr/Sonarr).
**Prowlarr** — indexer proxy (centralizes tracker config for all \*arr services).

Each service volume:

- `config` — application config/database (`/srv/<service>/config`)
- Media library mount (read-write bind from shared storage)

**Jellyseerr** — user request portal integrated with Jellyfin and Radarr/Sonarr.

- `config` — application data (`/srv/jellyseerr/config`)

**Flaresolverr** — headless browser for Cloudflare-protected indexer sites.

- Stateless; no persistent volumes required.
- Used by Prowlarr as a proxy for specific indexers.

### Shared Storage Layout

A unified media directory structure prevents hardlink breakage across services that
handle the same files (download clients → \*arr services → Jellyfin/Tdarr):

```text
/srv/media/
├── movies/          (Radarr manages, Jellyfin/Tdarr reads)
├── tv/              (Sonarr manages, Jellyfin/Tdarr reads)
├── music/           (Lidarr manages, Jellyfin reads)
├── books/           (Readarr manages)
├── downloads/       (download client writes, *arr services import from)
│   ├── complete/
│   └── incomplete/
└── transcode/       (Tdarr workspace, optional separate mount)
```

Mount semantics per service:

| Service | Mount path in container | Host path | Access |
| --- | --- | --- | --- |
| radarr | /data | /srv/media | rw |
| sonarr | /data | /srv/media | rw |
| lidarr | /data | /srv/media | rw |
| readarr | /data | /srv/media | rw |
| bazarr | /data | /srv/media | rw |
| jellyfin | /data | /srv/media | ro |
| tdarr | /data | /srv/media | rw |
| prowlarr | — | — | no media access |
| jellyseerr | — | — | no media access |
| flaresolverr | — | — | no media access |
| immich | /upload | /srv/immich/upload | rw (separate library) |

Immich operates its own photo library independently from the media stack.

### Hardware Acceleration

deimos has an i7-7700T with Intel HD Graphics 630 (Kaby Lake). This provides:

- VA-API for decode/encode (H.264, H.265/HEVC, VP8, VP9)
- Intel Quick Sync Video (QSV) via `intel-media-driver`

Container requirements:

- Device passthrough: `--device /dev/dri/renderD128:/dev/dri/renderD128`
- Group membership: container process needs `render` group access (GID varies;
  use `--group-add` with the host render GID or `--device-cgroup-rule`)

Affected services: Jellyfin, Tdarr.

Host prerequisites (defined in deimos `host.yaml` software):

- `intel-media-driver` (or `intel-media-va-driver-non-free`) package
- `vainfo` for validation (optional, diagnostic only)

### Secrets and API Key Model

Inter-service communication in the \*arr stack uses API keys:

- Prowlarr connects to Radarr, Sonarr, Lidarr, Readarr (push sync)
- Jellyseerr connects to Jellyfin, Radarr, Sonarr (request fulfillment)
- Bazarr connects to Radarr, Sonarr (subtitle association)
- Tdarr does not use \*arr API keys (filesystem-based workflow)

**Immich** requires:

- PostgreSQL password
- JWT secret for session management

Two delivery models are viable:

1. **Vault-agent delivery:** vault-agent renders API keys from Vault KV store to
   env files or config snippets consumed by each service. Requires pre-seeding
   Vault with each application's generated API key after first run.

1. **Application-managed:** each \*arr service generates its own API key on first
   start (stored in its SQLite database). Operators copy keys between services
   via the web UI during initial setup. No vault-agent integration needed.

The chosen model affects whether these services declare `composition.vault_agent.templates`.

### Ingress (caddy-internal)

All web-accessible services contribute internal ingress blocks to caddy-internal:

| FQDN | Upstream |
| --- | --- |
| immich.abhaile.home.arpa | 172.20.20.240:3001 |
| jellyfin.abhaile.home.arpa | 172.20.20.241:8096 |
| tdarr.abhaile.home.arpa | 172.20.20.242:8265 |
| radarr.abhaile.home.arpa | 172.20.20.243:7878 |
| sonarr.abhaile.home.arpa | 172.20.20.244:8989 |
| lidarr.abhaile.home.arpa | 172.20.20.245:8686 |
| readarr.abhaile.home.arpa | 172.20.20.246:8787 |
| bazarr.abhaile.home.arpa | 172.20.20.247:6767 |
| prowlarr.abhaile.home.arpa | 172.20.20.248:9696 |
| jellyseerr.abhaile.home.arpa | 172.20.20.249:5055 |

Flaresolverr has no web UI for end users; accessed only by Prowlarr via direct IP.

All ingress blocks use Authelia forward-auth protection except Jellyfin (which has
its own authentication) and Jellyseerr (which handles its own user management).

### Dependency Ordering

On deimos, the media services depend on the existing base chain:

```text
systemd-networkd
  → chrony-b
    → coredns-clean
      → vault-agent → abhaile-secrets-ready (if vault-agent templates used)
        → media services (After=abhaile-secrets-ready)
```

If the application-managed API key model is chosen:

```text
systemd-networkd
  → chrony-b
    → coredns-clean
      → media services (After=coredns-clean only, no secrets dependency)
```

Immich (pod) has internal ordering: postgres and redis start before the server.

Inter-service runtime dependencies (not systemd-enforced, handled by application
retry logic):

- Prowlarr → \*arr services (API sync, retries on connection failure)
- Jellyseerr → Jellyfin, Radarr, Sonarr (request routing)
- Bazarr → Radarr, Sonarr (subtitle association)
- Flaresolverr ← Prowlarr (proxy requests)

### DNS Records

Already defined in `config/network.yaml`. Each service has:

- A record in `svc.abhaile.home.arpa.` pointing to its /32 address (with PTR)
- CNAME in `abhaile.home.arpa.` pointing to `caddy.abhaile.home.arpa.` (for
  ingress-fronted services — to be added)

## Decision Notes

_To be recorded during implementation._

## Acceptance Criteria

- [ ] Detail `service.yaml` definitions for all services in this group
- [ ] Shared media storage volume layout is defined and consistent across all consuming services.
- [ ] Hardware acceleration device passthrough is configured for Jellyfin and Tdarr containers.
- [ ] deimos host.yaml includes Intel media driver in software requirements.
- [ ] API key delivery model is chosen and documented (vault-agent or application-managed).
- [ ] All 11 services added to deimos in `config/mapping.yaml`.
- [ ] caddy-internal ingress blocks are defined for all web-accessible services.
- [ ] Authelia forward-auth applied to appropriate services (exclude Jellyfin, Jellyseerr).
- [ ] Immich pod composition renders correctly (server + ML + postgres + redis).
- [ ] DNS CNAME records for `*.abhaile.home.arpa` added to `config/network.yaml` for ingress-fronted services.
- [ ] Systemd dependency ordering documented and rendered in quadlet output.
- [ ] Unit tests pass for new service rendering.
- [ ] Integration test renders deimos with all media services without regression.
- [ ] No secrets appear in rendered output.

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- Download client (qBittorrent + Gluetun VPN) — separate spec with network isolation concerns.
- Jellyfin DMZ/external access via caddy-dmz.
- Immich external access via caddy-dmz.
- Monitoring and alerting for media services (Prometheus exporters, Grafana dashboards).
- Backup strategy for media databases and configuration.
- Media storage provisioning (filesystem, ZFS, NFS — host-level concern outside service config).
- Automated initial setup/seeding of \*arr services (first-run wizard is manual).

## Open Questions

1. **Storage layout:** Should `/srv/media` be a single filesystem mount, or should
   subdirectories (movies, tv, music, books, downloads) be separate mounts? A single
   mount preserves hardlinks across the entire tree. Separate mounts provide independent
   capacity management but break hardlinks between download and library directories.

1. **Hardware acceleration configuration:** Should device passthrough use
   `--device /dev/dri:/dev/dri` (expose all DRI devices) or target only
   `/dev/dri/renderD128` specifically? The broad approach is simpler but exposes the
   display device unnecessarily. Does deimos need `render` group created in host user
   management, or is the default Debian GID sufficient?

1. **API key secrets model:** Should \*arr inter-service API keys be delivered via
   vault-agent (pre-seeded in Vault KV after initial setup) or remain
   application-managed (operators configure via web UI, keys live in each app's
   database)? Vault-agent delivery provides auditability and rotation capability but
   adds complexity for values that rarely change. Application-managed is simpler for
   initial deployment but leaves key material outside the secrets management boundary.

1. **Immich database credentials:** Should the PostgreSQL password for Immich be
   vault-agent delivered (consistent with the secrets model) or set via environment
   variable at first deploy with a static value? Vault-agent delivery requires a
   `.ctmpl` template and restart-on-change path unit.

1. **Tdarr node topology:** Should Tdarr run a single integrated server+node, or
   should a separate Tdarr node container run on phobos as well (leveraging both
   hosts for transcoding)? Single-host is simpler; cross-host requires Tdarr node
   containers on both machines with shared storage access.

## References

- `config/network.yaml` — service addressing and DNS records
- `config/mapping.yaml` — current service-to-host assignments
- `config/services/immich/service.yaml` (stub)
- `config/services/jellyfin/service.yaml` (stub)
- `config/services/tdarr/service.yaml` (stub)
- `config/services/radarr/service.yaml` (stub)
- `config/services/sonarr/service.yaml` (stub)
- `config/services/lidarr/service.yaml` (stub)
- `config/services/readarr/service.yaml` (stub)
- `config/services/bazarr/service.yaml` (stub)
- `config/services/prowlarr/service.yaml` (stub)
- `config/services/jellyseerr/service.yaml` (stub)
- `config/services/flaresolverr/service.yaml` (stub)
- `docs/adr/0005-service-authoring-model.md`
- `docs/specs/proposed/0018-services-networking.md` (SPEC-2026-018 — qBittorrent + Gluetun, shared download directory)
- `docs/specs/proposed/0016-services-monitoring.md` (SPEC-2026-016 — Prometheus scraping of media services)
- `docs/specs/accepted/0011-core-services.md` (SPEC-2026-011 — Phase 1 service group reference)
- `docs/specs/accepted/0005-service-composition.md` (SPEC-2026-005 — composition model)
