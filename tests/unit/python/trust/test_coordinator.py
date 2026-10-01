"""Test the protected Phase 4 transaction coordinator."""

from __future__ import annotations

import os
import hashlib
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from abhaile.trust.coordinator import (
    HealthResult,
    LocalConvergenceResult,
    NetworkRecoveryRequest,
    ProtectedTransactionCoordinator,
    _commit_local_transaction,
    commit_rollback_transaction,
    evaluate_wider_health,
    prepare_network_recovery,
    publish_committed_runner,
)
from abhaile.trust.errors import TrustError
from abhaile.trust.network_recovery import NetworkRecovery, NetworkStage
from abhaile.trust.state_store import recover_state_record
from abhaile.trust.runner_publication import RunnerCandidates, stage_runner_candidates
from abhaile.trust.runner_lkg import write_protected_health_result
from abhaile.trust.runner_update import RunnerUpdateStage, plan_runner_update
from abhaile.trust.transaction import (
    TransactionPlan,
    TransactionStage,
    commit_apply_state,
    record_local_convergence,
)


class _Ledger:
    def __init__(self, revision: str) -> None:
        self.revision = revision
        self.fail_update = False

    def last_known_good(self) -> str:
        return self.revision

    def advance_last_known_good(self, revision: str, *, expected: str | None) -> None:
        if self.fail_update:
            raise TrustError("injected LKG update failure")
        if self.revision != expected:
            raise TrustError("CAS mismatch")
        self.revision = revision


def _start_health_producer(
    root: Path, transaction: TransactionPlan, succeeded: bool
) -> threading.Thread:
    def produce() -> None:
        deadline = time.monotonic() + 2
        while True:
            if time.monotonic() >= deadline:
                return
            if (root / "wider-health.challenge.json").exists():
                try:
                    write_protected_health_result(
                        root,
                        transaction,
                        (("wider-host-health", succeeded),),
                        expected_uid=os.getuid(),
                        expected_gid=os.getgid(),
                    )
                    return
                except TrustError as exc:
                    if "transaction authority" not in str(
                        exc
                    ) and "transaction-mismatched" not in str(exc):
                        raise
            time.sleep(0.005)

    thread = threading.Thread(target=produce)
    thread.start()
    return thread


def _health(
    tmp_path: Path, state: Path, transaction: TransactionPlan, *, succeeded: bool
) -> HealthResult:
    lkg = tmp_path / "runner-lkg"
    lkg.mkdir(mode=0o700, exist_ok=True)
    producer = _start_health_producer(lkg, transaction, succeeded)
    ledger = _Ledger(transaction.retained_lkg_revision)
    result = evaluate_wider_health(
        state,
        lkg,
        transaction,
        ledger,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        health_timeout_seconds=2,
    )
    producer.join(timeout=2)
    return result


def _plan(*, dry_run: bool = False) -> TransactionPlan:
    return TransactionPlan(
        transaction_id="coordinator-1",
        candidate_revision="1" * 40,
        candidate_capsule_sha256="2" * 64,
        candidate_manifest_sha256="3" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
        dry_run=dry_run,
    )


