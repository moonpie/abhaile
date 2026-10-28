"""Test broker credential refresh without invoking Podman or systemd."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import Mock

import pytest

import abhaile.cli.mosquitto_passwords as refresh
from abhaile.utils.errors import RenderError


@pytest.fixture
def accounts() -> list[dict[str, str]]:
    """Return synthetic staging accounts for tests."""
    return [
        {"username": name, "password": "{{ vault_placeholder_test }}"}
        for name in ("home-assistant", "zigbee2mqtt", "frigate")
    ]


@pytest.fixture
def ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid privileged ownership changes in temporary test directories."""
    monkeypatch.setattr(os, "chown", Mock())
    monkeypatch.setattr(os, "fchown", Mock())


class TestPasswordMaterial:
    """Validate staging inputs before any operational side effects."""

    @pytest.mark.parametrize("source", [b"not-json", b"\xff", b"{}", b"[]", b"[1,2,3]"])
    def test_invalid_structure(self, source: bytes) -> None:
        """Reject malformed JSON and account structures."""
        with pytest.raises(RenderError):
            refresh._password_lines(source)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("username", ""),
            ("username", "a:b"),
            ("username", "a\nb"),
            ("username", "a b"),
            ("username", "a\x00b"),
            ("username", None),
            ("password", ""),
            ("password", "a\nb"),
            ("password", "a\rb"),
            ("password", "a\x00b"),
            ("password", None),
        ],
    )
    def test_invalid_account(self, accounts: list[dict[str, Any]], field: str, value: Any) -> None:
        """Reject values that cannot safely become password-file records."""
        accounts[0][field] = value
        with pytest.raises(RenderError):
            refresh._password_lines(json.dumps(accounts).encode())

    def test_duplicate_user(self, accounts: list[dict[str, str]]) -> None:
        """Require a different username for each client."""
        accounts[1]["username"] = accounts[0]["username"]
        with pytest.raises(RenderError, match="distinct"):
            refresh._password_lines(json.dumps(accounts).encode())

    def test_missing_field(self, accounts: list[dict[str, str]]) -> None:
        """Fail closed when Vault staging lacks a required field."""
        del accounts[0]["password"]
        with pytest.raises(RenderError, match="fields"):
            refresh._password_lines(json.dumps(accounts).encode())


