"""Stage and publish transaction-authorized runner unit pairs safely."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from abhaile.trust.errors import TrustError
from abhaile.trust.runner_lkg import VerifiedRunnerLkgAuthority, validate_runner_lkg_authority
from abhaile.trust.runner_update import RunnerPublicationEvidence, RunnerUpdatePlan
from abhaile.trust.runner_update import authorize_runner_publication
from abhaile.trust.transaction import TransactionPlan


@dataclass(frozen=True)
class RunnerCandidates:
    """Carry validated runner service and timer bytes."""

    service: bytes
    timer: bytes


RUNNER_JOURNAL_VERSION = 1
RUNNER_TRANSITIONS = (
    "initializing",
    "authorized",
    "service-published",
    "pair-published",
    "reloaded",
    "rearmed",
    "committed",
)


def stage_runner_candidates(
    stage_root: Path,
    candidates: RunnerCandidates,
    plan: RunnerUpdatePlan,
    *,
    validate: Callable[[str, bytes], bool],
    failure_hook: Callable[[str], None] | None = None,
) -> None:
    """Validate both units and durably stage them with a recovery record."""
    if not validate("service", candidates.service) or not validate("timer", candidates.timer):
        raise TrustError("Runner unit candidate validation failed")
    if (
        _sha(candidates.service) != plan.service_sha256
        or _sha(candidates.timer) != plan.timer_sha256
    ):
        raise TrustError("Runner unit candidate digest is mismatched")
    recovery = json.dumps(
        {
            "transaction_id": plan.transaction_id,
            "service_sha256": plan.service_sha256,
            "timer_sha256": plan.timer_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if _sha(recovery) != plan.recovery_record_sha256:
        raise TrustError("Runner recovery record digest is mismatched")
    _persist_initial_stage(
        stage_root,
        candidates,
        plan,
        recovery,
        failure_hook,
    )


def _persist_initial_stage(
    stage_root: Path,
    candidates: RunnerCandidates,
    plan: RunnerUpdatePlan,
    recovery: bytes,
    failure_hook: Callable[[str], None] | None,
) -> None:
    """Finish or resume one transaction-bound atomic staging publication."""
    if (
        not stage_root.is_absolute()
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", stage_root.name) is None
    ):
        raise TrustError("Runner staging directory name is invalid")
    parent = stage_root.parent
    _verify_private_directory(parent)
    identity = _encode_staging_identity(stage_root.name, plan)
    identity_sha = _sha(identity)
    suffix = _sha(plan.transaction_id.encode())[:16]
    pending_name = f".{stage_root.name}.{suffix}.pending"
    authority_name = f".{stage_root.name}.initialization.json"
    authority = _encode_initialization_authority(stage_root.name, pending_name, identity_sha, plan)
    authority_path = parent / authority_name
    pending = parent / pending_name

    if stage_root.exists() or stage_root.is_symlink():
        _verify_initial_stage(stage_root, candidates, recovery, identity)
        _finish_staging_initialization(parent, authority_name, authority)
        return

    authority_exists = authority_path.exists() or authority_path.is_symlink()
    if (pending.exists() or pending.is_symlink()) and not authority_exists:
        raise TrustError("Runner candidate staging predates initialization authority")
    if authority_exists:
        if _read_private_regular(authority_path) != authority:
            raise TrustError("Runner staging initialization is transaction-mismatched")
    else:
        _inject_failure(failure_hook, "before-initialization-authority")
        _write_new(authority_path, authority)
        _sync_directory(parent)
        _inject_failure(failure_hook, "after-initialization-authority")

    if pending.exists() or pending.is_symlink():
        _verify_private_directory(pending)
    else:
        _inject_failure(failure_hook, "before-directory-creation")
        pending.mkdir(mode=0o700)
        _sync_directory(parent)
        _inject_failure(failure_hook, "after-directory-creation")

    _ensure_staging_file(
        pending / "runner.service", candidates.service, failure_hook, "service-write"
    )
    _ensure_staging_file(pending / "runner.timer", candidates.timer, failure_hook, "timer-write")
    _ensure_staging_file(pending / "recovery.json", recovery, failure_hook, "recovery-write")
    _ensure_staging_file(
        pending / "staging.identity.json", identity, failure_hook, "identity-write"
    )
    _inject_failure(failure_hook, "before-directory-fsync")
    _sync_directory(pending)
    _inject_failure(failure_hook, "after-directory-fsync")
    _inject_failure(failure_hook, "before-directory-publication")
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.rename(pending.name, stage_root.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    _sync_directory(parent)
    _inject_failure(failure_hook, "after-directory-publication")
    _finish_staging_initialization(parent, authority_name, authority)


def _ensure_staging_file(
    path: Path,
    payload: bytes,
    failure_hook: Callable[[str], None] | None,
    stage: str,
) -> None:
    """Create a staging artifact or verify the exact durable retry artifact."""
    if path.exists() or path.is_symlink():
        if _read_private_regular(path) != payload:
            raise TrustError(f"Runner {stage} artifact is mismatched")
        return
    _inject_failure(failure_hook, f"before-{stage}")
    _write_new(path, payload)
    _inject_failure(failure_hook, f"after-{stage}")


def _encode_staging_identity(final_name: str, plan: RunnerUpdatePlan) -> bytes:
    """Encode the complete immutable identity retained with staged candidates."""
    value = {
        "version": 1,
        "final_name": final_name,
        "transaction_id": plan.transaction_id,
        "candidate_revision": plan.candidate_revision,
        "candidate_capsule_sha256": plan.candidate_capsule_sha256,
        "candidate_manifest_sha256": plan.candidate_manifest_sha256,
        "service_sha256": plan.service_sha256,
        "timer_sha256": plan.timer_sha256,
        "recovery_record_sha256": plan.recovery_record_sha256,
        "lock_device": plan.lock_device,
        "lock_inode": plan.lock_inode,
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _encode_initialization_authority(
    final_name: str,
    pending_name: str,
    identity_sha256: str,
    plan: RunnerUpdatePlan,
) -> bytes:
    """Encode authority that must exist before a private staging directory."""
    value = {
        "version": 1,
        "final_name": final_name,
        "pending_name": pending_name,
        "transaction_id": plan.transaction_id,
        "identity_sha256": identity_sha256,
        "service_sha256": plan.service_sha256,
        "timer_sha256": plan.timer_sha256,
        "recovery_record_sha256": plan.recovery_record_sha256,
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _verify_initial_stage(
    root: Path,
    candidates: RunnerCandidates,
    recovery: bytes,
    identity: bytes,
) -> None:
    """Accept only an exact, complete, protected previously published stage."""
    _verify_private_directory(root)
    expected = {
        "runner.service": candidates.service,
        "runner.timer": candidates.timer,
        "recovery.json": recovery,
        "staging.identity.json": identity,
    }
    for name, payload in expected.items():
        if _read_private_regular(root / name) != payload:
            raise TrustError("Existing runner staging state is transaction-mismatched")


def _finish_staging_initialization(parent: Path, name: str, expected: bytes) -> None:
    """Remove only the exact initialization authority after atomic publication."""
    path = parent / name
    if not path.exists() and not path.is_symlink():
        return
    if _read_private_regular(path) != expected:
        raise TrustError("Runner staging initialization is transaction-mismatched")
    path.unlink()
    _sync_directory(parent)


def _publish_runner_candidates(
    stage_root: Path,
    unit_root: Path,
    transaction: TransactionPlan,
    plan: RunnerUpdatePlan,
    evidence: RunnerPublicationEvidence,
    authority: VerifiedRunnerLkgAuthority,
    *,
    lock_device: int,
    lock_inode: int,
    dry_run: bool,
    reload_manager: Callable[[], None],
    rearm_timer: Callable[[], None],
    failure_hook: Callable[[str], None] | None = None,
) -> None:
    """Publish the exact authorized pair without restarting the active runner."""
    if dry_run:
        raise TrustError("Dry-run cannot publish runner units")
    receipt_sha256 = validate_runner_lkg_authority(authority, transaction)
    if evidence.durable_runner_lkg_receipt_sha256 != receipt_sha256:
        raise TrustError("Runner publication evidence is not bound to verified durable authority")
    authorized = authorize_runner_publication(transaction, plan, evidence)
    if (lock_device, lock_inode) != (plan.lock_device, plan.lock_inode):
        raise TrustError("Runner lock identity changed before publication")
    expected = (
        plan.transaction_id,
        plan.candidate_revision,
        plan.candidate_capsule_sha256,
        plan.candidate_manifest_sha256,
        plan.service_sha256,
        plan.timer_sha256,
        plan.recovery_record_sha256,
    )
    actual = (
        evidence.transaction_id,
        evidence.candidate_revision,
        evidence.candidate_capsule_sha256,
        evidence.candidate_manifest_sha256,
        evidence.service_sha256,
        evidence.timer_sha256,
        evidence.recovery_record_sha256,
    )
    if actual != expected:
        raise TrustError("Runner publication evidence does not match staged artifacts")
    _verify_directory(stage_root, writable=False)
    service = _read_private_regular(stage_root / "runner.service")
    timer = _read_private_regular(stage_root / "runner.timer")
    if (_sha(service), _sha(timer)) != (plan.service_sha256, plan.timer_sha256):
        raise TrustError("Staged runner unit digest changed")
    if authorized.transaction_id != plan.transaction_id:
        raise TrustError("Runner publication authorization changed identity")
    unit_root.mkdir(mode=0o755, exist_ok=True)
    _verify_directory(unit_root, writable=False)
    journal_path = stage_root / "publication.journal.json"
    if journal_path.exists():
        raise TrustError("Interrupted runner publication requires recovery")
    journal: dict[str, object] = {
        "version": RUNNER_JOURNAL_VERSION,
        "transaction_id": plan.transaction_id,
        "candidate_revision": plan.candidate_revision,
        "candidate_capsule_sha256": plan.candidate_capsule_sha256,
        "candidate_manifest_sha256": plan.candidate_manifest_sha256,
        "service_sha256": plan.service_sha256,
        "timer_sha256": plan.timer_sha256,
        "recovery_record_sha256": plan.recovery_record_sha256,
        "apply_commit_evidence": evidence.apply_commit_evidence,
        "runner_lkg_commit_evidence": evidence.runner_lkg_commit_evidence,
        "durable_runner_lkg_receipt_sha256": evidence.durable_runner_lkg_receipt_sha256,
        "lock_device": plan.lock_device,
        "lock_inode": plan.lock_inode,
        "prior": {},
        "timer_changed": plan.timer_changed,
        "stage": "initializing",
    }
    _write_journal(journal_path, journal)
    _inject_failure(failure_hook, "initializing")
    prior = _capture_prior_pair(stage_root, unit_root)
    _inject_failure(failure_hook, "after-prior-capture")
    journal["prior"] = prior
    _advance_journal(journal_path, journal, "authorized")
    _inject_failure(failure_hook, "authorized")
    _inject_failure(failure_hook, "before-service-replace")
    _replace(unit_root / "runner.service", service)
    _inject_failure(failure_hook, "after-service-replace")
    _advance_journal(journal_path, journal, "service-published")
    _inject_failure(failure_hook, "service-published")
    _inject_failure(failure_hook, "before-timer-replace")
    _replace(unit_root / "runner.timer", timer)
    _sync_directory(unit_root)
    _inject_failure(failure_hook, "after-timer-replace")
    _verify_installed_pair(unit_root, plan)
    _advance_journal(journal_path, journal, "pair-published")
    _inject_failure(failure_hook, "pair-published")
    _inject_failure(failure_hook, "before-reload")
    reload_manager()
    _inject_failure(failure_hook, "after-reload")
    _advance_journal(journal_path, journal, "reloaded")
    _inject_failure(failure_hook, "reloaded")
    if plan.timer_changed:
        _inject_failure(failure_hook, "before-rearm")
        rearm_timer()
        _inject_failure(failure_hook, "after-rearm")
    _advance_journal(journal_path, journal, "rearmed")
    _inject_failure(failure_hook, "rearmed")
    _advance_journal(journal_path, journal, "committed")
    _inject_failure(failure_hook, "before-journal-unlink")
    journal_path.unlink()
    _sync_directory(stage_root)


def _recover_runner_publication(
    stage_root: Path,
    unit_root: Path,
    transaction: TransactionPlan,
    plan: RunnerUpdatePlan,
    evidence: RunnerPublicationEvidence,
    authority: VerifiedRunnerLkgAuthority,
    *,
    lock_device: int,
    lock_inode: int,
    reload_manager: Callable[[], None],
    rearm_timer: Callable[[], None],
    rearm_idempotent: bool,
) -> str:
    """Recover an interrupted publication from its durable prior pair and journal."""
    receipt_sha256 = validate_runner_lkg_authority(authority, transaction)
    if evidence.durable_runner_lkg_receipt_sha256 != receipt_sha256:
        raise TrustError("Runner recovery evidence is not bound to verified durable authority")
    authorize_runner_publication(transaction, plan, evidence)
    if (lock_device, lock_inode) != (plan.lock_device, plan.lock_inode):
        raise TrustError("Runner lock identity changed before recovery")
    journal_path = stage_root / "publication.journal.json"
    journal = _read_journal(journal_path)
    if (
        journal["transaction_id"] != plan.transaction_id
        or journal["candidate_revision"] != plan.candidate_revision
        or journal["candidate_capsule_sha256"] != plan.candidate_capsule_sha256
        or journal["candidate_manifest_sha256"] != plan.candidate_manifest_sha256
        or journal["service_sha256"] != plan.service_sha256
        or journal["timer_sha256"] != plan.timer_sha256
        or journal["recovery_record_sha256"] != plan.recovery_record_sha256
        or journal["apply_commit_evidence"] != evidence.apply_commit_evidence
        or journal["runner_lkg_commit_evidence"] != evidence.runner_lkg_commit_evidence
        or journal["durable_runner_lkg_receipt_sha256"]
        != evidence.durable_runner_lkg_receipt_sha256
        or journal["lock_device"] != lock_device
        or journal["lock_inode"] != lock_inode
    ):
        raise TrustError("Runner publication journal identity is mismatched")
    stage = str(journal["stage"])
    if stage == "initializing":
        journal["prior"] = _capture_prior_pair(stage_root, unit_root)
        _advance_journal(journal_path, journal, "authorized")
        stage = "authorized"
    if RUNNER_TRANSITIONS.index(stage) < RUNNER_TRANSITIONS.index("reloaded"):
        _verify_staged_pair(stage_root, plan)
        _restore_prior_pair(stage_root, unit_root, journal["prior"])
        reload_manager()
        result = "restored-prior-pair"
    else:
        _verify_installed_pair(unit_root, plan)
        if bool(journal["timer_changed"]) and stage == "reloaded":
            if not rearm_idempotent:
                raise TrustError("Runner timer rearm recovery is ambiguous")
            rearm_timer()
        result = "completed-published-pair"
    journal["stage"] = "committed"
    _write_journal(journal_path, journal)
    journal_path.unlink()
    _sync_directory(stage_root)
    return result


def _capture_prior_pair(stage_root: Path, unit_root: Path) -> dict[str, object]:
    """Durably retain the exact prior unit pair or explicit absence markers."""
    identities: dict[str, object] = {}
    for name in ("runner.service", "runner.timer"):
        source = unit_root / name
        prior = stage_root / f"prior.{name}"
        absent = stage_root / f"prior.{name}.absent"
        try:
            payload = _read_regular(source)
        except TrustError:
            if source.exists() or source.is_symlink():
                raise
        else:
            _ensure_prior_file(prior, payload)
            metadata = source.stat(follow_symlinks=False)
            identities[name] = {
                "present": True,
                "sha256": _sha(payload),
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "mode": stat.S_IMODE(metadata.st_mode),
            }
            continue
        _ensure_prior_file(absent, b"absent\n")
        identities[name] = {"present": False}
    _sync_directory(stage_root)
    return identities


def _ensure_prior_file(path: Path, payload: bytes) -> None:
    """Create one retained prior artifact or verify its exact retry value."""
    if path.exists() or path.is_symlink():
        if _read_private_regular(path) != payload:
            raise TrustError("Runner prior-pair initialization is inconsistent")
        return
    _write_new(path, payload)


def _restore_prior_pair(stage_root: Path, unit_root: Path, identities: object) -> None:
    """Restore both prior unit identities before reloading the manager."""
    if not isinstance(identities, dict):
        raise TrustError("Runner prior-pair identity is malformed")
    for name in ("runner.service", "runner.timer"):
        identity = identities.get(name)
        if not isinstance(identity, dict) or type(identity.get("present")) is not bool:
            raise TrustError("Runner prior-pair identity is malformed")
        prior = stage_root / f"prior.{name}"
        absent = stage_root / f"prior.{name}.absent"
        if identity["present"] and prior.exists() and not absent.exists():
            payload = _read_private_regular(prior)
            if _sha(payload) != identity.get("sha256"):
                raise TrustError("Runner prior-pair content is mismatched")
            target = unit_root / name
            _replace(target, payload)
            os.chown(target, int(identity["uid"]), int(identity["gid"]), follow_symlinks=False)
            os.chmod(target, int(identity["mode"]), follow_symlinks=False)
        elif not identity["present"] and absent.exists() and not prior.exists():
            (unit_root / name).unlink(missing_ok=True)
        else:
            raise TrustError("Runner prior-pair recovery evidence is inconsistent")
    _sync_directory(unit_root)


def _verify_staged_pair(stage_root: Path, plan: RunnerUpdatePlan) -> None:
    """Verify the exact staged candidate pair before any recovery action."""
    if (
        _sha(_read_private_regular(stage_root / "runner.service")) != plan.service_sha256
        or _sha(_read_private_regular(stage_root / "runner.timer")) != plan.timer_sha256
    ):
        raise TrustError("Staged runner pair is mismatched during recovery")


def _verify_installed_pair(unit_root: Path, plan: RunnerUpdatePlan) -> None:
    """Verify the exact installed candidate pair at a committed transition."""
    if (
        _sha(_read_regular(unit_root / "runner.service")) != plan.service_sha256
        or _sha(_read_regular(unit_root / "runner.timer")) != plan.timer_sha256
    ):
        raise TrustError("Installed runner pair is mismatched during recovery")


def _write_journal(path: Path, journal: dict[str, object]) -> None:
    """Atomically publish and sync the runner transition journal."""
    payload = (json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _replace(path, payload)
    _sync_directory(path.parent)


def _read_journal(path: Path) -> dict[str, object]:
    """Read and validate the closed versioned runner transition journal."""
    try:
        value = json.loads(_read_private_regular(path))
        required = {
            "version",
            "transaction_id",
            "candidate_revision",
            "candidate_capsule_sha256",
            "candidate_manifest_sha256",
            "service_sha256",
            "timer_sha256",
            "recovery_record_sha256",
            "apply_commit_evidence",
            "runner_lkg_commit_evidence",
            "durable_runner_lkg_receipt_sha256",
            "lock_device",
            "lock_inode",
            "prior",
            "timer_changed",
            "stage",
        }
        if (
            not isinstance(value, dict)
            or set(value) != required
            or value["version"] != RUNNER_JOURNAL_VERSION
            or value["stage"] not in RUNNER_TRANSITIONS
        ):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise TrustError("Runner publication journal is malformed") from exc
    return value


def _advance_journal(path: Path, journal: dict[str, object], stage: str) -> None:
    """Advance the runner journal by one monotonic transition."""
    current = str(journal["stage"])
    if RUNNER_TRANSITIONS.index(stage) != RUNNER_TRANSITIONS.index(current) + 1:
        raise TrustError("Runner publication transition is not monotonic")
    journal["stage"] = stage
    _write_journal(path, journal)


def _inject_failure(hook: Callable[[str], None] | None, stage: str) -> None:
    """Invoke an isolated-test failure point after a durable transition."""
    if hook is not None:
        hook(stage)


def _write_new(path: Path, payload: bytes) -> None:
    """Create and sync one new no-follow file."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise TrustError(f"Runner candidate write stalled: {path.name}")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace(path: Path, payload: bytes) -> None:
    """Atomically replace one unit file through a sibling temporary."""
    temporary = path.with_name(f".{path.name}.pending")
    if temporary.exists() or temporary.is_symlink():
        metadata = temporary.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise TrustError(f"Runner pending file has an unsafe type: {path.name}")
        temporary.unlink()
    _write_new(temporary, payload)
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    """Fsync one no-follow directory."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular(path: Path, *, require_private: bool = False) -> bytes:
    """Read one staged regular file without following a final link."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TrustError(f"Staged runner candidate cannot be opened: {path.name}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise TrustError(f"Staged runner candidate has an unsafe type: {path.name}")
        if require_private and (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise TrustError(f"Staged runner evidence has unsafe metadata: {path.name}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_private_regular(path: Path) -> bytes:
    """Read executor-owned mode-0600 staged evidence without following links."""
    return _read_regular(path, require_private=True)


def _sha(payload: bytes) -> str:
    """Calculate the immutable artifact identity."""
    return hashlib.sha256(payload).hexdigest()


def _verify_directory(path: Path, *, writable: bool) -> None:
    """Reject linked, foreign-owned, or unexpectedly writable directories."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TrustError(f"Runner directory cannot be opened safely: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        unsafe_mode = metadata.st_mode & 0o022 if not writable else 0
        if metadata.st_uid != os.geteuid() or metadata.st_gid != os.getegid() or unsafe_mode:
            raise TrustError(f"Runner directory ownership or mode is unsafe: {path}")
    finally:
        os.close(descriptor)


def _verify_private_directory(path: Path) -> None:
    """Require one executor-owned mode-0700 no-follow staging directory."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TrustError(f"Runner staging directory cannot be opened safely: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise TrustError(f"Runner staging directory ownership or mode is unsafe: {path}")
    finally:
        os.close(descriptor)
