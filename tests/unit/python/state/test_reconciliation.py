"""Test the minimal durable reconciliation state boundary."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abhaile.state.reconciliation import (
    classify_startup,
    clear_matching_failed_target,
    clear_matching_current_run,
    commit_last_successful,
    establish_last_successful,
    mark_current_run,
    mark_failed_target,
    read_current_run,
    read_failed_target,
    read_last_successful,
)
from abhaile.utils.errors import ApplyError

OLD_SHA = "1" * 40
NEW_SHA = "2" * 40


def test_startup_requires_enrollment_without_last_successful(tmp_path: Path) -> None:
    """Forbid unattended mutation before a baseline exists."""
    assert classify_startup(tmp_path) == "enrollment-required"


def test_explicit_enrollment_establishes_last_successful(tmp_path: Path) -> None:
    """Make a completed bootstrap apply the first recovery baseline."""
    establish_last_successful(tmp_path, OLD_SHA)

    assert read_last_successful(tmp_path) == OLD_SHA
    assert classify_startup(tmp_path) == "normal"
    assert (tmp_path / "last-successful-commit").stat().st_mode & 0o777 == 0o600


def test_enrollment_refuses_an_interrupted_mutation(tmp_path: Path) -> None:
    """Never overwrite recovery authority while a mutation marker exists."""
    mark_current_run(tmp_path, NEW_SHA)

    with pytest.raises(ApplyError, match="while a current run is recorded"):
        establish_last_successful(tmp_path, OLD_SHA)

    assert read_last_successful(tmp_path) is None
    assert read_current_run(tmp_path) == NEW_SHA


def test_interrupted_candidate_recovers_last_successful(tmp_path: Path) -> None:
    """Return to the old success while a different candidate marker exists."""
    (tmp_path / "last-successful-commit").write_text(f"{OLD_SHA} legacy metadata\n")
    mark_current_run(tmp_path, NEW_SHA)

    assert read_last_successful(tmp_path) == OLD_SHA
    assert read_current_run(tmp_path) == NEW_SHA
    assert classify_startup(tmp_path) == "recover-last-successful"


def test_interruption_after_commit_requires_verification(tmp_path: Path) -> None:
    """Recognize success committed before its matching marker was cleared."""
    mark_current_run(tmp_path, NEW_SHA)
    (tmp_path / "last-successful-commit").write_text(f"{NEW_SHA}\n")

    assert classify_startup(tmp_path) == "verify-committed"


def test_commit_advances_then_clears_matching_marker(tmp_path: Path) -> None:
    """Commit one successful candidate without another durable record."""
    mark_current_run(tmp_path, NEW_SHA)

    commit_last_successful(tmp_path, NEW_SHA)

    assert read_last_successful(tmp_path) == NEW_SHA
    assert read_current_run(tmp_path) is None
    assert classify_startup(tmp_path) == "normal"
    assert (tmp_path / "last-successful-commit").stat().st_mode & 0o777 == 0o600


def test_commit_refuses_marker_mismatch(tmp_path: Path) -> None:
    """Never advance success for a candidate other than the mutation marker."""
    mark_current_run(tmp_path, OLD_SHA)

    with pytest.raises(ApplyError, match="without its current-run marker"):
        commit_last_successful(tmp_path, NEW_SHA)

    assert read_last_successful(tmp_path) is None
    assert read_current_run(tmp_path) == OLD_SHA


def test_recovery_is_blocked_without_last_successful(tmp_path: Path) -> None:
    """Preserve an interrupted marker when no automatic recovery target exists."""
    mark_current_run(tmp_path, NEW_SHA)

    assert classify_startup(tmp_path) == "recovery-blocked"


def test_clear_refuses_nonmatching_verified_revision(tmp_path: Path) -> None:
    """Keep recovery evidence until the matching revision is verified."""
    mark_current_run(tmp_path, NEW_SHA)

    with pytest.raises(ApplyError, match="does not match"):
        clear_matching_current_run(tmp_path, OLD_SHA)

    assert read_current_run(tmp_path) == NEW_SHA


def test_state_reads_reject_symlink_records(tmp_path: Path) -> None:
    """Do not follow redirected state authority."""
    target = tmp_path / "elsewhere"
    target.write_text(f"{NEW_SHA}\n")
    os.symlink(target, tmp_path / "current-run")

    with pytest.raises(ApplyError, match="not a regular file"):
        read_current_run(tmp_path)


def test_failed_target_accepts_legacy_metadata_and_rewrites_sha_only(tmp_path: Path) -> None:
    """Migrate the existing suppression record without adding another format."""
    failed_target = tmp_path / "failed-target"
    failed_target.write_text(f"{OLD_SHA} timestamp last_good={NEW_SHA}\n")

    assert read_failed_target(tmp_path) == OLD_SHA

    mark_failed_target(tmp_path, NEW_SHA)

    assert failed_target.read_text() == f"{NEW_SHA}\n"
    assert failed_target.stat().st_mode & 0o777 == 0o600


def test_clear_failed_target_requires_observed_record(tmp_path: Path) -> None:
    """Do not erase suppression evidence that changed after it was read."""
    mark_failed_target(tmp_path, OLD_SHA)

    with pytest.raises(ApplyError, match="changed before"):
        clear_matching_failed_target(tmp_path, NEW_SHA)

    assert read_failed_target(tmp_path) == OLD_SHA


def test_clear_failed_target_is_idempotent_when_absent(tmp_path: Path) -> None:
    """Allow a successful candidate with no prior suppression record."""
    clear_matching_failed_target(tmp_path, NEW_SHA)

    assert read_failed_target(tmp_path) is None


def test_clear_failed_target_removes_previously_observed_record(tmp_path: Path) -> None:
    """Clear an obsolete failed SHA after a correcting candidate succeeds."""
    mark_failed_target(tmp_path, OLD_SHA)

    clear_matching_failed_target(tmp_path, OLD_SHA)

    assert read_failed_target(tmp_path) is None


def test_failed_target_read_rejects_symlink(tmp_path: Path) -> None:
    """Do not follow a redirected failed-target record."""
    target = tmp_path / "elsewhere"
    target.write_text(f"{NEW_SHA}\n")
    os.symlink(target, tmp_path / "failed-target")

    with pytest.raises(ApplyError, match="not a regular file"):
        read_failed_target(tmp_path)


def test_atomic_publication_failure_is_domain_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report publication failure without leaving a temporary authority file."""

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("injected replacement failure")

    monkeypatch.setattr("abhaile.state.reconciliation.os.replace", fail_replace)

    with pytest.raises(ApplyError, match="Unable to publish runner state record"):
        mark_current_run(tmp_path, NEW_SHA)

    assert not (tmp_path / "current-run").exists()
    assert list(tmp_path.glob(".current-run.*")) == []


@pytest.mark.parametrize("value", ["", "abc", "A" * 40, "3" * 39, "4" * 41])
def test_state_writes_reject_invalid_sha(tmp_path: Path, value: str) -> None:
    """Require one complete lowercase SHA-1 commit identity."""
    with pytest.raises(ApplyError, match="Invalid current-run"):
        mark_current_run(tmp_path, value)
