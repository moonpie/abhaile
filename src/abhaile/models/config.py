"""Typed configuration structures used by CLI validation/render flow."""

from __future__ import annotations

from typing import Any, TypedDict


class MappingConfig(TypedDict):
    """Top-level structure of mapping.yaml."""

    abhaile: list[dict[str, Any]]


class NetworkConfig(TypedDict, total=False):
    """Top-level structure of network.yaml."""

    vlans: dict[str, Any]
    dns: dict[str, Any]
    hosts: dict[str, Any]
    services: dict[str, Any]


class ServiceConfig(TypedDict, total=False):
    """Common service.yaml fields used by validation and renderers."""

    name: str
    type: str
    mode: str
    network: str
    includes: list[str]
    dns: dict[str, Any]
