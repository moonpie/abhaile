"""Artifact kind and owner inference helpers for render metadata registration."""

from __future__ import annotations

from pathlib import Path

_SYSTEMD_UNIT_PREFIX = "/etc/systemd/system/"
_RESOLVED_CONF = "/etc/systemd/resolved.conf"
_RESOLVED_DROPIN_PREFIX = "/etc/systemd/resolved.conf.d/"
_NETWORKD_PREFIX = "/etc/systemd/network/"
_COREDNS_COREFILE = "/etc/coredns/Corefile"
_CONTAINERS_SYSTEMD_PREFIX = "/etc/containers/systemd/"


def classify_config_artifact(
    destination: str,
    *,
    default_owner_ref: str,
    is_directory: bool,
) -> tuple[str, str]:
    """Classify artifact `kind` and infer `owner_ref` from destination path."""
    if destination.startswith(_NETWORKD_PREFIX):
        tail = destination[len(_NETWORKD_PREFIX) :]
        if ".network.d/" in tail:
            iface = _normalize_networkd_iface(tail.split(".network.d/", 1)[0])
            return ("networkd.dropin", f"iface:{iface}")

        name = Path(tail).name
        if name.endswith(".network"):
            iface = _normalize_networkd_iface(name[: -len(".network")])
            return ("networkd.network", f"iface:{iface}")
        if name.endswith(".netdev"):
            iface = _normalize_networkd_iface(name[: -len(".netdev")])
            return ("networkd.netdev", f"iface:{iface}")

    if destination.startswith(_SYSTEMD_UNIT_PREFIX):
        return classify_systemd_artifact(destination)

    if destination == _RESOLVED_CONF:
        return ("resolved.config", "service:systemd-resolved")

    if destination.startswith(_RESOLVED_DROPIN_PREFIX):
        return ("resolved.dropin", "service:systemd-resolved")

    if destination == _COREDNS_COREFILE:
        return ("coredns.config", "dns:coredns")

    quadlet_kind_owner = _classify_quadlet_destination(destination)
    if quadlet_kind_owner is not None:
        return quadlet_kind_owner

    if is_directory:
        return ("service.directory", default_owner_ref)

    filename = Path(destination).name
    if filename == "env" or filename.endswith(".env"):
        return ("service.env", default_owner_ref)

    return ("service.config", default_owner_ref)


def classify_service_artifact(
    destination: str,
    *,
    default_owner_ref: str,
    is_directory: bool,
) -> tuple[str, str]:
    """Classify service composition.config artifacts.

    For services, authored section membership is the semantic source of truth for
    systemd artifacts, so this classifier intentionally does not infer the
    systemd family from destination path. It preserves existing special cases for
    CoreDNS and static quadlet artifacts that still live under composition.config.
    """
    if destination == _COREDNS_COREFILE:
        return ("coredns.config", "dns:coredns")

    quadlet_kind_owner = _classify_quadlet_destination(destination)
    if quadlet_kind_owner is not None:
        return quadlet_kind_owner

    if is_directory:
        return ("service.directory", default_owner_ref)

    filename = Path(destination).name
    if filename == "env" or filename.endswith(".env"):
        return ("service.env", default_owner_ref)

    return ("service.config", default_owner_ref)


def classify_systemd_artifact(destination: str) -> tuple[str, str]:
    """Classify composition.systemd artifacts by destination path."""
    tail = destination
    if destination.startswith(_SYSTEMD_UNIT_PREFIX):
        tail = destination[len(_SYSTEMD_UNIT_PREFIX) :]

    if ".d/" in tail:
        unit_dir = tail.split("/", 1)[0]
        unit_name = unit_dir[:-2] if unit_dir.endswith(".d") else unit_dir
        return ("systemd.dropin", f"unit:{unit_name}")

    unit_name = Path(tail).name
    return ("systemd.unit", f"unit:{unit_name}")


def _normalize_networkd_iface(raw: str) -> str:
    """Normalize networkd base name into interface identity."""
    parts = raw.split("-", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return raw


def _classify_quadlet_destination(destination: str) -> tuple[str, str] | None:
    """Classify quadlet destinations written under /etc/containers/systemd/."""
    if not destination.startswith(_CONTAINERS_SYSTEMD_PREFIX):
        return None

    filename = Path(destination).name
    stem = Path(filename).stem
    suffix = Path(filename).suffix

    if suffix == ".container":
        return ("quadlet.container", f"unit:{stem}.service")
    if suffix == ".pod":
        return ("quadlet.pod", f"unit:{stem}.service")
    if suffix == ".image":
        return ("quadlet.image", f"unit:{stem}-image.service")
    if suffix == ".build":
        return ("quadlet.build", f"unit:{stem}-build.service")
    if suffix == ".volume":
        return ("quadlet.volume", f"unit:{stem}-volume.service")
    if suffix == ".network":
        return ("quadlet.network", f"unit:{stem}-network.service")

    return None
