"""Test durable runner last-known-good commit and recovery boundaries."""

from __future__ import annotations

import os
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

from abhaile.trust.coordinator import (
    HealthResult,
    LocalConvergenceResult,
    _commit_local_transaction,
    evaluate_wider_health,
)
from abhaile.trust.errors import TrustError
from abhaile.trust.runner_lkg import (
    VerifiedRunnerLkgAuthority,
    prepare_wider_health_challenge,
    protected_coordinator_lock,
    validate_runner_lkg_authority,
    verify_runner_lkg_commit,
    write_protected_health_result,
)
from abhaile.trust.transaction import (
    TransactionPlan,
    TransactionStage,
    commit_apply_state,
    record_local_convergence,
)


class Ledger:
    """Provide a strict injected implementation of the protected mirror interface."""

    def __init__(self, revision: str) -> None:
        self.revision = revision
        self.updates = 0
        self.fail = False

    def last_known_good(self) -> str:
        return self.revision

    def advance_last_known_good(self, revision: str, *, expected: str | None) -> None:
        if self.fail:
            raise TrustError("injected mirror update failure")
        if self.revision != expected:
            raise TrustError("injected mirror CAS mismatch")
        self.updates += 1
        self.revision = revision


def _plan(transaction_id: str = "runner-lkg-1") -> TransactionPlan:
    return TransactionPlan(
        transaction_id=transaction_id,
        candidate_revision="1" * 40,
        candidate_capsule_sha256="2" * 64,
        candidate_manifest_sha256="3" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )


def _applied(tmp_path: Path, transaction_id: str = "runner-lkg-1") -> tuple[Path, TransactionPlan]:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    retained = replace(
        _plan("retained-authority"),
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
    applied = _commit_local_transaction(
        state,
        _plan(transaction_id),
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    return state, applied


def _evaluate(
    state: Path,
    root: Path,
    transaction: TransactionPlan,
    ledger: Ledger,
    *,
    succeeded: bool = True,
    hook: Callable[[str], None] | None = None,
) -> HealthResult:
    def produce() -> None:
        deadline = time.monotonic() + 2
        while not (root / "wider-health.challenge.json").exists():
            if time.monotonic() >= deadline:
                return
            time.sleep(0.005)
        if not (root / "wider-health.result.json").exists():
            write_protected_health_result(
                root,
                transaction,
                (("wider-host-health", succeeded),),
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
            )

    producer = threading.Thread(target=produce)
    producer.start()
    result = evaluate_wider_health(
        state,
        root,
        transaction,
        ledger,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        failure_hook=hook,
        health_timeout_seconds=2,
    )
    producer.join(timeout=2)
    return result


def test_health_failure_preserves_ref_and_writes_no_lkg_state(tmp_path: Path) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    result = _evaluate(state, root, applied, ledger, succeeded=False)
    assert result.transaction.stage is TransactionStage.ROLLBACK_PLANNED
    assert ledger.revision == "a" * 40
    assert {item.name for item in root.iterdir()} == {
        ".coordinator.lock",
        "wider-health.active.json",
        "wider-health.challenge.json",
        "wider-health.result.json",
    }


@pytest.mark.parametrize("succeeded", [True, False])
def test_retained_mirror_is_reverified_after_health_wait(tmp_path: Path, succeeded: bool) -> None:
    """Reject success and rollback authority if retained LKG changes during health."""
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)

    class ChangingLedger(Ledger):
        def __init__(self) -> None:
            super().__init__("a" * 40)
            self.reads = 0

        def last_known_good(self) -> str:
            self.reads += 1
            return "a" * 40 if self.reads == 1 else "d" * 40

    with pytest.raises(TrustError, match="retained authority"):
        _evaluate(state, root, applied, ChangingLedger(), succeeded=succeeded)


def test_missing_persisted_health_result_fails_closed(tmp_path: Path) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    with pytest.raises(TrustError, match="Timed out"):
        evaluate_wider_health(
            state,
            root,
            applied,
            Ledger("a" * 40),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            health_timeout_seconds=0.05,
        )


def test_mismatched_persisted_health_cannot_authorize_rollback(tmp_path: Path) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)

    mismatched = replace(applied, transaction_id="different-transaction")
    path = root / "wider-health.result.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "transaction_id": mismatched.transaction_id,
                "candidate_revision": mismatched.candidate_revision,
                "capsule_sha256": mismatched.candidate_capsule_sha256,
                "manifest_sha256": mismatched.candidate_manifest_sha256,
                "apply_commit_evidence": mismatched.apply_commit_evidence,
                "observations": [{"name": "wider-host-health", "succeeded": False}],
            }
        )
    )
    path.chmod(0o600)
    with pytest.raises(TrustError, match="Predated"):
        evaluate_wider_health(
            state,
            root,
            applied,
            Ledger("a" * 40),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_publication_authority_cannot_be_publicly_constructed_or_fabricated() -> None:
    with pytest.raises(TypeError, match="issued only"):
        VerifiedRunnerLkgAuthority("tx", "e" * 64)
    fabricated = object.__new__(VerifiedRunnerLkgAuthority)
    with pytest.raises(TrustError, match="lacks verified"):
        validate_runner_lkg_authority(fabricated, _plan())


def test_protected_coordinator_lock_serializes_transaction_boundary(tmp_path: Path) -> None:
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    attempted = threading.Event()
    acquired = threading.Event()

    def contender() -> None:
        attempted.set()
        with protected_coordinator_lock(root, expected_uid=os.getuid(), expected_gid=os.getgid()):
            acquired.set()

    with protected_coordinator_lock(root, expected_uid=os.getuid(), expected_gid=os.getgid()):
        thread = threading.Thread(target=contender)
        thread.start()
        assert attempted.wait(1)
        assert not acquired.wait(0.1)
    thread.join(timeout=1)
    assert acquired.is_set()


def test_update_failure_retains_recoverable_planned_journal(tmp_path: Path) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    ledger.fail = True
    with pytest.raises(TrustError, match="injected mirror"):
        _evaluate(state, root, applied, ledger)
    assert (root / "runner-lkg.journal.json").is_file()
    assert not (root / "runner-lkg.current.json").exists()


def test_interruption_after_ref_update_finishes_forward_without_second_update(
    tmp_path: Path,
) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)

    def interrupt(boundary: str) -> None:
        if boundary == "after-ref-update":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _evaluate(state, root, applied, ledger, hook=interrupt)
    assert ledger.revision == "1" * 40
    assert ledger.updates == 1
    recovered = _evaluate(state, root, applied, ledger)
    assert recovered.transaction.stage is TransactionStage.RUNNER_COMMITTED
    assert ledger.updates == 1
    verify_runner_lkg_commit(
        root,
        recovered.transaction,
        ledger,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


@pytest.mark.parametrize(
    "boundary",
    ["planned", "ref-advanced", "before-receipt-write", "after-receipt-write", "receipt-written"],
)
def test_retry_recovers_every_durable_boundary(tmp_path: Path, boundary: str) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)

    def interrupt(actual: str) -> None:
        if actual == boundary:
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _evaluate(state, root, applied, ledger, hook=interrupt)
    recovered = _evaluate(state, root, applied, ledger)
    assert recovered.transaction.stage is TransactionStage.RUNNER_COMMITTED
    assert ledger.revision == "1" * 40
    assert not (root / "runner-lkg.journal.json").exists()


