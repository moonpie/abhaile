"""Execution helpers for mutating local host state during apply."""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from abhaile.utils.errors import ApplyError


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
    """Copy source file to target atomically with optional ownership and mode enforcement.

    Args:
        source: Source file path (must exist and be regular).
        target: Absolute target path.
        mode: Optional file mode (e.g., 0o600). If None, preserves source mode.
        owner_user: Optional owner username. If None, owner is not changed.
        owner_group: Optional owner group name. If None, owner is not changed.

    Raises:
        ApplyError: On any failure (missing source, invalid target, ownership lookup, etc.).
    """
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
    action_id: str = "",
    action_type: str = "command",
    run_as_user: str | None = None,
    check: bool = True,
) -> ExecutionResult:
    """Execute a command and return structured result.

    Args:
        argv: Command argv (not shell-interpreted).
        action_id: Caller-provided identifier for the action.
        action_type: Type of action (e.g., 'validate', 'reload', 'restart').
        run_as_user: Optional user to run command as (via `sudo -u`).
        check: If True, raise ApplyError on non-zero exit.

    Returns:
        ExecutionResult with success/failure and captured output.

    Raises:
        ApplyError: If check=True and command exits non-zero.
    """
    if not argv:
        raise ApplyError("Command argv is empty")

    actual_argv = argv
    if run_as_user:
        actual_argv = ["sudo", "-u", run_as_user, "--", *argv]

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
    action_id: str = "",
    is_blocker: bool = True,
) -> ExecutionResult:
    """Run a validation command and return result.

    Args:
        argv: Validation command argv.
        action_id: Identifier for this validation.
        is_blocker: If True, raise on failure (blocker); if False, log as diagnostic.

    Returns:
        ExecutionResult with validation outcome.

    Raises:
        ApplyError: If is_blocker=True and validation fails.
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
    """Execute systemctl command for a unit.

    Args:
        action: systemctl action (e.g., 'start', 'stop', 'reload', 'try-restart').
        unit_name: Full unit name (e.g., 'caddy.service').
        user: If True, use `systemctl --user`.
        run_as_user: If set (with user=True), run command as this user via sudo.

    Returns:
        ExecutionResult of the systemctl invocation.

    Raises:
        ApplyError: On command execution or non-zero exit.
    """
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

    Args:
        gate_name: Human-readable gate name (e.g., 'quadlet.volume.delete').
        allow_destructive: Whether --allow-destructive flag is set.
        escalations: List of escalations from owner_plan. If gate_name in escalations, require flag.

    Raises:
        ApplyError: If operation is blocked by gate.
    """
    escalations = escalations or []
    is_escalated = any(gate_name in esc for esc in escalations)
    if is_escalated and not allow_destructive:
        raise ApplyError(
            f"Destructive operation blocked by gate: {gate_name}. "
            f"Use --allow-destructive to override."
        )
