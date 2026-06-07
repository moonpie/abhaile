"""Execution helpers for mutating local host state during apply."""

from __future__ import annotations

import logging
import os
import pwd
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from abhaile.utils.errors import ApplyError

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    """Result of a single execution action."""

    action_id: str
    action_type: str
    success: bool
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""


def resolve_rendered_source(rendered_dir: Path, render_path: str) -> Path:
    """Resolve a manifest render_path safely under rendered_dir."""
    rendered_root = rendered_dir.resolve()
    source_path = (rendered_dir / render_path).resolve()
    if source_path != rendered_root and rendered_root not in source_path.parents:
        raise ApplyError(f"Manifest render_path escapes rendered dir: {render_path}")
    return source_path


def atomic_copy_file(source: Path, target: Path) -> None:
    """Copy source file to target atomically, creating parent directories."""
    atomic_copy_file_with_perms(source, target, mode=None, owner_user=None, owner_group=None)


def atomic_copy_file_with_perms(
    source: Path,
    target: Path,
    *,
    mode: int | None = None,
    owner_user: str | None = None,
    owner_group: str | None = None,
) -> None:
    """Copy source file to target atomically with optional ownership and mode enforcement."""
    if not source.exists() or not source.is_file():
        raise ApplyError(f"Missing rendered source file: {source}")
    if not target.is_absolute():
        raise ApplyError(f"Target path must be absolute: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=target.parent,
            prefix=".abhaile-tmp-",
            suffix=".tmp",
        ) as handle:
            tmp_path = Path(handle.name)

        shutil.copy2(source, tmp_path)

        # Enforce mode if specified
        if mode is not None:
            tmp_path.chmod(mode)

        # Enforce ownership if specified
        if owner_user is not None or owner_group is not None:
            uid = -1
            gid = -1
            if owner_user is not None:
                try:
                    uid = pwd.getpwnam(owner_user).pw_uid
                except KeyError as exc:
                    raise ApplyError(f"User not found: {owner_user}") from exc
            if owner_group is not None:
                try:
                    import grp

                    gid = grp.getgrnam(owner_group).gr_gid
                except KeyError as exc:
                    raise ApplyError(f"Group not found: {owner_group}") from exc
            os.chown(tmp_path, uid, gid)

        os.replace(tmp_path, target)
    except OSError as exc:
        raise ApplyError(f"Failed to copy {source} -> {target} ({exc})") from exc
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def remove_target_file(target: Path) -> None:
    """Remove a file target if it exists; non-regular paths are rejected."""
    if not target.exists():
        return
    if target.is_file() or target.is_symlink():
        try:
            target.unlink()
            return
        except OSError as exc:
            raise ApplyError(f"Failed to remove file: {target} ({exc})") from exc
    raise ApplyError(f"Refusing to remove non-file target: {target}")


def run_command(
    argv: list[str],
    *,
    action_id: str,
    action_type: str = "command",
    run_as_user: str | None = None,
    check: bool = True,
) -> ExecutionResult:
    """Execute a command and return structured result.

    argv is not shell-interpreted. If check is True, raises ApplyError on non-zero exit.
    """
    if not argv:
        raise ApplyError("Command argv is empty")

    actual_argv = argv
    if run_as_user:
        actual_argv = ["sudo", "-u", run_as_user, "--", *argv]

    LOG.debug("exec cmd=%s action_id=%s", " ".join(actual_argv), action_id)

    try:
        result = subprocess.run(
            actual_argv,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ApplyError(f"Failed to execute command ({action_id}): {exc}") from exc

    success = result.returncode == 0
    error_msg = ""
    if not success:
        error_msg = result.stderr.strip() or result.stdout.strip()
        LOG.debug("exec.failed action_id=%s rc=%d", action_id, result.returncode)
        if check:
            raise ApplyError(
                f"Command failed ({action_id}): " f"exit={result.returncode} error={error_msg}"
            )

    return ExecutionResult(
        action_id=action_id,
        action_type=action_type,
        success=success,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        error_message=error_msg,
    )


def run_validation(
    argv: list[str],
    *,
    action_id: str,
    is_blocker: bool = True,
) -> ExecutionResult:
    """Run a validation command and return result.

    If is_blocker is True, raises on failure; otherwise logs as diagnostic.
    """
    return run_command(
        argv,
        action_id=action_id,
        action_type="validation",
        check=is_blocker,
    )


def run_systemctl_command(
    action: str,
    unit_name: str,
    *,
    user: bool = False,
    run_as_user: str | None = None,
) -> ExecutionResult:
    """Execute systemctl command for a unit (e.g., 'caddy.service')."""
    argv = ["systemctl"]
    if user:
        argv.append("--user")
    argv.extend([action, unit_name])
    return run_command(
        argv,
        action_id=f"systemctl {action} {unit_name}",
        action_type="systemctl",
        run_as_user=run_as_user,
    )


def check_destructive_gate(
    *,
    gate_name: str,
    allow_destructive: bool,
    escalations: list[str] | None = None,
) -> None:
    """Check if a destructive operation is allowed.

    Raises ApplyError if gate_name appears in escalations and --allow-destructive is not set.
    """
    escalations = escalations or []
    is_escalated = any(gate_name in esc for esc in escalations)
    if is_escalated and not allow_destructive:
        raise ApplyError(
            f"Destructive operation blocked by gate: {gate_name}. "
            f"Use --allow-destructive to override."
        )
