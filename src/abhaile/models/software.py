"""Parse the closed typed software-operation contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from abhaile.utils.errors import RenderError

SHA256 = re.compile(r"[0-9a-f]{64}")
MODE = re.compile(r"0[0-7]{3}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@+-]*")
MODULE = re.compile(r"[A-Za-z0-9_-]+")
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?")
SAFE_PATH_ROOTS = ("/etc/", "/home/", "/srv/", "/usr/local/", "/var/lib/abhaile/")
EFFECT_ROLES = frozenset(
    {
        "activation",
        "backup",
        "configuration",
        "declaration",
        "link",
        "options",
        "output",
        "primary",
        "requirement",
        "rule",
        "runtime",
    }
)

OPERATION_PARAMETERS = {
    "binary-download": {"url", "sha256", "destination", "mode"},
    "archive-download": {"url", "sha256", "destination", "mode", "archive_member"},
    "container-build": {"url", "source_ref", "containerfile_base", "output_glob"},
    "kernel-modules": {"modules"},
    "systemd-units": {"units"},
    "network-backend": {"units", "legacy_path", "backup_path"},
    "resolver": {"units", "link_path", "resolv_conf_target"},
    "unattended-upgrades": {"enabled"},
    "udev-rule": {"rule_path", "rule", "reload"},
}
OPERATION_VALIDATION = {
    "binary-download": "binary-version",
    "archive-download": "binary-version",
    "container-build": "package-artifact",
    "kernel-modules": "modules-loadable",
    "systemd-units": "units-active",
    "network-backend": "networkd-enabled",
    "resolver": "resolved-enabled",
    "unattended-upgrades": "debconf-state",
    "udev-rule": "udev-rule-present",
}
TOP_LEVEL_KEYS = {
    "id",
    "name",
    "description",
    "operation",
    "parameters",
    "effects",
    "validation",
    "expected_results",
    "execution_policy",
}


@dataclass(frozen=True)
class SoftwareEffect:
    """Identify one filesystem or host-state mutation authority."""

    kind: str
    target: str
    role: str
    pattern: str | None = None
    cardinality: int | None = None

    @property
    def collision_key(self) -> str:
        """Return the namespace-qualified authority key."""
        namespace = "path" if self.kind == "artifact-set" else self.kind
        return f"{namespace}:{self.target}"

    def manifest_value(self) -> dict[str, object]:
        """Return the deterministic manifest representation."""
        value: dict[str, object] = {"kind": self.kind, "target": self.target, "role": self.role}
        if self.pattern is not None:
            value["pattern"] = self.pattern
            value["cardinality"] = self.cardinality
        return value


@dataclass(frozen=True)
class SoftwareOperation:
    """Hold a validated software operation and its mutation authorities."""

    operation_id: str
    operation_type: str
    execution_policy: str
    effects: tuple[SoftwareEffect, ...]


def parse_software_operation(payload: object) -> SoftwareOperation:
    """Validate and parse an operation without granting execution authority."""
    if not isinstance(payload, dict) or set(payload) != TOP_LEVEL_KEYS:
        raise RenderError("Software operation fields are incomplete or unsupported")
    operation_id = payload.get("id")
    operation = payload.get("operation")
    parameters = payload.get("parameters")
    validation = payload.get("validation")
    policy = payload.get("execution_policy")
    if (
        not isinstance(operation_id, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]*", operation_id) is None
    ):
        raise RenderError("Software operation id is invalid")
    if operation not in OPERATION_PARAMETERS or validation != OPERATION_VALIDATION[operation]:
        raise RenderError("Software operation or validation pairing is unsupported")
    if policy not in {"admitted", "phase4-integrity-blocked"}:
        raise RenderError("Software execution policy is invalid")
    if (operation == "container-build") != (policy == "phase4-integrity-blocked"):
        raise RenderError("Software execution policy disagrees with operation integrity")
    if not isinstance(parameters, dict) or set(parameters) != OPERATION_PARAMETERS[operation]:
        raise RenderError("Software operation parameters are incomplete or unsupported")
    _validate_parameters(operation, parameters)
    _validate_descriptions(payload)
    effects = _parse_effects(payload.get("effects"))
    _validate_effect_relationships(operation_id, operation, parameters, effects)
    return SoftwareOperation(operation_id, operation, policy, effects)


def _validate_parameters(operation: str, value: dict[str, Any]) -> None:
    if operation in {"binary-download", "archive-download"}:
        _https(value["url"])
        if not isinstance(value["sha256"], str) or SHA256.fullmatch(value["sha256"]) is None:
            raise RenderError("Software download digest is invalid")
        _path(value["destination"])
        if not isinstance(value["mode"], str) or MODE.fullmatch(value["mode"]) is None:
            raise RenderError("Software download mode is invalid")
        if operation == "archive-download":
            member = value["archive_member"]
            if (
                not isinstance(member, str)
                or PurePosixPath(member).name != member
                or member in {".", ".."}
            ):
                raise RenderError("Software archive member is unsafe")
    elif operation == "container-build":
        _https(value["url"])
        if (
            not isinstance(value["source_ref"], str)
            or re.fullmatch(r"[A-Za-z0-9._/-]+", value["source_ref"]) is None
        ):
            raise RenderError("Software build source reference is invalid")
        if not isinstance(value["containerfile_base"], str) or not value["containerfile_base"]:
            raise RenderError("Software build base image is invalid")
        pattern = value["output_glob"]
        if (
            not isinstance(pattern, str)
            or pattern.count("*") != 1
            or re.fullmatch(r"[A-Za-z0-9_.+-]*\*[A-Za-z0-9_.+-]*", pattern) is None
        ):
            raise RenderError("Software build output glob is unsafe")
    elif operation == "kernel-modules":
        modules = value["modules"]
        if not isinstance(modules, list) or not modules:
            raise RenderError("Software module declarations are invalid")
        for module in modules:
            if not isinstance(module, dict) or set(module) != {"name", "options"}:
                raise RenderError("Software module declaration is malformed")
            if not isinstance(module["name"], str) or MODULE.fullmatch(module["name"]) is None:
                raise RenderError("Software module name is invalid")
            if not isinstance(module["options"], list) or any(
                not isinstance(option, str) or not option or "\n" in option
                for option in module["options"]
            ):
                raise RenderError("Software module options are invalid")
    elif operation in {"systemd-units", "network-backend", "resolver"}:
        units = value["units"]
        if not isinstance(units, list) or not units:
            raise RenderError("Software unit declarations are invalid")
        for unit in units:
            if not isinstance(unit, dict) or set(unit) != {"name", "enabled", "state"}:
                raise RenderError("Software unit declaration is malformed")
            if not isinstance(unit["name"], str) or NAME.fullmatch(unit["name"]) is None:
                raise RenderError("Software unit name is invalid")
            if type(unit["enabled"]) is not bool or unit["state"] not in {
                "started",
                "stopped",
                "unchanged",
            }:
                raise RenderError("Software unit state is invalid")
        for key in set(value) - {"units"}:
            _path(value[key], mutation=key != "resolv_conf_target")
    elif operation == "unattended-upgrades":
        if type(value["enabled"]) is not bool:
            raise RenderError("Software debconf state is invalid")
    elif operation == "udev-rule":
        _path(value["rule_path"])
        if not isinstance(value["rule"], str) or not value["rule"] or "\n" in value["rule"]:
            raise RenderError("Software udev rule is invalid")
        if type(value["reload"]) is not bool:
            raise RenderError("Software udev reload flag is invalid")


def _validate_descriptions(payload: dict[str, Any]) -> None:
    for key in ("name", "description"):
        if not isinstance(payload[key], str) or not payload[key] or "\n" in payload[key]:
            raise RenderError(f"Software operation {key} is invalid")
    results = payload["expected_results"]
    if (
        not isinstance(results, list)
        or not results
        or len(results) != len(set(results))
        or any(not isinstance(result, str) or not result or "\n" in result for result in results)
    ):
        raise RenderError("Software expected results are invalid")


def _parse_effects(value: object) -> tuple[SoftwareEffect, ...]:
    if not isinstance(value, list) or not value:
        raise RenderError("Software effects must be a non-empty list")
    effects: list[SoftwareEffect] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise RenderError("Software effect is malformed")
        kind = raw.get("kind")
        keys = (
            {"kind", "target", "role", "pattern", "cardinality"}
            if kind == "artifact-set"
            else {"kind", "target", "role"}
        )
        if set(raw) != keys or kind not in {
            "path",
            "unit",
            "module",
            "package",
            "debconf",
            "artifact-set",
        }:
            raise RenderError("Software effect fields are unsupported")
        target, role = raw.get("target"), raw.get("role")
        if not isinstance(target, str) or role not in EFFECT_ROLES:
            raise RenderError("Software effect identity is invalid")
        pattern = raw.get("pattern")
        cardinality = raw.get("cardinality")
        if kind in {"path", "artifact-set"}:
            _path(target)
        elif kind == "unit" and NAME.fullmatch(target) is None:
            raise RenderError("Software unit effect is invalid")
        elif kind == "module" and MODULE.fullmatch(target) is None:
            raise RenderError("Software module effect is invalid")
        elif kind in {"package", "debconf"} and PACKAGE.fullmatch(target) is None:
            raise RenderError("Software package effect is invalid")
        if kind == "artifact-set" and (
            not isinstance(pattern, str)
            or pattern.count("*") != 1
            or re.fullmatch(r"[A-Za-z0-9_.+-]*\*[A-Za-z0-9_.+-]*", pattern) is None
            or cardinality != 1
        ):
            raise RenderError("Software artifact-set effect is unsafe")
        effects.append(SoftwareEffect(kind, target, role, pattern, cardinality))
    collision_keys = [effect.collision_key for effect in effects]
    if len(collision_keys) != len(set(collision_keys)):
        raise RenderError("Software effects contain duplicate mutation authority")
    return tuple(sorted(effects, key=lambda effect: (effect.kind, effect.target, effect.role)))


def _validate_effect_relationships(
    operation_id: str,
    operation: str,
    parameters: dict[str, Any],
    effects: tuple[SoftwareEffect, ...],
) -> None:
    expected: list[SoftwareEffect]
    if operation in {"binary-download", "archive-download"}:
        expected = [SoftwareEffect("path", parameters["destination"], "primary")]
    elif operation == "container-build":
        expected = [
            SoftwareEffect(
                "artifact-set",
                f"/var/lib/abhaile/builds/{operation_id}",
                "output",
                parameters["output_glob"],
                1,
            )
        ]
    elif operation == "kernel-modules":
        expected = [
            SoftwareEffect(
                "path", f"/etc/modules-load.d/abhaile-{operation_id}.conf", "declaration"
            )
        ]
        for module in parameters["modules"]:
            if module["options"]:
                expected.append(
                    SoftwareEffect(
                        "path", f"/etc/modprobe.d/abhaile-{module['name']}.conf", "options"
                    )
                )
            expected.append(SoftwareEffect("module", module["name"], "runtime"))
    elif operation in {"systemd-units", "network-backend", "resolver"}:
        expected = [
            SoftwareEffect("unit", unit["name"], "activation") for unit in parameters["units"]
        ]
        if operation == "network-backend":
            expected.extend(
                [
                    SoftwareEffect("path", parameters["legacy_path"], "primary"),
                    SoftwareEffect("path", parameters["backup_path"], "backup"),
                ]
            )
        if operation == "resolver":
            expected.append(SoftwareEffect("path", parameters["link_path"], "link"))
    elif operation == "unattended-upgrades":
        expected = [SoftwareEffect("debconf", "unattended-upgrades", "configuration")]
    else:
        expected = [SoftwareEffect("path", parameters["rule_path"], "rule")]
    expected_values = [
        effect.manifest_value()
        for effect in sorted(expected, key=lambda effect: (effect.kind, effect.target, effect.role))
    ]
    actual_values = [effect.manifest_value() for effect in effects]
    if actual_values != expected_values:
        raise RenderError("Software effects do not exactly match declared mutations")


def _https(value: object) -> None:
    if not isinstance(value, str):
        raise RenderError("Software source URL is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise RenderError("Software source URL must be canonical HTTPS")


def _path(value: object, *, mutation: bool = True) -> None:
    if not isinstance(value, str) or not value.startswith("/") or "//" in value:
        raise RenderError("Software path is not canonical absolute")
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in {".", ".."} for part in path.parts):
        raise RenderError("Software path is not canonical absolute")
    if mutation and not value.startswith(SAFE_PATH_ROOTS):
        raise RenderError("Software mutation path is outside allowed roots")
