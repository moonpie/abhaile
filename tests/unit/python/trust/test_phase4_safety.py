"""Test repository-safe Phase 4 state and recovery mechanics."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.network_recovery import (
    NetworkRecovery,
    NetworkStage,
    advance_network,
    load_network_recovery,
    persist_network_snapshot,
    persist_network_transition,
    recover_network,
)
from abhaile.trust.prune import (
    ObjectIdentity,
    PruneClass,
    PruneDecision,
    authorize_prune,
    classify_prune,
    execute_authorized_prune,
    inspect_identity,
)
from abhaile.trust.runner_publication import (
    RunnerCandidates,
    _publish_runner_candidates,
    _recover_runner_publication,
    stage_runner_candidates,
)
from abhaile.trust.runner_lkg import (
    RunnerLkgReceipt,
    VerifiedRunnerLkgAuthority,
    _commit_runner_lkg_durably,
    _issue_runner_lkg_authority,
    prepare_wider_health_challenge,
    read_protected_health_evidence,
    runner_lkg_receipt_digest,
    write_protected_health_result,
)
from abhaile.trust.runner_update import (
    RunnerPublicationEvidence,
    RunnerUpdatePlan,
    RunnerUpdateStage,
    bind_runner_publication_evidence,
    plan_runner_update,
)
from abhaile.trust.state_store import (
    StateRecord,
    commit_local_apply_result,
    commit_state_record,
    recover_state_record,
)
from abhaile.trust.transaction import (
    TransactionPlan,
    TransactionStage,
    commit_apply_state,
    commit_runner_lkg,
    record_local_convergence,
    record_wider_health,
)


def _state_transaction(index: int) -> TransactionPlan:
    transaction = TransactionPlan(
        transaction_id=f"tx-{index}",
        candidate_revision=f"{index:x}" * 40,
        candidate_capsule_sha256=f"{index + 1:x}" * 64,
        candidate_manifest_sha256=f"{index + 2:x}" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )
    transaction = record_local_convergence(transaction, validations_succeeded=True, changed=True)
    return commit_apply_state(transaction)


def _same_desired_transaction(transaction_id: str) -> TransactionPlan:
    """Create fresh transaction evidence for unchanged desired-state identity."""
    transaction = TransactionPlan(
        transaction_id=transaction_id,
        candidate_revision="1" * 40,
        candidate_capsule_sha256="2" * 64,
        candidate_manifest_sha256="3" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )
    return commit_apply_state(
        record_local_convergence(transaction, validations_succeeded=True, changed=False)
    )


def _record(index: int) -> StateRecord:
    transaction = _state_transaction(index)
    assert transaction.apply_commit_evidence is not None
    return StateRecord(
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
        None,
        "changed",
    )


def test_state_store_rotates_and_bounds_durable_history(tmp_path: Path) -> None:
    """Retain exact current, previous, and bounded transaction records."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    for index in range(1, 5):
        commit_state_record(
            state,
            _state_transaction(index),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            keep_history=2,
        )
    assert recover_state_record(
        state, expected_uid=os.getuid(), expected_gid=os.getgid()
    ) == _record(4)
    previous = json.loads((state / "previous.json").read_text(encoding="utf-8"))
    assert previous["transaction_id"] == "tx-3"
    assert len(list((state / "history").iterdir())) == 2


def test_local_apply_result_commits_only_complete_success(tmp_path: Path) -> None:
    """Integrate convergence, validation, handlers, prune, and state publication."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    plan = TransactionPlan(
        transaction_id="tx-integrated",
        candidate_revision="1" * 40,
        candidate_capsule_sha256="2" * 64,
        candidate_manifest_sha256="3" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )
    committed = commit_local_apply_result(
        state,
        plan,
        convergence_succeeded=True,
        validations_succeeded=True,
        handlers_succeeded=True,
        prune_succeeded=True,
        changed=True,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert committed.stage is TransactionStage.APPLY_COMMITTED
    assert recover_state_record(
        state, expected_uid=os.getuid(), expected_gid=os.getgid()
    ) == StateRecord(
        committed.transaction_id,
        committed.candidate_revision,
        committed.candidate_capsule_sha256,
        committed.candidate_manifest_sha256,
        committed.apply_commit_evidence or "",
        None,
        "changed",
    )


@pytest.mark.parametrize(
    "failed_boundary",
    ["convergence_succeeded", "validations_succeeded", "handlers_succeeded", "prune_succeeded"],
)
def test_local_apply_result_failure_and_dry_run_write_nothing(
    tmp_path: Path, failed_boundary: str
) -> None:
    """Keep the ledger untouched for every failed local boundary and dry-run."""
    state = tmp_path / failed_boundary
    state.mkdir(mode=0o700)
    values = {
        "convergence_succeeded": True,
        "validations_succeeded": True,
        "handlers_succeeded": True,
        "prune_succeeded": True,
    }
    values[failed_boundary] = False
    plan = TransactionPlan(
        transaction_id=f"tx-{failed_boundary}",
        candidate_revision="1" * 40,
        candidate_capsule_sha256="2" * 64,
        candidate_manifest_sha256="3" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )
    with pytest.raises(TrustError, match="cannot authorize"):
        commit_local_apply_result(
            state,
            plan,
            convergence_succeeded=values["convergence_succeeded"],
            validations_succeeded=values["validations_succeeded"],
            handlers_succeeded=values["handlers_succeeded"],
            prune_succeeded=values["prune_succeeded"],
            changed=True,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
    assert list(state.iterdir()) == []

    dry_state = tmp_path / f"dry-{failed_boundary}"
    dry_state.mkdir(mode=0o700)
    with pytest.raises(TrustError, match="apply gate"):
        commit_local_apply_result(
            dry_state,
            replace(plan, dry_run=True),
            convergence_succeeded=True,
            validations_succeeded=True,
            handlers_succeeded=True,
            prune_succeeded=True,
            changed=False,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
    assert list(dry_state.iterdir()) == []


@pytest.mark.parametrize("unsafe", ["symlink", "mode"])
def test_state_store_rejects_unsafe_root(tmp_path: Path, unsafe: str) -> None:
    """Reject linked or group-writable protected state roots."""
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    root = tmp_path / "state"
    if unsafe == "symlink":
        root.symlink_to(target, target_is_directory=True)
    else:
        root.mkdir(mode=0o770)
        root.chmod(0o770)
    with pytest.raises(TrustError):
        commit_state_record(
            root, _state_transaction(1), expected_uid=os.getuid(), expected_gid=os.getgid()
        )


def test_state_store_ignores_interrupted_pending_record(tmp_path: Path) -> None:
    """Recover only the last renamed record after an interrupted write."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    commit_state_record(
        state, _state_transaction(1), expected_uid=os.getuid(), expected_gid=os.getgid()
    )
    (state / ".current.json.pending").write_text("partial", encoding="utf-8")
    assert recover_state_record(
        state, expected_uid=os.getuid(), expected_gid=os.getgid()
    ) == _record(1)