class TestPasswordRefresh:
    """Cover hashing isolation, installation, idempotence, and retry behaviour."""

    def test_install_and_unchanged_refresh(
        self,
        tmp_path: Path,
        accounts: list[dict[str, str]],
        ownership: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hash once, install protected files, and preserve them for unchanged inputs."""
        source = tmp_path / "staging.json"
        source.write_text(json.dumps(accounts))
        destination = tmp_path / "secrets/passwords"
        commands: list[list[str]] = []

        def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            assert kwargs["stdout"] == subprocess.DEVNULL
            assert kwargs["stderr"] == subprocess.DEVNULL
            if command[0] == "/usr/bin/podman":
                volume = command[command.index("--volume") + 1].split(":", 1)[0]
                path = Path(volume) / "passwords"
                assert "{{ vault_placeholder_test }}" in path.read_text()
                assert "{{ vault_placeholder_test }}" not in str(command)
                assert path.stat().st_mode & 0o777 == 0o600
                path.write_text("".join(f"{a['username']}:$7$synthetic\n" for a in accounts))
            return subprocess.CompletedProcess(command, 3 if "is-active" in command else 0)

        monkeypatch.setattr(refresh.subprocess, "run", run)
        assert refresh.refresh_passwords(
            source, destination, "image:1", group=1883, work_root=tmp_path
        )
        original = destination.read_bytes()
        assert destination.stat().st_mode & 0o777 == 0o640
        assert destination.parent.stat().st_mode & 0o777 == 0o750
        assert destination.with_name(".passwords.state").stat().st_mode & 0o777 == 0o600
        assert not refresh.refresh_passwords(
            source, destination, "image:1", group=1883, work_root=tmp_path
        )
        assert len(commands) == 2
        assert destination.read_bytes() == original
        assert not list(tmp_path.glob("abhaile-mqtt-*"))
        destination.write_bytes(b"corrupted")
        assert refresh.refresh_passwords(
            source, destination, "image:1", group=1883, work_root=tmp_path
        )
        assert destination.read_bytes() == original
        assert refresh.refresh_passwords(
            source, destination, "image:2", group=1883, work_root=tmp_path
        )

    @pytest.mark.parametrize("failure", ["conversion", "restart", "state-inspection", "install"])
    def test_failure_preserves_retry(
        self,
        tmp_path: Path,
        accounts: list[dict[str, str]],
        ownership: None,
        monkeypatch: pytest.MonkeyPatch,
        failure: str,
    ) -> None:
        """Preserve old credentials on conversion failure and never acknowledge failed updates."""
        source = tmp_path / "staging.json"
        source.write_text(json.dumps(accounts))
        destination = tmp_path / "passwords"
        destination.write_bytes(b"old-hashes")
        if failure == "conversion":
            monkeypatch.setattr(
                refresh, "_hashed_passwords", Mock(side_effect=RenderError("failed"))
            )
        else:
            monkeypatch.setattr(refresh, "_hashed_passwords", Mock(return_value=b"new-hashes"))
        if failure == "install":
            monkeypatch.setattr(refresh.os, "fsync", Mock(side_effect=OSError("failed")))
        runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        if failure == "restart":
            runner.side_effect = [
                subprocess.CompletedProcess([], 0),
                subprocess.CalledProcessError(1, []),
            ]
        elif failure == "state-inspection":
            runner.return_value = subprocess.CompletedProcess([], 1)
        monkeypatch.setattr(refresh.subprocess, "run", runner)
        with pytest.raises((OSError, RenderError, subprocess.SubprocessError)):
            refresh.refresh_passwords(
                source, destination, "image:1", group=1883, work_root=tmp_path
            )
        assert not destination.with_name(".passwords.state").exists()
        if failure in ("conversion", "install"):
            assert destination.read_bytes() == b"old-hashes"
        assert not list(tmp_path.glob(".passwords.*"))

    @pytest.mark.parametrize("failure", ["exit", "timeout", "unhashed", "encoding"])
    def test_converter_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
    ) -> None:
        """Reject failed or invalid converter output and remove temporary plaintext."""

        def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if failure == "exit":
                raise subprocess.CalledProcessError(1, command)
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 120)
            if failure == "encoding":
                volume = command[command.index("--volume") + 1].split(":", 1)[0]
                (Path(volume) / "passwords").write_bytes(b"\xff")
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(refresh.subprocess, "run", run)
        with pytest.raises(RenderError):
            refresh._hashed_passwords("test:{{ vault_placeholder_test }}\n", "image:1", tmp_path)
        assert not list(tmp_path.glob("abhaile-mqtt-*"))

    def test_active_restart(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Queue a restart for an already active broker."""
        runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        monkeypatch.setattr(refresh.subprocess, "run", runner)
        refresh._restart_running_broker()
        assert runner.call_count == 2
        assert "try-restart" in runner.call_args.args[0]

    @pytest.mark.parametrize("changed", [False, True])
    def test_cli_success(self, monkeypatch: pytest.MonkeyPatch, changed: bool) -> None:
        """Exit successfully for both changed and unchanged credentials."""
        monkeypatch.setattr(refresh, "refresh_passwords", Mock(return_value=changed))
        assert (
            refresh.main(["--source", "/unused", "--destination", "/unused", "--image", "image:1"])
            == 0
        )

    def test_cli_failure(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log a generic failure without echoing sensitive exception details."""
        monkeypatch.setattr(
            refresh, "refresh_passwords", Mock(side_effect=OSError("sensitive-detail"))
        )
        assert (
            refresh.main(["--source", "/unused", "--destination", "/unused", "--image", "image:1"])
            == 1
        )
        assert "sensitive-detail" not in caplog.text
