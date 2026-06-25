"""Canonical kind taxonomy for the render/apply pipeline."""

from __future__ import annotations

KIND_FAMILIES: dict[str, frozenset[str]] = {
    "systemd": frozenset({"systemd.unit", "systemd.dropin", "resolved.config", "resolved.dropin"}),
    "user": frozenset({"host.sysusers", "host.sudoers", "host.authorized_keys"}),
    "coredns": frozenset({"coredns.config", "coredns.zone"}),
    "caddy": frozenset({"caddy.config"}),
    "vault": frozenset({"vault.config", "vault.template"}),
    "networkd": frozenset({"networkd.netdev", "networkd.network", "networkd.dropin"}),
    "quadlet": frozenset(
        {
            "quadlet.network",
            "quadlet.volume",
            "quadlet.image",
            "quadlet.build",
            "quadlet.pod",
            "quadlet.container",
        }
    ),
    "service": frozenset({"service.config", "service.env", "service.directory"}),
}

ALL_KINDS: frozenset[str] = frozenset().union(*KIND_FAMILIES.values())

# Documentation-only: valid apply_hints keys per kind family.
# Not enforced in hot path — used for documentation, testing, and auditing.
KNOWN_APPLY_HINTS: dict[str, list[str]] = {
    "systemd": ["restart_mode", "enable_mode", "activation_mode"],
    "user": ["owner_user", "owner_group", "mode", "ssh_dir_mode"],
    "coredns": [],
    "caddy": ["contributors", "restart_on_failure"],
    "vault": ["write_order", "restart_mode", "rootless", "podman_user"],
    "networkd": [],
    "quadlet": ["rootless", "podman_user", "shared"],
    "service": ["restart_unit", "rootless", "podman_user", "owner", "group", "mode"],
}
