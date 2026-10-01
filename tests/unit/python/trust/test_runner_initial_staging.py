"""Test interruption-safe initial runner candidate staging."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.runner_publication import RunnerCandidates, stage_runner_candidates
from abhaile.trust.runner_update import RunnerUpdatePlan, RunnerUpdateStage, plan_runner_update


def _plan(
    candidates: RunnerCandidates, *, transaction_id: str = "tx-runner-stage"
) -> RunnerUpdatePlan:
    recovery = json.dumps(
        {
            "transaction_id": transaction_id,
            "service_sha256": hashlib.sha256(candidates.service).hexdigest(),
            "timer_sha256": hashlib.sha256(candidates.timer).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return replace(
        plan_runner_update(
            lock_device=11,
            lock_inode=12,
            service_changed=True,
            timer_changed=True,
            transaction_id=transaction_id,
            candidate_revision="a" * 40,
            candidate_capsule_sha256="b" * 64,
            candidate_manifest_sha256="c" * 64,
            service_sha256=hashlib.sha256(candidates.service).hexdigest(),
            timer_sha256=hashlib.sha256(candidates.timer).hexdigest(),
            recovery_record_sha256=hashlib.sha256(recovery).hexdigest(),
        ),
        stage=RunnerUpdateStage.STAGED,
    )


@pytest.mark.parametrize(
    "failure_stage",
    [
        "before-initialization-authority",
        "after-initialization-authority",
        "before-directory-creation",
        "after-directory-creation",
        "before-service-write",
        "after-service-write",
        "before-timer-write",
        "after-timer-write",
        "before-recovery-write",
        "after-recovery-write",
        "before-identity-write",
        "after-identity-write",
        "before-directory-fsync",
        "after-directory-fsync",
        "before-directory-publication",
        "after-directory-publication",
    ],
)
def test_initial_staging_retries_every_durable_gap(tmp_path: Path, failure_stage: str) -> None:
    """Finish the exact initial publication after every injected interruption."""
    candidates = RunnerCandidates(b"[Service]\n", b"[Timer]\n")
    plan = _plan(candidates)
    root = tmp_path / "runner-stage"

    def fail(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError("injected staging interruption")

    with pytest.raises(RuntimeError, match="injected"):
        stage_runner_candidates(root, candidates, plan, validate=lambda *_: True, failure_hook=fail)
    stage_runner_candidates(root, candidates, plan, validate=lambda *_: True)
    assert (root / "runner.service").read_bytes() == candidates.service
    assert (root / "runner.timer").read_bytes() == candidates.timer
    assert (root / "staging.identity.json").is_file()
    assert not list(tmp_path.glob(".runner-stage.*"))


def test_initial_staging_rejects_partial_state_without_authority(tmp_path: Path) -> None:
    """Reject a preexisting private directory not introduced by this protocol."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _plan(candidates)
    pending = (
        tmp_path
        / f".runner-stage.{hashlib.sha256(plan.transaction_id.encode()).hexdigest()[:16]}.pending"
    )
    pending.mkdir(mode=0o700)
    with pytest.raises(TrustError, match="predates initialization authority"):
        stage_runner_candidates(
            tmp_path / "runner-stage", candidates, plan, validate=lambda *_: True
        )
    assert pending.is_dir()


def test_initial_staging_rejects_tampered_retry_artifact(tmp_path: Path) -> None:
    """Retain and reject ambiguous partial content instead of replacing it."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _plan(candidates)
    root = tmp_path / "runner-stage"

    def fail(stage: str) -> None:
        if stage == "after-service-write":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        stage_runner_candidates(root, candidates, plan, validate=lambda *_: True, failure_hook=fail)
    pending = next(tmp_path.glob(".runner-stage.*.pending"))
    (pending / "runner.service").write_bytes(b"tampered")
    with pytest.raises(TrustError, match="mismatched"):
        stage_runner_candidates(root, candidates, plan, validate=lambda *_: True)
    assert pending.is_dir()


def test_initial_staging_rejects_symlink_and_unsafe_mode(tmp_path: Path) -> None:
    """Never follow substituted staging state or accept loose metadata."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _plan(candidates)
    root = tmp_path / "runner-stage"

    def fail(stage: str) -> None:
        if stage == "after-initialization-authority":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        stage_runner_candidates(root, candidates, plan, validate=lambda *_: True, failure_hook=fail)
    pending = (
        tmp_path
        / f".runner-stage.{hashlib.sha256(plan.transaction_id.encode()).hexdigest()[:16]}.pending"
    )
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    pending.symlink_to(outside, target_is_directory=True)
    with pytest.raises(TrustError, match="cannot be opened safely"):
        stage_runner_candidates(root, candidates, plan, validate=lambda *_: True)
    pending.unlink()
    pending.mkdir(mode=0o755)
    with pytest.raises(TrustError, match="mode is unsafe"):
        stage_runner_candidates(root, candidates, plan, validate=lambda *_: True)


def test_initial_staging_rejects_transaction_mismatch(tmp_path: Path) -> None:
    """Do not resume another transaction's initialization authority."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _plan(candidates)
    root = tmp_path / "runner-stage"

    def fail(stage: str) -> None:
        if stage == "after-initialization-authority":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        stage_runner_candidates(root, candidates, plan, validate=lambda *_: True, failure_hook=fail)
    with pytest.raises(TrustError, match="transaction-mismatched"):
        stage_runner_candidates(
            root,
            candidates,
            _plan(candidates, transaction_id="tx-other"),
            validate=lambda *_: True,
        )


def test_initial_staging_rejects_arbitrary_final_directory(tmp_path: Path) -> None:
    """Reject a final directory lacking the complete transaction-bound identity."""
    candidates = RunnerCandidates(b"service", b"timer")
    root = tmp_path / "runner-stage"
    root.mkdir(mode=0o700)
    (root / "runner.service").write_bytes(candidates.service)
    with pytest.raises(TrustError):
        stage_runner_candidates(root, candidates, _plan(candidates), validate=lambda *_: True)
