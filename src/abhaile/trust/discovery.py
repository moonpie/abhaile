"""Collect metadata-only evidence for existing-host adoption."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol, Sequence


class Classification(str, Enum):
    """Describe how observed existing-host state may be handled."""

    PREREQUISITE = "prerequisite to preserve"
    LEGACY_MANAGED = "legacy-managed state suitable for adoption"
    DESIRED_DRIFT = "desired drift safe to reconcile"
    CONFLICT = "conflict requiring operator resolution"
    OBSOLETE = "obsolete state requiring prune/destructive approval"


class ProbeKind(str, Enum):
    """Identify the type of read-only evidence requested from a backend."""

    ACCOUNT_IDENTITY = "account identity"
    EFFECTIVE_SUDO = "effective sudo authorization"
    REPOSITORY_TRUST = "repository and SSH trust"
    STATE_LEDGER = "state ledger"
    RUNTIME = "runtime, user manager, and Podman"
    SYSTEM_UNIT = "system unit and Quadlet"
    USER_UNIT = "user unit and Quadlet"
    VAULT_PREREQUISITE = "Vault prerequisite metadata"
    NETWORKD = "systemd-networkd metadata"


@dataclass(frozen=True)
class Probe:
    """Describe one typed, read-only existing-host observation."""

    name: str
    kind: ProbeKind
    subject: str
    expected: bool = True
    preserve: bool = False
    legacy_managed: bool = False


@dataclass(frozen=True)
class Observation:
    """Hold sanitized evidence returned by a read-only discovery backend."""

    available: bool
    present: bool | None
    matches_expected: bool | None
    reason: str
    provenance: str
    valid: bool = True


class DiscoveryBackend(Protocol):
    """Provide injected, read-only observations for typed probes."""

    def observe(self, probe: Probe) -> Observation:
        """Return sanitized evidence without exposing secret content."""


@dataclass(frozen=True)
class DiscoveryCommandResult:
    """Capture bounded output from a shell-free discovery command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False