def test_completed_commit_retry_is_idempotent(tmp_path: Path) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    first = _evaluate(state, root, applied, ledger)
    second = _evaluate(state, root, applied, ledger)
    assert second == first
    assert ledger.updates == 1


def test_distinct_successful_transactions_share_protected_roots(tmp_path: Path) -> None:
    """Finalize transaction A before admitting and promoting transaction B."""
    state, applied_a = _applied(tmp_path, "runner-lkg-a")
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    committed_a = _evaluate(state, root, applied_a, ledger).transaction

    plan_b = TransactionPlan(
        transaction_id="runner-lkg-b",
        candidate_revision="4" * 40,
        candidate_capsule_sha256="5" * 64,
        candidate_manifest_sha256="6" * 64,
        retained_lkg_revision=committed_a.candidate_revision,
        retained_lkg_manifest_sha256=committed_a.candidate_manifest_sha256,
    )
    applied_b = _commit_local_transaction(
        state,
        plan_b,
        LocalConvergenceResult(True, True, True, True),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    committed_b = _evaluate(state, root, applied_b, ledger).transaction

    assert committed_b.stage is TransactionStage.RUNNER_COMMITTED
    assert ledger.revision == "4" * 40
    assert not (root / "wider-health.active.json").exists()
    assert (root / "wider-health.terminal.runner-lkg-a.json").is_file()
    assert (root / "wider-health.terminal.runner-lkg-b.json").is_file()


def test_fresh_same_desired_state_transaction_follows_finalized_transaction(
    tmp_path: Path,
) -> None:
    """Distinguish a fresh same-state transaction from retry of its predecessor."""
    state, applied_a = _applied(tmp_path, "same-state-a")
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    committed_a = _evaluate(state, root, applied_a, ledger).transaction
    plan_b = replace(
        _plan("same-state-b"),
        retained_lkg_revision=committed_a.candidate_revision,
        retained_lkg_manifest_sha256=committed_a.candidate_manifest_sha256,
    )
    applied_b = _commit_local_transaction(
        state,
        plan_b,
        LocalConvergenceResult(True, True, True, False),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )

    committed_b = _evaluate(state, root, applied_b, ledger).transaction

    assert committed_b.stage is TransactionStage.RUNNER_COMMITTED
    assert ledger.updates == 1


@pytest.mark.parametrize(
    "boundary",
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
def test_success_finalization_interruption_recovers_exact_transaction(
    tmp_path: Path, boundary: str
) -> None:
    """Finish forward only from a terminal record backed by the durable receipt/ref."""
    state, applied = _applied(tmp_path, f"finalize-{boundary}")
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)

    def interrupt(actual: str) -> None:
        if actual == boundary:
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _evaluate(state, root, applied, ledger, hook=interrupt)
    recovered = _evaluate(state, root, applied, ledger)
    assert recovered.transaction.stage is TransactionStage.RUNNER_COMMITTED
    assert ledger.updates == 1
    assert not (root / "wider-health.active.json").exists()


def test_mismatched_or_fabricated_apply_state_cannot_mutate_lkg(tmp_path: Path) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    forged = replace(applied, candidate_capsule_sha256="f" * 64)
    with pytest.raises(TrustError):
        _evaluate(state, root, forged, ledger)
    assert ledger.revision == "a" * 40
    assert {item.name for item in root.iterdir()} == {
        ".coordinator.lock",
    }


def test_same_revision_fresh_transaction_is_durably_recorded(tmp_path: Path) -> None:
    plan = replace(
        _plan("same-revision"),
        candidate_revision="a" * 40,
        candidate_manifest_sha256="b" * 64,
    )
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    applied = _commit_local_transaction(
        state,
        plan,
        LocalConvergenceResult(True, True, True, False),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    result = _evaluate(state, root, applied, ledger)
    assert result.transaction.stage is TransactionStage.RUNNER_COMMITTED
    assert ledger.revision == "a" * 40
    assert ledger.updates == 0


def test_same_revision_health_failure_returns_exact_recovery_plan(tmp_path: Path) -> None:
    """Retain LKG and report honest same-desired-state recovery after failed health."""
    plan = replace(
        _plan("same-revision-health-failure"),
        candidate_revision="a" * 40,
        candidate_manifest_sha256="b" * 64,
    )
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    applied = _commit_local_transaction(
        state,
        plan,
        LocalConvergenceResult(True, True, True, False),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)

    result = _evaluate(state, root, applied, ledger, succeeded=False)

    assert result.transaction.stage is TransactionStage.ROLLBACK_PLANNED
    assert result.rollback is not None
    assert result.rollback.from_revision == result.rollback.to_revision == "a" * 40
    assert result.rollback.from_manifest_sha256 == result.rollback.to_manifest_sha256 == "b" * 64
    assert result.rollback.reason == "wider-health-failed-same-desired-state-recovery"
    assert ledger.updates == 0


def test_failed_health_blocks_unrelated_transaction_until_rollback(tmp_path: Path) -> None:
    """Keep active failed-health authority exclusive until rollback is durable."""
    state, applied = _applied(tmp_path, "failed-active-a")
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    _evaluate(state, root, applied, Ledger("a" * 40), succeeded=False)
    unrelated = commit_apply_state(
        record_local_convergence(
            replace(_plan("unrelated-b"), candidate_revision="4" * 40),
            validations_succeeded=True,
            changed=True,
        )
    )
    with pytest.raises(TrustError, match="transaction-mismatched"):
        prepare_wider_health_challenge(
            root,
            unrelated,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_same_revision_interruption_recovers_without_ref_update(tmp_path: Path) -> None:
    plan = replace(
        _plan("same-revision-recovery"),
        candidate_revision="a" * 40,
        candidate_manifest_sha256="b" * 64,
    )
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    applied = _commit_local_transaction(
        state,
        plan,
        LocalConvergenceResult(True, True, True, False),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)

    def interrupt(boundary: str) -> None:
        if boundary == "ref-advanced":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _evaluate(state, root, applied, ledger, hook=interrupt)
    assert ledger.updates == 0
    recovered = _evaluate(state, root, applied, ledger)
    assert recovered.transaction.stage is TransactionStage.RUNNER_COMMITTED
    assert ledger.updates == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("retained_lkg_revision", "d" * 40), ("retained_lkg_manifest_sha256", "e" * 64)],
)
def test_retained_authority_tampering_invalidates_apply_evidence(
    tmp_path: Path, field: str, value: str
) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    forged = (
        replace(applied, retained_lkg_revision=value)
        if field == "retained_lkg_revision"
        else replace(applied, retained_lkg_manifest_sha256=value)
    )
    with pytest.raises(TrustError, match="fabricated or mismatched"):
        evaluate_wider_health(
            state,
            root,
            forged,
            Ledger(applied.retained_lkg_revision),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            health_timeout_seconds=0.05,
        )


def test_publication_verification_rejects_premature_or_stale_evidence(tmp_path: Path) -> None:
    state, applied = _applied(tmp_path)
    root = tmp_path / "lkg"
    root.mkdir(mode=0o700)
    ledger = Ledger("a" * 40)
    with pytest.raises(TrustError):
        verify_runner_lkg_commit(
            root,
            applied,
            ledger,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
    committed = _evaluate(state, root, applied, ledger).transaction
    ledger.revision = "f" * 40
    with pytest.raises(TrustError, match="verification failed"):
        verify_runner_lkg_commit(
            root,
            committed,
            ledger,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
