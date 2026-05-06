"""Unit tests for metadata classification helpers."""

from abhaile.renderers.metadata import classify_config_artifact


def test_classify_networkd_dropin() -> None:
    """Networkd drop-in destinations should map to iface-scoped dropin kind."""
    kind, owner_ref = classify_config_artifact(
        "/etc/systemd/network/20-br0.network.d/010-test.conf",
        default_owner_ref="host:phobos",
        is_directory=False,
    )

    assert kind == "networkd.dropin"
    assert owner_ref == "iface:br0"


def test_classify_networkd_network() -> None:
    """Networkd .network files should map to iface-scoped network kind."""
    kind, owner_ref = classify_config_artifact(
        "/etc/systemd/network/20-eth0.network",
        default_owner_ref="host:phobos",
        is_directory=False,
    )

    assert kind == "networkd.network"
    assert owner_ref == "iface:eth0"


def test_classify_networkd_netdev() -> None:
    """Networkd .netdev files should map to iface-scoped netdev kind."""
    kind, owner_ref = classify_config_artifact(
        "/etc/systemd/network/30-vlan10.netdev",
        default_owner_ref="host:phobos",
        is_directory=False,
    )

    assert kind == "networkd.netdev"
    assert owner_ref == "iface:vlan10"


def test_classify_systemd_unit() -> None:
    """Systemd unit file destinations should map to unit owner."""
    kind, owner_ref = classify_config_artifact(
        "/etc/systemd/system/caddy.service",
        default_owner_ref="host:phobos",
        is_directory=False,
    )

    assert kind == "systemd.unit"
    assert owner_ref == "unit:caddy.service"


def test_classify_systemd_dropin() -> None:
    """Systemd unit drop-ins should map to dropin kind and base unit owner."""
    kind, owner_ref = classify_config_artifact(
        "/etc/systemd/system/caddy.service.d/10-override.conf",
        default_owner_ref="host:phobos",
        is_directory=False,
    )

    assert kind == "systemd.dropin"
    assert owner_ref == "unit:caddy.service"


def test_classify_resolved_config() -> None:
    """resolved.conf should map to resolved.config with stable owner."""
    kind, owner_ref = classify_config_artifact(
        "/etc/systemd/resolved.conf",
        default_owner_ref="host:phobos",
        is_directory=False,
    )

    assert kind == "resolved.config"
    assert owner_ref == "service:systemd-resolved"


def test_classify_resolved_dropin() -> None:
    """resolved drop-ins should map to resolved.dropin with stable owner."""
    kind, owner_ref = classify_config_artifact(
        "/etc/systemd/resolved.conf.d/10-dns.conf",
        default_owner_ref="host:phobos",
        is_directory=False,
    )

    assert kind == "resolved.dropin"
    assert owner_ref == "service:systemd-resolved"


def test_classify_service_directory() -> None:
    """Non-special directories should map to service.directory with default owner."""
    kind, owner_ref = classify_config_artifact(
        "/srv/my-service/config",
        default_owner_ref="service:my-service",
        is_directory=True,
    )

    assert kind == "service.directory"
    assert owner_ref == "service:my-service"


def test_classify_service_env_file() -> None:
    """env and *.env files should map to service.env."""
    kind1, owner_ref1 = classify_config_artifact(
        "/srv/my-service/env",
        default_owner_ref="service:my-service",
        is_directory=False,
    )
    kind2, owner_ref2 = classify_config_artifact(
        "/srv/my-service/app.env",
        default_owner_ref="service:my-service",
        is_directory=False,
    )

    assert kind1 == "service.env"
    assert owner_ref1 == "service:my-service"
    assert kind2 == "service.env"
    assert owner_ref2 == "service:my-service"


def test_classify_service_config_fallback() -> None:
    """Unknown file destinations should fall back to service.config."""
    kind, owner_ref = classify_config_artifact(
        "/srv/my-service/config.yaml",
        default_owner_ref="service:my-service",
        is_directory=False,
    )

    assert kind == "service.config"
    assert owner_ref == "service:my-service"


def test_classify_coredns_corefile() -> None:
    """CoreDNS Corefile should map to coredns.config with server owner."""
    kind, owner_ref = classify_config_artifact(
        "/etc/coredns/Corefile",
        default_owner_ref="service:coredns",
        is_directory=False,
    )

    assert kind == "coredns.config"
    assert owner_ref == "dns:coredns"


def test_classify_quadlet_build_destination() -> None:
    """Config entry for quadlet build should map to quadlet.build kind."""
    kind, owner_ref = classify_config_artifact(
        "/etc/containers/systemd/coredns-omada.build",
        default_owner_ref="service:coredns",
        is_directory=False,
    )

    assert kind == "quadlet.build"
    assert owner_ref == "unit:coredns-omada-build.service"


def test_classify_quadlet_container_destination() -> None:
    """Config entry for quadlet container should map to quadlet.container kind."""
    kind, owner_ref = classify_config_artifact(
        "/etc/containers/systemd/caddy-internal.container",
        default_owner_ref="service:caddy-internal",
        is_directory=False,
    )

    assert kind == "quadlet.container"
    assert owner_ref == "unit:caddy-internal.service"