class DiscoveryCommandRunner(Protocol):
    """Run only a backend-selected command with fixed execution limits."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        max_output: int,
    ) -> DiscoveryCommandResult: ...


@dataclass(frozen=True)
class MetadataObservation:
    """Describe sanitized metadata for a backend-selected path."""

    available: bool
    present: bool | None
    matches_expected: bool | None
    valid: bool = True


class DiscoveryMetadataReader(Protocol):
    """Read metadata for a backend-selected fixed path without file content."""

    def __call__(
        self, path: Path, *, expected_kind: str, expected_mode: int | None
    ) -> MetadataObservation: ...


@dataclass(frozen=True)
class _CatalogEntry:
    """Bind a probe kind to one fixed command or metadata path."""

    name: str
    subject: str
    command: tuple[str, ...] | None = None
    path: Path | None = None
    expected_kind: str = "directory"
    expected_mode: int | None = None
    parser: str = "metadata"


_DISCOVERY_CATALOG = (
    _CatalogEntry(
        "account identity",
        "account:abhaile",
        ("/usr/bin/getent", "passwd", "abhaile"),
        parser="account",
    ),
    _CatalogEntry(
        "effective sudo",
        "sudo:constrained-launcher",
        ("/usr/bin/sudo", "-n", "-l", "-U", "abhaile"),
        parser="sudo",
    ),
    _CatalogEntry(
        "protected mirror", "repository:mirror", path=Path("/var/lib/abhaile/mirror.git")
    ),
    _CatalogEntry(
        "pinned host keys",
        "repository:known-hosts",
        path=Path("/etc/abhaile/known_hosts"),
        expected_kind="file",
        expected_mode=0o600,
    ),
    _CatalogEntry(
        "fetch identity",
        "repository:fetch-identity",
        path=Path("/etc/abhaile/git-fetch-identity"),
        expected_kind="file",
        expected_mode=0o600,
    ),
    _CatalogEntry(
        "protected refs",
        "repository:protected-refs",
        (
            "/usr/bin/git",
            "--git-dir={mirror}",
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/abhaile/",
        ),
        parser="refs",
    ),
    _CatalogEntry(
        "applied ledger",
        "state:applied",
        path=Path("/var/lib/abhaile/state/manifest.json"),
        expected_kind="file",
    ),
    _CatalogEntry(
        "runner ledger",
        "state:runner",
        path=Path("/var/lib/abhaile/runner/last-successful-commit"),
        expected_kind="file",
    ),
    _CatalogEntry(
        "user manager",
        "runtime:user-manager",
        ("/usr/bin/loginctl", "show-user", "abhaile", "--property=Linger", "--value"),
        parser="yes-no",
    ),
    _CatalogEntry(
        "container storage",
        "runtime:container-storage",
        path=Path("/home/abhaile/.local/share/containers/storage"),
    ),
    _CatalogEntry(
        "runner system unit",
        "system-unit:abhaile-runner.service",
        path=Path("/etc/systemd/system/abhaile-runner.service"),
        expected_kind="file",
    ),
    _CatalogEntry("system Quadlets", "system-unit:quadlets", path=Path("/etc/containers/systemd")),
    _CatalogEntry("user units", "user-unit:units", path=Path("/home/abhaile/.config/systemd/user")),
    _CatalogEntry(
        "user Quadlets",
        "user-unit:quadlets",
        path=Path("/home/abhaile/.config/containers/systemd"),
    ),
    _CatalogEntry(
        "Vault Agent unit",
        "vault:user-quadlet",
        path=Path("/home/abhaile/.config/containers/systemd/vault-agent.container"),
        expected_kind="file",
    ),
    _CatalogEntry(
        "Vault Agent config",
        "vault:user-config",
        path=Path("/home/abhaile/.config/vault-agent"),
    ),
    _CatalogEntry(
        "networkd unit",
        "networkd:unit",
        path=Path("/usr/lib/systemd/system/systemd-networkd.service"),
        expected_kind="file",
    ),
    _CatalogEntry("networkd config", "networkd:config", path=Path("/etc/systemd/network")),
)

_ENTRY_KINDS = (
    ProbeKind.ACCOUNT_IDENTITY,
    ProbeKind.EFFECTIVE_SUDO,
    ProbeKind.REPOSITORY_TRUST,
    ProbeKind.REPOSITORY_TRUST,
    ProbeKind.REPOSITORY_TRUST,
    ProbeKind.REPOSITORY_TRUST,
    ProbeKind.STATE_LEDGER,
    ProbeKind.STATE_LEDGER,
    ProbeKind.RUNTIME,
    ProbeKind.RUNTIME,
    ProbeKind.SYSTEM_UNIT,
    ProbeKind.SYSTEM_UNIT,
    ProbeKind.USER_UNIT,
    ProbeKind.USER_UNIT,
    ProbeKind.VAULT_PREREQUISITE,
    ProbeKind.VAULT_PREREQUISITE,
    ProbeKind.NETWORKD,
    ProbeKind.NETWORKD,
)

_DISCOVERY_ENV: Mapping[str, str] = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
}
_DISCOVERY_TIMEOUT = 5.0
_DISCOVERY_MAX_OUTPUT = 65536


def fixed_discovery_probes() -> list[Probe]:
    """Return the closed catalog of supported existing-host probes."""
    return [
        Probe(entry.name, kind, entry.subject, legacy_managed=True)
        for kind, entry in zip(_ENTRY_KINDS, _DISCOVERY_CATALOG)
    ]


class FixedDiscoveryBackend:
    """Collect bounded metadata through a closed command and path catalog."""

    def __init__(
        self,
        runner: DiscoveryCommandRunner,
        metadata_reader: DiscoveryMetadataReader,
        filesystem_root: Path = Path("/"),
    ) -> None:
        self.runner = runner
        self.metadata_reader = metadata_reader
        self.filesystem_root = filesystem_root

    def observe(self, probe: Probe) -> Observation:
        """Observe one catalog probe without accepting caller commands or paths."""
        entries = {
            (kind, entry.name, entry.subject): entry
            for kind, entry in zip(_ENTRY_KINDS, _DISCOVERY_CATALOG)
        }
        entry = entries.get((probe.kind, probe.name, probe.subject))
        if entry is None:
            return _invalid_observation(probe.kind)
        if entry.path is not None:
            return self._observe_metadata(probe.kind, entry)
        if entry.command is None:
            return _invalid_observation(probe.kind)
        try:
            command = tuple(
                item.format(mirror=str(self._fixed_path(Path("/var/lib/abhaile/mirror.git"))))
                for item in entry.command
            )
            result = self.runner(
                command,
                env=_DISCOVERY_ENV,
                timeout=_DISCOVERY_TIMEOUT,
                max_output=_DISCOVERY_MAX_OUTPUT,
            )
        except (OSError, TimeoutError, ValueError):
            return _invalid_observation(probe.kind)
        if (
            result.returncode != 0
            or result.truncated
            or len(result.stdout.encode("utf-8")) > _DISCOVERY_MAX_OUTPUT
            or len(result.stderr.encode("utf-8")) > _DISCOVERY_MAX_OUTPUT
        ):
            return _invalid_observation(probe.kind)
        parsed = _parse_command_observation(entry.parser, result.stdout)
        if parsed is None:
            return _invalid_observation(probe.kind)
        return Observation(True, parsed, True, "catalog probe completed", _provenance(probe.kind))

    def _observe_metadata(self, kind: ProbeKind, entry: _CatalogEntry) -> Observation:
        """Convert sanitized fixed-path metadata to an observation."""
        assert entry.path is not None
        try:
            result = self.metadata_reader(
                self._fixed_path(entry.path),
                expected_kind=entry.expected_kind,
                expected_mode=entry.expected_mode,
            )
        except (OSError, ValueError):
            return _invalid_observation(kind)
        if (
            not result.available
            or not result.valid
            or result.present is None
            or result.matches_expected is None
        ):
            return _invalid_observation(kind)
        return Observation(
            True,
            result.present,
            result.matches_expected,
            "fixed-path metadata collected",
            _provenance(kind),
        )

    def _fixed_path(self, path: Path) -> Path:
        """Map an absolute catalog path beneath an injected filesystem root."""
        return self.filesystem_root.joinpath(*path.relative_to("/").parts)


def _parse_command_observation(parser: str, output: str) -> bool | None:
    """Parse only bounded structural or enum output into a boolean."""
    value = output.strip()
    if parser == "account":
        fields = value.split(":")
        if len(fields) != 7 or fields[0] != "abhaile":
            return None
        if not fields[2].isdecimal() or not fields[3].isdecimal():
            return None
        return fields[5] == "/home/abhaile" and fields[6] in {"/usr/sbin/nologin", "/bin/false"}
    if parser == "sudo":
        rules = [line.strip() for line in value.splitlines() if line.lstrip().startswith("(")]
        expected = (
            "(root) NOPASSWD: /usr/local/sbin/abhaile-converge-launcher "
            "^--runner --host (deimos|phobos) --revision [0-9a-f]{40} "
            "--dry-run( --offline)?$"
        )
        return True if rules == [expected] else None
    if parser == "refs":
        lines = value.splitlines()
        if not lines:
            return False
        return True if all(_valid_ref_line(line) for line in lines) else None
    if parser == "yes-no":
        return True if value in {"yes", "no"} else None
    return None


def _valid_ref_line(line: str) -> bool:
    """Validate one sanitized protected-ref record structurally."""
    ref, separator, revision = line.partition(" ")
    return bool(
        separator
        and ref.startswith("refs/abhaile/")
        and len(revision) == 40
        and all(character in "0123456789abcdef" for character in revision)
    )


def _invalid_observation(kind: ProbeKind) -> Observation:
    """Return a fixed failure record that cannot leak command or file content."""
    return Observation(False, None, None, "catalog evidence unavailable", _provenance(kind), False)


def _provenance(kind: ProbeKind) -> str:
    """Return fixed provenance independent of observed content."""
    return f"fixed-catalog:{kind.name.lower()}"


@dataclass(frozen=True)
class TypedDiscoveryRecord:
    """Report a typed classification with sanitized evidence provenance."""

    name: str
    kind: ProbeKind
    subject: str
    classification: Classification
    reason: str
    provenance: str


@dataclass(frozen=True)
class DiscoveryTarget:
    """Describe one compatibility filesystem metadata probe."""

    name: str
    category: str
    path: Path
    expected: bool = True
    preserve: bool = False
    legacy_managed: bool = False
    expected_kind: str | None = None
    expected_uid: int | None = None
    expected_gid: int | None = None
    required_mode: int | None = None


@dataclass(frozen=True)
class DiscoveryRecord:
    """Report filesystem metadata without reading possibly secret file content."""

    name: str
    category: str
    path: str
    exists: bool
    kind: str | None
    uid: int | None
    gid: int | None
    mode: int | None
    classification: Classification


def discover_typed_host(
    probes: list[Probe], backend: DiscoveryBackend
) -> list[TypedDiscoveryRecord]:
    """Classify injected observations, failing closed on uncertain evidence."""
    records: list[TypedDiscoveryRecord] = []
    for probe in probes:
        try:
            observation = backend.observe(probe)
        except (OSError, ValueError) as exc:
            observation = Observation(
                available=False,
                present=None,
                matches_expected=None,
                reason=f"probe failed: {type(exc).__name__}",
                provenance="backend error",
            )
        classification, reason = _classify_observation(probe, observation)
        records.append(
            TypedDiscoveryRecord(
                name=probe.name,
                kind=probe.kind,
                subject=probe.subject,
                classification=classification,
                reason=reason,
                provenance=f"backend:{probe.kind.name.lower()}",
            )
        )
    return records


def _classify_observation(probe: Probe, observation: Observation) -> tuple[Classification, str]:
    """Classify only complete and unambiguous sanitized evidence."""
    if (
        not observation.available
        or not observation.valid
        or observation.present is None
        or observation.matches_expected is None
    ):
        return Classification.CONFLICT, "evidence is unavailable or ambiguous"
    if not observation.matches_expected:
        return Classification.CONFLICT, "evidence does not match the adoption policy"
    if probe.preserve and observation.present:
        return Classification.PREREQUISITE, "required prerequisite is present"
    if not probe.expected and observation.present:
        return Classification.OBSOLETE, "obsolete managed state is present"
    if probe.expected and not observation.present:
        return Classification.DESIRED_DRIFT, "expected state is absent"
    if probe.legacy_managed and observation.present:
        return Classification.LEGACY_MANAGED, "recognized legacy-managed state is present"
    if probe.expected and observation.present:
        return Classification.PREREQUISITE, "expected prerequisite is present"
    return Classification.CONFLICT, "evidence does not establish a safe classification"


def discover_existing_host(targets: list[DiscoveryTarget]) -> list[DiscoveryRecord]:
    """Inspect path metadata only and classify every observation fail closed."""
    records: list[DiscoveryRecord] = []
    for target in targets:
        try:
            metadata = target.path.lstat()
        except FileNotFoundError:
            records.append(_missing_path_record(target))
            continue
        unsafe = stat.S_ISLNK(metadata.st_mode)
        if unsafe:
            kind = "symlink"
        elif stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file"
        else:
            kind = "special"
            unsafe = True
        mode = stat.S_IMODE(metadata.st_mode)
        metadata_conflict = (
            (target.expected_kind is not None and kind != target.expected_kind)
            or (target.expected_uid is not None and metadata.st_uid != target.expected_uid)
            or (target.expected_gid is not None and metadata.st_gid != target.expected_gid)
            or (target.required_mode is not None and mode != target.required_mode)
        )
        records.append(
            DiscoveryRecord(
                target.name,
                target.category,
                str(target.path),
                True,
                kind,
                metadata.st_uid,
                metadata.st_gid,
                mode,
                _classify_path(target, exists=True, unsafe=unsafe or metadata_conflict),
            )
        )
    return records


def _missing_path_record(target: DiscoveryTarget) -> DiscoveryRecord:
    """Build a compatibility record for an absent path."""
    return DiscoveryRecord(
        target.name,
        target.category,
        str(target.path),
        False,
        None,
        None,
        None,
        None,
        _classify_path(target, exists=False, unsafe=False),
    )


def _classify_path(target: DiscoveryTarget, *, exists: bool, unsafe: bool) -> Classification:
    if unsafe:
        return Classification.CONFLICT
    if target.preserve and exists:
        return Classification.PREREQUISITE
    if not target.expected and exists:
        return Classification.OBSOLETE
    if target.expected and not exists:
        return Classification.DESIRED_DRIFT
    if target.legacy_managed and exists:
        return Classification.LEGACY_MANAGED
    if target.expected and exists:
        return Classification.PREREQUISITE
    return Classification.CONFLICT
