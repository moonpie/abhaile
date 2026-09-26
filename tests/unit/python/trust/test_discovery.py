"""Unit tests for metadata-only existing-host discovery."""

from __future__ import annotations

from pathlib import Path
import os
from typing import Mapping, Sequence

from abhaile.trust.discovery import (
    Classification,
    DiscoveryBackend,
    DiscoveryCommandResult,
    DiscoveryTarget,
    FixedDiscoveryBackend,
    MetadataObservation,
    Observation,
    Probe,
    ProbeKind,
    discover_existing_host,
    discover_typed_host,
    fixed_discovery_probes,
)


class SyntheticBackend(DiscoveryBackend):
    """Return predefined sanitized observations without host access."""

    def __init__(self, observations: dict[str, Observation | Exception]) -> None:
        self.observations = observations

    def observe(self, probe: Probe) -> Observation:
        """Return the observation keyed by the probe name."""
        result = self.observations[probe.name]
        if isinstance(result, Exception):
            raise result
        return result


def test_classifies_all_existing_host_states(tmp_path: Path) -> None:
    """Classify preservation, adoption, drift, conflict, and gated obsolete state."""
    prerequisite = tmp_path / "age.key"
    legacy = tmp_path / "applied.json"
    obsolete = tmp_path / "old.unit"
    conflict = tmp_path / "repo"
    prerequisite.write_text("not-read", encoding="utf-8")
    legacy.write_text("not-read", encoding="utf-8")
    obsolete.write_text("not-read", encoding="utf-8")
    conflict.symlink_to(legacy)
    records = discover_existing_host(
        [
            DiscoveryTarget("age identity", "identity", prerequisite, preserve=True),
            DiscoveryTarget("apply ledger", "state", legacy, legacy_managed=True),
            DiscoveryTarget("runner unit", "service", tmp_path / "missing"),
            DiscoveryTarget("repository", "repository", conflict),
            DiscoveryTarget("old unit", "service", obsolete, expected=False),
        ]
    )
    assert [record.classification for record in records] == [
        Classification.PREREQUISITE,
        Classification.LEGACY_MANAGED,
        Classification.DESIRED_DRIFT,
        Classification.CONFLICT,
        Classification.OBSOLETE,
    ]
    assert all(not hasattr(record, "content") for record in records)


def test_covers_required_existing_host_subsystems_without_reading_content(
    tmp_path: Path,
) -> None:
    """Classify synthetic metadata for every Phase 1 discovery subsystem."""
    categories = (
        "identity",
        "ownership",
        "ssh",
        "sudo",
        "repository",
        "mirror",
        "state",
        "runtime",
        "systemd",
        "quadlet",
        "vault",
        "networkd",
    )
    targets: list[DiscoveryTarget] = []
    for category in categories:
        path = tmp_path / category
        path.write_text("must-not-be-read", encoding="utf-8")
        targets.append(
            DiscoveryTarget(
                category,
                category,
                path,
                legacy_managed=True,
                expected_kind="file",
                expected_uid=os.geteuid(),
                expected_gid=os.getegid(),
                required_mode=path.stat().st_mode & 0o7777,
            )
        )
    records = discover_existing_host(targets)
    assert {record.category for record in records} == set(categories)
    assert all(record.classification is Classification.LEGACY_MANAGED for record in records)


def test_ambiguous_metadata_is_a_conflict(tmp_path: Path) -> None:
    """Fail closed when an observed type, owner, group, or mode is unexpected."""
    path = tmp_path / "sudoers"
    path.write_text("not-read", encoding="utf-8")
    path.chmod(0o644)
    records = discover_existing_host(
        [
            DiscoveryTarget(
                "sudo policy",
                "sudo",
                path,
                legacy_managed=True,
                expected_kind="file",
                expected_uid=os.geteuid(),
                expected_gid=os.getegid(),
                required_mode=0o440,
            )
        ]
    )
    assert records[0].classification is Classification.CONFLICT


def test_typed_discovery_covers_every_phase_one_subsystem() -> None:
    """Classify every required subsystem through an injected read-only backend."""
    probes = [
        Probe(kind.value, kind, f"synthetic:{kind.name}", legacy_managed=True) for kind in ProbeKind
    ]
    backend = SyntheticBackend(
        {
            probe.name: Observation(
                available=True,
                present=True,
                matches_expected=True,
                reason="metadata matches the declared adoption policy",
                provenance=f"fixture:{probe.kind.name}",
            )
            for probe in probes
        }
    )

    records = discover_typed_host(probes, backend)

    assert {record.kind for record in records} == set(ProbeKind)
    assert all(record.classification is Classification.LEGACY_MANAGED for record in records)
    assert all(record.reason and record.provenance for record in records)


