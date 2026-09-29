"""Validate admitted host configuration without decrypting bootstrap material."""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abhaile.trust.errors import TrustError
from abhaile.utils.config import read_json, read_yaml_mapping
from abhaile.utils.errors import RenderError
from abhaile.validation.network import validate_host_physical_device, validate_network_sanity
from abhaile.validation.schema import validate_schema
from abhaile.validation.services import parse_mapping
from abhaile.validation.users import validate_user_management_ids


@dataclass(frozen=True)
class HostValidation:
    """Return only non-secret identity and selected creation-rule position."""

    host: str
    creation_rule: int


def validate_admitted_config(source: Path, host: str, local_host: str) -> HostValidation:
    """Validate admitted config using canonical schemas and host semantics.

    The caller must independently admit and verify source before calling. Host
    identity is injected by the launcher, not derived from Ansible facts. This
    function never opens the encrypted bundle or performs host discovery.
    """
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", host) or host != local_host:
        raise TrustError("Host identity does not match the requested target")
    try:
        config = source / "config"
        mapping = read_yaml_mapping(config / "mapping.yaml")
        network = read_yaml_mapping(config / "network.yaml")
        host_data = read_yaml_mapping(config / "hosts" / host / "host.yaml")
        for name, data in (("mapping", mapping), ("network", network), ("host", host_data)):
            schema_path = source / "schemas" / f"{name}.schema.json"
            validate_schema(data, read_json(schema_path), name, schema_path)
        declared = parse_mapping(mapping)
        if len(declared) != len(mapping["abhaile"]):
            raise TrustError("Host declarations are ambiguous")
        if host not in declared or host not in network.get("hosts", {}):
            raise TrustError("Requested host is not declared")
        validate_network_sanity(network)
        validate_host_physical_device(host, host_data, network)
        validate_user_management_ids(host, config)
        rule = select_bootstrap_rule(read_yaml_mapping(source / ".sops.yaml"), host)
        bundle = (source / "secrets" / host / "vault-agent.sops.yaml").lstat()
        if not stat.S_ISREG(bundle.st_mode) or bundle.st_nlink != 1:
            raise TrustError("Bootstrap bundle metadata is invalid")
    except (RenderError, OSError, ValueError, TypeError, KeyError):
        # Canonical validators include config values in diagnostics. Suppress their
        # payload and exception chain at this privileged report boundary.
        raise TrustError("Admitted host configuration is invalid") from None
    return HostValidation(host, rule)


def select_bootstrap_rule(config: dict[str, Any], host: str) -> int:
    """Select the first matching SOPS rule without inspecting secret values.

    Support repository age-only bootstrap rules and portable literal/wildcard
    expressions. Unsupported features fail closed rather than being reinterpreted
    by Python's different regular-expression engine.
    """
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", host):
        raise TrustError("Bootstrap host is invalid")
    rules = config.get("creation_rules")
    if not isinstance(rules, list) or not rules:
        raise TrustError("SOPS creation rules are missing or malformed")
    candidate = f"secrets/{host}/vault-agent.sops.yaml"
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise TrustError("SOPS creation rule is malformed")
        expression = _portable_pattern(rule.get("path_regex", ""))
        if expression.search(candidate) is not None:
            _validate_age_rule(rule)
            return index
    raise TrustError("No SOPS creation rule matches the bootstrap artifact")


def _portable_pattern(value: object) -> re.Pattern[str]:
    """Accept an explicit shared subset of Go and Python path regex syntax."""
    if not isinstance(value, str) or len(value) > 512:
        raise TrustError("SOPS path expression is unsupported")
    remainder = value.removeprefix("^").removesuffix("$").replace(r"\.", "x")
    if remainder.count(".*") > 1:
        raise TrustError("SOPS path expression is unsupported")
    remainder = remainder.replace(".*", "x")
    if not re.fullmatch(r"[A-Za-z0-9/_.-]*", remainder):
        raise TrustError("SOPS path expression is unsupported")
    try:
        return re.compile(value)
    except re.error:
        raise TrustError("SOPS path expression is malformed") from None


def _validate_age_rule(rule: dict[str, Any]) -> None:
    """Validate supported recipient metadata without returning or logging it."""
    if set(rule) - {"path_regex", "age"}:
        raise TrustError("SOPS creation rule uses unsupported bootstrap options")
    age = rule.get("age")
    recipients = age.split(",") if isinstance(age, str) else age
    if not isinstance(recipients, list) or not recipients:
        raise TrustError("SOPS bootstrap age recipients are malformed")
    if any(
        not isinstance(value, str)
        or not re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", value.strip())
        for value in recipients
    ):
        raise TrustError("SOPS bootstrap age recipients are malformed")
