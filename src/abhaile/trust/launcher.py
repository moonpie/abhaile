"""Provide the fixed privileged launcher interface for experimental capsules."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Sequence

from abhaile.trust.capsule import CapsuleStore
from abhaile.trust.errors import TrustError
from abhaile.trust.git import TrustedMirror
from abhaile.trust.model import (
    TrustPaths,
    TrustPolicy,
    validate_protected_chain,
    validate_protected_path,
)

POLICY_PATH = Path("/etc/abhaile/trust-policy.json")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Accept only revision identity and constrained non-mutating switches."""
    parser = argparse.ArgumentParser(description="Prepare a trusted Abhaile capsule")
    parser.add_argument("--runner", action="store_true", required=True)
    parser.add_argument("--host", required=True, choices=("deimos", "phobos"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args(argv)


def load_policy(path: Path = POLICY_PATH, *, root_uid: int = 0) -> tuple[TrustPaths, TrustPolicy]:
    """Load roots only from a protected fixed policy file, never caller arguments."""
    validate_protected_chain(path, anchor=path.parent, owner_uid=root_uid, regular_file=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        roots = data["paths"]
        paths = TrustPaths(**{name: Path(value) for name, value in roots.items()})
        policy = TrustPolicy(
            remote_url=data["remote_url"],
            branch=data["branch"],
            host=data["host"],
            root_uid=root_uid,
            render_uid=data["render_uid"],
            rollback_history=data.get("rollback_history", 2),
            known_host_pins=tuple(data["known_host_pins"]),
            remote_host=data["remote_host"],
            remote_user=data.get("remote_user"),
            remote_port=data.get("remote_port", 22),
            fetch_identity=paths.fetch_identity,
            render_python=Path(
                data.get("render_python", "/usr/lib/abhaile-render-runtime/bin/python")
            ),
            render_runtime_root=Path(
                data.get("render_runtime_root", "/usr/lib/abhaile-render-runtime")
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustError("Protected trust policy is invalid") from exc
    return paths, policy


def protected_render(source: Path, output: Path, host: str, policy: TrustPolicy) -> None:
    """Render selected protected source through the dedicated fixed runtime."""
    if policy.render_uid is None:
        raise TrustError("Protected render identity UID is not configured")
    source_package = source / "src"
    _validate_render_runtime(policy)
    validate_protected_path(source_package, owner_uid=policy.root_uid)
    validate_protected_path(output, owner_uid=policy.render_uid)
    bootstrap = (
        "import runpy,sys; "
        "sys.path.insert(0, sys.argv.pop(1)); "
        "runpy.run_module('abhaile.cli.render', run_name='__main__')"
    )
    result = subprocess.run(
        (
            "/usr/sbin/runuser",
            "--user",
            "abhaile-render",
            "--",
            str(policy.render_python),
            "-I",
            "-c",
            bootstrap,
            str(source_package),
            "--host",
            host,
            "--output",
            str(output.parent),
        ),
        cwd=source,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        check=False,
    )
    if result.returncode != 0:
        raise TrustError("Protected render failed")


def _validate_render_runtime(policy: TrustPolicy) -> None:
    """Require a protected runtime tree executable by the restricted identity."""
    try:
        relative = policy.render_python.relative_to(policy.render_runtime_root)
    except ValueError as exc:
        raise TrustError("Protected render interpreter is outside its runtime root") from exc
    if ".." in relative.parts:
        raise TrustError("Protected render interpreter escapes its runtime root")
    validate_protected_path(policy.render_runtime_root, owner_uid=policy.root_uid)
    if policy.render_runtime_root.stat().st_mode & 0o111 != 0o111:
        raise TrustError("Protected render runtime root is not traversable")
    current = policy.render_runtime_root
    for component in relative.parts[:-1]:
        current /= component
        validate_protected_path(current, owner_uid=policy.root_uid)
        if current.stat().st_mode & 0o111 != 0o111:
            raise TrustError(f"Protected render runtime is not traversable: {current}")
    validate_protected_path(policy.render_python, owner_uid=policy.root_uid, regular_file=True)
    if policy.render_python.stat().st_mode & 0o111 != 0o111:
        raise TrustError("Protected render interpreter is not executable by the render identity")


def main(argv: Sequence[str] | None = None) -> int:
    """Refresh trust when online and prepare a sealed dry-run capsule."""
    args = parse_args(argv)
    if os.geteuid() != 0:
        raise TrustError("Trusted convergence launcher must run as root")
    paths, policy = load_policy()
    if policy.host != args.host:
        raise TrustError("Requested host does not match protected trust policy")
    mirror = TrustedMirror(paths.mirror, policy, paths.known_hosts)
    mirror.initialize()
    if not args.offline:
        mirror.fetch()
    store = CapsuleStore(paths, policy, mirror)
    store.prepare(
        args.revision,
        lambda source, output, host: protected_render(source, output, host, policy),
        mode="dry-run",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