def test_typed_discovery_reports_all_five_classifications() -> None:
    """Apply the adoption policy to complete synthetic evidence."""
    probes = [
        Probe("identity", ProbeKind.ACCOUNT_IDENTITY, "account:abhaile", preserve=True),
        Probe("ledger", ProbeKind.STATE_LEDGER, "ledger:legacy", legacy_managed=True),
        Probe("runtime", ProbeKind.RUNTIME, "runtime:podman"),
        Probe("obsolete", ProbeKind.SYSTEM_UNIT, "unit:old.service", expected=False),
        Probe("sudo", ProbeKind.EFFECTIVE_SUDO, "sudo:launcher"),
    ]
    backend = SyntheticBackend(
        {
            "identity": Observation(True, True, True, "identity exists", "fixture:identity"),
            "ledger": Observation(True, True, True, "ledger is recognized", "fixture:ledger"),
            "runtime": Observation(True, False, True, "runtime is absent", "fixture:runtime"),
            "obsolete": Observation(True, True, True, "old unit exists", "fixture:unit"),
            "sudo": Observation(True, True, False, "authorization differs", "fixture:sudo"),
        }
    )

    records = discover_typed_host(probes, backend)

    assert [record.classification for record in records] == [
        Classification.PREREQUISITE,
        Classification.LEGACY_MANAGED,
        Classification.DESIRED_DRIFT,
        Classification.OBSOLETE,
        Classification.CONFLICT,
    ]


def test_unavailable_malformed_and_backend_failure_fail_closed() -> None:
    """Treat unavailable, ambiguous, malformed, and failed probes as conflicts."""
    probes = [
        Probe("unavailable", ProbeKind.REPOSITORY_TRUST, "git:trusted"),
        Probe("ambiguous", ProbeKind.VAULT_PREREQUISITE, "vault:agent"),
        Probe("malformed", ProbeKind.NETWORKD, "network:links"),
        Probe("failed", ProbeKind.USER_UNIT, "unit:user"),
    ]
    backend = SyntheticBackend(
        {
            "unavailable": Observation(False, None, None, "probe unavailable", "fixture:git"),
            "ambiguous": Observation(True, True, None, "multiple owners observed", "fixture:vault"),
            "malformed": Observation(True, True, True, "", "fixture:network", valid=False),
            "failed": OSError("synthetic failure containing data that must not leak"),
        }
    )

    records = discover_typed_host(probes, backend)

    assert all(record.classification is Classification.CONFLICT for record in records)
    assert records[-1].reason == "evidence is unavailable or ambiguous"
    assert all("must not leak" not in record.reason for record in records)


def test_typed_report_cannot_carry_observed_or_secret_content() -> None:
    """Keep observation values and possible secret content out of reports."""
    probe = Probe("ssh", ProbeKind.REPOSITORY_TRUST, "ssh:origin")
    backend = SyntheticBackend(
        {
            "ssh": Observation(
                True,
                True,
                True,
                "pinned host metadata matches",
                "fixture:ssh-policy",
            )
        }
    )

    record = discover_typed_host([probe], backend)[0]

    assert not hasattr(record, "content")
    assert not hasattr(record, "value")
    assert record.subject == "ssh:origin"
    assert record.reason == "expected prerequisite is present"
    assert record.provenance == "backend:repository_trust"


class SyntheticCommandRunner:
    """Record fixed command execution and return synthetic bounded results."""

    def __init__(self, results: dict[tuple[str, ...], DiscoveryCommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str], float, int]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        max_output: int,
    ) -> DiscoveryCommandResult:
        """Return the result for an exact catalog command."""
        key = tuple(command)
        self.calls.append((key, env, timeout, max_output))
        return self.results[key]


