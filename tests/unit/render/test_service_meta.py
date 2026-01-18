"""Tests for service metadata loading with include support."""

from __future__ import annotations


import pytest

from tools.common.core import RenderError
from tools.render.services.service_meta import load_service_meta_with_includes


def test_load_service_meta_basic(tmp_path):
    """Test basic service metadata loading without includes."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create a simple service
    service_dir = services_dir / "test-service"
    service_dir.mkdir()
    service_file = service_dir / "service.yaml"
    service_file.write_text(
        """
name: test-service
type: container
network: host
ports: [8080]
"""
    )

    cache = {}
    meta = load_service_meta_with_includes("test-service", services_dir, cache)

    assert meta["name"] == "test-service"
    assert meta["type"] == "container"
    assert meta["network"] == "host"
    assert meta["ports"] == [8080]
    assert "test-service" in cache


def test_load_service_meta_single_include(tmp_path):
    """Test service metadata with a single include."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create base service
    base_dir = services_dir / "base-service"
    base_dir.mkdir()
    base_file = base_dir / "service.yaml"
    base_file.write_text(
        """
name: base-service
config:
  - source: base/config.yaml
    destination: /etc/base/config.yaml
"""
    )

    # Create service that includes base
    child_dir = services_dir / "child-service"
    child_dir.mkdir()
    child_file = child_dir / "service.yaml"
    child_file.write_text(
        """
name: child-service
include:
  - base-service
config:
  - source: child/config.yaml
    destination: /etc/child/config.yaml
"""
    )

    cache = {}
    meta = load_service_meta_with_includes("child-service", services_dir, cache)

    # Should have configs from both base and child
    assert len(meta["config"]) == 2
    # Included config comes first, then child's config
    assert meta["config"][0]["source"] == "base/config.yaml"
    assert meta["config"][1]["source"] == "child/config.yaml"


def test_load_service_meta_nested_includes(tmp_path):
    """Test service metadata with nested includes (A includes B includes C)."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create service C (base)
    c_dir = services_dir / "service-c"
    c_dir.mkdir()
    (c_dir / "service.yaml").write_text(
        """
name: service-c
config:
  - source: c/config.yaml
    destination: /etc/c/config.yaml
"""
    )

    # Create service B (includes C)
    b_dir = services_dir / "service-b"
    b_dir.mkdir()
    (b_dir / "service.yaml").write_text(
        """
name: service-b
include:
  - service-c
config:
  - source: b/config.yaml
    destination: /etc/b/config.yaml
"""
    )

    # Create service A (includes B, which includes C)
    a_dir = services_dir / "service-a"
    a_dir.mkdir()
    (a_dir / "service.yaml").write_text(
        """
name: service-a
include:
  - service-b
config:
  - source: a/config.yaml
    destination: /etc/a/config.yaml
"""
    )

    cache = {}
    meta = load_service_meta_with_includes("service-a", services_dir, cache)

    # Should have configs from C, B, and A (in that order)
    assert len(meta["config"]) == 3
    assert meta["config"][0]["source"] == "c/config.yaml"
    assert meta["config"][1]["source"] == "b/config.yaml"
    assert meta["config"][2]["source"] == "a/config.yaml"


def test_load_service_meta_circular_include_direct(tmp_path):
    """Test that direct circular includes are detected (A includes B, B includes A)."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create service A that includes B
    a_dir = services_dir / "service-a"
    a_dir.mkdir()
    (a_dir / "service.yaml").write_text(
        """
name: service-a
include:
  - service-b
"""
    )

    # Create service B that includes A (circular!)
    b_dir = services_dir / "service-b"
    b_dir.mkdir()
    (b_dir / "service.yaml").write_text(
        """
name: service-b
include:
  - service-a
"""
    )

    cache = {}
    with pytest.raises(RenderError, match="circular include detected"):
        load_service_meta_with_includes("service-a", services_dir, cache)


def test_load_service_meta_circular_include_indirect(tmp_path):
    """Test that indirect circular includes are detected (A -> B -> C -> A)."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create service A that includes B
    a_dir = services_dir / "service-a"
    a_dir.mkdir()
    (a_dir / "service.yaml").write_text(
        """
name: service-a
include:
  - service-b
"""
    )

    # Create service B that includes C
    b_dir = services_dir / "service-b"
    b_dir.mkdir()
    (b_dir / "service.yaml").write_text(
        """
name: service-b
include:
  - service-c
"""
    )

    # Create service C that includes A (circular!)
    c_dir = services_dir / "service-c"
    c_dir.mkdir()
    (c_dir / "service.yaml").write_text(
        """
name: service-c
include:
  - service-a
