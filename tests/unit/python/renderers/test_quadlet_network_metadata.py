"""Verify deterministic native-network identities for enrollment collision checks."""

from pathlib import Path

import pytest

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.quadlets.network import _render_network_quadlets


@pytest.mark.parametrize(
    "ip_range,first,last",
    [
        ("192.0.2.128/25", "192.0.2.129", "192.0.2.254"),
        ("192.0.2.200-192.0.2.254", "192.0.2.200", "192.0.2.254"),
    ],
)
def test_network_collision_metadata_preserves_configured_range(
    tmp_path: Path, ip_range: str, first: str, last: str
) -> None:
    """Describe both supported IP-range forms without consulting live network state."""
    config = tmp_path / "config"
    template = config / "_templates/services/quadlets/network.network.j2"
    template.parent.mkdir(parents=True)
    template.write_text("[Network]\nDriver=ipvlan\n")
    rendered = tmp_path / "rendered"
    collector = ArtifactCollector()
    _render_network_quadlets(
        "example",
        {
            "vlans": {
                "services": {
                    "cidr": "192.0.2.0/24",
                    "gateway": "192.0.2.1",
                    "ipvlanl2_range": ip_range,
                }
            },
            "hosts": {"example": {"interfaces": {"example.20": {"vlan": "services"}}}},
        },
        ["services"],
        rendered / "services/podman-networks",
        config,
        collector=collector,
        rendered_root=rendered,
    )
    [artifact] = collector.get_all_artifacts()
    assert artifact.apply_hints is not None
    resource = artifact.apply_hints["podman_resource"]
    assert resource["name"] == "systemd-services"
    assert resource["network_interface"] == "example.20"
    assert resource["subnets"] == [
        {
            "subnet": "192.0.2.0/24",
            "gateway": "192.0.2.1",
            "lease_range": {"start_ip": first, "end_ip": last},
        }
    ]