def test_state_store_rejects_unsafe_existing_history(tmp_path: Path) -> None:
    """Do not enumerate a linked or writable history directory."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    history = state / "history"
    history.mkdir(mode=0o700)
    history.chmod(0o770)
    with pytest.raises(TrustError, match="history"):
        commit_state_record(
            state, _state_transaction(1), expected_uid=os.getuid(), expected_gid=os.getgid()
        )


@pytest.mark.parametrize("failure_stage", ["previous-written", "history-written"])
def test_state_journal_recovers_prior_record_before_current_publication(
    tmp_path: Path, failure_stage: str
) -> None:
    """Finish the transaction forward when rotation stops before publication."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    commit_state_record(
        state, _state_transaction(1), expected_uid=os.getuid(), expected_gid=os.getgid()
    )

    def fail(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError("injected state failure")

    with pytest.raises(RuntimeError, match="injected"):
        commit_state_record(
            state,
            _state_transaction(2),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            failure_hook=fail,
        )
    assert (state / "transaction.journal.json").is_file()
    assert recover_state_record(
        state, expected_uid=os.getuid(), expected_gid=os.getgid()
    ) == _record(2)
    assert not (state / "transaction.journal.json").exists()


def test_state_journal_recovers_published_candidate_after_current_transition(
    tmp_path: Path,
) -> None:
    """Recognize the candidate only after its current record is durably published."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    commit_state_record(
        state, _state_transaction(1), expected_uid=os.getuid(), expected_gid=os.getgid()
    )

    def fail(stage: str) -> None:
        if stage == "current-written":
            raise RuntimeError("injected state failure")

    with pytest.raises(RuntimeError, match="injected"):
        commit_state_record(
            state,
            _state_transaction(2),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            failure_hook=fail,
        )
    assert recover_state_record(
        state, expected_uid=os.getuid(), expected_gid=os.getgid()
    ) == _record(2)


@pytest.mark.parametrize(
    "failure_stage",
    [
        "before-previous-write",
        "after-previous-write",
        "before-history-write",
        "after-history-write",
        "before-current-write",
        "after-current-write",
        "before-history-prune",
        "after-history-prune",
        "before-commit-journal",
        "after-commit-journal",
        "before-journal-unlink",
        "after-journal-unlink",
    ],
)
def test_state_rotation_gap_recovery_finishes_one_complete_tuple(
    tmp_path: Path, failure_stage: str
) -> None:
    """Finish forward without duplicate history from every injected write gap."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    commit_state_record(
        state, _state_transaction(1), expected_uid=os.getuid(), expected_gid=os.getgid()
    )

    def fail(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError("injected rotation gap")

    with pytest.raises(RuntimeError, match="injected"):
        commit_state_record(
            state,
            _state_transaction(2),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            failure_hook=fail,
        )
    assert recover_state_record(
        state, expected_uid=os.getuid(), expected_gid=os.getgid()
    ) == _record(2)
    assert json.loads((state / "previous.json").read_text())["transaction_id"] == "tx-1"
    history = list((state / "history").glob("*.json"))
    assert len(history) == 1
    assert json.loads(history[0].read_text())["transaction_id"] == "tx-1"


@pytest.mark.parametrize(
    "desired,prior,live,expected",
    [
        (True, None, None, PruneClass.DESIRED),
        (False, ObjectIdentity("file", "a", 1, 1, 0o600), None, PruneClass.ALREADY_ABSENT),
        (
            False,
            ObjectIdentity("file", "a", 1, 1, 0o600),
            ObjectIdentity("file", "a", 1, 1, 0o600),
            PruneClass.EXACT_PRIOR,
        ),
        (
            False,
            ObjectIdentity("file", "a", 1, 1, 0o600),
            ObjectIdentity("file", "b", 1, 1, 0o600),
            PruneClass.DRIFTED,
        ),
        (False, None, ObjectIdentity("file", "b", 1, 1, 0o600), PruneClass.UNKNOWN),
    ],
)
def test_prune_classification(
    desired: bool,
    prior: ObjectIdentity | None,
    live: ObjectIdentity | None,
    expected: PruneClass,
) -> None:
    """Distinguish desired, absent, prior-owned, drifted, and unmanaged state."""
    assert classify_prune(desired=desired, prior=prior, live=live) is expected


@pytest.mark.parametrize(
    "change",
    [
        {"uid": 2},
        {"gid": 2},
        {"mode": 0o644},
        {"kind": "symlink", "sha256": None},
    ],
)
def test_prune_treats_metadata_and_type_changes_as_drift(change: dict[str, Any]) -> None:
    """Treat changed ownership, mode, and no-follow object type as drift."""
    prior = ObjectIdentity("file", "a", 1, 1, 0o600)
    live = ObjectIdentity(**{**prior.__dict__, **change})
    assert classify_prune(desired=False, prior=prior, live=live) is PruneClass.DRIFTED


def test_prune_inspection_does_not_follow_symlinks(tmp_path: Path) -> None:
    """Report a link itself rather than hashing its target."""
    target = tmp_path / "target"
    target.write_text("managed", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    identity = inspect_identity(tmp_path, "link")
    assert identity is not None and identity.kind == "symlink" and identity.sha256 is None


def test_prune_inspection_rejects_linked_parent(tmp_path: Path) -> None:
    """Require descriptor-relative traversal beneath the trusted root."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "managed").write_text("content", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(TrustError, match="ancestry"):
        inspect_identity(root, "linked/managed")


def test_authorized_prune_revalidates_and_removes_exact_file(tmp_path: Path) -> None:
    """Remove only the exact descriptor-inspected managed file."""
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    target = root / "managed"
    target.write_text("managed", encoding="utf-8")
    live = inspect_identity(root, "managed")
    assert live is not None
    decision = authorize_prune(PruneClass.EXACT_PRIOR, prune=True, destructive=False)
    assert execute_authorized_prune(
        root,
        "managed",
        prior=live,
        authorized_live=live,
        decision=decision,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        dry_run=False,
    )
    assert not target.exists()
    assert not execute_authorized_prune(
        root,
        "managed",
        prior=live,
        authorized_live=live,
        decision=decision,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        dry_run=False,
    )


def test_authorized_prune_dry_run_and_changed_target_do_not_mutate(tmp_path: Path) -> None:
    """Keep dry-run inert and reject identity drift after authorization."""
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    target = root / "managed"
    target.write_text("managed", encoding="utf-8")
    live = inspect_identity(root, "managed")
    assert live is not None
    decision = authorize_prune(PruneClass.EXACT_PRIOR, prune=True, destructive=False)
    assert execute_authorized_prune(
        root,
        "managed",
        prior=live,
        authorized_live=live,
        decision=decision,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        dry_run=True,
    )
    target.write_text("drift", encoding="utf-8")
    with pytest.raises(TrustError, match="changed after authorization"):
        execute_authorized_prune(
            root,
            "managed",
            prior=live,
            authorized_live=live,
            decision=decision,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            dry_run=False,
        )
    assert target.exists()


def test_authorized_prune_rejects_symlinks_and_incomplete_gates(tmp_path: Path) -> None:
    """Never execute linked removal or a decision awaiting another approval."""
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "target").write_text("managed", encoding="utf-8")
    (root / "link").symlink_to("target")
    linked = inspect_identity(root, "link")
    assert linked is not None
    with pytest.raises(TrustError, match="linked or unsupported"):
        execute_authorized_prune(
            root,
            "link",
            prior=linked,
            authorized_live=linked,
            decision=PruneDecision(PruneClass.EXACT_PRIOR, True, "authorized"),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            dry_run=False,
        )
    with pytest.raises(TrustError, match="approval"):
        execute_authorized_prune(
            root,
            "target",
            prior=inspect_identity(root, "target"),  # type: ignore[arg-type]
            authorized_live=inspect_identity(root, "target"),  # type: ignore[arg-type]
            decision=PruneDecision(PruneClass.EXACT_PRIOR, False, "network"),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            dry_run=False,
        )


def test_state_store_rejects_fabricated_record_input(tmp_path: Path) -> None:
    """Accept only transaction-derived evidence at the commit boundary."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    with pytest.raises(TrustError):
        commit_state_record(
            state,
            _record(1),  # type: ignore[arg-type]
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_state_store_rejects_fabricated_transaction_evidence(tmp_path: Path) -> None:
    """Recompute commit evidence rather than trusting dataclass fields."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    fabricated = TransactionPlan(
        transaction_id="tx-fabricated",
        candidate_revision="a" * 40,
        candidate_capsule_sha256="b" * 64,
        candidate_manifest_sha256="c" * 64,
        retained_lkg_revision="d" * 40,
        retained_lkg_manifest_sha256="e" * 64,
        stage=TransactionStage.APPLY_COMMITTED,
        apply_commit_evidence="f" * 64,
    )
    with pytest.raises(TrustError, match="fabricated"):
        commit_state_record(
            state,
            fabricated,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_state_store_accepts_only_exact_apply_commit_and_rejects_replay(
    tmp_path: Path,
) -> None:
    """Keep applied state separate from runner LKG and reject old evidence."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    transaction = _state_transaction(1)
    commit_state_record(state, transaction, expected_uid=os.getuid(), expected_gid=os.getgid())
    with pytest.raises(TrustError, match="stale or replayed"):
        commit_state_record(state, transaction, expected_uid=os.getuid(), expected_gid=os.getgid())
    healthy = record_wider_health(transaction, succeeded=True)
    with pytest.raises(TrustError, match="durable"):
        commit_state_record(state, healthy, expected_uid=os.getuid(), expected_gid=os.getgid())


def test_state_store_accepts_fresh_same_revision_reconciliation(tmp_path: Path) -> None:
    """Distinguish fresh no-op and drift-repair without inventing a revision change."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    base = TransactionPlan(
        transaction_id="tx-same-1",
        candidate_revision="1" * 40,
        candidate_capsule_sha256="2" * 64,
        candidate_manifest_sha256="3" * 64,
        retained_lkg_revision="a" * 40,
        retained_lkg_manifest_sha256="b" * 64,
    )
    first = commit_local_apply_result(
        state,
        base,
        convergence_succeeded=True,
        validations_succeeded=True,
        handlers_succeeded=True,
        prune_succeeded=True,
        changed=False,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    second = commit_local_apply_result(
        state,
        replace(base, transaction_id="tx-same-2"),
        convergence_succeeded=True,
        validations_succeeded=True,
        handlers_succeeded=True,
        prune_succeeded=True,
        changed=True,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    recovered = recover_state_record(state, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert recovered is not None
    assert recovered.transaction_id == "tx-same-2"
    assert recovered.candidate_revision == first.candidate_revision
    assert recovered.manifest_sha256 == second.candidate_manifest_sha256
    assert recovered.convergence_outcome == "changed"
    previous = StateRecord(**json.loads((state / "previous.json").read_text()))
    assert previous.convergence_outcome == "no-op"


def test_state_replay_authority_survives_diagnostic_history_pruning(tmp_path: Path) -> None:
    """Never expire transaction/evidence replay protection with bounded history."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    oldest = _state_transaction(1)
    for transaction in (oldest, _state_transaction(2), _state_transaction(3)):
        commit_state_record(
            state,
            transaction,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            keep_history=1,
        )
    assert all(
        json.loads(path.read_text())["transaction_id"] != oldest.transaction_id
        for path in (state / "history").iterdir()
    )
    with pytest.raises(TrustError, match="stale or replayed"):
        commit_state_record(
            state,
            oldest,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            keep_history=1,
        )


@pytest.mark.parametrize("unsafe", ["symlink", "mode"])
def test_state_replay_authority_rejects_unsafe_ancestry(tmp_path: Path, unsafe: str) -> None:
    """Never follow or trust unsafe replay-marker directory ancestry."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    if unsafe == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir(mode=0o700)
        (state / "replay").symlink_to(outside, target_is_directory=True)
    else:
        (state / "replay").mkdir(mode=0o700)
        (state / "replay").chmod(0o770)
    with pytest.raises(TrustError, match="replay directory"):
        commit_state_record(
            state,
            _state_transaction(1),
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_state_record_rejects_unbound_outcome(tmp_path: Path) -> None:
    """Accept only evidence-bound changed or no-op outcomes."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    record = _record(1)
    value = {**record.__dict__, "convergence_outcome": "fabricated"}
    (state / "current.json").write_text(json.dumps(value), encoding="utf-8")
    (state / "current.json").chmod(0o600)
    with pytest.raises(TrustError, match="identity"):
        recover_state_record(state, expected_uid=os.getuid(), expected_gid=os.getgid())


def test_state_store_rejects_reused_evidence_under_another_transaction(tmp_path: Path) -> None:
    """Reject reused apply evidence even when a stored transaction identifier differs."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    candidate = _same_desired_transaction("tx-evidence-candidate")
    assert candidate.apply_commit_evidence is not None
    forged_prior = StateRecord(
        "tx-other",
        "4" * 40,
        "5" * 64,
        "6" * 64,
        candidate.apply_commit_evidence,
        None,
        "changed",
    )
    (state / "current.json").write_text(
        json.dumps(forged_prior.__dict__, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (state / "current.json").chmod(0o600)
    with pytest.raises(TrustError, match="stale or replayed"):
        commit_state_record(state, candidate, expected_uid=os.getuid(), expected_gid=os.getgid())


def test_state_store_dry_run_advances_no_state(tmp_path: Path) -> None:
    """Reject dry-run evidence before writing any protected ledger artifact."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    dry_run = replace(_network_transaction(), dry_run=True)
    with pytest.raises(TrustError, match="durable"):
        commit_state_record(state, dry_run, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert list(state.iterdir()) == []


def test_state_store_retries_same_transaction_after_interruption(tmp_path: Path) -> None:
    """Finish forward when the exact interrupted transaction is retried."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    transaction = _state_transaction(1)

    def fail(stage: str) -> None:
        if stage == "after-current-write":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        commit_state_record(
            state,
            transaction,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            failure_hook=fail,
        )
    commit_state_record(state, transaction, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert recover_state_record(
        state, expected_uid=os.getuid(), expected_gid=os.getgid()
    ) == _record(1)


def test_prune_uses_separate_destructive_network_and_volume_gates() -> None:
    """Never infer specialized deletion approval from general destructive approval."""
    assert not authorize_prune(PruneClass.DRIFTED, prune=True, destructive=False).remove
    assert (
        authorize_prune(PruneClass.DRIFTED, prune=True, destructive=True, network=True).gate
        == "network"
    )
    assert (
        authorize_prune(PruneClass.EXACT_PRIOR, prune=True, destructive=False, volume=True).gate
        == "volume"
    )
    assert authorize_prune(
        PruneClass.DRIFTED,
        prune=True,
        destructive=True,
        network=True,
        volume=True,
        network_approved=True,
        volume_approved=True,
    ).remove
    with pytest.raises(TrustError, match="Unmanaged"):
        authorize_prune(PruneClass.UNKNOWN, prune=True, destructive=True)


def test_network_requires_snapshot_timer_reachability_and_confirmation() -> None:
    """Keep the revert armed until explicit post-reachability confirmation."""
    plan = NetworkRecovery("a" * 64, "b" * 64, "token", False, False)
    for action in (
        "record-protected-snapshot",
        "arm-independent-revert",
        "apply-candidate",
        "verify-reachability",
        "confirm-and-cancel-revert",
    ):
        plan = advance_network(plan, action)
    assert plan.stage is NetworkStage.CONFIRMED
    with pytest.raises(TrustError):
        recover_network(plan, token="token")


def test_network_interruption_reverts_and_deletion_is_separate() -> None:
    """Permit exact-token recovery while refusing unapproved deletion."""
    plan = NetworkRecovery("a" * 64, "b" * 64, "token", True, False)
    plan = advance_network(plan, "record-protected-snapshot")
    plan = advance_network(plan, "arm-independent-revert")
    with pytest.raises(TrustError, match="deletion"):
        advance_network(plan, "apply-candidate")
    assert recover_network(plan, token="token").stage is NetworkStage.REVERTED
    with pytest.raises(TrustError):
        recover_network(plan, token="wrong")


def test_network_recovery_journal_persists_snapshot_reachability_and_confirmation(
    tmp_path: Path,
) -> None:
    """Persist repository-only evidence without exposing a network mutation callback."""
    snapshot = b"network snapshot"
    candidate = b"network candidate"
    transaction = _network_transaction()
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"
    persisted = persist_network_snapshot(root, transaction, snapshot, candidate, plan)
    persisted = persist_network_transition(
        root, persisted, "arm-independent-revert", transaction=transaction
    )
    persisted = persist_network_transition(
        root, persisted, "apply-candidate", transaction=transaction
    )
    persisted = persist_network_transition(
        root,
        persisted,
        "verify-reachability",
        transaction=transaction,
        evidence=b"reachable-from-vlan",
    )
    persisted = persist_network_transition(
        root,
        persisted,
        "confirm-and-cancel-revert",
        transaction=transaction,
        evidence=b"operator-confirmed",
    )
    assert persisted.plan.stage is NetworkStage.CONFIRMED
    assert persisted.reachability_sha256 is not None
    assert persisted.confirmation_sha256 is not None
    assert load_network_recovery(root) == persisted


def test_network_recovery_journal_rejects_tampered_snapshot(tmp_path: Path) -> None:
    """Fail closed when persisted snapshot bytes no longer match the journal."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"
    persist_network_snapshot(root, _network_transaction(), snapshot, candidate, plan)
    (root / "snapshot.bin").write_bytes(b"tampered")
    with pytest.raises(TrustError, match="snapshot identity"):
        load_network_recovery(root)


def test_network_initialization_rejects_stage_predating_authority(tmp_path: Path) -> None:
    """Do not adopt an arbitrary owner/mode-correct private staging directory."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    transaction = _network_transaction()
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"
    staging = tmp_path / f".{root.name}.{transaction.transaction_id}.pending"
    staging.mkdir(mode=0o700)
    with pytest.raises(TrustError, match="predates initialization authority"):
        persist_network_snapshot(root, transaction, snapshot, candidate, plan)


def test_network_recovery_rejects_tampered_candidate_and_stale_transaction(
    tmp_path: Path,
) -> None:
    """Bind candidate bytes and every transition to one immutable transaction."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    transaction = _network_transaction()
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"
    persisted = persist_network_snapshot(root, transaction, snapshot, candidate, plan)
    stale = replace(transaction, candidate_manifest_sha256="9" * 64)
    with pytest.raises(TrustError, match="stale or mismatched"):
        persist_network_transition(root, persisted, "arm-independent-revert", transaction=stale)
    (root / "candidate.bin").write_bytes(b"tampered")
    with pytest.raises(TrustError, match="candidate identity"):
        load_network_recovery(root)


def test_network_recovery_rejects_unsafe_evidence_metadata(tmp_path: Path) -> None:
    """Require protected ownership and mode on every persisted evidence file."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"
    persist_network_snapshot(root, _network_transaction(), snapshot, candidate, plan)
    (root / "candidate.bin").chmod(0o640)
    with pytest.raises(TrustError, match="unsafe type"):
        load_network_recovery(root)


@pytest.mark.parametrize(
    "failure_stage",
    [
        "before-initialization-journal",
        "after-initialization-journal",
        "before-directory-creation",
        "after-directory-creation",
        "before-snapshot-write",
        "after-snapshot-write",
        "before-candidate-write",
        "after-candidate-write",
        "before-initial-journal-write",
        "after-initial-journal-write",
        "before-directory-fsync-publication",
        "after-directory-fsync-publication",
    ],
)
def test_network_initialization_retries_every_durable_gap(
    tmp_path: Path, failure_stage: str
) -> None:
    """Finish the exact initialization safely after every injected interruption."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    transaction = _network_transaction()
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"

    def fail(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError("injected network initialization failure")

    with pytest.raises(RuntimeError, match="injected"):
        persist_network_snapshot(root, transaction, snapshot, candidate, plan, failure_hook=fail)
    expected = persist_network_snapshot(root, transaction, snapshot, candidate, plan)
    assert load_network_recovery(root) == expected
    assert not list(tmp_path.glob(".network-recovery.*"))


def test_network_initialization_rejects_malformed_partial_state(tmp_path: Path) -> None:
    """Retain and reject an ambiguous staged artifact instead of deleting it."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    transaction = _network_transaction()
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"

    def fail(stage: str) -> None:
        if stage == "after-snapshot-write":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        persist_network_snapshot(root, transaction, snapshot, candidate, plan, failure_hook=fail)
    staging = next(tmp_path.glob(".network-recovery.*.pending"))
    (staging / "snapshot.bin").write_bytes(b"tampered")
    with pytest.raises(TrustError, match="mismatched"):
        persist_network_snapshot(root, transaction, snapshot, candidate, plan)
    assert staging.exists()


def test_network_initialization_rejects_symlinked_staging_directory(tmp_path: Path) -> None:
    """Never follow a substituted staging directory during retry."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    transaction = _network_transaction()
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"

    def fail(stage: str) -> None:
        if stage == "after-initialization-journal":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        persist_network_snapshot(root, transaction, snapshot, candidate, plan, failure_hook=fail)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    staging = tmp_path / ".network-recovery.tx-network.pending"
    staging.symlink_to(outside, target_is_directory=True)
    with pytest.raises(TrustError):
        persist_network_snapshot(root, transaction, snapshot, candidate, plan)


def test_network_initialization_rejects_transaction_mismatch(tmp_path: Path) -> None:
    """Do not resume initialization using a different transaction identity."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"

    def fail(stage: str) -> None:
        if stage == "after-initialization-journal":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        persist_network_snapshot(
            root, _network_transaction(), snapshot, candidate, plan, failure_hook=fail
        )
    stale = replace(_network_transaction(), transaction_id="tx-network-other")
    with pytest.raises(TrustError, match="transaction-mismatched"):
        persist_network_snapshot(root, stale, snapshot, candidate, plan)


def test_network_dry_run_creates_no_recovery_state(tmp_path: Path) -> None:
    """Reject dry-run initialization before creating parent evidence."""
    snapshot = b"snapshot"
    candidate = b"candidate"
    plan = NetworkRecovery(
        hashlib.sha256(snapshot).hexdigest(),
        hashlib.sha256(candidate).hexdigest(),
        "token",
        False,
        False,
    )
    root = tmp_path / "network-recovery"
    with pytest.raises(TrustError, match="planned mutating"):
        persist_network_snapshot(
            root, replace(_network_transaction(), dry_run=True), snapshot, candidate, plan
        )
    assert list(tmp_path.iterdir()) == []


def _network_transaction() -> TransactionPlan:
    """Create the exact planned transaction accepted before network mutation."""
    return TransactionPlan(
        transaction_id="tx-network",
        candidate_revision="1" * 40,
        candidate_capsule_sha256="2" * 64,
        candidate_manifest_sha256="3" * 64,
        retained_lkg_revision="4" * 40,
        retained_lkg_manifest_sha256="5" * 64,
    )


def _runner_plan(service: bytes, timer: bytes) -> RunnerUpdatePlan:
    recovery = json.dumps(
        {
            "transaction_id": "tx-1",
            "service_sha256": hashlib.sha256(service).hexdigest(),
            "timer_sha256": hashlib.sha256(timer).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    plan = plan_runner_update(
        lock_device=2,
        lock_inode=3,
        service_changed=True,
        timer_changed=True,
        transaction_id="tx-1",
        candidate_revision="a" * 40,
        candidate_capsule_sha256="b" * 64,
        candidate_manifest_sha256="c" * 64,
        service_sha256=hashlib.sha256(service).hexdigest(),
        timer_sha256=hashlib.sha256(timer).hexdigest(),
        recovery_record_sha256=hashlib.sha256(recovery).hexdigest(),
    )
    return replace(plan, stage=RunnerUpdateStage.STAGED)


def _transaction() -> TransactionPlan:
    transaction = TransactionPlan(
        transaction_id="tx-1",
        candidate_revision="a" * 40,
        candidate_capsule_sha256="b" * 64,
        candidate_manifest_sha256="c" * 64,
        retained_lkg_revision="d" * 40,
        retained_lkg_manifest_sha256="e" * 64,
    )
    transaction = record_local_convergence(transaction, validations_succeeded=True, changed=True)
    transaction = commit_apply_state(transaction)
    transaction = record_wider_health(transaction, succeeded=True)
    return commit_runner_lkg(transaction)


def _evidence(plan: RunnerUpdatePlan) -> RunnerPublicationEvidence:
    return bind_runner_publication_evidence(
        _transaction(), plan, durable_runner_lkg_receipt_sha256=_receipt_sha256()
    )


class _TestLedger:
    def __init__(self, revision: str) -> None:
        self.revision = revision

    def last_known_good(self) -> str:
        return self.revision

    def advance_last_known_good(self, revision: str, *, expected: str | None) -> None:
        assert self.revision == expected
        self.revision = revision


def _health_digest(transaction: TransactionPlan) -> str:
    observations = (("wider-host-health", True),)
    observations_sha256 = hashlib.sha256(
        (json.dumps(observations, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    payload = (
        json.dumps(
            {
                "transaction_id": transaction.transaction_id,
                "candidate_revision": transaction.candidate_revision,
                "capsule_sha256": transaction.candidate_capsule_sha256,
                "manifest_sha256": transaction.candidate_manifest_sha256,
                "observations_sha256": observations_sha256,
                "succeeded": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _receipt_sha256() -> str:
    transaction = _transaction()
    assert transaction.apply_commit_evidence is not None
    assert transaction.runner_lkg_commit_evidence is not None
    return runner_lkg_receipt_digest(
        RunnerLkgReceipt(
            transaction.transaction_id,
            transaction.candidate_revision,
            transaction.candidate_capsule_sha256,
            transaction.candidate_manifest_sha256,
            transaction.apply_commit_evidence,
            transaction.runner_lkg_commit_evidence,
            transaction.retained_lkg_revision,
            transaction.retained_lkg_manifest_sha256,
            _health_digest(transaction),
        )
    )


def _authority(tmp_path: Path) -> VerifiedRunnerLkgAuthority:
    """Obtain publication authority through real durable verification."""
    state = tmp_path / "authority-state"
    lkg = tmp_path / "authority-lkg"
    state.mkdir(mode=0o700, exist_ok=True)
    lkg.mkdir(mode=0o700, exist_ok=True)
    committed = _transaction()
    applied = replace(
        committed,
        stage=TransactionStage.APPLY_COMMITTED,
        runner_lkg_commit_evidence=None,
    )
    if not (state / "current.json").exists():
        commit_state_record(state, applied, expected_uid=os.getuid(), expected_gid=os.getgid())
    ledger = _TestLedger(
        committed.candidate_revision
        if (lkg / "runner-lkg.current.json").exists()
        else committed.retained_lkg_revision
    )
    healthy = replace(applied, stage=TransactionStage.HEALTHY)
    prepare_wider_health_challenge(lkg, applied, expected_uid=os.getuid(), expected_gid=os.getgid())
    write_protected_health_result(
        lkg,
        applied,
        (("wider-host-health", True),),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    health = read_protected_health_evidence(
        lkg, applied, expected_uid=os.getuid(), expected_gid=os.getgid()
    )
    durable = _commit_runner_lkg_durably(
        lkg,
        state,
        healthy,
        ledger,
        health,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    return _issue_runner_lkg_authority(
        lkg,
        durable,
        ledger,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def test_runner_publication_stages_validated_pair_then_reloads_and_rearms(tmp_path: Path) -> None:
    """Publish only a validated exact pair under the unchanged lock identity."""
    candidates = RunnerCandidates(b"[Service]\n", b"[Timer]\n")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: bool(value))
    effects: list[str] = []
    _publish_runner_candidates(
        stage,
        tmp_path / "units",
        _transaction(),
        plan,
        _evidence(plan),
        _authority(tmp_path),
        lock_device=2,
        lock_inode=3,
        dry_run=False,
        reload_manager=lambda: effects.append("reload"),
        rearm_timer=lambda: effects.append("rearm"),
    )
    assert effects == ["reload", "rearm"]
    assert (tmp_path / "units/runner.service").read_bytes() == candidates.service


@pytest.mark.parametrize("dry_run,lock_inode", [(True, 3), (False, 4)])
def test_runner_publication_rejects_preview_and_replaced_lock(
    tmp_path: Path, dry_run: bool, lock_inode: int
) -> None:
    """Perform no publication or manager effects without both safety gates."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)
    with pytest.raises(TrustError):
        _publish_runner_candidates(
            stage,
            tmp_path / "units",
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=lock_inode,
            dry_run=dry_run,
            reload_manager=lambda: pytest.fail("must not reload"),
            rearm_timer=lambda: pytest.fail("must not rearm"),
        )
    assert not (tmp_path / "units").exists()


def test_runner_publication_rejects_tampered_staged_unit(tmp_path: Path) -> None:
    """Refuse a staged artifact changed after candidate validation."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)
    (stage / "runner.timer").write_bytes(b"tampered")
    with pytest.raises(TrustError, match="digest"):
        _publish_runner_candidates(
            stage,
            tmp_path / "units",
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: None,
            rearm_timer=lambda: None,
        )


def test_runner_publication_rejects_unsafe_staged_metadata(tmp_path: Path) -> None:
    """Validate private metadata through the same descriptor used for content."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)
    (stage / "runner.timer").chmod(0o640)
    with pytest.raises(TrustError, match="unsafe metadata"):
        _publish_runner_candidates(
            stage,
            tmp_path / "units",
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: pytest.fail("must not reload"),
            rearm_timer=lambda: pytest.fail("must not rearm"),
        )
    assert not (tmp_path / "units").exists()


def test_runner_publication_rejects_fabricated_and_replayed_evidence(tmp_path: Path) -> None:
    """Require exact Phase 3 transaction evidence before any filesystem write."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)
    evidence = replace(_evidence(plan), apply_commit_evidence="f" * 64)
    with pytest.raises(TrustError, match="stale, replayed, or mismatched"):
        _publish_runner_candidates(
            stage,
            tmp_path / "units",
            _transaction(),
            plan,
            evidence,
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: pytest.fail("must not reload"),
            rearm_timer=lambda: pytest.fail("must not rearm"),
        )
    assert not (tmp_path / "units").exists()


def test_failed_runner_reload_retains_staged_recovery_and_does_not_rearm(
    tmp_path: Path,
) -> None:
    """Leave the protected recovery record available after manager reload failure."""
    candidates = RunnerCandidates(b"service", b"timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)

    def fail_reload() -> None:
        raise RuntimeError("injected reload failure")

    with pytest.raises(RuntimeError, match="injected"):
        _publish_runner_candidates(
            stage,
            tmp_path / "units",
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=fail_reload,
            rearm_timer=lambda: pytest.fail("must not rearm"),
        )
    assert (stage / "recovery.json").is_file()


def test_runner_journal_restores_prior_pair_after_partial_publication(tmp_path: Path) -> None:
    """Restore both prior units when interruption occurs after publishing only one."""
    candidates = RunnerCandidates(b"new service", b"new timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    units = tmp_path / "units"
    units.mkdir()
    (units / "runner.service").write_bytes(b"old service")
    (units / "runner.timer").write_bytes(b"old timer")
    (units / "runner.service").chmod(0o640)
    (units / "runner.timer").chmod(0o600)
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)

    def fail(stage_name: str) -> None:
        if stage_name == "service-published":
            raise RuntimeError("injected publication failure")

    with pytest.raises(RuntimeError, match="injected"):
        _publish_runner_candidates(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: pytest.fail("must not reload"),
            rearm_timer=lambda: pytest.fail("must not rearm"),
            failure_hook=fail,
        )
    effects: list[str] = []
    assert (
        _recover_runner_publication(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            reload_manager=lambda: effects.append("reload-prior"),
            rearm_timer=lambda: effects.append("unexpected-rearm"),
            rearm_idempotent=True,
        )
        == "restored-prior-pair"
    )
    assert effects == ["reload-prior"]
    assert (units / "runner.service").read_bytes() == b"old service"
    assert (units / "runner.timer").read_bytes() == b"old timer"
    assert (units / "runner.service").stat().st_mode & 0o777 == 0o640
    assert (units / "runner.timer").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure_stage", ["initializing", "after-prior-capture"])
def test_runner_prior_pair_initialization_is_recoverable(
    tmp_path: Path, failure_stage: str
) -> None:
    """Recover when interrupted before prior-pair authority reaches authorized state."""
    candidates = RunnerCandidates(b"new service", b"new timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    units = tmp_path / "units"
    units.mkdir()
    (units / "runner.service").write_bytes(b"old service")
    (units / "runner.timer").write_bytes(b"old timer")
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)

    def fail(stage_name: str) -> None:
        if stage_name == failure_stage:
            raise RuntimeError("injected initialization gap")

    with pytest.raises(RuntimeError, match="injected"):
        _publish_runner_candidates(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: pytest.fail("must not reload before recovery"),
            rearm_timer=lambda: pytest.fail("must not rearm"),
            failure_hook=fail,
        )
    assert (
        _recover_runner_publication(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            reload_manager=lambda: None,
            rearm_timer=lambda: None,
            rearm_idempotent=True,
        )
        == "restored-prior-pair"
    )
    assert (units / "runner.service").read_bytes() == b"old service"
    assert (units / "runner.timer").read_bytes() == b"old timer"


def test_runner_journal_completes_rearm_after_reload_interruption(tmp_path: Path) -> None:
    """Resume only the deferred timer effect when the published pair was reloaded."""
    candidates = RunnerCandidates(b"new service", b"new timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    units = tmp_path / "units"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)

    def fail(stage_name: str) -> None:
        if stage_name == "reloaded":
            raise RuntimeError("injected reload transition failure")

    with pytest.raises(RuntimeError, match="injected"):
        _publish_runner_candidates(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: None,
            rearm_timer=lambda: pytest.fail("must not rearm before recovery"),
            failure_hook=fail,
        )
    effects: list[str] = []
    assert (
        _recover_runner_publication(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            reload_manager=lambda: effects.append("unexpected-reload"),
            rearm_timer=lambda: effects.append("rearm"),
            rearm_idempotent=True,
        )
        == "completed-published-pair"
    )
    assert effects == ["rearm"]


@pytest.mark.parametrize(
    "failure_stage,expected",
    [
        ("after-service-replace", "restored-prior-pair"),
        ("after-timer-replace", "restored-prior-pair"),
        ("after-reload", "restored-prior-pair"),
        ("after-rearm", "completed-published-pair"),
    ],
)
def test_runner_transition_gap_recovery_is_safe(
    tmp_path: Path, failure_stage: str, expected: str
) -> None:
    """Restore prior state on ambiguity or repeat only an idempotent timer rearm."""
    candidates = RunnerCandidates(b"new service", b"new timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    units = tmp_path / "units"
    units.mkdir()
    (units / "runner.service").write_bytes(b"old service")
    (units / "runner.timer").write_bytes(b"old timer")
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)

    def fail(stage_name: str) -> None:
        if stage_name == failure_stage:
            raise RuntimeError("injected transition gap")

    with pytest.raises(RuntimeError, match="injected"):
        _publish_runner_candidates(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: None,
            rearm_timer=lambda: None,
            failure_hook=fail,
        )
    result = _recover_runner_publication(
        stage,
        units,
        _transaction(),
        plan,
        _evidence(plan),
        _authority(tmp_path),
        lock_device=2,
        lock_inode=3,
        reload_manager=lambda: None,
        rearm_timer=lambda: None,
        rearm_idempotent=True,
    )
    assert result == expected


def test_runner_recovery_reauthorizes_lock_and_evidence(tmp_path: Path) -> None:
    """Reject recovery before touching units when lock or commit evidence differs."""
    candidates = RunnerCandidates(b"new service", b"new timer")
    plan = _runner_plan(candidates.service, candidates.timer)
    stage = tmp_path / "stage"
    units = tmp_path / "units"
    stage_runner_candidates(stage, candidates, plan, validate=lambda kind, value: True)

    def fail(stage_name: str) -> None:
        if stage_name == "authorized":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        _publish_runner_candidates(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=3,
            dry_run=False,
            reload_manager=lambda: None,
            rearm_timer=lambda: None,
            failure_hook=fail,
        )
    with pytest.raises(TrustError, match="lock identity"):
        _recover_runner_publication(
            stage,
            units,
            _transaction(),
            plan,
            _evidence(plan),
            _authority(tmp_path),
            lock_device=2,
            lock_inode=99,
            reload_manager=lambda: pytest.fail("must not reload"),
            rearm_timer=lambda: pytest.fail("must not rearm"),
            rearm_idempotent=True,
        )
