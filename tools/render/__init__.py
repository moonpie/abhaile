"""tools.render: Render systemd-networkd configs, Podman quadlets, and service templates.

Modules:
- dns: DNS context building, record generation, zone management, and deSEC API integration.
- host: Host-specific configuration (user, software, resolved).
- network: Network configuration builders, validation, file mapping.
- quadlet: Podman quadlet template rendering (container network definitions).
- services: Service config and metadata handling, Caddy/Vault-Agent templates.

All shared utilities (load_yaml, ValidationError, RenderError, strip_cidr) are imported from
tools.common.core and should be used directly from there:
  from tools.common.core import load_yaml, ValidationError, RenderError, strip_cidr
"""
