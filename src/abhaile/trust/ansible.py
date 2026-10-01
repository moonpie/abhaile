"""Describe quarantined Ansible invocation and safety contracts without execution."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from abhaile.trust.capsule import CapsuleStore, SealedCapsule
from abhaile.trust.errors import TrustError
from abhaile.trust.model import validate_production_path
from abhaile.trust.manifest import validate_manifest
from abhaile.trust.convergence import ConvergencePlan, build_convergence_plan
from abhaile.trust.convergence_engine import compile_ansible_operations

RUNTIME = Path("/usr/lib/abhaile-ansible-runtime")
CAPSULES = Path("/var/lib/abhaile/capsules")
TEMPORARY = Path("/run/abhaile/ansible")

FLAG_CONTRACT = {
    "--help": "parser-only",
    "-h": "parser-only",
    "--ansible": "unconditionally-unavailable",
    "--output": "reject-caller-path",
    "--desired-manifest": "reject-caller-path",
    "--applied-manifest": "reject-caller-path",
    "--allow-host-mismatch": "reject-bypass",
    "--host": "must-match-protected-host",
    "--dry-run": "non-mutating-plan",
    "--dry-run-validations": "read-only-validation-plan",
    "--prune": "safe-removals-after-phase3",
    "--force-prune": "forced-removals-after-phase3",
    "--allow-destructive": "explicit-approval-after-phase3",
    "--json": "sanitized-report",
    "--verbose": "sanitized-status-only",
    "-v": "sanitized-status-only",
}


@dataclass(frozen=True)
class ApplyIntent:
    """Preserve supported requests for future manifest planning, without executing them."""

    dry_run: bool = True
    validations: bool = False
    prune: Literal["none", "safe", "force"] = "none"
    allow_destructive: bool = False
    json_report: bool = False
    verbosity: int = 0


def map_apply_intent(args: argparse.Namespace, host: str) -> ApplyIntent:
    """Validate compatibility without delegation or invented artifact semantics."""
    if args.output or args.desired_manifest or args.applied_manifest:
        raise TrustError("Ansible does not accept caller-selected artifact or state paths")
    if args.allow_host_mismatch or (args.host is not None and args.host != host):
        raise TrustError("Ansible host identity must match protected policy")
    if args.prune and args.force_prune:
        raise TrustError("Use either --prune or --force-prune, not both")
    if args.force_prune and not args.dry_run and not args.allow_destructive:
        raise TrustError("--force-prune requires --allow-destructive outside dry-run")
    if args.dry_run_validations and not args.dry_run:
        raise TrustError("--dry-run-validations requires --dry-run")
    return ApplyIntent(
        args.dry_run,
        args.dry_run_validations,
        "force" if args.force_prune else "safe" if args.prune else "none",
        args.allow_destructive,
        args.json,
        args.verbose,
    )


@dataclass(frozen=True)
class AnsiblePlan:
    """Record a proposal requiring later runtime and convergence gates."""

    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    cwd: Path
    source: Path
    rendered: Path
    manifest: Path
    convergence: ConvergencePlan
    intent: ApplyIntent
    executable: Literal[False] = False


def plan_ansible(store: CapsuleStore, capsule: SealedCapsule, intent: ApplyIntent) -> AnsiblePlan:
    """Independently admit and verify protected inputs; never start a process."""
    try:
        return _plan_ansible(store, capsule, intent, filesystem_root=Path("/"), owner_uid=0)
    except (OSError, ValueError, TrustError):
        raise TrustError("Ansible protected input validation failed") from None


def _plan_ansible(
    store: CapsuleStore,
    capsule: SealedCapsule,
    intent: ApplyIntent,
    *,
    filesystem_root: Path,
    owner_uid: int,
) -> AnsiblePlan:
    """Allow a synthetic filesystem only through a private test seam."""

    def fixed(path: Path) -> Path:
        return filesystem_root / path.relative_to("/")

    expected = fixed(CAPSULES) / store.policy.host / capsule.revision
    if capsule.path != expected or not re.fullmatch("[0-9a-f]{40}", capsule.revision):
        raise TrustError("Ansible requires the canonical sealed capsule")
    validate_production_path(
        expected, CAPSULES, filesystem_root=filesystem_root, owner_uid=owner_uid
    )
    admitted = store.mirror.admit(capsule.revision)
    verified = store.verify(expected, admitted)
    if verified != capsule:
        raise TrustError("Ansible capsule identity mismatch")
    runtime, temporary = fixed(RUNTIME), fixed(TEMPORARY)
    for path, namespace in ((runtime, RUNTIME), (temporary, TEMPORARY)):
        validate_production_path(
            path, namespace, filesystem_root=filesystem_root, owner_uid=owner_uid
        )
    if temporary.stat().st_mode & 0o077:
        raise TrustError("Ansible temporary directory must be private")
    python = runtime / "bin/python"
    validate_production_path(
        python, RUNTIME, regular_file=True, filesystem_root=filesystem_root, owner_uid=owner_uid
    )
    for path in runtime.rglob("*"):
        validate_production_path(
            path,
            RUNTIME,
            regular_file=not path.is_dir(),
            filesystem_root=filesystem_root,
            owner_uid=owner_uid,
        )
    config = verified.source / "ansible/ansible.cfg"
    playbook = verified.source / "ansible/playbooks/converge.yml"
    roles = verified.source / "ansible/roles"
    for path in (config, playbook, roles):
        validate_production_path(
            path,
            CAPSULES,
            regular_file=path != roles,
            filesystem_root=filesystem_root,
            owner_uid=owner_uid,
        )
    environment = {
        "PATH": str(runtime / "bin"),
        "HOME": str(temporary),
        "LANG": "C.UTF-8",
        "ANSIBLE_CONFIG": str(config),
        "ANSIBLE_ROLES_PATH": str(roles),
        "ANSIBLE_COLLECTIONS_PATH": str(runtime / "collections"),
        "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH": "False",
        "ANSIBLE_INVENTORY_ENABLED": "host_list",
        "ANSIBLE_STDOUT_CALLBACK": "default",
        "ANSIBLE_LOAD_CALLBACK_PLUGINS": "False",
        "ANSIBLE_NOCOLOR": "True",
        "ANSIBLE_NO_LOG": "True",
        "ANSIBLE_DIFF_ALWAYS": "False",
        "ANSIBLE_KEEP_REMOTE_FILES": "False",
        "ANSIBLE_LOCAL_TEMP": str(temporary),
        "ANSIBLE_REMOTE_TEMP": str(temporary),
        "ANSIBLE_RETRY_FILES_ENABLED": "False",
        "ANSIBLE_CACHE_PLUGIN": "memory",
        "ANSIBLE_GATHERING": "explicit",
        "ANSIBLE_INTERPRETER_PYTHON": str(python),
        "TMPDIR": str(temporary),
    }
    # Only protected builtin/runtime plugins and admitted capsule plugins are candidates.
    # Actual Ansible loader closure remains a later runtime integration gate.
    for plugin in (
        "ACTION",
        "BECOME",
        "CACHE",
        "CALLBACK",
        "CLICONF",
        "CONNECTION",
        "FILTER",
        "HTTPAPI",
        "INVENTORY",
        "LOOKUP",
        "NETCONF",
        "SHELL",
        "STRATEGY",
        "TERMINAL",
        "TEST",
        "VARS",
    ):
        environment[f"ANSIBLE_{plugin}_PLUGINS"] = str(runtime / "plugins" / plugin.lower())
    environment["ANSIBLE_LIBRARY"] = str(runtime / "modules")
    environment["ANSIBLE_MODULE_UTILS"] = str(runtime / "module_utils")
    environment["ANSIBLE_LOG_PATH"] = "/dev/null"
    convergence_manifest = validate_manifest(verified.rendered, verified.host)
    convergence = build_convergence_plan(convergence_manifest)
    operations = compile_ansible_operations(convergence, convergence_manifest, verified.rendered)
    variables = json.dumps(
        {
            "abhaile_capsule_verified": True,
            "abhaile_expected_host": verified.host,
            "abhaile_manifest": str(verified.rendered / "convergence-manifest.json"),
            "abhaile_rendered_root": str(verified.rendered),
            "abhaile_operations": [operation.ansible_value() for operation in operations],
            "ansible_python_interpreter": str(python),
        },
        sort_keys=True,
    )
    argv: tuple[str, ...] = (
        str(python),
        "-I",
        "-m",
        "ansible.cli.playbook",
        "-i",
        "localhost,",
        "--connection=local",
        "--extra-vars",
        variables,
        str(playbook),
    )
    if intent.dry_run:
        argv += ("--check",)
    return AnsiblePlan(
        argv,
        tuple(sorted(environment.items())),
        verified.source,
        verified.source,
        verified.rendered,
        verified.rendered / "convergence-manifest.json",
        convergence,
        intent,
    )


@dataclass(frozen=True)
class SecretTaskPolicy:
    """Suppress payload channels; leave runtime values with Vault Agent."""

    no_log: Literal[True] = True
    diff: Literal[False] = False
    gather_facts: Literal[False] = False
    temporary_mode: int = 0o700
    umask: int = 0o077


def sanitized_result(*, succeeded: bool) -> dict[str, str]:
    """Report a closed status without accepting command output or exception text."""
    return {"status": "succeeded" if succeeded else "failed", "detail": "output suppressed"}


def reject_execution() -> None:
    """Fail closed without exposing subprocess arguments, errors, or output."""
    raise TrustError("Ansible execution remains quarantined") from None