def _seed_retained(state: Path) -> None:
    retained = replace(
        _plan(),
        transaction_id="retained-authority",
        candidate_revision="a" * 40,
        candidate_capsule_sha256="c" * 64,
        candidate_manifest_sha256="b" * 64,
    )
    _commit_local_transaction(
        state,
        retained,
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def test_commits_local_result_before_health_and_runner_lkg(tmp_path: Path) -> None:
    """Bind local success, apply state, wider health, and runner LKG in order."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    _seed_retained(state)
    applied = _commit_local_transaction(
        state,
        _plan(),
        LocalConvergenceResult(True, True, True, False),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert applied.stage is TransactionStage.APPLY_COMMITTED
    record = recover_state_record(state, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert record is not None and record.convergence_outcome == "no-op"

    promoted = _health(tmp_path, state, applied, succeeded=True)
    assert promoted.transaction.stage is TransactionStage.RUNNER_COMMITTED
    assert promoted.rollback is None
    assert (tmp_path / "runner-lkg" / "runner-lkg.current.json").is_file()


def test_ordered_coordinator_prepares_network_then_commits_health_and_lkg(
    tmp_path: Path,
) -> None:
    """Expose one production entry point with ordering independent of its caller."""
    state = tmp_path / "state"
    lkg = tmp_path / "lkg"
    state.mkdir(mode=0o700)
    lkg.mkdir(mode=0o700)
    _seed_retained(state)
    network_root = tmp_path / "network-recovery"
    snapshot = b"snapshot"
    candidate = b"candidate"
    recovery = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "recovery-token",
        False,
        False,
    )
    events: list[str] = []

    class OrderedLedger(_Ledger):
        def advance_last_known_good(self, revision: str, *, expected: str | None) -> None:
            events.append("lkg")
            super().advance_last_known_good(revision, expected=expected)

    coordinator = ProtectedTransactionCoordinator(
        state,
        lkg,
        OrderedLedger("a" * 40),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )

    expected_applied = commit_apply_state(
        record_local_convergence(_plan(), validations_succeeded=True, changed=True)
    )
    producer = _start_health_producer(lkg, expected_applied, True)

    def converge() -> LocalConvergenceResult:
        assert network_root.is_dir()
        events.append("converge")
        return LocalConvergenceResult(True, True, True, True)

    result = coordinator.run(
        _plan(),
        converge,
        network=NetworkRecoveryRequest(network_root, snapshot, candidate, recovery),
    )
    producer.join(timeout=2)
    assert result.health.transaction.stage is TransactionStage.RUNNER_COMMITTED
    assert result.network is not None
    assert events == ["converge", "lkg"]


def test_health_failure_returns_exact_rollback_authority(tmp_path: Path) -> None:
    """Retain LKG and plan rollback from the actual applied candidate."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    _seed_retained(state)
    applied = _commit_local_transaction(
        state,
        _plan(),
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    failed = _health(tmp_path, state, applied, succeeded=False)
    assert failed.transaction.stage is TransactionStage.ROLLBACK_PLANNED
    assert failed.rollback is not None
    assert failed.rollback.from_manifest_sha256 == "3" * 64
    assert failed.rollback.to_manifest_sha256 == "b" * 64


def test_unresolved_health_is_rejected_before_any_new_transaction_mutation(
    tmp_path: Path,
) -> None:
    """Reject transaction B before network preparation, convergence, or state rotation."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    _seed_retained(state)
    applied = _commit_local_transaction(
        state,
        _plan(),
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    _health(tmp_path, state, applied, succeeded=False)
    before = recover_state_record(state, expected_uid=os.getuid(), expected_gid=os.getgid())
    lkg = tmp_path / "runner-lkg"
    network_root = tmp_path / "blocked-network"
    snapshot = b"snapshot"
    candidate = b"candidate"
    recovery = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "recovery-token",
        False,
        False,
    )
    called = False

    def converge() -> LocalConvergenceResult:
        nonlocal called
        called = True
        return LocalConvergenceResult(True, True, True, True)

    transaction_b = replace(_plan(), transaction_id="blocked-b", candidate_revision="4" * 40)
    coordinator = ProtectedTransactionCoordinator(
        state,
        lkg,
        _Ledger("a" * 40),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    with pytest.raises(TrustError, match="remains unresolved"):
        coordinator.run(
            transaction_b,
            converge,
            network=NetworkRecoveryRequest(network_root, snapshot, candidate, recovery),
        )
    assert called is False
    assert not network_root.exists()
    assert recover_state_record(state, expected_uid=os.getuid(), expected_gid=os.getgid()) == before


def test_network_recovery_is_persisted_before_any_network_executor(tmp_path: Path) -> None:
    """Connect the coordinator to protected recovery persistence without mutation."""
    snapshot = b"retained network state"
    candidate = b"candidate network state"
    recovery = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "recovery-token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"

    persisted = prepare_network_recovery(root, _plan(), snapshot, candidate, recovery)

    assert persisted.transaction_id == _plan().transaction_id
    assert persisted.plan.stage is NetworkStage.SNAPSHOTTED
    assert (root / "snapshot.bin").read_bytes() == snapshot
    assert (root / "candidate.bin").read_bytes() == candidate
    assert (root / "network.journal.json").is_file()

    with pytest.raises(TrustError, match="Dry-run"):
        prepare_network_recovery(
            tmp_path / "dry-run-network",
            _plan(dry_run=True),
            snapshot,
            candidate,
            recovery,
        )
    assert not (tmp_path / "dry-run-network").exists()


def test_committed_runner_publication_requires_and_rechecks_durable_lkg(
    tmp_path: Path,
) -> None:
    """Connect apply, health, protected ref, receipt, and runner publication gates."""
    plan = replace(
        _plan(),
        transaction_id="runner-publish",
        candidate_revision="6" * 40,
        candidate_capsule_sha256="7" * 64,
        candidate_manifest_sha256="8" * 64,
    )
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    _seed_retained(state)
    applied = _commit_local_transaction(
        state,
        plan,
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    lkg = tmp_path / "lkg"
    lkg.mkdir(mode=0o700)
    producer = _start_health_producer(lkg, applied, True)
    ledger = _Ledger(plan.retained_lkg_revision)
    committed = evaluate_wider_health(
        state,
        lkg,
        applied,
        ledger,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        health_timeout_seconds=2,
    ).transaction
    producer.join(timeout=2)

    service, timer = b"[Service]\n", b"[Timer]\n"
    recovery = json.dumps(
        {
            "transaction_id": plan.transaction_id,
            "service_sha256": hashlib.sha256(service).hexdigest(),
            "timer_sha256": hashlib.sha256(timer).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    runner = plan_runner_update(
        lock_device=2,
        lock_inode=3,
        service_changed=True,
        timer_changed=True,
        transaction_id=plan.transaction_id,
        candidate_revision=plan.candidate_revision,
        candidate_capsule_sha256=plan.candidate_capsule_sha256,
        candidate_manifest_sha256=plan.candidate_manifest_sha256,
        service_sha256=hashlib.sha256(service).hexdigest(),
        timer_sha256=hashlib.sha256(timer).hexdigest(),
        recovery_record_sha256=hashlib.sha256(recovery).hexdigest(),
    )
    runner = replace(runner, stage=RunnerUpdateStage.STAGED)
    stage = tmp_path / "runner-stage"
    stage_runner_candidates(
        stage,
        RunnerCandidates(service, timer),
        runner,
        validate=lambda _kind, payload: bool(payload),
    )
    effects: list[str] = []
    evidence = publish_committed_runner(
        state,
        stage,
        tmp_path / "units",
        lkg,
        committed,
        runner,
        ledger,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        lock_device=2,
        lock_inode=3,
        reload_manager=lambda: effects.append("reload"),
        rearm_timer=lambda: effects.append("rearm"),
    )
    assert evidence.durable_runner_lkg_receipt_sha256
    assert effects == ["reload", "rearm"]

    ledger.revision = "f" * 40
    with pytest.raises(TrustError, match="verification failed"):
        publish_committed_runner(
            state,
            stage,
            tmp_path / "units-2",
            lkg,
            committed,
            runner,
            ledger,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            lock_device=2,
            lock_inode=3,
            reload_manager=lambda: None,
            rearm_timer=lambda: None,
        )


@pytest.mark.parametrize(
    "finalization_boundary",
    [
        "before-health-terminal-write",
        "health-terminal-written",
        "before-health-result-unlink",
        "after-health-result-unlink",
        "before-health-challenge-unlink",
        "after-health-challenge-unlink",
        "before-health-active-unlink",
        "after-health-active-unlink",
        "health-finalized",
    ],
)
def test_rollback_commits_only_the_protected_retained_identity(
    tmp_path: Path, finalization_boundary: str
) -> None:
    """Rotate apply state back to exact prior capsule only after rollback validation."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    retained = TransactionPlan(
        transaction_id="retained-apply",
        candidate_revision="a" * 40,
        candidate_capsule_sha256="c" * 64,
        candidate_manifest_sha256="b" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )
    _commit_local_transaction(
        state,
        retained,
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    candidate = _commit_local_transaction(
        state,
        _plan(),
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    failed = _health(tmp_path, state, candidate, succeeded=False).transaction
    rollback = TransactionPlan(
        transaction_id="coordinator-1.rollback",
        candidate_revision="a" * 40,
        candidate_capsule_sha256="c" * 64,
        candidate_manifest_sha256="b" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )
    rollback_lock = tmp_path / "runner-lkg"

    def interrupt(boundary: str) -> None:
        if boundary == finalization_boundary:
            raise RuntimeError("crash after rollback commit")

    with pytest.raises(RuntimeError, match="crash after rollback commit"):
        commit_rollback_transaction(
            state,
            rollback_lock,
            failed,
            rollback,
            LocalConvergenceResult(True, True, True, True),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            failure_hook=interrupt,
        )
    if finalization_boundary == "health-terminal-written":
        next_plan = replace(
            _plan(),
            transaction_id="after-rollback-admission",
            candidate_revision="d" * 40,
            candidate_capsule_sha256="e" * 64,
            candidate_manifest_sha256="f" * 64,
        )
        expected_next = commit_apply_state(
            record_local_convergence(next_plan, validations_succeeded=True, changed=True)
        )
        producer = _start_health_producer(rollback_lock, expected_next, True)
        coordinator = ProtectedTransactionCoordinator(
            state,
            rollback_lock,
            _Ledger("a" * 40),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
        admitted = coordinator.run(
            next_plan,
            lambda: LocalConvergenceResult(True, True, True, True),
        )
        producer.join(timeout=2)
        assert admitted.health.transaction.stage is TransactionStage.RUNNER_COMMITTED
        assert not (rollback_lock / "wider-health.active.json").exists()
        return
    completed = commit_rollback_transaction(
        state,
        rollback_lock,
        failed,
        rollback,
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert completed.failed_transaction.stage is TransactionStage.ROLLBACK_COMMITTED
    current = recover_state_record(state, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert current is not None and current.capsule_sha256 == "c" * 64
    assert not (rollback_lock / "wider-health.active.json").exists()
    assert (rollback_lock / "wider-health.terminal.coordinator-1.json").is_file()

    next_plan = replace(
        _plan(),
        transaction_id="after-rollback",
        candidate_revision="d" * 40,
        candidate_capsule_sha256="e" * 64,
        candidate_manifest_sha256="f" * 64,
    )
    next_applied = _commit_local_transaction(
        state,
        next_plan,
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    after_rollback = _health(tmp_path, state, next_applied, succeeded=True)
    assert after_rollback.transaction.stage is TransactionStage.RUNNER_COMMITTED

    with pytest.raises(TrustError, match="retained"):
        commit_rollback_transaction(
            state,
            rollback_lock,
            failed,
            replace(rollback, transaction_id="bad-rollback", candidate_capsule_sha256="d" * 64),
            LocalConvergenceResult(True, True, True, True),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


@pytest.mark.parametrize("boundary", ["convergence", "validation", "handler"])
def test_failure_and_dry_run_write_no_state(tmp_path: Path, boundary: str) -> None:
    """Reject every incomplete local boundary and all dry-run state mutation."""
    state = tmp_path / boundary
    state.mkdir(mode=0o700)
    values = {
        "convergence": boundary != "convergence",
        "validation": boundary != "validation",
        "handler": boundary != "handler",
    }
    with pytest.raises(TrustError):
        _commit_local_transaction(
            state,
            _plan(),
            LocalConvergenceResult(
                values["convergence"], values["validation"], values["handler"], True
            ),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
    assert list(state.iterdir()) == []

    with pytest.raises(TrustError, match="Dry-run"):
        _commit_local_transaction(
            state,
            replace(_plan(), dry_run=True),
            LocalConvergenceResult(True, True, True, False),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
    assert list(state.iterdir()) == []
