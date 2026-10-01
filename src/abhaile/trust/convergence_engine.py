"""Compile a verified convergence plan into bounded Ansible operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from abhaile.trust.convergence import ConvergencePlan, ConvergenceStep
from abhaile.trust.errors import TrustError
from abhaile.models.software import parse_software_operation
from abhaile.utils.errors import RenderError

NETWORK_KINDS = frozenset({"networkd.netdev", "networkd.network", "networkd.dropin"})
FILE_KINDS = frozenset(
    {
        "systemd.unit",
        "systemd.dropin",
        "resolved.config",
        "resolved.dropin",
        "host.sysusers",
        "host.sudoers",
        "host.authorized_keys",
        "coredns.config",
        "coredns.zone",
        "caddy.config",
        "vault.config",
        "vault.template",
        "quadlet.network",
        "quadlet.volume",
        "quadlet.image",
        "quadlet.build",
        "quadlet.pod",
        "quadlet.container",
        "service.config",
        "service.env",
    }
)
NETWORK_PREREQUISITES = frozenset({"network-backend", "resolver"})


@dataclass(frozen=True)
class AnsibleOperation:
    """Describe one closed operation for the admitted Ansible role."""

    operation: str
    kind: str
    action: str
    owner_ref: str
    source: str
    source_sha256: str
    target: str | None
    context: str
    owner: str | None
    group: str | None
    mode: str | None
    validation: str
    lifecycle: tuple[str, ...]
    lifecycle_metadata: tuple[tuple[str, object], ...]
    execution_identity: tuple[tuple[str, object], ...] | None = None
    parameters: tuple[tuple[str, object], ...] = ()
    effects: tuple[tuple[tuple[str, object], ...], ...] = ()
    no_log: bool = True
    diff: bool = False

    def ansible_value(self) -> dict[str, object]:
        """Return a deterministic data-only value for Ansible extra variables."""
        return {
            "operation": self.operation,
            "kind": self.kind,
            "action": self.action,
            "owner_ref": self.owner_ref,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "target": self.target,
            "context": self.context,
            "owner": self.owner,
            "group": self.group,
            "mode": self.mode,
            "validation": self.validation,
            "lifecycle": list(self.lifecycle),
            "lifecycle_metadata": dict(self.lifecycle_metadata),
            "execution_identity": (
                dict(self.execution_identity) if self.execution_identity is not None else None
            ),
            "parameters": dict(self.parameters),
            "effects": [dict(effect) for effect in self.effects],
            "no_log": self.no_log,
            "diff": self.diff,
        }


def compile_ansible_operations(
    plan: ConvergencePlan, manifest: dict[str, Any], rendered_root: Path
) -> tuple[AnsibleOperation, ...]:
    """Compile only validated, dependency-ordered manifest entries.

    The caller must pass the exact plan and manifest produced by the protected
    capsule validation path. Compilation is pure and rejects every unsupported
    family before Ansible can mutate the target.
    """
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != len(plan.steps):
        raise TrustError("Convergence operation input disagrees with the verified plan")
    by_render = {entry.get("render_path"): entry for entry in entries if isinstance(entry, dict)}
    if len(by_render) != len(entries):
        raise TrustError("Convergence operation input contains duplicate artifacts")
    identities = manifest.get("execution_identities")
    if not isinstance(identities, dict):
        raise TrustError("Convergence execution identity authority is unavailable")
    compiled = [
        _compile_step(step, by_render.get(step.render_path), rendered_root, identities)
        for step in plan.steps
    ]
    operations = _aggregate_owner_lifecycle(plan, compiled)
    if {operation.source for operation in compiled} != {
        str(rendered_root / step.render_path) for step in plan.steps
    }:
        raise TrustError("Convergence operation compilation is incomplete")
    return operations


def _compile_step(
    step: ConvergenceStep,
    entry: object,
    rendered_root: Path,
    identities: dict[str, object],
) -> AnsibleOperation:
    if not isinstance(entry, dict) or any(
        entry.get(name) != getattr(step, attribute)
        for name, attribute in (
            ("owner_ref", "owner_ref"),
            ("target_path", "target_path"),
            ("kind", "kind"),
            ("action", "action"),
            ("execution_context", "execution_context"),
            ("validation", "validation"),
        )
    ):
        raise TrustError("Convergence operation entry disagrees with its verified plan")
    if tuple(entry.get("lifecycle", ())) != step.lifecycle:
        raise TrustError("Convergence operation lifecycle disagrees with its verified plan")
    if tuple(sorted(entry.get("lifecycle_metadata", {}).items())) != step.lifecycle_metadata:
        raise TrustError("Convergence lifecycle authority disagrees with its verified plan")
    source = rendered_root / step.render_path
    if not source.is_relative_to(rendered_root) or source.is_symlink():
        raise TrustError("Convergence operation source is outside the sealed artifact root")
    if step.kind in NETWORK_KINDS:
        raise TrustError("Network convergence remains separately quarantined")
    if step.kind.startswith("software."):
        return _software_operation(step, entry, source, identities)
    if step.kind == "service.directory":
        return _file_operation("directory", step, entry, source, identities)
    if step.kind == "host.sudoers":
        return _file_operation("sudo-candidate", step, entry, source, identities)
    if step.kind in FILE_KINDS:
        return _file_operation("publish", step, entry, source, identities)
    raise TrustError(f"Convergence kind has no bounded Ansible mapping: {step.kind}")


def _software_operation(
    step: ConvergenceStep,
    entry: dict[str, Any],
    source: Path,
    identities: dict[str, object],
) -> AnsibleOperation:
    """Compile one closed typed software operation without inventing authority."""
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        raise TrustError("Convergence software metadata is unavailable")
    if step.kind == "software.build":
        raise TrustError("Container build lacks immutable root-verifiable inputs")
    if step.kind == "software.packages":
        try:
            packages = source.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            raise TrustError("Convergence package payload is invalid") from None
        effects = [
            {"kind": "package", "target": package, "role": "requirement"} for package in packages
        ]
        if not packages or metadata != {
            "operation_id": "packages",
            "operation_type": "packages",
            "execution_policy": "admitted",
            "effects": effects,
        }:
            raise TrustError("Convergence package authority disagrees with its payload")
        return AnsibleOperation(
            "packages",
            step.kind,
            step.action,
            step.owner_ref,
            str(source),
            str(entry["sha256"]),
            None,
            step.execution_context,
            None,
            None,
            None,
            step.validation,
            (),
            (),
            _identity(step, identities),
            (("packages", packages),),
            tuple(tuple(sorted(effect.items())) for effect in effects),
        )
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        parsed = parse_software_operation(payload)
    except (OSError, UnicodeError, yaml.YAMLError, RenderError):
        raise TrustError("Convergence software payload is invalid") from None
    if (
        parsed.operation_id != metadata.get("operation_id")
        or parsed.operation_type != metadata.get("operation_type")
        or parsed.execution_policy != metadata.get("execution_policy")
        or [effect.manifest_value() for effect in parsed.effects] != metadata.get("effects")
    ):
        raise TrustError("Convergence software authority disagrees with its payload")
    if parsed.operation_type in NETWORK_PREREQUISITES:
        raise TrustError("Network convergence remains separately quarantined")
    if parsed.execution_policy != "admitted" or not isinstance(payload, dict):
        raise TrustError("Convergence software operation is not admitted")
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        raise TrustError("Convergence software parameters are unavailable")
    return AnsibleOperation(
        parsed.operation_type,
        step.kind,
        step.action,
        step.owner_ref,
        str(source),
        str(entry["sha256"]),
        None,
        step.execution_context,
        "0" if parsed.operation_type in {"binary-download", "archive-download"} else None,
        "0" if parsed.operation_type in {"binary-download", "archive-download"} else None,
        (
            str(parameters["mode"])
            if parsed.operation_type in {"binary-download", "archive-download"}
            else None
        ),
        step.validation,
        (),
        (),
        _identity(step, identities),
        tuple(sorted(parameters.items())),
        tuple(tuple(sorted(effect.manifest_value().items())) for effect in parsed.effects),
    )


def _file_operation(
    operation: str,
    step: ConvergenceStep,
    entry: dict[str, Any],
    source: Path,
    identities: dict[str, object],
) -> AnsibleOperation:
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        raise TrustError("Convergence file metadata is unavailable")
    parameters: tuple[tuple[str, object], ...] = ()
    if step.kind == "coredns.zone":
        target = entry.get("target_path")
        if not isinstance(target, str) or not target.endswith(".zone"):
            raise TrustError("CoreDNS zone target lacks exact origin authority")
        zone = Path(target).name.removesuffix(".zone")
        if not zone or zone.startswith("."):
            raise TrustError("CoreDNS zone origin authority is invalid")
        parameters = (("zone", zone),)
    return AnsibleOperation(
        operation,
        step.kind,
        step.action,
        step.owner_ref,
        str(source),
        str(entry["sha256"]),
        (
            "/var/lib/abhaile/sudo-candidates/abhaile"
            if operation == "sudo-candidate"
            else step.target_path
        ),
        step.execution_context,
        _numeric_identity(metadata["owner"], identities, group=False),
        _numeric_identity(metadata["group"], identities, group=True),
        str(metadata["mode"]),
        step.validation,
        (),
        (),
        _identity(step, identities),
        parameters,
    )


def _numeric_identity(value: object, identities: dict[str, object], *, group: bool) -> str:
    """Resolve ownership only from numeric, root, or sealed identity authority."""
    text = str(value)
    if text == "root":
        return "0"
    if text.isdecimal():
        return str(int(text))
    matches = [
        identity
        for identity in identities.values()
        if isinstance(identity, dict) and identity.get("name") == text
    ]
    if len(matches) != 1:
        raise TrustError("Convergence ownership lacks unambiguous sealed identity authority")
    key = "gid" if group else "uid"
    identifier = matches[0].get(key)
    if type(identifier) is not int or identifier < 0:
        raise TrustError("Convergence ownership identity is invalid")
    return str(identifier)


def _aggregate_owner_lifecycle(
    plan: ConvergencePlan, compiled: list[AnsibleOperation]
) -> tuple[AnsibleOperation, ...]:
    """Flush coalesced lifecycle authority once at each owner boundary."""
    operations: list[AnsibleOperation] = []
    for owner in plan.owner_order:
        pairs = [
            (step, operation)
            for step, operation in zip(plan.steps, compiled)
            if step.owner_ref == owner
        ]
        operations.extend(operation for _step, operation in pairs)
        contexts = sorted(
            {(operation.context, operation.execution_identity) for _step, operation in pairs},
            key=lambda value: value[0],
        )
        for context, identity in contexts:
            scoped = [pair for pair in pairs if pair[1].context == context]
            effects: dict[str, object] = {}
            for step, _operation in scoped:
                metadata = dict(step.lifecycle_metadata)
                for effect in step.lifecycle:
                    value = metadata.get(effect, {})
                    if effect in effects and effects[effect] != value:
                        raise TrustError("Convergence owner has conflicting lifecycle authority")
                    effects[effect] = value
            if not effects:
                continue
            anchor = scoped[-1][1]
            operations.append(
                AnsibleOperation(
                    "lifecycle",
                    "owner.lifecycle",
                    "ensure",
                    owner,
                    anchor.source,
                    anchor.source_sha256,
                    None,
                    context,
                    None,
                    None,
                    None,
                    "structural",
                    tuple(sorted(effects)),
                    tuple(sorted(effects.items())),
                    identity,
                )
            )
    return tuple(operations)


def _identity(
    step: ConvergenceStep, identities: dict[str, object]
) -> tuple[tuple[str, object], ...] | None:
    if not step.execution_context.startswith("user:"):
        return None
    value = identities.get(step.execution_context)
    name = step.execution_context.removeprefix("user:")
    if (
        not isinstance(value, dict)
        or set(value) != {"name", "uid", "gid", "home", "shell"}
        or value.get("name") != name
        or type(value.get("uid")) is not int
        or type(value.get("gid")) is not int
        or not 0 < value["uid"] < 2**32 - 1
        or not 0 < value["gid"] < 2**32 - 1
        or value.get("home") != f"/home/{name}"
        or value.get("shell") not in {"/bin/bash", "/usr/sbin/nologin", "/bin/false"}
    ):
        raise TrustError("Named-user operation lacks admitted execution identity")
    return tuple(sorted(value.items()))