def test_fixed_collectors_cover_catalog_with_bounded_shell_free_inputs(tmp_path: Path) -> None:
    """Collect every probe kind using only backend-selected commands and paths."""
    probes = fixed_discovery_probes()
    command_results = {
        ("/usr/bin/getent", "passwd", "abhaile"): DiscoveryCommandResult(
            0, "abhaile:x:1000:1000::/home/abhaile:/usr/sbin/nologin\n"
        ),
        (
            "/usr/bin/sudo",
            "-n",
            "-l",
            "-U",
            "abhaile",
        ): DiscoveryCommandResult(
            0,
            "User abhaile may run the following commands:\n"
            "    (root) NOPASSWD: /usr/local/sbin/abhaile-converge-launcher "
            "^--runner --host (deimos|phobos) --revision [0-9a-f]{40} "
            "--dry-run( --offline)?$\n",
        ),
        (
            "/usr/bin/git",
            f"--git-dir={tmp_path}/var/lib/abhaile/mirror.git",
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/abhaile/",
        ): DiscoveryCommandResult(0, f"refs/abhaile/trusted {'a' * 40}\n"),
        (
            "/usr/bin/loginctl",
            "show-user",
            "abhaile",
            "--property=Linger",
            "--value",
        ): DiscoveryCommandResult(0, "yes\n"),
    }
    runner = SyntheticCommandRunner(command_results)
    paths: list[tuple[Path, str, int | None]] = []

    def metadata(
        path: Path, *, expected_kind: str, expected_mode: int | None
    ) -> MetadataObservation:
        paths.append((path, expected_kind, expected_mode))
        return MetadataObservation(True, True, True)

    backend = FixedDiscoveryBackend(runner, metadata, filesystem_root=tmp_path)
    records = discover_typed_host(probes, backend)

    assert {record.kind for record in records} == set(ProbeKind)
    assert len(probes) > len(ProbeKind)
    assert len(runner.calls) == 4
    assert all(call[1]["PATH"] == "/usr/sbin:/usr/bin:/sbin:/bin" for call in runner.calls)
    assert all(call[2:] == (5.0, 65536) for call in runner.calls)
    assert len(paths) == 14
    assert (tmp_path / "etc/abhaile/known_hosts", "file", 0o600) in paths
    assert (tmp_path / "var/lib/abhaile/state/manifest.json", "file", None) in paths
    assert (
        tmp_path / "var/lib/abhaile/runner/last-successful-commit",
        "file",
        None,
    ) in paths
    assert (
        tmp_path / "home/abhaile/.config/containers/systemd/vault-agent.container",
        "file",
        None,
    ) in paths
    assert (
        tmp_path / "home/abhaile/.config/vault-agent",
        "directory",
        None,
    ) in paths
    assert (
        tmp_path / "home/abhaile/.local/share/containers/storage",
        "directory",
        None,
    ) in paths
    assert (
        tmp_path / "home/abhaile/.config/systemd/user",
        "directory",
        None,
    ) in paths
    assert not any(path == tmp_path / "etc/vault-agent.d" for path, _kind, _mode in paths)
    commands = " ".join(item for call in runner.calls for item in call[0])
    assert "podman" not in commands
    assert "runuser" not in commands
    assert not any(verb in commands for verb in (" apply ", " start ", " enable ", " restart "))


def test_fixed_backend_rejects_caller_selected_subject_without_execution() -> None:
    """Reject attempts to turn a catalog probe into caller-selected execution."""
    runner = SyntheticCommandRunner({})
    metadata_calls: list[Path] = []

    def metadata(
        path: Path, *, expected_kind: str, expected_mode: int | None
    ) -> MetadataObservation:
        metadata_calls.append(path)
        return MetadataObservation(
            True, True, expected_kind == "directory" and expected_mode is None
        )

    backend = FixedDiscoveryBackend(runner, metadata)
    probe = Probe("account identity", ProbeKind.ACCOUNT_IDENTITY, "account:root")

    record = discover_typed_host([probe], backend)[0]

    assert record.classification is Classification.CONFLICT
    assert runner.calls == []
    assert metadata_calls == []


def test_fixed_backend_fails_closed_without_leaking_command_failures() -> None:
    """Sanitize nonzero, truncated, oversized, malformed, and exceptional results."""
    probe = next(
        item for item in fixed_discovery_probes() if item.kind is ProbeKind.ACCOUNT_IDENTITY
    )
    command = ("/usr/bin/getent", "passwd", "abhaile")
    failures = [
        DiscoveryCommandResult(1, stderr="token=do-not-report"),
        DiscoveryCommandResult(0, "valid", truncated=True),
        DiscoveryCommandResult(0, "x" * 65537),
        DiscoveryCommandResult(0, "malformed secret-like value"),
    ]

    def metadata(
        path: Path, *, expected_kind: str, expected_mode: int | None
    ) -> MetadataObservation:
        del path
        return MetadataObservation(
            True, True, expected_kind == "directory" and expected_mode is None
        )

    for failure in failures:
        record = discover_typed_host(
            [probe], FixedDiscoveryBackend(SyntheticCommandRunner({command: failure}), metadata)
        )[0]
        assert record.classification is Classification.CONFLICT
        assert "token" not in record.reason
        assert "secret" not in record.reason


def test_fixed_sudo_parser_rejects_broad_or_additional_authorization() -> None:
    """Accept only the one constrained launcher rule and suppress listed content."""
    probe = next(item for item in fixed_discovery_probes() if item.kind is ProbeKind.EFFECTIVE_SUDO)
    command = ("/usr/bin/sudo", "-n", "-l", "-U", "abhaile")
    result = DiscoveryCommandResult(
        0,
        "User abhaile may run the following commands:\n"
        "    (root) NOPASSWD: /usr/local/sbin/abhaile-converge-launcher "
        "^--runner --host (deimos|phobos) --revision [0-9a-f]{40} "
        "--dry-run( --offline)?$\n"
        "    (ALL) NOPASSWD: ALL secret-token\n",
    )

    def metadata(
        path: Path, *, expected_kind: str, expected_mode: int | None
    ) -> MetadataObservation:
        del path
        return MetadataObservation(True, True, True)

    record = discover_typed_host(
        [probe], FixedDiscoveryBackend(SyntheticCommandRunner({command: result}), metadata)
    )[0]

    assert record.classification is Classification.CONFLICT
    assert "secret-token" not in record.reason
