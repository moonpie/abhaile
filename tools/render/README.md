# Render Tools

Configuration rendering and validation for Abhaile's host-level GitOps.

- `cli.py`: Main orchestrator that processes all hosts from `config/mapping.yaml` and generates output to `out/rendered/`
- `lib/`: Domain builders and validation modules (dns, network, quadlet, services, validators)

Usage:

```bash
python3 tools/render/cli.py           # Render all hosts
python3 tools/render/cli.py phobos    # Render specific host
python3 tools/render/cli.py --validate-only  # Validate without rendering
```

## Validation Architecture

Validation operates in two modes:

### Validate-Only Mode

```bash
python3 tools/render/cli.py --validate-only
```

Validates all hosts from `config/mapping.yaml` without generating output files. Useful for pre-flight checks before full render.

### Full Render with Validation

```bash
python3 tools/render/cli.py [hosts...]
```

Validates then renders. Validation errors prevent output generation.

## Error Handling

### Critical Errors (Exit Code 1)

Block rendering and require config fixes:

1. Service not found in mapping

   - Error: `ServiceNotFoundError: Service '<svc>' mapped to host '<host>' but service.yaml missing in config/services/<svc>/`
   - Fix: Create `config/services/<svc>/service.yaml`

1. Service network mode not in network.yaml

   - Error: `ServiceNotFound: Service '<svc>' (network=service-32) not found in network.yaml services section`
   - Fix: Add service to `config/network.yaml services`

1. Missing address or VLAN for service

   - Error: `ServiceConfigError: Service '<svc>' (network=<mode>) missing address or vlan in network.yaml`
   - Fix: Ensure `address` and `vlan` fields in `network.yaml`

1. VLAN not defined in network.yaml

   - Error: `VLANNotFound: VLAN '<vlan>' referenced by service '<svc>' not defined in network.yaml vlans`
   - Fix: Add VLAN to `config/network.yaml vlans` section

1. Host missing ipvlan interface for service

   - Error: `HostConfigError: No matching ipvlan network found for VLAN id <id> on host <host>`
   - Fix: Ensure host has ipvlan interface defined in `config/network.yaml hosts.<host>.interfaces`

1. Referenced config source file missing

   - Error: `ConfigFileNotFound: Config source file '<source>' referenced by service '<svc>' not found in config/services/<svc>/`
   - Fix: Create the referenced config file or update `service.yaml` reference

1. Vault Agent template file missing

   - Error: `TemplateNotFound: Vault Agent template '<source>' referenced by service '<svc>' not found`
   - Fix: Create the template file in `config/services/<svc>/templates/`

1. Placeholder resolution fails

   - Error: `PlaceholderResolutionError: Failed to resolve placeholder '%%<placeholder>%%' in service '<svc>' config: <details>`
   - Fix: Ensure `%%path.to.variable%%` references a valid key in config YAML

1. Duplicate /32 addresses on same interface

   - Error: `DuplicateAddressError: Services '<svc1>' and '<svc2>' both use address <ip>/32 on host <host> interface <iface>`
   - Fix: Assign unique /32 addresses in `config/network.yaml`

### Warnings (Exit Code 0)

Render succeeds but logs warnings:

1. Host has no services mapped

   - Warning: `Host '<host>' has no services mapped in mapping.yaml; rendering with empty service list`
   - Rationale: Intentional during bootstrap

1. Service type not recognized

   - Warning: `Service '<svc>' has unrecognized type '<type>'; skipping quadlet generation`
   - Rationale: May be intentional for future service types

## Render Output Structure

All output goes to `out/rendered/` (dev) or `/var/lib/abhaile/rendered/` (production):

```text
out/rendered/
├── phobos/
│   ├── systemd-networkd/
│   │   ├── 00-enp0s31f6.network
│   │   ├── 20-ipvlan-l2.20.netdev
│   │   ├── 20-ipvlan-l2.20.network
│   │   └── 30-caddy-internal.conf
│   ├── services/
│   │   ├── caddy-internal/
│   │   │   ├── Caddyfile
│   │   │   └── caddy-internal.service
│   │   ├── vault-agent/
│   │   │   ├── vault-agent.hcl
│   │   │   └── vault-agent.service
│   │   └── _shared/
│   │       ├── home/.config/containers/systemd/
│   │       └── etc/containers/systemd/
│   └── resolved/
│       └── resolved.conf
├── deimos/
│   ├── systemd-networkd/
│   └── services/
└── state/
    ├── networkd.state
    ├── services.state
    ├── systemd.state
    ├── resolved.state
    ├── software.state
    ├── users.state
    └── desec_plan.json
```

## Key Validation Modules

**Validators (in `lib/`)**:

- `mapping_validator.py`: Validates service-to-host mappings exist
- `network_validator.py`: Validates VLAN references, interface assignments, /32 uniqueness
- `service_validator.py`: Validates service metadata, network modes, required fields
- `placeholder_resolver.py`: Resolves `%%...%%` template variables with fail-fast on errors

**Builders (in `lib/`)**:

- `dns_builder.py`: Generates CoreDNS zones, manages serials
- `network_builder.py`: Generates systemd-networkd `.network` and `.netdev` files
- `quadlet_builder.py`: Generates Podman quadlet units
- `service_builder.py`: Renders service configs from templates

## Validation Integration

Full render process:

1. Load all config YAML files
1. Run semantic validators on mapping, network, services
1. Resolve placeholders in all templates
1. Generate output for all hosts
1. Write state files for drift tracking
1. Write deSEC plan (if external DNS configured)

Each stage can fail on critical errors. Warnings are logged but don't block rendering.

See [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md) for rendering architecture and builder patterns.