"""
    )

    cache = {}
    with pytest.raises(
        RenderError,
        match="circular include detected.*service-a -> service-b -> service-c -> service-a",
    ):
        load_service_meta_with_includes("service-a", services_dir, cache)


def test_load_service_meta_self_include(tmp_path):
    """Test that self-includes are detected (A includes A)."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create service that includes itself
    service_dir = services_dir / "self-service"
    service_dir.mkdir()
    (service_dir / "service.yaml").write_text(
        """
name: self-service
include:
  - self-service
"""
    )

    cache = {}
    with pytest.raises(
        RenderError, match="circular include detected.*self-service -> self-service"
    ):
        load_service_meta_with_includes("self-service", services_dir, cache)


def test_load_service_meta_ingress_merging(tmp_path):
    """Test that ingress blocks are properly merged from includes."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create base with internal ingress
    base_dir = services_dir / "base-auth"
    base_dir.mkdir()
    (base_dir / "service.yaml").write_text(
        """
name: base-auth
ingress:
  internal:
    - block: auth/internal.txt
"""
    )

    # Create service with DMZ ingress and includes base
    service_dir = services_dir / "app-service"
    service_dir.mkdir()
    (service_dir / "service.yaml").write_text(
        """
name: app-service
include:
  - base-auth
ingress:
  dmz:
    - block: app/dmz.txt
"""
    )

    cache = {}
    meta = load_service_meta_with_includes("app-service", services_dir, cache)

    # Should have both internal and dmz ingress
    assert "ingress" in meta
    assert "internal" in meta["ingress"]
    assert "dmz" in meta["ingress"]
    assert len(meta["ingress"]["internal"]) == 1
    assert len(meta["ingress"]["dmz"]) == 1


def test_load_service_meta_vault_agent_templates_merging(tmp_path):
    """Test that vault_agent templates are properly merged from includes."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create base with vault template
    base_dir = services_dir / "base-vault"
    base_dir.mkdir()
    (base_dir / "service.yaml").write_text(
        """
name: base-vault
vault_agent:
  templates:
    - source: base/secrets.ctmpl
      out: secrets.conf
      perms: "0640"
"""
    )

    # Create service with additional vault template
    service_dir = services_dir / "app-vault"
    service_dir.mkdir()
    (service_dir / "service.yaml").write_text(
        """
name: app-vault
include:
  - base-vault
vault_agent:
  templates:
    - source: app/config.ctmpl
      out: config.conf
      perms: "0600"
"""
    )

    cache = {}
    meta = load_service_meta_with_includes("app-vault", services_dir, cache)

    # Should have templates from both
    assert "vault_agent" in meta
    assert "templates" in meta["vault_agent"]
    assert len(meta["vault_agent"]["templates"]) == 2
    # Included template comes first
    assert meta["vault_agent"]["templates"][0]["source"] == "base/secrets.ctmpl"
    assert meta["vault_agent"]["templates"][1]["source"] == "app/config.ctmpl"


def test_load_service_meta_missing_service_error(tmp_path):
    """Test that loading a non-existent service raises an error."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    cache = {}
    with pytest.raises(RenderError, match="missing service metadata for nonexistent"):
        load_service_meta_with_includes("nonexistent", services_dir, cache)


def test_load_service_meta_cache_behavior(tmp_path):
    """Test that loaded services are properly cached."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create a service
    service_dir = services_dir / "cached-service"
    service_dir.mkdir()
    (service_dir / "service.yaml").write_text(
        """
name: cached-service
type: host
network: host
"""
    )

    cache = {}

    # First load
    meta1 = load_service_meta_with_includes("cached-service", services_dir, cache)
    assert "cached-service" in cache

    # Second load should return cached version
    meta2 = load_service_meta_with_includes("cached-service", services_dir, cache)
    assert meta1 is meta2  # Same object reference


def test_load_service_meta_multiple_includes_same_level(tmp_path):
    """Test service with multiple includes at the same level."""
    services_dir = tmp_path / "services"
    services_dir.mkdir()

    # Create base-1
    (services_dir / "base-1").mkdir()
    (services_dir / "base-1" / "service.yaml").write_text(
        """
name: base-1
config:
  - source: base1/config.yaml
    destination: /etc/base1/config.yaml
"""
    )

    # Create base-2
    (services_dir / "base-2").mkdir()
    (services_dir / "base-2" / "service.yaml").write_text(
        """
name: base-2
config:
  - source: base2/config.yaml
    destination: /etc/base2/config.yaml
"""
    )

    # Create service that includes both
    (services_dir / "multi-service").mkdir()
    (services_dir / "multi-service" / "service.yaml").write_text(
        """
name: multi-service
include:
  - base-1
  - base-2
config:
  - source: multi/config.yaml
    destination: /etc/multi/config.yaml
"""
    )

    cache = {}
    meta = load_service_meta_with_includes("multi-service", services_dir, cache)

    # Should have configs from base-1, base-2, and multi (in that order)
    assert len(meta["config"]) == 3
    assert meta["config"][0]["source"] == "base1/config.yaml"
    assert meta["config"][1]["source"] == "base2/config.yaml"
    assert meta["config"][2]["source"] == "multi/config.yaml"
