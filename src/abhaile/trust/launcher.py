"""Provide the fixed privileged launcher interface for experimental capsules."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from abhaile.trust.capsule import CapsuleStore
from abhaile.trust.containment import CgroupBoundary, RenderBoundary
from abhaile.trust.errors import TrustError
from abhaile.trust.git import TrustedMirror
from abhaile.trust.model import (
    TrustPaths,
    TrustPolicy,
    validate_production_path,
    validate_protected_path,
)

POLICY_PATH = Path("/etc/abhaile/trust-policy.json")
_MAX_ID = 2**32 - 2


def _validate_render_identity(policy: TrustPolicy) -> tuple[int, int]:
    """Return a dedicated unprivileged numeric renderer identity."""
    uid = policy.render_uid
    gid = policy.render_gid
    if (
        type(uid) is not int
        or type(gid) is not int
        or not 1 <= uid <= _MAX_ID
        or not 1 <= gid <= _MAX_ID
    ):
        raise TrustError("Protected render identity must be a dedicated non-root UID and GID")
    return uid, gid


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Accept only revision identity and constrained non-mutating switches."""
    parser = argparse.ArgumentParser(description="Prepare a trusted Abhaile capsule")
    parser.add_argument("--runner", action="store_true", required=True)
    parser.add_argument("--host", required=True, choices=("deimos", "phobos"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args(argv)


def load_policy(
    path: Path = POLICY_PATH,
    *,
    root_uid: int = 0,
    filesystem_root: Path = Path("/"),
) -> tuple[TrustPaths, TrustPolicy]:
    """Load roots only from a protected fixed policy file, never caller arguments."""
    fixed_policy = filesystem_root / POLICY_PATH.relative_to("/")
    if path != fixed_policy:
        raise TrustError("Protected trust policy path is not fixed")
    validate_production_path(
        path,
        Path("/etc/abhaile"),
        owner_uid=root_uid,
        regular_file=True,
        filesystem_root=filesystem_root,
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        roots = data["paths"]
        declared_paths = TrustPaths(**{name: Path(value) for name, value in roots.items()})
        paths = TrustPaths(
            **{
                name: filesystem_root / getattr(declared_paths, name).relative_to("/")
                for name in TrustPaths.__dataclass_fields__
            }
        )
        policy = TrustPolicy(
            remote_url=data["remote_url"],
            branch=data["branch"],
            host=data["host"],
            root_uid=root_uid,
            render_uid=data["render_uid"],
            render_gid=data["render_gid"],
            rollback_history=data.get("rollback_history", 2),
            known_host_pins=tuple(data["known_host_pins"]),
            remote_host=data["remote_host"],
            remote_user=data.get("remote_user"),
            remote_port=data.get("remote_port", 22),
            fetch_identity=paths.fetch_identity,
            render_python=filesystem_root
            / Path(
                data.get("render_python", "/usr/lib/abhaile-render-runtime/bin/python")
            ).relative_to("/"),
            render_runtime_root=filesystem_root
            / Path(data.get("render_runtime_root", "/usr/lib/abhaile-render-runtime")).relative_to(
                "/"
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise TrustError("Protected trust policy is invalid") from None
    _validate_render_identity(policy)
    for field in ("mirror", "staging", "quarantine", "capsules", "active"):
        value = getattr(declared_paths, field)
        if not value.is_relative_to(Path("/var/lib/abhaile")) or ".." in value.parts:
            raise TrustError("Protected policy selects a path outside its fixed namespace")
    for declared, value in (
        (declared_paths.known_hosts, paths.known_hosts),
        (declared_paths.fetch_identity, paths.fetch_identity),
    ):
        if not declared.is_relative_to(Path("/etc/abhaile")) or ".." in declared.parts:
            raise TrustError("Protected policy selects a path outside its fixed namespace")
        validate_production_path(
            value,
            Path("/etc/abhaile"),
            regular_file=True,
            filesystem_root=filesystem_root,
            owner_uid=root_uid,
        )
    expected_runtime = filesystem_root / Path("usr/lib/abhaile-render-runtime")
    if policy.render_runtime_root != expected_runtime:
        raise TrustError("Protected policy selects an unexpected render runtime")
    return paths, policy


def protected_render(
    source: Path,
    output: Path,
    host: str,
    policy: TrustPolicy,
    *,
    boundary: RenderBoundary | None = None,
) -> None:
    """Render selected protected source through the dedicated fixed runtime."""
    render_uid, render_gid = _validate_render_identity(policy)
    source_package = source / "src"
    _validate_render_runtime(policy)
    validate_protected_path(source_package, owner_uid=policy.root_uid)
    validate_protected_path(output, owner_uid=render_uid)
    bootstrap = (
        "import runpy,sys; "
        "sys.path.insert(0, sys.argv.pop(1)); "
        "runpy.run_module('abhaile.cli.render', run_name='__main__')"
    )
    if boundary is None:
        raise TrustError("Root-controlled renderer containment is required")
    boundary.run(
        (
            "/usr/bin/setpriv",
            f"--reuid={render_uid}",
            f"--regid={render_gid}",
            "--clear-groups",
            "--no-new-privs",
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
    )


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
    for path in policy.render_runtime_root.rglob("*"):
        validate_protected_path(
            path,
            owner_uid=policy.root_uid,
            regular_file=not path.is_dir(),
        )


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
    boundary = CgroupBoundary(interpreter=policy.render_python)
    store = CapsuleStore(paths, policy, mirror, boundary=boundary)
    store.prepare(
        args.revision,
        lambda source, output, host, render_boundary: protected_render(
            source, output, host, policy, boundary=render_boundary
        ),
        mode="dry-run",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
